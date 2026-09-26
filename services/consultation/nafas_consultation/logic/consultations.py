"""Consultation rows, in the doctor's scope: row-level security shows a doctor only their own."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nafas_consultation.enums import ConsultationStatus
from nafas_consultation.exceptions import ConsultationNotFoundError, WrongStateError
from nafas_consultation.models import Consultation
from nafas_core.interfaces.storage.base import patient_key
from nafas_core.metrics import VISIT_NOTES

# what MediaRecorder produces in the browsers we support, and what the stt service reads
AUDIO_TYPES = {"audio/webm": "webm", "audio/ogg": "ogg", "audio/mp4": "m4a", "audio/mpeg": "mp3", "audio/wav": "wav"}
MAX_PART_BYTES = 20_000_000
# about three hours in one-minute parts: a visit, not a day
MAX_PARTS = 180


def base_mime(mime: str) -> str:
    """ "audio/webm;codecs=opus" is audio/webm."""
    return mime.split(";")[0].strip().lower()


def part_key(c: Consultation, index: int, mime: str) -> str:
    return patient_key(c.doctor_id, c.patient_id, "consultations", str(c.id), f"part-{index:04d}.{AUDIO_TYPES[mime]}")


async def create(
    session: AsyncSession,
    *,
    doctor_id: uuid.UUID,
    patient_id: uuid.UUID,
    consent_id: uuid.UUID,
    appointment_id: uuid.UUID | None = None,
) -> Consultation:
    consultation = Consultation(doctor_id=doctor_id, patient_id=patient_id, consent_id=consent_id, appointment_id=appointment_id)
    session.add(consultation)
    await session.flush()
    return consultation


async def get(session: AsyncSession, consultation_id: uuid.UUID) -> Consultation:
    consultation = await session.get(Consultation, consultation_id)
    if consultation is None:
        raise ConsultationNotFoundError(str(consultation_id))
    return consultation


def require(consultation: Consultation, *allowed: ConsultationStatus) -> None:
    if consultation.status not in allowed:
        raise WrongStateError(f"the consultation is {consultation.status.value}")


async def add_part(
    session: AsyncSession, consultation: Consultation, *, index: int, mime: str, offset_seconds: float, size_bytes: int
) -> dict:
    """Where the browser uploads part `index`; sending the same index again replaces it (a retried upload)."""
    require(consultation, ConsultationStatus.RECORDING)
    mime = base_mime(mime)
    if mime not in AUDIO_TYPES:
        raise ValueError(f"{mime} is not an audio type Nafas records")
    if not 0 < size_bytes <= MAX_PART_BYTES:
        raise ValueError(f"a part must be between 1 byte and {MAX_PART_BYTES} bytes")
    if not 0 <= index < MAX_PARTS:
        raise ValueError(f"a recording has at most {MAX_PARTS} parts")
    part = {"index": index, "mime": mime, "offset_seconds": float(offset_seconds), "key": part_key(consultation, index, mime)}
    # reassigned, not changed in place, so the JSONB column is written
    consultation.parts = sorted([p for p in consultation.parts if p["index"] != index] + [part], key=lambda p: p["index"])
    await session.flush()
    return part


async def for_patient(session: AsyncSession, patient_id: uuid.UUID) -> list[Consultation]:
    query = select(Consultation).where(Consultation.patient_id == patient_id).order_by(Consultation.created_at.desc())
    return list((await session.scalars(query)).all())


async def awaiting_review(session: AsyncSession) -> list[Consultation]:
    """This doctor's drafts waiting for them, oldest first."""
    query = select(Consultation).where(Consultation.status == ConsultationStatus.DRAFT_READY).order_by(Consultation.created_at)
    return list((await session.scalars(query)).all())


def mark(consultation: Consultation, status: ConsultationStatus, error: str | None = None) -> None:
    consultation.status = status
    consultation.error = error
    if status is ConsultationStatus.APPROVED:
        consultation.approved_at = datetime.now(UTC)


def forget(consultation: Consultation) -> list[str]:
    """A discarded recording keeps no words: its transcript and drafts go, and the caller deletes the audio keys returned."""
    keys = [p["key"] for p in consultation.parts]
    VISIT_NOTES.labels("discarded").inc()
    consultation.transcript = None
    consultation.draft = None
    consultation.approved = None
    mark(consultation, ConsultationStatus.DISCARDED)
    return keys

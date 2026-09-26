"""
Online visits: who may join a room and when, and how a recorded track
becomes a part of the visit. Framework-free, beside the rows it reads.
"""

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nafas_consultation.enums import ConsultationStatus
from nafas_consultation.models import Consultation
from nafas_consultation.rooms import Track, speaker_of
from nafas_core.interfaces.storage.base import patient_key

# a room opens a little before its visit and stays open a while after, for one that runs late
JOIN_EARLY = timedelta(minutes=15)
JOIN_LATE = timedelta(minutes=30)
# LiveKit's names for how a track's recording ended; a file was written for these
WRITTEN = {"EGRESS_COMPLETE", "EGRESS_LIMIT_REACHED"}


def join_refusal(appointment: dict, now: datetime) -> str | None:
    """Why this appointment's room cannot be joined now; None when it can."""
    if appointment["mode"] != "online":
        return "not_online"
    if appointment["status"] != "confirmed":
        return "not_confirmed"
    start, end = datetime.fromisoformat(appointment["start"]), datetime.fromisoformat(appointment["end"])
    if now < start - JOIN_EARLY:
        return "too_early"
    if now > end + JOIN_LATE:
        return "too_late"
    return None


def new_part(consultation: Consultation, track: Track, egress_id: str, now: datetime) -> dict:
    """A track being recorded, as a part of the visit: its speaker, its file, its time from the recording's start."""
    speaker = speaker_of(track.identity) or "unknown"
    index = len(consultation.parts)
    key = patient_key(
        consultation.doctor_id, consultation.patient_id, "consultations", str(consultation.id), f"{index:02d}-{speaker}.ogg"
    )
    return {
        "index": index,
        "mime": "audio/ogg",
        "offset_seconds": round(max((now - consultation.started_at).total_seconds(), 0.0), 2),
        "key": key,
        "speaker": speaker,
        "track_sid": track.track_sid,
        "egress_id": egress_id,
        "state": "recording",
    }


def still_writing(consultation: Consultation) -> bool:
    return any(p.get("state") == "recording" for p in consultation.parts)


def mark_part(consultation: Consultation, egress_id: str, status: str) -> bool:
    """Records how a track's recording ended; False when this visit has no such track."""
    found = False
    parts = []
    for part in consultation.parts:
        if part.get("egress_id") == egress_id:
            part = part | {"state": "written" if status in WRITTEN else "failed"}
            found = True
        parts.append(part)
    # reassigned, not changed in place, so the JSONB column is written
    consultation.parts = parts
    return found


async def recording_in(session: AsyncSession, room: str) -> Consultation | None:
    """The visit being recorded in this room, stopped or not, until it is processed."""
    return await session.scalar(
        select(Consultation)
        .where(Consultation.room == room, Consultation.status == ConsultationStatus.RECORDING)
        .order_by(Consultation.created_at.desc())
        .limit(1)
    )

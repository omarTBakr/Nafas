"""
A patient's consents, in the patient's own scope.

Granting is idempotent (a second grant of what is already in force returns
it), revoking ends a consent without deleting it, and "in force" means
granted and not revoked: the history stays, as evidence must.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nafas_identity.enums import ConsentKind
from nafas_identity.exceptions import ConsentNotFoundError
from nafas_identity.models import Consent

PLATFORM_WIDE = {ConsentKind.DATA_PROCESSING}


def _check_shape(kind: ConsentKind, doctor_id: uuid.UUID | None) -> None:
    if (kind in PLATFORM_WIDE) != (doctor_id is None):
        raise ValueError(f"{kind.value} consent is {'platform-wide' if kind in PLATFORM_WIDE else 'given to one doctor'}")


async def in_force(session: AsyncSession, patient_id: uuid.UUID) -> list[Consent]:
    return list(
        (
            await session.scalars(
                select(Consent).where(Consent.patient_id == patient_id, Consent.revoked_at.is_(None)).order_by(Consent.granted_at)
            )
        ).all()
    )


async def grant(
    session: AsyncSession,
    *,
    patient_id: uuid.UUID,
    kind: ConsentKind,
    doctor_id: uuid.UUID | None = None,
    evidence: str | None = None,
) -> Consent:
    _check_shape(kind, doctor_id)
    for consent in await in_force(session, patient_id):
        if consent.kind is kind and consent.doctor_id == doctor_id:
            return consent

    consent = Consent(patient_id=patient_id, doctor_id=doctor_id, kind=kind, evidence=evidence)
    session.add(consent)
    await session.flush()
    return consent


async def revoke(session: AsyncSession, patient_id: uuid.UUID, consent_id: uuid.UUID, now: datetime | None = None) -> Consent:
    consent = await session.get(Consent, consent_id)
    if consent is None or consent.patient_id != patient_id:
        raise ConsentNotFoundError(str(consent_id))
    if consent.revoked_at is None:
        consent.revoked_at = now or datetime.now(UTC)
        await session.flush()
    return consent


async def may_chat(session: AsyncSession, patient_id: uuid.UUID, doctor_id: uuid.UUID) -> bool:
    """Both in force: data processing, and AI chat with this doctor."""
    kinds = {(c.kind, c.doctor_id) for c in await in_force(session, patient_id)}
    return (ConsentKind.DATA_PROCESSING, None) in kinds and (ConsentKind.AI_CHAT, doctor_id) in kinds


async def record_session_recording(
    session: AsyncSession, *, patient_id: uuid.UUID, doctor_id: uuid.UUID, evidence: str
) -> Consent:
    """
    Consent to record one session, taken in the room and recorded by the doctor
    (their scope). Always a new row: consent to record is asked afresh for
    every recording, never carried over from an earlier one.
    """
    consent = Consent(patient_id=patient_id, doctor_id=doctor_id, kind=ConsentKind.SESSION_RECORDING, evidence=evidence)
    session.add(consent)
    await session.flush()
    return consent

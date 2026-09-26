import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from nafas_core.enums.channel import Channel
from nafas_core.enums.identity import Language
from nafas_identity.enums import ConsentKind
from nafas_identity.models import Consent, DoctorPatient, Patient, PatientChannel


async def register_patient(
    session: AsyncSession,
    *,
    doctor_id: uuid.UUID,
    full_name: str,
    channel: Channel,
    external_id: str,
    preferred_language: Language = Language.ARABIC,
    phone: str | None = None,
) -> Patient:
    """
    A new patient, reachable on one channel, under one doctor's care.

    All three rows go in one transaction, which must be scoped to `doctor_id`
    (session_scope(doctor_id=...)): row-level security lets anyone insert a
    patient, but only the link to this doctor makes the patient visible.
    """
    patient = Patient(full_name=full_name, preferred_language=preferred_language, phone=phone)
    session.add(patient)
    await session.flush()

    session.add(PatientChannel(patient_id=patient.id, channel=channel, external_id=external_id))
    session.add(DoctorPatient(doctor_id=doctor_id, patient_id=patient.id))
    await session.flush()

    return patient


async def record_consent(
    session: AsyncSession,
    *,
    doctor_id: uuid.UUID,
    patient_id: uuid.UUID,
    kind: ConsentKind,
    channel: Channel | None = None,
    evidence: str | None = None,
) -> Consent:
    consent = Consent(doctor_id=doctor_id, patient_id=patient_id, kind=kind, channel=channel, evidence=evidence)
    session.add(consent)
    await session.flush()

    return consent

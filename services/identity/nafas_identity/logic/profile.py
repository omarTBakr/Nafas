import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from nafas_core.enums.dialect import SpokenDialect, VoiceGender
from nafas_core.enums.identity import Language
from nafas_identity.models import Patient

# a value that means "leave this field as it is", distinct from None ("clear it")
UNCHANGED = object()


@dataclass
class PatientProfile:
    patient_id: uuid.UUID
    full_name: str
    phone: str | None
    preferred_language: Language
    dialect: SpokenDialect | None
    voice: VoiceGender | None
    email: str | None = None
    email_notices: bool = True


def _profile(patient: Patient) -> PatientProfile:
    return PatientProfile(
        patient_id=patient.id,
        full_name=patient.full_name,
        phone=patient.phone,
        preferred_language=patient.preferred_language,
        dialect=patient.dialect,
        voice=patient.voice,
        email=patient.email,
        email_notices=patient.email_notices,
    )


async def get_profile(session: AsyncSession, patient_id: uuid.UUID) -> PatientProfile | None:
    """The patient's profile; needs their own scope (or a linked doctor's), else None."""
    patient = await session.get(Patient, patient_id)
    return _profile(patient) if patient else None


async def update_profile(session: AsyncSession, patient_id: uuid.UUID, **changes) -> PatientProfile | None:
    """
    Applies the given fields, in the patient's own scope: row-level security
    lets a patient update only their own row. Fields left out are untouched.
    """
    patient = await session.get(Patient, patient_id)
    if patient is None:
        return None

    for field in ("full_name", "phone", "preferred_language", "dialect", "voice", "email_notices"):
        value = changes.get(field, UNCHANGED)
        if value is not UNCHANGED:
            setattr(patient, field, value)
    await session.flush()

    return _profile(patient)

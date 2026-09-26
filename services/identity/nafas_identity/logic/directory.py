import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from nafas_identity.enums import CareStatus
from nafas_identity.models import Doctor, DoctorPatient, Specialization, User


@dataclass
class DoctorCard:
    """What a patient sees when choosing a doctor: no account details, nothing about other patients."""

    doctor_id: uuid.UUID
    full_name_en: str
    full_name_ar: str
    specialization_code: str
    specialization_en: str
    specialization_ar: str
    languages: list[str]


async def list_specializations(session: AsyncSession) -> list[Specialization]:
    return list((await session.scalars(select(Specialization).order_by(Specialization.name_en))).all())


async def list_doctors(
    session: AsyncSession, specialization_code: str | None = None, doctor_id: uuid.UUID | None = None
) -> list[DoctorCard]:
    """Doctors whose accounts are active, optionally of one specialization."""
    query = (
        select(Doctor, Specialization)
        .join(Specialization, Doctor.specialization_id == Specialization.id)
        .join(User, Doctor.user_id == User.id)
        .where(User.is_active.is_(True))
        .order_by(Doctor.full_name_en)
    )
    if specialization_code:
        query = query.where(Specialization.code == specialization_code)
    if doctor_id:
        query = query.where(Doctor.id == doctor_id)

    return [
        DoctorCard(
            doctor_id=doctor.id,
            full_name_en=doctor.full_name_en,
            full_name_ar=doctor.full_name_ar,
            specialization_code=spec.code,
            specialization_en=spec.name_en,
            specialization_ar=spec.name_ar,
            languages=list(doctor.languages),
        )
        for doctor, spec in (await session.execute(query)).all()
    ]


async def ensure_care_link(session: AsyncSession, doctor_id: uuid.UUID, patient_id: uuid.UUID) -> None:
    """
    Puts the patient under the doctor's care, if they are not already.

    Must run in the doctor's scope: the row-level security check only lets a
    doctor create a link to themself. Idempotent, so every booking may call it.
    """
    await session.execute(insert(DoctorPatient).values(doctor_id=doctor_id, patient_id=patient_id).on_conflict_do_nothing())


async def under_care(session: AsyncSession, doctor_id: uuid.UUID, patient_id: uuid.UUID) -> bool:
    """An active care link between them; read in the patient's scope, where their own links are visible."""
    status = await session.scalar(
        select(DoctorPatient.status).where(DoctorPatient.doctor_id == doctor_id, DoctorPatient.patient_id == patient_id)
    )
    return status is CareStatus.ACTIVE


async def doctor_scope(session: AsyncSession, doctor_id: uuid.UUID) -> Specialization | None:
    """The specialization a doctor practises, with the boundary the scope gate reads."""
    return await session.scalar(
        select(Specialization).join(Doctor, Doctor.specialization_id == Specialization.id).where(Doctor.id == doctor_id)
    )

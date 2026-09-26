import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from nafas_core.enums.identity import Language, UserRole
from nafas_identity.exceptions import AccountExistsError, UnknownSpecializationError
from nafas_identity.logic.passwords import DUMMY_HASH, hash_password, needs_rehash, verify_password
from nafas_identity.models import Doctor, Patient, Specialization, User


@dataclass
class AuthenticatedUser:
    user_id: uuid.UUID
    email: str
    role: UserRole
    # exactly one is set for a doctor's or a patient's account; each is what
    # scopes that person's data (session_scope(doctor_id=...) or (patient_id=...))
    doctor_id: uuid.UUID | None
    patient_id: uuid.UUID | None = None


async def _email_taken(session: AsyncSession, email: str) -> bool:
    return (await session.scalar(select(User.id).where(func.lower(User.email) == email.lower()))) is not None


async def create_doctor_account(
    session: AsyncSession,
    *,
    email: str,
    password: str,
    full_name_en: str,
    full_name_ar: str,
    specialization_code: str,
) -> Doctor:
    """
    A dashboard account and the doctor behind it, created together.

    Accounts are made by an admin (the CLI), never by sign-up: a doctor on
    Nafas is someone the operator has checked. They take bookings once the
    scheduling service has their hours (`nafas_scheduling.cli`).
    """
    if await _email_taken(session, email):
        raise AccountExistsError(f"an account for {email} already exists")

    specialization_id = await session.scalar(select(Specialization.id).where(Specialization.code == specialization_code))
    if specialization_id is None:
        raise UnknownSpecializationError(f"no specialization {specialization_code!r}")

    user = User(email=email, password_hash=hash_password(password), role=UserRole.DOCTOR)
    session.add(user)
    await session.flush()

    doctor = Doctor(
        user_id=user.id,
        full_name_en=full_name_en,
        full_name_ar=full_name_ar,
        specialization_id=specialization_id,
    )
    session.add(doctor)
    await session.flush()

    return doctor


async def register_patient_account(
    session: AsyncSession,
    *,
    email: str,
    password: str,
    full_name: str,
    preferred_language: Language = Language.ARABIC,
    phone: str | None = None,
) -> AuthenticatedUser:
    """
    Self sign-up: a patient's login and their patient record, together.

    The patient belongs to no doctor yet; the care link is made when they
    first book (scheduling asks identity for it).
    """
    if await _email_taken(session, email):
        raise AccountExistsError(f"an account for {email} already exists")

    user = User(email=email, password_hash=hash_password(password), role=UserRole.PATIENT)
    session.add(user)
    await session.flush()

    patient = Patient(user_id=user.id, full_name=full_name, email=email, preferred_language=preferred_language, phone=phone)
    session.add(patient)
    await session.flush()

    return AuthenticatedUser(user_id=user.id, email=user.email, role=user.role, doctor_id=None, patient_id=patient.id)


async def _person_ids(session: AsyncSession, user: User) -> tuple[uuid.UUID | None, uuid.UUID | None]:
    """(doctor_id, patient_id) behind an account."""
    if user.role is UserRole.DOCTOR:
        return await session.scalar(select(Doctor.id).where(Doctor.user_id == user.id)), None
    if user.role is UserRole.PATIENT:
        # patients are hidden by RLS until a patient scope exists; this
        # security-definer function answers only "which patient is this account"
        patient_id = await session.scalar(text("SELECT identity.patient_id_for_user(:user)"), {"user": user.id})
        return None, patient_id

    return None, None


async def authenticate(session: AsyncSession, email: str, password: str) -> AuthenticatedUser | None:
    """
    The account for these credentials, or None — the same None for an unknown
    email, a wrong password and a disabled account, so a caller cannot tell
    which and neither can an attacker.
    """
    user = await session.scalar(select(User).where(func.lower(User.email) == email.lower()))

    if user is None:
        verify_password(DUMMY_HASH, password)
        return None

    if not verify_password(user.password_hash, password) or not user.is_active:
        return None

    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    user.last_login_at = datetime.now(UTC)

    doctor_id, patient_id = await _person_ids(session, user)

    return AuthenticatedUser(user_id=user.id, email=user.email, role=user.role, doctor_id=doctor_id, patient_id=patient_id)


async def get_user(session: AsyncSession, user_id: uuid.UUID) -> AuthenticatedUser | None:
    """An active account by id; for checking a session is still valid."""
    user = await session.get(User, user_id)
    if user is None or not user.is_active:
        return None

    doctor_id, patient_id = await _person_ids(session, user)

    return AuthenticatedUser(user_id=user.id, email=user.email, role=user.role, doctor_id=doctor_id, patient_id=patient_id)

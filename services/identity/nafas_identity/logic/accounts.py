import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nafas_core.enums.identity import UserRole
from nafas_core.exceptions.config import InvalidSettingError
from nafas_identity.exceptions import AccountExistsError, UnknownSpecializationError
from nafas_identity.logic.passwords import DUMMY_HASH, hash_password, needs_rehash, verify_password
from nafas_identity.models import Doctor, Specialization, User


@dataclass
class AuthenticatedUser:
    user_id: uuid.UUID
    email: str
    role: UserRole
    # set when the account is a doctor's, which is what scopes their data
    doctor_id: uuid.UUID | None


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
    timezone: str = "Africa/Cairo",
    default_slot_minutes: int = 20,
) -> Doctor:
    """
    A dashboard account and the doctor behind it, created together.

    Accounts are made by an admin (the CLI), never by sign-up: a doctor on
    Nafas is someone the operator has checked.
    """
    if await _email_taken(session, email):
        raise AccountExistsError(f"an account for {email} already exists")

    specialization_id = await session.scalar(select(Specialization.id).where(Specialization.code == specialization_code))
    if specialization_id is None:
        raise UnknownSpecializationError(f"no specialization {specialization_code!r}")

    try:
        ZoneInfo(timezone)
    except ZoneInfoNotFoundError as exc:
        raise InvalidSettingError(f"{timezone!r} is not an IANA time zone") from exc

    user = User(email=email, password_hash=hash_password(password), role=UserRole.DOCTOR)
    session.add(user)
    await session.flush()

    doctor = Doctor(
        user_id=user.id,
        full_name_en=full_name_en,
        full_name_ar=full_name_ar,
        specialization_id=specialization_id,
        timezone=timezone,
        default_slot_minutes=default_slot_minutes,
    )
    session.add(doctor)
    await session.flush()

    return doctor


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

    doctor_id = await session.scalar(select(Doctor.id).where(Doctor.user_id == user.id))

    return AuthenticatedUser(user_id=user.id, email=user.email, role=user.role, doctor_id=doctor_id)


async def get_user(session: AsyncSession, user_id: uuid.UUID) -> AuthenticatedUser | None:
    """An active account by id; for checking a session is still valid."""
    user = await session.get(User, user_id)
    if user is None or not user.is_active:
        return None

    doctor_id = await session.scalar(select(Doctor.id).where(Doctor.user_id == user.id))

    return AuthenticatedUser(user_id=user.id, email=user.email, role=user.role, doctor_id=doctor_id)

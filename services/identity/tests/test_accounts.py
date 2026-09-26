import pytest
from sqlalchemy import select, update

from nafas_core.db import session_scope
from nafas_core.enums.identity import UserRole
from nafas_identity.exceptions import AccountExistsError, UnknownSpecializationError
from nafas_identity.logic.accounts import authenticate, create_doctor_account, get_user
from nafas_identity.logic.seed import seed_specializations
from nafas_identity.models import Specialization, User
from nafas_identity.specializations import SPECIALIZATIONS

from .conftest import PASSWORD


async def test_seeding_is_idempotent_and_applies_edits(database):
    async with session_scope() as session:
        assert await seed_specializations(session) == (len(SPECIALIZATIONS), 0)
    async with session_scope() as session:
        assert await seed_specializations(session) == (0, len(SPECIALIZATIONS))
        cardiology = await session.scalar(select(Specialization).where(Specialization.code == "cardiology"))

    assert cardiology.name_ar == "قلب وأوعية دموية"
    assert "chest pain or pressure" in cardiology.always_escalate


async def test_login_returns_the_doctor_behind_the_account(two_doctors):
    heart_id, _ = two_doctors

    async with session_scope() as session:
        # the address as typed differently from how it was registered
        user = await authenticate(session, "HEART@example.com", PASSWORD)

    assert user.role is UserRole.DOCTOR
    assert user.doctor_id == heart_id


@pytest.mark.parametrize(
    ("email", "password"),
    [("heart@example.com", "wrong password here"), ("nobody@example.com", PASSWORD)],
)
async def test_bad_credentials_all_look_the_same(two_doctors, email, password):
    async with session_scope() as session:
        assert await authenticate(session, email, password) is None


async def test_a_disabled_account_cannot_log_in_or_keep_its_session(two_doctors):
    async with session_scope() as session:
        user = await authenticate(session, "heart@example.com", PASSWORD)
        await session.execute(update(User).where(User.id == user.user_id).values(is_active=False))

    async with session_scope() as session:
        assert await authenticate(session, "heart@example.com", PASSWORD) is None
        assert await get_user(session, user.user_id) is None


async def test_one_account_per_email_whatever_the_case(two_doctors):
    with pytest.raises(AccountExistsError):
        async with session_scope() as session:
            await create_doctor_account(
                session,
                email="Heart@Example.com",
                password=PASSWORD,
                full_name_en="Dr Copy",
                full_name_ar="د. نسخة",
                specialization_code="cardiology",
            )


async def test_a_doctor_needs_a_known_specialization(database):
    with pytest.raises(UnknownSpecializationError):
        async with session_scope() as session:
            await create_doctor_account(
                session,
                email="x@example.com",
                password=PASSWORD,
                full_name_en="Dr X",
                full_name_ar="د. س",
                specialization_code="astrology",
            )


async def test_a_disabled_account_cannot_log_in_and_can_be_enabled_again(two_doctors):
    from nafas_identity.logic.accounts import authenticate, set_active

    async with session_scope() as session:
        assert await set_active(session, " Heart@example.com", False)
        assert not await set_active(session, "nobody@example.com", False)
    async with session_scope() as session:
        assert await authenticate(session, "heart@example.com", PASSWORD) is None
    async with session_scope() as session:
        await set_active(session, "heart@example.com", True)
    async with session_scope() as session:
        assert await authenticate(session, "heart@example.com", PASSWORD) is not None

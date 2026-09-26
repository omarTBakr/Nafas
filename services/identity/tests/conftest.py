import pytest

from nafas_core.db import session_scope
from nafas_identity.logic.accounts import create_doctor_account
from nafas_identity.logic.seed import seed_specializations

PASSWORD = "correct horse battery"


@pytest.fixture
async def two_doctors(database):
    """A cardiologist and a dermatologist, each with an account; returns their doctor ids."""
    async with session_scope() as session:
        await seed_specializations(session)
        heart = await create_doctor_account(
            session,
            email="heart@example.com",
            password=PASSWORD,
            full_name_en="Dr Heart",
            full_name_ar="د. قلب",
            specialization_code="cardiology",
        )
        skin = await create_doctor_account(
            session,
            email="skin@example.com",
            password=PASSWORD,
            full_name_en="Dr Skin",
            full_name_ar="د. جلد",
            specialization_code="dermatology",
        )

    return heart.id, skin.id

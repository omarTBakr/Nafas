import uuid
from dataclasses import dataclass

import pytest

from nafas_core.db import session_scope
from nafas_core.enums.channel import Channel
from nafas_identity.logic.accounts import create_doctor_account
from nafas_identity.logic.patients import register_patient
from nafas_identity.logic.seed import seed_specializations


@dataclass
class Parties:
    doctor_id: uuid.UUID
    patient_id: uuid.UUID
    other_patient_id: uuid.UUID


@pytest.fixture
async def parties(database) -> Parties:
    """A doctor and two of their patients, made through identity's own logic."""
    async with session_scope() as session:
        await seed_specializations(session)
        doctor = await create_doctor_account(
            session,
            email="heart@example.com",
            password="correct horse battery",
            full_name_en="Dr Heart",
            full_name_ar="د. قلب",
            specialization_code="cardiology",
        )
    async with session_scope(doctor_id=doctor.id) as session:
        first = await register_patient(session, doctor_id=doctor.id, full_name="منى", channel=Channel.TELEGRAM, external_id="1")
        second = await register_patient(session, doctor_id=doctor.id, full_name="كريم", channel=Channel.TELEGRAM, external_id="2")
    return Parties(doctor.id, first.id, second.id)

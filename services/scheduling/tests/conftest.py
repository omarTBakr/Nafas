from dataclasses import dataclass
from datetime import time
from uuid import UUID

import pytest

from nafas_core.db import session_scope
from nafas_core.enums.channel import Channel
from nafas_identity.logic.accounts import create_doctor_account
from nafas_identity.logic.patients import register_patient
from nafas_identity.logic.seed import seed_specializations
from nafas_scheduling.enums import AvailabilityMode
from nafas_scheduling.models import AvailabilityRule, BookingSettings

WEDNESDAY, THURSDAY = 2, 3


@dataclass
class Clinic:
    doctor_id: UUID
    other_doctor_id: UUID
    patient_id: UUID
    second_patient_id: UUID


async def _doctor(session, email: str) -> UUID:
    doctor = await create_doctor_account(
        session,
        email=email,
        password="correct horse battery",
        full_name_en="Dr Test",
        full_name_ar="د. تجربة",
        specialization_code="cardiology",
    )
    return doctor.id


@pytest.fixture
async def clinic(database) -> Clinic:
    """
    A cardiologist in Cairo who sees patients Wednesdays and Thursdays 17:00-21:00
    in 20-minute slots (Thursdays in person only), two of their patients, and
    a second doctor with no hours at all. Built through the identity service's
    own logic, as the real flow would.
    """
    async with session_scope() as session:
        await seed_specializations(session)
        doctor_id = await _doctor(session, "heart@example.com")
        other_doctor_id = await _doctor(session, "other@example.com")

    async with session_scope(doctor_id=doctor_id) as session:
        session.add(BookingSettings(doctor_id=doctor_id, timezone="Africa/Cairo", slot_minutes=20, min_notice_minutes=60))
        session.add(AvailabilityRule(doctor_id=doctor_id, weekday=WEDNESDAY, start_local=time(17), end_local=time(21)))
        session.add(
            AvailabilityRule(
                doctor_id=doctor_id,
                weekday=THURSDAY,
                start_local=time(17),
                end_local=time(21),
                mode=AvailabilityMode.IN_PERSON,
            )
        )
        first = await register_patient(session, doctor_id=doctor_id, full_name="منى", channel=Channel.TELEGRAM, external_id="1")
        second = await register_patient(session, doctor_id=doctor_id, full_name="كريم", channel=Channel.TELEGRAM, external_id="2")

    return Clinic(doctor_id, other_doctor_id, first.id, second.id)

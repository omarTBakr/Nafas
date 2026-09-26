from sqlalchemy import select, update

from nafas_core.db import session_scope
from nafas_identity.logic.accounts import register_patient_account
from nafas_identity.logic.directory import ensure_care_link, list_doctors
from nafas_identity.models import DoctorPatient, User


async def test_doctors_are_listed_with_their_specialization(two_doctors):
    async with session_scope() as session:
        everyone = await list_doctors(session)
        cardiologists = await list_doctors(session, specialization_code="cardiology")

    assert {d.specialization_code for d in everyone} == {"cardiology", "dermatology"}
    assert [(d.full_name_en, d.specialization_ar) for d in cardiologists] == [("Dr Heart", "قلب وأوعية دموية")]


async def test_a_disabled_doctor_disappears_from_the_directory(two_doctors):
    heart_id, _ = two_doctors
    async with session_scope() as session:
        await session.execute(update(User).where(User.email == "heart@example.com").values(is_active=False))

    async with session_scope() as session:
        assert heart_id not in [d.doctor_id for d in await list_doctors(session)]


async def test_the_care_link_is_idempotent(two_doctors):
    heart_id, _ = two_doctors
    async with session_scope() as session:
        mona = await register_patient_account(session, email="m@example.com", password="a long patient password", full_name="منى")

    for _ in range(2):
        async with session_scope(doctor_id=heart_id) as session:
            await ensure_care_link(session, heart_id, mona.patient_id)

    async with session_scope(doctor_id=heart_id) as session:
        assert len((await session.scalars(select(DoctorPatient))).all()) == 1

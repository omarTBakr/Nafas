import pytest
from sqlalchemy import select

from nafas_core.db import session_scope
from nafas_core.enums.identity import UserRole
from nafas_identity.exceptions import AccountExistsError
from nafas_identity.logic.accounts import authenticate, get_user, register_patient_account
from nafas_identity.models import DoctorPatient, Patient

PASSWORD = "a long patient password"


async def _sign_up(email="mona@example.com", name="منى علي"):
    async with session_scope() as session:
        return await register_patient_account(session, email=email, password=PASSWORD, full_name=name)


async def test_sign_up_then_log_in_as_the_patient(database):
    signed_up = await _sign_up()

    async with session_scope() as session:
        logged_in = await authenticate(session, "Mona@Example.com", PASSWORD)

    assert logged_in.role is UserRole.PATIENT
    assert logged_in.patient_id == signed_up.patient_id
    assert logged_in.doctor_id is None


async def test_one_account_per_email_for_patients_too(two_doctors):
    with pytest.raises(AccountExistsError):
        await _sign_up(email="heart@example.com")


async def test_a_patient_sees_their_own_record_and_no_one_elses(database):
    mona = await _sign_up()
    karim = await _sign_up(email="karim@example.com", name="كريم")

    async with session_scope(patient_id=mona.patient_id) as session:
        visible = (await session.scalars(select(Patient))).all()

    assert [p.id for p in visible] == [mona.patient_id]
    assert karim.patient_id not in [p.id for p in visible]


async def test_a_new_patient_is_invisible_to_doctors_until_linked(two_doctors):
    heart_id, _ = two_doctors
    mona = await _sign_up()

    async with session_scope(doctor_id=heart_id) as session:
        assert (await session.scalars(select(Patient))).all() == []
        session.add(DoctorPatient(doctor_id=heart_id, patient_id=mona.patient_id))

    async with session_scope(doctor_id=heart_id) as session:
        assert [p.id for p in (await session.scalars(select(Patient))).all()] == [mona.patient_id]

    # and the patient can see the link from their side
    async with session_scope(patient_id=mona.patient_id) as session:
        links = (await session.scalars(select(DoctorPatient))).all()
    assert [(link.doctor_id, link.patient_id) for link in links] == [(heart_id, mona.patient_id)]


async def test_a_session_check_returns_the_patient_too(database):
    mona = await _sign_up()

    async with session_scope() as session:
        account = await get_user(session, mona.user_id)

    assert account.patient_id == mona.patient_id

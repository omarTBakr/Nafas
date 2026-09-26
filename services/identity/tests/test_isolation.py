"""
Row-level security, end to end: a doctor sees their own patients and nobody
else's, and cannot write rows into another doctor's care. These run as
nafas_service, the role services really use.
"""

import pytest
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError

from nafas_core.db import session_scope
from nafas_core.enums.channel import Channel
from nafas_identity.enums import ConsentKind
from nafas_identity.logic.patients import record_consent, register_patient
from nafas_identity.models import Consent, DoctorPatient, Patient, PatientChannel


@pytest.fixture
async def heart_patient(two_doctors):
    heart_id, _ = two_doctors
    async with session_scope(doctor_id=heart_id) as session:
        patient = await register_patient(
            session, doctor_id=heart_id, full_name="منى علي", channel=Channel.TELEGRAM, external_id="1001"
        )
        await record_consent(session, doctor_id=heart_id, patient_id=patient.id, kind=ConsentKind.DATA_PROCESSING)

    return patient.id


async def _visible(doctor_id):
    """How many of each patient-data row this doctor can see."""
    async with session_scope(doctor_id=doctor_id) as session:
        return {
            model.__tablename__: len((await session.scalars(select(model))).all())
            for model in (Patient, PatientChannel, DoctorPatient, Consent)
        }


async def test_a_doctor_sees_their_own_patient(two_doctors, heart_patient):
    heart_id, _ = two_doctors

    assert await _visible(heart_id) == {"patients": 1, "patient_channels": 1, "doctor_patients": 1, "consents": 1}


async def test_another_doctor_sees_nothing_of_them(two_doctors, heart_patient):
    _, skin_id = two_doctors

    assert await _visible(skin_id) == {"patients": 0, "patient_channels": 0, "doctor_patients": 0, "consents": 0}


async def test_without_a_doctor_nothing_is_visible(heart_patient):
    assert await _visible(None) == {"patients": 0, "patient_channels": 0, "doctor_patients": 0, "consents": 0}


async def test_a_doctor_cannot_claim_another_doctors_patient(two_doctors, heart_patient):
    """Linking the patient to yourself is the one way in, so it must be refused."""
    heart_id, skin_id = two_doctors

    with pytest.raises(DBAPIError, match="row-level security"):
        async with session_scope(doctor_id=skin_id) as session:
            session.add(DoctorPatient(doctor_id=heart_id, patient_id=heart_patient))
            await session.flush()


async def test_a_doctor_cannot_write_rows_as_another_doctor(two_doctors, heart_patient):
    heart_id, skin_id = two_doctors

    with pytest.raises(DBAPIError, match="row-level security"):
        async with session_scope(doctor_id=skin_id) as session:
            await record_consent(session, doctor_id=heart_id, patient_id=heart_patient, kind=ConsentKind.AI_CHAT)

"""Consent to record a session: taken fresh for each recording, and only by the patient's own doctor."""

import httpx
import pytest
from sqlalchemy import select

import nafas_core.config
from nafas_core.db import session_scope
from nafas_core.enums.channel import Channel
from nafas_identity.api import app
from nafas_identity.logic.patients import register_patient
from nafas_identity.models import Consent

TOKEN = {"X-Internal-Token": "internal-secret"}


@pytest.fixture
async def client(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_TOKEN", "internal-secret")
    nafas_core.config._settings_instance = None
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://identity", headers=TOKEN) as client:
        yield client


async def test_each_recording_gets_its_own_consent_and_only_from_the_patients_doctor(two_doctors, client):
    heart_id, skin_id = two_doctors
    async with session_scope(doctor_id=heart_id) as session:
        patient = await register_patient(
            session, doctor_id=heart_id, full_name="منى علي", channel=Channel.TELEGRAM, external_id="2001"
        )

    path = f"/internal/v1/doctors/{heart_id}/patients/{patient.id}/recording-consent"
    first = await client.post(path, json={"evidence": "verbal, in the room"})
    second = await client.post(path, json={"evidence": "verbal, in the room"})
    stranger = await client.post(
        f"/internal/v1/doctors/{skin_id}/patients/{patient.id}/recording-consent", json={"evidence": "verbal"}
    )
    empty = await client.post(path, json={"evidence": ""})

    assert first.status_code == second.status_code == 201
    assert first.json()["kind"] == "session_recording" and first.json()["consent_id"] != second.json()["consent_id"]
    assert stranger.status_code == 409
    assert empty.status_code == 422
    async with session_scope(doctor_id=heart_id) as session:
        kinds = (await session.scalars(select(Consent.kind).where(Consent.patient_id == patient.id))).all()
    assert [k.value for k in kinds].count("session_recording") == 2

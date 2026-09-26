"""Online visits through the gateway: the patient and the doctor join; only the doctor records."""

import uuid
from datetime import UTC, datetime, time, timedelta

import pytest
from sqlalchemy import update

from nafas_consultation.fake_rooms import FakeRooms
from nafas_consultation.rooms import Track, room_name, set_rooms
from nafas_core.db import session_scope
from nafas_scheduling.enums import AppointmentMode
from nafas_scheduling.logic import booking
from nafas_scheduling.models import AvailabilityRule, BookingSettings

from .conftest import DOCTOR_PASSWORD, browser, sign_up


@pytest.fixture
def rooms():
    fake = FakeRooms()
    set_rooms(fake)
    yield fake
    set_rooms(None)


async def soon_online(doctor_id, patient_id) -> uuid.UUID:
    """An online visit confirmed for the next 5-minute mark: the test doctor gets open hours and short slots."""
    now = datetime.now(UTC)
    start = now.replace(second=0, microsecond=0) + timedelta(minutes=5 - now.minute % 5)
    async with session_scope(doctor_id=doctor_id) as session:
        await session.execute(
            update(BookingSettings).where(BookingSettings.doctor_id == doctor_id).values(slot_minutes=5, min_notice_minutes=0)
        )
        for weekday in range(7):
            session.add(AvailabilityRule(doctor_id=doctor_id, weekday=weekday, start_local=time(0), end_local=time(23, 55)))
        await session.flush()
        held = await booking.hold(
            session, doctor_id=doctor_id, patient_id=patient_id, start=start, now=now, mode=AppointmentMode.ONLINE
        )
        return (await booking.confirm(session, held.id, now)).id


async def test_the_patient_and_doctor_join_and_the_doctor_records(doctor_id, rooms):
    async with browser() as sara, browser() as doctor, browser() as omar:
        await sign_up(sara)
        patient_id = (await sara.get("/api/auth/me")).json()["patient_id"]
        async with session_scope(doctor_id=doctor_id) as session:
            from nafas_identity.logic.directory import ensure_care_link

            await ensure_care_link(session, doctor_id=doctor_id, patient_id=uuid.UUID(patient_id))
        appointment_id = await soon_online(doctor_id, uuid.UUID(patient_id))
        await doctor.post("/api/auth/login", json={"email": "heart@example.com", "password": DOCTOR_PASSWORD})
        await sign_up(omar, email="omar@example.com", name="عمر")

        mine = await sara.post(f"/api/visits/{appointment_id}/join")
        theirs = await doctor.post(f"/api/visits/{appointment_id}/join")
        stranger = await omar.post(f"/api/visits/{appointment_id}/join")
        not_doctor = await sara.post(f"/api/doctor/visits/{appointment_id}/recording", json={})

        room = room_name(doctor_id, appointment_id)
        rooms.tracks[room] = [Track(f"patient:{patient_id}", "TR_1")]
        recording = await doctor.post(f"/api/doctor/visits/{appointment_id}/recording", json={})
        stopped = await doctor.post(f"/api/doctor/consultations/{recording.json()['consultation_id']}/stop-recording")

    assert mine.status_code == 200 and mine.json()["token"] == f"token:{room}:patient:{patient_id}:سارة"
    assert theirs.json()["token"] == f"token:{room}:doctor:{doctor_id}:د. قلب"
    assert stranger.status_code == 404
    assert not_doctor.status_code == 403
    assert recording.status_code == 201 and recording.json()["tracks"] == 1
    assert stopped.json()["waiting_for_tracks"] is True

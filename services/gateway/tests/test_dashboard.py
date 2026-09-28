"""The doctor's dashboard through the gateway and the real services: patients, a timeline, and who is next."""

from datetime import UTC, datetime, time, timedelta

import pytest
from sqlalchemy import update

from nafas_core.db import session_scope
from nafas_core.interfaces.embeddings.factory import set_embeddings
from nafas_core.interfaces.embeddings.fake import FakeEmbeddings
from nafas_scheduling.models import AvailabilityRule, BookingSettings

from .conftest import CAIRO, DOCTOR_PASSWORD, browser, sign_up


@pytest.fixture
async def open_all_day(doctor_id):
    """Hours every day, all day, bookable at once: so a visit can be booked for today."""
    async with session_scope(doctor_id=doctor_id) as session:
        await session.execute(
            update(BookingSettings).where(BookingSettings.doctor_id == doctor_id).values(min_notice_minutes=0, slot_minutes=5)
        )
        for weekday in range(7):
            session.add(AvailabilityRule(doctor_id=doctor_id, weekday=weekday, start_local=time(0), end_local=time(23, 59)))
    set_embeddings(FakeEmbeddings())
    yield
    set_embeddings(None)


async def book_soonest(sara, doctor_id) -> dict:
    now = datetime.now(UTC)
    today_in_clinic = now.astimezone(CAIRO).date()
    end_of_day = datetime.combine(today_in_clinic + timedelta(days=1), time.min, tzinfo=CAIRO)
    slots = (
        await sara.get(
            f"/api/doctors/{doctor_id}/slots",
            params={"start": now.isoformat(), "end": end_of_day.isoformat(), "limit": 1},
        )
    ).json()
    held = (await sara.post("/api/appointments", json={"doctor_id": str(doctor_id), "start": slots[0]["start"]})).json()
    return (await sara.post(f"/api/appointments/{held['appointment_id']}/confirm")).json()


async def test_the_doctor_sees_who_is_next_with_a_brief(doctor_id, open_all_day):
    async with browser() as sara, browser() as omar, browser() as doctor:
        await sign_up(sara)
        visit = await book_soonest(sara, doctor_id)
        await sign_up(omar, email="omar@example.com", name="عمر")
        omar_id = (await omar.get("/api/auth/me")).json()["patient_id"]
        await doctor.post("/api/auth/login", json={"email": "heart@example.com", "password": DOCTOR_PASSWORD})
        await doctor.post(f"/api/doctor/patients/{visit['patient_id']}/history", json={"content": "Palpitations at night."})

        upcoming = (await doctor.get("/api/doctor/next")).json()
        roster = (await doctor.get("/api/doctor/patients")).json()
        timeline = (await doctor.get(f"/api/doctor/patients/{visit['patient_id']}/timeline")).json()
        stranger = await doctor.get(f"/api/doctor/patients/{omar_id}/timeline")

    assert upcoming["appointment"]["appointment_id"] == visit["appointment_id"]
    assert upcoming["patient"]["full_name"] == "سارة"
    assert [e["content"] for e in upcoming["brief"]["recent_entries"]] == ["Palpitations at night."]
    assert upcoming["brief"]["open_questions"] == [] and upcoming["brief"]["last_visit"] is None
    # only patients under the doctor's care: Omar never booked
    assert [p["full_name"] for p in roster] == ["سارة"]
    assert {item["type"] for item in timeline["items"]} == {"appointment", "history"}
    assert timeline["timezone"] == "Africa/Cairo"
    assert stranger.status_code == 403


async def test_a_day_with_nothing_left_has_no_next_patient(doctor_id, open_all_day):
    async with browser() as doctor:
        await doctor.post("/api/auth/login", json={"email": "heart@example.com", "password": DOCTOR_PASSWORD})
        upcoming = (await doctor.get("/api/doctor/next")).json()

    assert upcoming["appointment"] is None

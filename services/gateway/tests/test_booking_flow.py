"""
The web app's booking flow end to end: the gateway, wired in-process to the
real identity and scheduling apps, over the real database, with real row-level
security. Only HTTP between the services is short-circuited.
"""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import httpx
import pytest

import nafas_core.config
from nafas_core.clients.identity import IdentityClient, set_identity
from nafas_core.clients.scheduling import SchedulingClient, set_scheduling
from nafas_core.db import session_scope
from nafas_gateway.main import app as gateway
from nafas_identity.api import app as identity_app
from nafas_identity.logic.accounts import create_doctor_account
from nafas_identity.logic.seed import seed_specializations
from nafas_scheduling.api import app as scheduling_app
from nafas_scheduling.models import AvailabilityRule, BookingSettings

CAIRO = ZoneInfo("Africa/Cairo")
DOCTOR_PASSWORD = "doctor password 123"
PATIENT_PASSWORD = "patient password 123"


def next_wednesday(at: time) -> datetime:
    today = datetime.now(CAIRO).date()
    return datetime.combine(today + timedelta(days=(2 - today.weekday()) % 7 or 7), at, tzinfo=CAIRO)


@pytest.fixture
async def doctor_id(database, monkeypatch):
    monkeypatch.setenv("INTERNAL_API_TOKEN", "internal-secret")
    monkeypatch.setenv("JWT_SECRET", "s" * 40)
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "false")
    nafas_core.config._settings_instance = None

    async with session_scope() as session:
        await seed_specializations(session)
        doctor = await create_doctor_account(
            session,
            email="heart@example.com",
            password=DOCTOR_PASSWORD,
            full_name_en="Dr Heart",
            full_name_ar="د. قلب",
            specialization_code="cardiology",
        )
    async with session_scope(doctor_id=doctor.id) as session:
        session.add(BookingSettings(doctor_id=doctor.id, timezone="Africa/Cairo"))
        session.add(AvailabilityRule(doctor_id=doctor.id, weekday=2, start_local=time(17), end_local=time(21)))

    set_identity(IdentityClient(httpx.AsyncClient(transport=httpx.ASGITransport(app=identity_app), base_url="http://identity")))
    set_scheduling(
        SchedulingClient(httpx.AsyncClient(transport=httpx.ASGITransport(app=scheduling_app), base_url="http://scheduling"))
    )
    yield doctor.id
    set_identity(None)
    set_scheduling(None)


def browser() -> httpx.AsyncClient:
    """One browser: its own cookie jar."""
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=gateway), base_url="http://nafas")


async def sign_up(client, email="sara@example.com", name="سارة"):
    return await client.post("/api/auth/register", json={"email": email, "password": PATIENT_PASSWORD, "full_name": name})


async def test_a_patient_signs_up_finds_a_doctor_and_books(doctor_id):
    start = next_wednesday(time(17, 40))

    async with browser() as sara, browser() as doctor:
        signed_up = await sign_up(sara)
        assert signed_up.status_code == 201 and signed_up.json()["role"] == "patient"

        cardiologists = (await sara.get("/api/doctors", params={"specialization": "cardiology"})).json()
        assert [d["full_name_en"] for d in cardiologists] == ["Dr Heart"]

        slots = (
            await sara.get(
                f"/api/doctors/{doctor_id}/slots",
                params={"start": next_wednesday(time(0)).isoformat(), "end": next_wednesday(time(23)).isoformat()},
            )
        ).json()
        assert start.isoformat() in [datetime.fromisoformat(s["start"]).astimezone(CAIRO).isoformat() for s in slots]

        held = await sara.post(
            "/api/appointments", json={"doctor_id": str(doctor_id), "start": start.isoformat(), "reason_for_visit": "خفقان"}
        )
        assert held.status_code == 201 and held.json()["status"] == "held"

        # before confirming, the doctor sees a held slot with no name
        await doctor.post("/api/auth/login", json={"email": "heart@example.com", "password": DOCTOR_PASSWORD})
        window = {"start": next_wednesday(time(0)).isoformat(), "end": next_wednesday(time(23, 59)).isoformat()}
        pending = (await doctor.get("/api/doctor/schedule", params=window)).json()
        assert [(a["status"], a["patient_name"]) for a in pending["appointments"]] == [("held", None)]

        confirmed = await sara.post(f"/api/appointments/{held.json()['appointment_id']}/confirm")
        assert confirmed.json()["status"] == "confirmed"

        mine = (await sara.get("/api/appointments/mine")).json()
        assert [(a["status"], a["doctor"]["full_name_ar"]) for a in mine] == [("confirmed", "د. قلب")]

        # confirming put Sara under the doctor's care, so now her name shows
        booked = (await doctor.get("/api/doctor/schedule", params=window)).json()
        assert [(a["status"], a["patient_name"]) for a in booked["appointments"]] == [("confirmed", "سارة")]
        assert booked["timezone"] == "Africa/Cairo"


async def test_a_taken_time_comes_back_with_its_reason(doctor_id):
    start = next_wednesday(time(18))
    async with browser() as sara, browser() as omar:
        await sign_up(sara)
        await sign_up(omar, email="omar@example.com", name="عمر")
        await sara.post("/api/appointments", json={"doctor_id": str(doctor_id), "start": start.isoformat()})

        second = await omar.post("/api/appointments", json={"doctor_id": str(doctor_id), "start": start.isoformat()})

    assert second.status_code == 409
    assert second.json()["reason"] == "taken"


async def test_a_patient_cannot_cancel_another_patients_appointment(doctor_id):
    async with browser() as sara, browser() as omar:
        await sign_up(sara)
        await sign_up(omar, email="omar@example.com", name="عمر")
        held = await sara.post(
            "/api/appointments", json={"doctor_id": str(doctor_id), "start": next_wednesday(time(19)).isoformat()}
        )

        attempt = await omar.post(f"/api/appointments/{held.json()['appointment_id']}/cancel")

    assert attempt.status_code == 404


async def test_roles_keep_to_their_portal(doctor_id):
    async with browser() as sara, browser() as doctor:
        await sign_up(sara)
        await doctor.post("/api/auth/login", json={"email": "heart@example.com", "password": DOCTOR_PASSWORD})
        window = {"start": next_wednesday(time(0)).isoformat(), "end": next_wednesday(time(23)).isoformat()}

        assert (await sara.get("/api/doctor/schedule", params=window)).status_code == 403
        assert (await doctor.get("/api/appointments/mine")).status_code == 403
        assert (
            await doctor.post(
                "/api/appointments", json={"doctor_id": str(doctor_id), "start": next_wednesday(time(20)).isoformat()}
            )
        ).status_code == 403


async def test_signing_up_twice_with_one_email_is_a_conflict(doctor_id):
    async with browser() as first, browser() as second:
        await sign_up(first)
        again = await sign_up(second)

    assert again.status_code == 409


async def test_the_directory_is_public_but_booking_is_not(doctor_id):
    async with browser() as anonymous:
        assert (await anonymous.get("/api/doctors")).status_code == 200
        assert (
            await anonymous.post(
                "/api/appointments", json={"doctor_id": str(doctor_id), "start": next_wednesday(time(17)).isoformat()}
            )
        ).status_code == 401


async def test_a_patient_chooses_their_dialect_and_voice(doctor_id):
    async with browser() as sara:
        signed_up = await sara.post(
            "/api/auth/register",
            json={"email": "sara@example.com", "password": PATIENT_PASSWORD, "full_name": "سارة", "dialect": "lb"},
        )
        assert signed_up.status_code == 201
        assert (await sara.get("/api/me/profile")).json()["dialect"] == "lb"

        changed = await sara.patch("/api/me/profile", json={"dialect": "eg", "voice": "female"})
        assert (changed.json()["dialect"], changed.json()["voice"]) == ("eg", "female")

        assert (await sara.patch("/api/me/profile", json={"dialect": "klingon"})).status_code == 422

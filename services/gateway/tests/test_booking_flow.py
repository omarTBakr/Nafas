"""The web app's booking flow end to end, through the gateway and the real services."""

from datetime import datetime, time

from .conftest import CAIRO, DOCTOR_PASSWORD, PATIENT_PASSWORD, browser, next_wednesday, sign_up


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


async def test_booking_is_visible_then_removed_from_the_active_schedule_after_cancellation(doctor_id):
    start = next_wednesday(time(20, 20))
    window = {"start": next_wednesday(time(0)).isoformat(), "end": next_wednesday(time(23, 59)).isoformat()}

    async with browser() as sara, browser() as doctor:
        await sign_up(sara)
        held = await sara.post(
            "/api/appointments", json={"doctor_id": str(doctor_id), "start": start.isoformat(), "reason_for_visit": "check-up"}
        )
        assert held.status_code == 201
        appointment_id = held.json()["appointment_id"]
        assert held.json()["status"] == "held"

        confirmed = await sara.post(f"/api/appointments/{appointment_id}/confirm")
        assert confirmed.status_code == 200
        assert confirmed.json()["status"] == "confirmed"

        await doctor.post("/api/auth/login", json={"email": "heart@example.com", "password": DOCTOR_PASSWORD})
        schedule = (await doctor.get("/api/doctor/schedule", params=window)).json()
        assert [(item["appointment_id"], item["status"]) for item in schedule["appointments"]] == [(appointment_id, "confirmed")]
        assert [(item["appointment_id"], item["status"]) for item in (await sara.get("/api/appointments/mine")).json()] == [
            (appointment_id, "confirmed")
        ]

        cancelled = await sara.post(f"/api/appointments/{appointment_id}/cancel")
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "cancelled"

        patient_appointments = (await sara.get("/api/appointments/mine")).json()
        assert [(item["appointment_id"], item["status"]) for item in patient_appointments] == [(appointment_id, "cancelled")]
        assert (await doctor.get("/api/doctor/schedule", params=window)).json()["appointments"] == []

        available = await sara.get(f"/api/doctors/{doctor_id}/check", params={"start": start.isoformat(), "mode": "in_person"})
        assert available.status_code == 200 and available.json()["bookable"] is True


async def test_confirmed_booking_adds_the_patient_to_the_doctors_roster(doctor_id):
    async with browser() as sara, browser() as doctor:
        await sign_up(sara)
        patient_id = (await sara.get("/api/auth/me")).json()["patient_id"]
        held = await sara.post(
            "/api/appointments", json={"doctor_id": str(doctor_id), "start": next_wednesday(time(20, 40)).isoformat()}
        )
        assert held.status_code == 201

        confirmed = await sara.post(f"/api/appointments/{held.json()['appointment_id']}/confirm")
        assert confirmed.status_code == 200
        assert confirmed.json()["status"] == "confirmed"

        logged_in = await doctor.post("/api/auth/login", json={"email": "heart@example.com", "password": DOCTOR_PASSWORD})
        assert logged_in.status_code == 200
        roster = await doctor.get("/api/doctor/patients")

    assert roster.status_code == 200
    assert any(patient["patient_id"] == patient_id and patient["full_name"] == "سارة" for patient in roster.json())


async def test_a_new_patient_can_sign_up_log_out_and_sign_back_in(doctor_id):
    async with browser() as patient:
        registered = await sign_up(patient, email="new.patient@example.com", name="مستخدم جديد")
        assert registered.status_code == 201
        assert registered.json()["role"] == "patient"

        first_me = await patient.get("/api/auth/me")
        assert first_me.status_code == 200
        assert first_me.json()["email"] == "new.patient@example.com"

        logged_out = await patient.post("/api/auth/logout")
        assert logged_out.status_code == 204
        assert (await patient.get("/api/auth/me")).status_code == 401

        logged_in = await patient.post("/api/auth/login", json={"email": "new.patient@example.com", "password": PATIENT_PASSWORD})
        assert logged_in.status_code == 200
        assert (await patient.get("/api/auth/me")).json()["role"] == "patient"


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
            json={
                "email": "sara@example.com",
                "password": PATIENT_PASSWORD,
                "full_name": "سارة",
                "dialect": "lb",
                "accept_data_processing": True,
            },
        )
        assert signed_up.status_code == 201
        assert (await sara.get("/api/me/profile")).json()["dialect"] == "lb"

        changed = await sara.patch("/api/me/profile", json={"dialect": "eg", "voice": "female"})
        assert (changed.json()["dialect"], changed.json()["voice"]) == ("eg", "female")

        assert (await sara.patch("/api/me/profile", json={"dialect": "klingon"})).status_code == 422

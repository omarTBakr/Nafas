from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

import httpx
import pytest

import nafas_core.config
from nafas_core.db import session_scope
from nafas_identity.logic.accounts import register_patient_account
from nafas_scheduling.api import app

CAIRO = ZoneInfo("Africa/Cairo")
TOKEN = {"X-Internal-Token": "internal-secret"}


def next_wednesday(at: time) -> datetime:
    """The coming Wednesday (never today) at a local time: always bookable by the clinic's rules."""
    today = datetime.now(CAIRO).date()
    ahead = (2 - today.weekday()) % 7 or 7
    return datetime.combine(today + timedelta(days=ahead), at, tzinfo=CAIRO)


@pytest.fixture
async def api(clinic, monkeypatch):
    monkeypatch.setenv("INTERNAL_API_TOKEN", "internal-secret")
    nafas_core.config._settings_instance = None
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://scheduling", headers=TOKEN) as client:
        yield client


@pytest.fixture
async def web_patient(clinic):
    """A patient who signed up on the web: no doctor link, reached only through their own scope."""
    async with session_scope() as session:
        account = await register_patient_account(
            session, email="web@example.com", password="a long patient password", full_name="سارة"
        )
    return account.patient_id


async def test_without_the_token_nothing_is_answered(clinic):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://scheduling") as client:
        assert (await client.get(f"/internal/v1/doctors/{clinic.doctor_id}/booking-info")).status_code == 403


async def test_slots_come_back_as_aware_times(api, clinic):
    start = next_wednesday(time(0))
    response = await api.get(
        f"/internal/v1/doctors/{clinic.doctor_id}/slots",
        params={"start": start.isoformat(), "end": (start + timedelta(days=1)).isoformat(), "limit": 3},
    )

    assert response.status_code == 200
    starts = [datetime.fromisoformat(s["start"]).astimezone(CAIRO).strftime("%H:%M") for s in response.json()]
    assert starts == ["17:00", "17:20", "17:40"]


async def test_naive_times_are_refused(api, clinic):
    response = await api.get(f"/internal/v1/doctors/{clinic.doctor_id}/check", params={"start": "2026-10-07T17:40:00"})

    assert response.status_code == 422


async def test_check_explains_a_refusal_and_offers_the_nearest_times(api, clinic):
    closed = next_wednesday(time(16, 50))
    body = (await api.get(f"/internal/v1/doctors/{clinic.doctor_id}/check", params={"start": closed.isoformat()})).json()

    assert body["bookable"] is False
    assert body["reason"] == "outside_hours"
    assert datetime.fromisoformat(body["suggestions"][0]["start"]) == next_wednesday(time(17))


async def test_a_web_patient_holds_confirms_and_sees_the_appointment(api, clinic, web_patient):
    start = next_wednesday(time(17, 40))

    held = await api.post(
        f"/internal/v1/doctors/{clinic.doctor_id}/holds",
        json={
            "patient_id": str(web_patient),
            "start": start.isoformat(),
            "mode": "in_person",
            "reason_for_visit": "palpitations",
        },
    )
    assert held.status_code == 201
    appointment_id = held.json()["appointment_id"]

    confirmed = await api.post(f"/internal/v1/appointments/{appointment_id}/confirm", json={"patient_id": str(web_patient)})
    assert confirmed.json()["status"] == "confirmed"

    mine = (await api.get(f"/internal/v1/patients/{web_patient}/appointments")).json()
    assert [(a["appointment_id"], a["status"]) for a in mine] == [(appointment_id, "confirmed")]

    schedule = (
        await api.get(
            f"/internal/v1/doctors/{clinic.doctor_id}/appointments",
            params={"start": next_wednesday(time(0)).isoformat(), "end": next_wednesday(time(23)).isoformat()},
        )
    ).json()
    assert [a["patient_id"] for a in schedule] == [str(web_patient)]


async def test_a_taken_time_is_a_409_with_the_reason(api, clinic, web_patient):
    start = next_wednesday(time(18))
    body = {"patient_id": str(web_patient), "start": start.isoformat(), "mode": "in_person"}
    await api.post(f"/internal/v1/doctors/{clinic.doctor_id}/holds", json=body)

    second = await api.post(f"/internal/v1/doctors/{clinic.doctor_id}/holds", json=body | {"patient_id": str(clinic.patient_id)})

    assert second.status_code == 409
    assert second.json()["reason"] == "taken"


async def test_a_patient_cannot_act_on_someone_elses_appointment(api, clinic, web_patient):
    """The id alone is not enough: the lookup happens in the acting patient's own scope."""
    theirs = await api.post(
        f"/internal/v1/doctors/{clinic.doctor_id}/holds",
        json={"patient_id": str(clinic.patient_id), "start": next_wednesday(time(19)).isoformat(), "mode": "in_person"},
    )

    response = await api.post(
        f"/internal/v1/appointments/{theirs.json()['appointment_id']}/cancel", json={"patient_id": str(web_patient)}
    )

    assert response.status_code == 404


async def test_the_actor_must_be_exactly_one(api, clinic):
    response = await api.post(f"/internal/v1/appointments/{clinic.doctor_id}/cancel", json={})

    assert response.status_code == 422


async def test_a_doctor_without_hours_says_not_bookable(api, clinic):
    response = await api.get(f"/internal/v1/doctors/{clinic.other_doctor_id}/booking-info")

    assert response.status_code == 409
    assert response.json()["reason"] == "not_bookable"


async def test_the_clock_is_real(api, clinic):
    """A time in the past is too soon, whatever the test's fixed dates elsewhere."""
    past = datetime.now(UTC) - timedelta(hours=1)
    body = (
        await api.get(
            f"/internal/v1/doctors/{clinic.doctor_id}/check", params={"start": past.replace(second=0, microsecond=0).isoformat()}
        )
    ).json()

    assert body["bookable"] is False


async def test_interpreting_an_hour_without_am_pm_checks_both(api, clinic):
    """ "Wednesday at 5:40": 05:40 is outside hours, 17:40 is bookable; the caller sees both, checked."""
    body = (
        await api.post(
            f"/internal/v1/doctors/{clinic.doctor_id}/interpret-time",
            json={"day": {"weekday": 2}, "hour": 5, "minute": 40},
        )
    ).json()

    checked = {datetime.fromisoformat(c["start"]).astimezone(CAIRO).strftime("%H:%M"): c for c in body["candidates"]}
    assert checked["05:40"]["bookable"] is False and checked["05:40"]["reason"] == "outside_hours"
    assert checked["17:40"]["bookable"] is True
    assert body["timezone"] == "Africa/Cairo"


async def test_interpreting_a_period_lists_its_free_slots(api, clinic):
    """ "Wednesday after asr" (15:00-18:00) meets the 17:00 opening: 17:00, 17:20, 17:40."""
    body = (
        await api.post(f"/internal/v1/doctors/{clinic.doctor_id}/interpret-time", json={"day": {"weekday": 2}, "period": "asr"})
    ).json()

    assert body["candidates"] == []
    starts = [datetime.fromisoformat(s["start"]).astimezone(CAIRO).strftime("%H:%M") for s in body["free_slots"]]
    assert starts == ["17:00", "17:20", "17:40"]


async def test_an_impossible_expression_is_422(api, clinic):
    response = await api.post(
        f"/internal/v1/doctors/{clinic.doctor_id}/interpret-time", json={"day": {"weekday": 2, "relative_days": 1}}
    )

    assert response.status_code == 422

"""The API's side of BookingWorkflow: what it tells the workflow, and the notices the workflow's activities write."""

import asyncio
import uuid
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

import httpx
import pytest
from sqlalchemy import update

import nafas_core.config
from nafas_core.db import session_scope
from nafas_scheduling import activities
from nafas_scheduling.api import app
from nafas_scheduling.enums import AppointmentStatus
from nafas_scheduling.models import Appointment
from nafas_scheduling.schemas import AppointmentRef, NotificationRequest

CAIRO = ZoneInfo("Africa/Cairo")


def next_wednesday(at: time) -> datetime:
    today = datetime.now(CAIRO).date()
    return datetime.combine(today + timedelta(days=(2 - today.weekday()) % 7 or 7), at, tzinfo=CAIRO)


@pytest.fixture
async def api(clinic, monkeypatch):
    monkeypatch.setenv("INTERNAL_API_TOKEN", "internal-secret")
    nafas_core.config._settings_instance = None
    headers = {"X-Internal-Token": "internal-secret"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://s", headers=headers) as client:
        yield client


async def held(api, clinic, at=time(17, 40)) -> dict:
    response = await api.post(
        f"/internal/v1/doctors/{clinic.doctor_id}/holds",
        json={"patient_id": str(clinic.patient_id), "start": next_wednesday(at).isoformat(), "mode": "in_person"},
    )
    assert response.status_code == 201
    return response.json()


async def test_each_change_is_told_to_the_workflow_after_the_database(api, clinic, booking_events):
    appointment = await held(api, clinic)
    appointment_id = appointment["appointment_id"]
    await api.post(f"/internal/v1/appointments/{appointment_id}/confirm", json={"patient_id": str(clinic.patient_id)})
    await api.post(f"/internal/v1/appointments/{appointment_id}/cancel", json={"doctor_id": str(clinic.doctor_id)})

    assert booking_events.events == [
        ("held", appointment_id),
        ("confirmed", appointment_id),
        ("cancelled_by_doctor", appointment_id),
    ]


async def test_the_workflows_notices_reach_only_their_patient(api, clinic):
    appointment = await held(api, clinic)
    request = NotificationRequest(str(uuid.uuid4()), appointment["appointment_id"], str(clinic.doctor_id), "confirmed")
    # a retried activity writes the same notice once
    await activities.notify(request)
    await activities.notify(request)

    mine = (await api.get(f"/internal/v1/patients/{clinic.patient_id}/notifications")).json()
    theirs = (await api.get(f"/internal/v1/patients/{clinic.second_patient_id}/notifications")).json()

    assert [(n["kind"], n["appointment_id"]) for n in mine] == [("confirmed", appointment["appointment_id"])]
    assert datetime.fromisoformat(mine[0]["details"]["start"]) == datetime.fromisoformat(appointment["start"])
    assert mine[0]["details"]["timezone"] == "Africa/Cairo"
    assert theirs == []

    notice = mine[0]["notification_id"]
    assert (await api.post(f"/internal/v1/patients/{clinic.second_patient_id}/notifications/{notice}/read")).status_code == 404
    assert (await api.post(f"/internal/v1/patients/{clinic.patient_id}/notifications/{notice}/read")).status_code == 204
    unread = await api.get(f"/internal/v1/patients/{clinic.patient_id}/notifications", params={"unread_only": "true"})
    assert unread.json() == []


async def test_expiring_touches_only_a_hold_still_waiting(api, clinic):
    waiting = await held(api, clinic, time(17, 0))
    confirmed = await held(api, clinic, time(18, 0))
    await api.post(
        f"/internal/v1/appointments/{confirmed['appointment_id']}/confirm", json={"patient_id": str(clinic.patient_id)}
    )
    async with session_scope(doctor_id=clinic.doctor_id) as session:
        await session.execute(
            update(Appointment)
            .where(Appointment.id == uuid.UUID(waiting["appointment_id"]))
            .values(hold_expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )

    assert await activities.expire_hold(AppointmentRef(waiting["appointment_id"], str(clinic.doctor_id))) is True
    assert await activities.expire_hold(AppointmentRef(confirmed["appointment_id"], str(clinic.doctor_id))) is False
    async with session_scope(doctor_id=clinic.doctor_id) as session:
        assert (await session.get(Appointment, uuid.UUID(waiting["appointment_id"]))).status is AppointmentStatus.CANCELLED


async def test_a_no_show_needs_the_visit_to_have_started_and_its_own_doctor(api, clinic, booking_events):
    appointment = await held(api, clinic)
    appointment_id = appointment["appointment_id"]
    await api.post(f"/internal/v1/appointments/{appointment_id}/confirm", json={"patient_id": str(clinic.patient_id)})

    early = await api.post(f"/internal/v1/appointments/{appointment_id}/no-show", json={"doctor_id": str(clinic.doctor_id)})
    assert early.status_code == 409

    async with session_scope(doctor_id=clinic.doctor_id) as session:
        await session.execute(
            update(Appointment)
            .where(Appointment.id == uuid.UUID(appointment_id))
            .values(starts_at=datetime(2026, 1, 7, 15, 0, tzinfo=UTC), ends_at=datetime(2026, 1, 7, 15, 20, tzinfo=UTC))
        )
    other = await api.post(f"/internal/v1/appointments/{appointment_id}/no-show", json={"doctor_id": str(clinic.other_doctor_id)})
    marked = await api.post(f"/internal/v1/appointments/{appointment_id}/no-show", json={"doctor_id": str(clinic.doctor_id)})

    assert other.status_code == 404
    assert marked.status_code == 200 and marked.json()["status"] == "no_show"
    assert booking_events.events[-1] == ("no_show", appointment_id)
    # and completing it afterwards changes nothing
    assert await activities.complete(AppointmentRef(appointment_id, str(clinic.doctor_id))) is False


async def test_a_real_booking_runs_its_workflow(api, clinic, temporal, task_queue):
    from temporalio.worker import Worker

    from nafas_scheduling.events import TemporalBookingEvents, set_events
    from nafas_scheduling.workflows import WORKFLOWS

    set_events(TemporalBookingEvents(temporal, task_queue))

    async def kinds() -> list[str]:
        response = await api.get(f"/internal/v1/patients/{clinic.patient_id}/notifications")
        return sorted(n["kind"] for n in response.json())

    async def eventually(expected: list[str]) -> list[str]:
        for _ in range(50):
            if (found := await kinds()) == expected:
                break
            await asyncio.sleep(0.1)
        return found

    async with Worker(temporal, task_queue=task_queue, workflows=WORKFLOWS, activities=activities.ACTIVITIES):
        appointment = await held(api, clinic)
        appointment_id = appointment["appointment_id"]
        async with session_scope(doctor_id=clinic.doctor_id) as session:
            stored = await session.get(Appointment, uuid.UUID(appointment_id))
        assert stored.booking_workflow_id == f"booking-{appointment_id}"

        await api.post(f"/internal/v1/appointments/{appointment_id}/confirm", json={"patient_id": str(clinic.patient_id)})
        assert await eventually(["confirmed"]) == ["confirmed"]

        await api.post(f"/internal/v1/appointments/{appointment_id}/cancel", json={"doctor_id": str(clinic.doctor_id)})
        assert await temporal.get_workflow_handle(stored.booking_workflow_id).result() == "cancelled"

    assert await kinds() == ["cancelled_by_doctor", "confirmed"]


async def test_a_notice_is_emailed_unless_the_patient_turned_emails_off(api, clinic, monkeypatch):
    import httpx

    from nafas_core.clients.identity import IdentityClient, set_identity
    from nafas_core.interfaces.email import set_email_sender
    from nafas_core.interfaces.email.fake import FakeEmailSender
    from nafas_identity.api import app as identity_app
    from nafas_identity.logic.accounts import register_patient_account
    from nafas_identity.logic.profile import update_profile

    async with session_scope() as session:
        web = await register_patient_account(session, email="mona@example.com", password="a long password", full_name="منى")
    set_identity(IdentityClient(httpx.AsyncClient(transport=httpx.ASGITransport(app=identity_app), base_url="http://identity")))
    sender = FakeEmailSender()
    set_email_sender(sender)
    try:
        response = await api.post(
            f"/internal/v1/doctors/{clinic.doctor_id}/holds",
            json={"patient_id": str(web.patient_id), "start": next_wednesday(time(19)).isoformat(), "mode": "in_person"},
        )
        appointment_id = response.json()["appointment_id"]
        request = NotificationRequest(str(uuid.uuid4()), appointment_id, str(clinic.doctor_id), "confirmed")

        assert await activities.email_notice(request) == "sent"
        async with session_scope(patient_id=web.patient_id) as session:
            await update_profile(session, web.patient_id, email_notices=False)
        assert await activities.email_notice(request) == "skipped"

        set_email_sender(None)
        async with session_scope(patient_id=web.patient_id) as session:
            await update_profile(session, web.patient_id, email_notices=True)
        # no SMTP_HOST: switched off, and says so
        assert await activities.email_notice(request) == "off"
    finally:
        set_identity(None)
        set_email_sender(None)

    [sent] = sender.sent
    assert (sent.to, sent.subject) == ("mona@example.com", "تم تأكيد موعدك مع د. تجربة")
    assert sent.attachments[0].filename == "appointment.ics"

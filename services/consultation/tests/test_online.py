"""Online visits: who joins a room and when, recording each microphone, and LiveKit's webhooks driving the rest."""

import base64
import hashlib
import json
from datetime import UTC, datetime, time, timedelta

import httpx
import pytest
from google.protobuf.json_format import MessageToJson
from livekit import api as lk
from temporalio.testing import ActivityEnvironment

import nafas_core.config
from nafas_consultation.activities import ConsultationActivities
from nafas_consultation.fake_rooms import FakeRooms
from nafas_consultation.logic import transcript
from nafas_consultation.rooms import LiveKitRooms, Track, room_name, set_rooms
from nafas_consultation.schemas import ConsultationRef
from nafas_core.clients.scheduling import SchedulingClient, set_scheduling
from nafas_core.db import session_scope
from nafas_core.interfaces.llm.fake import FakeLLM
from nafas_core.interfaces.stt.base import Segment, Transcript
from nafas_scheduling.api import app as scheduling_app
from nafas_scheduling.enums import AppointmentMode
from nafas_scheduling.logic import booking
from nafas_scheduling.models import AvailabilityRule, BookingSettings


async def online_visit(clinic, starts_in: timedelta = timedelta(minutes=5), mode=AppointmentMode.ONLINE) -> dict:
    """A confirmed appointment for the clinic's patient, starting on the next 5-minute mark after `starts_in`."""
    now = datetime.now(UTC)
    at = now + starts_in
    start = at.replace(second=0, microsecond=0) + timedelta(minutes=(5 - at.minute % 5) % 5 or 5)
    async with session_scope(doctor_id=clinic.doctor_id) as session:
        if not await session.get(BookingSettings, clinic.doctor_id):
            session.add(BookingSettings(doctor_id=clinic.doctor_id, timezone="UTC", slot_minutes=5, min_notice_minutes=0))
            for weekday in range(7):
                session.add(
                    AvailabilityRule(doctor_id=clinic.doctor_id, weekday=weekday, start_local=time(0), end_local=time(23, 55))
                )
            await session.flush()
        held = await booking.hold(
            session, doctor_id=clinic.doctor_id, patient_id=clinic.patient_id, start=start, now=now, mode=mode
        )
        confirmed = await booking.confirm(session, held.id, now)
        return {"appointment_id": confirmed.id, "start": start}


@pytest.fixture
async def rooms(api):
    fake = FakeRooms()
    set_rooms(fake)
    set_scheduling(SchedulingClient(httpx.AsyncClient(transport=httpx.ASGITransport(app=scheduling_app), base_url="http://s")))
    yield fake
    set_rooms(None)
    set_scheduling(None)


def join(api, appointment_id, role, person_id):
    return api.post(
        f"/internal/v1/appointments/{appointment_id}/join", json={"role": role, "person_id": str(person_id), "name": role}
    )


async def test_only_the_patient_and_doctor_join_and_only_around_the_visit(api, clinic, rooms):
    visit = await online_visit(clinic)
    later = await online_visit(clinic, starts_in=timedelta(hours=3))
    in_person = await online_visit(clinic, starts_in=timedelta(hours=5), mode=AppointmentMode.IN_PERSON)

    patient = await join(api, visit["appointment_id"], "patient", clinic.patient_id)
    doctor = await join(api, visit["appointment_id"], "doctor", clinic.doctor_id)
    stranger = await join(api, visit["appointment_id"], "patient", clinic.other_patient_id)
    other_doctor = await join(api, visit["appointment_id"], "doctor", clinic.other_doctor_id)
    early = await join(api, later["appointment_id"], "patient", clinic.patient_id)
    not_online = await join(api, in_person["appointment_id"], "patient", clinic.patient_id)

    room = room_name(clinic.doctor_id, visit["appointment_id"])
    assert patient.status_code == 200 and patient.json()["room"] == room
    assert patient.json()["token"] == f"token:{room}:patient:{clinic.patient_id}:patient"
    assert doctor.json()["token"].startswith(f"token:{room}:doctor:{clinic.doctor_id}")
    assert stranger.status_code == other_doctor.status_code == 404
    assert early.status_code == 409 and "too_early" in early.json()["detail"]
    assert not_online.status_code == 409 and "not_online" in not_online.json()["detail"]

    set_rooms(None)
    nafas_core.config._settings_instance = None
    assert (await join(api, visit["appointment_id"], "patient", clinic.patient_id)).status_code == 503


def hook(api, **event):
    return api.post("/webhooks/livekit", content=json.dumps(event), headers={"Authorization": "signed"})


async def test_each_microphone_is_recorded_and_the_last_file_starts_processing(api, clinic, rooms, consultation_events):
    visit = await online_visit(clinic)
    room = room_name(clinic.doctor_id, visit["appointment_id"])
    rooms.tracks[room] = [Track(f"doctor:{clinic.doctor_id}", "TR_doc"), Track(f"patient:{clinic.patient_id}", "TR_pat")]

    started = await api.post(f"/internal/v1/doctors/{clinic.doctor_id}/appointments/{visit['appointment_id']}/recording", json={})
    assert started.status_code == 201 and started.json()["tracks"] == 2
    cid = started.json()["consultation_id"]
    again = await api.post(f"/internal/v1/doctors/{clinic.doctor_id}/appointments/{visit['appointment_id']}/recording", json={})
    assert again.status_code == 409
    assert rooms.announced == [(room, {"recording": True, "consultation_id": cid})]
    assert sorted(t for _, t, _ in rooms.recording.values()) == ["TR_doc", "TR_pat"]
    kinds = [c["kind"] for c in await api.identity.consents(clinic.patient_id)]
    assert kinds.count("session_recording") == 1

    # the patient drops and comes back: their new microphone is recorded too; a stranger's webhook is refused
    assert (
        await hook(
            api, event="track_published", room=room, track_sid="TR_pat2", identity=f"patient:{clinic.patient_id}", audio=True
        )
    ).status_code == 204
    forged = await api.post("/webhooks/livekit", content="{}", headers={"Authorization": "forged"})
    assert forged.status_code == 401
    detail = (await api.get(f"/internal/v1/doctors/{clinic.doctor_id}/consultations/{cid}")).json()
    assert detail["part_count"] == 3 and detail["recording"] is True and detail["source"] == "online"

    stopped = await api.post(f"/internal/v1/doctors/{clinic.doctor_id}/consultations/{cid}/stop-recording")
    assert stopped.json() == {"consultation_id": cid, "status": "recording", "waiting_for_tracks": True}
    assert sorted(rooms.stopped) == sorted(rooms.recording) and rooms.announced[-1] == (room, {"recording": False})

    egress = list(rooms.recording)
    for egress_id, status in zip(egress, ["EGRESS_COMPLETE", "EGRESS_FAILED", "EGRESS_COMPLETE"], strict=True):
        _, _, key = rooms.recording[egress_id]
        if status == "EGRESS_COMPLETE":
            await api.storage.put(key, b"ogg", "audio/ogg")
        assert consultation_events.events == []
        await hook(api, event="egress_ended", room=room, egress_id=egress_id, egress_status=status)

    # the last file written: the visit goes to its workflow, the failed track left out
    assert consultation_events.events == [("finished", cid)]
    assert (await api.get(f"/internal/v1/doctors/{clinic.doctor_id}/consultations/{cid}")).json()["status"] == "transcribing"

    heard = {
        "doctor": Transcript("", "ar", [Segment(0, 3, "خير، إيه اللي تاعبك؟")]),
        "patient": Transcript("", "ar", [Segment(1, 4, "عندي صداع")]),
    }

    class BySpeaker:
        def __init__(self):
            self.order = []

        async def transcribe(self, audio, mime_type, language_hint=None, diarize=False):
            speaker = "doctor" if not self.order else "patient"
            self.order.append(speaker)
            return heard[speaker]

    acts = ConsultationActivities(api.storage, BySpeaker(), FakeLLM([]), api.identity, api.clinical, "m")
    await ActivityEnvironment().run(acts.transcribe, ConsultationRef(cid, str(clinic.doctor_id)))
    segments = (await api.get(f"/internal/v1/doctors/{clinic.doctor_id}/consultations/{cid}")).json()["transcript"]
    assert [(s["speaker"], s["text"]) for s in segments] == [("doctor", "خير، إيه اللي تاعبك؟"), ("patient", "عندي صداع")]
    assert transcript.for_prompt(segments).splitlines()[1].startswith("[00:") and "Patient: عندي صداع" in transcript.for_prompt(
        segments
    )


async def test_a_room_that_ends_while_recording_stops_it(api, clinic, rooms):
    visit = await online_visit(clinic)
    room = room_name(clinic.doctor_id, visit["appointment_id"])
    rooms.tracks[room] = [Track(f"doctor:{clinic.doctor_id}", "TR_doc")]
    cid = (
        await api.post(f"/internal/v1/doctors/{clinic.doctor_id}/appointments/{visit['appointment_id']}/recording", json={})
    ).json()["consultation_id"]

    await hook(api, event="room_finished", room=room)

    assert list(rooms.recording) == rooms.stopped
    detail = (await api.get(f"/internal/v1/doctors/{clinic.doctor_id}/consultations/{cid}")).json()
    assert detail["recording"] is False


def test_livekit_tokens_and_webhooks_are_signed_with_the_secret(monkeypatch):
    monkeypatch.setenv("LIVEKIT_URL", "ws://livekit.test:7880")
    monkeypatch.setenv("LIVEKIT_API_KEY", "devkey")
    monkeypatch.setenv("LIVEKIT_API_SECRET", "a-secret-that-is-long-enough-for-hs256")
    nafas_core.config._settings_instance = None
    rooms = LiveKitRooms()

    token = rooms.join_token("visit-x", "patient:p1", "Sara")
    claims = lk.TokenVerifier("devkey", "a-secret-that-is-long-enough-for-hs256").verify(token)
    assert claims.identity == "patient:p1" and claims.video.room == "visit-x" and claims.video.room_join

    event = lk.WebhookEvent(
        event="egress_ended",
        egress_info=lk.EgressInfo(egress_id="EG_1", room_name="visit-x", status=lk.EgressStatus.EGRESS_COMPLETE),
    )
    body = MessageToJson(event)
    digest = base64.b64encode(hashlib.sha256(body.encode()).digest()).decode()
    signed = lk.AccessToken("devkey", "a-secret-that-is-long-enough-for-hs256").with_sha256(digest).to_jwt()

    read = rooms.read_webhook(body, signed)
    assert (read.event, read.room, read.egress_id, read.egress_status) == ("egress_ended", "visit-x", "EG_1", "EGRESS_COMPLETE")
    with pytest.raises(ValueError):
        rooms.read_webhook(body, lk.AccessToken("devkey", "another-secret-entirely-and-long-enough").with_sha256(digest).to_jwt())
    with pytest.raises(ValueError):
        rooms.read_webhook(body.replace("EG_1", "EG_2"), signed)

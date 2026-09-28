"""
The patient's chat end to end: the gateway, the conversation workflow on a
real Temporal, the real conversation activities with a scripted model, and
the real identity and scheduling services over the database.
"""

import json
from datetime import time

import pytest
from temporalio.worker import Worker

from nafas_conversation.activities import ConversationActivities
from nafas_conversation.logic.turn import Models
from nafas_conversation.logic.voice import VoiceProviders
from nafas_conversation.prompts import intent as intent_prompt
from nafas_conversation.workflows import WORKFLOWS
from nafas_core.clients.conversation import send_patient_message
from nafas_core.clients.identity import get_identity
from nafas_core.clients.scheduling import get_scheduling
from nafas_core.interfaces.dialect.fake import FakeDialectClassifier
from nafas_core.interfaces.llm.fake import FakeLLM, tool_use_message
from nafas_core.interfaces.storage.factory import set_storage
from nafas_core.interfaces.storage.fake import InMemoryStorage
from nafas_core.interfaces.stt.fake import FakeSTT
from nafas_core.interfaces.tts.fake import FakeTTS
from nafas_gateway.main import app as gateway
from nafas_gateway.routes.chat import chat_sender

from .conftest import DOCTOR_PASSWORD, browser, consent_to_chat, next_wednesday, sign_up


def classified(intent: str):
    return tool_use_message(intent_prompt.TOOL["name"], {"intent": intent})


@pytest.fixture
def conversation(doctor_id, temporal, task_queue):
    """The conversation service's worker with a scripted model, and the gateway pointed at it."""

    def run(llm, voice=None):
        activities = ConversationActivities(llm, get_identity(), get_scheduling(), Models("chat", "classifier"), voice)

        async def sender(*, patient_id, doctor_id, text, audio_key, audio_mime, stream_id=None):
            return await send_patient_message(
                temporal,
                patient_id=patient_id,
                doctor_id=doctor_id,
                text=text,
                audio_key=audio_key,
                audio_mime=audio_mime,
                stream_id=stream_id,
                task_queue=task_queue,
            )

        gateway.dependency_overrides[chat_sender] = lambda: sender
        return Worker(temporal, task_queue=task_queue, workflows=WORKFLOWS, activities=activities.all())

    yield run
    gateway.dependency_overrides.pop(chat_sender, None)


async def test_a_time_held_in_chat_is_confirmed_with_the_slot_picker(doctor_id, conversation):
    start = next_wednesday(time(17, 40))
    llm = FakeLLM(
        [
            classified("booking"),
            tool_use_message("hold", {"start": start.isoformat()}),
            "حجزتلك الأربعاء الساعة ٥:٤٠. تأكد؟",
        ]
    )

    async with conversation(llm), browser() as sara:
        await sign_up(sara)
        await consent_to_chat(sara, doctor_id)
        sent = await sara.post(f"/api/chat/{doctor_id}/messages", json={"text": "عايز الأربعاء ٥:٤٠"})
        assert sent.status_code == 200
        reply = sent.json()
        assert reply["text"] == "حجزتلك الأربعاء الساعة ٥:٤٠. تأكد؟"
        assert reply["intent"] == "booking" and reply["patient_text"] == "عايز الأربعاء ٥:٤٠"
        [action] = reply["actions"]
        assert action["type"] == "hold"

        # the chat's hold is an ordinary appointment: the portal shows it and confirms it
        mine = (await sara.get("/api/appointments/mine")).json()
        assert [(a["appointment_id"], a["status"]) for a in mine] == [(action["appointment"]["appointment_id"], "held")]
        confirmed = await sara.post(f"/api/appointments/{mine[0]['appointment_id']}/confirm")
        assert confirmed.json()["status"] == "confirmed"

        thread = (await sara.get(f"/api/chat/{doctor_id}/messages")).json()

    assert [(m["role"], m["content"]) for m in thread] == [
        ("patient", "عايز الأربعاء ٥:٤٠"),
        ("assistant", "حجزتلك الأربعاء الساعة ٥:٤٠. تأكد؟"),
    ]


def server_sent_events(body: str) -> list[tuple[str, dict]]:
    events = []
    for block in body.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        events.append((lines["event"], json.loads(lines["data"])))
    return events


async def test_a_booking_reply_streams_as_it_is_written_then_arrives_whole(doctor_id, conversation):
    """
    The whole path: the gateway listens, the workflow runs the turn in its
    activity, the agent streams the model, and the pieces come back over
    Postgres NOTIFY before the complete reply closes the stream.
    """
    reply_text = "عندك ميعاد واحد بس. تحب أحجزلك ميعاد تاني؟"
    llm = FakeLLM([classified("booking"), tool_use_message("my_appointments", {}), reply_text])

    async with conversation(llm), browser() as sara:
        await sign_up(sara)
        await consent_to_chat(sara, doctor_id)
        response = await sara.post(f"/api/chat/{doctor_id}/messages/stream", json={"text": "مواعيدي ايه؟"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = server_sent_events(response.text)
    deltas = [data["text"] for name, data in events if name == "delta"]
    assert len(deltas) > 1, "the reply should arrive in pieces"
    assert "".join(deltas) == reply_text
    name, done = events[-1]
    assert name == "done" and done["text"] == reply_text and done["intent"] == "booking"


async def test_a_streamed_medical_answer_is_never_shown_before_its_guard(doctor_id, conversation):
    """Medical answers pass the output guard first: nothing of them streams, the reply arrives whole."""
    from nafas_conversation.prompts import safety as safety_prompt

    answer = "Salt matters: less than a teaspoon a day helps most people's blood pressure."
    llm = FakeLLM(
        [
            classified("medical"),
            tool_use_message(safety_prompt.SCOPE_TOOL["name"], {"verdict": "in_scope"}),
            tool_use_message(safety_prompt.SENSITIVITY_TOOL["name"], {"sensitive": False, "category": "general"}),
            answer,
            tool_use_message(safety_prompt.GUARD_TOOL["name"], {"verdict": "pass"}),
        ]
    )

    async with conversation(llm), browser() as sara:
        await sign_up(sara)
        await consent_to_chat(sara, doctor_id)
        response = await sara.post(f"/api/chat/{doctor_id}/messages/stream", json={"text": "does salt matter?"})

    events = server_sent_events(response.text)
    assert [name for name, _ in events] == ["done"]


async def test_chat_is_for_patients_and_known_doctors(doctor_id, conversation):
    async with conversation(FakeLLM()), browser() as sara, browser() as anonymous:
        await sign_up(sara)
        await consent_to_chat(sara, doctor_id)
        unknown = await sara.post("/api/chat/00000000-0000-0000-0000-000000000000/messages", json={"text": "hi"})
        empty = await sara.post(f"/api/chat/{doctor_id}/messages", json={"text": ""})
        stranger = await anonymous.post(f"/api/chat/{doctor_id}/messages", json={"text": "hi"})

    assert unknown.status_code == 404
    assert empty.status_code == 422
    assert stranger.status_code == 401


async def test_a_voice_note_is_answered_aloud_and_only_its_patient_can_play_it(doctor_id, conversation):
    storage = InMemoryStorage()
    set_storage(storage)
    tts = FakeTTS()
    voice = VoiceProviders(stt=FakeSTT("عايز أعرف العيادة فين"), tts=tts, storage=storage, dialects=FakeDialectClassifier())
    llm = FakeLLM([classified("admin"), "العيادة في المعادي، شارع ٩."])

    try:
        async with conversation(llm, voice), browser() as sara, browser() as omar:
            await sign_up(sara)
            await consent_to_chat(sara, doctor_id)
            await sara.patch("/api/me/profile", json={"dialect": "eg", "voice": "female"})
            await sign_up(omar, email="omar@example.com", name="عمر")

            refused = await sara.post(f"/api/chat/{doctor_id}/voice", files={"audio": ("note.txt", b"hi", "text/plain")})
            sent = await sara.post(
                f"/api/chat/{doctor_id}/voice", files={"audio": ("note.webm", b"webm-bytes", "audio/webm;codecs=opus")}
            )
            reply = sent.json()
            played = await sara.get(f"/api/chat/{doctor_id}/messages/{reply['message_id']}/audio")
            stolen = await omar.get(f"/api/chat/{doctor_id}/messages/{reply['message_id']}/audio")
            suggestion = await sara.get("/api/me/dialect-suggestion")
    finally:
        set_storage(None)

    assert refused.status_code == 415
    assert sent.status_code == 200
    assert (reply["patient_text"], reply["text"], reply["intent"]) == (
        "عايز أعرف العيادة فين",
        "العيادة في المعادي، شارع ٩.",
        "admin",
    )
    # the note is stored under this doctor and patient, and the reply spoken with the number as a word
    [note] = [key for key in storage.objects if key.endswith(".webm")]
    assert note.startswith(f"doctor/{doctor_id}/patient/")
    assert tts.calls == [{"text": "العيادة في المعادي، شارع تسعة.", "dialect": "eg", "voice": "female"}]
    assert played.status_code == 307 and played.headers["location"].startswith(f"memory://get/{reply['audio_key']}")
    assert stolen.status_code == 404
    # one reading is not enough to suggest anything
    assert suggestion.json() == {"dialect": None}


async def test_chat_waits_for_consent_and_stops_when_it_is_revoked(doctor_id, conversation):
    llm = FakeLLM([classified("smalltalk"), "أهلاً"])
    async with conversation(llm), browser() as sara:
        await sign_up(sara)
        before = await sara.post(f"/api/chat/{doctor_id}/messages", json={"text": "أهلاً"})

        await consent_to_chat(sara, doctor_id)
        # consenting twice gives the same consent, not a second one
        await consent_to_chat(sara, doctor_id)
        given = (await sara.get("/api/me/consents")).json()
        allowed = await sara.post(f"/api/chat/{doctor_id}/messages", json={"text": "أهلاً"})

        ai_chat = next(c for c in given if c["kind"] == "ai_chat")
        await sara.post(f"/api/me/consents/{ai_chat['consent_id']}/revoke")
        after = await sara.post(f"/api/chat/{doctor_id}/messages", json={"text": "أهلاً"})

    assert (before.status_code, before.json()["reason"]) == (403, "consent_required")
    assert sorted((c["kind"], c["evidence"]) for c in given) == [
        ("ai_chat", "web:consent-v1"),
        ("data_processing", "web:consent-v1"),
    ]
    assert allowed.status_code == 200
    assert (after.status_code, after.json()["reason"]) == (403, "consent_required")


async def test_signing_up_needs_the_data_processing_box(doctor_id):
    async with browser() as sara:
        refused = await sara.post(
            "/api/auth/register",
            json={"email": "sara@example.com", "password": "patient password 123", "full_name": "سارة"},
        )

    assert refused.status_code == 422


async def test_a_dose_question_goes_to_the_doctor_whose_answer_appears_in_the_chat(doctor_id, conversation):
    from nafas_conversation.prompts import safety as safety_prompts

    llm = FakeLLM([classified("medical"), tool_use_message(safety_prompts.SCOPE_TOOL["name"], {"verdict": "in_scope"})])
    async with conversation(llm), browser() as sara, browser() as doctor:
        await sign_up(sara)
        await consent_to_chat(sara, doctor_id)
        start = next_wednesday(time(18)).isoformat()
        held = await sara.post("/api/appointments", json={"doctor_id": str(doctor_id), "start": start})
        await sara.post(f"/api/appointments/{held.json()['appointment_id']}/confirm")

        asked = (await sara.post(f"/api/chat/{doctor_id}/messages", json={"text": "ينفع أزود جرعة الدوا؟"})).json()

        await doctor.post("/api/auth/login", json={"email": "heart@example.com", "password": DOCTOR_PASSWORD})
        [item] = (await doctor.get("/api/doctor/escalations")).json()
        path = f"/api/doctor/escalations/{item['escalation_id']}/reply"
        answered = await doctor.post(path, json={"reply": "لا، نتكلم في الزيارة."})
        stolen = await sara.post(f"/api/doctor/escalations/{item['escalation_id']}/reply", json={"reply": "x"})
        thread = (await sara.get(f"/api/chat/{doctor_id}/messages")).json()

    assert asked["intent"] == "medical" and "د. قلب" in asked["text"]
    assert (item["patient_name"], item["reason"], item["question"]) == ("سارة", "sensitive", "ينفع أزود جرعة الدوا؟")
    assert answered.status_code == 200
    assert stolen.status_code == 403
    assert (thread[-1]["role"], thread[-1]["content"]) == ("doctor", "لا، نتكلم في الزيارة.")


async def test_a_patient_rates_a_reply_and_may_change_their_mind(doctor_id, conversation):
    async with conversation(FakeLLM([classified("other"), "العيادة بتفتح الساعة ٥."])), browser() as sara, browser() as omar:
        await sign_up(sara)
        await consent_to_chat(sara, doctor_id)
        await sara.post(f"/api/chat/{doctor_id}/messages", json={"text": "العيادة بتفتح إمتى؟"})
        question, reply = (await sara.get(f"/api/chat/{doctor_id}/messages")).json()

        down = await sara.put(f"/api/chat/{doctor_id}/messages/{reply['message_id']}/feedback", json={"rating": "down"})
        up = await sara.put(f"/api/chat/{doctor_id}/messages/{reply['message_id']}/feedback", json={"rating": "up"})
        own_message = await sara.put(f"/api/chat/{doctor_id}/messages/{question['message_id']}/feedback", json={"rating": "up"})
        await sign_up(omar, email="omar@example.com", name="عمر")
        someone_else = await omar.put(f"/api/chat/{doctor_id}/messages/{reply['message_id']}/feedback", json={"rating": "down"})
        thread = (await sara.get(f"/api/chat/{doctor_id}/messages")).json()

    assert (down.status_code, up.status_code) == (204, 204)
    assert own_message.status_code == 404 and someone_else.status_code == 404
    assert [m["feedback"] for m in thread] == [None, "up"]

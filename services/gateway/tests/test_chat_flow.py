"""
The patient's chat end to end: the gateway, the conversation workflow on a
real Temporal, the real conversation activities with a scripted model, and
the real identity and scheduling services over the database.
"""

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

from .conftest import browser, next_wednesday, sign_up


def classified(intent: str):
    return tool_use_message(intent_prompt.TOOL["name"], {"intent": intent})


@pytest.fixture
def conversation(doctor_id, temporal, task_queue):
    """The conversation service's worker with a scripted model, and the gateway pointed at it."""

    def run(llm, voice=None):
        activities = ConversationActivities(llm, get_identity(), get_scheduling(), Models("chat", "classifier"), voice)

        async def sender(*, patient_id, doctor_id, text, audio_key, audio_mime):
            return await send_patient_message(
                temporal,
                patient_id=patient_id,
                doctor_id=doctor_id,
                text=text,
                audio_key=audio_key,
                audio_mime=audio_mime,
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


async def test_chat_is_for_patients_and_known_doctors(doctor_id, conversation):
    async with conversation(FakeLLM()), browser() as sara, browser() as anonymous:
        await sign_up(sara)
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

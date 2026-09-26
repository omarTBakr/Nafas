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
from nafas_conversation.prompts import intent as intent_prompt
from nafas_conversation.workflows import WORKFLOWS
from nafas_core.clients.conversation import send_patient_message
from nafas_core.clients.identity import get_identity
from nafas_core.clients.scheduling import get_scheduling
from nafas_core.interfaces.llm.fake import FakeLLM, tool_use_message
from nafas_gateway.main import app as gateway
from nafas_gateway.routes.chat import chat_sender

from .conftest import browser, next_wednesday, sign_up


def classified(intent: str):
    return tool_use_message(intent_prompt.TOOL["name"], {"intent": intent})


@pytest.fixture
def conversation(doctor_id, temporal, task_queue):
    """The conversation service's worker with a scripted model, and the gateway pointed at it."""

    def run(llm):
        activities = ConversationActivities(llm, get_identity(), get_scheduling(), Models("chat", "classifier"))

        async def sender(*, patient_id, doctor_id, text, audio_key):
            return await send_patient_message(
                temporal, patient_id=patient_id, doctor_id=doctor_id, text=text, audio_key=audio_key, task_queue=task_queue
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

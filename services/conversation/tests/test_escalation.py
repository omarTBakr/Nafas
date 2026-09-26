"""Escalations: the waiting workflow's timing, and a question's whole way from a gate to the doctor's answer in the chat."""

import asyncio
import uuid

import httpx
import pytest
from temporalio import activity
from temporalio.client import WorkflowExecutionStatus
from temporalio.worker import Worker

import nafas_core.config
from nafas_conversation.activities import ConversationActivities
from nafas_conversation.api import app as conversation_app
from nafas_conversation.client import send_patient_message
from nafas_conversation.enums import MessageRole
from nafas_conversation.logic import messages
from nafas_conversation.logic.turn import Models
from nafas_conversation.prompts import replies
from nafas_conversation.schemas import DOCTOR_REPLIED_SIGNAL, ESCALATION_WORKFLOW, EscalationNotice, EscalationStart
from nafas_conversation.workflows import WORKFLOWS
from nafas_core.interfaces.llm.fake import FakeLLM

from .test_medical import Clinic, classified, scoped


class FakeTelling:
    def __init__(self, still_open: bool = True):
        self.still_open = still_open
        self.told: list[str] = []

    @activity.defn(name="conversation.tell_patient_about_escalation")
    async def tell(self, notice: EscalationNotice) -> bool:
        if not self.still_open:
            return False
        self.told.append("expired" if notice.expire else "nudge")
        return True


async def wait_for(temporal, task_queue, fakes, nudge, expire, act=None) -> str:
    start = EscalationStart(str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4()), nudge, expire)
    async with Worker(temporal, task_queue=task_queue, workflows=WORKFLOWS, activities=[fakes.tell]):
        handle = await temporal.start_workflow(
            ESCALATION_WORKFLOW, start, id=f"escalation-{start.escalation_id}", task_queue=task_queue
        )
        if act:
            await act(handle)
        return await handle.result()


async def test_an_unanswered_question_is_nudged_then_expires(temporal, task_queue):
    fakes = FakeTelling()

    assert await wait_for(temporal, task_queue, fakes, 1, 2) == "expired"
    assert fakes.told == ["nudge", "expired"]


async def test_an_answer_stops_the_clock(temporal, task_queue):
    fakes = FakeTelling()

    async def answer(handle):
        await asyncio.sleep(0.3)
        await handle.signal(DOCTOR_REPLIED_SIGNAL)

    assert await wait_for(temporal, task_queue, fakes, 3, 6, answer) == "answered"
    assert fakes.told == []


async def test_an_answer_whose_signal_was_lost_still_wins(temporal, task_queue):
    fakes = FakeTelling(still_open=False)

    assert await wait_for(temporal, task_queue, fakes, 1, 2) == "answered"


@pytest.fixture
async def conversation_api(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_TOKEN", "internal-secret")
    nafas_core.config._settings_instance = None
    headers = {"X-Internal-Token": "internal-secret"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=conversation_app), base_url="http://c", headers=headers) as c:
        yield c


async def test_a_sensitive_question_reaches_the_doctor_and_their_answer_the_patient(
    parties, temporal, task_queue, conversation_api, escalation_events
):
    clinic = Clinic(parties.doctor_id)
    activities = ConversationActivities(FakeLLM([classified("medical"), scoped("in_scope")]), clinic, clinic, Models("c", "k"))
    party = {"patient_id": str(parties.patient_id), "doctor_id": str(parties.doctor_id)}

    async with Worker(temporal, task_queue=task_queue, workflows=WORKFLOWS, activities=activities.all()):
        reply = await send_patient_message(temporal, **party, text="ينفع أزود جرعة الدوا؟", task_queue=task_queue)

        inbox = (await conversation_api.get(f"/internal/v1/doctors/{parties.doctor_id}/escalations")).json()
        [item] = inbox
        waiting = temporal.get_workflow_handle(f"escalation-{item['escalation_id']}")
        assert (await waiting.describe()).status == WorkflowExecutionStatus.RUNNING

        path = f"/internal/v1/doctors/{parties.doctor_id}/escalations/{item['escalation_id']}/reply"
        answered = await conversation_api.post(path, json={"reply": "لا تغيّر الجرعة، نتكلم في الزيارة يوم الأربعاء."})
        again = await conversation_api.post(path, json={"reply": "twice"})
        stranger = await conversation_api.post(
            f"/internal/v1/doctors/{uuid.uuid4()}/escalations/{item['escalation_id']}/reply", json={"reply": "x"}
        )
        await waiting.signal(DOCTOR_REPLIED_SIGNAL)
        outcome = await waiting.result()
        await temporal.get_workflow_handle(f"conv-{parties.doctor_id}-{parties.patient_id}").terminate()

    assert reply.text == replies.ESCALATED["ar"].format(doctor="د. قلب")
    assert (item["reason"], item["status"], item["question"]) == ("sensitive", "open", "ينفع أزود جرعة الدوا؟")
    assert answered.status_code == 200 and answered.json()["status"] == "answered"
    assert again.status_code == 409 and stranger.status_code == 404
    assert escalation_events.answered_ids == [item["escalation_id"]]
    assert outcome == "answered"

    thread = await messages.patient_thread(parties.patient_id, parties.doctor_id, 10)
    assert [(m.role, m.content) for m in thread][-1] == (MessageRole.DOCTOR, "لا تغيّر الجرعة، نتكلم في الزيارة يوم الأربعاء.")
    # the reply that told the patient carries the gates' verdicts
    assert thread[1].safety["escalated"] == "sensitive" and thread[1].safety["sensitivity"] == "medication"

"""PatientConversationWorkflow's order of work, over fake activities: no database, no model."""

import asyncio
import uuid

import pytest
from temporalio import activity
from temporalio.client import WorkflowExecutionStatus, WorkflowUpdateFailedError
from temporalio.worker import Worker

from nafas_conversation.client import send_patient_message
from nafas_conversation.schemas import ConversationStart, StoredMessage, StoredReply, TurnRequest, TurnResult
from nafas_conversation.workflows import WORKFLOWS, PatientConversationWorkflow
from nafas_core.clients.conversation import conversation_workflow_id


class FakeActivities:
    """Records what the workflow asked for, and checks turns never overlap."""

    def __init__(self):
        self.opened = 0
        self.saved: list[str] = []
        self.replies: list[StoredReply] = []
        self.answering = 0
        self.overlapped = False

    @activity.defn(name="conversation.open")
    async def open_conversation(self, start: ConversationStart) -> str:
        self.opened += 1
        return "c-1"

    @activity.defn(name="conversation.save_patient_message")
    async def save_patient_message(self, message: StoredMessage) -> None:
        self.saved.append(message.content)

    @activity.defn(name="conversation.answer")
    async def answer(self, request: TurnRequest) -> TurnResult:
        self.answering += 1
        self.overlapped |= self.answering > 1
        await asyncio.sleep(0.2)
        self.answering -= 1
        last = self.saved[-1]
        actions = [{"type": "hold"}] if "hold" in last else []
        return TurnResult(f"reply to {last}", "fake", "booking-v1", 10, 5, actions, intent="booking")

    @activity.defn(name="conversation.save_reply")
    async def save_reply(self, reply: StoredReply) -> None:
        self.replies.append(reply)

    def all(self):
        return [self.open_conversation, self.save_patient_message, self.answer, self.save_reply]


def ids() -> dict:
    return {"patient_id": str(uuid.uuid4()), "doctor_id": str(uuid.uuid4())}


async def test_first_message_starts_the_conversation_and_returns_the_reply(temporal, task_queue):
    fakes = FakeActivities()
    party = ids()
    async with Worker(temporal, task_queue=task_queue, workflows=WORKFLOWS, activities=fakes.all()):
        reply = await send_patient_message(temporal, **party, text="  عايز أحجز hold  ", task_queue=task_queue)

    assert reply.text == "reply to عايز أحجز hold"
    assert reply.actions == [{"type": "hold"}]
    assert reply.conversation_id == "c-1"
    assert (reply.intent, reply.patient_text) == ("booking", "عايز أحجز hold")
    # the reply carries its intent back onto the message it answers
    assert fakes.replies[0].intent == "booking" and fakes.replies[0].answers_message_id
    assert fakes.saved == ["عايز أحجز hold"]
    assert fakes.replies[0].message_id == reply.message_id
    assert (fakes.replies[0].model, fakes.replies[0].prompt_version, fakes.replies[0].tokens_in) == ("fake", "booking-v1", 10)


async def test_messages_sent_together_are_answered_one_at_a_time_in_order(temporal, task_queue):
    fakes = FakeActivities()
    party = ids()
    async with Worker(temporal, task_queue=task_queue, workflows=WORKFLOWS, activities=fakes.all()):
        first = await send_patient_message(temporal, **party, text="one", task_queue=task_queue)
        # sent at once: the second must wait for the first reply
        second, third = await asyncio.gather(
            send_patient_message(temporal, **party, text="two", task_queue=task_queue),
            send_patient_message(temporal, **party, text="three", task_queue=task_queue),
        )

    assert not fakes.overlapped
    assert fakes.opened == 1
    assert first.text == "reply to one"
    # each reply answers its own message, whichever arrived first
    assert {second.text, third.text} == {"reply to two", "reply to three"}
    assert len({first.message_id, second.message_id, third.message_id}) == 3


async def test_an_empty_or_huge_message_is_refused_before_it_is_stored(temporal, task_queue):
    fakes = FakeActivities()
    party = ids()
    async with Worker(temporal, task_queue=task_queue, workflows=WORKFLOWS, activities=fakes.all()):
        with pytest.raises(WorkflowUpdateFailedError):
            await send_patient_message(temporal, **party, text="   ", task_queue=task_queue)
        with pytest.raises(WorkflowUpdateFailedError):
            await send_patient_message(temporal, **party, text="x" * 5000, task_queue=task_queue)
        # the conversation is still there and still answers
        reply = await send_patient_message(temporal, **party, text="hello", task_queue=task_queue)

    assert fakes.saved == ["hello"]
    assert reply.text == "reply to hello"


async def test_it_continues_as_new_and_keeps_the_same_thread(temporal, task_queue):
    fakes = FakeActivities()
    party = ids()
    workflow_id = conversation_workflow_id(party["doctor_id"], party["patient_id"])
    async with Worker(temporal, task_queue=task_queue, workflows=WORKFLOWS, activities=fakes.all()):
        handle = await temporal.start_workflow(
            PatientConversationWorkflow.run,
            ConversationStart(**party, turns_per_run=2),
            id=workflow_id,
            task_queue=task_queue,
        )
        for text in ("one", "two"):
            await send_patient_message(temporal, **party, text=text, task_queue=task_queue)

        first_run = temporal.get_workflow_handle(workflow_id, run_id=handle.result_run_id)
        for _ in range(50):
            if (await first_run.describe()).status == WorkflowExecutionStatus.CONTINUED_AS_NEW:
                break
            await asyncio.sleep(0.1)
        assert (await first_run.describe()).status == WorkflowExecutionStatus.CONTINUED_AS_NEW

        reply = await send_patient_message(temporal, **party, text="three", task_queue=task_queue)
        latest = await temporal.get_workflow_handle(workflow_id).describe()
        await temporal.get_workflow_handle(workflow_id).terminate()

    assert latest.run_id != handle.result_run_id
    assert reply.conversation_id == "c-1"
    # the new run carried the conversation over instead of looking it up again
    assert fakes.opened == 1
    assert fakes.saved == ["one", "two", "three"]

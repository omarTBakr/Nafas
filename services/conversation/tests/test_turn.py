"""The booking turn with its context, alone and end to end through the workflow and the database."""

import uuid
from datetime import UTC, datetime

from temporalio.worker import Worker

from nafas_conversation.activities import ConversationActivities
from nafas_conversation.client import send_patient_message
from nafas_conversation.enums import MessageRole
from nafas_conversation.logic import messages
from nafas_conversation.logic.turn import answer_booking
from nafas_conversation.prompts.booking import APOLOGIES, PROMPT_VERSION, TOOLS
from nafas_conversation.workflows import WORKFLOWS
from nafas_core.interfaces.llm.fake import FakeLLM

DOCTOR = {
    "full_name_en": "Dr Heart",
    "full_name_ar": "د. قلب",
    "specialization_en": "Cardiology",
    "specialization_ar": "أمراض القلب",
}


class FakeDirectory:
    """Stands in for both identity and scheduling: the lookups a turn makes before the model."""

    def __init__(self, preferred_language: str = "ar", dialect: str | None = "eg", fail: bool = False):
        self.profile_body = {"preferred_language": preferred_language, "dialect": dialect}
        self.fail = fail

    async def profile(self, patient_id):
        return self.profile_body

    async def doctor(self, doctor_id):
        if self.fail:
            raise ConnectionError("identity is down")
        return DOCTOR

    async def booking_info(self, doctor_id):
        return {"timezone": "Africa/Cairo"}


NOW = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)
HISTORY = [{"role": "user", "content": "عايز أحجز"}]


async def test_the_prompt_is_in_the_patients_language_and_clinic_time():
    llm = FakeLLM(["تمام"])
    directory = FakeDirectory()

    reply = await answer_booking(
        llm, directory, directory, patient_id=uuid.uuid4(), doctor_id=uuid.uuid4(), history=HISTORY, model="m", now=NOW
    )

    request = llm.requests[0]
    assert reply.text == "تمام"
    assert reply.prompt_version == PROMPT_VERSION
    assert "د. قلب" in request["system"] and "Egyptian Arabic" in request["system"]
    # 12:00 UTC is 15:00 in Cairo
    assert "Saturday 26 September 2026, 15:00" in request["system"]
    assert request["tools"] == TOOLS and request["model"] == "m"


async def test_an_english_patient_gets_english_names():
    llm = FakeLLM(["Sure"])
    directory = FakeDirectory(preferred_language="en", dialect=None)

    await answer_booking(
        llm, directory, directory, patient_id=uuid.uuid4(), doctor_id=uuid.uuid4(), history=HISTORY, model="m", now=NOW
    )

    assert "Dr Heart, a Cardiology doctor" in llm.requests[0]["system"]


async def test_a_failing_lookup_becomes_an_apology_in_their_language():
    directory = FakeDirectory(preferred_language="en", fail=True)

    reply = await answer_booking(
        FakeLLM(), directory, directory, patient_id=uuid.uuid4(), doctor_id=uuid.uuid4(), history=HISTORY, model="m", now=NOW
    )

    assert reply.text == APOLOGIES["en"]


async def test_a_conversation_end_to_end(parties, temporal, task_queue):
    llm = FakeLLM(["أهلاً! تحب تيجي إمتى؟", "تمام، هشوف الأربعاء."])
    directory = FakeDirectory()
    activities = ConversationActivities(llm, directory, directory, "claude-sonnet-5")
    party = {"patient_id": str(parties.patient_id), "doctor_id": str(parties.doctor_id)}

    async with Worker(temporal, task_queue=task_queue, workflows=WORKFLOWS, activities=activities.all()):
        first = await send_patient_message(temporal, **party, text="عايز أحجز", task_queue=task_queue)
        second = await send_patient_message(temporal, **party, text="الأربعاء", task_queue=task_queue)
        await temporal.get_workflow_handle(f"conv-{parties.doctor_id}-{parties.patient_id}").terminate()

    assert (first.text, second.text) == ("أهلاً! تحب تيجي إمتى؟", "تمام، هشوف الأربعاء.")
    # the second turn saw the whole thread, from the database
    assert [m["content"] for m in llm.requests[1]["messages"]] == ["عايز أحجز", "أهلاً! تحب تيجي إمتى؟", "الأربعاء"]

    stored = await messages.recent_messages(parties.patient_id, uuid.UUID(first.conversation_id))
    assert [m.role for m in stored] == [MessageRole.PATIENT, MessageRole.ASSISTANT] * 2
    assert stored[1].id == uuid.UUID(first.message_id)
    assert (stored[1].model, stored[1].prompt_version) == ("fake", PROMPT_VERSION)

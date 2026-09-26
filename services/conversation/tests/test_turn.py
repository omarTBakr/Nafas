"""The patient turn: routing by intent, the booking prompt's context, and end to end through the workflow and the database."""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from temporalio.worker import Worker

from nafas_conversation.activities import ConversationActivities
from nafas_conversation.client import send_patient_message
from nafas_conversation.enums import EscalationReason, Intent, MessageRole
from nafas_conversation.logic import messages
from nafas_conversation.logic.turn import FIXED, Models, answer_turn
from nafas_conversation.prompts import intent as intent_prompt
from nafas_conversation.prompts import replies
from nafas_conversation.prompts.booking import APOLOGIES, PROMPT_VERSION, TOOLS
from nafas_conversation.workflows import WORKFLOWS
from nafas_core.exceptions.providers import LLMError
from nafas_core.interfaces.llm.fake import FakeLLM, tool_use_message

DOCTOR = {
    "full_name_en": "Dr Heart",
    "full_name_ar": "د. قلب",
    "specialization_en": "Cardiology",
    "specialization_ar": "أمراض القلب",
}
MODELS = Models(chat="chat-model", classifier="classifier-model")
NOW = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)


def classified(intent: str):
    return tool_use_message(intent_prompt.TOOL["name"], {"intent": intent})


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


class FailingLLM:
    def __init__(self):
        self.requests = []

    async def create(self, **params):
        self.requests.append(params)
        raise LLMError("the model is down")


async def turn(llm, text: str, directory: FakeDirectory | None = None):
    directory = directory or FakeDirectory()
    return await answer_turn(
        llm,
        directory,
        directory,
        patient_id=uuid.uuid4(),
        doctor_id=uuid.uuid4(),
        history=[{"role": "user", "content": text}],
        models=MODELS,
        now=NOW,
    )


async def test_booking_goes_to_the_assistant_in_the_patients_language_and_clinic_time():
    llm = FakeLLM([classified("booking"), "تمام"])

    result = await turn(llm, "عايز أحجز")

    classifier, agent = llm.requests
    assert classifier["model"] == "classifier-model"
    assert classifier["tool_choice"] == {"type": "tool", "name": "record_intent"}
    assert (result.intent, result.reply.text, result.reply.prompt_version) == (Intent.BOOKING, "تمام", PROMPT_VERSION)
    assert agent["model"] == "chat-model" and agent["tools"] == TOOLS
    assert "د. قلب" in agent["system"] and "Egyptian Arabic" in agent["system"]
    # 12:00 UTC is 15:00 in Cairo
    assert "Saturday 26 September 2026, 15:00" in agent["system"]


async def test_an_english_patient_gets_english_names():
    llm = FakeLLM([classified("smalltalk"), "Hello!"])

    result = await turn(llm, "hi", FakeDirectory(preferred_language="en", dialect=None))

    assert result.intent is Intent.SMALLTALK
    assert "Dr Heart, a Cardiology doctor" in llm.requests[1]["system"]


@pytest.mark.parametrize(
    "text",
    [
        "عندي ألم شديد في الصدر",
        "مش قادر اتنفس خالص",
        "I have crushing chest pain",
        "بفكر أنتحر",
        "my dad just passed out",
    ],
)
async def test_emergency_words_get_the_fixed_reply_without_any_model(text):
    llm = FakeLLM()

    result = await turn(llm, text)

    assert llm.requests == []
    assert result.intent is Intent.EMERGENCY
    assert result.reply.text == replies.EMERGENCY["ar"] and result.reply.model == FIXED
    # and the doctor hears of it
    assert result.escalation is EscalationReason.EMERGENCY


async def test_an_emergency_the_keywords_miss_is_caught_by_the_classifier():
    result = await turn(
        FakeLLM([classified("emergency")]), "Something is very wrong, my lips are turning blue", FakeDirectory("en")
    )

    assert result.intent is Intent.EMERGENCY and result.reply.text == replies.EMERGENCY["en"]


async def test_a_classifier_failure_falls_back_to_the_booking_assistant():
    llm = FakeLLM([tool_use_message("something_else", {}), "أهلاً"])

    result = await turn(llm, "مساء الخير")

    assert result.intent is Intent.BOOKING and result.reply.text == "أهلاً"


async def test_a_model_that_is_down_gives_an_apology_in_their_language():
    result = await turn(FailingLLM(), "book me", FakeDirectory("en"))

    assert result.reply.text == APOLOGIES["en"]


async def test_a_failing_lookup_becomes_an_apology_in_their_language():
    result = await turn(FakeLLM([classified("booking")]), "book me", FakeDirectory(preferred_language="en", fail=True))

    assert result.reply.text == APOLOGIES["en"]


async def test_a_conversation_end_to_end(parties, temporal, task_queue, database):
    llm = FakeLLM([classified("booking"), "أهلاً! تحب تيجي إمتى؟", classified("booking"), "تمام، هشوف الأربعاء."])
    directory = FakeDirectory()
    activities = ConversationActivities(llm, directory, directory, MODELS)
    party = {"patient_id": str(parties.patient_id), "doctor_id": str(parties.doctor_id)}

    async with Worker(temporal, task_queue=task_queue, workflows=WORKFLOWS, activities=activities.all()):
        first = await send_patient_message(temporal, **party, text="عايز أحجز", task_queue=task_queue)
        second = await send_patient_message(temporal, **party, text="الأربعاء", task_queue=task_queue)
        await temporal.get_workflow_handle(f"conv-{parties.doctor_id}-{parties.patient_id}").terminate()

    assert (first.text, second.text) == ("أهلاً! تحب تيجي إمتى؟", "تمام، هشوف الأربعاء.")
    # the second turn saw the whole thread, from the database
    assert [m["content"] for m in llm.requests[3]["messages"]] == ["عايز أحجز", "أهلاً! تحب تيجي إمتى؟", "الأربعاء"]

    stored = await messages.patient_thread(parties.patient_id, parties.doctor_id, 10)
    assert [m.role for m in stored] == [MessageRole.PATIENT, MessageRole.ASSISTANT] * 2
    assert stored[1].id == uuid.UUID(first.message_id)
    assert (stored[1].model, stored[1].prompt_version) == ("fake", PROMPT_VERSION)
    # both sides of each turn carry its intent
    assert {m.intent for m in stored} == {Intent.BOOKING}

    # each time the model read the thread, the audit log says so
    owner = create_async_engine(database)
    try:
        async with owner.connect() as connection:
            reads = (
                await connection.execute(
                    text("SELECT actor_type, action, patient_id FROM audit.audit_log WHERE service = 'conversation'")
                )
            ).all()
    finally:
        await owner.dispose()
    assert [tuple(r) for r in reads] == [("model", "read_thread", parties.patient_id)] * 2

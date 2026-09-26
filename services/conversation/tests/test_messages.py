import asyncio
import uuid

from sqlalchemy import select

from nafas_conversation.enums import MessageRole
from nafas_conversation.logic import messages
from nafas_conversation.models import Message
from nafas_core.db import session_scope


def message(role: MessageRole, content: str) -> Message:
    return Message(role=role, content=content)


def test_history_starts_with_the_patient_and_alternates():
    history = messages.model_history(
        [
            message(MessageRole.ASSISTANT, "orphaned reply"),
            message(MessageRole.PATIENT, "Wednesday?"),
            message(MessageRole.PATIENT, "evening please"),
            message(MessageRole.DOCTOR, "a doctor's note"),
            message(MessageRole.ASSISTANT, "17:40 is free"),
        ]
    )

    assert history == [
        {"role": "user", "content": "Wednesday?\n\nevening please"},
        {"role": "assistant", "content": "17:40 is free"},
    ]


async def test_opening_twice_at_once_gives_one_conversation(parties):
    ids = await asyncio.gather(*(messages.open_conversation(parties.patient_id, parties.doctor_id) for _ in range(3)))

    assert len(set(ids)) == 1


async def test_a_retried_insert_stores_the_message_once(parties):
    conversation_id = await messages.open_conversation(parties.patient_id, parties.doctor_id)
    message_id = uuid.uuid4()
    for _ in range(2):
        await messages.add_patient_message(parties.patient_id, message_id, conversation_id, "بكرة العصر")
    await messages.add_assistant_message(
        parties.patient_id,
        uuid.uuid4(),
        conversation_id,
        text="الساعة ٥ فاضية",
        model="fake",
        prompt_version="booking-v1",
        tokens_in=10,
        tokens_out=5,
    )

    stored = await messages.recent_messages(parties.patient_id, conversation_id)
    assert [(m.role, m.content) for m in stored] == [
        (MessageRole.PATIENT, "بكرة العصر"),
        (MessageRole.ASSISTANT, "الساعة ٥ فاضية"),
    ]
    assert stored[1].prompt_version == "booking-v1"


async def test_another_patient_cannot_read_the_thread(parties):
    conversation_id = await messages.open_conversation(parties.patient_id, parties.doctor_id)
    await messages.add_patient_message(parties.patient_id, uuid.uuid4(), conversation_id, "private")

    assert await messages.recent_messages(parties.other_patient_id, conversation_id) == []
    # the doctor of the conversation can
    async with session_scope(doctor_id=parties.doctor_id) as session:
        seen = await session.scalars(select(Message.content).where(Message.conversation_id == conversation_id))
        assert seen.all() == ["private"]

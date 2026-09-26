"""Conversations and their messages, always read and written in the patient's own scope."""

import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from nafas_conversation.enums import Intent, MessageRole
from nafas_conversation.models import Conversation, Message
from nafas_core.db import session_scope

# how much of the thread the model sees; older turns rarely matter to a booking
HISTORY_LIMIT = 40
MODEL_ROLES = {MessageRole.PATIENT: "user", MessageRole.ASSISTANT: "assistant"}


async def open_conversation(patient_id: uuid.UUID, doctor_id: uuid.UUID) -> uuid.UUID:
    """The patient's conversation with this doctor, created on first use; safe to call concurrently."""
    async with session_scope(patient_id=patient_id) as session:
        await session.execute(
            insert(Conversation)
            .values(id=uuid.uuid4(), patient_id=patient_id, doctor_id=doctor_id)
            .on_conflict_do_nothing(index_elements=["patient_id", "doctor_id"])
        )
        return await session.scalar(
            select(Conversation.id).where(Conversation.patient_id == patient_id, Conversation.doctor_id == doctor_id)
        )


async def add_message(patient_id: uuid.UUID, message_id: uuid.UUID, conversation_id: uuid.UUID, **fields) -> None:
    """Inserts one message; a second insert with the same id (a retry) changes nothing."""
    async with session_scope(patient_id=patient_id) as session:
        await session.execute(
            insert(Message)
            .values(id=message_id, conversation_id=conversation_id, **fields)
            .on_conflict_do_nothing(index_elements=["id"])
        )


async def add_patient_message(patient_id: uuid.UUID, message_id: uuid.UUID, conversation_id: uuid.UUID, text: str) -> None:
    await add_message(patient_id, message_id, conversation_id, role=MessageRole.PATIENT, content=text)


async def add_assistant_message(
    patient_id: uuid.UUID,
    message_id: uuid.UUID,
    conversation_id: uuid.UUID,
    *,
    text: str,
    model: str,
    prompt_version: str,
    tokens_in: int,
    tokens_out: int,
) -> None:
    await add_message(
        patient_id,
        message_id,
        conversation_id,
        role=MessageRole.ASSISTANT,
        content=text,
        intent=Intent.BOOKING,
        model=model,
        prompt_version=prompt_version,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
    )


async def recent_messages(patient_id: uuid.UUID, conversation_id: uuid.UUID, limit: int = HISTORY_LIMIT) -> list[Message]:
    """The last `limit` messages, oldest first."""
    async with session_scope(patient_id=patient_id) as session:
        rows = await session.scalars(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(limit)
        )
        return list(reversed(rows.all()))


def model_history(messages: list[Message]) -> list[dict]:
    """
    The thread as the model expects it: starting with the patient, roles
    alternating. Doctors' answers (phase 4) are not the assistant's words and
    are left out; two messages in a row from one side (a reply that failed to
    save) are joined rather than dropped.
    """
    history: list[dict] = []
    for message in messages:
        role = MODEL_ROLES.get(message.role)
        if role is None or (not history and role != "user"):
            continue
        if history and history[-1]["role"] == role:
            history[-1]["content"] += "\n\n" + message.content
        else:
            history.append({"role": role, "content": message.content})
    return history

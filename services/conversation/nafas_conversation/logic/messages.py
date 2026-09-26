"""Conversations and their messages, always read and written in the patient's own scope."""

import uuid

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

from nafas_conversation.enums import Intent, MessageRole, Modality
from nafas_conversation.exceptions import MessageNotFoundError
from nafas_conversation.models import Conversation, Message, ReplyFeedback
from nafas_core.db import session_scope
from nafas_core.metrics import REPLY_FEEDBACK

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


async def add_patient_message(
    patient_id: uuid.UUID,
    message_id: uuid.UUID,
    conversation_id: uuid.UUID,
    text: str,
    modality: Modality = Modality.TEXT,
    audio_key: str | None = None,
) -> None:
    await add_message(
        patient_id,
        message_id,
        conversation_id,
        role=MessageRole.PATIENT,
        content=text,
        modality=modality,
        audio_key=audio_key,
    )


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
    intent: Intent | None = None,
    answers_message_id: uuid.UUID | None = None,
    audio_key: str | None = None,
    safety: dict | None = None,
) -> None:
    """The reply, and the intent it was answered under on the message it answers."""
    await add_message(
        patient_id,
        message_id,
        conversation_id,
        role=MessageRole.ASSISTANT,
        content=text,
        intent=intent,
        model=model,
        prompt_version=prompt_version,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        audio_key=audio_key,
        modality=Modality.VOICE if audio_key else Modality.TEXT,
        safety=safety,
    )
    if intent is not None and answers_message_id is not None:
        async with session_scope(patient_id=patient_id) as session:
            await session.execute(update(Message).where(Message.id == answers_message_id).values(intent=intent))


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


async def patient_thread(patient_id: uuid.UUID, doctor_id: uuid.UUID, limit: int) -> list[Message]:
    """The patient's thread with this doctor, oldest first; empty before the first message."""
    async with session_scope(patient_id=patient_id) as session:
        conversation_id = await session.scalar(
            select(Conversation.id).where(Conversation.patient_id == patient_id, Conversation.doctor_id == doctor_id)
        )
    if conversation_id is None:
        return []
    return await recent_messages(patient_id, conversation_id, limit)


async def rate_reply(patient_id: uuid.UUID, doctor_id: uuid.UUID, message_id: uuid.UUID, rating: str) -> None:
    """The patient's thumbs on an assistant reply in their thread with this doctor; a second rating replaces the first."""
    async with session_scope(patient_id=patient_id) as session:
        reply = await session.scalar(
            select(Message.id)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(Message.id == message_id, Message.role == MessageRole.ASSISTANT, Conversation.doctor_id == doctor_id)
        )
        if reply is None:
            raise MessageNotFoundError(str(message_id))
        await session.execute(
            insert(ReplyFeedback)
            .values(message_id=message_id, patient_id=patient_id, doctor_id=doctor_id, rating=rating)
            .on_conflict_do_update(constraint="uq_reply_feedback_message", set_={"rating": rating})
        )
    REPLY_FEEDBACK.labels(rating).inc()


async def ratings(patient_id: uuid.UUID, message_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not message_ids:
        return {}
    async with session_scope(patient_id=patient_id) as session:
        rows = await session.execute(
            select(ReplyFeedback.message_id, ReplyFeedback.rating).where(ReplyFeedback.message_id.in_(message_ids))
        )
        return dict(rows.all())


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

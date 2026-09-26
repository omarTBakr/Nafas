"""The `conversation` schema. A patient sees their own conversations; a doctor, their patients'."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import ENUM, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from nafas_conversation.enums import EscalationReason, EscalationStatus, Intent, MessageRole, Modality
from nafas_core.db import Base

SCHEMA = "conversation"


def _enum(enum_cls, name: str) -> ENUM:
    return ENUM(enum_cls, name=name, schema=SCHEMA, values_callable=lambda e: [m.value for m in e], create_type=False)


def _now() -> datetime:
    return datetime.now(UTC)


class Conversation(Base):
    """
    One thread between a patient and the assistant of one doctor.

    doctor_id and patient_id refer into identity: foreign keys in the
    migration, plain columns here, so this service runs on its own code.
    """

    __tablename__ = "conversations"
    __table_args__ = (UniqueConstraint("patient_id", "doctor_id"), {"schema": SCHEMA})

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    doctor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, server_default=func.now())


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (Index("ix_messages_conversation_created", "conversation_id", "created_at"), {"schema": SCHEMA})

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.conversations.id", ondelete="CASCADE"))
    role: Mapped[MessageRole] = mapped_column(_enum(MessageRole, "message_role"))
    modality: Mapped[Modality] = mapped_column(_enum(Modality, "modality"), default=Modality.TEXT, server_default="text")
    # the text: what the patient typed, the transcript of their voice note, or the reply
    content: Mapped[str] = mapped_column(Text)
    # the voice note itself, in object storage
    audio_key: Mapped[str | None] = mapped_column(Text)
    intent: Mapped[Intent | None] = mapped_column(_enum(Intent, "intent"))
    # what produced an assistant message: which model and which prompt version,
    # so any reply can be traced to exactly what wrote it (PLAN §6b)
    model: Mapped[str | None] = mapped_column(String(64))
    prompt_version: Mapped[str | None] = mapped_column(String(64))
    tokens_in: Mapped[int | None] = mapped_column(Integer)
    tokens_out: Mapped[int | None] = mapped_column(Integer)
    # the dialect-router's reading of a patient message, for suggesting a dialect
    detected_dialect: Mapped[str | None] = mapped_column(String(8))
    # the safety gates' verdicts on the turn this reply ends (scope, sensitivity, guard, escalation)
    safety: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, server_default=func.now())


class Escalation(Base):
    """
    A patient's question that the doctor answers instead of the assistant.
    Seen by its patient and its doctor, like the conversation it came from.
    """

    __tablename__ = "escalations"
    __table_args__ = (Index("ix_escalations_doctor_status", "doctor_id", "status", "created_at"), {"schema": SCHEMA})

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.conversations.id", ondelete="CASCADE"))
    doctor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    # the patient's question
    message_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.messages.id", ondelete="CASCADE"))
    reason: Mapped[EscalationReason] = mapped_column(_enum(EscalationReason, "escalation_reason"))
    status: Mapped[EscalationStatus] = mapped_column(
        _enum(EscalationStatus, "escalation_status"), default=EscalationStatus.OPEN, server_default="open"
    )
    doctor_reply: Mapped[str | None] = mapped_column(Text)
    # the reply as it appears in the patient's chat
    reply_message_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    workflow_id: Mapped[str | None] = mapped_column(String(128))
    nudged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, server_default=func.now())


class ReplyFeedback(Base):
    """A patient's thumbs up or down on one of the assistant's replies; one per reply, changeable."""

    __tablename__ = "reply_feedback"
    __table_args__ = (UniqueConstraint("message_id", name="uq_reply_feedback_message"), {"schema": SCHEMA})

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    message_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.messages.id", ondelete="CASCADE"))
    patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    doctor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    # "up" or "down"
    rating: Mapped[str] = mapped_column(String(8))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, server_default=func.now())

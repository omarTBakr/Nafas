"""
Escalations: opened in the patient's scope when a gate sends a question to
the doctor, answered in the doctor's. The database is the authority; the
workflow only keeps time, and each step re-reads the row before acting.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from nafas_conversation.enums import EscalationReason, EscalationStatus, MessageRole
from nafas_conversation.exceptions import EscalationClosedError, EscalationNotFoundError
from nafas_conversation.models import Escalation, Message
from nafas_core.db import session_scope


@dataclass
class InboxItem:
    escalation: Escalation
    question: str


async def open_escalation(
    *,
    escalation_id: uuid.UUID,
    patient_id: uuid.UUID,
    doctor_id: uuid.UUID,
    conversation_id: uuid.UUID,
    message_id: uuid.UUID,
    reason: EscalationReason,
    workflow_id: str,
) -> None:
    """Idempotent on its id, which the workflow chooses."""
    async with session_scope(patient_id=patient_id) as session:
        await session.execute(
            insert(Escalation)
            .values(
                id=escalation_id,
                patient_id=patient_id,
                doctor_id=doctor_id,
                conversation_id=conversation_id,
                message_id=message_id,
                reason=reason,
                workflow_id=workflow_id,
            )
            .on_conflict_do_nothing(index_elements=["id"])
        )


async def inbox(doctor_id: uuid.UUID, statuses: tuple[EscalationStatus, ...], limit: int = 100) -> list[InboxItem]:
    """The doctor's escalations with the question each asked, oldest open first."""
    async with session_scope(doctor_id=doctor_id) as session:
        rows = (
            await session.execute(
                select(Escalation, Message.content)
                .join(Message, Message.id == Escalation.message_id)
                .where(Escalation.doctor_id == doctor_id, Escalation.status.in_(statuses))
                .order_by(Escalation.created_at)
                .limit(limit)
            )
        ).all()
    return [InboxItem(escalation, question) for escalation, question in rows]


async def answer(doctor_id: uuid.UUID, escalation_id: uuid.UUID, reply: str, now: datetime | None = None) -> Escalation:
    """
    The doctor's answer, written into the patient's chat as the doctor's own
    message. Only an open escalation of this doctor can be answered, once.
    """
    now = now or datetime.now(UTC)
    async with session_scope(doctor_id=doctor_id) as session:
        escalation = await session.get(Escalation, escalation_id, with_for_update=True)
        if escalation is None:
            raise EscalationNotFoundError(str(escalation_id))
        if escalation.status is not EscalationStatus.OPEN:
            raise EscalationClosedError(f"this escalation is {escalation.status.value}")

        message = Message(conversation_id=escalation.conversation_id, role=MessageRole.DOCTOR, content=reply)
        session.add(message)
        await session.flush()
        escalation.status = EscalationStatus.ANSWERED
        escalation.doctor_reply = reply
        escalation.reply_message_id = message.id
        escalation.answered_at = now
        await session.flush()
        return escalation


async def still_open(patient_id: uuid.UUID, escalation_id: uuid.UUID) -> Escalation | None:
    async with session_scope(patient_id=patient_id) as session:
        escalation = await session.get(Escalation, escalation_id)
    return escalation if escalation is not None and escalation.status is EscalationStatus.OPEN else None


async def tell_patient(
    patient_id: uuid.UUID, escalation_id: uuid.UUID, text: str, *, expire: bool, message_id: uuid.UUID
) -> bool:
    """
    A fixed assistant message in the chat about an escalation still open:
    the nudge, or its expiry. False (nothing written) once it is answered.
    """
    async with session_scope(patient_id=patient_id) as session:
        escalation = await session.get(Escalation, escalation_id, with_for_update=True)
        if escalation is None or escalation.status is not EscalationStatus.OPEN:
            return False
        await session.execute(
            insert(Message)
            .values(id=message_id, conversation_id=escalation.conversation_id, role=MessageRole.ASSISTANT, content=text)
            .on_conflict_do_nothing(index_elements=["id"])
        )
        if expire:
            escalation.status = EscalationStatus.EXPIRED
        else:
            escalation.nudged_at = datetime.now(UTC)
        return True

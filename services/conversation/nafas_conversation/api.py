"""
The conversation service's internal API, reached only by other services (the
gateway) behind the internal token. Messages go in through the workflow; this
only reads, always in the scope of the person asking.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from nafas_conversation.enums import EscalationReason, EscalationStatus, Intent, MessageRole, Modality
from nafas_conversation.events import get_events
from nafas_conversation.exceptions import EscalationClosedError, EscalationNotFoundError
from nafas_conversation.logic import escalations, messages, voice
from nafas_conversation.models import Message
from nafas_core import audit
from nafas_core.internal_api import require_internal_token


class MessageOut(BaseModel):
    message_id: uuid.UUID
    role: MessageRole
    modality: Modality
    content: str
    audio_key: str | None
    intent: Intent | None
    created_at: datetime


def _message(m: Message) -> MessageOut:
    return MessageOut(
        message_id=m.id,
        role=m.role,
        modality=m.modality,
        content=m.content,
        audio_key=m.audio_key,
        intent=m.intent,
        created_at=m.created_at,
    )


router = APIRouter(prefix="/internal/v1")


@router.get("/patients/{patient_id}/conversations/{doctor_id}/messages", response_model=list[MessageOut])
async def patient_messages(
    patient_id: uuid.UUID, doctor_id: uuid.UUID, limit: int = Query(default=100, ge=1, le=500)
) -> list[MessageOut]:
    """The patient's thread with this doctor, oldest first, read in the patient's own scope."""
    thread = await messages.patient_thread(patient_id, doctor_id, limit)
    if thread:
        await audit.record(
            service="conversation",
            actor=audit.Actor.PATIENT,
            actor_id=patient_id,
            action="read_thread",
            resource_type="conversation",
            resource_id=thread[0].conversation_id,
            patient_id=patient_id,
            doctor_id=doctor_id,
            detail={"messages": len(thread)},
        )
    return [_message(m) for m in thread]


@router.get("/patients/{patient_id}/dialect-suggestion")
async def dialect_suggestion(patient_id: uuid.UUID) -> dict:
    """A spoken dialect to offer the patient, from what they have written; null when nothing is clear."""
    return {"dialect": await voice.suggested_dialect(patient_id)}


class EscalationOut(BaseModel):
    escalation_id: uuid.UUID
    patient_id: uuid.UUID
    reason: EscalationReason
    status: EscalationStatus
    question: str
    doctor_reply: str | None
    nudged_at: datetime | None
    answered_at: datetime | None
    created_at: datetime


class ReplyIn(BaseModel):
    reply: str = Field(min_length=1, max_length=4000)


def _escalation(e, question: str) -> EscalationOut:
    return EscalationOut(
        escalation_id=e.id,
        patient_id=e.patient_id,
        reason=e.reason,
        status=e.status,
        question=question,
        doctor_reply=e.doctor_reply,
        nudged_at=e.nudged_at,
        answered_at=e.answered_at,
        created_at=e.created_at,
    )


@router.get("/doctors/{doctor_id}/escalations", response_model=list[EscalationOut])
async def doctor_escalations(
    doctor_id: uuid.UUID,
    status: list[EscalationStatus] = Query(default=[EscalationStatus.OPEN]),
    patient_id: uuid.UUID | None = None,
):
    """The doctor's inbox: the questions waiting for them (or any statuses asked for), oldest first; one patient's if named."""
    items = await escalations.inbox(doctor_id, tuple(status))
    items = [i for i in items if patient_id is None or i.escalation.patient_id == patient_id]
    for item in items:
        await audit.record(
            service="conversation",
            actor=audit.Actor.DOCTOR,
            actor_id=doctor_id,
            action="read_escalation",
            resource_type="escalation",
            resource_id=item.escalation.id,
            patient_id=item.escalation.patient_id,
            doctor_id=doctor_id,
        )
    return [_escalation(item.escalation, item.question) for item in items]


@router.post("/doctors/{doctor_id}/escalations/{escalation_id}/reply", response_model=EscalationOut)
async def reply_to_escalation(doctor_id: uuid.UUID, escalation_id: uuid.UUID, body: ReplyIn) -> EscalationOut:
    """The doctor's answer, into the patient's chat; 404 for another doctor's, 409 once it is closed."""
    try:
        answered = await escalations.answer(doctor_id, escalation_id, body.reply.strip())
    except EscalationNotFoundError as exc:
        raise HTTPException(status_code=404, detail="no such escalation") from exc
    except EscalationClosedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await get_events().answered(answered)
    [item] = [i for i in await escalations.inbox(doctor_id, (EscalationStatus.ANSWERED,)) if i.escalation.id == escalation_id]
    return _escalation(item.escalation, item.question)


app = FastAPI(title="Nafas conversation (internal)")
app.include_router(router, dependencies=[Depends(require_internal_token)])


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}

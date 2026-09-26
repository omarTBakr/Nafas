"""
The conversation service's internal API, reached only by other services (the
gateway) behind the internal token. Messages go in through the workflow; this
only reads, always in the scope of the person asking.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, FastAPI, Query
from pydantic import BaseModel

from nafas_conversation.enums import Intent, MessageRole, Modality
from nafas_conversation.logic import messages, voice
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


app = FastAPI(title="Nafas conversation (internal)")
app.include_router(router, dependencies=[Depends(require_internal_token)])


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}

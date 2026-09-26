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
from nafas_conversation.logic import messages
from nafas_conversation.models import Message
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
    return [_message(m) for m in await messages.patient_thread(patient_id, doctor_id, limit)]


app = FastAPI(title="Nafas conversation (internal)")
app.include_router(router, dependencies=[Depends(require_internal_token)])


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}

"""The doctor's assistant chat: the gateway forwards the turn and streams the answer back as it is written."""

import uuid
from typing import Literal

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from nafas_core.clients.doctor_assistant import get_doctor_assistant
from nafas_core.clients.identity import Account
from nafas_gateway.limits import Limit, limiter
from nafas_gateway.sessions import current_doctor

router = APIRouter(prefix="/api/doctor", tags=["assistant"])

ASSISTANT_PER_DOCTOR = Limit("doctor-assistant", 30, 60)


class Turn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=20000)


class ChatIn(BaseModel):
    patient_id: uuid.UUID | None = None
    messages: list[Turn] = Field(min_length=1, max_length=60)


@router.post("/assistant")
async def assistant(body: ChatIn, doctor: Account = Depends(current_doctor)) -> StreamingResponse:
    limiter.hit(ASSISTANT_PER_DOCTOR, str(doctor.doctor_id))
    stream = await get_doctor_assistant().open_chat(doctor.doctor_id, body.model_dump(mode="json"))
    return StreamingResponse(
        stream, media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )

"""
The patient's chat with a doctor's assistant. The patient comes from the
session; the doctor from the path. Messages go to the conversation's
workflow, and the reply comes back on the same request.
"""

import uuid
from dataclasses import asdict
from typing import Protocol

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from temporalio.client import WorkflowUpdateFailedError

from nafas_core.clients.conversation import ChatReply, get_conversation, send_patient_message
from nafas_core.clients.identity import Account, get_identity
from nafas_core.exceptions.workflow import TemporalConnectionError
from nafas_core.temporal import get_temporal_client
from nafas_gateway.sessions import current_patient

router = APIRouter(prefix="/api/chat", tags=["chat"])


class ChatSender(Protocol):
    async def __call__(self, *, patient_id: str, doctor_id: str, text: str, audio_key: str | None) -> ChatReply: ...


async def send_through_temporal(*, patient_id: str, doctor_id: str, text: str, audio_key: str | None) -> ChatReply:
    return await send_patient_message(
        await get_temporal_client(), patient_id=patient_id, doctor_id=doctor_id, text=text, audio_key=audio_key
    )


def chat_sender() -> ChatSender:
    """A dependency, so a test can answer for the conversation service."""
    return send_through_temporal


class MessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


async def _known_doctor(doctor_id: uuid.UUID) -> None:
    # 404 through UpstreamRefusal when there is no such doctor
    await get_identity().doctor(doctor_id)


async def deliver(sender: ChatSender, patient: Account, doctor_id: uuid.UUID, text: str, audio_key: str | None) -> dict:
    try:
        reply = await sender(patient_id=str(patient.patient_id), doctor_id=str(doctor_id), text=text, audio_key=audio_key)
    except WorkflowUpdateFailedError as refused:
        raise HTTPException(status_code=422, detail="the message was refused") from refused
    except TemporalConnectionError as down:
        raise HTTPException(status_code=503, detail="the assistant is unavailable; try again shortly") from down
    return asdict(reply)


@router.post("/{doctor_id}/messages")
async def send(
    doctor_id: uuid.UUID,
    message: MessageIn,
    patient: Account = Depends(current_patient),
    sender: ChatSender = Depends(chat_sender),
) -> dict:
    """The assistant's reply, with any appointment it held, confirmed or cancelled on the way."""
    await _known_doctor(doctor_id)
    return await deliver(sender, patient, doctor_id, message.text, None)


@router.get("/{doctor_id}/messages")
async def thread(doctor_id: uuid.UUID, patient: Account = Depends(current_patient)) -> list[dict]:
    return await get_conversation().patient_messages(patient.patient_id, doctor_id)

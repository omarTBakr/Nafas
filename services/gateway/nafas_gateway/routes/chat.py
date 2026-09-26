"""
The patient's chat with a doctor's assistant. The patient comes from the
session; the doctor from the path. Messages go to the conversation's
workflow, and the reply comes back on the same request.
"""

import uuid
from dataclasses import asdict
from typing import Protocol

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from temporalio.client import WorkflowUpdateFailedError

from nafas_core.clients.conversation import ChatReply, get_conversation, send_patient_message
from nafas_core.clients.identity import Account, get_identity
from nafas_core.exceptions.workflow import TemporalConnectionError
from nafas_core.interfaces.storage.base import patient_key
from nafas_core.interfaces.storage.factory import get_storage
from nafas_core.temporal import get_temporal_client
from nafas_gateway.errors import Refusal
from nafas_gateway.sessions import current_patient

router = APIRouter(prefix="/api/chat", tags=["chat"])


# what browsers record (MediaRecorder) and what the stt service decodes
VOICE_TYPES = {"audio/webm": "webm", "audio/ogg": "ogg", "audio/mp4": "m4a", "audio/mpeg": "mp3", "audio/wav": "wav"}
MAX_VOICE_BYTES = 15_000_000


class ChatSender(Protocol):
    async def __call__(
        self, *, patient_id: str, doctor_id: str, text: str, audio_key: str | None, audio_mime: str | None
    ) -> ChatReply: ...


async def send_through_temporal(
    *, patient_id: str, doctor_id: str, text: str, audio_key: str | None, audio_mime: str | None
) -> ChatReply:
    return await send_patient_message(
        await get_temporal_client(),
        patient_id=patient_id,
        doctor_id=doctor_id,
        text=text,
        audio_key=audio_key,
        audio_mime=audio_mime,
    )


def chat_sender() -> ChatSender:
    """A dependency, so a test can answer for the conversation service."""
    return send_through_temporal


class MessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


async def _may_chat(patient: Account, doctor_id: uuid.UUID) -> None:
    """The doctor exists (404 otherwise), and the patient consented to data processing and to AI chat with them."""
    await get_identity().doctor(doctor_id)
    if not await get_identity().may_chat(patient.patient_id, doctor_id):
        raise Refusal(403, "consent_required", "consent to data processing and AI chat is needed first")


async def deliver(
    sender: ChatSender,
    patient: Account,
    doctor_id: uuid.UUID,
    text: str,
    audio_key: str | None = None,
    audio_mime: str | None = None,
) -> dict:
    try:
        reply = await sender(
            patient_id=str(patient.patient_id), doctor_id=str(doctor_id), text=text, audio_key=audio_key, audio_mime=audio_mime
        )
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
    await _may_chat(patient, doctor_id)
    return await deliver(sender, patient, doctor_id, message.text)


@router.post("/{doctor_id}/voice")
async def send_voice(
    doctor_id: uuid.UUID,
    audio: UploadFile = File(...),
    patient: Account = Depends(current_patient),
    sender: ChatSender = Depends(chat_sender),
) -> dict:
    """A voice note: stored under the patient, transcribed by the workflow, answered like typed text."""
    mime = (audio.content_type or "").split(";")[0].strip()
    if mime not in VOICE_TYPES:
        raise HTTPException(status_code=415, detail="send a voice note as webm, ogg, mp4, mp3 or wav")
    data = await audio.read(MAX_VOICE_BYTES + 1)
    if not data:
        raise HTTPException(status_code=422, detail="the voice note is empty")
    if len(data) > MAX_VOICE_BYTES:
        raise HTTPException(status_code=413, detail="the voice note is too large")

    await _may_chat(patient, doctor_id)
    key = patient_key(doctor_id, patient.patient_id, "voice", f"{uuid.uuid4()}.{VOICE_TYPES[mime]}")
    await get_storage().put(key, data, mime)
    return await deliver(sender, patient, doctor_id, "", key, mime)


@router.get("/{doctor_id}/messages/{message_id}/audio")
async def message_audio(doctor_id: uuid.UUID, message_id: uuid.UUID, patient: Account = Depends(current_patient)):
    """A short-lived link to a voice note or spoken reply in the patient's own thread; anything else is not found."""
    thread = await get_conversation().patient_messages(patient.patient_id, doctor_id)
    key = next((m["audio_key"] for m in thread if m["message_id"] == str(message_id) and m["audio_key"]), None)
    if key is None:
        raise HTTPException(status_code=404, detail="no audio for this message")
    return RedirectResponse(await get_storage().presigned_get_url(key, expires_seconds=300), status_code=307)


@router.get("/{doctor_id}/messages")
async def thread(doctor_id: uuid.UUID, patient: Account = Depends(current_patient)) -> list[dict]:
    return await get_conversation().patient_messages(patient.patient_id, doctor_id)

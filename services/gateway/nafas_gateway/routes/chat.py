"""
The patient's chat with a doctor's assistant. The patient comes from the
session; the doctor from the path. Messages go to the conversation's
workflow, and the reply comes back on the same request: whole, or (the
/stream routes) as server-sent events while it is written.
"""

import asyncio
import json
import uuid
from dataclasses import asdict
from typing import Literal, Protocol

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import RedirectResponse, StreamingResponse
from pydantic import BaseModel, Field
from temporalio.client import WorkflowUpdateFailedError

from nafas_core import streams
from nafas_core.clients.conversation import ChatReply, get_conversation, send_patient_message
from nafas_core.clients.identity import Account, get_identity
from nafas_core.exceptions.workflow import TemporalConnectionError
from nafas_core.interfaces.storage.base import patient_key
from nafas_core.interfaces.storage.factory import get_storage
from nafas_core.temporal import get_temporal_client
from nafas_gateway.errors import Refusal
from nafas_gateway.limits import limit_chat, limit_voice
from nafas_gateway.sessions import current_patient

router = APIRouter(prefix="/api/chat", tags=["chat"])


# what browsers record (MediaRecorder) and what the stt service decodes
VOICE_TYPES = {"audio/webm": "webm", "audio/ogg": "ogg", "audio/mp4": "m4a", "audio/mpeg": "mp3", "audio/wav": "wav"}
MAX_VOICE_BYTES = 15_000_000


class ChatSender(Protocol):
    async def __call__(
        self,
        *,
        patient_id: str,
        doctor_id: str,
        text: str,
        audio_key: str | None,
        audio_mime: str | None,
        stream_id: str | None = None,
    ) -> ChatReply: ...


async def send_through_temporal(
    *,
    patient_id: str,
    doctor_id: str,
    text: str,
    audio_key: str | None,
    audio_mime: str | None,
    stream_id: str | None = None,
) -> ChatReply:
    return await send_patient_message(
        await get_temporal_client(),
        patient_id=patient_id,
        doctor_id=doctor_id,
        text=text,
        audio_key=audio_key,
        audio_mime=audio_mime,
        stream_id=stream_id,
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


def _event(name: str, data: dict) -> str:
    return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def stream_reply(
    sender: ChatSender,
    patient: Account,
    doctor_id: uuid.UUID,
    text: str,
    audio_key: str | None = None,
    audio_mime: str | None = None,
) -> StreamingResponse:
    """
    The reply as server-sent events: `delta` for each piece of text as the
    model writes it, then `done` with the whole reply (the authority: what is
    stored, and what replaces the pieces), or `error`. Pieces are relayed
    from the worker over Postgres NOTIFY; listening starts before the message
    is sent, so the first piece cannot be missed.
    """
    stream_id = uuid.uuid4().hex

    async def events():
        try:
            async with streams.listen(stream_id) as pieces:
                sending = asyncio.create_task(
                    sender(
                        patient_id=str(patient.patient_id),
                        doctor_id=str(doctor_id),
                        text=text,
                        audio_key=audio_key,
                        audio_mime=audio_mime,
                        stream_id=stream_id,
                    )
                )
                while True:
                    waiting = asyncio.create_task(pieces.get())
                    finished, _ = await asyncio.wait({waiting, sending}, return_when=asyncio.FIRST_COMPLETED)
                    if waiting in finished:
                        yield _event("delta", {"text": waiting.result().get("text", "")})
                        continue
                    waiting.cancel()
                    while not pieces.empty():
                        yield _event("delta", {"text": pieces.get_nowait().get("text", "")})
                    break
                reply = sending.result()
        except WorkflowUpdateFailedError:
            yield _event("error", {"status": 422, "detail": "the message was refused"})
            return
        except TemporalConnectionError:
            yield _event("error", {"status": 503, "detail": "the assistant is unavailable; try again shortly"})
            return
        yield _event("done", asdict(reply))

    # no buffering anywhere on the way: nginx, and any proxy that honours the header
    return StreamingResponse(
        events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


@router.post("/{doctor_id}/messages", dependencies=[Depends(limit_chat)])
async def send(
    doctor_id: uuid.UUID,
    message: MessageIn,
    patient: Account = Depends(current_patient),
    sender: ChatSender = Depends(chat_sender),
) -> dict:
    """The assistant's reply, with any appointment it held, confirmed or cancelled on the way."""
    await _may_chat(patient, doctor_id)
    return await deliver(sender, patient, doctor_id, message.text)


@router.post("/{doctor_id}/messages/stream", dependencies=[Depends(limit_chat)])
async def send_streamed(
    doctor_id: uuid.UUID,
    message: MessageIn,
    patient: Account = Depends(current_patient),
    sender: ChatSender = Depends(chat_sender),
) -> StreamingResponse:
    """The same as sending, with the reply streamed as it is written."""
    await _may_chat(patient, doctor_id)
    return stream_reply(sender, patient, doctor_id, message.text)


async def _store_voice(doctor_id: uuid.UUID, audio: UploadFile, patient: Account) -> tuple[str, str]:
    """Checks and stores a voice note under the patient; its (key, mime)."""
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
    return key, mime


@router.post("/{doctor_id}/voice", dependencies=[Depends(limit_voice)])
async def send_voice(
    doctor_id: uuid.UUID,
    audio: UploadFile = File(...),
    patient: Account = Depends(current_patient),
    sender: ChatSender = Depends(chat_sender),
) -> dict:
    """A voice note: stored under the patient, transcribed by the workflow, answered like typed text."""
    key, mime = await _store_voice(doctor_id, audio, patient)
    return await deliver(sender, patient, doctor_id, "", key, mime)


@router.post("/{doctor_id}/voice/stream", dependencies=[Depends(limit_voice)])
async def send_voice_streamed(
    doctor_id: uuid.UUID,
    audio: UploadFile = File(...),
    patient: Account = Depends(current_patient),
    sender: ChatSender = Depends(chat_sender),
) -> StreamingResponse:
    """A voice note, with the reply streamed as it is written."""
    key, mime = await _store_voice(doctor_id, audio, patient)
    return stream_reply(sender, patient, doctor_id, "", key, mime)


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


class FeedbackIn(BaseModel):
    rating: Literal["up", "down"]


@router.put("/{doctor_id}/messages/{message_id}/feedback", status_code=204)
async def rate_reply(
    doctor_id: uuid.UUID, message_id: uuid.UUID, body: FeedbackIn, patient: Account = Depends(current_patient)
) -> None:
    """Thumbs up or down on one of the assistant's replies."""
    await get_conversation().rate_reply(patient.patient_id, doctor_id, message_id, body.rating)

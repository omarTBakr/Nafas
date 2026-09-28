"""
The doctor's assistant chat: the gateway forwards the turn and streams the
answer back as it is written. The doctor may dictate a question instead of
typing it, and have an Arabic answer read aloud in a dialect's voice, one
passage at a time.
"""

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from nafas_core.clients.doctor_assistant import get_doctor_assistant
from nafas_core.clients.identity import Account
from nafas_core.exceptions.providers import STTError, TTSError
from nafas_core.interfaces.stt import get_stt
from nafas_core.interfaces.tts import get_tts
from nafas_core.logger import get_logger
from nafas_gateway.errors import Refusal
from nafas_gateway.limits import Limit, limiter
from nafas_gateway.routes.chat import MAX_VOICE_BYTES, VOICE_TYPES
from nafas_gateway.sessions import current_doctor

logger = get_logger(__name__)

router = APIRouter(prefix="/api/doctor", tags=["assistant"])

ASSISTANT_PER_DOCTOR = Limit("doctor-assistant", 30, 60)
DICTATION_PER_DOCTOR = Limit("doctor-dictation", 30, 60)
# an answer is read a passage at a time: a long one is a dozen requests
SPEECH_PER_DOCTOR = Limit("doctor-speech", 120, 60)
# the tts service reads at most 600 characters a request
MAX_PASSAGE = 600

Dialect = Literal["eg", "sa", "ma", "bh", "sd", "iq", "lb", "sy", "ly", "ps", "tn", "dz", "ye"]


class SpeakIn(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_PASSAGE)
    dialect: Dialect = "eg"
    voice: Literal["female", "male"] | None = None


class Turn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=20000)


class ChatIn(BaseModel):
    patient_id: uuid.UUID | None = None
    messages: list[Turn] = Field(min_length=1, max_length=60)


@router.post("/assistant")
async def assistant(body: ChatIn, doctor: Account = Depends(current_doctor)) -> StreamingResponse:
    await limiter.hit(ASSISTANT_PER_DOCTOR, str(doctor.doctor_id))
    stream = await get_doctor_assistant().open_chat(doctor.doctor_id, body.model_dump(mode="json"))
    return StreamingResponse(
        stream, media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


@router.post("/speak", responses={200: {"content": {"audio/wav": {}}}})
async def speak(body: SpeakIn, doctor: Account = Depends(current_doctor)) -> Response:
    """
    One passage of an answer in Nafas's dialect voice. Unlike a patient's
    reply, nothing is held back as clinical: the listener is the doctor. The
    browser reads English itself, and falls back to its own voice when this
    one is unavailable (503).
    """
    await limiter.hit(SPEECH_PER_DOCTOR, str(doctor.doctor_id))
    try:
        speech = await get_tts().speak(body.text, body.dialect, body.voice)
    except TTSError as exc:
        logger.warning("the dialect voice is unavailable for the doctor's assistant: %s", exc)
        raise Refusal(503, "voice_unavailable", "the dialect voice is unavailable") from exc
    return Response(speech.audio, media_type=speech.mime_type, headers={"Cache-Control": "no-store"})


@router.post("/transcribe")
async def transcribe(
    audio: UploadFile = File(...),
    language: Literal["ar", "en"] | None = Form(None),
    doctor: Account = Depends(current_doctor),
) -> dict:
    """
    A dictated question as text, for the doctor to read over before asking.
    The recording is transcribed and dropped: it is never stored.
    """
    await limiter.hit(DICTATION_PER_DOCTOR, str(doctor.doctor_id))
    mime = (audio.content_type or "").split(";")[0].strip()
    if mime not in VOICE_TYPES:
        raise Refusal(415, "unsupported_audio", "send the recording as webm, ogg, mp4, mp3 or wav")
    data = await audio.read(MAX_VOICE_BYTES + 1)
    if not data:
        raise Refusal(422, "empty_audio", "the recording is empty")
    if len(data) > MAX_VOICE_BYTES:
        raise Refusal(413, "audio_too_large", "the recording is too large")
    try:
        transcript = await get_stt().transcribe(data, mime, language_hint=language)
    except STTError as exc:
        logger.warning("dictation could not be transcribed: %s", exc)
        raise Refusal(503, "stt_unavailable", "speech could not be turned into text right now") from exc
    return {"text": transcript.text.strip(), "language": transcript.language}

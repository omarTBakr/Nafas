"""
Voice around a turn: the patient's voice note in, the assistant's reply out,
and the dialect a patient seems to write in.

Every step here is optional to the turn: a transcription that fails leaves
an empty message (answered with "I could not hear that"), and a reply that
cannot be spoken is simply shown as text, which it always is anyway.
"""

import uuid
from collections import Counter
from dataclasses import dataclass

from sqlalchemy import select, update

from nafas_conversation.enums import Intent, MessageRole
from nafas_conversation.logic.speech import speakable
from nafas_conversation.models import Conversation, Message
from nafas_core.clients.identity import IdentityClient
from nafas_core.db import session_scope
from nafas_core.enums.dialect import SUGGESTED_FROM_DETECTED, Dialect
from nafas_core.interfaces.dialect.base import DialectClassifier
from nafas_core.interfaces.storage.base import Storage, patient_key
from nafas_core.interfaces.stt.base import STT
from nafas_core.interfaces.tts.base import TTS
from nafas_core.logger import get_logger

logger = get_logger(__name__)

# only these are ever read aloud; clinical answers and emergencies stay text (PLAN §1, TTS)
SPOKEN_INTENTS = {Intent.BOOKING, Intent.ADMIN, Intent.SMALLTALK}
# a suggestion needs this many confident readings, most of them agreeing
SUGGESTION_MIN_READINGS = 3
SUGGESTION_MIN_SHARE = 0.6


@dataclass
class VoiceProviders:
    stt: STT
    tts: TTS
    storage: Storage
    dialects: DialectClassifier


async def transcribe(providers: VoiceProviders, identity: IdentityClient, patient_id: uuid.UUID, key: str, mime: str) -> str:
    """The voice note's text; empty when it could not be heard."""
    try:
        language = (await identity.profile(patient_id))["preferred_language"]
        audio = await providers.storage.get(key)
        transcript = await providers.stt.transcribe(audio, mime, language_hint=language)
    except Exception:
        logger.exception("could not transcribe a voice note for patient %s", patient_id)
        return ""
    return transcript.text.strip()


async def tag_dialect(providers: VoiceProviders, patient_id: uuid.UUID, message_id: uuid.UUID, text: str) -> str | None:
    """
    Stores the dialect-router's reading on the message when it is confident.
    Analytics and a suggestion only: never an input to safety or a clinical decision.
    """
    try:
        [prediction] = await providers.dialects.classify([text])
    except Exception:
        logger.exception("dialect-router unavailable; message left untagged")
        return None
    if prediction.low_confidence:
        return None

    async with session_scope(patient_id=patient_id) as session:
        await session.execute(update(Message).where(Message.id == message_id).values(detected_dialect=prediction.dialect.value))
    return prediction.dialect.value


async def suggested_dialect(patient_id: uuid.UUID) -> str | None:
    """
    A spoken dialect to suggest from what the patient has written: most of at
    least three confident readings agree, and they name a dialect a voice
    speaks. It only suggests; the patient's own choice always wins.
    """
    async with session_scope(patient_id=patient_id) as session:
        readings = (
            await session.scalars(
                select(Message.detected_dialect)
                .join(Conversation, Conversation.id == Message.conversation_id)
                .where(
                    Conversation.patient_id == patient_id,
                    Message.role == MessageRole.PATIENT,
                    Message.detected_dialect.is_not(None),
                )
            )
        ).all()
    if len(readings) < SUGGESTION_MIN_READINGS:
        return None

    code, count = Counter(readings).most_common(1)[0]
    if count / len(readings) < SUGGESTION_MIN_SHARE:
        return None
    try:
        spoken = SUGGESTED_FROM_DETECTED.get(Dialect(code))
    except ValueError:
        return None
    return spoken.value if spoken else None


async def speak_reply(
    providers: VoiceProviders,
    identity: IdentityClient,
    *,
    doctor_id: uuid.UUID,
    patient_id: uuid.UUID,
    reply_id: uuid.UUID,
    text: str,
) -> str | None:
    """
    The reply read aloud in the patient's chosen dialect and voice, stored
    beside the text; None when it should not or cannot be spoken.
    """
    try:
        profile = await identity.profile(patient_id)
    except Exception:
        logger.exception("profile lookup failed; the reply stays text")
        return None
    dialect = profile.get("dialect")
    if not dialect:
        # the patient has not chosen how to be spoken to: text is the safe default
        return None
    spoken = speakable(text, dialect)
    if spoken is None:
        return None

    try:
        speech = await providers.tts.speak(spoken, dialect, profile.get("voice"))
        key = patient_key(doctor_id, patient_id, "voice", f"{reply_id}.wav")
        await providers.storage.put(key, speech.audio, speech.mime_type)
    except Exception:
        logger.exception("could not speak a reply for patient %s; it stays text", patient_id)
        return None
    return key

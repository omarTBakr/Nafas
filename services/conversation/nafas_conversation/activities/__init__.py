"""
The conversation service's activities: one side effect each, thin over `logic`.

They are methods on one object holding the providers, so the worker builds it
from the process-wide clients and a test hands it fakes.
"""

import uuid
from datetime import UTC, datetime

from temporalio import activity

from nafas_conversation.enums import Intent, Modality
from nafas_conversation.logic import messages, voice
from nafas_conversation.logic.turn import Models, answer_turn
from nafas_conversation.logic.voice import VoiceProviders
from nafas_conversation.schemas import (
    ConversationStart,
    DialectRequest,
    SpeakRequest,
    StoredMessage,
    StoredReply,
    TranscribeRequest,
    TurnRequest,
    TurnResult,
)
from nafas_core.clients.identity import IdentityClient
from nafas_core.clients.scheduling import SchedulingClient
from nafas_core.interfaces.llm import LLM


class ConversationActivities:
    def __init__(
        self,
        llm: LLM,
        identity: IdentityClient,
        scheduling: SchedulingClient,
        models: Models,
        voice: VoiceProviders | None = None,
    ):
        self._llm = llm
        self._identity = identity
        self._scheduling = scheduling
        self._models = models
        self._voice = voice

    def _voice_providers(self) -> VoiceProviders:
        if self._voice is None:
            raise RuntimeError("this worker was built without voice providers")
        return self._voice

    @activity.defn(name="conversation.open")
    async def open_conversation(self, start: ConversationStart) -> str:
        return str(await messages.open_conversation(uuid.UUID(start.patient_id), uuid.UUID(start.doctor_id)))

    @activity.defn(name="conversation.save_patient_message")
    async def save_patient_message(self, message: StoredMessage) -> None:
        await messages.add_patient_message(
            uuid.UUID(message.patient_id),
            uuid.UUID(message.message_id),
            uuid.UUID(message.conversation_id),
            message.content,
            Modality(message.modality),
            message.audio_key,
        )

    @activity.defn(name="conversation.answer")
    async def answer(self, request: TurnRequest) -> TurnResult:
        """The assistant's reply to the thread as stored; it may hold, confirm or cancel on the way."""
        patient_id = uuid.UUID(request.patient_id)
        history = messages.model_history(await messages.recent_messages(patient_id, uuid.UUID(request.conversation_id)))
        turn = await answer_turn(
            self._llm,
            self._identity,
            self._scheduling,
            patient_id=patient_id,
            doctor_id=uuid.UUID(request.doctor_id),
            history=history,
            models=self._models,
            now=datetime.now(UTC),
        )
        reply = turn.reply
        return TurnResult(
            reply.text, reply.model, reply.prompt_version, reply.tokens_in, reply.tokens_out, reply.actions, turn.intent.value
        )

    @activity.defn(name="conversation.save_reply")
    async def save_reply(self, reply: StoredReply) -> None:
        await messages.add_assistant_message(
            uuid.UUID(reply.patient_id),
            uuid.UUID(reply.message_id),
            uuid.UUID(reply.conversation_id),
            text=reply.content,
            model=reply.model,
            prompt_version=reply.prompt_version,
            tokens_in=reply.tokens_in,
            tokens_out=reply.tokens_out,
            intent=Intent(reply.intent) if reply.intent else None,
            answers_message_id=uuid.UUID(reply.answers_message_id) if reply.answers_message_id else None,
            audio_key=reply.audio_key,
        )

    @activity.defn(name="conversation.transcribe")
    async def transcribe(self, request: TranscribeRequest) -> str:
        return await voice.transcribe(
            self._voice_providers(), self._identity, uuid.UUID(request.patient_id), request.audio_key, request.audio_mime
        )

    @activity.defn(name="conversation.tag_dialect")
    async def tag_dialect(self, request: DialectRequest) -> str | None:
        return await voice.tag_dialect(
            self._voice_providers(), uuid.UUID(request.patient_id), uuid.UUID(request.message_id), request.text
        )

    @activity.defn(name="conversation.speak_reply")
    async def speak_reply(self, request: SpeakRequest) -> str | None:
        return await voice.speak_reply(
            self._voice_providers(),
            self._identity,
            doctor_id=uuid.UUID(request.doctor_id),
            patient_id=uuid.UUID(request.patient_id),
            reply_id=uuid.UUID(request.reply_id),
            text=request.text,
        )

    def all(self) -> list:
        return [
            self.open_conversation,
            self.save_patient_message,
            self.answer,
            self.save_reply,
            self.transcribe,
            self.tag_dialect,
            self.speak_reply,
        ]

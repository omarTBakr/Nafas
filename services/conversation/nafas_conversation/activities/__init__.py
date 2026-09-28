"""
The conversation service's activities: one side effect each, thin over `logic`.

They are methods on one object holding the providers, so the worker builds it
from the process-wide clients and a test hands it fakes.
"""

import uuid
from datetime import UTC, datetime

from temporalio import activity

from nafas_conversation.enums import EscalationReason, Intent, Modality
from nafas_conversation.logic import escalations, messages, voice
from nafas_conversation.logic.context import PatientContext
from nafas_conversation.logic.medical import doctor_name
from nafas_conversation.logic.turn import Models, answer_turn
from nafas_conversation.logic.voice import VoiceProviders
from nafas_conversation.prompts import replies
from nafas_conversation.schemas import (
    ConversationStart,
    DialectRequest,
    EscalationNotice,
    OpenEscalation,
    SpeakRequest,
    StoredMessage,
    StoredReply,
    TranscribeRequest,
    TurnRequest,
    TurnResult,
    escalation_workflow_id,
)
from nafas_core import audit, streams
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
        context: PatientContext | None = None,
    ):
        self._llm = llm
        self._identity = identity
        self._scheduling = scheduling
        self._models = models
        self._voice = voice
        # what the medical answer may draw on; the visits alone without clinical-records
        self._context = context

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
        stored = await messages.recent_messages(patient_id, uuid.UUID(request.conversation_id))
        # the model reads the patient's words: audited like a person's read
        await audit.record(
            service="conversation",
            actor=audit.Actor.MODEL,
            actor_id=None,
            action="read_thread",
            resource_type="conversation",
            resource_id=request.conversation_id,
            patient_id=patient_id,
            doctor_id=uuid.UUID(request.doctor_id),
            detail={"messages": len(stored), "models": [self._models.classifier, self._models.chat]},
        )
        history = messages.model_history(stored)

        on_text = None
        if request.stream_id:
            stream_id = request.stream_id

            async def on_text(piece: str) -> None:
                await streams.publish(stream_id, {"type": "delta", "text": piece})

        turn = await answer_turn(
            self._llm,
            self._identity,
            self._scheduling,
            patient_id=patient_id,
            doctor_id=uuid.UUID(request.doctor_id),
            history=history,
            models=self._models,
            now=datetime.now(UTC),
            context=self._context,
            on_text=on_text,
        )
        reply = turn.reply
        return TurnResult(
            reply.text,
            reply.model,
            reply.prompt_version,
            reply.tokens_in,
            reply.tokens_out,
            reply.actions,
            turn.intent.value,
            escalation=turn.escalation.value if turn.escalation else None,
            safety=turn.safety,
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
            safety=reply.safety,
        )

    @activity.defn(name="conversation.open_escalation")
    async def open_escalation(self, request: OpenEscalation) -> None:
        await escalations.open_escalation(
            escalation_id=uuid.UUID(request.escalation_id),
            patient_id=uuid.UUID(request.patient_id),
            doctor_id=uuid.UUID(request.doctor_id),
            conversation_id=uuid.UUID(request.conversation_id),
            message_id=uuid.UUID(request.message_id),
            reason=EscalationReason(request.reason),
            workflow_id=escalation_workflow_id(request.escalation_id),
        )

    @activity.defn(name="conversation.tell_patient_about_escalation")
    async def tell_patient_about_escalation(self, notice: EscalationNotice) -> bool:
        """The nudge, or the expiry, in the patient's language; False once the doctor has answered."""
        patient_id = uuid.UUID(notice.patient_id)
        if await escalations.still_open(patient_id, uuid.UUID(notice.escalation_id)) is None:
            return False
        language = (await self._identity.profile(patient_id))["preferred_language"]
        doctor = await self._identity.doctor(uuid.UUID(notice.doctor_id))
        words = replies.ESCALATION_EXPIRED if notice.expire else replies.ESCALATION_NUDGE
        text = replies.pick(words, language).format(doctor=doctor_name(doctor, language))
        return await escalations.tell_patient(
            patient_id, uuid.UUID(notice.escalation_id), text, expire=notice.expire, message_id=uuid.UUID(notice.message_id)
        )

    @activity.defn(name="conversation.transcribe")
    async def transcribe(self, request: TranscribeRequest) -> str:
        return await voice.transcribe(
            self._voice_providers(), self._identity, uuid.UUID(request.patient_id), request.audio_key, request.audio_mime
        )

    @activity.defn(name="conversation.tag_dialect")
    async def tag_dialect(self, request: DialectRequest) -> str | None:
        if self._voice is None:
            # a worker without the dialect-router: messages stay untagged
            return None
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
            self.open_escalation,
            self.tell_patient_about_escalation,
        ]

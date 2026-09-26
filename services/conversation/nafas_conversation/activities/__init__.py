"""
The conversation service's activities: one side effect each, thin over `logic`.

They are methods on one object holding the providers, so the worker builds it
from the process-wide clients and a test hands it fakes.
"""

import uuid
from datetime import UTC, datetime

from temporalio import activity

from nafas_conversation.logic import messages
from nafas_conversation.logic.turn import answer_booking
from nafas_conversation.schemas import ConversationStart, StoredMessage, StoredReply, TurnRequest, TurnResult
from nafas_core.clients.identity import IdentityClient
from nafas_core.clients.scheduling import SchedulingClient
from nafas_core.interfaces.llm import LLM


class ConversationActivities:
    def __init__(self, llm: LLM, identity: IdentityClient, scheduling: SchedulingClient, model: str):
        self._llm = llm
        self._identity = identity
        self._scheduling = scheduling
        self._model = model

    @activity.defn(name="conversation.open")
    async def open_conversation(self, start: ConversationStart) -> str:
        return str(await messages.open_conversation(uuid.UUID(start.patient_id), uuid.UUID(start.doctor_id)))

    @activity.defn(name="conversation.save_patient_message")
    async def save_patient_message(self, message: StoredMessage) -> None:
        await messages.add_patient_message(
            uuid.UUID(message.patient_id), uuid.UUID(message.message_id), uuid.UUID(message.conversation_id), message.content
        )

    @activity.defn(name="conversation.answer_booking")
    async def answer_booking(self, request: TurnRequest) -> TurnResult:
        """The assistant's reply to the thread as stored; it may hold, confirm or cancel on the way."""
        patient_id = uuid.UUID(request.patient_id)
        history = messages.model_history(await messages.recent_messages(patient_id, uuid.UUID(request.conversation_id)))
        reply = await answer_booking(
            self._llm,
            self._identity,
            self._scheduling,
            patient_id=patient_id,
            doctor_id=uuid.UUID(request.doctor_id),
            history=history,
            model=self._model,
            now=datetime.now(UTC),
        )
        return TurnResult(reply.text, reply.model, reply.prompt_version, reply.tokens_in, reply.tokens_out, reply.actions)

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
        )

    def all(self) -> list:
        return [self.open_conversation, self.save_patient_message, self.answer_booking, self.save_reply]

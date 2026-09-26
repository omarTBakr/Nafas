"""
PatientConversationWorkflow: one long-lived workflow per patient and doctor.

Every message arrives as the `send_message` update, sent with update-with-start
(nafas_conversation.client), so the first message starts the workflow and the
patient's send returns the reply itself. A lock takes messages one at a time
in arrival order: a second message waits for the first reply, and the model
always sees the thread as it really went.

The thread lives in the database, not here; this workflow holds only which
conversation it is. So continue_as_new every `turns_per_run` turns carries a
few ids, and a workflow idle for IDLE_TIMEOUT simply ends: the next message
starts a fresh one on the same thread.
"""

import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from nafas_conversation.activities import ConversationActivities
    from nafas_conversation.schemas import (
        ChatReply,
        ConversationStart,
        PatientMessage,
        StoredMessage,
        StoredReply,
        TurnRequest,
    )
    from nafas_core.clients import conversation

IDLE_TIMEOUT = timedelta(days=7)
MAX_MESSAGE_CHARS = 4000

STORE = {"start_to_close_timeout": timedelta(seconds=15), "retry_policy": RetryPolicy(maximum_attempts=5)}
# one attempt only: a turn may hold or confirm an appointment, and running it
# twice would act twice; the turn itself turns failures into an apology
TURN = {"start_to_close_timeout": timedelta(minutes=3), "retry_policy": RetryPolicy(maximum_attempts=1)}


@workflow.defn(name=conversation.WORKFLOW)
class PatientConversationWorkflow:
    @workflow.init
    def __init__(self, start: ConversationStart) -> None:
        # set here, not in run: update-with-start delivers the first message
        # in the same task that starts the run, and its handler may go first
        self._start = start
        self._conversation_id = start.conversation_id
        self._turns = 0
        self._lock = asyncio.Lock()

    @workflow.run
    async def run(self, start: ConversationStart) -> None:
        try:
            await workflow.wait_condition(
                lambda: self._turns >= self._start.turns_per_run or workflow.info().is_continue_as_new_suggested(),
                timeout=IDLE_TIMEOUT,
            )
        except TimeoutError:
            await workflow.wait_condition(workflow.all_handlers_finished)
            return

        await workflow.wait_condition(workflow.all_handlers_finished)
        workflow.continue_as_new(
            ConversationStart(
                patient_id=self._start.patient_id,
                doctor_id=self._start.doctor_id,
                conversation_id=self._conversation_id,
                turns_per_run=self._start.turns_per_run,
            )
        )

    @workflow.update(name=conversation.SEND_MESSAGE)
    async def send_message(self, message: PatientMessage) -> ChatReply:
        async with self._lock:
            if self._conversation_id is None:
                self._conversation_id = await workflow.execute_activity_method(
                    ConversationActivities.open_conversation, self._start, **STORE
                )
            patient_id, conversation_id = self._start.patient_id, self._conversation_id
            text = message.text.strip()

            message_id = str(workflow.uuid4())
            await workflow.execute_activity_method(
                ConversationActivities.save_patient_message,
                StoredMessage(message_id, conversation_id, patient_id, text),
                **STORE,
            )
            result = await workflow.execute_activity_method(
                ConversationActivities.answer,
                TurnRequest(patient_id, self._start.doctor_id, conversation_id),
                **TURN,
            )
            reply_id = str(workflow.uuid4())
            await workflow.execute_activity_method(
                ConversationActivities.save_reply,
                StoredReply(
                    reply_id,
                    conversation_id,
                    patient_id,
                    result.text,
                    result.model,
                    result.prompt_version,
                    result.tokens_in,
                    result.tokens_out,
                    intent=result.intent,
                    answers_message_id=message_id,
                ),
                **STORE,
            )
            self._turns += 1
            return ChatReply(conversation_id, reply_id, result.text, result.actions, result.intent, patient_text=text)

    @send_message.validator
    def _check_message(self, message: PatientMessage) -> None:
        """Rejected here, a message never enters the history at all."""
        if not message.text.strip():
            raise ValueError("empty message")
        if len(message.text) > MAX_MESSAGE_CHARS:
            raise ValueError(f"message longer than {MAX_MESSAGE_CHARS} characters")

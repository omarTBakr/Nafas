"""
The conversation service, for the callers that reach it: the gateway today.

A patient's message goes in as an update on the conversation's workflow, by
name, so no caller needs the conversation service's code; reading the thread
back goes through its internal API. The dataclasses here are the contract,
and the conversation service uses these very classes.
"""

import uuid
from dataclasses import dataclass, field

import httpx
from temporalio.client import Client, WithStartWorkflowOperation
from temporalio.common import WorkflowIDConflictPolicy

from nafas_core.clients.base import InternalClient
from nafas_core.config import get_setting
from nafas_core.temporal.queues import TaskQueue

WORKFLOW = "PatientConversationWorkflow"
SEND_MESSAGE = "send_message"


def conversation_workflow_id(doctor_id: str, patient_id: str) -> str:
    return f"conv-{doctor_id}-{patient_id}"


@dataclass
class ConversationStart:
    """The workflow's input, and what continue_as_new carries forward."""

    patient_id: str
    doctor_id: str
    # found or created by the first message, then carried across runs
    conversation_id: str | None = None
    # continue_as_new after this many turns, so the history stays small
    turns_per_run: int = 50


@dataclass
class PatientMessage:
    text: str = ""
    # a voice note in object storage; the workflow transcribes it into `text`
    audio_key: str | None = None
    audio_mime: str | None = None


@dataclass
class ChatReply:
    """What the patient's send returns: their message as stored, the reply, and what changed in the calendar."""

    conversation_id: str
    message_id: str
    text: str
    actions: list[dict] = field(default_factory=list)
    intent: str | None = None
    # the patient's own text: what they typed, or the transcript of their voice note
    patient_text: str = ""
    # the reply read aloud, when it is an admin message and the patient spoke
    audio_key: str | None = None
    # the patient's own message as stored (its voice note plays from it)
    patient_message_id: str | None = None


async def send_patient_message(
    client: Client,
    *,
    patient_id: str,
    doctor_id: str,
    text: str = "",
    audio_key: str | None = None,
    audio_mime: str | None = None,
    task_queue: str = TaskQueue.CONVERSATION,
) -> ChatReply:
    """
    Delivers one message and waits for the reply, starting the conversation's
    workflow if none is running. Raises WorkflowUpdateFailedError for a
    message the workflow refuses (empty, too long).
    """
    start = WithStartWorkflowOperation(
        WORKFLOW,
        ConversationStart(patient_id=patient_id, doctor_id=doctor_id),
        id=conversation_workflow_id(doctor_id, patient_id),
        task_queue=str(task_queue),
        id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
    )
    return await client.execute_update_with_start_workflow(
        SEND_MESSAGE, PatientMessage(text, audio_key, audio_mime), start_workflow_operation=start, result_type=ChatReply
    )


class ConversationClient(InternalClient):
    """The conversation service's internal API: reading threads and escalations."""

    service = "conversation"

    def __init__(self, client: httpx.AsyncClient | None = None):
        super().__init__(client or httpx.AsyncClient(base_url=get_setting().conversation_url, timeout=10.0))

    async def patient_messages(self, patient_id: uuid.UUID, doctor_id: uuid.UUID, limit: int = 100) -> list[dict]:
        response = await self.request(
            "GET", f"/internal/v1/patients/{patient_id}/conversations/{doctor_id}/messages", params={"limit": limit}
        )
        return response.json()

    async def rate_reply(self, patient_id: uuid.UUID, doctor_id: uuid.UUID, message_id: uuid.UUID, rating: str) -> None:
        path = f"/internal/v1/patients/{patient_id}/conversations/{doctor_id}/messages/{message_id}/feedback"
        await self.request("PUT", path, json={"rating": rating})

    async def escalations(
        self, doctor_id: uuid.UUID, statuses: list[str] | None = None, patient_id: uuid.UUID | None = None
    ) -> list[dict]:
        params = [("status", s) for s in (statuses or ["open"])]
        if patient_id:
            params.append(("patient_id", str(patient_id)))
        return (await self.request("GET", f"/internal/v1/doctors/{doctor_id}/escalations", params=params)).json()

    async def reply_to_escalation(self, doctor_id: uuid.UUID, escalation_id: uuid.UUID, reply: str) -> dict:
        path = f"/internal/v1/doctors/{doctor_id}/escalations/{escalation_id}/reply"
        return (await self.request("POST", path, json={"reply": reply})).json()

    async def dialect_suggestion(self, patient_id: uuid.UUID) -> dict:
        return (await self.request("GET", f"/internal/v1/patients/{patient_id}/dialect-suggestion")).json()


_conversation: ConversationClient | None = None


def get_conversation() -> ConversationClient:
    global _conversation
    if _conversation is None:
        _conversation = ConversationClient()

    return _conversation


def set_conversation(client: ConversationClient | None) -> None:
    global _conversation
    _conversation = client

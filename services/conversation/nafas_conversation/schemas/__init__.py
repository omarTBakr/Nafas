"""
Dataclasses crossing a Temporal boundary: workflow input, updates, activity arguments.

The workflow's own contract (its input, the message, the reply) lives in
nafas_core.clients.conversation, shared with the callers that send messages.
Ids travel as strings so any worker, whatever its converter, reads them the
same way. Adding a field needs a default, or a run in flight cannot decode
its own history (README, "one generation of workers per task queue").
"""

from dataclasses import dataclass, field

from nafas_core.clients.conversation import ChatReply, ConversationStart, PatientMessage

__all__ = [
    "ChatReply",
    "ConversationStart",
    "PatientMessage",
    "StoredMessage",
    "StoredReply",
    "TurnRequest",
    "TurnResult",
]


@dataclass
class StoredMessage:
    """A message to insert. The id comes from the workflow, so a retried insert is a no-op."""

    message_id: str
    conversation_id: str
    patient_id: str
    content: str
    modality: str = "text"
    audio_key: str | None = None


@dataclass
class StoredReply:
    message_id: str
    conversation_id: str
    patient_id: str
    content: str
    model: str
    prompt_version: str
    tokens_in: int = 0
    tokens_out: int = 0
    intent: str | None = None
    # the patient message this answers, which gets the same intent
    answers_message_id: str | None = None
    audio_key: str | None = None


@dataclass
class TurnRequest:
    patient_id: str
    doctor_id: str
    conversation_id: str


@dataclass
class TurnResult:
    text: str
    model: str
    prompt_version: str
    tokens_in: int = 0
    tokens_out: int = 0
    actions: list[dict] = field(default_factory=list)
    intent: str | None = None

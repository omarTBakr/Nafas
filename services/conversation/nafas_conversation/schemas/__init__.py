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
    "DialectRequest",
    "EscalationNotice",
    "EscalationStart",
    "OpenEscalation",
    "PatientMessage",
    "SpeakRequest",
    "StoredMessage",
    "StoredReply",
    "TranscribeRequest",
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
    safety: dict | None = None


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
    # set when the question goes to the doctor
    escalation: str | None = None
    safety: dict = field(default_factory=dict)


@dataclass
class TranscribeRequest:
    patient_id: str
    audio_key: str
    audio_mime: str


@dataclass
class DialectRequest:
    patient_id: str
    message_id: str
    text: str


@dataclass
class SpeakRequest:
    doctor_id: str
    patient_id: str
    reply_id: str
    text: str


ESCALATION_WORKFLOW = "EscalationWorkflow"
DOCTOR_REPLIED_SIGNAL = "doctor_replied"


def escalation_workflow_id(escalation_id: str) -> str:
    return f"escalation-{escalation_id}"


@dataclass
class EscalationStart:
    escalation_id: str
    patient_id: str
    doctor_id: str
    # the patient hears "not answered yet" after this long, and the question expires after the second
    nudge_after_seconds: int = 24 * 3600
    expire_after_seconds: int = 72 * 3600


@dataclass
class OpenEscalation:
    escalation_id: str
    patient_id: str
    doctor_id: str
    conversation_id: str
    message_id: str
    reason: str


@dataclass
class EscalationNotice:
    escalation_id: str
    patient_id: str
    doctor_id: str
    message_id: str
    expire: bool = False

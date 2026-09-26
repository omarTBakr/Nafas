"""
Dataclasses crossing a Temporal boundary: workflow input, updates, activity arguments.

Ids travel as strings so any worker, whatever its converter, reads them the
same way. Adding a field needs a default, or a run in flight cannot decode
its own history (README, "one generation of workers per task queue").
"""

from dataclasses import dataclass, field


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
    text: str


@dataclass
class StoredMessage:
    """A message to insert. The id comes from the workflow, so a retried insert is a no-op."""

    message_id: str
    conversation_id: str
    patient_id: str
    content: str


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


@dataclass
class ChatReply:
    """What the patient's send returns: the reply, and what changed in the calendar."""

    conversation_id: str
    message_id: str
    text: str
    actions: list[dict] = field(default_factory=list)

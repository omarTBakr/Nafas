from enum import StrEnum


class Sex(StrEnum):
    FEMALE = "female"
    MALE = "male"


class CareStatus(StrEnum):
    """Whether a patient is currently under a doctor's care."""

    ACTIVE = "active"
    ARCHIVED = "archived"


class ConsentKind(StrEnum):
    DATA_PROCESSING = "data_processing"
    AI_CHAT = "ai_chat"
    # asked afresh for every recording, never assumed from an earlier one
    SESSION_RECORDING = "session_recording"
    # optional, off unless given: de-identified extracts reviewed to test and improve the assistants
    SERVICE_IMPROVEMENT = "service_improvement"

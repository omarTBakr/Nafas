from enum import StrEnum


class MessageRole(StrEnum):
    PATIENT = "patient"
    ASSISTANT = "assistant"
    # a doctor's answer to an escalated question (phase 4)
    DOCTOR = "doctor"


class Modality(StrEnum):
    TEXT = "text"
    VOICE = "voice"


class Intent(StrEnum):
    """What a patient's message is for; decides which part of the assistant answers."""

    BOOKING = "booking"
    MEDICAL = "medical"
    ADMIN = "admin"
    SMALLTALK = "smalltalk"
    EMERGENCY = "emergency"
    UNCLEAR = "unclear"


class EscalationReason(StrEnum):
    """Why a patient's question went to the doctor instead of being answered by the assistant."""

    SENSITIVE = "sensitive"
    OUT_OF_SCOPE_MEDICAL = "out_of_scope_medical"
    EMERGENCY = "emergency"
    UNCLEAR = "unclear"
    # the assistant wrote an answer and the output guard stopped it
    OUTPUT_GUARD = "output_guard"


class EscalationStatus(StrEnum):
    OPEN = "open"
    ANSWERED = "answered"
    CLOSED = "closed"
    EXPIRED = "expired"

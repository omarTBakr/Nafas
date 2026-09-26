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

from enum import StrEnum


class Channel(StrEnum):
    """Where a patient talks to Nafas from."""

    TELEGRAM = "telegram"
    EMAIL = "email"
    WHATSAPP = "whatsapp"

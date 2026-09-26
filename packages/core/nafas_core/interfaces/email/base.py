from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class Attachment:
    filename: str
    content: bytes
    mime_type: str


@dataclass
class Email:
    to: str
    subject: str
    text: str
    attachments: list[Attachment] = field(default_factory=list)


class EmailSender(Protocol):
    async def send(self, email: Email) -> bool:
        """True when handed to the mail server; False when email is switched off. Raises EmailError on failure."""
        ...

import asyncio
import smtplib
from email.message import EmailMessage

from nafas_core.exceptions.providers import EmailError
from nafas_core.interfaces.email.base import Email


class SMTPSender:
    """Sends through one SMTP server; blocking smtplib in a thread, one connection per message."""

    def __init__(self, host: str, port: int, sender: str, username: str = "", password: str = "", starttls: bool = True):
        self._host, self._port, self._sender = host, port, sender
        self._username, self._password, self._starttls = username, password, starttls

    def _message(self, email: Email) -> EmailMessage:
        message = EmailMessage()
        message["From"] = self._sender
        message["To"] = email.to
        message["Subject"] = email.subject
        message.set_content(email.text)
        for attachment in email.attachments:
            maintype, subtype = attachment.mime_type.split("/", 1)
            message.add_attachment(attachment.content, maintype=maintype, subtype=subtype, filename=attachment.filename)
        return message

    def _send(self, message: EmailMessage) -> None:
        with smtplib.SMTP(self._host, self._port, timeout=15) as server:
            if self._starttls:
                server.starttls()
            if self._username:
                server.login(self._username, self._password)
            server.send_message(message)

    async def send(self, email: Email) -> bool:
        try:
            await asyncio.to_thread(self._send, self._message(email))
        except (smtplib.SMTPException, OSError) as exc:
            raise EmailError(f"the mail server refused or could not be reached: {type(exc).__name__}") from exc
        return True


class DisabledSender:
    """Email is off (no SMTP_HOST): nothing is sent, and callers can tell."""

    async def send(self, email: Email) -> bool:
        return False

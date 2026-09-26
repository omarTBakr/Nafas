from nafas_core.config import get_setting
from nafas_core.interfaces.email.base import EmailSender

_sender: EmailSender | None = None


def get_email_sender() -> EmailSender:
    """SMTP when SMTP_HOST is set, otherwise a sender that sends nothing."""
    global _sender
    if _sender is None:
        from nafas_core.interfaces.email.smtp import DisabledSender, SMTPSender

        settings = get_setting()
        _sender = (
            SMTPSender(
                settings.smtp_host,
                settings.smtp_port,
                settings.smtp_from,
                settings.smtp_username,
                settings.smtp_password.get_secret_value(),
                settings.smtp_starttls,
            )
            if settings.smtp_host
            else DisabledSender()
        )
    return _sender


def set_email_sender(sender: EmailSender | None) -> None:
    """Replaces the process-wide sender; tests pass a FakeEmailSender, and None to reset."""
    global _sender
    _sender = sender

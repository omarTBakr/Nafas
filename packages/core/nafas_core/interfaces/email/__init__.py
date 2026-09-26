"""Outgoing email: appointment notices today. SMTP, a fake for tests, and off until SMTP_HOST is set."""

from nafas_core.interfaces.email.base import Attachment, Email, EmailSender
from nafas_core.interfaces.email.factory import get_email_sender, set_email_sender

__all__ = ["Attachment", "Email", "EmailSender", "get_email_sender", "set_email_sender"]

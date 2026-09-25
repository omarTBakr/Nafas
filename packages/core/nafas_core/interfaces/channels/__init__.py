"""The messaging channel port: Telegram, email, and later WhatsApp.

A channel turns its own webhook payload into an InboundMessage and knows how to
reply. Everything past that point — the conversation workflow, booking, the
safety gates — sees only InboundMessage, so a new channel is one module here.
"""

from nafas_core.interfaces.channels.base import ChannelAdapter, InboundMessage
from nafas_core.interfaces.channels.factory import get_channel

__all__ = ["ChannelAdapter", "InboundMessage", "get_channel"]

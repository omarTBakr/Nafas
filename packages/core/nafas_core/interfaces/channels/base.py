from dataclasses import dataclass
from typing import Any, Protocol

from nafas_core.enums.channel import Channel


@dataclass
class InboundMessage:
    channel: Channel
    # who sent it, in the channel's own terms: a Telegram chat id, an email address
    external_id: str
    # the channel's id for this message, for de-duplicating webhook retries
    message_id: str
    text: str | None = None
    # a reference download_media understands (a Telegram file_id, an attachment id)
    voice_ref: str | None = None
    voice_mime_type: str | None = None
    sender_name: str | None = None


class ChannelAdapter(Protocol):
    channel: Channel

    def parse_inbound(self, payload: dict[str, Any]) -> InboundMessage | None:
        """The message in a webhook payload, or None for updates that are not one (edits, joins)."""
        ...

    async def send_text(self, external_id: str, text: str) -> None: ...

    async def download_media(self, ref: str) -> bytes: ...

from typing import Any

from enums.channel import Channel
from interfaces.channels.base import InboundMessage


class FakeChannel:
    """
    Records what would have been sent, and serves media from a dict.

    `parse_inbound` accepts the InboundMessage fields as a flat dict, which is
    enough to drive the pipeline from a test without a real webhook payload.
    """

    def __init__(self, channel: Channel = Channel.TELEGRAM, media: dict[str, bytes] | None = None):
        self.channel = channel
        self.media = media or {}
        self.sent: list[tuple[str, str]] = []

    def parse_inbound(self, payload: dict[str, Any]) -> InboundMessage | None:
        if "message_id" not in payload:
            return None

        return InboundMessage(channel=self.channel, **payload)

    async def send_text(self, external_id: str, text: str) -> None:
        self.sent.append((external_id, text))

    async def download_media(self, ref: str) -> bytes:
        return self.media[ref]

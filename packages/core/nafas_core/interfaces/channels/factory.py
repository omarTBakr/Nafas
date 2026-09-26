from nafas_core.enums.channel import Channel
from nafas_core.exceptions.config import MissingSettingError
from nafas_core.interfaces.channels.base import ChannelAdapter

_channels: dict[Channel, ChannelAdapter] = {}


def get_channel(channel: Channel) -> ChannelAdapter:
    """The adapter for one channel. Deferred: Telegram, email and WhatsApp return in a later phase (docs/CHECKLIST.md)."""
    if channel not in _channels:
        raise MissingSettingError(f"no adapter for the {channel} channel yet")

    return _channels[channel]


def set_channel(channel: Channel, adapter: ChannelAdapter | None) -> None:
    """Registers or removes one channel's adapter; tests register a FakeChannel."""
    if adapter is None:
        _channels.pop(channel, None)
    else:
        _channels[channel] = adapter

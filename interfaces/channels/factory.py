from enums.channel import Channel
from exceptions.config import MissingSettingError
from interfaces.channels.base import ChannelAdapter

_channels: dict[Channel, ChannelAdapter] = {}


def get_channel(channel: Channel) -> ChannelAdapter:
    """The adapter for one channel. Telegram arrives in phase 2, email in phase 4."""
    if channel not in _channels:
        raise MissingSettingError(f"no adapter for the {channel} channel yet")

    return _channels[channel]


def set_channel(channel: Channel, adapter: ChannelAdapter | None) -> None:
    """Registers or removes one channel's adapter; tests register a FakeChannel."""
    if adapter is None:
        _channels.pop(channel, None)
    else:
        _channels[channel] = adapter

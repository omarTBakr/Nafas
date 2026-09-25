from nafas_core.config import get_setting
from nafas_core.exceptions.config import MissingSettingError
from nafas_core.interfaces.stt.base import STT

_stt: STT | None = None


def get_stt() -> STT:
    """The process-wide STT for STT_PROVIDER."""
    global _stt
    if _stt is None:
        provider = get_setting().stt_provider
        # every real provider is a case here; none is wired until the spike picks one
        raise MissingSettingError(f"STT_PROVIDER {provider!r} has no implementation yet; pick one after the dialect spike")

    return _stt


def set_stt(stt: STT | None) -> None:
    """Replaces the process-wide STT; tests pass a FakeSTT, and None to reset."""
    global _stt
    _stt = stt

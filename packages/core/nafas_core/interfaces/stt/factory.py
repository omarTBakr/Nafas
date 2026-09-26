from nafas_core.config import get_setting
from nafas_core.enums.providers import STTProvider
from nafas_core.exceptions.config import MissingSettingError
from nafas_core.interfaces.stt.base import STT

_stt: STT | None = None


def get_stt() -> STT:
    """The process-wide STT for STT_PROVIDER."""
    global _stt
    if _stt is None:
        settings = get_setting()
        match settings.stt_provider:
            case STTProvider.SELF_HOSTED:
                from nafas_core.interfaces.stt.http import HttpSTT

                _stt = HttpSTT(settings.stt_url)
            case _:
                raise MissingSettingError("STT_PROVIDER is not set; voice input needs a speech-to-text backend")

    return _stt


def set_stt(stt: STT | None) -> None:
    """Replaces the process-wide STT; tests pass a FakeSTT, and None to reset."""
    global _stt
    _stt = stt

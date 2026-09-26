from nafas_core.config import get_setting
from nafas_core.interfaces.tts.base import TTS

_tts: TTS | None = None


def get_tts() -> TTS:
    """The process-wide client for the tts service at TTS_URL."""
    global _tts
    if _tts is None:
        from nafas_core.interfaces.tts.http import HttpTTS

        _tts = HttpTTS(get_setting().tts_url)

    return _tts


def set_tts(tts: TTS | None) -> None:
    """Replaces the process-wide TTS; tests pass a FakeTTS, and None to reset."""
    global _tts
    _tts = tts

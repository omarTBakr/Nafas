from nafas_core.interfaces.tts.base import SpeechAudio


class FakeTTS:
    """Returns a tiny fixed WAV and records what it was asked to say."""

    def __init__(self, fail: bool = False):
        self.fail = fail
        self.calls: list[dict] = []

    async def speak(self, text: str, dialect: str, voice: str | None) -> SpeechAudio:
        from nafas_core.exceptions.providers import TTSError

        self.calls.append({"text": text, "dialect": dialect, "voice": voice})
        if self.fail:
            raise TTSError("the fake tts was told to fail")
        return SpeechAudio(audio=b"RIFF-fake-wav", mime_type="audio/wav", seconds=1.0, model_id="fake/tts")

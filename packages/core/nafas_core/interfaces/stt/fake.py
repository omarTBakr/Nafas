from nafas_core.interfaces.stt.base import Transcript


class FakeSTT:
    """Returns a fixed transcript and records what it was asked to transcribe."""

    def __init__(self, transcript: Transcript | str = "", language: str | None = "ar"):
        self._transcript = transcript if isinstance(transcript, Transcript) else Transcript(transcript, language)
        self.calls: list[dict] = []

    async def transcribe(
        self, audio: bytes, mime_type: str, language_hint: str | None = None, diarize: bool = False
    ) -> Transcript:
        self.calls.append({"audio": audio, "mime_type": mime_type, "language_hint": language_hint, "diarize": diarize})
        return self._transcript

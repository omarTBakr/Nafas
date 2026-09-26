from dataclasses import dataclass
from typing import Protocol


@dataclass
class SpeechAudio:
    audio: bytes
    mime_type: str
    seconds: float
    model_id: str


class TTS(Protocol):
    async def speak(self, text: str, dialect: str, voice: str | None) -> SpeechAudio:
        """Speaks one message in one of the 13 dialects. Raises TTSError on failure."""
        ...

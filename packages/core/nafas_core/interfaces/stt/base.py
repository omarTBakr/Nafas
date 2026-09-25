from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class Segment:
    """A stretch of speech; `speaker` is filled only by diarizing providers."""

    start_seconds: float
    end_seconds: float
    text: str
    speaker: str | None = None


@dataclass
class Transcript:
    text: str
    # ISO 639-1 as detected ("ar", "en"); code-switched audio reports the dominant one
    language: str | None = None
    segments: list[Segment] = field(default_factory=list)


class STT(Protocol):
    async def transcribe(
        self,
        audio: bytes,
        mime_type: str,
        language_hint: str | None = None,
        diarize: bool = False,
    ) -> Transcript:
        """Transcribes one recording. Raises STTError on failure."""
        ...

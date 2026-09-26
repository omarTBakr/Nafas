from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np

from stt.audio import SAMPLE_RATE
from stt.config import Settings

# Whisper's language names for what patients speak; the dialectal fine-tune is
# Arabic, English is passed through for the rare English voice note
LANGUAGES = {"ar": "arabic", "en": "english"}


@dataclass
class Transcript:
    text: str
    language: str


class Transcriber(Protocol):
    device: str

    def transcribe(self, samples: np.ndarray, language: str) -> Transcript: ...


class WhisperTranscriber:
    """The pinned Whisper fine-tune, loaded once from the weights baked into the image."""

    def __init__(self, settings: Settings):
        import torch
        from transformers import pipeline

        if settings.device == "auto":
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
        else:
            self.device = settings.device

        baked = (Path(settings.model_dir) / "config.json").is_file()
        self._pipe = pipeline(
            "automatic-speech-recognition",
            model=settings.model_dir if baked else settings.model_id,
            revision=None if baked else settings.model_revision,
            # half precision on the GPU: the same answers at half the memory
            torch_dtype=torch.float16 if self.device == "cuda" else torch.float32,
            device=self.device,
            chunk_length_s=settings.chunk_seconds,
        )

    def transcribe(self, samples: np.ndarray, language: str) -> Transcript:
        result = self._pipe(
            {"raw": samples, "sampling_rate": SAMPLE_RATE},
            generate_kwargs={"language": LANGUAGES[language], "task": "transcribe"},
        )
        return Transcript(text=result["text"].strip(), language=language)

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np

from tts.config import Settings

# the patient's dialect code → OmniVoice's language name in the Lahgtna fine-tunes
LAHGTNA_LANGUAGES = {
    "eg": "egyptian lahgtna",
    "sa": "saudi lahgtna",
    "ma": "moroccan lahgtna",
    "bh": "bahraini lahgtna",
    "sd": "sudanese lahgtna",
    "iq": "iraqi lahgtna",
    "lb": "lebanese lahgtna",
    "sy": "syrian lahgtna",
    "ly": "libyan lahgtna",
    "ps": "palestinian lahgtna",
    "tn": "tunisian lahgtna",
    "dz": "algerian lahgtna",
    "ye": "yemeni lahgtna",
}


def register_dialects() -> None:
    """
    Teaches the omnivoice library the Lahgtna dialect names. The fine-tunes
    were trained with each dialect's code in the prompt's language slot
    (Lahgtna's own fork of the library maps "egyptian lahgtna" to "eg"); the
    library on PyPI does not know the names, and would drop them and speak
    with no dialect at all. Idempotent.
    """
    from omnivoice.utils import lang_map

    for code, name in LAHGTNA_LANGUAGES.items():
        lang_map.LANG_NAME_TO_ID[name] = code
        lang_map.LANG_NAMES.add(name)
        lang_map.LANG_IDS.add(code)


@dataclass
class Speech:
    samples: np.ndarray
    rate: int
    model_id: str


class Synthesizer(Protocol):
    device: str

    def speak(self, text: str, dialect: str, voice: str | None) -> Speech: ...

    def supported(self) -> dict[str, bool]:
        """Per dialect: does the loaded model know its language name? False means it would speak language-agnostic."""
        ...


def _load(model_dir: str, model_id: str, revision: str, device: str):
    import torch
    from omnivoice import OmniVoice

    baked = (Path(model_dir) / "config.json").is_file()
    return OmniVoice.from_pretrained(
        model_dir if baked else model_id,
        revision=None if baked else revision,
        device_map="cuda:0" if device == "cuda" else "cpu",
        # half precision on the GPU: the same voice at half the memory
        dtype=torch.float16 if device == "cuda" else torch.float32,
    )


class OmniVoiceSynthesizer:
    """The pinned Lahgtna OmniVoice models, loaded once from the weights baked into the image."""

    def __init__(self, settings: Settings):
        import torch

        self.device = ("cuda" if torch.cuda.is_available() else "cpu") if settings.device == "auto" else settings.device
        register_dialects()
        self._settings = settings
        self._model = _load(settings.model_dir, settings.model_id, settings.model_revision, self.device)
        self._egyptian = (
            _load(settings.egyptian_model_dir, settings.egyptian_model_id, settings.egyptian_model_revision, self.device)
            if settings.use_egyptian_model
            else None
        )

    def _for(self, dialect: str):
        if dialect == "eg" and self._egyptian is not None:
            return self._egyptian, self._settings.egyptian_model_id
        return self._model, self._settings.model_id

    def supported(self) -> dict[str, bool]:
        names = {n.lower() for n in self._model.supported_language_names()}
        return {code: language in names for code, language in LAHGTNA_LANGUAGES.items()}

    def speak(self, text: str, dialect: str, voice: str | None) -> Speech:
        model, model_id = self._for(dialect)
        audio = model.generate(
            text=text,
            language=LAHGTNA_LANGUAGES[dialect],
            # the built-in voice, steered to the patient's choice; no cloning, no reference audio
            instruct=voice,
            num_step=self._settings.num_step,
        )
        return Speech(samples=audio[0], rate=model.sampling_rate, model_id=model_id)

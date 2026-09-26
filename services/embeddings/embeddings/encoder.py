from pathlib import Path
from typing import Protocol

from embeddings.config import Settings


class Encoder(Protocol):
    device: str

    def encode(self, texts: list[str]) -> list[list[float]]: ...


class BgeM3Encoder:
    """bge-m3's dense vectors, normalised for cosine search, from the weights baked into the image."""

    def __init__(self, settings: Settings):
        from sentence_transformers import SentenceTransformer

        self.device = settings.device
        baked = (Path(settings.model_dir) / "config.json").is_file()
        self._model = SentenceTransformer(
            settings.model_dir if baked else settings.model_id,
            revision=None if baked else settings.model_revision,
            device=self.device,
        )

    def encode(self, texts: list[str]) -> list[list[float]]:
        return self._model.encode(texts, normalize_embeddings=True, batch_size=16).tolist()

from nafas_core.config import get_setting
from nafas_core.exceptions.config import MissingSettingError
from nafas_core.interfaces.embeddings.base import Embeddings

_embeddings: Embeddings | None = None


def get_embeddings() -> Embeddings:
    """The process-wide embeddings model for EMBEDDINGS_PROVIDER."""
    global _embeddings
    if _embeddings is None:
        provider = get_setting().embeddings_provider
        # bge-m3 is wired in phase 7, when the first document gets indexed
        raise MissingSettingError(f"EMBEDDINGS_PROVIDER {provider!r} has no implementation yet")

    return _embeddings


def set_embeddings(embeddings: Embeddings | None) -> None:
    """Replaces the process-wide embeddings model; tests pass a FakeEmbeddings, and None to reset."""
    global _embeddings
    _embeddings = embeddings

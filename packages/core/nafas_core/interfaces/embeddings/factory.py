from nafas_core.config import get_setting
from nafas_core.enums.providers import EmbeddingsProvider
from nafas_core.exceptions.config import MissingSettingError
from nafas_core.interfaces.embeddings.base import Embeddings

_embeddings: Embeddings | None = None


def get_embeddings() -> Embeddings:
    """The process-wide embeddings model for EMBEDDINGS_PROVIDER."""
    global _embeddings
    if _embeddings is None:
        settings = get_setting()
        match settings.embeddings_provider:
            case EmbeddingsProvider.SELF_HOSTED:
                from nafas_core.interfaces.embeddings.http import HttpEmbeddings

                _embeddings = HttpEmbeddings(settings.embeddings_url)
            case _:
                raise MissingSettingError("EMBEDDINGS_PROVIDER is not set; documents cannot be indexed or searched")

    return _embeddings


def set_embeddings(embeddings: Embeddings | None) -> None:
    """Replaces the process-wide embeddings model; tests pass a FakeEmbeddings, and None to reset."""
    global _embeddings
    _embeddings = embeddings

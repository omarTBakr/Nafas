"""The embeddings port behind per-patient RAG.

Every vector in `chunks` must come from one model with one dimension count, so
switching models means re-embedding, not just a config change.
"""

from interfaces.embeddings.base import EMBEDDING_DIMENSIONS, Embeddings
from interfaces.embeddings.factory import get_embeddings

__all__ = ["EMBEDDING_DIMENSIONS", "Embeddings", "get_embeddings"]

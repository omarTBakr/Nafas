import hashlib
import math

from interfaces.embeddings.base import EMBEDDING_DIMENSIONS


class FakeEmbeddings:
    """
    Deterministic unit vectors derived from a hash of the text.

    Identical texts get identical vectors, so a retrieval test can plant an
    exact match and expect it first; unrelated texts are near-orthogonal.
    """

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [_vector(text) for text in texts]


def _vector(text: str) -> list[float]:
    raw = []
    counter = 0
    while len(raw) < EMBEDDING_DIMENSIONS:
        digest = hashlib.sha256(f"{counter}:{text}".encode()).digest()
        raw.extend(byte - 127.5 for byte in digest)
        counter += 1

    raw = raw[:EMBEDDING_DIMENSIONS]
    norm = math.sqrt(sum(x * x for x in raw))

    return [x / norm for x in raw]

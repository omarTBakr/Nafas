from typing import Protocol

# the width of chunks.embedding; bge-m3's size, which the plan settles on
EMBEDDING_DIMENSIONS = 1024


class Embeddings(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """One vector of EMBEDDING_DIMENSIONS floats per text, in order."""
        ...

import httpx

from nafas_core.exceptions.providers import EmbeddingsError
from nafas_core.interfaces.embeddings.base import EMBEDDING_DIMENSIONS

TIMEOUT_SECONDS = 60.0


class HttpEmbeddings:
    """Client for the embeddings service's POST /v1/embed."""

    def __init__(self, base_url: str, client: httpx.AsyncClient | None = None):
        self._client = client or httpx.AsyncClient(base_url=base_url, timeout=TIMEOUT_SECONDS)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            response = await self._client.post("/v1/embed", json={"texts": texts})
        except httpx.HTTPError as exc:
            raise EmbeddingsError(f"embeddings service unreachable: {exc}") from exc
        if response.status_code != 200:
            raise EmbeddingsError(f"embeddings service answered {response.status_code}")

        vectors = response.json()["vectors"]
        if len(vectors) != len(texts) or any(len(v) != EMBEDDING_DIMENSIONS for v in vectors):
            # one model, one width, for every vector in chunks: anything else is a misconfigured service
            raise EmbeddingsError(f"expected {len(texts)} vectors of {EMBEDDING_DIMENSIONS}")
        return vectors

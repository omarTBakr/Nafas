import httpx

from nafas_core.enums.dialect import Dialect
from nafas_core.exceptions.providers import ProviderError
from nafas_core.interfaces.dialect.base import DialectPrediction


class HttpDialectClassifier:
    """Client for the dialect-router service's POST /v1/classify."""

    def __init__(self, base_url: str, timeout_seconds: float = 5.0, client: httpx.AsyncClient | None = None):
        self._client = client or httpx.AsyncClient(base_url=base_url, timeout=timeout_seconds)

    async def classify(self, texts: list[str]) -> list[DialectPrediction]:
        try:
            response = await self._client.post("/v1/classify", json={"texts": texts})
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProviderError(f"dialect-router failed: {exc}") from exc

        body = response.json()
        return [
            DialectPrediction(
                dialect=Dialect(p["label"]),
                score=p["score"],
                low_confidence=p["low_confidence"],
                model_revision=body["model_revision"],
            )
            for p in body["predictions"]
        ]

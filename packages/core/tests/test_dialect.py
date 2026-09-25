import httpx
import pytest

from nafas_core.enums.dialect import Dialect
from nafas_core.exceptions.providers import ProviderError
from nafas_core.interfaces.dialect.http import HttpDialectClassifier


def client_with(handler) -> HttpDialectClassifier:
    transport = httpx.MockTransport(handler)
    return HttpDialectClassifier("http://router", client=httpx.AsyncClient(base_url="http://router", transport=transport))


async def test_predictions_map_onto_the_dialect_enum():
    def handler(request):
        assert request.url.path == "/v1/classify"
        return httpx.Response(
            200,
            json={
                "model_id": "oddadmix/dialect-router-v0.1",
                "model_revision": "abc123",
                "predictions": [
                    {"label": "eg", "score": 0.93, "low_confidence": False, "scores": {}},
                    {"label": "ma", "score": 0.41, "low_confidence": True, "scores": {}},
                ],
            },
        )

    egyptian, moroccan = await client_with(handler).classify(["عايز أحجز", "بغيت نحجز"])

    assert egyptian.dialect is Dialect.EGYPTIAN
    assert moroccan.dialect is Dialect.MOROCCAN
    assert moroccan.low_confidence is True
    assert egyptian.model_revision == "abc123"


async def test_a_failing_service_raises_a_provider_error():
    with pytest.raises(ProviderError, match="dialect-router"):
        await client_with(lambda request: httpx.Response(503)).classify(["x"])

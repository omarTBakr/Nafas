import pytest
from fastapi.testclient import TestClient

from dialect_router.app import create_app
from dialect_router.classifier import Prediction
from dialect_router.config import Settings


class FakeClassifier:
    """Labels a text "eg" when it contains an Egyptian marker word, else "ar", with fixed scores."""

    device = "cpu"
    labels = ["ar", "eg"]

    def __init__(self):
        self.seen: list[list[str]] = []

    def classify(self, texts):
        self.seen.append(texts)
        return [
            Prediction("eg", 0.9, {"ar": 0.1, "eg": 0.9}) if "عايز" in t else Prediction("ar", 0.55, {"ar": 0.55, "eg": 0.45})
            for t in texts
        ]


@pytest.fixture
def client():
    settings = Settings(max_batch_size=3)
    return TestClient(create_app(FakeClassifier(), settings))


def test_the_pinned_model_is_the_one_configured():
    """model.toml is the source of truth for what gets served."""
    settings = Settings()

    assert settings.model_id == "oddadmix/dialect-router-v0.1"
    assert len(settings.model_revision) == 40


def test_health_reports_exactly_what_is_serving(client):
    body = client.get("/health").json()

    assert body["model_revision"] == Settings().model_revision
    assert body["device"] == "cpu"
    assert body["labels"] == ["ar", "eg"]


def test_classify_returns_one_prediction_per_text_in_order(client):
    body = client.post("/v1/classify", json={"texts": ["عايز أحجز بكرة", "أريد حجز موعد"]}).json()

    assert [p["label"] for p in body["predictions"]] == ["eg", "ar"]
    assert body["model_id"] == "oddadmix/dialect-router-v0.1"


def test_low_confidence_is_flagged(client):
    confident, unsure = client.post("/v1/classify", json={"texts": ["عايز", "موعد"]}).json()["predictions"]

    assert confident["low_confidence"] is False
    assert unsure["low_confidence"] is True


def test_oversized_batches_are_refused(client):
    response = client.post("/v1/classify", json={"texts": ["a", "b", "c", "d"]})

    assert response.status_code == 413


def test_an_empty_batch_is_invalid(client):
    assert client.post("/v1/classify", json={"texts": []}).status_code == 422


def test_metrics_count_predictions(client):
    client.post("/v1/classify", json={"texts": ["عايز"]})

    metrics = client.get("/metrics").text

    assert 'dialect_router_predictions_total{confidence="ok",label="eg"}' in metrics
    assert "dialect_router_inference_seconds_bucket" in metrics

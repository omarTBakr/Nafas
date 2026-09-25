import time

from fastapi import FastAPI, HTTPException, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from pydantic import BaseModel, Field

from dialect_router.classifier import Classifier
from dialect_router.config import Settings

REQUESTS = Counter("dialect_router_requests_total", "Classify requests", ["outcome"])
TEXTS = Counter("dialect_router_texts_total", "Texts classified")
PREDICTIONS = Counter("dialect_router_predictions_total", "Predictions by label", ["label", "confidence"])
LATENCY = Histogram(
    "dialect_router_inference_seconds",
    "Model time per request",
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5),
)
CONFIDENCE = Histogram(
    "dialect_router_top_score", "Top-label probability", buckets=(0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 1)
)


class ClassifyRequest(BaseModel):
    texts: list[str] = Field(min_length=1)


class PredictionOut(BaseModel):
    label: str
    score: float
    low_confidence: bool
    scores: dict[str, float]


class ClassifyResponse(BaseModel):
    model_id: str
    model_revision: str
    predictions: list[PredictionOut]


def create_app(classifier: Classifier, settings: Settings) -> FastAPI:
    """
    The HTTP service around one loaded classifier.

    Texts are never logged: they are patient messages. What is kept is the
    label, the score and whether it was confident — enough for metrics, and
    the caller stores low-confidence items for the feedback pipeline.
    """
    app = FastAPI(title="Nafas dialect-router")

    @app.get("/health")
    def health() -> dict:
        """The exact model answering requests, so any result can be traced to it."""
        return {
            "status": "ok",
            "model_id": settings.model_id,
            "model_revision": settings.model_revision,
            "device": classifier.device,
            "labels": classifier.labels,
            "low_confidence_threshold": settings.low_confidence_threshold,
        }

    @app.get("/metrics")
    def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.post("/v1/classify", response_model=ClassifyResponse)
    def classify(request: ClassifyRequest) -> ClassifyResponse:
        # a plain def: FastAPI runs it in a thread, so inference never blocks the event loop
        if len(request.texts) > settings.max_batch_size:
            REQUESTS.labels("rejected").inc()
            raise HTTPException(413, f"at most {settings.max_batch_size} texts per request")

        started = time.perf_counter()
        try:
            predictions = classifier.classify(request.texts)
        except Exception:
            REQUESTS.labels("error").inc()
            raise
        LATENCY.observe(time.perf_counter() - started)

        REQUESTS.labels("ok").inc()
        TEXTS.inc(len(request.texts))

        out = []
        for prediction in predictions:
            low = prediction.score < settings.low_confidence_threshold
            PREDICTIONS.labels(prediction.label, "low" if low else "ok").inc()
            CONFIDENCE.observe(prediction.score)
            out.append(
                PredictionOut(label=prediction.label, score=prediction.score, low_confidence=low, scores=prediction.scores)
            )

        return ClassifyResponse(model_id=settings.model_id, model_revision=settings.model_revision, predictions=out)

    return app

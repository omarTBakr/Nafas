import time

from fastapi import FastAPI, HTTPException, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from pydantic import BaseModel, Field

from embeddings.config import Settings
from embeddings.encoder import Encoder

REQUESTS = Counter("embeddings_requests_total", "Embedding requests", ["outcome"])
TEXTS = Histogram("embeddings_texts", "Texts per request", buckets=(1, 2, 4, 8, 16, 32, 64))
LATENCY = Histogram("embeddings_seconds", "Model time per request", buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 4, 8))


class EmbedIn(BaseModel):
    texts: list[str] = Field(min_length=1)


class EmbedOut(BaseModel):
    vectors: list[list[float]]
    model_id: str
    model_revision: str


def create_app(encoder: Encoder, settings: Settings) -> FastAPI:
    """The HTTP service around the loaded model. Texts are patient records and are never logged."""
    app = FastAPI(title="Nafas embeddings")

    @app.get("/health")
    def health() -> dict:
        return {
            "status": "ok",
            "model_id": settings.model_id,
            "model_revision": settings.model_revision,
            "pinned": settings.pinned,
            "dimensions": settings.dimensions,
            "device": encoder.device,
        }

    @app.get("/metrics")
    def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.post("/v1/embed", response_model=EmbedOut)
    def embed(request: EmbedIn) -> EmbedOut:
        if len(request.texts) > settings.max_texts:
            REQUESTS.labels("too_many").inc()
            raise HTTPException(413, f"at most {settings.max_texts} texts per request")
        if any(len(t) > settings.max_chars for t in request.texts):
            REQUESTS.labels("too_long").inc()
            raise HTTPException(413, f"at most {settings.max_chars} characters per text")

        started = time.perf_counter()
        vectors = encoder.encode(request.texts)
        LATENCY.observe(time.perf_counter() - started)
        TEXTS.observe(len(request.texts))
        if any(len(v) != settings.dimensions for v in vectors):
            REQUESTS.labels("wrong_width").inc()
            raise HTTPException(500, "the model gave vectors of the wrong width")
        REQUESTS.labels("ok").inc()
        return EmbedOut(vectors=vectors, model_id=settings.model_id, model_revision=settings.model_revision)

    return app

import time
from typing import Literal

from fastapi import FastAPI, HTTPException, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from pydantic import BaseModel, Field

from tts.audio import to_wav
from tts.config import Settings
from tts.synthesizer import LAHGTNA_LANGUAGES, Synthesizer

REQUESTS = Counter("tts_requests_total", "Speech requests", ["outcome", "dialect"])
AUDIO_SECONDS = Histogram("tts_audio_seconds", "Length of speech produced", buckets=(1, 2, 5, 10, 20, 40))
LATENCY = Histogram("tts_inference_seconds", "Model time per request", buckets=(0.1, 0.25, 0.5, 1, 2, 4, 8, 16))
REALTIME_FACTOR = Histogram(
    "tts_realtime_factor", "Inference seconds per audio second", buckets=(0.02, 0.05, 0.1, 0.2, 0.5, 1, 2)
)

Dialect = Literal["eg", "sa", "ma", "bh", "sd", "iq", "lb", "sy", "ly", "ps", "tn", "dz", "ye"]


class SpeakIn(BaseModel):
    text: str = Field(min_length=1)
    dialect: Dialect
    voice: Literal["female", "male"] | None = None


def create_app(synthesizer: Synthesizer, settings: Settings) -> FastAPI:
    """The HTTP service around the loaded models. Text is never logged; metrics keep only sizes and times."""
    app = FastAPI(title="Nafas tts")
    supported = synthesizer.supported()

    @app.get("/health")
    def health() -> dict:
        return {
            "status": "ok",
            "model_id": settings.model_id,
            "model_revision": settings.model_revision,
            "egyptian_model": (
                {"model_id": settings.egyptian_model_id, "model_revision": settings.egyptian_model_revision}
                if settings.use_egyptian_model
                else None
            ),
            "device": synthesizer.device,
            "max_chars": settings.max_chars,
            # a dialect the model does not know would be spoken language-agnostic: visible here, refused below
            "dialects": supported,
        }

    @app.get("/metrics")
    def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.post("/v1/speak", responses={200: {"content": {"audio/wav": {}}}})
    def speak(request: SpeakIn) -> Response:
        # a plain def: FastAPI runs it in a thread, so inference never blocks the loop
        if len(request.text) > settings.max_chars:
            REQUESTS.labels("too_long", request.dialect).inc()
            raise HTTPException(413, f"at most {settings.max_chars} characters per message")
        if not supported.get(request.dialect, False):
            REQUESTS.labels("unsupported", request.dialect).inc()
            raise HTTPException(422, f"the loaded model does not speak {LAHGTNA_LANGUAGES[request.dialect]}")

        started = time.perf_counter()
        try:
            speech = synthesizer.speak(request.text, request.dialect, request.voice)
        except Exception:
            REQUESTS.labels("error", request.dialect).inc()
            raise
        elapsed = time.perf_counter() - started

        length = len(speech.samples) / speech.rate
        REQUESTS.labels("ok", request.dialect).inc()
        AUDIO_SECONDS.observe(length)
        LATENCY.observe(elapsed)
        if length > 0:
            REALTIME_FACTOR.observe(elapsed / length)

        return Response(
            to_wav(speech.samples, speech.rate),
            media_type="audio/wav",
            headers={"X-Model-Id": speech.model_id, "X-Audio-Seconds": f"{length:.2f}"},
        )

    return app

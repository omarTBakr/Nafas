import time
from typing import Literal

from fastapi import FastAPI, File, Form, HTTPException, Response, UploadFile
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from pydantic import BaseModel

from stt.audio import UnreadableAudio, decode, seconds
from stt.config import Settings
from stt.transcriber import Transcriber

REQUESTS = Counter("stt_requests_total", "Transcription requests", ["outcome"])
AUDIO_SECONDS = Histogram("stt_audio_seconds", "Length of transcribed audio", buckets=(2, 5, 10, 20, 30, 60, 120, 180))
LATENCY = Histogram("stt_inference_seconds", "Model time per request", buckets=(0.1, 0.25, 0.5, 1, 2, 4, 8, 16, 32))
# realtime factor: model seconds per audio second; the number capacity planning needs
REALTIME_FACTOR = Histogram(
    "stt_realtime_factor", "Inference seconds per audio second", buckets=(0.02, 0.05, 0.1, 0.2, 0.5, 1, 2)
)


class TranscriptOut(BaseModel):
    text: str
    language: str
    seconds: float
    model_id: str
    model_revision: str


def create_app(transcriber: Transcriber, settings: Settings) -> FastAPI:
    """
    The HTTP service around one loaded model. Neither audio nor text is
    logged — they are the patient's words; metrics keep only sizes and times.
    """
    app = FastAPI(title="Nafas stt")

    @app.get("/health")
    def health() -> dict:
        return {
            "status": "ok",
            "model_id": settings.model_id,
            "model_revision": settings.model_revision,
            "device": transcriber.device,
            "max_seconds": settings.max_seconds,
        }

    @app.get("/metrics")
    def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.post("/v1/transcribe", response_model=TranscriptOut)
    def transcribe(audio: UploadFile = File(...), language: Literal["ar", "en"] = Form("ar")) -> TranscriptOut:
        # a plain def: FastAPI runs it in a thread, so decoding and inference never block the loop
        data = audio.file.read(settings.max_bytes + 1)
        if len(data) > settings.max_bytes:
            REQUESTS.labels("too_large").inc()
            raise HTTPException(413, f"at most {settings.max_bytes} bytes per recording")

        try:
            samples = decode(data)
        except UnreadableAudio as exc:
            REQUESTS.labels("unreadable").inc()
            raise HTTPException(422, "the recording could not be read") from exc

        length = seconds(samples)
        if length > settings.max_seconds:
            REQUESTS.labels("too_long").inc()
            raise HTTPException(413, f"at most {settings.max_seconds} seconds per recording")

        started = time.perf_counter()
        try:
            transcript = transcriber.transcribe(samples, language)
        except Exception:
            REQUESTS.labels("error").inc()
            raise
        elapsed = time.perf_counter() - started

        REQUESTS.labels("ok").inc()
        AUDIO_SECONDS.observe(length)
        LATENCY.observe(elapsed)
        if length > 0:
            REALTIME_FACTOR.observe(elapsed / length)

        return TranscriptOut(
            text=transcript.text,
            language=transcript.language,
            seconds=round(length, 2),
            model_id=settings.model_id,
            model_revision=settings.model_revision,
        )

    return app

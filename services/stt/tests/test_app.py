import io
import math
import shutil
import struct
import wave

import numpy as np
import pytest
from fastapi.testclient import TestClient

from stt.app import create_app
from stt.config import Settings
from stt.transcriber import Transcript

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="decoding needs ffmpeg")


def tone(seconds: float, rate: int = 44_100) -> bytes:
    """A WAV of a 440 Hz tone at a sample rate the model does not use, so decoding must resample."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(2)
        out.setsampwidth(2)
        out.setframerate(rate)
        frames = int(seconds * rate)
        sample = [int(8000 * math.sin(2 * math.pi * 440 * i / rate)) for i in range(frames)]
        out.writeframes(b"".join(struct.pack("<hh", s, s) for s in sample))
    return buffer.getvalue()


class FakeTranscriber:
    device = "cpu"

    def __init__(self):
        self.heard: list[tuple[np.ndarray, str]] = []

    def transcribe(self, samples, language):
        self.heard.append((samples, language))
        return Transcript(text="عايز أحجز بكرة", language=language)


@pytest.fixture
def service():
    fake = FakeTranscriber()
    return TestClient(create_app(fake, Settings(max_seconds=5, max_bytes=2_000_000))), fake


def test_the_pinned_model_is_the_one_configured():
    settings = Settings()

    assert settings.model_id == "oddadmix/whisper-large-v3-turbo-arabic-dialectal-v2"
    assert len(settings.model_revision) == 40


def test_audio_is_decoded_to_16k_mono_before_the_model_hears_it(service):
    client, fake = service

    response = client.post("/v1/transcribe", files={"audio": ("note.wav", tone(1.5), "audio/wav")})

    assert response.status_code == 200
    body = response.json()
    assert body["text"] == "عايز أحجز بكرة"
    assert body["seconds"] == pytest.approx(1.5, abs=0.05)
    samples, language = fake.heard[0]
    assert samples.dtype == np.float32 and len(samples) == pytest.approx(24_000, abs=800)
    assert language == "ar"


def test_an_english_note_is_passed_as_english(service):
    client, fake = service

    client.post("/v1/transcribe", files={"audio": ("note.wav", tone(0.5), "audio/wav")}, data={"language": "en"})

    assert fake.heard[0][1] == "en"


def test_too_long_is_refused_before_the_model_runs(service):
    client, fake = service

    response = client.post("/v1/transcribe", files={"audio": ("long.wav", tone(6), "audio/wav")})

    assert response.status_code == 413
    assert fake.heard == []


def test_something_that_is_not_audio_is_422(service):
    client, _ = service

    response = client.post("/v1/transcribe", files={"audio": ("x.webm", b"definitely not audio", "audio/webm")})

    assert response.status_code == 422


def test_only_arabic_or_english(service):
    client, _ = service

    response = client.post("/v1/transcribe", files={"audio": ("n.wav", tone(0.5), "audio/wav")}, data={"language": "fr"})

    assert response.status_code == 422


def test_health_and_metrics(service):
    client, _ = service
    client.post("/v1/transcribe", files={"audio": ("note.wav", tone(1), "audio/wav")})

    assert client.get("/health").json()["device"] == "cpu"
    assert "stt_realtime_factor_bucket" in client.get("/metrics").text

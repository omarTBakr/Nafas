import io
import wave

import numpy as np
import pytest
from fastapi.testclient import TestClient

from tts.app import create_app
from tts.audio import to_wav
from tts.config import Settings
from tts.synthesizer import LAHGTNA_LANGUAGES, Speech


class FakeSynthesizer:
    device = "cpu"

    def __init__(self, unsupported: tuple[str, ...] = ()):
        self.spoken: list[tuple[str, str, str | None]] = []
        self.unsupported = unsupported

    def supported(self):
        return {code: code not in self.unsupported for code in LAHGTNA_LANGUAGES}

    def speak(self, text, dialect, voice):
        self.spoken.append((text, dialect, voice))
        # half a second of a quiet tone at the model's 24 kHz
        return Speech(samples=0.1 * np.sin(np.linspace(0, 440 * np.pi, 12_000)), rate=24_000, model_id="fake/model")


@pytest.fixture
def service():
    fake = FakeSynthesizer(unsupported=("dz",))
    return TestClient(create_app(fake, Settings(max_chars=50))), fake


def test_the_pinned_models_are_the_ones_configured():
    settings = Settings()

    assert settings.model_id == "oddadmix/lahgtna-omnivoice-v2"
    assert len(settings.model_revision) == 40 and len(settings.egyptian_model_revision) == 40
    # v3 is not served until it wins the listening test
    assert settings.use_egyptian_model is False


def test_speech_comes_back_as_a_playable_wav_in_the_chosen_dialect_and_voice(service):
    client, fake = service

    response = client.post("/v1/speak", json={"text": "موعدك يوم الأربعاء", "dialect": "eg", "voice": "female"})

    assert response.status_code == 200 and response.headers["content-type"] == "audio/wav"
    assert response.headers["x-audio-seconds"] == "0.50"
    with wave.open(io.BytesIO(response.content)) as heard:
        assert (heard.getnchannels(), heard.getframerate(), heard.getnframes()) == (1, 24_000, 12_000)
    assert fake.spoken == [("موعدك يوم الأربعاء", "eg", "female")]


def test_long_text_and_unknown_or_unsupported_dialects_are_refused(service):
    client, fake = service

    assert client.post("/v1/speak", json={"text": "ا" * 51, "dialect": "eg"}).status_code == 413
    assert client.post("/v1/speak", json={"text": "اهلا", "dialect": "xx"}).status_code == 422
    unsupported = client.post("/v1/speak", json={"text": "اهلا", "dialect": "dz"})
    assert unsupported.status_code == 422 and "algerian lahgtna" in unsupported.json()["detail"]
    assert fake.spoken == []


def test_health_reports_the_config_and_which_dialects_the_model_knows(service):
    client, _ = service

    health = client.get("/health").json()

    assert health["model_id"] == "oddadmix/lahgtna-omnivoice-v2"
    assert health["dialects"]["eg"] is True and health["dialects"]["dz"] is False
    assert health["egyptian_model"] is None
    assert "tts_requests_total" in client.get("/metrics").text


def test_samples_outside_the_range_are_clipped_not_wrapped():
    wav = to_wav(np.array([2.0, -2.0, 0.0]), 24_000)

    with wave.open(io.BytesIO(wav)) as heard:
        frames = np.frombuffer(heard.readframes(3), dtype="<i2")
    assert list(frames) == [32767, -32767, 0]

import httpx

from nafas_core.exceptions.providers import TTSError
from nafas_core.interfaces.tts.base import SpeechAudio

TIMEOUT_SECONDS = 30.0


class HttpTTS:
    """Client for the tts service's POST /v1/speak."""

    def __init__(self, base_url: str, client: httpx.AsyncClient | None = None):
        self._client = client or httpx.AsyncClient(base_url=base_url, timeout=TIMEOUT_SECONDS)

    async def speak(self, text: str, dialect: str, voice: str | None) -> SpeechAudio:
        try:
            response = await self._client.post("/v1/speak", json={"text": text, "dialect": dialect, "voice": voice})
        except httpx.HTTPError as exc:
            raise TTSError(f"tts service unreachable: {exc}") from exc

        if response.status_code != 200:
            raise TTSError(f"tts service answered {response.status_code}")

        return SpeechAudio(
            audio=response.content,
            mime_type=response.headers.get("content-type", "audio/wav"),
            seconds=float(response.headers.get("x-audio-seconds", 0)),
            model_id=response.headers.get("x-model-id", ""),
        )

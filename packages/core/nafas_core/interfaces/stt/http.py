import httpx

from nafas_core.exceptions.providers import STTError
from nafas_core.interfaces.stt.base import Transcript

# a voice note can be up to three minutes; leave room for the model
TIMEOUT_SECONDS = 60.0


class HttpSTT:
    """Client for the stt service's POST /v1/transcribe."""

    def __init__(self, base_url: str, client: httpx.AsyncClient | None = None):
        self._client = client or httpx.AsyncClient(base_url=base_url, timeout=TIMEOUT_SECONDS)

    async def transcribe(
        self, audio: bytes, mime_type: str, language_hint: str | None = None, diarize: bool = False
    ) -> Transcript:
        if diarize:
            # voice notes have one speaker; consultations (phase 7) get their own diarizing backend
            raise STTError("the stt service does not diarize")

        try:
            response = await self._client.post(
                "/v1/transcribe",
                files={"audio": ("recording", audio, mime_type)},
                data={"language": language_hint if language_hint in ("ar", "en") else "ar"},
            )
        except httpx.HTTPError as exc:
            raise STTError(f"stt service unreachable: {exc}") from exc

        if response.status_code == 413:
            raise STTError("the recording is too long or too large")
        if response.status_code == 422:
            raise STTError("the recording could not be read")
        if response.status_code != 200:
            raise STTError(f"stt service answered {response.status_code}")

        body = response.json()
        return Transcript(text=body["text"], language=body["language"])

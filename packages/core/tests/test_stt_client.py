import httpx
import pytest

from nafas_core.exceptions.providers import STTError
from nafas_core.interfaces.stt.http import HttpSTT


def client_with(handler) -> HttpSTT:
    return HttpSTT("http://stt", client=httpx.AsyncClient(base_url="http://stt", transport=httpx.MockTransport(handler)))


async def test_the_recording_is_sent_as_a_file_with_the_language():
    seen = {}

    def handler(request):
        seen["body"] = request.read()
        return httpx.Response(200, json={"text": "عايز أحجز", "language": "ar", "seconds": 2.1})

    transcript = await client_with(handler).transcribe(b"OGGDATA", "audio/webm", language_hint="ar")

    assert transcript.text == "عايز أحجز"
    assert b"OGGDATA" in seen["body"] and b'name="language"' in seen["body"]


@pytest.mark.parametrize(("status", "message"), [(413, "too long"), (422, "could not be read"), (503, "503")])
async def test_refusals_become_stt_errors(status, message):
    with pytest.raises(STTError, match=message):
        await client_with(lambda r: httpx.Response(status)).transcribe(b"x", "audio/webm")


async def test_voice_notes_are_not_diarized():
    with pytest.raises(STTError, match="diarize"):
        await client_with(lambda r: httpx.Response(200)).transcribe(b"x", "audio/webm", diarize=True)

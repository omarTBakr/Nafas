"""The doctor assistant's internal API: one chat turn, streamed back as server-sent events."""

import uuid
from collections.abc import AsyncIterator

import httpx

from nafas_core.clients.base import PASSED_THROUGH, UpstreamRefusal
from nafas_core.config import get_setting
from nafas_core.exceptions.providers import ProviderError
from nafas_core.internal_api import internal_headers


class DoctorAssistantClient:
    def __init__(self, client: httpx.AsyncClient | None = None):
        # no read timeout: a streamed answer takes as long as it takes, between tool calls
        self._client = client or httpx.AsyncClient(
            base_url=get_setting().doctor_assistant_url, timeout=httpx.Timeout(10.0, read=None)
        )

    async def open_chat(self, doctor_id: uuid.UUID, body: dict) -> AsyncIterator[bytes]:
        """
        Starts the turn and returns its stream. A refusal (not under care, a bad
        request) raises before any byte is streamed, so the caller can answer it.
        """
        request = self._client.build_request(
            "POST", f"/internal/v1/doctors/{doctor_id}/chat", json=body, headers=internal_headers()
        )
        try:
            response = await self._client.send(request, stream=True)
        except httpx.HTTPError as exc:
            raise ProviderError(f"doctor assistant unreachable: {exc}") from exc
        if response.status_code in PASSED_THROUGH:
            body_bytes = await response.aread()
            await response.aclose()
            raise UpstreamRefusal(response.status_code, httpx.Response(200, content=body_bytes).json())
        if response.status_code != 200:
            await response.aclose()
            raise ProviderError(f"doctor assistant answered {response.status_code}")

        async def chunks() -> AsyncIterator[bytes]:
            try:
                async for chunk in response.aiter_raw():
                    yield chunk
            finally:
                await response.aclose()

        return chunks()


_assistant: DoctorAssistantClient | None = None


def get_doctor_assistant() -> DoctorAssistantClient:
    global _assistant
    if _assistant is None:
        _assistant = DoctorAssistantClient()
    return _assistant


def set_doctor_assistant(client: DoctorAssistantClient | None) -> None:
    global _assistant
    _assistant = client

from typing import Any

import httpx

from nafas_core.exceptions.base import NafasError
from nafas_core.exceptions.providers import ProviderError
from nafas_core.internal_api import internal_headers

# refusals a service gives for the caller's request, which the web app should
# see as they are (with the reason in the body): not found, conflict, invalid
PASSED_THROUGH = (404, 409, 422)


class UpstreamRefusal(NafasError):
    """A service refused the request for a reason the user can act on; relayed as is."""

    def __init__(self, status_code: int, body: Any):
        self.status_code = status_code
        self.body = body
        super().__init__(f"{status_code}: {body}")


class InternalClient:
    """Calls one service's internal API with the internal token."""

    service = "service"

    def __init__(self, client: httpx.AsyncClient):
        self._client = client

    async def request(self, method: str, path: str, expected: tuple[int, ...] = (200, 201, 204), **kwargs) -> httpx.Response:
        try:
            response = await self._client.request(method, path, headers=internal_headers(), **kwargs)
        except httpx.HTTPError as exc:
            raise ProviderError(f"{self.service} unreachable: {exc}") from exc

        if response.status_code in expected:
            return response
        if response.status_code == 403:
            # our INTERNAL_API_TOKEN is missing or differs from the service's: configuration, not the user
            raise ProviderError(f"{self.service} refused the internal token")
        if response.status_code in PASSED_THROUGH:
            raise UpstreamRefusal(response.status_code, response.json())

        raise ProviderError(f"{self.service} answered {response.status_code} on {path}")

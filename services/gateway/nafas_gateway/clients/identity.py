import uuid
from dataclasses import dataclass

import httpx

from nafas_core.config import get_setting
from nafas_core.enums.identity import UserRole
from nafas_core.exceptions.providers import ProviderError
from nafas_core.internal_api import internal_headers


@dataclass
class Account:
    user_id: uuid.UUID
    email: str
    role: UserRole
    doctor_id: uuid.UUID | None


def _account(body: dict) -> Account:
    return Account(
        user_id=uuid.UUID(body["user_id"]),
        email=body["email"],
        role=UserRole(body["role"]),
        doctor_id=uuid.UUID(body["doctor_id"]) if body["doctor_id"] else None,
    )


class IdentityClient:
    """The identity service's internal API. None means "no such account", never an error."""

    def __init__(self, client: httpx.AsyncClient | None = None):
        self._client = client or httpx.AsyncClient(base_url=get_setting().identity_url, timeout=5.0)

    async def verify(self, email: str, password: str) -> Account | None:
        response = await self._call("POST", "/internal/v1/auth/verify", json={"email": email, "password": password})
        return None if response.status_code == 401 else _account(response.json())

    async def get_user(self, user_id: uuid.UUID) -> Account | None:
        response = await self._call("GET", f"/internal/v1/users/{user_id}")
        return None if response.status_code == 404 else _account(response.json())

    async def _call(self, method: str, path: str, **kwargs) -> httpx.Response:
        try:
            response = await self._client.request(method, path, headers=internal_headers(), **kwargs)
        except httpx.HTTPError as exc:
            raise ProviderError(f"identity service unreachable: {exc}") from exc

        if response.status_code == 403:
            # our INTERNAL_API_TOKEN is missing or differs from identity's: configuration, not credentials
            raise ProviderError("identity service refused the internal token")
        if response.status_code not in (200, 401, 404):
            raise ProviderError(f"identity service answered {response.status_code} on {path}")

        return response


_identity: IdentityClient | None = None


def get_identity() -> IdentityClient:
    global _identity
    if _identity is None:
        _identity = IdentityClient()

    return _identity


def set_identity(client: IdentityClient | None) -> None:
    """Replaces the process-wide client; tests pass one over a mock transport, and None to reset."""
    global _identity
    _identity = client

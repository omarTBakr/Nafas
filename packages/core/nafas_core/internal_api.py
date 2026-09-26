"""What every service's internal HTTP API shares: the service-to-service check.

Internal APIs are reached only by other services, never by browsers or
patients. The network keeps them private; this token is the second lock, so
a request that slips through the network still needs the shared secret.
"""

import hmac

from fastapi import Header, HTTPException

from nafas_core.config import get_setting

INTERNAL_TOKEN_HEADER = "X-Internal-Token"


async def require_internal_token(x_internal_token: str | None = Header(default=None)) -> None:
    """
    A FastAPI dependency: 403 unless the header matches INTERNAL_API_TOKEN, which must be set.

    403, not 401: internal APIs use 401 for the caller's *users* (bad
    credentials), and a caller must be able to tell that apart from being
    misconfigured itself.
    """
    expected = get_setting().internal_api_token.get_secret_value()

    # an unset token refuses everything rather than accepting everything
    if not expected or not x_internal_token or not hmac.compare_digest(x_internal_token, expected):
        raise HTTPException(status_code=403, detail="internal token missing or wrong")


def internal_headers() -> dict[str, str]:
    """Headers for calling another service's internal API."""
    return {INTERNAL_TOKEN_HEADER: get_setting().internal_api_token.get_secret_value()}

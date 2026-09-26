"""Entrypoint: `uv run python -m nafas_gateway.main`."""

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from nafas_core.clients.base import UpstreamRefusal
from nafas_core.config import get_setting
from nafas_core.exceptions.config import ConfigurationError
from nafas_core.exceptions.providers import ProviderError
from nafas_core.logger import get_logger, setup_logging
from nafas_core.tracing import configure_tracing
from nafas_gateway.errors import Refusal
from nafas_gateway.routes import auth, booking, chat, consents, directory, doctor, notifications, profile, records
from nafas_gateway.sessions import signing_secret

logger = get_logger(__name__)

app = FastAPI(title="Nafas gateway", description="HTTP edge for the Nafas doctor dashboard")

# Each router's routes declare the session they need (current_patient,
# current_doctor, current_account) because the web app mixes public routes
# (sign-up, the doctor directory) with role-bound ones.
app.include_router(auth.router)
app.include_router(directory.router)
app.include_router(booking.router)
app.include_router(doctor.router)
app.include_router(profile.router)
app.include_router(chat.router)
app.include_router(notifications.router)
app.include_router(consents.router)
app.include_router(records.router)


@app.exception_handler(UpstreamRefusal)
async def upstream_refusal(request: Request, exc: UpstreamRefusal) -> JSONResponse:
    """A service refused for a reason the user can act on (taken, not found, invalid): pass it on as is."""
    # a doctor reaching for a patient not under their care is forbidden, whatever code the service used
    forbidden = isinstance(exc.body, dict) and exc.body.get("reason") == "not_under_care"
    return JSONResponse(status_code=403 if forbidden else exc.status_code, content=exc.body)


@app.exception_handler(Refusal)
async def refusal(request: Request, exc: Refusal) -> JSONResponse:
    headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after else None
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail, "reason": exc.reason}, headers=headers)


@app.exception_handler(ProviderError)
async def provider_unavailable(request: Request, exc: ProviderError) -> JSONResponse:
    """A service behind the gateway failed: say so plainly, keep the detail in the log."""
    logger.error("upstream failure on %s: %s", request.url.path, exc)
    return JSONResponse(status_code=503, content={"detail": "a service is unavailable; try again shortly"})


@app.exception_handler(ConfigurationError)
async def misconfigured(request: Request, exc: ConfigurationError) -> JSONResponse:
    logger.error("configuration error on %s: %s", request.url.path, exc)
    return JSONResponse(status_code=500, content={"detail": "the service is misconfigured"})


@app.get("/health")
async def health() -> dict:
    """Open on purpose: a monitor should not need a secret to see we are alive."""
    return {"status": "ok"}


def main() -> None:
    setup_logging()
    configure_tracing()
    # no sessions without a signing secret: refuse to start rather than fail every login
    signing_secret()
    settings = get_setting()
    # the client's address from X-Forwarded-For, trusted only from the web proxy: rate limits key on it
    uvicorn.run(
        app,
        host=settings.api_host,
        port=settings.api_port,
        proxy_headers=True,
        forwarded_allow_ips=settings.forwarded_allow_ips,
    )


if __name__ == "__main__":
    main()

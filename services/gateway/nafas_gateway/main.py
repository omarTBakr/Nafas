"""Entrypoint: `uv run python -m nafas_gateway.main`."""

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from nafas_core.config import get_setting
from nafas_core.exceptions.config import ConfigurationError
from nafas_core.exceptions.providers import ProviderError
from nafas_core.logger import get_logger, setup_logging
from nafas_core.tracing import configure_tracing
from nafas_gateway.routes import auth
from nafas_gateway.sessions import signing_secret

logger = get_logger(__name__)

app = FastAPI(title="Nafas gateway", description="HTTP edge for the Nafas doctor dashboard")

# routers are included here; anything that must apply to all of them — the
# session dependency, say — is attached at inclusion rather than on each
# endpoint. auth carries its own: login must be reachable logged out.
app.include_router(auth.router)


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
    uvicorn.run(app, host=settings.api_host, port=settings.api_port)


if __name__ == "__main__":
    main()

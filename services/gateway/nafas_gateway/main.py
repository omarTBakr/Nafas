"""Entrypoint: `uv run python -m nafas_gateway.main`."""

import uvicorn
from fastapi import FastAPI

from nafas_core.config import get_setting
from nafas_core.logger import setup_logging
from nafas_core.tracing import configure_tracing

app = FastAPI(title="Nafas gateway", description="HTTP edge for the Nafas doctor dashboard")

# routers are included here; anything that must apply to all of them — an auth
# dependency, say — is attached at inclusion rather than on each endpoint
# app.include_router(thing_router)


@app.get("/health")
async def health() -> dict:
    """Open on purpose: a monitor should not need a secret to see we are alive."""
    return {"status": "ok"}


def main() -> None:
    setup_logging()
    configure_tracing()
    settings = get_setting()
    uvicorn.run(app, host=settings.api_host, port=settings.api_port)


if __name__ == "__main__":
    main()

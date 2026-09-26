"""Entrypoint: `uv run python -m nafas_identity.main`."""

import uvicorn

from nafas_core.startup import start_service
from nafas_identity.api import app

PORT = 8010


def main() -> None:
    start_service("identity")
    uvicorn.run(app, host="0.0.0.0", port=PORT)


if __name__ == "__main__":
    main()

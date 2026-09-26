"""Entrypoint: `uv run python -m nafas_doctor_assistant.main`."""

import uvicorn

from nafas_core.logger import setup_logging
from nafas_core.tracing import configure_tracing
from nafas_doctor_assistant.api import app

PORT = 8020


def main() -> None:
    setup_logging()
    configure_tracing()
    uvicorn.run(app, host="0.0.0.0", port=PORT)


if __name__ == "__main__":
    main()

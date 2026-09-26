"""Entrypoint: `uv run python -m nafas_doctor_assistant.main`."""

import uvicorn

from nafas_core.startup import start_service
from nafas_doctor_assistant.api import app

PORT = 8020


def main() -> None:
    start_service("doctor-assistant")
    uvicorn.run(app, host="0.0.0.0", port=PORT)


if __name__ == "__main__":
    main()

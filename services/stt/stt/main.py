"""Entrypoint: `python -m stt.main`. Loads the model once, then serves."""

import logging

import uvicorn

from stt.app import create_app
from stt.config import Settings
from stt.transcriber import WhisperTranscriber


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-8s %(name)s: %(message)s")
    settings = Settings()

    transcriber = WhisperTranscriber(settings)
    logging.getLogger("stt").info("serving %s@%s on %s", settings.model_id, settings.model_revision[:12], transcriber.device)

    uvicorn.run(create_app(transcriber, settings), host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()

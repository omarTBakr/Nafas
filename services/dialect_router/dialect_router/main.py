"""Entrypoint: `python -m dialect_router.main`. Loads the model once, then serves."""

import logging

import uvicorn

from dialect_router.app import create_app
from dialect_router.classifier import TransformersClassifier
from dialect_router.config import Settings


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-8s %(name)s: %(message)s")
    settings = Settings()

    classifier = TransformersClassifier(settings)
    logging.getLogger("dialect_router").info(
        "serving %s@%s on %s", settings.model_id, settings.model_revision[:12], classifier.device
    )

    uvicorn.run(create_app(classifier, settings), host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()

"""Entrypoint: `python -m embeddings.main`. Loads the model once, then serves."""

import logging

import uvicorn

from embeddings.app import create_app
from embeddings.config import Settings
from embeddings.encoder import BgeM3Encoder


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-8s %(name)s: %(message)s")
    settings = Settings()
    if not settings.pinned:
        logging.getLogger("embeddings").warning(
            "%s is not pinned to a commit (model_revision=%s)", settings.model_id, settings.model_revision
        )
    encoder = BgeM3Encoder(settings)
    uvicorn.run(create_app(encoder, settings), host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()

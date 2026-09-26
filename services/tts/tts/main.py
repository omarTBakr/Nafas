"""Entrypoint: `python -m tts.main`. Loads the models once, then serves."""

import logging

import uvicorn

from tts.app import create_app
from tts.config import Settings
from tts.synthesizer import OmniVoiceSynthesizer


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-8s %(name)s: %(message)s")
    settings = Settings()

    synthesizer = OmniVoiceSynthesizer(settings)
    unsupported = [code for code, ok in synthesizer.supported().items() if not ok]
    if unsupported:
        # served anyway for the dialects that work; these are refused with 422 and listed on /health
        logging.getLogger("tts").warning("the loaded model does not know these dialects: %s", ", ".join(unsupported))
    logging.getLogger("tts").info("serving %s@%s on %s", settings.model_id, settings.model_revision[:12], synthesizer.device)

    uvicorn.run(create_app(synthesizer, settings), host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()

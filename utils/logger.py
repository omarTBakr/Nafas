import logging

from utils.config import get_setting

_configured = False


def setup_logging() -> None:
    """
    Configures root logging once, using LOG_LEVEL from .env.

    Call this from an entrypoint (the API, the worker). Temporal's
    `activity.logger` writes through the standard logging tree, so this is what
    makes activity logs actually show up.
    """
    global _configured
    if _configured:
        return

    level = get_setting().log_level.upper()

    logging.basicConfig(level=level, format="%(asctime)s %(levelname)-8s %(name)s: %(message)s")

    # basicConfig is a no-op when the root logger already has handlers, which is
    # the case under uvicorn and pytest, so set the level explicitly as well.
    logging.getLogger().setLevel(level)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    """A plain module logger, for code that runs outside an activity."""
    return logging.getLogger(name)

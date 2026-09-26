import json
import logging
from datetime import UTC, datetime

from nafas_core import redaction
from nafas_core.config import get_setting

_configured = False


class JsonFormatter(logging.Formatter):
    """One JSON object per line, for a log pipeline; the message is already redacted by the record factory."""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False)


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

    # before anything logs: patient data never reaches a handler
    redaction.install()

    settings = get_setting()
    level = settings.log_level.upper()

    logging.basicConfig(level=level, format="%(asctime)s %(levelname)-8s %(name)s: %(message)s")
    if settings.log_format == "json":
        for handler in logging.getLogger().handlers:
            handler.setFormatter(JsonFormatter())

    # basicConfig is a no-op when the root logger already has handlers, which is
    # the case under uvicorn and pytest, so set the level explicitly as well.
    logging.getLogger().setLevel(level)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    """A plain module logger, for code that runs outside an activity."""
    return logging.getLogger(name)

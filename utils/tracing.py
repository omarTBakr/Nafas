import os

from utils.config import Settings, get_setting
from utils.logger import get_logger

logger = get_logger(__name__)


def configure_tracing(settings: Settings | None = None) -> bool:
    """
    Hands the LANGSMITH_* settings to the langsmith SDK, and says whether tracing is on.

    langsmith reads its configuration from the process environment and caches
    it on first use, while pydantic-settings loads .env without exporting it.
    Without this, a key put in .env would be ignored in silence. Call it from
    an entrypoint before the first model call.

    Tracing is on only when LANGSMITH_TRACING is true *and* a key is present,
    so a half-configured .env cannot fail every model call on an auth error.
    """
    settings = settings or get_setting()
    api_key = settings.langsmith_api_key.get_secret_value()

    if not settings.langsmith_tracing:
        os.environ["LANGSMITH_TRACING"] = "false"
        return False

    if not api_key:
        logger.warning("LANGSMITH_TRACING is on but LANGSMITH_API_KEY is empty; tracing stays off")
        os.environ["LANGSMITH_TRACING"] = "false"
        return False

    os.environ["LANGSMITH_TRACING"] = "true"
    os.environ["LANGSMITH_API_KEY"] = api_key
    os.environ["LANGSMITH_PROJECT"] = settings.langsmith_project
    os.environ["LANGSMITH_ENDPOINT"] = settings.langsmith_endpoint
    # traces carry prompts, and prompts carry PHI
    os.environ["LANGSMITH_HIDE_INPUTS"] = str(settings.langsmith_hide_inputs).lower()
    os.environ["LANGSMITH_HIDE_OUTPUTS"] = str(settings.langsmith_hide_outputs).lower()

    logger.info("LangSmith tracing on, project %r", settings.langsmith_project)

    return True

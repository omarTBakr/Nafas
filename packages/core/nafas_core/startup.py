"""
What every service does first: logging, tracing, and a check that the
settings are fit for the environment. Staging and production refuse to start
on a laptop's defaults, so a missing secret stops a deploy instead of
reaching patients.
"""

from nafas_core.config import Environment, Settings, get_setting
from nafas_core.exceptions.config import ConfigurationError
from nafas_core.logger import get_logger, setup_logging
from nafas_core.tracing import configure_tracing

logger = get_logger(__name__)

# the values docker-compose.yml and the Settings defaults ship with
LAPTOP_SECRETS = {"", "dev-internal-token", "dev-jwt-secret-change-me-in-any-real-deployment", "nafas", "nafas-secret"}


def problems(settings: Settings) -> list[str]:
    """Why these settings must not run outside dev; empty when they may."""
    if settings.environment is Environment.DEV:
        return []
    found = []
    if settings.internal_api_token.get_secret_value() in LAPTOP_SECRETS:
        found.append("INTERNAL_API_TOKEN is unset or a laptop default")
    if settings.jwt_secret.get_secret_value() in LAPTOP_SECRETS or len(settings.jwt_secret.get_secret_value()) < 32:
        found.append("JWT_SECRET is unset, a laptop default, or shorter than 32 characters")
    if settings.s3_secret_key.get_secret_value() in LAPTOP_SECRETS:
        found.append("S3_SECRET_KEY is a laptop default")
    if ":nafas@" in settings.database_url:
        found.append("DATABASE_URL uses the laptop password")
    if not settings.session_cookie_secure:
        found.append("SESSION_COOKIE_SECURE is off")
    if settings.forwarded_allow_ips.strip() == "*":
        found.append("FORWARDED_ALLOW_IPS trusts every sender; name the web proxy")
    if not settings.git_sha:
        found.append("GIT_SHA is unset: /health could not say which build is answering")
    # traces carry prompts, and prompts carry PHI (PLAN.md §2, tracing)
    cloud = "smith.langchain.com" in settings.langsmith_endpoint
    hidden = settings.langsmith_hide_inputs and settings.langsmith_hide_outputs
    if settings.langsmith_tracing and cloud and not hidden:
        found.append("LangSmith tracing to the cloud with prompts visible; self-host it or hide inputs and outputs")
    return found


def start_service(service: str) -> None:
    setup_logging()
    configure_tracing()
    settings = get_setting()
    found = problems(settings)
    if found:
        raise ConfigurationError(f"{service} will not start in {settings.environment.value}: " + "; ".join(found))
    logger.info("%s starting in %s at %s", service, settings.environment.value, settings.git_sha or "an unversioned build")

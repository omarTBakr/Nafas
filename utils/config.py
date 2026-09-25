from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Every setting the project reads, in one place, loaded from .env.

    Everything has a default, so the suite and a fresh checkout run with no
    .env at all. Make a setting required (`Field(...)`) only once the project
    genuinely cannot start without it — a missing value then fails at startup
    rather than at the first request that needed it.
    """

    api_host: str = Field("0.0.0.0", description="Host the FastAPI server binds to")
    api_port: int = Field(8000, description="Port the FastAPI server listens on")

    temporal_host: str = Field("localhost:7234", description="host:port of the Temporal frontend service")
    temporal_namespace: str = Field("default", description="Temporal namespace the worker and client use")
    temporal_task_queue: str = Field("nafas_queue", description="Task queue the workflow and activities are polled from")

    database_url: str = Field(
        "postgresql+asyncpg://nafas:nafas@localhost:5433/nafas",
        description="SQLAlchemy async URL of the Postgres database",
    )

    s3_endpoint_url: str = Field("http://localhost:8333", description="S3 endpoint; empty for AWS itself")
    s3_region: str = Field("us-east-1", description="S3 region")
    s3_access_key: SecretStr = Field(SecretStr("nafas"), description="S3 access key")
    s3_secret_key: SecretStr = Field(SecretStr("nafas-secret"), description="S3 secret key")
    s3_bucket: str = Field("nafas", description="Bucket holding recordings, voice notes and documents")

    anthropic_api_key: SecretStr = Field(SecretStr(""), description="Claude API key")
    llm_chat_model: str = Field("claude-sonnet-5", description="Model for patient and doctor chat")
    llm_classifier_model: str = Field("claude-haiku-4-5-20251001", description="Model for intent and safety classifiers")
    llm_summary_model: str = Field("claude-opus-5-5", description="Model for consultation summaries")

    # LangSmith reads these from the process environment, not from this object;
    # utils.tracing.configure_tracing copies them there at startup
    langsmith_tracing: bool = Field(False, description="Send traces of every model call to LangSmith")
    langsmith_api_key: SecretStr = Field(SecretStr(""), description="LangSmith API key")
    langsmith_project: str = Field("nafas-dev", description="LangSmith project traces are filed under")
    langsmith_endpoint: str = Field("https://api.smith.langchain.com", description="LangSmith API endpoint")
    langsmith_hide_inputs: bool = Field(False, description="Keep prompts (which carry PHI) out of traces")
    langsmith_hide_outputs: bool = Field(False, description="Keep model outputs out of traces")

    telegram_bot_token: SecretStr = Field(SecretStr(""), description="Token of the patient-facing Telegram bot")
    telegram_webhook_secret: SecretStr = Field(SecretStr(""), description="Secret Telegram echoes on every webhook call")

    smtp_host: str = Field("", description="SMTP server for outbound email")
    smtp_port: int = Field(587, description="SMTP port (STARTTLS)")
    smtp_username: str = Field("", description="SMTP username")
    smtp_password: SecretStr = Field(SecretStr(""), description="SMTP password")
    email_from: str = Field("", description="From address on outbound email")

    jwt_secret: SecretStr = Field(SecretStr(""), description="Signs doctor dashboard sessions; required before auth runs")
    jwt_ttl_minutes: int = Field(720, description="Lifetime of a dashboard session")

    log_level: str = Field("INFO", description="Root log level: DEBUG, INFO, WARNING, ERROR")
    run_worker_in_api: bool = Field(False, description="Run the Temporal worker inside the API process")

    # local scratch space; anything written here is disposable
    temp_dir: str = Field("assets", description="Local root directory for scratch files")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def temp_root(self) -> Path:
        """The scratch directory, created on first use."""
        path = Path(self.temp_dir)
        path.mkdir(parents=True, exist_ok=True)

        return path


_settings_instance = None


def get_setting() -> Settings:
    """
    Returns a singleton Settings, loaded from the .env file by pydantic.

    A singleton because reading the environment on every call is wasted work,
    and because a setting that changed underneath a running process would be a
    confusing source of inconsistency.
    """
    global _settings_instance
    if _settings_instance is None:
        _settings_instance = Settings()

    return _settings_instance

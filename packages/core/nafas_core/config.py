from enum import StrEnum
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from nafas_core.enums.providers import EmbeddingsProvider, LLMProvider, StorageProvider, STTProvider


class Environment(StrEnum):
    DEV = "dev"
    STAGING = "staging"
    PROD = "prod"


class Settings(BaseSettings):
    """
    Every setting the project reads, in one place, loaded from .env.

    Everything has a default, so the suite and a fresh checkout run with no
    .env at all. Make a setting required (`Field(...)`) only once the project
    genuinely cannot start without it — a missing value then fails at startup
    rather than at the first request that needed it.
    """

    environment: Environment = Field(
        Environment.DEV, description="dev, staging or prod; staging and prod refuse laptop defaults at startup"
    )
    git_sha: str = Field("", description="The commit this build is from, reported on /health; set by the image build")
    api_host: str = Field("0.0.0.0", description="Host the FastAPI server binds to")
    forwarded_allow_ips: str = Field(
        "127.0.0.1", description="Proxies whose X-Forwarded-For the gateway trusts for the client's address"
    )
    api_port: int = Field(8000, description="Port the FastAPI server listens on")

    temporal_host: str = Field("localhost:7234", description="host:port of the Temporal frontend service")
    temporal_namespace: str = Field("default", description="Temporal namespace the worker and client use")

    database_url: str = Field(
        "postgresql+asyncpg://nafas_service:nafas@localhost:5433/nafas",
        description="What services connect as: a role row-level security applies to",
    )
    db_pool_size: int = Field(20, description="Database connections each process keeps open")
    db_max_overflow: int = Field(10, description="Extra connections a process may open at a peak, closed after use")
    database_owner_url: str = Field(
        "postgresql+asyncpg://nafas:nafas@localhost:5433/nafas",
        description="The schema owner, for migrations only; RLS does not apply to it",
    )

    s3_endpoint_url: str = Field("http://localhost:8333", description="S3 endpoint; empty for AWS itself")
    s3_public_endpoint_url: str = Field(
        "", description="S3 endpoint as browsers reach it, for upload and download links; empty: the same as S3_ENDPOINT_URL"
    )
    s3_region: str = Field("us-east-1", description="S3 region")
    s3_access_key: SecretStr = Field(SecretStr("nafas"), description="S3 access key")
    s3_secret_key: SecretStr = Field(SecretStr("nafas-secret"), description="S3 secret key")
    s3_bucket: str = Field("nafas", description="Bucket holding recordings, voice notes and documents")

    llm_provider: LLMProvider = Field(LLMProvider.ANTHROPIC, description="Which language model backend to use")
    llm_base_url: str = Field("http://localhost:11434/v1", description="OpenAI-compatible local LLM endpoint")
    llm_api_key: SecretStr = Field(SecretStr("ollama"), description="API key for an OpenAI-compatible local LLM")
    stt_provider: STTProvider = Field(STTProvider.SELF_HOSTED, description="Speech-to-text backend")
    stt_url: str = Field("http://localhost:8420", description="Base URL of the stt service")
    embeddings_provider: EmbeddingsProvider = Field(EmbeddingsProvider.NONE, description="Embeddings backend")
    storage_provider: StorageProvider = Field(StorageProvider.S3, description="Object storage backend")

    anthropic_api_key: SecretStr = Field(SecretStr(""), description="Claude API key")
    anthropic_workspace_id: str = Field(
        "", description="Workspace to bill; required when the API key is not scoped to one workspace"
    )
    llm_chat_model: str = Field("gemma4:e4b", description="Model for patient and doctor chat")
    llm_classifier_model: str = Field("gemma4:e4b", description="Model for intent and safety classifiers")
    llm_summary_model: str = Field("gemma4:e4b", description="Model for consultation summaries")

    tavily_api_key: SecretStr = Field(SecretStr(""), description="Tavily web search; empty turns web grounding off")
    web_search_doctor: bool = Field(True, description="The doctor assistant may search the web (with a Tavily key)")
    web_search_patient: bool = Field(
        False, description="Patients' general medical answers may draw on trusted medical sites (with a Tavily key)"
    )
    web_search_domains: list[str] = Field(
        default_factory=lambda: [
            "who.int",
            "cdc.gov",
            "nhs.uk",
            "medlineplus.gov",
            "mayoclinic.org",
            "nih.gov",
            "clevelandclinic.org",
        ],
        description="The only sites patients' answers are grounded in",
    )

    # LangSmith reads these from the process environment, not from this object;
    # utils.tracing.configure_tracing copies them there at startup
    langsmith_tracing: bool = Field(False, description="Send traces of every model call to LangSmith")
    langsmith_api_key: SecretStr = Field(SecretStr(""), description="LangSmith API key")
    langsmith_project: str = Field("nafas-dev", description="LangSmith project traces are filed under")
    langsmith_endpoint: str = Field("https://api.smith.langchain.com", description="LangSmith API endpoint")
    langsmith_hide_inputs: bool = Field(False, description="Keep prompts (which carry PHI) out of traces")
    langsmith_hide_outputs: bool = Field(False, description="Keep model outputs out of traces")

    dialect_router_url: str = Field("http://localhost:8410", description="Base URL of the dialect-router service")
    tts_url: str = Field("http://localhost:8440", description="Base URL of the tts service")
    embeddings_url: str = Field("http://localhost:8430", description="Base URL of the embeddings service")
    doctor_assistant_url: str = Field("http://localhost:8020", description="Base URL of the doctor assistant's internal API")
    clinical_url: str = Field("http://localhost:8050", description="Base URL of the clinical-records service's internal API")
    consultation_url: str = Field("http://localhost:8060", description="Base URL of the consultation service's internal API")

    livekit_url: str = Field("", description="The LiveKit address browsers connect to (wss://...); empty turns online visits off")
    livekit_api_url: str = Field("", description="The LiveKit address services call; defaults to livekit_url")
    livekit_api_key: str = Field("", description="LiveKit API key")
    livekit_api_secret: SecretStr = Field(SecretStr(""), description="LiveKit API secret: signs join tokens, verifies webhooks")
    egress_s3_endpoint: str = Field(
        "", description="The S3 endpoint as the LiveKit egress container reaches it; defaults to S3_ENDPOINT_URL"
    )
    internal_api_token: SecretStr = Field(
        SecretStr(""), description="Shared secret on service-to-service calls; empty refuses them all"
    )
    identity_url: str = Field("http://localhost:8010", description="Base URL of the identity service's internal API")
    scheduling_url: str = Field("http://localhost:8030", description="Base URL of the scheduling service's internal API")
    conversation_url: str = Field("http://localhost:8040", description="Base URL of the conversation service's internal API")

    smtp_host: str = Field("", description="Mail server for appointment emails; empty sends none")
    smtp_port: int = Field(587, description="Mail server port")
    smtp_username: str = Field("", description="Mail server login; empty for none")
    smtp_password: SecretStr = Field(SecretStr(""), description="Mail server password")
    smtp_starttls: bool = Field(True, description="Upgrade the connection with STARTTLS")
    smtp_from: str = Field("Nafas <no-reply@nafas.local>", description="The From address of appointment emails")
    web_url: str = Field("http://localhost:8088", description="The web app's address, for links in emails")

    jwt_secret: SecretStr = Field(SecretStr(""), description="Signs doctor dashboard sessions; required before auth runs")
    session_check_seconds: int = Field(
        30, description="How long the gateway trusts an account it confirmed with identity; 0 asks every time"
    )
    jwt_ttl_minutes: int = Field(720, description="Lifetime of a dashboard session")
    session_cookie_secure: bool = Field(True, description="Send the session cookie over HTTPS only (browsers exempt localhost)")

    rate_limits_shared: bool = Field(
        False, description="Count the gateway's rate limits in Postgres, shared by every replica, not in one process's memory"
    )
    log_level: str = Field("INFO", description="Root log level: DEBUG, INFO, WARNING, ERROR")
    log_format: str = Field("text", description="text for a terminal, json for a log pipeline (one object per line)")
    metrics_token: SecretStr = Field(
        SecretStr(""), description="When set, /metrics asks for it as a bearer token; the gateway is public, so set it there"
    )

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

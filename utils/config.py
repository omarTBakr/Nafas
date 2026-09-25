from pathlib import Path

from pydantic import Field
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

    temporal_host: str = Field("localhost:7233", description="host:port of the Temporal frontend service")
    temporal_namespace: str = Field("default", description="Temporal namespace the worker and client use")
    temporal_task_queue: str = Field("nafas_queue", description="Task queue the workflow and activities are polled from")

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

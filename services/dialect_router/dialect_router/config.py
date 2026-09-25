from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict, TomlConfigSettingsSource

MODEL_CONFIG = Path(__file__).with_name("model.toml")


class Settings(BaseSettings):
    """
    The pinned model config from model.toml, overridable by DIALECT_* variables.

    Environment overrides exist for local experiments; staging and production
    run exactly what model.toml says, and /health reports it.
    """

    model_id: str
    model_revision: str
    model_dir: str
    max_length: int = Field(gt=0, le=512)
    max_batch_size: int = Field(gt=0)
    low_confidence_threshold: float = Field(ge=0, le=1)

    # "auto" picks cuda when a GPU is visible, else cpu
    device: str = "auto"
    host: str = "0.0.0.0"
    port: int = 8410

    model_config = SettingsConfigDict(env_prefix="DIALECT_", toml_file=MODEL_CONFIG, protected_namespaces=())

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # explicit arguments, then the environment, then the pinned file
        return init_settings, env_settings, TomlConfigSettingsSource(settings_cls)

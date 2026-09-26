from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict, TomlConfigSettingsSource

MODEL_CONFIG = Path(__file__).with_name("model.toml")


class Settings(BaseSettings):
    """The pinned model config from model.toml, overridable by TTS_* variables for local experiments."""

    model_id: str
    model_revision: str
    model_dir: str
    egyptian_model_id: str
    egyptian_model_revision: str
    egyptian_model_dir: str
    use_egyptian_model: bool = False
    max_chars: int = Field(gt=0)
    num_step: int = Field(gt=0)

    # "auto" picks cuda when a GPU is visible, else cpu
    device: str = "auto"
    host: str = "0.0.0.0"
    port: int = 8440

    model_config = SettingsConfigDict(env_prefix="TTS_", toml_file=MODEL_CONFIG, protected_namespaces=())

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return init_settings, env_settings, TomlConfigSettingsSource(settings_cls)

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict, TomlConfigSettingsSource

MODEL_CONFIG = Path(__file__).with_name("model.toml")


class Settings(BaseSettings):
    """The model config from model.toml, overridable by EMBEDDINGS_* variables for local experiments."""

    model_id: str
    model_revision: str
    model_dir: str
    dimensions: int = Field(gt=0)
    max_texts: int = Field(gt=0)
    max_chars: int = Field(gt=0)

    # cpu by default: the GPU is spent on stt, the dialect-router and tts
    device: str = "cpu"
    host: str = "0.0.0.0"
    port: int = 8430

    model_config = SettingsConfigDict(env_prefix="EMBEDDINGS_", toml_file=MODEL_CONFIG, protected_namespaces=())

    @property
    def pinned(self) -> bool:
        return len(self.model_revision) == 40

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

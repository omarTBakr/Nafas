from enum import StrEnum


class LLMProvider(StrEnum):
    ANTHROPIC = "anthropic"


class STTProvider(StrEnum):
    # the stt GPU service (services/stt): the Arabic-dialect Whisper, decided 2026-09-26
    SELF_HOSTED = "self_hosted"
    NONE = ""


class EmbeddingsProvider(StrEnum):
    NONE = ""


class StorageProvider(StrEnum):
    S3 = "s3"

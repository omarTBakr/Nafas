from enum import StrEnum


class LLMProvider(StrEnum):
    ANTHROPIC = "anthropic"


class STTProvider(StrEnum):
    # the hosted vendors join after the Arabic dialect spike (docs/CHECKLIST.md, phase 0)
    NONE = ""


class EmbeddingsProvider(StrEnum):
    NONE = ""


class StorageProvider(StrEnum):
    S3 = "s3"

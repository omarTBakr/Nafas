"""Exception hierarchy for the project.

    NafasError
    |
    +-- ConfigurationError
    |     +-- MissingSettingError
    |     +-- InvalidSettingError
    |
    +-- WorkflowError
    |     +-- ActivityFailedError
    |     +-- TemporalConnectionError
    |     +-- WorkflowExecutionError
    |
    +-- ProviderError
          +-- LLMError
          |     +-- LLMRefusalError
          +-- STTError
          +-- StorageError
          +-- ChannelError

Catch `NafasError` for anything the project raised on purpose; catch a subtree
(`WorkflowError`) when the handling is the same across a domain.

Add a domain by adding a module beside these — one file per subtree, each
importing `NafasError` from `exceptions.base` — and re-exporting it here.
"""

from nafas_core.exceptions.base import NafasError
from nafas_core.exceptions.config import ConfigurationError, InvalidSettingError, MissingSettingError
from nafas_core.exceptions.providers import ChannelError, LLMError, LLMRefusalError, ProviderError, StorageError, STTError
from nafas_core.exceptions.workflow import ActivityFailedError, TemporalConnectionError, WorkflowError, WorkflowExecutionError

__all__ = [
    "ActivityFailedError",
    "ChannelError",
    "ConfigurationError",
    "InvalidSettingError",
    "LLMError",
    "LLMRefusalError",
    "MissingSettingError",
    "NafasError",
    "ProviderError",
    "STTError",
    "StorageError",
    "TemporalConnectionError",
    "WorkflowError",
    "WorkflowExecutionError",
]

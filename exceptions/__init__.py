"""Exception hierarchy for the project.

    NafasError
    |
    +-- ConfigurationError
    |     +-- MissingSettingError
    |     +-- InvalidSettingError
    |
    +-- WorkflowError
          +-- ActivityFailedError
          +-- TemporalConnectionError
          +-- WorkflowExecutionError

Catch `NafasError` for anything the project raised on purpose; catch a subtree
(`WorkflowError`) when the handling is the same across a domain.

Add a domain by adding a module beside these — one file per subtree, each
importing `NafasError` from `exceptions.base` — and re-exporting it here.
"""

from exceptions.base import NafasError
from exceptions.config import ConfigurationError, InvalidSettingError, MissingSettingError
from exceptions.workflow import ActivityFailedError, TemporalConnectionError, WorkflowError, WorkflowExecutionError

__all__ = [
    "ActivityFailedError",
    "ConfigurationError",
    "InvalidSettingError",
    "MissingSettingError",
    "NafasError",
    "TemporalConnectionError",
    "WorkflowError",
    "WorkflowExecutionError",
]

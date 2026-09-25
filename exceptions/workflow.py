from exceptions.base import NafasError


class WorkflowError(NafasError):
    """A step of the pipeline failed for a reason not covered above."""


class ActivityFailedError(WorkflowError):
    """A single activity failed and the pipeline cannot continue."""


class TemporalConnectionError(WorkflowError):
    """The Temporal frontend could not be reached."""


class WorkflowExecutionError(WorkflowError):
    """The workflow ran but failed."""

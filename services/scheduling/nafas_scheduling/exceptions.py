from nafas_core.exceptions.base import NafasError
from nafas_scheduling.enums import Unavailable


class SchedulingError(NafasError):
    """A scheduling request that cannot be carried out as asked."""


class SlotUnavailableError(SchedulingError):
    """The requested time cannot be booked; `reason` says why."""

    def __init__(self, reason: Unavailable, message: str | None = None):
        self.reason = reason
        super().__init__(message or reason.value)


class HoldExpiredError(SchedulingError):
    """The hold lapsed before it was confirmed; the slot may have gone to someone else."""


class AppointmentNotFoundError(SchedulingError):
    """No appointment with this id is visible to the current doctor."""


class InvalidTransitionError(SchedulingError):
    """The appointment is not in a status that allows this change."""

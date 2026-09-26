from enum import StrEnum


class AppointmentMode(StrEnum):
    IN_PERSON = "in_person"
    ONLINE = "online"


class AvailabilityMode(StrEnum):
    """Which kind of appointment a block of hours accepts."""

    IN_PERSON = "in_person"
    ONLINE = "online"
    BOTH = "both"

    def accepts(self, mode: AppointmentMode) -> bool:
        return self is AvailabilityMode.BOTH or self.value == mode.value


class AppointmentStatus(StrEnum):
    # a slot reserved while the patient confirms; it expires on its own
    HELD = "held"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    NO_SHOW = "no_show"


# the statuses that occupy a slot; the database's exclusion constraint uses the same set
BLOCKING_STATUSES = (AppointmentStatus.HELD, AppointmentStatus.CONFIRMED)


class Unavailable(StrEnum):
    """Why a requested start time cannot be booked, precise enough to explain to the patient."""

    NOT_WHOLE_MINUTE = "not_whole_minute"
    TOO_SOON = "too_soon"
    BEYOND_HORIZON = "beyond_horizon"
    OUTSIDE_HOURS = "outside_hours"
    WRONG_MODE = "wrong_mode"
    TIME_OFF = "time_off"
    TAKEN = "taken"
    NOT_BOOKABLE = "not_bookable"

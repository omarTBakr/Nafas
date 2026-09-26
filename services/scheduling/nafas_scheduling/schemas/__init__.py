"""
Dataclasses crossing a Temporal boundary. Times travel as ISO 8601 strings,
ids as strings; a new field needs a default, or a run in flight cannot decode
its own history.
"""

from dataclasses import dataclass, field

BOOKING_WORKFLOW = "BookingWorkflow"
CONFIRMED_SIGNAL = "confirmed"
CANCELLED_SIGNAL = "cancelled"
NO_SHOW_SIGNAL = "no_show"


def booking_workflow_id(appointment_id: str) -> str:
    return f"booking-{appointment_id}"


@dataclass
class BookingStart:
    appointment_id: str
    doctor_id: str
    start: str
    end: str
    hold_expires_at: str
    # reminders, in seconds before the start (T-24h, T-1h)
    reminders: list[int] = field(default_factory=lambda: [24 * 3600, 3600])
    # how long after the end a visit nobody marked becomes completed
    complete_after_seconds: int = 3600


@dataclass
class Cancellation:
    by: str = "patient"


@dataclass
class NotificationRequest:
    notification_id: str
    appointment_id: str
    doctor_id: str
    kind: str
    minutes_before: int | None = None


@dataclass
class AppointmentRef:
    appointment_id: str
    doctor_id: str

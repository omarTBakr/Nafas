"""
What the API tells BookingWorkflow, after the database has changed.

Best effort by design: the database is the authority, so a Temporal that is
down costs the reminders of that one booking, never the booking itself (and
lapsed holds are also released on the next hold, see booking.hold). Tests
replace the process-wide sender with a recorder.
"""

from typing import Protocol

from temporalio.client import Client
from temporalio.common import WorkflowIDReusePolicy

from nafas_core.logger import get_logger
from nafas_core.temporal import TaskQueue, get_temporal_client
from nafas_scheduling.models import Appointment
from nafas_scheduling.schemas import (
    BOOKING_WORKFLOW,
    CANCELLED_SIGNAL,
    CONFIRMED_SIGNAL,
    NO_SHOW_SIGNAL,
    BookingStart,
    Cancellation,
    booking_workflow_id,
)

logger = get_logger(__name__)


class BookingEvents(Protocol):
    async def held(self, appointment: Appointment) -> str | None: ...

    async def confirmed(self, appointment: Appointment) -> None: ...

    async def cancelled(self, appointment: Appointment, by: str) -> None: ...

    async def no_show(self, appointment: Appointment) -> None: ...


class TemporalBookingEvents:
    def __init__(self, client: Client | None = None, task_queue: str = TaskQueue.SCHEDULING):
        self._client = client
        self._task_queue = str(task_queue)

    async def _temporal(self) -> Client:
        return self._client or await get_temporal_client()

    async def held(self, appointment: Appointment) -> str | None:
        """Starts the appointment's workflow; its id, or None when Temporal could not be reached."""
        workflow_id = booking_workflow_id(str(appointment.id))
        start = BookingStart(
            appointment_id=str(appointment.id),
            doctor_id=str(appointment.doctor_id),
            start=appointment.starts_at.isoformat(),
            end=appointment.ends_at.isoformat(),
            hold_expires_at=appointment.hold_expires_at.isoformat(),
        )
        try:
            client = await self._temporal()
            await client.start_workflow(
                BOOKING_WORKFLOW,
                start,
                id=workflow_id,
                task_queue=self._task_queue,
                id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
            )
        except Exception:
            logger.exception("could not start %s; the hold stands without reminders", workflow_id)
            return None
        return workflow_id

    async def _signal(self, appointment: Appointment, signal: str, *args) -> None:
        if not appointment.booking_workflow_id:
            return
        try:
            client = await self._temporal()
            await client.get_workflow_handle(appointment.booking_workflow_id).signal(signal, *args)
        except Exception:
            logger.exception("could not signal %s to %s", signal, appointment.booking_workflow_id)

    async def confirmed(self, appointment: Appointment) -> None:
        await self._signal(appointment, CONFIRMED_SIGNAL)

    async def cancelled(self, appointment: Appointment, by: str) -> None:
        await self._signal(appointment, CANCELLED_SIGNAL, Cancellation(by=by))

    async def no_show(self, appointment: Appointment) -> None:
        await self._signal(appointment, NO_SHOW_SIGNAL)


_events: BookingEvents | None = None


def get_events() -> BookingEvents:
    global _events
    if _events is None:
        _events = TemporalBookingEvents()
    return _events


def set_events(events: BookingEvents | None) -> None:
    """Replaces the process-wide sender; tests pass a recorder, and None to reset."""
    global _events
    _events = events

"""
BookingWorkflow: one appointment, from its hold to its end.

Started by the hold, it waits for the patient's confirmation until the hold
expires, then releases the slot if none came. Once confirmed it tells the
patient, reminds them before the visit (T-24h and T-1h), and marks the visit
completed after it ends unless the doctor recorded a no-show. A cancellation,
by either side, ends it at any point.

The database stays the authority: the API changes an appointment first and
signals this second, and every activity re-reads the row before acting, so a
late or missing signal can never undo what the database says.
"""

from datetime import datetime, timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

with workflow.unsafe.imports_passed_through():
    from nafas_scheduling import activities
    from nafas_scheduling.enums import NotificationKind
    from nafas_scheduling.schemas import (
        BOOKING_WORKFLOW,
        CANCELLED_SIGNAL,
        CONFIRMED_SIGNAL,
        NO_SHOW_SIGNAL,
        AppointmentRef,
        BookingStart,
        Cancellation,
        NotificationRequest,
    )

EMAIL = {"start_to_close_timeout": timedelta(seconds=30), "retry_policy": RetryPolicy(maximum_attempts=3)}
ACTIVITY = {"start_to_close_timeout": timedelta(seconds=15), "retry_policy": RetryPolicy(maximum_interval=timedelta(minutes=1))}


@workflow.defn(name=BOOKING_WORKFLOW)
class BookingWorkflow:
    def __init__(self) -> None:
        self._confirmed = False
        self._cancelled: Cancellation | None = None
        self._no_show = False

    @workflow.signal(name=CONFIRMED_SIGNAL)
    def confirmed(self) -> None:
        self._confirmed = True

    @workflow.signal(name=CANCELLED_SIGNAL)
    def cancelled(self, cancellation: Cancellation) -> None:
        self._cancelled = cancellation

    @workflow.signal(name=NO_SHOW_SIGNAL)
    def no_show(self) -> None:
        self._no_show = True

    async def _until(self, at: datetime, also) -> bool:
        """Waits until `at` or until `also()` holds; True if `also()` came first."""
        remaining = (at - workflow.now()).total_seconds()
        if remaining <= 0:
            return also()
        try:
            await workflow.wait_condition(also, timeout=timedelta(seconds=remaining))
            return True
        except TimeoutError:
            return False

    async def _notify(self, start: BookingStart, kind: NotificationKind, minutes_before: int | None = None) -> None:
        request = NotificationRequest(str(workflow.uuid4()), start.appointment_id, start.doctor_id, kind.value, minutes_before)
        await workflow.execute_activity(activities.notify, request, **ACTIVITY)
        # runs in flight when email arrived replay without it
        if workflow.patched("email-notices"):
            try:
                await workflow.execute_activity(activities.email_notice, request, **EMAIL)
            except ActivityError:
                # the in-app notice stands; an email that cannot go is not worth failing the booking
                workflow.logger.warning("an appointment email could not be sent")

    @workflow.run
    async def run(self, start: BookingStart) -> str:
        ref = AppointmentRef(start.appointment_id, start.doctor_id)
        begins, ends = datetime.fromisoformat(start.start), datetime.fromisoformat(start.end)

        # 1. the hold: confirmation, cancellation, or expiry
        decided = await self._until(
            datetime.fromisoformat(start.hold_expires_at), lambda: self._confirmed or self._cancelled is not None
        )
        if not decided:
            if await workflow.execute_activity(activities.expire_hold, ref, **ACTIVITY):
                await self._notify(start, NotificationKind.HOLD_EXPIRED)
                return "expired"
            # confirmed or cancelled in the database without a signal reaching us: trust the database
            self._confirmed = True
        if self._cancelled is not None:
            return "cancelled"

        # 2. confirmed: tell the patient, then remind them
        await self._notify(start, NotificationKind.CONFIRMED)
        for seconds in sorted(start.reminders, reverse=True):
            at = begins - timedelta(seconds=seconds)
            if at <= workflow.now():
                continue
            if await self._until(at, lambda: self._cancelled is not None):
                return await self._end_cancelled(start)
            await self._notify(start, NotificationKind.REMINDER, seconds // 60)

        # 3. the visit: completed unless cancelled or recorded as a no-show
        finished = ends + timedelta(seconds=start.complete_after_seconds)
        if await self._until(finished, lambda: self._cancelled is not None or self._no_show):
            if self._cancelled is not None:
                return await self._end_cancelled(start)
            return "no_show"
        await workflow.execute_activity(activities.complete, ref, **ACTIVITY)
        return "completed"

    async def _end_cancelled(self, start: BookingStart) -> str:
        if self._cancelled.by == "doctor":
            await self._notify(start, NotificationKind.CANCELLED_BY_DOCTOR)
        return "cancelled"

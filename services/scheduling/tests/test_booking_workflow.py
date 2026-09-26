"""
BookingWorkflow's order of work over fake activities. Times are seconds
away, so the suite runs on a real Temporal as well as on the time-skipping
test server.
"""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from temporalio import activity
from temporalio.worker import Worker

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
from nafas_scheduling.workflows import WORKFLOWS


class FakeActivities:
    def __init__(self, hold_still_waiting: bool = True):
        self.hold_still_waiting = hold_still_waiting
        self.calls: list[str] = []

    @activity.defn(name="scheduling.expire_hold")
    async def expire_hold(self, ref: AppointmentRef) -> bool:
        self.calls.append("expire_hold")
        return self.hold_still_waiting

    @activity.defn(name="scheduling.complete")
    async def complete(self, ref: AppointmentRef) -> bool:
        self.calls.append("complete")
        return True

    @activity.defn(name="scheduling.notify")
    async def notify(self, request: NotificationRequest) -> None:
        self.calls.append(request.kind)

    def all(self):
        return [self.expire_hold, self.complete, self.notify]


def booking(*, hold_in: float, starts_in: float, lasts: float = 1, reminders=(2, 1)) -> BookingStart:
    now = datetime.now(UTC)
    start = now + timedelta(seconds=starts_in)
    return BookingStart(
        appointment_id=str(uuid.uuid4()),
        doctor_id=str(uuid.uuid4()),
        start=start.isoformat(),
        end=(start + timedelta(seconds=lasts)).isoformat(),
        hold_expires_at=(now + timedelta(seconds=hold_in)).isoformat(),
        reminders=list(reminders),
        complete_after_seconds=1,
    )


async def run(temporal, task_queue, fakes, start: BookingStart, act=None) -> str:
    async with Worker(temporal, task_queue=task_queue, workflows=WORKFLOWS, activities=fakes.all()):
        handle = await temporal.start_workflow(
            BOOKING_WORKFLOW, start, id=f"booking-{start.appointment_id}", task_queue=task_queue
        )
        if act:
            await act(handle)
        return await handle.result()


async def test_an_unconfirmed_hold_expires_and_the_patient_is_told(temporal, task_queue):
    fakes = FakeActivities()

    result = await run(temporal, task_queue, fakes, booking(hold_in=1, starts_in=3600))

    assert result == "expired"
    assert fakes.calls == ["expire_hold", "hold_expired"]


async def test_a_confirmed_visit_is_announced_reminded_and_completed(temporal, task_queue):
    fakes = FakeActivities()

    async def confirm(handle):
        await handle.signal(CONFIRMED_SIGNAL)

    result = await run(temporal, task_queue, fakes, booking(hold_in=60, starts_in=4), confirm)

    assert result == "completed"
    assert fakes.calls == ["confirmed", "reminder", "reminder", "complete"]


async def test_reminders_already_past_are_skipped(temporal, task_queue):
    fakes = FakeActivities()

    async def confirm(handle):
        await handle.signal(CONFIRMED_SIGNAL)

    # booked for 1.5 s from now: the 24 h reminder is long past, the 1 s one is not
    result = await run(temporal, task_queue, fakes, booking(hold_in=60, starts_in=1.5, reminders=(86400, 1)), confirm)

    assert result == "completed"
    assert fakes.calls == ["confirmed", "reminder", "complete"]


async def test_a_doctor_cancelling_a_confirmed_visit_tells_the_patient(temporal, task_queue):
    fakes = FakeActivities()

    async def confirm_then_cancel(handle):
        await handle.signal(CONFIRMED_SIGNAL)
        await asyncio.sleep(0.5)
        await handle.signal(CANCELLED_SIGNAL, Cancellation(by="doctor"))

    result = await run(temporal, task_queue, fakes, booking(hold_in=60, starts_in=3600), confirm_then_cancel)

    assert result == "cancelled"
    assert fakes.calls == ["confirmed", "cancelled_by_doctor"]


async def test_a_patient_cancelling_their_hold_ends_it_quietly(temporal, task_queue):
    fakes = FakeActivities()

    async def cancel(handle):
        await handle.signal(CANCELLED_SIGNAL, Cancellation(by="patient"))

    result = await run(temporal, task_queue, fakes, booking(hold_in=60, starts_in=3600), cancel)

    assert result == "cancelled"
    assert fakes.calls == []


async def test_a_no_show_is_not_marked_completed(temporal, task_queue):
    fakes = FakeActivities()

    async def confirm_then_no_show(handle):
        await handle.signal(CONFIRMED_SIGNAL)
        await asyncio.sleep(1.5)
        await handle.signal(NO_SHOW_SIGNAL)

    result = await run(temporal, task_queue, fakes, booking(hold_in=60, starts_in=1, lasts=2, reminders=()), confirm_then_no_show)

    assert result == "no_show"
    assert "complete" not in fakes.calls


async def test_a_confirmation_whose_signal_was_lost_is_taken_from_the_database(temporal, task_queue):
    # the hold timer fires, but the database says the appointment is no longer waiting
    fakes = FakeActivities(hold_still_waiting=False)

    result = await run(temporal, task_queue, fakes, booking(hold_in=0.5, starts_in=2, reminders=()))

    assert result == "completed"
    assert fakes.calls == ["expire_hold", "confirmed", "complete"]

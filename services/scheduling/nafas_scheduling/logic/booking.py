"""
Booking against the database. Every function expects a session scoped to
the doctor (session_scope(doctor_id=...)); row-level security makes any other
doctor's rows invisible, and so impossible to book or change.

The flow the booking workflow drives: `check_time` or `find_available` to
choose, `hold` to reserve while the patient confirms, then `confirm` — or
nothing, and the hold lapses. The exclusion constraint on appointments is
the final word on overlap; `hold` turns its refusal into SlotUnavailableError.
"""

import uuid
from datetime import datetime, timedelta

from sqlalchemy import and_, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from nafas_core.metrics import BOOKINGS
from nafas_scheduling.enums import BLOCKING_STATUSES, AppointmentMode, AppointmentStatus, Unavailable
from nafas_scheduling.exceptions import (
    AppointmentNotFoundError,
    HoldExpiredError,
    InvalidTransitionError,
    SlotUnavailableError,
)
from nafas_scheduling.logic import slots
from nafas_scheduling.models import Appointment, AvailabilityRule, BookingSettings, TimeOff

# Postgres's code for an exclusion constraint violation
EXCLUSION_VIOLATION = "23P01"

# how far either side of a range to load bookings and time off: enough to
# cover any appointment or buffer that could reach into it
_MARGIN = timedelta(days=1)


async def load_schedule(
    session: AsyncSession, doctor_id: uuid.UUID, start: datetime, end: datetime, now: datetime
) -> slots.Schedule:
    """Everything the pure rules need about [start, end): hours, time off, and what is already taken."""
    settings = await session.get(BookingSettings, doctor_id)
    if settings is None:
        raise SlotUnavailableError(Unavailable.NOT_BOOKABLE, "this doctor has no booking hours yet")

    rules = (await session.scalars(select(AvailabilityRule).where(AvailabilityRule.doctor_id == doctor_id))).all()
    time_off = (
        await session.scalars(
            select(TimeOff).where(
                TimeOff.doctor_id == doctor_id, TimeOff.ends_at > start - _MARGIN, TimeOff.starts_at < end + _MARGIN
            )
        )
    ).all()
    booked = (
        await session.scalars(
            select(Appointment).where(
                Appointment.doctor_id == doctor_id,
                Appointment.ends_at > start - _MARGIN,
                Appointment.starts_at < end + _MARGIN,
                # a lapsed hold no longer occupies its slot
                or_(
                    Appointment.status == AppointmentStatus.CONFIRMED,
                    and_(Appointment.status == AppointmentStatus.HELD, Appointment.hold_expires_at > now),
                ),
            )
        )
    ).all()

    return slots.Schedule(
        policy=slots.BookingPolicy(
            timezone=settings.timezone,
            slot_minutes=settings.slot_minutes,
            buffer_minutes=settings.buffer_minutes,
            min_notice_minutes=settings.min_notice_minutes,
            horizon_days=settings.horizon_days,
        ),
        hours=[
            slots.WeeklyHours(
                weekday=r.weekday,
                start=r.start_local,
                end=r.end_local,
                mode=r.mode,
                slot_minutes=r.slot_minutes,
                effective_from=r.effective_from,
                effective_to=r.effective_to,
            )
            for r in rules
        ],
        time_off=[slots.Interval(t.starts_at, t.ends_at) for t in time_off],
        booked=[slots.Interval(a.starts_at, a.ends_at) for a in booked],
    )


async def timezone_of(session: AsyncSession, doctor_id: uuid.UUID) -> str:
    settings = await session.get(BookingSettings, doctor_id)
    if settings is None:
        raise SlotUnavailableError(Unavailable.NOT_BOOKABLE, "this doctor has no booking hours yet")

    return settings.timezone


async def check_time(
    session: AsyncSession, doctor_id: uuid.UUID, start: datetime, now: datetime, mode: AppointmentMode
) -> slots.Interval:
    schedule = await load_schedule(session, doctor_id, start, start, now)
    return slots.check_start(schedule, start, now, mode)


async def find_available(
    session: AsyncSession,
    doctor_id: uuid.UUID,
    start: datetime,
    end: datetime,
    now: datetime,
    mode: AppointmentMode,
    limit: int | None = None,
) -> list[slots.Interval]:
    schedule = await load_schedule(session, doctor_id, start, end, now)
    return slots.find_slots(schedule, start, end, now, mode, limit=limit)


async def suggest(
    session: AsyncSession, doctor_id: uuid.UUID, around: datetime, now: datetime, mode: AppointmentMode, count: int = 3
) -> list[slots.Interval]:
    schedule = await load_schedule(session, doctor_id, around - timedelta(days=1), around + timedelta(days=8), now)
    return slots.suggest_near(schedule, around, now, mode, count=count)


async def release_lapsed_holds(session: AsyncSession, doctor_id: uuid.UUID, now: datetime) -> int:
    """Cancels holds past their expiry, freeing their slots for the exclusion constraint too."""
    result = await session.execute(
        update(Appointment)
        .where(
            Appointment.doctor_id == doctor_id,
            Appointment.status == AppointmentStatus.HELD,
            Appointment.hold_expires_at <= now,
        )
        .values(status=AppointmentStatus.CANCELLED, updated_at=now)
    )
    return result.rowcount


async def hold(
    session: AsyncSession,
    *,
    doctor_id: uuid.UUID,
    patient_id: uuid.UUID,
    start: datetime,
    now: datetime,
    mode: AppointmentMode,
    reason_for_visit: str | None = None,
) -> Appointment:
    """
    Reserves exactly `start` for the patient until they confirm.

    Raises SlotUnavailableError with the precise reason: from the rules when
    they refuse, or TAKEN when another request won the race to the same time.
    """
    await release_lapsed_holds(session, doctor_id, now)
    interval = await check_time(session, doctor_id, start, now, mode)
    settings = await session.get(BookingSettings, doctor_id)

    appointment = Appointment(
        doctor_id=doctor_id,
        patient_id=patient_id,
        starts_at=interval.start,
        ends_at=interval.end,
        status=AppointmentStatus.HELD,
        mode=mode,
        hold_expires_at=now + timedelta(minutes=settings.hold_minutes),
        reason_for_visit=reason_for_visit,
    )
    try:
        # a savepoint, so losing the race leaves the caller's transaction usable
        async with session.begin_nested():
            session.add(appointment)
            await session.flush()
    except IntegrityError as exc:
        if getattr(exc.orig, "sqlstate", None) == EXCLUSION_VIOLATION:
            raise SlotUnavailableError(Unavailable.TAKEN, "another booking took this time first") from exc
        raise

    BOOKINGS.labels("held").inc()
    return appointment


async def _get(session: AsyncSession, appointment_id: uuid.UUID) -> Appointment:
    appointment = await session.get(Appointment, appointment_id, with_for_update=True)
    if appointment is None:
        raise AppointmentNotFoundError(str(appointment_id))

    return appointment


async def confirm(session: AsyncSession, appointment_id: uuid.UUID, now: datetime) -> Appointment:
    appointment = await _get(session, appointment_id)

    if appointment.status is AppointmentStatus.CONFIRMED:
        # confirming twice (a retried activity, a double tap) is not an error
        return appointment
    if appointment.status is not AppointmentStatus.HELD:
        raise InvalidTransitionError(f"a {appointment.status.value} appointment cannot be confirmed")
    if appointment.hold_expires_at <= now:
        raise HoldExpiredError("the hold lapsed before it was confirmed")

    appointment.status = AppointmentStatus.CONFIRMED
    appointment.hold_expires_at = None
    await session.flush()
    BOOKINGS.labels("confirmed").inc()

    return appointment


async def cancel(session: AsyncSession, appointment_id: uuid.UUID) -> Appointment:
    appointment = await _get(session, appointment_id)

    if appointment.status is AppointmentStatus.CANCELLED:
        return appointment
    if appointment.status not in BLOCKING_STATUSES:
        raise InvalidTransitionError(f"a {appointment.status.value} appointment cannot be cancelled")

    appointment.status = AppointmentStatus.CANCELLED
    appointment.hold_expires_at = None
    await session.flush()
    BOOKINGS.labels("cancelled").inc()

    return appointment


async def patient_appointments(session: AsyncSession) -> list[Appointment]:
    """
    The current patient's appointments with every doctor, soonest first.

    Needs a patient scope (session_scope(patient_id=...)): the patient policy
    is what makes exactly these rows visible.
    """
    return list((await session.scalars(select(Appointment).order_by(Appointment.starts_at))).all())


async def doctor_appointments(
    session: AsyncSession, doctor_id: uuid.UUID, start: datetime, end: datetime, now: datetime
) -> list[Appointment]:
    """What occupies the doctor's calendar in [start, end): confirmed visits and live holds."""
    return list(
        (
            await session.scalars(
                select(Appointment)
                .where(
                    Appointment.doctor_id == doctor_id,
                    Appointment.starts_at < end,
                    Appointment.ends_at > start,
                    or_(
                        Appointment.status.in_(
                            [AppointmentStatus.CONFIRMED, AppointmentStatus.COMPLETED, AppointmentStatus.NO_SHOW]
                        ),
                        and_(Appointment.status == AppointmentStatus.HELD, Appointment.hold_expires_at > now),
                    ),
                )
                .order_by(Appointment.starts_at)
            )
        ).all()
    )


async def find_visible_appointment(session: AsyncSession, appointment_id: uuid.UUID) -> Appointment:
    """An appointment as the current scope (patient or doctor) sees it; AppointmentNotFoundError if it is not theirs."""
    appointment = await session.get(Appointment, appointment_id)
    if appointment is None:
        raise AppointmentNotFoundError(str(appointment_id))

    return appointment


async def expire_hold(session: AsyncSession, appointment_id: uuid.UUID, now: datetime) -> bool:
    """Cancels this hold if it is still waiting past its expiry; False if it was confirmed or cancelled meanwhile."""
    appointment = await _get(session, appointment_id)
    if appointment.status is not AppointmentStatus.HELD or appointment.hold_expires_at > now:
        return False

    appointment.status = AppointmentStatus.CANCELLED
    appointment.hold_expires_at = None
    await session.flush()
    BOOKINGS.labels("hold_expired").inc()
    return True


async def complete(session: AsyncSession, appointment_id: uuid.UUID) -> bool:
    """A confirmed visit that has ended becomes completed; anything else (a no-show, a cancellation) stays as it is."""
    appointment = await _get(session, appointment_id)
    if appointment.status is not AppointmentStatus.CONFIRMED:
        return False

    appointment.status = AppointmentStatus.COMPLETED
    await session.flush()
    BOOKINGS.labels("completed").inc()
    return True


async def mark_no_show(session: AsyncSession, appointment_id: uuid.UUID, now: datetime) -> Appointment:
    """The doctor records that the patient did not come: only for a confirmed visit that has started."""
    appointment = await _get(session, appointment_id)
    if appointment.status is AppointmentStatus.NO_SHOW:
        return appointment
    if appointment.status not in (AppointmentStatus.CONFIRMED, AppointmentStatus.COMPLETED):
        raise InvalidTransitionError(f"a {appointment.status.value} appointment cannot be a no-show")
    if appointment.starts_at > now:
        raise InvalidTransitionError("an appointment that has not started cannot be a no-show")

    appointment.status = AppointmentStatus.NO_SHOW
    await session.flush()
    BOOKINGS.labels("no_show").inc()
    return appointment

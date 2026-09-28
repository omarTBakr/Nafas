"""
The scheduling service's internal API, reached only by other services (the
gateway today, the booking workflow in phase 3) behind the internal token.

Who is acting is always explicit: a doctor's calendar is read and written in
that doctor's scope; a patient's actions on an appointment start with a
lookup in the patient's own scope, so a patient can only ever touch their
own appointments, whatever id they send.
"""

import uuid
from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import AwareDatetime, BaseModel, model_validator
from sqlalchemy import and_, select, update

from nafas_core.db import session_scope
from nafas_core.health import health_info
from nafas_core.internal_api import require_internal_token
from nafas_core.metrics import instrument
from nafas_scheduling.enums import AppointmentMode, AppointmentStatus, NotificationKind, Unavailable
from nafas_scheduling.events import get_events
from nafas_scheduling.exceptions import (
    AppointmentNotFoundError,
    HoldExpiredError,
    InvalidTransitionError,
    SlotUnavailableError,
)
from nafas_scheduling.logic import booking, notifications
from nafas_scheduling.logic.time_expressions import DayPeriod, DayRef, Meridiem, TimeExpression, resolve
from nafas_scheduling.models import Appointment, BookingSettings


def _now() -> datetime:
    return datetime.now(UTC)


class SlotOut(BaseModel):
    start: datetime
    end: datetime


class BookingInfo(BaseModel):
    doctor_id: uuid.UUID
    timezone: str
    slot_minutes: int
    hold_minutes: int


class CheckOut(BaseModel):
    bookable: bool
    slot: SlotOut | None = None
    reason: Unavailable | None = None
    # the nearest free alternatives, when the time asked for is not bookable
    suggestions: list[SlotOut] = []


class HoldIn(BaseModel):
    patient_id: uuid.UUID
    start: AwareDatetime
    mode: AppointmentMode
    reason_for_visit: str | None = None


class Actor(BaseModel):
    """Exactly one: the patient or the doctor on whose behalf the change is made."""

    patient_id: uuid.UUID | None = None
    doctor_id: uuid.UUID | None = None


class AppointmentOut(BaseModel):
    appointment_id: uuid.UUID
    doctor_id: uuid.UUID
    patient_id: uuid.UUID
    start: datetime
    end: datetime
    status: AppointmentStatus
    mode: AppointmentMode
    hold_expires_at: datetime | None
    reason_for_visit: str | None


def _slot(interval) -> SlotOut:
    return SlotOut(start=interval.start, end=interval.end)


def _appointment(a: Appointment) -> AppointmentOut:
    return AppointmentOut(
        appointment_id=a.id,
        doctor_id=a.doctor_id,
        patient_id=a.patient_id,
        start=a.starts_at,
        end=a.ends_at,
        status=a.status,
        mode=a.mode,
        hold_expires_at=a.hold_expires_at,
        reason_for_visit=a.reason_for_visit,
    )


class DayRefIn(BaseModel):
    """Exactly one: days from today (0 today, 1 tomorrow), a weekday (0 = Monday), or a date."""

    relative_days: int | None = None
    weekday: int | None = None
    on: date | None = None


class TimeExpressionIn(BaseModel):
    """
    What the patient said about time, as the language model extracted it; nothing computed.

    Written by models, so it tolerates their habits where the meaning is not in
    doubt: an explicit null for a field they had no value for, and "pm" said
    again on a 24-hour afternoon hour. A real contradiction (18 "am") is still
    refused.
    """

    day: DayRefIn
    hour: int | None = None
    minute: int | None = 0
    meridiem: Meridiem | None = None
    period: DayPeriod | None = None

    @model_validator(mode="after")
    def _settle_model_habits(self) -> "TimeExpressionIn":
        if self.minute is None:
            self.minute = 0
        if self.hour is not None and self.hour > 12 and self.meridiem is Meridiem.PM:
            self.meridiem = None
        return self


class CandidateOut(BaseModel):
    start: datetime
    bookable: bool
    reason: Unavailable | None = None


class InterpretOut(BaseModel):
    timezone: str
    day: date
    # exact times the patient may have meant (an am/pm pair when nothing settled it), each checked
    candidates: list[CandidateOut]
    # free slots in the period or day they named: what to offer when no exact time works
    free_slots: list[SlotOut]


router = APIRouter(prefix="/internal/v1")


@router.get("/doctors/{doctor_id}/booking-info", response_model=BookingInfo)
async def booking_info(doctor_id: uuid.UUID) -> BookingInfo:
    async with session_scope(doctor_id=doctor_id) as session:
        settings = await session.get(BookingSettings, doctor_id)
    if settings is None:
        raise SlotUnavailableError(Unavailable.NOT_BOOKABLE, "this doctor has no booking hours yet")

    return BookingInfo(
        doctor_id=doctor_id, timezone=settings.timezone, slot_minutes=settings.slot_minutes, hold_minutes=settings.hold_minutes
    )


@router.get("/doctors/{doctor_id}/slots", response_model=list[SlotOut])
async def slots(
    doctor_id: uuid.UUID,
    start: AwareDatetime,
    end: AwareDatetime,
    mode: AppointmentMode = AppointmentMode.IN_PERSON,
    limit: int | None = Query(default=None, ge=1, le=500),
) -> list[SlotOut]:
    if end <= start:
        raise HTTPException(status_code=422, detail="end must be after start")

    async with session_scope(doctor_id=doctor_id) as session:
        found = await booking.find_available(session, doctor_id, start, end, _now(), mode, limit=limit)

    return [_slot(s) for s in found]


@router.get("/doctors/{doctor_id}/check", response_model=CheckOut)
async def check(doctor_id: uuid.UUID, start: AwareDatetime, mode: AppointmentMode = AppointmentMode.IN_PERSON) -> CheckOut:
    """Whether exactly this minute is bookable; if not, why, and the nearest times that are."""
    now = _now()
    async with session_scope(doctor_id=doctor_id) as session:
        try:
            return CheckOut(bookable=True, slot=_slot(await booking.check_time(session, doctor_id, start, now, mode)))
        except SlotUnavailableError as refused:
            if refused.reason is Unavailable.NOT_BOOKABLE:
                raise
            nearby = await booking.suggest(session, doctor_id, start, now, mode)
            return CheckOut(bookable=False, reason=refused.reason, suggestions=[_slot(s) for s in nearby])


@router.post("/doctors/{doctor_id}/interpret-time", response_model=InterpretOut)
async def interpret_time(
    doctor_id: uuid.UUID, expression: TimeExpressionIn, mode: AppointmentMode = AppointmentMode.IN_PERSON
) -> InterpretOut:
    """
    Resolves a patient's words about time in the clinic's zone, checks every
    exact time they might have meant, and lists the free slots around it.
    The language model extracts; this does all the arithmetic.
    """
    try:
        parsed = TimeExpression(
            day=DayRef(relative_days=expression.day.relative_days, weekday=expression.day.weekday, on=expression.day.on),
            hour=expression.hour,
            minute=expression.minute,
            meridiem=expression.meridiem,
            period=expression.period,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    now = _now()
    async with session_scope(doctor_id=doctor_id) as session:
        timezone = await booking.timezone_of(session, doctor_id)
        resolution = resolve(parsed, now, timezone)

        candidates = []
        for start in resolution.candidates:
            try:
                await booking.check_time(session, doctor_id, start, now, mode)
                candidates.append(CandidateOut(start=start, bookable=True))
            except SlotUnavailableError as refused:
                candidates.append(CandidateOut(start=start, bookable=False, reason=refused.reason))

        free = await booking.find_available(
            session, doctor_id, resolution.search.start, resolution.search.end, now, mode, limit=12
        )

    return InterpretOut(timezone=timezone, day=resolution.day, candidates=candidates, free_slots=[_slot(s) for s in free])


@router.post("/doctors/{doctor_id}/holds", response_model=AppointmentOut, status_code=201)
async def hold(doctor_id: uuid.UUID, request: HoldIn) -> AppointmentOut:
    async with session_scope(doctor_id=doctor_id) as session:
        held = await booking.hold(
            session,
            doctor_id=doctor_id,
            patient_id=request.patient_id,
            start=request.start,
            now=_now(),
            mode=request.mode,
            reason_for_visit=request.reason_for_visit,
        )

    # committed first: the workflow's activities must find the row
    workflow_id = await get_events().held(held)
    if workflow_id:
        async with session_scope(doctor_id=doctor_id) as session:
            await session.execute(update(Appointment).where(Appointment.id == held.id).values(booking_workflow_id=workflow_id))
        held.booking_workflow_id = workflow_id

    return _appointment(held)


async def _doctor_of(appointment_id: uuid.UUID, actor: Actor) -> uuid.UUID:
    """The appointment's doctor, found in the actor's own scope: not theirs means not found."""
    if (actor.patient_id is None) == (actor.doctor_id is None):
        raise HTTPException(status_code=422, detail="name exactly one of patient_id and doctor_id")

    async with session_scope(patient_id=actor.patient_id, doctor_id=actor.doctor_id) as session:
        return (await booking.find_visible_appointment(session, appointment_id)).doctor_id


@router.post("/appointments/{appointment_id}/confirm", response_model=AppointmentOut)
async def confirm(appointment_id: uuid.UUID, actor: Actor) -> AppointmentOut:
    doctor_id = await _doctor_of(appointment_id, actor)
    async with session_scope(doctor_id=doctor_id) as session:
        confirmed = await booking.confirm(session, appointment_id, _now())
    await get_events().confirmed(confirmed)
    return _appointment(confirmed)


@router.post("/appointments/{appointment_id}/cancel", response_model=AppointmentOut)
async def cancel(appointment_id: uuid.UUID, actor: Actor) -> AppointmentOut:
    doctor_id = await _doctor_of(appointment_id, actor)
    async with session_scope(doctor_id=doctor_id) as session:
        cancelled = await booking.cancel(session, appointment_id)
    await get_events().cancelled(cancelled, by="doctor" if actor.doctor_id else "patient")
    return _appointment(cancelled)


class DoctorActor(BaseModel):
    doctor_id: uuid.UUID


@router.post("/appointments/{appointment_id}/no-show", response_model=AppointmentOut)
async def no_show(appointment_id: uuid.UUID, actor: DoctorActor) -> AppointmentOut:
    """The doctor records that the patient did not come; only the appointment's own doctor can."""
    doctor_id = await _doctor_of(appointment_id, Actor(doctor_id=actor.doctor_id))
    async with session_scope(doctor_id=doctor_id) as session:
        marked = await booking.mark_no_show(session, appointment_id, _now())
    await get_events().no_show(marked)
    return _appointment(marked)


class NotificationOut(BaseModel):
    notification_id: uuid.UUID
    appointment_id: uuid.UUID
    doctor_id: uuid.UUID
    kind: NotificationKind
    minutes_before: int | None
    details: dict
    read_at: datetime | None
    created_at: datetime


@router.get("/patients/{patient_id}/notifications", response_model=list[NotificationOut])
async def patient_notifications(
    patient_id: uuid.UUID, unread_only: bool = False, limit: int = Query(default=50, ge=1, le=200)
) -> list[NotificationOut]:
    async with session_scope(patient_id=patient_id) as session:
        found = await notifications.patient_notifications(session, unread_only=unread_only, limit=limit)
    return [
        NotificationOut(
            notification_id=n.id,
            appointment_id=n.appointment_id,
            doctor_id=n.doctor_id,
            kind=n.kind,
            minutes_before=n.minutes_before,
            details=n.details,
            read_at=n.read_at,
            created_at=n.created_at,
        )
        for n in found
    ]


@router.post("/patients/{patient_id}/notifications/{notification_id}/read", status_code=204)
async def read_notification(patient_id: uuid.UUID, notification_id: uuid.UUID) -> None:
    async with session_scope(patient_id=patient_id) as session:
        if not await notifications.mark_read(session, notification_id, _now()):
            raise HTTPException(status_code=404, detail="no such notification")


@router.get("/appointments/{appointment_id}", response_model=AppointmentOut)
async def appointment(
    appointment_id: uuid.UUID, patient_id: uuid.UUID | None = None, doctor_id: uuid.UUID | None = None
) -> AppointmentOut:
    """One appointment, read as its patient or as its doctor: someone else's is not found."""
    if (patient_id is None) == (doctor_id is None):
        raise HTTPException(status_code=422, detail="read an appointment as its patient or as its doctor")
    async with session_scope(patient_id=patient_id, doctor_id=doctor_id) as session:
        return _appointment(await booking.find_visible_appointment(session, appointment_id))


@router.get("/patients/{patient_id}/appointments", response_model=list[AppointmentOut])
async def patient_appointments(patient_id: uuid.UUID) -> list[AppointmentOut]:
    async with session_scope(patient_id=patient_id) as session:
        return [_appointment(a) for a in await booking.patient_appointments(session, _now())]


@router.get("/doctors/{doctor_id}/patients/{patient_id}/appointments", response_model=list[AppointmentOut])
async def doctor_patient_appointments(doctor_id: uuid.UUID, patient_id: uuid.UUID) -> list[AppointmentOut]:
    """
    One patient's appointments with this doctor, every status, oldest first: for the doctor's timeline.
    A hold past its expiry is left out, as on the patient's own list: it is not a booking.
    """
    lapsed = and_(Appointment.status == AppointmentStatus.HELD, Appointment.hold_expires_at <= _now())
    async with session_scope(doctor_id=doctor_id) as session:
        rows = (
            await session.scalars(
                select(Appointment)
                .where(Appointment.doctor_id == doctor_id, Appointment.patient_id == patient_id, ~lapsed)
                .order_by(Appointment.starts_at)
            )
        ).all()
    return [_appointment(a) for a in rows]


@router.get("/doctors/{doctor_id}/appointments", response_model=list[AppointmentOut])
async def doctor_appointments(doctor_id: uuid.UUID, start: AwareDatetime, end: AwareDatetime) -> list[AppointmentOut]:
    async with session_scope(doctor_id=doctor_id) as session:
        return [_appointment(a) for a in await booking.doctor_appointments(session, doctor_id, start, end, _now())]


app = FastAPI(title="Nafas scheduling (internal)")
instrument(app, "scheduling")
app.include_router(router, dependencies=[Depends(require_internal_token)])


@app.get("/health")
async def health() -> dict:
    return health_info("scheduling")


# domain refusals become answers a caller can act on, with the reason in the body
@app.exception_handler(SlotUnavailableError)
async def unavailable(request: Request, exc: SlotUnavailableError) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": str(exc), "reason": exc.reason.value})


@app.exception_handler(AppointmentNotFoundError)
async def not_found(request: Request, exc: AppointmentNotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": "no such appointment"})


@app.exception_handler(HoldExpiredError)
async def hold_expired(request: Request, exc: HoldExpiredError) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": str(exc), "reason": "hold_expired"})


@app.exception_handler(InvalidTransitionError)
async def invalid_transition(request: Request, exc: InvalidTransitionError) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": str(exc), "reason": "invalid_transition"})

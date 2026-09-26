"""
The scheduling service's internal API, reached only by other services (the
gateway today, the booking workflow in phase 3) behind the internal token.

Who is acting is always explicit: a doctor's calendar is read and written in
that doctor's scope; a patient's actions on an appointment start with a
lookup in the patient's own scope, so a patient can only ever touch their
own appointments, whatever id they send.
"""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import AwareDatetime, BaseModel

from nafas_core.db import session_scope
from nafas_core.internal_api import require_internal_token
from nafas_scheduling.enums import AppointmentMode, AppointmentStatus, Unavailable
from nafas_scheduling.exceptions import (
    AppointmentNotFoundError,
    HoldExpiredError,
    InvalidTransitionError,
    SlotUnavailableError,
)
from nafas_scheduling.logic import booking
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
        return _appointment(await booking.confirm(session, appointment_id, _now()))


@router.post("/appointments/{appointment_id}/cancel", response_model=AppointmentOut)
async def cancel(appointment_id: uuid.UUID, actor: Actor) -> AppointmentOut:
    doctor_id = await _doctor_of(appointment_id, actor)
    async with session_scope(doctor_id=doctor_id) as session:
        return _appointment(await booking.cancel(session, appointment_id))


@router.get("/patients/{patient_id}/appointments", response_model=list[AppointmentOut])
async def patient_appointments(patient_id: uuid.UUID) -> list[AppointmentOut]:
    async with session_scope(patient_id=patient_id) as session:
        return [_appointment(a) for a in await booking.patient_appointments(session)]


@router.get("/doctors/{doctor_id}/appointments", response_model=list[AppointmentOut])
async def doctor_appointments(doctor_id: uuid.UUID, start: AwareDatetime, end: AwareDatetime) -> list[AppointmentOut]:
    async with session_scope(doctor_id=doctor_id) as session:
        return [_appointment(a) for a in await booking.doctor_appointments(session, doctor_id, start, end, _now())]


app = FastAPI(title="Nafas scheduling (internal)")
app.include_router(router, dependencies=[Depends(require_internal_token)])


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


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

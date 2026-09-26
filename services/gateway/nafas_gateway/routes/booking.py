"""Patient booking. Every route acts for the logged-in patient only: the patient id comes from the session, never the request."""

import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import AwareDatetime, BaseModel

from nafas_gateway.clients.identity import Account, get_identity
from nafas_gateway.clients.scheduling import get_scheduling
from nafas_gateway.sessions import current_account, current_patient

router = APIRouter(prefix="/api", tags=["booking"])

# how much calendar one slots request may ask for
MAX_RANGE = timedelta(days=31)


class HoldRequest(BaseModel):
    doctor_id: uuid.UUID
    start: AwareDatetime
    mode: str = "in_person"
    reason_for_visit: str | None = None


@router.get("/doctors/{doctor_id}/booking-info")
async def booking_info(doctor_id: uuid.UUID, account: Account = Depends(current_account)) -> dict:
    return await get_scheduling().booking_info(doctor_id)


@router.get("/doctors/{doctor_id}/slots")
async def slots(
    doctor_id: uuid.UUID,
    start: AwareDatetime,
    end: AwareDatetime,
    mode: str = "in_person",
    limit: int | None = Query(default=None, ge=1, le=500),
    account: Account = Depends(current_account),
) -> list[dict]:
    if not start < end <= start + MAX_RANGE:
        raise HTTPException(status_code=422, detail="the range must be positive and at most 31 days")

    return await get_scheduling().slots(doctor_id, start, end, mode, limit)


@router.get("/doctors/{doctor_id}/check")
async def check(
    doctor_id: uuid.UUID, start: AwareDatetime, mode: str = "in_person", patient: Account = Depends(current_patient)
) -> dict:
    return await get_scheduling().check(doctor_id, start, mode)


@router.post("/appointments", status_code=201)
async def hold(request: HoldRequest, patient: Account = Depends(current_patient)) -> dict:
    """Holds the exact time for this patient while they confirm; 409 with the reason when it cannot."""
    body = {
        "patient_id": str(patient.patient_id),
        "start": request.start.isoformat(),
        "mode": request.mode,
        "reason_for_visit": request.reason_for_visit,
    }
    return await get_scheduling().hold(request.doctor_id, body)


@router.post("/appointments/{appointment_id}/confirm")
async def confirm(appointment_id: uuid.UUID, patient: Account = Depends(current_patient)) -> dict:
    confirmed = await get_scheduling().confirm(appointment_id, {"patient_id": str(patient.patient_id)})
    # the booking puts the patient under the doctor's care (idempotent on later bookings)
    await get_identity().ensure_care_link(uuid.UUID(confirmed["doctor_id"]), patient.patient_id)
    return confirmed


@router.post("/appointments/{appointment_id}/cancel")
async def cancel(appointment_id: uuid.UUID, account: Account = Depends(current_account)) -> dict:
    """A patient cancels their own appointment; a doctor, one of theirs. Anyone else's is not found."""
    if account.patient_id:
        actor = {"patient_id": str(account.patient_id)}
    elif account.doctor_id:
        actor = {"doctor_id": str(account.doctor_id)}
    else:
        raise HTTPException(status_code=403, detail="for patients and doctors only")

    return await get_scheduling().cancel(appointment_id, actor)


@router.get("/appointments/mine")
async def my_appointments(patient: Account = Depends(current_patient)) -> list[dict]:
    """The patient's appointments, each with its doctor's card for display."""
    appointments = await get_scheduling().patient_appointments(patient.patient_id)
    doctors = {d["doctor_id"]: d for d in await get_identity().doctors()}

    return [a | {"doctor": doctors.get(a["doctor_id"])} for a in appointments]

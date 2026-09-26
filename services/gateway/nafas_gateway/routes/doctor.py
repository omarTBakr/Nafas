"""The doctor portal's routes. Every route acts for the logged-in doctor only."""

import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import AwareDatetime, BaseModel, Field

from nafas_core.clients.conversation import get_conversation
from nafas_core.clients.identity import Account, get_identity
from nafas_core.clients.scheduling import get_scheduling
from nafas_gateway.sessions import current_doctor

router = APIRouter(prefix="/api/doctor", tags=["doctor"])


@router.get("/schedule")
async def schedule(start: AwareDatetime, end: AwareDatetime, doctor: Account = Depends(current_doctor)) -> dict:
    """
    The doctor's appointments in [start, end), with patient names where the
    patient is under their care. A hold not yet confirmed has no care link,
    so it shows without a name: the patient has not committed yet.
    """
    if not start < end <= start + timedelta(days=31):
        raise HTTPException(status_code=422, detail="the range must be positive and at most 31 days")

    appointments = await get_scheduling().doctor_appointments(doctor.doctor_id, start, end)
    names = await get_identity().patient_names(doctor.doctor_id, [uuid.UUID(a["patient_id"]) for a in appointments])
    info = await get_scheduling().booking_info(doctor.doctor_id)

    return {
        "timezone": info["timezone"],
        "appointments": [a | {"patient_name": names.get(a["patient_id"])} for a in appointments],
    }


@router.post("/appointments/{appointment_id}/no-show")
async def no_show(appointment_id: uuid.UUID, doctor: Account = Depends(current_doctor)) -> dict:
    """The patient did not come: only the appointment's own doctor, and only once it has started."""
    return await get_scheduling().no_show(appointment_id, doctor.doctor_id)


class Reply(BaseModel):
    reply: str = Field(min_length=1, max_length=4000)


@router.get("/escalations")
async def escalations(status: list[str] = Query(default=["open"]), doctor: Account = Depends(current_doctor)) -> list[dict]:
    """Questions the assistant sent to this doctor, with the patient's name when they are under the doctor's care."""
    items = await get_conversation().escalations(doctor.doctor_id, status)
    names = await get_identity().patient_names(doctor.doctor_id, list({uuid.UUID(i["patient_id"]) for i in items}))
    return [item | {"patient_name": names.get(item["patient_id"])} for item in items]


@router.post("/escalations/{escalation_id}/reply")
async def reply(escalation_id: uuid.UUID, body: Reply, doctor: Account = Depends(current_doctor)) -> dict:
    """The doctor's answer, which appears in the patient's chat as theirs."""
    return await get_conversation().reply_to_escalation(doctor.doctor_id, escalation_id, body.reply)

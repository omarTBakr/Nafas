"""
Online visits from the web app: joining the room (patient or doctor), and
the doctor recording it. The consultation service decides who may join and
when; this only says who is asking.
"""

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from nafas_core.clients.consultation import get_consultation
from nafas_core.clients.identity import Account, get_identity
from nafas_core.enums.identity import UserRole
from nafas_gateway.sessions import current_account, current_doctor

router = APIRouter(prefix="/api", tags=["visits"])


class RecordIn(BaseModel):
    # the doctor confirms, in the call, that the patient agreed to this recording
    evidence: str = Field(default="verbal, at the start of the online visit", min_length=1, max_length=200)


async def _display_name(account: Account) -> str:
    """The name the other side sees in the call."""
    if account.role is UserRole.DOCTOR and account.doctor_id:
        doctor = await get_identity().doctor(account.doctor_id)
        return doctor.get("full_name_ar") or doctor.get("full_name_en") or "Doctor"
    profile = await get_identity().profile(account.patient_id)
    return profile.get("full_name") or "Patient"


@router.post("/visits/{appointment_id}/join")
async def join(appointment_id: uuid.UUID, account: Account = Depends(current_account)) -> dict:
    role = "doctor" if account.role is UserRole.DOCTOR else "patient"
    person = account.doctor_id if role == "doctor" else account.patient_id
    return await get_consultation().join_visit(appointment_id, role, person, await _display_name(account))


@router.post("/doctor/visits/{appointment_id}/recording", status_code=201)
async def record(appointment_id: uuid.UUID, body: RecordIn, doctor: Account = Depends(current_doctor)) -> dict:
    return await get_consultation().start_online_recording(doctor.doctor_id, appointment_id, body.evidence)


@router.post("/doctor/consultations/{consultation_id}/stop-recording")
async def stop(consultation_id: uuid.UUID, doctor: Account = Depends(current_doctor)) -> dict:
    return await get_consultation().stop_online_recording(doctor.doctor_id, consultation_id)

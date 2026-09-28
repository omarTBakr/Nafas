"""
Recording an in-person visit, from the doctor's portal: consent, the
recorder's parts, the draft note to review, approve or discard. Only for
patients under the doctor's care; the consultation service checks.
"""

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from nafas_core.clients.consultation import get_consultation
from nafas_core.clients.identity import Account
from nafas_gateway.routes.patient_visits import visit_of
from nafas_gateway.sessions import current_doctor

router = APIRouter(prefix="/api/doctor", tags=["consultations"])


class StartIn(BaseModel):
    # the doctor confirms, in the portal, that the patient agreed to this recording
    evidence: str = Field(default="verbal, in the room", min_length=1, max_length=200)
    appointment_id: uuid.UUID | None = None


class PartIn(BaseModel):
    index: int = Field(ge=0)
    mime: str = Field(min_length=1, max_length=100)
    offset_seconds: float = Field(ge=0)
    size_bytes: int = Field(gt=0)


class ApproveIn(BaseModel):
    # validated by the consultation service, which owns the note's shape
    note: dict
    share_with_patient: bool = False


@router.post("/patients/{patient_id}/consultations", status_code=201)
async def start(patient_id: uuid.UUID, body: StartIn, doctor: Account = Depends(current_doctor)) -> dict:
    if body.appointment_id:
        await visit_of(doctor.doctor_id, patient_id, body.appointment_id)
    return await get_consultation().start(doctor.doctor_id, patient_id, body.model_dump(mode="json"))


@router.post("/consultations/{consultation_id}/parts", status_code=201)
async def new_part(consultation_id: uuid.UUID, body: PartIn, doctor: Account = Depends(current_doctor)) -> dict:
    """A link the recorder PUTs one part to, straight to storage."""
    return await get_consultation().new_part(doctor.doctor_id, consultation_id, body.model_dump())


@router.post("/consultations/{consultation_id}/finish")
async def finish(consultation_id: uuid.UUID, doctor: Account = Depends(current_doctor)) -> dict:
    return await get_consultation().finish(doctor.doctor_id, consultation_id)


@router.get("/consultations")
async def awaiting_review(doctor: Account = Depends(current_doctor)) -> list[dict]:
    return await get_consultation().awaiting_review(doctor.doctor_id)


@router.get("/consultations/{consultation_id}")
async def detail(consultation_id: uuid.UUID, doctor: Account = Depends(current_doctor)) -> dict:
    return await get_consultation().detail(doctor.doctor_id, consultation_id)


@router.post("/consultations/{consultation_id}/approve")
async def approve(consultation_id: uuid.UUID, body: ApproveIn, doctor: Account = Depends(current_doctor)) -> dict:
    return await get_consultation().approve(doctor.doctor_id, consultation_id, body.model_dump())


@router.post("/consultations/{consultation_id}/discard")
async def discard(consultation_id: uuid.UUID, doctor: Account = Depends(current_doctor)) -> dict:
    return await get_consultation().discard(doctor.doctor_id, consultation_id)

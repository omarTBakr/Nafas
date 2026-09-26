"""
A doctor's view of one patient's record: history, documents, uploads, and
what the patient may see. Only for patients under the doctor's care, which
clinical-records checks with identity on every write.
"""

import uuid
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from nafas_core.clients.clinical import get_clinical
from nafas_core.clients.identity import Account
from nafas_gateway.sessions import current_doctor, current_patient

router = APIRouter(prefix="/api", tags=["records"])


class UploadRequest(BaseModel):
    kind: str = "other"
    filename: str = Field(min_length=1, max_length=255)
    mime: str
    size_bytes: int = Field(gt=0)


class NoteIn(BaseModel):
    kind: str = "note"
    content: str = Field(min_length=1, max_length=20000)
    visibility: Literal["doctor_only", "patient_visible"] = "doctor_only"


class VisibilityIn(BaseModel):
    visibility: Literal["doctor_only", "patient_visible"]


@router.get("/doctor/patients/{patient_id}/documents")
async def documents(patient_id: uuid.UUID, doctor: Account = Depends(current_doctor)) -> list[dict]:
    return await get_clinical().documents(doctor.doctor_id, patient_id)


@router.post("/doctor/patients/{patient_id}/documents", status_code=201)
async def start_upload(patient_id: uuid.UUID, body: UploadRequest, doctor: Account = Depends(current_doctor)) -> dict:
    """A link the browser PUTs the file to directly, then /uploaded to read and index it."""
    return await get_clinical().new_document(doctor.doctor_id, patient_id, body.model_dump())


@router.post("/doctor/documents/{document_id}/uploaded")
async def finish_upload(document_id: uuid.UUID, doctor: Account = Depends(current_doctor)) -> dict:
    return await get_clinical().uploaded(doctor.doctor_id, document_id)


@router.get("/doctor/documents/{document_id}/download")
async def download(document_id: uuid.UUID, doctor: Account = Depends(current_doctor)) -> dict:
    return await get_clinical().download(doctor.doctor_id, document_id)


@router.get("/doctor/patients/{patient_id}/history")
async def history(patient_id: uuid.UUID, doctor: Account = Depends(current_doctor)) -> list[dict]:
    return await get_clinical().history(doctor.doctor_id, patient_id)


@router.post("/doctor/patients/{patient_id}/history", status_code=201)
async def add_note(patient_id: uuid.UUID, body: NoteIn, doctor: Account = Depends(current_doctor)) -> dict:
    return await get_clinical().add_entry(doctor.doctor_id, patient_id, body.model_dump() | {"author_id": str(doctor.user_id)})


@router.patch("/doctor/records/{source_type}/{record_id}/visibility", status_code=204)
async def visibility(
    source_type: Literal["document", "history"],
    record_id: uuid.UUID,
    body: VisibilityIn,
    doctor: Account = Depends(current_doctor),
) -> None:
    await get_clinical().set_visibility(doctor.doctor_id, source_type, record_id, body.visibility)


@router.get("/me/documents")
async def shared_with_me(patient: Account = Depends(current_patient)) -> list[dict]:
    """What the patient's doctors shared with them."""
    return await get_clinical().patient_documents(patient.patient_id)

"""The patient's consents: what they agreed to, given and revoked by the patient alone."""

import uuid
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from nafas_core.clients.identity import Account, get_identity
from nafas_gateway.sessions import current_patient

router = APIRouter(prefix="/api/me/consents", tags=["consents"])

# the wording shown in the web app; stored as the evidence of what was agreed to
CONSENT_VERSION = "consent-v1"


class ConsentIn(BaseModel):
    kind: Literal["data_processing", "ai_chat"]
    doctor_id: uuid.UUID | None = None


@router.get("")
async def consents(patient: Account = Depends(current_patient)) -> list[dict]:
    return await get_identity().consents(patient.patient_id)


@router.post("", status_code=201)
async def grant(consent: ConsentIn, patient: Account = Depends(current_patient)) -> dict:
    return await get_identity().grant_consent(patient.patient_id, consent.kind, consent.doctor_id, f"web:{CONSENT_VERSION}")


@router.post("/{consent_id}/revoke", status_code=204)
async def revoke(consent_id: uuid.UUID, patient: Account = Depends(current_patient)) -> None:
    await get_identity().revoke_consent(patient.patient_id, consent_id)

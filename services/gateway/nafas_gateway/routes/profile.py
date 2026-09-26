from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from nafas_core.clients.conversation import get_conversation
from nafas_core.clients.identity import Account, get_identity
from nafas_core.enums.dialect import SpokenDialect, VoiceGender
from nafas_core.enums.identity import Language
from nafas_gateway.sessions import current_patient

router = APIRouter(prefix="/api/me", tags=["profile"])


class ProfileChanges(BaseModel):
    """Only the fields sent change; null clears dialect, voice or phone."""

    full_name: str | None = Field(default=None, min_length=2, max_length=200)
    phone: str | None = Field(default=None, max_length=32)
    preferred_language: Language | None = None
    dialect: SpokenDialect | None = None
    voice: VoiceGender | None = None


@router.get("/profile")
async def profile(patient: Account = Depends(current_patient)) -> dict:
    return await get_identity().profile(patient.patient_id)


@router.patch("/profile")
async def change_profile(changes: ProfileChanges, patient: Account = Depends(current_patient)) -> dict:
    return await get_identity().update_profile(patient.patient_id, changes.model_dump(mode="json", exclude_unset=True))


@router.get("/dialect-suggestion")
async def dialect_suggestion(patient: Account = Depends(current_patient)) -> dict:
    """What the assistant thinks the patient writes in; the web app offers it, never applies it by itself."""
    return await get_conversation().dialect_suggestion(patient.patient_id)

"""The patient's in-app notices: confirmations, reminders, lapsed holds."""

import uuid

from fastapi import APIRouter, Depends

from nafas_core.clients.identity import Account
from nafas_core.clients.scheduling import get_scheduling
from nafas_gateway.sessions import current_patient

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("")
async def notifications(unread_only: bool = False, patient: Account = Depends(current_patient)) -> list[dict]:
    return await get_scheduling().notifications(patient.patient_id, unread_only)


@router.post("/{notification_id}/read", status_code=204)
async def read(notification_id: uuid.UUID, patient: Account = Depends(current_patient)) -> None:
    await get_scheduling().read_notification(patient.patient_id, notification_id)

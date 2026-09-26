"""
The doctor's dashboard: their patients, one patient's timeline, and who is
next. The gateway puts together what each owning service holds; every read
is audited by the service that holds it.
"""

import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends

from nafas_core.clients.clinical import get_clinical
from nafas_core.clients.consultation import get_consultation
from nafas_core.clients.conversation import get_conversation
from nafas_core.clients.identity import Account, get_identity
from nafas_core.clients.scheduling import get_scheduling
from nafas_core.clients.timeline import timeline_items as shared_timeline
from nafas_gateway.errors import Refusal
from nafas_gateway.sessions import current_doctor

router = APIRouter(prefix="/api/doctor", tags=["dashboard"])

# a visit still counts as "next" for a while after it was due to start
LATE_GRACE = timedelta(minutes=20)


async def _patient_of(doctor: Account, patient_id: uuid.UUID) -> dict:
    """The patient's card, if they are under this doctor's care; 403 otherwise."""
    card = next((p for p in await get_identity().roster(doctor.doctor_id) if p["patient_id"] == str(patient_id)), None)
    if card is None:
        raise Refusal(403, "not_under_care", "this patient is not under your care")
    return card


def _at(value: str) -> datetime:
    return datetime.fromisoformat(value)


async def timeline_items(doctor_id: uuid.UUID, patient_id: uuid.UUID) -> list[dict]:
    return await shared_timeline(
        doctor_id,
        patient_id,
        scheduling=get_scheduling(),
        clinical=get_clinical(),
        conversation=get_conversation(),
        consultation=get_consultation(),
    )


@router.get("/patients")
async def patients(doctor: Account = Depends(current_doctor)) -> list[dict]:
    return await get_identity().roster(doctor.doctor_id)


@router.get("/patients/{patient_id}/timeline")
async def timeline(patient_id: uuid.UUID, doctor: Account = Depends(current_doctor)) -> dict:
    card = await _patient_of(doctor, patient_id)
    zone = (await get_scheduling().booking_info(doctor.doctor_id))["timezone"]
    return {"patient": card, "timezone": zone, "items": await timeline_items(doctor.doctor_id, patient_id)}


@router.get("/next")
async def next_patient(doctor: Account = Depends(current_doctor)) -> dict:
    """
    The next confirmed visit today at the clinic (or one that started a few
    minutes ago), with a brief of the patient: last visit, recent entries,
    questions waiting, documents on file. Null when the day is done.
    """
    now = datetime.now(UTC)
    zone = ZoneInfo((await get_scheduling().booking_info(doctor.doctor_id))["timezone"])
    end_of_day = datetime.combine(now.astimezone(zone).date() + timedelta(days=1), datetime.min.time(), tzinfo=zone)
    today = await get_scheduling().doctor_appointments(doctor.doctor_id, now - LATE_GRACE, end_of_day)
    upcoming = [a for a in today if a["status"] == "confirmed" and _at(a["start"]) >= now - LATE_GRACE]
    if not upcoming:
        return {"appointment": None, "timezone": str(zone)}

    visit = min(upcoming, key=lambda a: _at(a["start"]))
    patient_id = uuid.UUID(visit["patient_id"])
    card = await _patient_of(doctor, patient_id)
    items = await timeline_items(doctor.doctor_id, patient_id)
    past_visits = [i for i in items if i["type"] == "appointment" and i["status"] == "completed"]
    return {
        "appointment": visit,
        "timezone": str(zone),
        "patient": card,
        "brief": {
            "last_visit": past_visits[0]["start"] if past_visits else None,
            "recent_entries": [i for i in items if i["type"] == "history"][:3],
            "open_questions": [i for i in items if i["type"] == "escalation" and i["status"] == "open"],
            "documents": len([i for i in items if i["type"] == "document"]),
        },
    }

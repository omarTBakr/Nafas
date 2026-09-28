"""
One patient's visits, each read on its own: the appointment, its recordings
and their notes, and the notes and documents the doctor filed under it. A
visit is an appointment; what belongs to it is linked by its id, or (for a
recording's filed note) by the recording it came from.
"""

import uuid

from fastapi import APIRouter, Depends

from nafas_core.clients.clinical import get_clinical
from nafas_core.clients.consultation import get_consultation
from nafas_core.clients.identity import Account
from nafas_core.clients.scheduling import get_scheduling
from nafas_gateway.errors import Refusal
from nafas_gateway.routes.dashboard import _patient_of
from nafas_gateway.sessions import current_doctor

router = APIRouter(prefix="/api/doctor", tags=["visits"])


async def visit_of(doctor_id: uuid.UUID, patient_id: uuid.UUID, appointment_id: uuid.UUID) -> dict:
    """The appointment, if it is this doctor's with this patient; 404 otherwise."""
    appointment = await get_scheduling().appointment(appointment_id, doctor_id=doctor_id)
    if appointment["patient_id"] != str(patient_id):
        raise Refusal(404, "visit_not_found", "this visit is not this patient's")
    return appointment


def _belongs(appointment_id: str, consultation_ids: set[str]):
    def belongs(entry: dict) -> bool:
        if entry.get("appointment_id") == appointment_id:
            return True
        return entry.get("source_type") == "consultation" and entry.get("source_id") in consultation_ids

    return belongs


def _visit(appointment: dict, consultations: list[dict], history: list[dict], documents: list[dict]) -> dict:
    """The appointment with what was filed under it."""
    aid = appointment["appointment_id"]
    recordings = [c for c in consultations if c.get("appointment_id") == aid and c["status"] != "discarded"]
    belongs = _belongs(aid, {c["consultation_id"] for c in recordings})
    return {
        "appointment": appointment,
        "consultations": recordings,
        "history": [e for e in history if belongs(e)],
        "documents": [d for d in documents if d.get("appointment_id") == aid],
    }


async def _record(doctor_id: uuid.UUID, patient_id: uuid.UUID) -> tuple[list[dict], list[dict], list[dict]]:
    clinical = get_clinical()
    return (
        await get_consultation().for_patient(doctor_id, patient_id),
        await clinical.history(doctor_id, patient_id),
        await clinical.documents(doctor_id, patient_id),
    )


@router.get("/patients/{patient_id}/visits")
async def visits(patient_id: uuid.UUID, doctor: Account = Depends(current_doctor)) -> dict:
    """Every visit, newest first, with how much was filed under each."""
    card = await _patient_of(doctor, patient_id)
    zone = (await get_scheduling().booking_info(doctor.doctor_id))["timezone"]
    appointments = await get_scheduling().doctor_patient_appointments(doctor.doctor_id, patient_id)
    consultations, history, documents = await _record(doctor.doctor_id, patient_id)
    out = []
    for appointment in sorted(appointments, key=lambda a: a["start"], reverse=True):
        visit = _visit(appointment, consultations, history, documents)
        out.append(
            appointment
            | {
                "recordings": len(visit["consultations"]),
                "notes": len(visit["history"]),
                "documents": len(visit["documents"]),
            }
        )
    return {"patient": card, "timezone": zone, "visits": out}


@router.get("/patients/{patient_id}/visits/{appointment_id}")
async def visit(patient_id: uuid.UUID, appointment_id: uuid.UUID, doctor: Account = Depends(current_doctor)) -> dict:
    card = await _patient_of(doctor, patient_id)
    appointment = await visit_of(doctor.doctor_id, patient_id, appointment_id)
    zone = (await get_scheduling().booking_info(doctor.doctor_id))["timezone"]
    consultations, history, documents = await _record(doctor.doctor_id, patient_id)
    return {"patient": card, "timezone": zone} | _visit(appointment, consultations, history, documents)

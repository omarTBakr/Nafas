"""
One patient's file organized by session: each visit (an appointment) with its
summary, recordings, documents and notes; what belongs to no visit; and the
questions waiting for the doctor. What belongs to a visit is linked by its
id, or (for a recording's filed note) by the recording it came from.
"""

import uuid

from fastapi import APIRouter, Depends

from nafas_core.clients.clinical import get_clinical
from nafas_core.clients.consultation import get_consultation
from nafas_core.clients.conversation import get_conversation
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


def _session(appointment: dict, consultations: list[dict], history: list[dict], documents: list[dict]) -> dict:
    """
    One visit as the doctor reads it: the approved note's summary (and the
    patient's, when there is one), each recording with its transcript, the
    documents, and every other entry as a note.
    """
    aid = appointment["appointment_id"]
    recordings = [c for c in consultations if c.get("appointment_id") == aid and c["status"] != "discarded"]
    belongs = _belongs(aid, {c["consultation_id"] for c in recordings})
    entries = [e for e in history if belongs(e)]

    summaries = [e for e in entries if e["kind"] == "visit_summary"]
    # the approved note carries its SOAP sections; the plain-language one is what the patient was given
    doctor_summary = next((e for e in summaries if "subjective" in (e.get("structured") or {})), None)
    patient_summary = next((e for e in summaries if e is not doctor_summary), None)
    transcripts = {e.get("source_id"): e for e in entries if e["kind"] == "visit_transcript"}
    notes = [e for e in entries if e["kind"] not in ("visit_summary", "visit_transcript")]
    files = [d for d in documents if d.get("appointment_id") == aid]

    return {
        "appointment": appointment,
        "summary": {"note": doctor_summary, "patient": patient_summary},
        "recordings": [c | {"transcript": transcripts.get(c["consultation_id"])} for c in recordings],
        "documents": files,
        "notes": notes,
        "counts": {"recordings": len(recordings), "documents": len(files), "notes": len(notes) + len(summaries)},
    }


def _general(sessions: list[dict], history: list[dict], documents: list[dict]) -> dict:
    """What was filed in the patient's record outside any visit."""
    in_sessions = set()
    for s in sessions:
        in_sessions |= {d["document_id"] for d in s["documents"]}
        in_sessions |= {e["entry_id"] for e in s["notes"]}
        in_sessions |= {e["entry_id"] for e in (s["summary"]["note"], s["summary"]["patient"]) if e}
        in_sessions |= {r["transcript"]["entry_id"] for r in s["recordings"] if r["transcript"]}
    return {
        "notes": [e for e in history if e["entry_id"] not in in_sessions],
        "documents": [d for d in documents if d["document_id"] not in in_sessions],
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
    """The patient's file by session, newest first; what belongs to none; the questions still open."""
    card = await _patient_of(doctor, patient_id)
    zone = (await get_scheduling().booking_info(doctor.doctor_id))["timezone"]
    appointments = await get_scheduling().doctor_patient_appointments(doctor.doctor_id, patient_id)
    consultations, history, documents = await _record(doctor.doctor_id, patient_id)
    sessions = [
        _session(a, consultations, history, documents) for a in sorted(appointments, key=lambda a: a["start"], reverse=True)
    ]
    questions = await get_conversation().escalations(doctor.doctor_id, ["open"], patient_id)
    return {
        "patient": card,
        "timezone": zone,
        "sessions": sessions,
        "general": _general(sessions, history, documents),
        "questions": questions,
    }


@router.get("/patients/{patient_id}/visits/{appointment_id}")
async def visit(patient_id: uuid.UUID, appointment_id: uuid.UUID, doctor: Account = Depends(current_doctor)) -> dict:
    card = await _patient_of(doctor, patient_id)
    appointment = await visit_of(doctor.doctor_id, patient_id, appointment_id)
    zone = (await get_scheduling().booking_info(doctor.doctor_id))["timezone"]
    consultations, history, documents = await _record(doctor.doctor_id, patient_id)
    return {"patient": card, "timezone": zone, "session": _session(appointment, consultations, history, documents)}

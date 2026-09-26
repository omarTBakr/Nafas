"""One patient's timeline with one doctor, put together from the services that hold its parts."""

import uuid
from datetime import datetime

ALL_ESCALATIONS = ["open", "answered", "closed", "expired"]


async def timeline_items(
    doctor_id: uuid.UUID, patient_id: uuid.UUID, *, scheduling, clinical, conversation, consultation=None
) -> list[dict]:
    """
    Appointments, history entries, documents and escalated questions, newest
    first; recorded visits too when `consultation` is given. The doctor's
    dashboard gives it; the doctor assistant does not, because a draft is not
    the record: what a visit adds to the record arrives as history entries
    once the doctor approves it. Each service audits its read.
    """
    appointments = await scheduling.doctor_patient_appointments(doctor_id, patient_id)
    history = await clinical.history(doctor_id, patient_id)
    documents = await clinical.documents(doctor_id, patient_id)
    escalations = await conversation.escalations(doctor_id, ALL_ESCALATIONS, patient_id)
    items = (
        [{"type": "appointment", "at": a["start"], **a} for a in appointments]
        + [{"type": "history", "at": e["occurred_at"], **e} for e in history]
        + [{"type": "document", "at": d["created_at"], **d} for d in documents]
        + [{"type": "escalation", "at": e["created_at"], **e} for e in escalations]
    )
    if consultation is not None:
        visits = await consultation.for_patient(doctor_id, patient_id)
        items += [{"type": "consultation", "at": c["started_at"], **c} for c in visits if c["status"] != "discarded"]
    return sorted(items, key=lambda item: datetime.fromisoformat(item["at"]), reverse=True)

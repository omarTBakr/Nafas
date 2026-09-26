"""One patient's timeline with one doctor, put together from the services that hold its parts."""

import uuid
from datetime import datetime

ALL_ESCALATIONS = ["open", "answered", "closed", "expired"]


async def timeline_items(doctor_id: uuid.UUID, patient_id: uuid.UUID, *, scheduling, clinical, conversation) -> list[dict]:
    """Appointments, history entries, documents and escalated questions, newest first. Each service audits its read."""
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
    return sorted(items, key=lambda item: datetime.fromisoformat(item["at"]), reverse=True)

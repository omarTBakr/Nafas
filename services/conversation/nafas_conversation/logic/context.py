"""
What the assistant may know about a patient when answering them: only what
the patient may see (docs/PLAN.md §2, patient-visible retrieval).

A port with one source today, the patient's own appointments with this
doctor. Phase 6 adds the patient-visible part of their clinical record
(approved summaries, documents the doctor shared) behind the same call.
"""

import uuid
from datetime import datetime
from typing import Protocol
from zoneinfo import ZoneInfo

from nafas_core.clients.scheduling import SchedulingClient

ACTIVE = ("confirmed", "completed")


class PatientContext(Protocol):
    async def for_patient(self, patient_id: uuid.UUID, doctor_id: uuid.UUID, question: str) -> list[str]:
        """Short facts the patient may see, relevant to the question; never another patient's."""
        ...


class AppointmentsContext:
    def __init__(self, scheduling: SchedulingClient):
        self._scheduling = scheduling

    async def visits(self, patient_id: uuid.UUID, doctor_id: uuid.UUID) -> list[dict]:
        mine = await self._scheduling.patient_appointments(patient_id)
        return [a for a in mine if a["doctor_id"] == str(doctor_id) and a["status"] in ACTIVE]

    async def for_patient(self, patient_id: uuid.UUID, doctor_id: uuid.UUID, question: str) -> list[str]:
        zone = ZoneInfo((await self._scheduling.booking_info(doctor_id))["timezone"])
        facts = []
        for visit in await self.visits(patient_id, doctor_id):
            when = datetime.fromisoformat(visit["start"]).astimezone(zone).strftime("%A %d %B %Y, %H:%M")
            facts.append(f"{visit['status'].capitalize()} appointment with this doctor: {when} (clinic time).")
        return facts

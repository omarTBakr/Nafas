"""
What the assistant may know about a patient when answering them: only what
the patient may see (docs/PLAN.md §2, patient-visible retrieval).

Two sources: the patient's own appointments with this doctor, and the part
of their clinical record the doctor shared (notes, approved summaries,
documents), searched in the patient's scope so nothing else can come back.
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


# enough to ground a short answer without drowning it
PASSAGES = 4


class ClinicalContext:
    """The visits, then the shared passages of the record that best match the question."""

    def __init__(self, scheduling: SchedulingClient, clinical):
        self._appointments = AppointmentsContext(scheduling)
        self._clinical = clinical

    async def visits(self, patient_id: uuid.UUID, doctor_id: uuid.UUID) -> list[dict]:
        return await self._appointments.visits(patient_id, doctor_id)

    async def for_patient(self, patient_id: uuid.UUID, doctor_id: uuid.UUID, question: str) -> list[str]:
        facts = await self._appointments.for_patient(patient_id, doctor_id, question)
        passages = await self._clinical.search(patient_id, doctor_id, question, audience="patient", k=PASSAGES)
        for passage in passages:
            source = passage["details"].get("filename") or passage["details"].get("kind") or "record"
            facts.append(f"From the patient's record ({source}): {passage['content']}")
        return facts

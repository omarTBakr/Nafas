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

from nafas_conversation.prompts import web as web_prompt
from nafas_core.clients.scheduling import SchedulingClient
from nafas_core.exceptions.providers import LLMError, SearchError
from nafas_core.tracing import step

ACTIVE = ("confirmed", "completed")


class PatientContext(Protocol):
    @step("conversation.context", run_type="retriever")
    async def for_patient(self, patient_id: uuid.UUID, doctor_id: uuid.UUID, question: str) -> list[str]:
        """Short facts the patient may see, relevant to the question; never another patient's."""
        ...


class AppointmentsContext:
    def __init__(self, scheduling: SchedulingClient):
        self._scheduling = scheduling

    async def visits(self, patient_id: uuid.UUID, doctor_id: uuid.UUID) -> list[dict]:
        mine = await self._scheduling.patient_appointments(patient_id)
        return [a for a in mine if a["doctor_id"] == str(doctor_id) and a["status"] in ACTIVE]

    @step("conversation.context", run_type="retriever")
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

    @step("conversation.context", run_type="retriever")
    async def for_patient(self, patient_id: uuid.UUID, doctor_id: uuid.UUID, question: str) -> list[str]:
        facts = await self._appointments.for_patient(patient_id, doctor_id, question)
        passages = await self._clinical.search(patient_id, doctor_id, question, audience="patient", k=PASSAGES)
        for passage in passages:
            source = passage["details"].get("filename") or passage["details"].get("kind") or "record"
            facts.append(f"From the patient's record ({source}): {passage['content']}")
        return facts


# a query is short; anything longer is likely the question pasted back, details and all
MAX_QUERY_WORDS = 16
WEB_RESULTS = 3


async def general_query(llm, model: str, question: str) -> str | None:
    """The general topic of the question, as a search query with nothing of the patient in it; None for none."""
    try:
        response = await llm.create(
            model=model,
            system=web_prompt.SYSTEM,
            tools=[web_prompt.TOOL],
            tool_choice={"type": "tool", "name": web_prompt.TOOL["name"]},
            messages=[{"role": "user", "content": question}],
            max_tokens=64,
        )
    except LLMError:
        return None
    query = next((b.input.get("query") for b in response.content if b.type == "tool_use"), None)
    if not isinstance(query, str) or not query.strip() or len(query.split()) > MAX_QUERY_WORDS:
        return None
    return query.strip()


class WebGroundedContext:
    """
    What the record says, then what trusted medical sites say about the
    question in general. Only for general answers, after every gate: the
    output guard still reads the draft. The search query is a de-identified
    rewrite of the question; the question itself never leaves.
    """

    def __init__(self, inner, web, llm, model: str, domains: list[str]):
        self._inner, self._web, self._llm, self._model, self._domains = inner, web, llm, model, domains

    async def visits(self, patient_id: uuid.UUID, doctor_id: uuid.UUID) -> list[dict]:
        return await self._inner.visits(patient_id, doctor_id)

    @step("conversation.web_context", run_type="retriever")
    async def for_patient(self, patient_id: uuid.UUID, doctor_id: uuid.UUID, question: str) -> list[str]:
        facts = await self._inner.for_patient(patient_id, doctor_id, question)
        query = await general_query(self._llm, self._model, question)
        if query is None:
            return facts
        try:
            found = await self._web.search(query, max_results=WEB_RESULTS, domains=self._domains)
        except SearchError:
            return facts
        return facts + [f"General information from {r.title} ({r.url}): {r.content}" for r in found]

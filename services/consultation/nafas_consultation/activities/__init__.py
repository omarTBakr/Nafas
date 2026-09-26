"""
The consultation activities: transcribing the parts, drafting the note,
filing the approved note, throwing a recording away. Each is idempotent (a
retry redoes the same step to the same result), so each may be retried.
The words stay in the database: nothing but ids crosses Temporal.
"""

import uuid

from pydantic import ValidationError
from temporalio import activity
from temporalio.exceptions import ApplicationError

from nafas_consultation.enums import ConsultationStatus
from nafas_consultation.logic import consultations, transcript
from nafas_consultation.logic.note import Note, entries
from nafas_consultation.prompts import soap
from nafas_consultation.schemas import ConsultationRef, Failure
from nafas_core.db import session_scope
from nafas_core.interfaces.llm import LLM
from nafas_core.interfaces.storage.base import Storage
from nafas_core.interfaces.stt.base import STT
from nafas_core.logger import get_logger
from nafas_core.metrics import VISIT_NOTES, WORKFLOW_FAILURES

logger = get_logger(__name__)


class ConsultationActivities:
    def __init__(self, storage: Storage, stt: STT, llm: LLM, identity, clinical, summary_model: str):
        self._storage, self._stt, self._llm = storage, stt, llm
        self._identity, self._clinical = identity, clinical
        self._model = summary_model

    @staticmethod
    def _ids(ref: ConsultationRef) -> tuple[uuid.UUID, uuid.UUID]:
        return uuid.UUID(ref.doctor_id), uuid.UUID(ref.consultation_id)

    @activity.defn(name="consultation.transcribe")
    async def transcribe(self, ref: ConsultationRef) -> int:
        """Every part, in order and in visit time; returns how many segments were heard."""
        doctor_id, consultation_id = self._ids(ref)
        async with session_scope(doctor_id=doctor_id) as session:
            consultation = await consultations.get(session, consultation_id)
            parts = list(consultation.parts)

        segments: list[dict] = []
        for i, part in enumerate(parts):
            activity.heartbeat(i)
            heard = await self._stt.transcribe(await self._storage.get(part["key"]), part["mime"])
            following = parts[i + 1]["offset_seconds"] if i + 1 < len(parts) else None
            segments += transcript.place(heard, part["offset_seconds"], following)

        async with session_scope(doctor_id=doctor_id) as session:
            consultation = await consultations.get(session, consultation_id)
            consultation.transcript = segments
            consultations.mark(consultation, ConsultationStatus.SUMMARIZING)
        return len(segments)

    @activity.defn(name="consultation.draft")
    async def draft(self, ref: ConsultationRef) -> None:
        """The model's note from the transcript: status draft_ready, for the doctor to review."""
        doctor_id, consultation_id = self._ids(ref)
        async with session_scope(doctor_id=doctor_id) as session:
            consultation = await consultations.get(session, consultation_id)
            segments, patient_id = consultation.transcript or [], consultation.patient_id
        if not segments:
            raise ApplicationError("nothing could be heard in the recording", non_retryable=True)

        language = (await self._identity.profile(patient_id)).get("preferred_language") or "ar"
        response = await self._llm.create(
            model=self._model,
            system=soap.system(language),
            tools=[soap.TOOL],
            tool_choice={"type": "tool", "name": soap.TOOL["name"]},
            messages=[{"role": "user", "content": f"Transcript of the visit:\n\n{transcript.for_prompt(segments)}"}],
            max_tokens=4000,
        )
        raw = next((b.input for b in response.content if b.type == "tool_use" and b.name == soap.TOOL["name"]), None)
        try:
            note = Note.model_validate(raw)
        except ValidationError as exc:
            # a malformed call is worth one more try; the retry policy bounds it
            raise ApplicationError(f"the summary model gave no usable note: {exc.error_count()} problems") from exc

        async with session_scope(doctor_id=doctor_id) as session:
            consultation = await consultations.get(session, consultation_id)
            consultation.draft = note.model_dump()
            consultation.model, consultation.prompt_version = self._model, soap.PROMPT_VERSION
            consultations.mark(consultation, ConsultationStatus.DRAFT_READY)

    @activity.defn(name="consultation.file")
    async def file(self, ref: ConsultationRef) -> int:
        """The approved note into the patient's record; entries named by the consultation, so a retry adds nothing."""
        doctor_id, consultation_id = self._ids(ref)
        async with session_scope(doctor_id=doctor_id) as session:
            consultation = await consultations.get(session, consultation_id)
            note, share = Note.model_validate(consultation.approved), consultation.share_with_patient
            patient_id = consultation.patient_id
            occurred = consultation.started_at.isoformat()

        bodies = entries(consultation_id, note, share)
        for body in bodies:
            await self._clinical.add_entry(doctor_id, patient_id, body | {"occurred_at": occurred, "author_id": None})

        async with session_scope(doctor_id=doctor_id) as session:
            consultations.mark(await consultations.get(session, consultation_id), ConsultationStatus.APPROVED)
        return len(bodies)

    @activity.defn(name="consultation.discard")
    async def discard(self, ref: ConsultationRef) -> None:
        doctor_id, consultation_id = self._ids(ref)
        async with session_scope(doctor_id=doctor_id) as session:
            keys = consultations.forget(await consultations.get(session, consultation_id))
        for key in keys:
            await self._storage.delete(key)

    @activity.defn(name="consultation.mark_failed")
    async def mark_failed(self, failure: Failure) -> None:
        async with session_scope(doctor_id=uuid.UUID(failure.doctor_id)) as session:
            consultation = await consultations.get(session, uuid.UUID(failure.consultation_id))
            if consultation.status is not ConsultationStatus.DISCARDED:
                consultations.mark(consultation, ConsultationStatus.FAILED, failure.error[:500])
                VISIT_NOTES.labels("failed").inc()
                WORKFLOW_FAILURES.labels("consultation").inc()

    def all(self) -> list:
        return [self.transcribe, self.draft, self.file, self.discard, self.mark_failed]

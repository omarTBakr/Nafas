"""
The consultation internal API, behind the internal token. Everything is in
the doctor's scope and for patients under their care. Recording starts with
the patient's consent, recorded with identity for this recording alone;
nothing reaches the patient's record until the doctor approves the note.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from nafas_consultation import online_api
from nafas_consultation.enums import DISCARDABLE, ConsultationStatus
from nafas_consultation.events import get_events
from nafas_consultation.exceptions import ConsultationNotFoundError, JoinRefusedError, NotUnderCareError, WrongStateError
from nafas_consultation.logic import consultations
from nafas_consultation.logic.note import Note
from nafas_consultation.models import Consultation
from nafas_consultation.prompts import soap
from nafas_core import audit
from nafas_core.clients.base import UpstreamRefusal
from nafas_core.clients.identity import get_identity
from nafas_core.db import session_scope
from nafas_core.exceptions.providers import StorageError
from nafas_core.health import health_info
from nafas_core.interfaces.storage.factory import get_storage
from nafas_core.internal_api import require_internal_token
from nafas_core.metrics import VISIT_NOTES, instrument

UPLOAD_LINK_SECONDS = 600


class NewConsultation(BaseModel):
    # how the patient agreed, as the doctor confirms it: "verbal, in the room"
    evidence: str = Field(min_length=1, max_length=200)
    appointment_id: uuid.UUID | None = None


class NewPart(BaseModel):
    index: int = Field(ge=0)
    mime: str = Field(min_length=1, max_length=100)
    offset_seconds: float = Field(ge=0)
    size_bytes: int = Field(gt=0)


class Approval(BaseModel):
    note: Note
    share_with_patient: bool = False


class ConsultationOut(BaseModel):
    consultation_id: uuid.UUID
    patient_id: uuid.UUID
    appointment_id: uuid.UUID | None
    status: ConsultationStatus
    error: str | None
    part_count: int
    source: str = "in_person"
    recording: bool = False
    share_with_patient: bool
    started_at: datetime
    approved_at: datetime | None
    created_at: datetime


class ConsultationDetail(ConsultationOut):
    transcript: list[dict] | None
    draft: Note | None
    approved: Note | None
    model: str | None
    prompt_version: str | None


def _out(c: Consultation) -> ConsultationOut:
    return ConsultationOut(
        consultation_id=c.id,
        patient_id=c.patient_id,
        appointment_id=c.appointment_id,
        status=c.status,
        error=c.error,
        part_count=len(c.parts),
        source=c.source,
        recording=c.status is ConsultationStatus.RECORDING and c.source == "online" and c.recording_stopped_at is None,
        share_with_patient=c.share_with_patient,
        started_at=c.started_at,
        approved_at=c.approved_at,
        created_at=c.created_at,
    )


def _detail(c: Consultation) -> ConsultationDetail:
    return ConsultationDetail(
        **_out(c).model_dump(),
        transcript=c.transcript,
        draft=Note.model_validate(c.draft) if c.draft else None,
        approved=Note.model_validate(c.approved) if c.approved else None,
        model=c.model,
        prompt_version=c.prompt_version,
    )


async def _audit(doctor_id: uuid.UUID, action: str, c: Consultation, **detail) -> None:
    await audit.record(
        service="consultation",
        actor=audit.Actor.DOCTOR,
        actor_id=doctor_id,
        action=action,
        resource_type="consultation",
        resource_id=c.id,
        patient_id=c.patient_id,
        doctor_id=doctor_id,
        detail=detail,
    )


router = APIRouter(prefix="/internal/v1")


@router.post("/doctors/{doctor_id}/patients/{patient_id}/consultations", response_model=ConsultationOut, status_code=201)
async def start(doctor_id: uuid.UUID, patient_id: uuid.UUID, body: NewConsultation) -> ConsultationOut:
    """The patient agreed to this visit being recorded: record that consent, then the consultation it covers."""
    try:
        consent = await get_identity().record_recording_consent(doctor_id, patient_id, body.evidence)
    except UpstreamRefusal as exc:
        if exc.status_code == 409:
            raise NotUnderCareError(f"{patient_id} is not under {doctor_id}'s care") from exc
        raise
    async with session_scope(doctor_id=doctor_id) as session:
        consultation = await consultations.create(
            session,
            doctor_id=doctor_id,
            patient_id=patient_id,
            consent_id=uuid.UUID(consent["consent_id"]),
            appointment_id=body.appointment_id,
        )
        await _audit(doctor_id, "start_recording", consultation, consent_id=consent["consent_id"])
    return _out(consultation)


@router.post("/doctors/{doctor_id}/consultations/{consultation_id}/parts", status_code=201)
async def new_part(doctor_id: uuid.UUID, consultation_id: uuid.UUID, body: NewPart) -> dict:
    """A short-lived link the browser PUTs one recorded part to, straight to storage."""
    async with session_scope(doctor_id=doctor_id) as session:
        consultation = await consultations.get(session, consultation_id)
        try:
            part = await consultations.add_part(
                session,
                consultation,
                index=body.index,
                mime=body.mime,
                offset_seconds=body.offset_seconds,
                size_bytes=body.size_bytes,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    url = await get_storage().presigned_put_url(part["key"], part["mime"], UPLOAD_LINK_SECONDS)
    return {"index": part["index"], "upload_url": url, "content_type": part["mime"]}


@router.post("/doctors/{doctor_id}/consultations/{consultation_id}/finish", response_model=ConsultationOut)
async def finish(doctor_id: uuid.UUID, consultation_id: uuid.UUID) -> ConsultationOut:
    """Recording stopped and every part is uploaded: transcribe and draft. Also sends a failed one again."""
    async with session_scope(doctor_id=doctor_id) as session:
        consultation = await consultations.get(session, consultation_id)
        consultations.require(consultation, ConsultationStatus.RECORDING, ConsultationStatus.FAILED)
        keys = [p["key"] for p in consultation.parts]
    if not keys:
        raise HTTPException(status_code=409, detail="nothing was recorded")
    storage = get_storage()
    for key in keys:
        try:
            await storage.get(key)
        except StorageError as exc:
            raise HTTPException(status_code=409, detail="a part of the recording has not been uploaded yet") from exc

    return _out(await begin_processing(doctor_id, consultation_id))


async def begin_processing(doctor_id: uuid.UUID, consultation_id: uuid.UUID) -> Consultation:
    """Hands a recorded visit to its workflow: transcribe, draft, wait for the doctor. Shared by both kinds of visit."""
    async with session_scope(doctor_id=doctor_id) as session:
        consultation = await consultations.get(session, consultation_id)
        consultations.mark(consultation, ConsultationStatus.TRANSCRIBING)
    started = await get_events().finished(str(consultation_id), str(doctor_id))
    async with session_scope(doctor_id=doctor_id) as session:
        consultation = await consultations.get(session, consultation_id)
        if not started:
            consultations.mark(consultation, ConsultationStatus.FAILED, "could not start processing; try again")
    return consultation


@router.get("/doctors/{doctor_id}/consultations", response_model=list[ConsultationOut])
async def awaiting_review(doctor_id: uuid.UUID) -> list[ConsultationOut]:
    """Drafts waiting for this doctor, oldest first."""
    async with session_scope(doctor_id=doctor_id) as session:
        return [_out(c) for c in await consultations.awaiting_review(session)]


@router.get("/doctors/{doctor_id}/patients/{patient_id}/consultations", response_model=list[ConsultationOut])
async def for_patient(doctor_id: uuid.UUID, patient_id: uuid.UUID) -> list[ConsultationOut]:
    async with session_scope(doctor_id=doctor_id) as session:
        return [_out(c) for c in await consultations.for_patient(session, patient_id)]


@router.get("/doctors/{doctor_id}/consultations/{consultation_id}", response_model=ConsultationDetail)
async def detail(doctor_id: uuid.UUID, consultation_id: uuid.UUID) -> ConsultationDetail:
    async with session_scope(doctor_id=doctor_id) as session:
        consultation = await consultations.get(session, consultation_id)
    if consultation.transcript or consultation.draft:
        await _audit(doctor_id, "read_consultation", consultation)
    return _detail(consultation)


@router.post("/doctors/{doctor_id}/consultations/{consultation_id}/approve", response_model=ConsultationOut)
async def approve(doctor_id: uuid.UUID, consultation_id: uuid.UUID, body: Approval) -> ConsultationOut:
    """The doctor's version of the note, to be filed to the record; the patient's summary too if they chose to share it."""
    if body.note.is_empty():
        raise HTTPException(status_code=422, detail="an approved note needs at least one SOAP section")
    async with session_scope(doctor_id=doctor_id) as session:
        consultation = await consultations.get(session, consultation_id)
        consultations.require(consultation, ConsultationStatus.DRAFT_READY)
        consultation.approved = body.note.model_dump()
        consultation.share_with_patient = body.share_with_patient
        consultations.mark(consultation, ConsultationStatus.FILING)
        await _audit(
            doctor_id,
            "approve_note",
            consultation,
            shared=body.share_with_patient,
            edited=consultation.draft != consultation.approved,
        )
    VISIT_NOTES.labels("approved_edited" if consultation.draft != consultation.approved else "approved_as_drafted").inc()
    await get_events().approved(str(consultation_id))
    return _out(consultation)


@router.post("/doctors/{doctor_id}/consultations/{consultation_id}/discard", response_model=ConsultationOut)
async def discard(doctor_id: uuid.UUID, consultation_id: uuid.UUID) -> ConsultationOut:
    """Throw the recording away: its audio, transcript and draft. Not once it is filed."""
    async with session_scope(doctor_id=doctor_id) as session:
        consultation = await consultations.get(session, consultation_id)
        if consultation.status not in DISCARDABLE:
            raise WrongStateError(f"the consultation is {consultation.status.value}")
        # no workflow is running while recording or after a failure: throw it away here
        here = consultation.status in (ConsultationStatus.RECORDING, ConsultationStatus.FAILED)
        keys = consultations.forget(consultation) if here else []
        await _audit(doctor_id, "discard_recording", consultation)
    for key in keys:
        await get_storage().delete(key)
    if not here and not await get_events().discarded(str(consultation_id)):
        raise HTTPException(status_code=503, detail="could not reach the recording's workflow; try again")
    async with session_scope(doctor_id=doctor_id) as session:
        return _out(await consultations.get(session, consultation_id))


app = FastAPI(title="Nafas consultation (internal)")
instrument(app, "consultation")
app.include_router(router, dependencies=[Depends(require_internal_token)])
app.include_router(online_api.router)
app.include_router(online_api.webhooks)


@app.get("/health")
async def health() -> dict:
    return health_info("consultation", **{"prompts": {"soap": soap.PROMPT_VERSION}})


@app.exception_handler(ConsultationNotFoundError)
async def not_found(request: Request, exc: ConsultationNotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": "no such consultation"})


@app.exception_handler(JoinRefusedError)
async def join_refused(request: Request, exc: JoinRefusedError) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": str(exc), "reason": exc.reason})


@app.exception_handler(WrongStateError)
async def wrong_state(request: Request, exc: WrongStateError) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": str(exc), "reason": "wrong_state"})


@app.exception_handler(NotUnderCareError)
async def not_under_care(request: Request, exc: NotUnderCareError) -> JSONResponse:
    # 409, not 403: internal APIs keep 403 for a wrong internal token; the gateway shows this as 403
    return JSONResponse(status_code=409, content={"detail": "this patient is not under your care", "reason": "not_under_care"})

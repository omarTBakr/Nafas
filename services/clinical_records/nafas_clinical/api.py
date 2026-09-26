"""
The clinical-records internal API, behind the internal token. Doctors act
in their own scope, and only on patients under their care; a patient reads
in theirs, and sees only what their doctor shared. Every read of clinical
data is audited, including the model's (search on the patient's behalf).
"""

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import AwareDatetime, BaseModel, Field

from nafas_clinical.enums import DocumentKind, DocumentStatus, HistoryKind, SourceType, Visibility
from nafas_clinical.events import get_events
from nafas_clinical.exceptions import NotUnderCareError, RecordNotFoundError
from nafas_clinical.logic import records, search
from nafas_clinical.prompts import vision
from nafas_core import audit
from nafas_core.clients.identity import get_identity
from nafas_core.db import session_scope
from nafas_core.exceptions.providers import StorageError
from nafas_core.health import health_info
from nafas_core.interfaces.embeddings import get_embeddings
from nafas_core.interfaces.storage.factory import get_storage
from nafas_core.internal_api import require_internal_token
from nafas_core.metrics import instrument

UPLOAD_LINK_SECONDS = 600


class NewDocument(BaseModel):
    kind: DocumentKind = DocumentKind.OTHER
    filename: str = Field(min_length=1, max_length=255)
    mime: str
    size_bytes: int = Field(gt=0)


class DocumentOut(BaseModel):
    document_id: uuid.UUID
    patient_id: uuid.UUID
    doctor_id: uuid.UUID
    kind: DocumentKind
    filename: str
    mime: str
    size_bytes: int | None
    page_count: int | None
    status: DocumentStatus
    error: str | None
    visibility: Visibility
    # labelled wherever it is shown: a model's description, never a read
    ai_description: str | None
    ai_label: str = vision.LABEL
    created_at: datetime


class NewEntry(BaseModel):
    kind: HistoryKind = HistoryKind.NOTE
    content: str = Field(min_length=1, max_length=20000)
    visibility: Visibility = Visibility.DOCTOR_ONLY
    occurred_at: AwareDatetime | None = None
    author_id: uuid.UUID | None = None
    structured: dict = Field(default_factory=dict)
    # where it came from, when not the doctor's own hand: an approved consultation
    source_type: Literal["consultation"] | None = None
    source_id: uuid.UUID | None = None
    # named by a caller that may retry (a workflow): the same id gives back the same entry
    entry_id: uuid.UUID | None = None


class EntryOut(BaseModel):
    entry_id: uuid.UUID
    doctor_id: uuid.UUID
    kind: HistoryKind
    content: str
    visibility: Visibility
    source_type: str | None
    source_id: uuid.UUID | None = None
    structured: dict = Field(default_factory=dict)
    occurred_at: datetime


class VisibilityIn(BaseModel):
    visibility: Visibility


class SearchIn(BaseModel):
    patient_id: uuid.UUID
    doctor_id: uuid.UUID
    query: str = Field(min_length=1, max_length=2000)
    # who the search is for: the doctor sees everything of theirs, the patient what was shared
    audience: Literal["doctor", "patient"]
    k: int = Field(default=6, ge=1, le=20)


class PassageOut(BaseModel):
    source_type: SourceType
    source_id: uuid.UUID
    content: str
    visibility: Visibility
    details: dict
    score: float


def _document(d) -> DocumentOut:
    return DocumentOut(
        document_id=d.id,
        patient_id=d.patient_id,
        doctor_id=d.doctor_id,
        kind=d.kind,
        filename=d.filename,
        mime=d.mime,
        size_bytes=d.size_bytes,
        page_count=d.page_count,
        status=d.status,
        error=d.error,
        visibility=d.visibility,
        ai_description=d.ai_description,
        created_at=d.created_at,
    )


def _entry(e) -> EntryOut:
    return EntryOut(
        entry_id=e.id,
        doctor_id=e.doctor_id,
        kind=e.kind,
        content=e.content,
        visibility=e.visibility,
        source_type=e.source_type,
        source_id=e.source_id,
        structured=e.structured or {},
        occurred_at=e.occurred_at,
    )


async def _require_care(doctor_id: uuid.UUID, patient_id: uuid.UUID) -> None:
    if not await get_identity().under_care(patient_id, doctor_id):
        raise NotUnderCareError(f"{patient_id} is not under {doctor_id}'s care")


async def _read(actor: audit.Actor, actor_id, action: str, resource: str, resource_id, patient_id, doctor_id, **detail) -> None:
    await audit.record(
        service="clinical",
        actor=actor,
        actor_id=actor_id,
        action=action,
        resource_type=resource,
        resource_id=resource_id,
        patient_id=patient_id,
        doctor_id=doctor_id,
        detail=detail,
    )


router = APIRouter(prefix="/internal/v1")


@router.post("/doctors/{doctor_id}/patients/{patient_id}/documents", status_code=201)
async def new_document(doctor_id: uuid.UUID, patient_id: uuid.UUID, body: NewDocument) -> dict:
    """A document row and a short-lived link the browser PUTs the file to; then call /uploaded."""
    await _require_care(doctor_id, patient_id)
    try:
        async with session_scope(doctor_id=doctor_id) as session:
            document = await records.new_document(
                session,
                doctor_id=doctor_id,
                patient_id=patient_id,
                kind=body.kind,
                filename=body.filename,
                mime=body.mime,
                size_bytes=body.size_bytes,
                uploaded_by=doctor_id,
            )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    upload_url = await get_storage().presigned_put_url(document.object_key, body.mime, UPLOAD_LINK_SECONDS)
    return {"document": _document(document).model_dump(mode="json"), "upload_url": upload_url, "content_type": body.mime}


@router.post("/doctors/{doctor_id}/documents/{document_id}/uploaded", response_model=DocumentOut)
async def uploaded(doctor_id: uuid.UUID, document_id: uuid.UUID) -> DocumentOut:
    """The file is in storage: read, describe and index it. Also re-sends a failed document."""
    async with session_scope(doctor_id=doctor_id) as session:
        document = await records.get_document(session, document_id)
        key = document.object_key
    try:
        await get_storage().get(key)
    except StorageError as exc:
        raise HTTPException(status_code=409, detail="the file has not been uploaded yet") from exc
    async with session_scope(doctor_id=doctor_id) as session:
        await records.mark(session, document_id, DocumentStatus.UPLOADED)
        document = await records.get_document(session, document_id)
    await get_events().uploaded(str(document_id), str(doctor_id))
    return _document(document)


@router.get("/doctors/{doctor_id}/patients/{patient_id}/documents", response_model=list[DocumentOut])
async def doctor_documents(doctor_id: uuid.UUID, patient_id: uuid.UUID) -> list[DocumentOut]:
    async with session_scope(doctor_id=doctor_id) as session:
        found = await records.documents(session, patient_id)
    if found:
        await _read(
            audit.Actor.DOCTOR, doctor_id, "list_documents", "patient", patient_id, patient_id, doctor_id, count=len(found)
        )
    return [_document(d) for d in found]


@router.get("/doctors/{doctor_id}/documents/{document_id}/download")
async def download(doctor_id: uuid.UUID, document_id: uuid.UUID) -> dict:
    async with session_scope(doctor_id=doctor_id) as session:
        document = await records.get_document(session, document_id)
    await _read(audit.Actor.DOCTOR, doctor_id, "open_document", "document", document_id, document.patient_id, doctor_id)
    return {"url": await get_storage().presigned_get_url(document.object_key, expires_seconds=300)}


@router.get("/doctors/{doctor_id}/patients/{patient_id}/history", response_model=list[EntryOut])
async def doctor_history(doctor_id: uuid.UUID, patient_id: uuid.UUID) -> list[EntryOut]:
    async with session_scope(doctor_id=doctor_id) as session:
        found = await records.history(session, patient_id)
    if found:
        await _read(audit.Actor.DOCTOR, doctor_id, "read_history", "patient", patient_id, patient_id, doctor_id, count=len(found))
    return [_entry(e) for e in found]


@router.post("/doctors/{doctor_id}/patients/{patient_id}/history", response_model=EntryOut, status_code=201)
async def add_entry(doctor_id: uuid.UUID, patient_id: uuid.UUID, body: NewEntry) -> EntryOut:
    """A note, medication, allergy... in the patient's record, searchable at once."""
    await _require_care(doctor_id, patient_id)
    async with session_scope(doctor_id=doctor_id) as session:
        entry, new = await records.add_history(
            session,
            doctor_id=doctor_id,
            patient_id=patient_id,
            kind=body.kind,
            content=body.content,
            visibility=body.visibility,
            occurred_at=body.occurred_at,
            structured=body.structured,
            source_type=body.source_type,
            source_id=body.source_id,
            created_by=body.author_id,
            entry_id=body.entry_id,
        )
        if not new:
            return _entry(entry)
        details = {"kind": body.kind.value, "occurred_at": entry.occurred_at.isoformat()}
        if body.source_type:
            details |= {"source": body.source_type, "source_id": str(body.source_id)}
        await search.index(
            session,
            get_embeddings(),
            patient_id=patient_id,
            doctor_id=doctor_id,
            source_type=SourceType.HISTORY,
            source_id=entry.id,
            text=body.content,
            visibility=body.visibility,
            details=details,
        )
    return _entry(entry)


@router.patch("/doctors/{doctor_id}/records/{source_type}/{record_id}/visibility", status_code=204)
async def visibility(doctor_id: uuid.UUID, source_type: SourceType, record_id: uuid.UUID, body: VisibilityIn) -> None:
    if source_type is SourceType.CONSULTATION:
        raise HTTPException(status_code=422, detail="a consultation is shared through its approved summary")
    async with session_scope(doctor_id=doctor_id) as session:
        await records.set_visibility(session, source_type, record_id, body.visibility)


@router.post("/search", response_model=list[PassageOut])
async def search_record(body: SearchIn) -> list[PassageOut]:
    """
    Passages of one patient's record with one doctor. For the doctor: all of
    theirs. For the patient (the patient's assistant): only what was shared,
    which the patient's own scope enforces.
    """
    scope = {"doctor_id": body.doctor_id} if body.audience == "doctor" else {"patient_id": body.patient_id}
    async with session_scope(**scope) as session:
        found = await search.search(
            session, get_embeddings(), patient_id=body.patient_id, doctor_id=body.doctor_id, query=body.query, k=body.k
        )
    await _read(
        audit.Actor.MODEL,
        None,
        f"search_for_{body.audience}",
        "patient",
        body.patient_id,
        body.patient_id,
        body.doctor_id,
        hits=len(found),
    )
    return [
        PassageOut(
            source_type=p.source_type,
            source_id=p.source_id,
            content=p.content,
            visibility=p.visibility,
            details=p.details,
            score=p.score,
        )
        for p in found
    ]


@router.get("/patients/{patient_id}/history", response_model=list[EntryOut])
async def patient_history(patient_id: uuid.UUID) -> list[EntryOut]:
    """The entries doctors shared with the patient, in the patient's own scope: their "My records"."""
    async with session_scope(patient_id=patient_id) as session:
        found = await records.history(session, patient_id)
    if found:
        await _read(
            audit.Actor.PATIENT, patient_id, "read_own_history", "patient", patient_id, patient_id, None, count=len(found)
        )
    return [_entry(e) for e in found]


@router.get("/patients/{patient_id}/documents", response_model=list[DocumentOut])
async def patient_documents(patient_id: uuid.UUID, doctor_id: uuid.UUID | None = Query(default=None)) -> list[DocumentOut]:
    """What doctors shared with the patient, in the patient's own scope."""
    async with session_scope(patient_id=patient_id) as session:
        found = [d for d in await records.documents(session, patient_id) if doctor_id is None or d.doctor_id == doctor_id]
    return [_document(d) for d in found]


@router.get("/patients/{patient_id}/documents/{document_id}/download")
async def patient_download(patient_id: uuid.UUID, document_id: uuid.UUID) -> dict:
    """A shared document, opened by its patient; the patient's scope hides one that is not shared."""
    async with session_scope(patient_id=patient_id) as session:
        document = await records.get_document(session, document_id)
    await _read(audit.Actor.PATIENT, patient_id, "open_document", "document", document_id, patient_id, document.doctor_id)
    return {"url": await get_storage().presigned_get_url(document.object_key, expires_seconds=300)}


app = FastAPI(title="Nafas clinical records (internal)")
instrument(app, "clinical-records")
app.include_router(router, dependencies=[Depends(require_internal_token)])


@app.get("/health")
async def health() -> dict:
    return health_info("clinical-records", **{"prompts": {"vision": vision.PROMPT_VERSION}})


@app.exception_handler(RecordNotFoundError)
async def not_found(request: Request, exc: RecordNotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": "no such record"})


@app.exception_handler(NotUnderCareError)
async def not_under_care(request: Request, exc: NotUnderCareError) -> JSONResponse:
    # 409, not 403: internal APIs keep 403 for a wrong internal token; the gateway shows this as 403
    return JSONResponse(status_code=409, content={"detail": "this patient is not under your care", "reason": "not_under_care"})

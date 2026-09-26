"""
Documents and history entries, in the doctor's scope (row-level security
shows a doctor only their own), and the patient-visible part in the
patient's. Changing what a patient may see changes it on the chunks too, in
the same transaction, so search never lags behind the doctor's choice.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from nafas_clinical.enums import DocumentKind, DocumentStatus, HistoryKind, SourceType, Visibility
from nafas_clinical.exceptions import RecordNotFoundError
from nafas_clinical.models import Chunk, Document, HistoryEntry
from nafas_core.interfaces.storage.base import patient_key

MAX_UPLOAD_BYTES = 25_000_000
ACCEPTED_TYPES = {
    "application/pdf": "pdf",
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
    "image/tiff": "tiff",
    "text/plain": "txt",
}


def document_key(doctor_id: uuid.UUID, patient_id: uuid.UUID, document_id: uuid.UUID, mime: str) -> str:
    return patient_key(doctor_id, patient_id, "documents", f"{document_id}.{ACCEPTED_TYPES[mime]}")


async def new_document(
    session: AsyncSession,
    *,
    doctor_id: uuid.UUID,
    patient_id: uuid.UUID,
    kind: DocumentKind,
    filename: str,
    mime: str,
    size_bytes: int,
    uploaded_by: uuid.UUID | None,
) -> Document:
    """A row waiting for its file; the caller hands out an upload link to its key."""
    if mime not in ACCEPTED_TYPES:
        raise ValueError(f"{mime} is not a document type Nafas reads")
    if not 0 < size_bytes <= MAX_UPLOAD_BYTES:
        raise ValueError(f"a document must be between 1 byte and {MAX_UPLOAD_BYTES} bytes")
    document_id = uuid.uuid4()
    document = Document(
        id=document_id,
        doctor_id=doctor_id,
        patient_id=patient_id,
        kind=kind,
        filename=filename[:255],
        mime=mime,
        size_bytes=size_bytes,
        object_key=document_key(doctor_id, patient_id, document_id, mime),
        uploaded_by=uploaded_by,
    )
    session.add(document)
    await session.flush()
    return document


async def get_document(session: AsyncSession, document_id: uuid.UUID) -> Document:
    document = await session.get(Document, document_id)
    if document is None:
        raise RecordNotFoundError(str(document_id))
    return document


async def documents(session: AsyncSession, patient_id: uuid.UUID) -> list[Document]:
    """The patient's documents as the current scope sees them, newest first."""
    query = select(Document).where(Document.patient_id == patient_id).order_by(Document.created_at.desc())
    return list((await session.scalars(query)).all())


async def add_history(
    session: AsyncSession,
    *,
    doctor_id: uuid.UUID,
    patient_id: uuid.UUID,
    kind: HistoryKind,
    content: str,
    visibility: Visibility = Visibility.DOCTOR_ONLY,
    occurred_at: datetime | None = None,
    structured: dict | None = None,
    source_type: str | None = None,
    source_id: uuid.UUID | None = None,
    created_by: uuid.UUID | None = None,
    entry_id: uuid.UUID | None = None,
) -> tuple[HistoryEntry, bool]:
    """
    The entry, and whether it is new. A caller that names the id (a workflow
    filing a consultation) may call again after a retry and gets the same
    entry back rather than a second one.
    """
    if entry_id is not None and (existing := await session.get(HistoryEntry, entry_id)) is not None:
        return existing, False
    entry = HistoryEntry(
        id=entry_id or uuid.uuid4(),
        doctor_id=doctor_id,
        patient_id=patient_id,
        kind=kind,
        content=content,
        visibility=visibility,
        occurred_at=occurred_at or datetime.now(UTC),
        structured=structured or {},
        source_type=source_type,
        source_id=source_id,
        created_by=created_by,
    )
    session.add(entry)
    await session.flush()
    return entry, True


async def history(session: AsyncSession, patient_id: uuid.UUID) -> list[HistoryEntry]:
    query = select(HistoryEntry).where(HistoryEntry.patient_id == patient_id).order_by(HistoryEntry.occurred_at.desc())
    return list((await session.scalars(query)).all())


async def set_visibility(session: AsyncSession, source_type: SourceType, source_id: uuid.UUID, visibility: Visibility) -> None:
    """What the patient may see of one document or entry, and of every passage searched from it."""
    model = Document if source_type is SourceType.DOCUMENT else HistoryEntry
    result = await session.execute(update(model).where(model.id == source_id).values(visibility=visibility).returning(model.id))
    if result.first() is None:
        raise RecordNotFoundError(str(source_id))
    await session.execute(
        update(Chunk).where(Chunk.source_type == source_type, Chunk.source_id == source_id).values(visibility=visibility)
    )


async def mark(session: AsyncSession, document_id: uuid.UUID, status: DocumentStatus, error: str | None = None) -> None:
    await session.execute(update(Document).where(Document.id == document_id).values(status=status, error=error))

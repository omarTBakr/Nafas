"""The `clinical` schema. Every row carries its doctor and patient; row-level security reads both."""

import uuid
from datetime import UTC, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, Computed, DateTime, Index, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import ENUM, JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column

from nafas_clinical.enums import DocumentKind, DocumentStatus, HistoryKind, SourceType, Visibility
from nafas_core.db import Base
from nafas_core.interfaces.embeddings import EMBEDDING_DIMENSIONS

SCHEMA = "clinical"


def _enum(enum_cls, name: str) -> ENUM:
    return ENUM(enum_cls, name=name, schema=SCHEMA, values_callable=lambda e: [m.value for m in e], create_type=False)


def _now() -> datetime:
    return datetime.now(UTC)


def _visibility() -> Mapped[Visibility]:
    return mapped_column(_enum(Visibility, "visibility"), default=Visibility.DOCTOR_ONLY, server_default="doctor_only")


class HistoryEntry(Base):
    """One fact in a patient's record with a doctor: a note, a visit summary, a medication, an allergy."""

    __tablename__ = "history_entries"
    __table_args__ = (Index("ix_history_patient_doctor_occurred", "patient_id", "doctor_id", "occurred_at"), {"schema": SCHEMA})

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    doctor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    kind: Mapped[HistoryKind] = mapped_column(_enum(HistoryKind, "history_kind"))
    content: Mapped[str] = mapped_column(Text)
    structured: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    # where it came from: a consultation's approved summary, a document, the doctor by hand
    source_type: Mapped[str | None] = mapped_column(String(32))
    source_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    visibility: Mapped[Visibility] = _visibility()
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, server_default=func.now())
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, server_default=func.now())


class Document(Base):
    """An uploaded report, scan or image, and what was read from it."""

    __tablename__ = "documents"
    __table_args__ = (Index("ix_documents_patient_doctor_created", "patient_id", "doctor_id", "created_at"), {"schema": SCHEMA})

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    doctor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    kind: Mapped[DocumentKind] = mapped_column(_enum(DocumentKind, "document_kind"))
    filename: Mapped[str] = mapped_column(String(255))
    object_key: Mapped[str] = mapped_column(Text)
    mime: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    sha256: Mapped[str | None] = mapped_column(String(64))
    page_count: Mapped[int | None] = mapped_column(Integer)
    extracted_text: Mapped[str | None] = mapped_column(Text)
    # a model's description of an image: labelled as such everywhere it is shown, never a read
    ai_description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[DocumentStatus] = mapped_column(
        _enum(DocumentStatus, "document_status"), default=DocumentStatus.AWAITING_UPLOAD, server_default="awaiting_upload"
    )
    error: Mapped[str | None] = mapped_column(Text)
    visibility: Mapped[Visibility] = _visibility()
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, server_default=func.now())


class Chunk(Base):
    """A searchable passage of a history entry or document, with its embedding and its words."""

    __tablename__ = "chunks"
    __table_args__ = (
        Index("ix_chunks_patient_doctor", "patient_id", "doctor_id"),
        Index("ix_chunks_source", "source_type", "source_id"),
        Index(
            "ix_chunks_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        Index("ix_chunks_tsv", "tsv", postgresql_using="gin"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    doctor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    source_type: Mapped[SourceType] = mapped_column(_enum(SourceType, "source_type"))
    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    position: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSIONS))
    # 'simple': Postgres has no Arabic stemmer, and exact words still find names, drugs and numbers
    tsv: Mapped[str] = mapped_column(TSVECTOR, Computed("to_tsvector('simple', content)", persisted=True))
    visibility: Mapped[Visibility] = _visibility()
    # what the passage came from, for the answer to cite: a filename and page, an entry's kind and date
    details: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, server_default=func.now())

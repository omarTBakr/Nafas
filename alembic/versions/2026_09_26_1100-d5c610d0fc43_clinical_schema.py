"""The clinical-records service's schema: history entries, documents, and the chunks they are searched through.

Every row names its doctor and patient. A doctor reads and writes their own
rows; a patient reads only rows their doctor marked patient_visible, so a
search in the patient's scope cannot surface a doctor-only note. chunks
holds bge-m3 embeddings (HNSW, cosine) beside a 'simple' tsvector for the
exact words the vectors blur: names, drugs, numbers.

Revision ID: d5c610d0fc43
Revises: c4d8e2f1a7b5
Create Date: 2026-09-26 11:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

from nafas_core.db.migration_ops import (
    create_service_schema,
    drop_service_schema,
    enable_doctor_isolation,
)
from nafas_core.interfaces.embeddings import EMBEDDING_DIMENSIONS

ENUMS = {
    "visibility": ("doctor_only", "patient_visible"),
    "history_kind": ("visit_summary", "diagnosis", "medication", "allergy", "lab_result", "procedure", "note", "intake"),
    "document_kind": ("report", "xray", "ct", "mri", "ultrasound", "lab", "prescription", "other"),
    "document_status": ("awaiting_upload", "uploaded", "processing", "indexed", "failed"),
    "source_type": ("history", "document", "consultation"),
}
TABLES = ("history_entries", "documents", "chunks")
PATIENT_VISIBLE = "patient_id = nafas_current_patient() AND visibility = 'patient_visible'"

# revision identifiers, used by Alembic.
revision: str = "d5c610d0fc43"
down_revision: str | Sequence[str] | None = "c4d8e2f1a7b5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    create_service_schema("clinical")
    for name, values in ENUMS.items():
        postgresql.ENUM(*values, name=name, schema="clinical").create(op.get_bind())

    op.create_table(
        "chunks",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("patient_id", sa.UUID(), nullable=False),
        sa.Column("doctor_id", sa.UUID(), nullable=False),
        sa.Column(
            "source_type",
            postgresql.ENUM("history", "document", "consultation", name="source_type", create_type=False, schema="clinical"),
            nullable=False,
        ),
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column("position", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(EMBEDDING_DIMENSIONS), nullable=False),
        sa.Column("tsv", postgresql.TSVECTOR(), sa.Computed("to_tsvector('simple', content)", persisted=True), nullable=False),
        sa.Column(
            "visibility",
            postgresql.ENUM("doctor_only", "patient_visible", name="visibility", create_type=False, schema="clinical"),
            server_default="doctor_only",
            nullable=False,
        ),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chunks")),
        schema="clinical",
    )
    op.create_index(
        "ix_chunks_embedding",
        "chunks",
        ["embedding"],
        unique=False,
        schema="clinical",
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_index("ix_chunks_patient_doctor", "chunks", ["patient_id", "doctor_id"], unique=False, schema="clinical")
    op.create_index("ix_chunks_source", "chunks", ["source_type", "source_id"], unique=False, schema="clinical")
    op.create_index("ix_chunks_tsv", "chunks", ["tsv"], unique=False, schema="clinical", postgresql_using="gin")
    op.create_table(
        "documents",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("patient_id", sa.UUID(), nullable=False),
        sa.Column("doctor_id", sa.UUID(), nullable=False),
        sa.Column(
            "kind",
            postgresql.ENUM(
                "report",
                "xray",
                "ct",
                "mri",
                "ultrasound",
                "lab",
                "prescription",
                "other",
                name="document_kind",
                create_type=False,
                schema="clinical",
            ),
            nullable=False,
        ),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column("mime", sa.String(length=100), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("extracted_text", sa.Text(), nullable=True),
        sa.Column("ai_description", sa.Text(), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(
                "awaiting_upload",
                "uploaded",
                "processing",
                "indexed",
                "failed",
                name="document_status",
                create_type=False,
                schema="clinical",
            ),
            server_default="awaiting_upload",
            nullable=False,
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "visibility",
            postgresql.ENUM("doctor_only", "patient_visible", name="visibility", create_type=False, schema="clinical"),
            server_default="doctor_only",
            nullable=False,
        ),
        sa.Column("uploaded_by", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_documents")),
        schema="clinical",
    )
    op.create_index(
        "ix_documents_patient_doctor_created",
        "documents",
        ["patient_id", "doctor_id", "created_at"],
        unique=False,
        schema="clinical",
    )
    op.create_table(
        "history_entries",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("patient_id", sa.UUID(), nullable=False),
        sa.Column("doctor_id", sa.UUID(), nullable=False),
        sa.Column(
            "kind",
            postgresql.ENUM(
                "visit_summary",
                "diagnosis",
                "medication",
                "allergy",
                "lab_result",
                "procedure",
                "note",
                "intake",
                name="history_kind",
                create_type=False,
                schema="clinical",
            ),
            nullable=False,
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("structured", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=True),
        sa.Column("source_id", sa.UUID(), nullable=True),
        sa.Column(
            "visibility",
            postgresql.ENUM("doctor_only", "patient_visible", name="visibility", create_type=False, schema="clinical"),
            server_default="doctor_only",
            nullable=False,
        ),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_history_entries")),
        schema="clinical",
    )
    op.create_index(
        "ix_history_patient_doctor_occurred",
        "history_entries",
        ["patient_id", "doctor_id", "occurred_at"],
        unique=False,
        schema="clinical",
    )

    for table in TABLES:
        # references into identity: in the database, not on the ORM models
        for column, target in (("doctor_id", "doctors"), ("patient_id", "patients")):
            op.create_foreign_key(
                f"fk_{table}_{column}_{target}",
                table,
                target,
                [column],
                ["id"],
                source_schema="clinical",
                referent_schema="identity",
            )
        enable_doctor_isolation(f"clinical.{table}")
        # the patient reads what the doctor shared with them, and nothing else
        op.execute(f"CREATE POLICY patient_visible_reads ON clinical.{table} FOR SELECT TO nafas_app USING ({PATIENT_VISIBLE})")


def downgrade() -> None:
    drop_service_schema("clinical")

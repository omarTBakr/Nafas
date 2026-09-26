"""The consultation service's schema: one row per recorded visit.

The doctor's own: row-level security shows and lets a doctor change only
their rows. Patients never read this table; what they may see of a visit is
the summary their doctor approved and shared, which lives in clinical.
Each row names the identity consent recorded for that recording alone.

Revision ID: e7a3b9c1d2f4
Revises: d5c610d0fc43
Create Date: 2026-09-26 13:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from nafas_core.db.migration_ops import create_service_schema, drop_service_schema, enable_doctor_isolation

STATUSES = ("recording", "transcribing", "summarizing", "draft_ready", "filing", "approved", "discarded", "failed")

# revision identifiers, used by Alembic.
revision: str = "e7a3b9c1d2f4"
down_revision: str | Sequence[str] | None = "d5c610d0fc43"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    create_service_schema("consultation")
    postgresql.ENUM(*STATUSES, name="consultation_status", schema="consultation").create(op.get_bind())
    op.create_table(
        "consultations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("doctor_id", sa.UUID(), nullable=False),
        sa.Column("patient_id", sa.UUID(), nullable=False),
        sa.Column("appointment_id", sa.UUID(), nullable=True),
        sa.Column("consent_id", sa.UUID(), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(*STATUSES, name="consultation_status", create_type=False, schema="consultation"),
            server_default="recording",
            nullable=False,
        ),
        sa.Column("parts", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("transcript", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("draft", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("approved", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("share_with_patient", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=True),
        sa.Column("prompt_version", sa.String(length=40), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_consultations")),
        schema="consultation",
    )
    op.create_index(
        "ix_consultations_doctor_patient_created",
        "consultations",
        ["doctor_id", "patient_id", "created_at"],
        unique=False,
        schema="consultation",
    )
    # references into identity: in the database, not on the ORM model
    for column, target in (("doctor_id", "doctors"), ("patient_id", "patients"), ("consent_id", "consents")):
        op.create_foreign_key(
            f"fk_consultations_{column}_{target}",
            "consultations",
            target,
            [column],
            ["id"],
            source_schema="consultation",
            referent_schema="identity",
        )
    enable_doctor_isolation("consultation.consultations")


def downgrade() -> None:
    drop_service_schema("consultation")

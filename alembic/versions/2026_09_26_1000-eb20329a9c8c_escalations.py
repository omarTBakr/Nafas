"""Escalations: patient questions the doctor answers instead of the assistant.

Visible to the conversation's two parties, like the conversation itself: the
patient who asked (their own scope) and the doctor (theirs). Opened in the
patient's scope by the conversation workflow; answered in the doctor's.

Revision ID: eb20329a9c8c
Revises: 84bbcf94c0f7
Create Date: 2026-09-26 10:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from nafas_core.db.migration_ops import APP_ROLE

REASONS = ("sensitive", "out_of_scope_medical", "emergency", "unclear", "output_guard")
STATUSES = ("open", "answered", "closed", "expired")
PARTY = "(patient_id = nafas_current_patient() OR doctor_id = nafas_current_doctor())"

# revision identifiers, used by Alembic.
revision: str = "eb20329a9c8c"
down_revision: str | Sequence[str] | None = "84bbcf94c0f7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    postgresql.ENUM(*REASONS, name="escalation_reason", schema="conversation").create(op.get_bind())
    postgresql.ENUM(*STATUSES, name="escalation_status", schema="conversation").create(op.get_bind())
    op.create_table(
        "escalations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("conversation_id", sa.UUID(), nullable=False),
        sa.Column("doctor_id", sa.UUID(), nullable=False),
        sa.Column("patient_id", sa.UUID(), nullable=False),
        sa.Column("message_id", sa.UUID(), nullable=False),
        sa.Column(
            "reason",
            postgresql.ENUM(*REASONS, name="escalation_reason", create_type=False, schema="conversation"),
            nullable=False,
        ),
        sa.Column(
            "status",
            postgresql.ENUM(*STATUSES, name="escalation_status", create_type=False, schema="conversation"),
            server_default="open",
            nullable=False,
        ),
        sa.Column("doctor_reply", sa.Text(), nullable=True),
        sa.Column("reply_message_id", sa.UUID(), nullable=True),
        sa.Column("workflow_id", sa.String(length=128), nullable=True),
        sa.Column("nudged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversation.conversations.id"],
            name=op.f("fk_escalations_conversation_id_conversations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["message_id"], ["conversation.messages.id"], name=op.f("fk_escalations_message_id_messages"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_escalations")),
        schema="conversation",
    )
    op.create_index(
        "ix_escalations_doctor_status", "escalations", ["doctor_id", "status", "created_at"], unique=False, schema="conversation"
    )
    # references into identity: in the database, not on the ORM model
    op.create_foreign_key(
        "fk_escalations_doctor_id_doctors",
        "escalations",
        "doctors",
        ["doctor_id"],
        ["id"],
        source_schema="conversation",
        referent_schema="identity",
    )
    op.create_foreign_key(
        "fk_escalations_patient_id_patients",
        "escalations",
        "patients",
        ["patient_id"],
        ["id"],
        source_schema="conversation",
        referent_schema="identity",
    )
    op.execute("ALTER TABLE conversation.escalations ENABLE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY party_access ON conversation.escalations TO {APP_ROLE} USING {PARTY} WITH CHECK {PARTY}")


def downgrade() -> None:
    op.drop_table("escalations", schema="conversation")
    op.execute("DROP TYPE conversation.escalation_status")
    op.execute("DROP TYPE conversation.escalation_reason")

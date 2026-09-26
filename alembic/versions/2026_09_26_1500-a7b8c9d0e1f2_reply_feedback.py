"""conversation.reply_feedback: a patient's thumbs up or down on an assistant reply.

Seen by its patient and its doctor, like the conversation it belongs to. One
row per reply (the patient may change their mind); the feedback export reads
it, de-identified, into eval candidates.

Revision ID: a7b8c9d0e1f2
Revises: f1c2d3e4a5b6
Create Date: 2026-09-26 15:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from nafas_core.db.migration_ops import APP_ROLE

PARTY = "(patient_id = nafas_current_patient() OR doctor_id = nafas_current_doctor())"

# revision identifiers, used by Alembic.
revision: str = "a7b8c9d0e1f2"
down_revision: str | Sequence[str] | None = "f1c2d3e4a5b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "reply_feedback",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("message_id", sa.UUID(), nullable=False),
        sa.Column("patient_id", sa.UUID(), nullable=False),
        sa.Column("doctor_id", sa.UUID(), nullable=False),
        sa.Column("rating", sa.String(length=8), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("rating IN ('up', 'down')", name=op.f("ck_reply_feedback_rating")),
        sa.ForeignKeyConstraint(
            ["message_id"], ["conversation.messages.id"], name=op.f("fk_reply_feedback_message_id_messages"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reply_feedback")),
        sa.UniqueConstraint("message_id", name="uq_reply_feedback_message"),
        schema="conversation",
    )
    for column, target in (("doctor_id", "doctors"), ("patient_id", "patients")):
        op.create_foreign_key(
            f"fk_reply_feedback_{column}_{target}",
            "reply_feedback",
            target,
            [column],
            ["id"],
            source_schema="conversation",
            referent_schema="identity",
        )
    op.execute("ALTER TABLE conversation.reply_feedback ENABLE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY party_access ON conversation.reply_feedback TO {APP_ROLE} USING {PARTY} WITH CHECK {PARTY}")


def downgrade() -> None:
    op.drop_table("reply_feedback", schema="conversation")

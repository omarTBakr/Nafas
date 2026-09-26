"""The conversation service's schema: conversations and their messages.

Two-sided row-level security: a conversation is visible to its patient
(session_scope(patient_id=...)) and to its doctor (session_scope(doctor_id=...)),
and its messages follow it. Patients' messages are written in the patient's
scope; a doctor's answers (phase 4) in the doctor's.

Revision ID: e36a91aa9df8
Revises: c923aebcc416
Create Date: 2026-09-26 04:19:09.579998

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from nafas_core.db.migration_ops import APP_ROLE, create_service_schema, drop_service_schema

ENUMS = {
    "message_role": ("patient", "assistant", "doctor"),
    "modality": ("text", "voice"),
    "intent": ("booking", "medical", "admin", "smalltalk", "emergency", "unclear"),
}
# a party to the conversation: its patient or its doctor
PARTY = "(patient_id = nafas_current_patient() OR doctor_id = nafas_current_doctor())"

# revision identifiers, used by Alembic.
revision: str = "e36a91aa9df8"
down_revision: str | Sequence[str] | None = "c923aebcc416"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    create_service_schema("conversation")
    for name, values in ENUMS.items():
        postgresql.ENUM(*values, name=name, schema="conversation").create(op.get_bind())

    op.create_table(
        "conversations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("patient_id", sa.UUID(), nullable=False),
        sa.Column("doctor_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conversations")),
        sa.UniqueConstraint("patient_id", "doctor_id", name=op.f("uq_conversations_patient_id_doctor_id")),
        schema="conversation",
    )
    op.create_index(
        op.f("ix_conversation_conversations_doctor_id"), "conversations", ["doctor_id"], unique=False, schema="conversation"
    )
    op.create_table(
        "messages",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("conversation_id", sa.UUID(), nullable=False),
        sa.Column(
            "role",
            postgresql.ENUM("patient", "assistant", "doctor", name="message_role", create_type=False, schema="conversation"),
            nullable=False,
        ),
        sa.Column(
            "modality",
            postgresql.ENUM("text", "voice", name="modality", create_type=False, schema="conversation"),
            server_default="text",
            nullable=False,
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("audio_key", sa.Text(), nullable=True),
        sa.Column(
            "intent",
            postgresql.ENUM(
                "booking",
                "medical",
                "admin",
                "smalltalk",
                "emergency",
                "unclear",
                name="intent",
                create_type=False,
                schema="conversation",
            ),
            nullable=True,
        ),
        sa.Column("model", sa.String(length=64), nullable=True),
        sa.Column("prompt_version", sa.String(length=64), nullable=True),
        sa.Column("tokens_in", sa.Integer(), nullable=True),
        sa.Column("tokens_out", sa.Integer(), nullable=True),
        sa.Column("detected_dialect", sa.String(length=8), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversation.conversations.id"],
            name=op.f("fk_messages_conversation_id_conversations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_messages")),
        schema="conversation",
    )
    op.create_index(
        "ix_messages_conversation_created", "messages", ["conversation_id", "created_at"], unique=False, schema="conversation"
    )

    # references into identity: in the database, not on the ORM models
    op.create_foreign_key(
        "fk_conversations_patient_id_patients",
        "conversations",
        "patients",
        ["patient_id"],
        ["id"],
        source_schema="conversation",
        referent_schema="identity",
    )
    op.create_foreign_key(
        "fk_conversations_doctor_id_doctors",
        "conversations",
        "doctors",
        ["doctor_id"],
        ["id"],
        source_schema="conversation",
        referent_schema="identity",
    )

    op.execute("ALTER TABLE conversation.conversations ENABLE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY party_access ON conversation.conversations TO {APP_ROLE} USING {PARTY} WITH CHECK {PARTY}")

    in_party_conversation = (
        "EXISTS (SELECT 1 FROM conversation.conversations c WHERE c.id = conversation_id"
        " AND (c.patient_id = nafas_current_patient() OR c.doctor_id = nafas_current_doctor()))"
    )
    op.execute("ALTER TABLE conversation.messages ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY party_access ON conversation.messages TO {APP_ROLE}"
        f" USING ({in_party_conversation}) WITH CHECK ({in_party_conversation})"
    )


def downgrade() -> None:
    drop_service_schema("conversation")

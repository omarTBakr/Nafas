"""The identity service's schema: accounts, specializations, doctors, patients.

Row-level security:
- doctor_patients and consents: rows of the current doctor only.
- patients and patient_channels: rows of patients linked to the current
  doctor; inserts are open, since a patient exists before their link.
- users, specializations, doctors: none. Login looks accounts up before any
  doctor is known, and a doctor's profile is not patient data. Only the
  identity service touches users.

Revision ID: c199e971e349
Revises: 4e80e0d8d300
Create Date: 2026-09-26 02:56:09.355252

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from nafas_core.db.migration_ops import (
    create_service_schema,
    drop_service_schema,
    enable_doctor_isolation,
    enable_patient_isolation,
)

ENUMS = {
    "user_role": ("doctor", "admin", "staff"),
    "language": ("ar", "en"),
    "sex": ("female", "male"),
    "channel": ("telegram", "email", "whatsapp"),
    "care_status": ("active", "archived"),
    "consent_kind": ("data_processing", "ai_chat", "session_recording"),
}

# revision identifiers, used by Alembic.
revision: str = "c199e971e349"
down_revision: str | Sequence[str] | None = "4e80e0d8d300"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    create_service_schema("identity")
    for name, values in ENUMS.items():
        postgresql.ENUM(*values, name=name, schema="identity").create(op.get_bind())

    op.create_table(
        "patients",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("full_name", sa.Text(), nullable=False),
        sa.Column("date_of_birth", sa.Date(), nullable=True),
        sa.Column("sex", postgresql.ENUM("female", "male", name="sex", create_type=False, schema="identity"), nullable=True),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column(
            "preferred_language",
            postgresql.ENUM("ar", "en", name="language", create_type=False, schema="identity"),
            server_default="ar",
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_patients")),
        schema="identity",
    )
    op.create_table(
        "specializations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name_en", sa.Text(), nullable=False),
        sa.Column("name_ar", sa.Text(), nullable=False),
        sa.Column("scope_description", sa.Text(), nullable=False),
        sa.Column(
            "in_scope_topics", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False
        ),
        sa.Column(
            "always_escalate", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_specializations")),
        sa.UniqueConstraint("code", name=op.f("uq_specializations_code")),
        schema="identity",
    )
    op.create_table(
        "users",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column(
            "role",
            postgresql.ENUM("doctor", "admin", "staff", name="user_role", create_type=False, schema="identity"),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        schema="identity",
    )
    op.create_index("uq_users_email_lower", "users", [sa.literal_column("lower(email)")], unique=True, schema="identity")
    op.create_table(
        "doctors",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("full_name_en", sa.Text(), nullable=False),
        sa.Column("full_name_ar", sa.Text(), nullable=False),
        sa.Column("specialization_id", sa.UUID(), nullable=False),
        sa.Column("timezone", sa.String(length=64), server_default="Africa/Cairo", nullable=False),
        sa.Column("default_slot_minutes", sa.Integer(), server_default=sa.text("20"), nullable=False),
        sa.Column("buffer_minutes", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("languages", sa.ARRAY(sa.String(length=8)), server_default=sa.text("ARRAY['ar']::varchar[]"), nullable=False),
        sa.Column("booking_horizon_days", sa.Integer(), server_default=sa.text("60"), nullable=False),
        sa.Column("min_notice_minutes", sa.Integer(), server_default=sa.text("60"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("booking_horizon_days > 0", name=op.f("ck_doctors_horizon_positive")),
        sa.CheckConstraint("buffer_minutes >= 0", name=op.f("ck_doctors_buffer_not_negative")),
        sa.CheckConstraint("default_slot_minutes > 0", name=op.f("ck_doctors_slot_positive")),
        sa.CheckConstraint("min_notice_minutes >= 0", name=op.f("ck_doctors_notice_not_negative")),
        sa.ForeignKeyConstraint(
            ["specialization_id"], ["identity.specializations.id"], name=op.f("fk_doctors_specialization_id_specializations")
        ),
        sa.ForeignKeyConstraint(["user_id"], ["identity.users.id"], name=op.f("fk_doctors_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_doctors")),
        sa.UniqueConstraint("user_id", name=op.f("uq_doctors_user_id")),
        schema="identity",
    )
    op.create_table(
        "patient_channels",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("patient_id", sa.UUID(), nullable=False),
        sa.Column(
            "channel",
            postgresql.ENUM("telegram", "email", "whatsapp", name="channel", create_type=False, schema="identity"),
            nullable=False,
        ),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["patient_id"], ["identity.patients.id"], name=op.f("fk_patient_channels_patient_id_patients"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_patient_channels")),
        sa.UniqueConstraint("channel", "external_id", name=op.f("uq_patient_channels_channel_external_id")),
        schema="identity",
    )
    op.create_index(
        op.f("ix_identity_patient_channels_patient_id"), "patient_channels", ["patient_id"], unique=False, schema="identity"
    )
    op.create_table(
        "consents",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("patient_id", sa.UUID(), nullable=False),
        sa.Column("doctor_id", sa.UUID(), nullable=False),
        sa.Column(
            "kind",
            postgresql.ENUM(
                "data_processing", "ai_chat", "session_recording", name="consent_kind", create_type=False, schema="identity"
            ),
            nullable=False,
        ),
        sa.Column("granted_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "channel",
            postgresql.ENUM("telegram", "email", "whatsapp", name="channel", create_type=False, schema="identity"),
            nullable=True,
        ),
        sa.Column("evidence", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["doctor_id"], ["identity.doctors.id"], name=op.f("fk_consents_doctor_id_doctors")),
        sa.ForeignKeyConstraint(
            ["patient_id"], ["identity.patients.id"], name=op.f("fk_consents_patient_id_patients"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_consents")),
        schema="identity",
    )
    op.create_index(op.f("ix_identity_consents_patient_id"), "consents", ["patient_id"], unique=False, schema="identity")
    op.create_table(
        "doctor_patients",
        sa.Column("doctor_id", sa.UUID(), nullable=False),
        sa.Column("patient_id", sa.UUID(), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM("active", "archived", name="care_status", create_type=False, schema="identity"),
            server_default="active",
            nullable=False,
        ),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["doctor_id"], ["identity.doctors.id"], name=op.f("fk_doctor_patients_doctor_id_doctors")),
        sa.ForeignKeyConstraint(
            ["patient_id"], ["identity.patients.id"], name=op.f("fk_doctor_patients_patient_id_patients"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("doctor_id", "patient_id", name=op.f("pk_doctor_patients")),
        schema="identity",
    )
    op.create_index(
        op.f("ix_identity_doctor_patients_patient_id"), "doctor_patients", ["patient_id"], unique=False, schema="identity"
    )

    enable_doctor_isolation("identity.doctor_patients")
    enable_doctor_isolation("identity.consents")
    enable_patient_isolation("identity.patients", patient_column="id")
    enable_patient_isolation("identity.patient_channels")


def downgrade() -> None:
    # the schema holds every table, type and policy above; the policies on
    # patients reference doctor_patients, so dropping tables one by one would
    # have to follow their dependencies by hand
    drop_service_schema("identity")

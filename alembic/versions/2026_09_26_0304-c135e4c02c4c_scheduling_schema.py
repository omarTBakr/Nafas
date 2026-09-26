"""The scheduling service's schema: booking settings, hours, time off, appointments.

Every table is isolated per doctor. appointments carries the guarantee the
whole booking flow rests on: an exclusion constraint that makes overlapping
held-or-confirmed appointments for one doctor impossible (it needs the
btree_gist extension from the first migration).

Revision ID: c135e4c02c4c
Revises: c199e971e349
Create Date: 2026-09-26 03:04:37.147493

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from nafas_core.db.migration_ops import create_service_schema, drop_service_schema, enable_doctor_isolation

ENUMS = {
    "availability_mode": ("in_person", "online", "both"),
    "appointment_mode": ("in_person", "online"),
    "appointment_status": ("held", "confirmed", "cancelled", "completed", "no_show"),
}
TABLES = ("booking_settings", "availability_rules", "time_off", "appointments")

# revision identifiers, used by Alembic.
revision: str = "c135e4c02c4c"
down_revision: str | Sequence[str] | None = "c199e971e349"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    create_service_schema("scheduling")
    for name, values in ENUMS.items():
        postgresql.ENUM(*values, name=name, schema="scheduling").create(op.get_bind())

    op.create_table(
        "appointments",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("doctor_id", sa.UUID(), nullable=False),
        sa.Column("patient_id", sa.UUID(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(
                "held",
                "confirmed",
                "cancelled",
                "completed",
                "no_show",
                name="appointment_status",
                create_type=False,
                schema="scheduling",
            ),
            nullable=False,
        ),
        sa.Column(
            "mode",
            postgresql.ENUM("in_person", "online", name="appointment_mode", create_type=False, schema="scheduling"),
            nullable=False,
        ),
        sa.Column("hold_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("meeting_url", sa.Text(), nullable=True),
        sa.Column("reason_for_visit", sa.Text(), nullable=True),
        sa.Column("booking_workflow_id", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        postgresql.ExcludeConstraint(
            (sa.column("doctor_id"), "="),
            (sa.text("tstzrange(starts_at, ends_at, '[)')"), "&&"),
            where=sa.text("status IN ('held', 'confirmed')"),
            using="gist",
            name="no_overlapping_appointments",
        ),
        sa.CheckConstraint("starts_at = date_trunc('minute', starts_at)", name=op.f("ck_appointments_whole_minute")),
        sa.CheckConstraint("status <> 'held' OR hold_expires_at IS NOT NULL", name=op.f("ck_appointments_held_expires")),
        sa.CheckConstraint("ends_at > starts_at", name=op.f("ck_appointments_ends_after_start")),
        sa.ForeignKeyConstraint(["doctor_id"], ["identity.doctors.id"], name=op.f("fk_appointments_doctor_id_doctors")),
        sa.ForeignKeyConstraint(["patient_id"], ["identity.patients.id"], name=op.f("fk_appointments_patient_id_patients")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_appointments")),
        schema="scheduling",
    )
    op.create_index(
        "ix_appointments_doctor_starts", "appointments", ["doctor_id", "starts_at"], unique=False, schema="scheduling"
    )
    op.create_index(
        op.f("ix_scheduling_appointments_patient_id"), "appointments", ["patient_id"], unique=False, schema="scheduling"
    )
    op.create_table(
        "availability_rules",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("doctor_id", sa.UUID(), nullable=False),
        sa.Column("weekday", sa.SmallInteger(), nullable=False),
        sa.Column("start_local", sa.Time(), nullable=False),
        sa.Column("end_local", sa.Time(), nullable=False),
        sa.Column(
            "mode",
            postgresql.ENUM("in_person", "online", "both", name="availability_mode", create_type=False, schema="scheduling"),
            server_default="both",
            nullable=False,
        ),
        sa.Column("slot_minutes", sa.Integer(), nullable=True),
        sa.Column("effective_from", sa.Date(), nullable=True),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_from IS NULL OR effective_to >= effective_from",
            name=op.f("ck_availability_rules_range_order"),
        ),
        sa.CheckConstraint("end_local > start_local", name=op.f("ck_availability_rules_ends_after_start")),
        sa.CheckConstraint("slot_minutes IS NULL OR slot_minutes > 0", name=op.f("ck_availability_rules_slot_positive")),
        sa.CheckConstraint("weekday BETWEEN 0 AND 6", name=op.f("ck_availability_rules_weekday_range")),
        sa.ForeignKeyConstraint(["doctor_id"], ["identity.doctors.id"], name=op.f("fk_availability_rules_doctor_id_doctors")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_availability_rules")),
        schema="scheduling",
    )
    op.create_index(
        op.f("ix_scheduling_availability_rules_doctor_id"), "availability_rules", ["doctor_id"], unique=False, schema="scheduling"
    )
    op.create_table(
        "booking_settings",
        sa.Column("doctor_id", sa.UUID(), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("slot_minutes", sa.Integer(), server_default=sa.text("20"), nullable=False),
        sa.Column("buffer_minutes", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("min_notice_minutes", sa.Integer(), server_default=sa.text("60"), nullable=False),
        sa.Column("horizon_days", sa.Integer(), server_default=sa.text("60"), nullable=False),
        sa.Column("hold_minutes", sa.Integer(), server_default=sa.text("10"), nullable=False),
        sa.CheckConstraint("buffer_minutes >= 0", name=op.f("ck_booking_settings_buffer_not_negative")),
        sa.CheckConstraint("hold_minutes > 0", name=op.f("ck_booking_settings_hold_positive")),
        sa.CheckConstraint("horizon_days > 0", name=op.f("ck_booking_settings_horizon_positive")),
        sa.CheckConstraint("min_notice_minutes >= 0", name=op.f("ck_booking_settings_notice_not_negative")),
        sa.CheckConstraint("slot_minutes > 0", name=op.f("ck_booking_settings_slot_positive")),
        sa.ForeignKeyConstraint(["doctor_id"], ["identity.doctors.id"], name=op.f("fk_booking_settings_doctor_id_doctors")),
        sa.PrimaryKeyConstraint("doctor_id", name=op.f("pk_booking_settings")),
        schema="scheduling",
    )
    op.create_table(
        "time_off",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("doctor_id", sa.UUID(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.CheckConstraint("ends_at > starts_at", name=op.f("ck_time_off_ends_after_start")),
        sa.ForeignKeyConstraint(["doctor_id"], ["identity.doctors.id"], name=op.f("fk_time_off_doctor_id_doctors")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_time_off")),
        schema="scheduling",
    )
    op.create_index(op.f("ix_scheduling_time_off_doctor_id"), "time_off", ["doctor_id"], unique=False, schema="scheduling")

    for table in TABLES:
        enable_doctor_isolation(f"scheduling.{table}")


def downgrade() -> None:
    drop_service_schema("scheduling")

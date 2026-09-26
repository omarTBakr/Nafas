"""In-app notifications about appointments, written by BookingWorkflow.

Written in the doctor's scope (the workflow acts for the doctor's calendar);
read and marked read by the patient in theirs.

Revision ID: 5b7e1d2c9a40
Revises: e36a91aa9df8
Create Date: 2026-09-26 05:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from nafas_core.db.migration_ops import enable_doctor_isolation, enable_patient_self_access

KINDS = ("confirmed", "hold_expired", "reminder", "cancelled_by_doctor")

# revision identifiers, used by Alembic.
revision: str = "5b7e1d2c9a40"
down_revision: str | Sequence[str] | None = "e36a91aa9df8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    postgresql.ENUM(*KINDS, name="notification_kind", schema="scheduling").create(op.get_bind())
    op.create_table(
        "notifications",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("doctor_id", sa.UUID(), nullable=False),
        sa.Column("patient_id", sa.UUID(), nullable=False),
        sa.Column("appointment_id", sa.UUID(), nullable=False),
        sa.Column(
            "kind", postgresql.ENUM(*KINDS, name="notification_kind", create_type=False, schema="scheduling"), nullable=False
        ),
        sa.Column("minutes_before", sa.Integer(), nullable=True),
        sa.Column("details", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["doctor_id"], ["identity.doctors.id"], name=op.f("fk_notifications_doctor_id_doctors")),
        sa.ForeignKeyConstraint(["patient_id"], ["identity.patients.id"], name=op.f("fk_notifications_patient_id_patients")),
        sa.ForeignKeyConstraint(
            ["appointment_id"],
            ["scheduling.appointments.id"],
            name=op.f("fk_notifications_appointment_id_appointments"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notifications")),
        schema="scheduling",
    )
    op.create_index(
        "ix_notifications_patient_created", "notifications", ["patient_id", "created_at"], unique=False, schema="scheduling"
    )
    enable_doctor_isolation("scheduling.notifications")
    enable_patient_self_access("scheduling.notifications", commands=("SELECT", "UPDATE"))


def downgrade() -> None:
    op.drop_table("notifications", schema="scheduling")
    op.execute("DROP TYPE scheduling.notification_kind")

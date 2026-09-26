"""Consent to data processing is platform-wide; AI chat and recordings are per doctor.

consents.doctor_id becomes nullable, and a check keeps the two shapes
apart: data_processing has no doctor, every other kind has one. A patient
may also revoke their own consents (UPDATE in their own scope).

Revision ID: 7c2f4e8a1b93
Revises: 5b7e1d2c9a40
Create Date: 2026-09-26 06:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from nafas_core.db.migration_ops import APP_ROLE

# revision identifiers, used by Alembic.
revision: str = "7c2f4e8a1b93"
down_revision: str | Sequence[str] | None = "5b7e1d2c9a40"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OWN = "patient_id = nafas_current_patient()"


def upgrade() -> None:
    op.alter_column("consents", "doctor_id", existing_type=sa.UUID(), nullable=True, schema="identity")
    op.create_check_constraint(
        "doctor_only_where_needed",
        "consents",
        "(kind = 'data_processing') = (doctor_id IS NULL)",
        schema="identity",
    )
    op.execute(f"CREATE POLICY patient_own_update ON identity.consents FOR UPDATE TO {APP_ROLE} USING ({OWN}) WITH CHECK ({OWN})")


def downgrade() -> None:
    op.execute("DROP POLICY patient_own_update ON identity.consents")
    op.drop_constraint("ck_consents_doctor_only_where_needed", "consents", schema="identity")
    op.execute("DELETE FROM identity.consents WHERE doctor_id IS NULL")
    op.alter_column("consents", "doctor_id", existing_type=sa.UUID(), nullable=False, schema="identity")

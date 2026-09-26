"""Fix identity.patient_channels' row-level security: a doctor sees only their own patients' channels.

The policies compared doctor_patients.patient_id with itself (the column was
not qualified, so it resolved inside the subquery), which let any doctor with
at least one patient read, change and delete every patient's channels. Found
by the isolation sweep once its second doctor had a patient of their own.

Revision ID: f2a3b4c5d6e7
Revises: e9f0a1b2c3d4
Create Date: 2026-09-26 18:00:00

"""

from collections.abc import Sequence

from alembic import op

from nafas_core.db.migration_ops import APP_ROLE, linked_to_current_doctor

# revision identifiers, used by Alembic.
revision: str = "f2a3b4c5d6e7"
down_revision: str | Sequence[str] | None = "e9f0a1b2c3d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "identity.patient_channels"


def upgrade() -> None:
    linked = linked_to_current_doctor(TABLE)
    for name in ("linked_doctor_reads", "linked_doctor_updates", "linked_doctor_deletes"):
        op.execute(f"DROP POLICY {name} ON {TABLE}")
    op.execute(f"CREATE POLICY linked_doctor_reads ON {TABLE} FOR SELECT TO {APP_ROLE} USING ({linked})")
    op.execute(f"CREATE POLICY linked_doctor_updates ON {TABLE} FOR UPDATE TO {APP_ROLE} USING ({linked}) WITH CHECK ({linked})")
    op.execute(f"CREATE POLICY linked_doctor_deletes ON {TABLE} FOR DELETE TO {APP_ROLE} USING ({linked})")


def downgrade() -> None:
    # the broken policies are not put back
    pass

"""The consent shape check: service_improvement is platform-wide, like data_processing.

Separate from the revision that added the value, because Postgres will not
use a new enum value in the transaction that created it; the check compares
the kind as text for the same reason.

Revision ID: c5d6e7f8a9b0
Revises: b3c4d5e6f7a8
Create Date: 2026-09-26 15:20:00

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c5d6e7f8a9b0"
down_revision: str | Sequence[str] | None = "b3c4d5e6f7a8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_consents_doctor_only_where_needed", "consents", schema="identity")
    op.create_check_constraint(
        "doctor_only_where_needed",
        "consents",
        "(kind::text IN ('data_processing', 'service_improvement')) = (doctor_id IS NULL)",
        schema="identity",
    )


def downgrade() -> None:
    op.drop_constraint("ck_consents_doctor_only_where_needed", "consents", schema="identity")
    op.create_check_constraint(
        "doctor_only_where_needed", "consents", "(kind = 'data_processing') = (doctor_id IS NULL)", schema="identity"
    )

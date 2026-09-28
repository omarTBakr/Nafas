"""clinical.history_entries and clinical.documents gain appointment_id: the visit a note or document belongs to.

A doctor reads each visit on its own page; what they add from there (a note,
a report, a scan) is filed under that visit. Nullable: most of the record
belongs to no one visit. No foreign key: the appointment lives in another
service's schema, and the gateway checks the link.

Revision ID: a1b2c3d4e5f6
Revises: f2a3b4c5d6e7
Create Date: 2026-09-28 10:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: str | Sequence[str] | None = "f2a3b4c5d6e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("history_entries", "documents")


def upgrade() -> None:
    for table in TABLES:
        op.add_column(table, sa.Column("appointment_id", UUID(as_uuid=True), nullable=True), schema="clinical")
        op.create_index(f"ix_{table}_appointment", table, ["appointment_id"], schema="clinical")


def downgrade() -> None:
    for table in TABLES:
        op.drop_index(f"ix_{table}_appointment", table_name=table, schema="clinical")
        op.drop_column(table, "appointment_id", schema="clinical")

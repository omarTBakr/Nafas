"""clinical.history_kind gains visit_transcript: a recorded visit's transcript, filed with its note.

When the doctor approves a recorded visit's note, the timed transcript is
filed beside it, doctor-only, so what was said stays findable in the record.

Revision ID: e9f0a1b2c3d4
Revises: d7e8f9a0b1c2
Create Date: 2026-09-26 17:00:00

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e9f0a1b2c3d4"
down_revision: str | Sequence[str] | None = "d7e8f9a0b1c2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE clinical.history_kind ADD VALUE IF NOT EXISTS 'visit_transcript'")


def downgrade() -> None:
    # Postgres cannot drop an enum value; the entries themselves are the record and stay
    pass

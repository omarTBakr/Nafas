"""consultation.consultations gains where a visit was recorded: in person, or in an online room.

An online visit records one track per participant, so its parts carry a
speaker; `recording_stopped_at` marks the doctor stopping, after which the
visit is processed once every track's file is written.

Revision ID: d7e8f9a0b1c2
Revises: c5d6e7f8a9b0
Create Date: 2026-09-26 16:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d7e8f9a0b1c2"
down_revision: str | Sequence[str] | None = "c5d6e7f8a9b0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "consultations",
        sa.Column("source", sa.String(length=16), server_default="in_person", nullable=False),
        schema="consultation",
    )
    op.add_column("consultations", sa.Column("room", sa.String(length=100), nullable=True), schema="consultation")
    op.add_column(
        "consultations", sa.Column("recording_stopped_at", sa.DateTime(timezone=True), nullable=True), schema="consultation"
    )
    op.create_index("ix_consultations_room", "consultations", ["room"], schema="consultation")


def downgrade() -> None:
    op.drop_index("ix_consultations_room", "consultations", schema="consultation")
    for column in ("recording_stopped_at", "room", "source"):
        op.drop_column("consultations", column, schema="consultation")

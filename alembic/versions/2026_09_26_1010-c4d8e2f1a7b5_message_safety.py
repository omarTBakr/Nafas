"""The safety gates' verdicts on each reply, for review and behavioural metrics.

Revision ID: c4d8e2f1a7b5
Revises: eb20329a9c8c
Create Date: 2026-09-26 10:10:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c4d8e2f1a7b5"
down_revision: str | Sequence[str] | None = "eb20329a9c8c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("safety", postgresql.JSONB(), nullable=True), schema="conversation")


def downgrade() -> None:
    op.drop_column("messages", "safety", schema="conversation")

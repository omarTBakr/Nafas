"""A patient's choice to get appointment emails beside the in-app notices, on by default.

Revision ID: 84bbcf94c0f7
Revises: a1e5c3d7b204
Create Date: 2026-09-26 09:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "84bbcf94c0f7"
down_revision: str | Sequence[str] | None = "a1e5c3d7b204"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "patients",
        sa.Column("email_notices", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        schema="identity",
    )


def downgrade() -> None:
    op.drop_column("patients", "email_notices", schema="identity")

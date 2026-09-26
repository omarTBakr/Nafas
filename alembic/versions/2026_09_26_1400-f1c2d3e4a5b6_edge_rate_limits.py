"""The gateway's schema, edge: rate-limit hits shared by every gateway replica.

No patient data: a limit's name, a SHA-256 of its key (an address, an email,
an account id) and when. No row-level security for that reason; closed to
every other service by the per-service roles. Rows older than the longest
window are swept by the gateway as it goes.

Revision ID: f1c2d3e4a5b6
Revises: e7a3b9c1d2f4
Create Date: 2026-09-26 14:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from nafas_core.db.migration_ops import create_service_schema, drop_service_schema

# revision identifiers, used by Alembic.
revision: str = "f1c2d3e4a5b6"
down_revision: str | Sequence[str] | None = "e7a3b9c1d2f4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    create_service_schema("edge")
    op.create_table(
        "rate_hits",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("limit_name", sa.String(length=40), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("hit_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rate_hits")),
        schema="edge",
    )
    op.create_index("ix_rate_hits_window", "rate_hits", ["limit_name", "key_hash", "hit_at"], schema="edge")
    op.create_index("ix_rate_hits_hit_at", "rate_hits", ["hit_at"], schema="edge")


def downgrade() -> None:
    drop_service_schema("edge")

"""Enable the Postgres extensions the schema relies on.

- vector: embedding columns and HNSW indexes for per-patient RAG
- btree_gist: lets one GiST exclusion constraint mix `doctor_id WITH =` and
  `during WITH &&`, which is what makes double-booking impossible

Revision ID: 874f432a81ce
Revises:
Create Date: 2026-09-26 02:02:05.193202

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "874f432a81ce"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")


def downgrade() -> None:
    op.execute("DROP EXTENSION IF EXISTS btree_gist")
    op.execute("DROP EXTENSION IF EXISTS vector")

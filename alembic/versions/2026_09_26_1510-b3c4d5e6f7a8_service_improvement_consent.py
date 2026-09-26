"""identity.consent_kind gains service_improvement: an optional, platform-wide opt-in.

Given, a patient's chats and visit notes may be extracted, de-identified, and
reviewed to test and improve the assistants (scripts/export_feedback.py).
Not given, nothing of theirs is ever exported. The sign-up consent does not
cover this, so it is its own record.

Revision ID: b3c4d5e6f7a8
Revises: a7b8c9d0e1f2
Create Date: 2026-09-26 15:10:00

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b3c4d5e6f7a8"
down_revision: str | Sequence[str] | None = "a7b8c9d0e1f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE identity.consent_kind ADD VALUE IF NOT EXISTS 'service_improvement'")


def downgrade() -> None:
    # Postgres cannot drop an enum value; the rows would have to go first
    op.execute("UPDATE identity.consents SET revoked_at = now() WHERE kind = 'service_improvement' AND revoked_at IS NULL")

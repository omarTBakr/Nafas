"""The audit log: every read of clinical data, by a person or the model.

Its own schema, which every service may append to (the one exception to "a
service writes only its own schema", docs/PLAN.md §6c) and none may read,
change or delete: the app role gets INSERT and nothing else. Reading it is
for the owner role, in an investigation or an access report.

Revision ID: 9d4b2a6e3f10
Revises: 7c2f4e8a1b93
Create Date: 2026-09-26 07:00:00

"""

from collections.abc import Sequence

from alembic import op

from nafas_core.db.migration_ops import APP_ROLE

# revision identifiers, used by Alembic.
revision: str = "9d4b2a6e3f10"
down_revision: str | Sequence[str] | None = "7c2f4e8a1b93"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA audit")
    op.execute(f"GRANT USAGE ON SCHEMA audit TO {APP_ROLE}")
    op.execute("""
        CREATE TABLE audit.audit_log (
            id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            at timestamptz NOT NULL DEFAULT now(),
            service text NOT NULL,
            actor_type text NOT NULL CHECK (actor_type IN ('doctor', 'patient', 'model', 'staff', 'system')),
            actor_id uuid,
            action text NOT NULL,
            resource_type text NOT NULL,
            resource_id text,
            patient_id uuid,
            doctor_id uuid,
            detail jsonb NOT NULL DEFAULT '{}'::jsonb
        )
        """)
    op.execute("CREATE INDEX ix_audit_log_patient_at ON audit.audit_log (patient_id, at)")
    op.execute("CREATE INDEX ix_audit_log_actor_at ON audit.audit_log (actor_id, at)")
    # append only: no SELECT, UPDATE or DELETE for services, now or by default later
    op.execute(f"GRANT INSERT ON audit.audit_log TO {APP_ROLE}")


def downgrade() -> None:
    op.execute("DROP SCHEMA audit CASCADE")

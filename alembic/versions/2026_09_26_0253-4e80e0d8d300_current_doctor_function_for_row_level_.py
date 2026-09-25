"""The function every row-level security policy calls, and the app role.

nafas_current_doctor() reads app.current_doctor_id, which
nafas_core.db.session_scope(doctor_id=...) sets for one transaction. An unset
or empty setting gives NULL, and `doctor_id = NULL` matches nothing.

nafas_app is normally created by deploy/postgres/roles.sql; creating it here
too (without a login) means a migration never fails on a server set up some
other way.

Revision ID: 4e80e0d8d300
Revises: 874f432a81ce
Create Date: 2026-09-26 02:53:59.089224

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4e80e0d8d300"
down_revision: str | Sequence[str] | None = "874f432a81ce"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'nafas_app') THEN
                CREATE ROLE nafas_app NOLOGIN;
            END IF;
        END
        $$
        """)
    op.execute("""
        CREATE FUNCTION nafas_current_doctor() RETURNS uuid
        LANGUAGE sql STABLE
        AS $$ SELECT NULLIF(current_setting('app.current_doctor_id', true), '')::uuid $$
        """)
    op.execute("GRANT EXECUTE ON FUNCTION nafas_current_doctor() TO nafas_app")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS nafas_current_doctor()")

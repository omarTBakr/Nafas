"""Each service's tables are held by that service's role alone.

Until now every service logged in as nafas_service, a member of nafas_app,
and nafas_app could read every schema: scheduling's credentials could read
identity.users. Now nafas_app holds no tables. It stays the role the
row-level security policies name, and every service login is in it, but
the privileges on a schema belong to nafas_<schema>_access, which only that
service's login holds (deploy/postgres/roles.sql). What every service
shares stays on nafas_app: the scope functions and appending to the audit log.

Revision ID: a1e5c3d7b204
Revises: 9d4b2a6e3f10
Create Date: 2026-09-26 08:00:00

"""

from collections.abc import Sequence

from alembic import op

from nafas_core.db.migration_ops import APP_ROLE, ensure_role, service_role

# revision identifiers, used by Alembic.
revision: str = "a1e5c3d7b204"
down_revision: str | Sequence[str] | None = "9d4b2a6e3f10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMAS = ("identity", "scheduling", "conversation")
TABLE_PRIVILEGES = "SELECT, INSERT, UPDATE, DELETE"


def upgrade() -> None:
    for schema in SCHEMAS:
        role = service_role(schema)
        ensure_role(role)
        op.execute(f"GRANT USAGE ON SCHEMA {schema} TO {role}")
        op.execute(f"GRANT {TABLE_PRIVILEGES} ON ALL TABLES IN SCHEMA {schema} TO {role}")
        op.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA {schema} TO {role}")
        op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA {schema} GRANT {TABLE_PRIVILEGES} ON TABLES TO {role}")
        op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA {schema} GRANT USAGE, SELECT ON SEQUENCES TO {role}")

        op.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA {schema} FROM {APP_ROLE}")
        op.execute(f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA {schema} FROM {APP_ROLE}")
        op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA {schema} REVOKE ALL ON TABLES FROM {APP_ROLE}")
        op.execute(f"REVOKE USAGE ON SCHEMA {schema} FROM {APP_ROLE}")

    # the login lookup that sees past patient row-level security is identity's alone
    op.execute(f"REVOKE EXECUTE ON FUNCTION identity.patient_id_for_user(uuid) FROM {APP_ROLE}")
    op.execute(f"GRANT EXECUTE ON FUNCTION identity.patient_id_for_user(uuid) TO {service_role('identity')}")


def downgrade() -> None:
    op.execute(f"REVOKE EXECUTE ON FUNCTION identity.patient_id_for_user(uuid) FROM {service_role('identity')}")
    op.execute(f"GRANT EXECUTE ON FUNCTION identity.patient_id_for_user(uuid) TO {APP_ROLE}")
    for schema in SCHEMAS:
        role = service_role(schema)
        op.execute(f"GRANT USAGE ON SCHEMA {schema} TO {APP_ROLE}")
        op.execute(f"GRANT {TABLE_PRIVILEGES} ON ALL TABLES IN SCHEMA {schema} TO {APP_ROLE}")
        op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA {schema} GRANT {TABLE_PRIVILEGES} ON TABLES TO {APP_ROLE}")
        op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA {schema} REVOKE ALL ON TABLES FROM {role}")
        op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA {schema} REVOKE ALL ON SEQUENCES FROM {role}")
        op.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA {schema} FROM {role}")
        op.execute(f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA {schema} FROM {role}")
        op.execute(f"REVOKE USAGE ON SCHEMA {schema} FROM {role}")

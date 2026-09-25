"""Building blocks for migrations, so every service's schema is set up the same way.

Called from alembic revisions only; each emits SQL through `alembic.op`.
"""

from alembic import op

# the group role services log in through (deploy/postgres/roles.sql)
APP_ROLE = "nafas_app"


def create_service_schema(schema: str) -> None:
    """A schema owned by one service, usable by the app role, now and for tables added later."""
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
    op.execute(f"GRANT USAGE ON SCHEMA {schema} TO {APP_ROLE}")
    # applies to tables the migration role creates from here on
    op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA {schema} GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {APP_ROLE}")


def drop_service_schema(schema: str) -> None:
    op.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")


def enable_doctor_isolation(table: str, using: str = "doctor_id = nafas_current_doctor()") -> None:
    """
    Row-level security on `table` (schema-qualified): the app role sees and
    writes only rows the current doctor may, as set by session_scope(doctor_id=...).

    With no doctor set, nafas_current_doctor() is NULL and nothing matches:
    the safe default. `using` replaces the condition for tables that reach the
    doctor indirectly (a patient, through doctor_patients).
    """
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY doctor_isolation ON {table} TO {APP_ROLE} USING ({using}) WITH CHECK ({using})")

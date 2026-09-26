"""Building blocks for migrations, so every service's schema is set up the same way.

Called from alembic revisions only; each emits SQL through `alembic.op`.
"""

from alembic import op

# the group role services log in through (deploy/postgres/roles.sql)
APP_ROLE = "nafas_app"


def service_role(schema: str) -> str:
    """The group holding one service's tables (deploy/postgres/roles.sql); only that service logs in with it."""
    return f"nafas_{schema}_access"


def ensure_role(role: str) -> None:
    """A NOLOGIN group role, created if a fresh server's roles.sql did not already."""
    op.execute(
        f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}')"
        f" THEN CREATE ROLE {role} NOLOGIN; END IF; END $$"
    )


def create_service_schema(schema: str) -> None:
    """
    A schema owned by one service, usable by that service's role alone, now
    and for tables added later. Its login is also in APP_ROLE, which the
    row-level security policies name; APP_ROLE itself holds no tables.
    """
    role = service_role(schema)
    ensure_role(role)
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
    op.execute(f"GRANT USAGE ON SCHEMA {schema} TO {role}")
    # applies to tables the migration role creates from here on
    op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA {schema} GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {role}")
    op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA {schema} GRANT USAGE, SELECT ON SEQUENCES TO {role}")


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


def enable_patient_isolation(table: str, patient_column: str = "patient_id") -> None:
    """
    Row-level security for a table reached through a patient rather than a doctor.

    A doctor sees and changes a row only when its patient is linked to them in
    identity.doctor_patients. Inserting is open, because a new patient exists
    before the link that makes them visible (onboarding creates both in one
    transaction); until linked, the row is invisible to everyone.
    """
    linked = (
        "EXISTS (SELECT 1 FROM identity.doctor_patients dp"
        f" WHERE dp.patient_id = {patient_column} AND dp.doctor_id = nafas_current_doctor())"
    )
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY linked_doctor_reads ON {table} FOR SELECT TO {APP_ROLE} USING ({linked})")
    op.execute(f"CREATE POLICY linked_doctor_updates ON {table} FOR UPDATE TO {APP_ROLE} USING ({linked}) WITH CHECK ({linked})")
    op.execute(f"CREATE POLICY linked_doctor_deletes ON {table} FOR DELETE TO {APP_ROLE} USING ({linked})")
    op.execute(f"CREATE POLICY anyone_inserts ON {table} FOR INSERT TO {APP_ROLE} WITH CHECK (true)")


def enable_patient_self_access(table: str, column: str = "patient_id", commands: tuple[str, ...] = ("SELECT",)) -> None:
    """
    Lets a patient reach their own rows in `table`, as set by
    session_scope(patient_id=...). Postgres ORs permissive policies, so this
    adds to the doctor policies rather than replacing them.
    """
    own = f"{column} = nafas_current_patient()"
    for command in commands:
        check = f" WITH CHECK ({own})" if command in ("INSERT", "UPDATE") else ""
        using = f" USING ({own})" if command != "INSERT" else ""
        op.execute(f"CREATE POLICY patient_own_{command.lower()} ON {table} FOR {command} TO {APP_ROLE}{using}{check}")

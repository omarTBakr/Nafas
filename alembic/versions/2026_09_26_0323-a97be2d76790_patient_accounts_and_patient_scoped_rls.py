"""Patient accounts, and a second row-level security scope: the patient's own rows.

Patients now log in to the web app. identity.patients.user_id is their
login, and nafas_current_patient() (from session_scope(patient_id=...)) lets
a patient read their profile, their care links, their consents and their
appointments with any doctor, alongside the existing doctor policies
(Postgres ORs permissive policies). Writes to appointments stay with the
scheduling service acting in the doctor's scope; a patient's session only
ever reads them.

Revision ID: a97be2d76790
Revises: c135e4c02c4c
Create Date: 2026-09-26 03:23:35.872493

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from nafas_core.db.migration_ops import enable_patient_self_access

PATIENT_POLICIES = [
    # (table, column, commands)
    ("identity.patients", "id", ("SELECT", "UPDATE")),
    ("identity.doctor_patients", "patient_id", ("SELECT",)),
    ("identity.consents", "patient_id", ("SELECT", "INSERT")),
    ("scheduling.appointments", "patient_id", ("SELECT",)),
]


# revision identifiers, used by Alembic.
revision: str = "a97be2d76790"
down_revision: str | Sequence[str] | None = "c135e4c02c4c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # usable from the next transaction on, which is all this migration needs
    op.execute("ALTER TYPE identity.user_role ADD VALUE IF NOT EXISTS 'patient' AFTER 'doctor'")

    op.add_column("patients", sa.Column("user_id", sa.UUID(), nullable=True), schema="identity")
    op.create_foreign_key(
        op.f("fk_patients_user_id_users"),
        "patients",
        "users",
        ["user_id"],
        ["id"],
        source_schema="identity",
        referent_schema="identity",
    )
    op.create_unique_constraint(op.f("uq_patients_user_id"), "patients", ["user_id"], schema="identity")

    op.execute("""
        CREATE FUNCTION nafas_current_patient() RETURNS uuid
        LANGUAGE sql STABLE
        AS $$ SELECT NULLIF(current_setting('app.current_patient_id', true), '')::uuid $$
        """)
    op.execute("GRANT EXECUTE ON FUNCTION nafas_current_patient() TO nafas_app")

    # Login must learn which patient an account is before any patient scope
    # exists, and RLS hides every patient row until then. This one function
    # runs as its owner to answer exactly that question: an id for an id,
    # never a row. search_path is pinned so it cannot be redirected.
    op.execute("""
        CREATE FUNCTION identity.patient_id_for_user(account uuid) RETURNS uuid
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = pg_catalog, pg_temp
        AS $$ SELECT id FROM identity.patients WHERE user_id = account $$
        """)
    op.execute("REVOKE ALL ON FUNCTION identity.patient_id_for_user(uuid) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION identity.patient_id_for_user(uuid) TO nafas_app")

    for table, column, commands in PATIENT_POLICIES:
        enable_patient_self_access(table, column, commands)


def downgrade() -> None:
    for table, _, commands in PATIENT_POLICIES:
        for command in commands:
            op.execute(f"DROP POLICY IF EXISTS patient_own_{command.lower()} ON {table}")
    op.execute("DROP FUNCTION IF EXISTS identity.patient_id_for_user(uuid)")
    op.execute("DROP FUNCTION IF EXISTS nafas_current_patient()")
    op.drop_constraint(op.f("uq_patients_user_id"), "patients", schema="identity", type_="unique")
    op.drop_constraint(op.f("fk_patients_user_id_users"), "patients", schema="identity", type_="foreignkey")
    op.drop_column("patients", "user_id", schema="identity")
    # Postgres cannot drop an enum value; 'patient' stays in identity.user_role, unused

"""Each service's database login reaches its own schema and no other's."""

import pytest
from sqlalchemy import make_url, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import create_async_engine

TABLES = {
    "identity": "identity.users",
    "scheduling": "scheduling.appointments",
    "conversation": "conversation.messages",
}


async def _can_read(app_url: str, service: str, table: str) -> bool:
    url = make_url(app_url).set(username=f"nafas_{service}_svc", password="nafas")
    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            await connection.execute(text(f"SELECT count(*) FROM {table}"))
        return True
    except ProgrammingError as refused:
        assert "permission denied" in str(refused)
        return False
    finally:
        await engine.dispose()


@pytest.mark.parametrize("service", sorted(TABLES))
async def test_a_service_reads_its_own_schema_and_no_other(migrated_database, service):
    app_url, _ = migrated_database

    for owner, table in TABLES.items():
        assert await _can_read(app_url, service, table) is (owner == service), f"{service} reading {table}"


async def test_every_service_may_append_to_the_audit_log_and_call_the_scope_functions(migrated_database):
    app_url, _ = migrated_database
    url = make_url(app_url).set(username="nafas_scheduling_svc", password="nafas")
    engine = create_async_engine(url)
    try:
        async with engine.begin() as connection:
            await connection.execute(text("SELECT nafas_current_doctor(), nafas_current_patient()"))
            await connection.execute(
                text(
                    "INSERT INTO audit.audit_log (service, actor_type, action, resource_type)"
                    " VALUES ('t', 'system', 'probe', 'x')"
                )
            )
            await connection.rollback()
    finally:
        await engine.dispose()

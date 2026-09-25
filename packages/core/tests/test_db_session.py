from uuid import uuid4

import pytest
from sqlalchemy import text

from nafas_core.db import session_scope

CURRENT_DOCTOR = text("SELECT current_setting('app.current_doctor_id', true)")


async def test_a_doctor_scope_is_visible_inside_the_transaction(database):
    doctor_id = uuid4()

    async with session_scope(doctor_id=doctor_id) as session:
        assert await session.scalar(CURRENT_DOCTOR) == str(doctor_id)


async def test_the_doctor_scope_does_not_outlive_its_transaction(database):
    """
    A pooled connection serves the next caller next; if the setting survived,
    that caller would run as the previous doctor.
    """
    async with session_scope(doctor_id=uuid4()):
        pass

    async with session_scope() as session:
        assert await session.scalar(CURRENT_DOCTOR) in (None, "")


async def test_an_exception_rolls_the_transaction_back(database):
    # a temporary table needs no privileges beyond connecting
    with pytest.raises(RuntimeError):
        async with session_scope() as session:
            await session.execute(text("CREATE TEMP TABLE rollback_probe (id int)"))
            raise RuntimeError("boom")

    async with session_scope() as session:
        assert await session.scalar(text("SELECT to_regclass('pg_temp.rollback_probe')")) is None


async def test_services_connect_as_a_role_rls_applies_to(database):
    """A superuser or table owner bypasses row-level security; the service role must be neither."""
    async with session_scope() as session:
        user, superuser = (
            await session.execute(text("SELECT current_user, usesuper FROM pg_user WHERE usename = current_user"))
        ).one()

    assert user == "nafas_service"
    assert superuser is False


async def test_current_doctor_is_null_without_a_scope(database):
    """Every policy compares against this, and NULL matches nothing."""
    doctor_id = uuid4()

    async with session_scope() as session:
        assert await session.scalar(text("SELECT nafas_current_doctor()")) is None
    async with session_scope(doctor_id=doctor_id) as session:
        assert await session.scalar(text("SELECT nafas_current_doctor()")) == doctor_id


async def test_migrations_enable_the_extensions(database):
    async with session_scope() as session:
        extensions = set((await session.scalars(text("SELECT extname FROM pg_extension"))).all())

    assert {"vector", "btree_gist"} <= extensions

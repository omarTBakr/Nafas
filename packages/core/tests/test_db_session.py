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
    async with session_scope() as session:
        await session.execute(text("CREATE TABLE IF NOT EXISTS rollback_probe (id int)"))
        await session.execute(text("DELETE FROM rollback_probe"))

    with pytest.raises(RuntimeError):
        async with session_scope() as session:
            await session.execute(text("INSERT INTO rollback_probe VALUES (1)"))
            raise RuntimeError("boom")

    async with session_scope() as session:
        assert await session.scalar(text("SELECT count(*) FROM rollback_probe")) == 0
        await session.execute(text("DROP TABLE rollback_probe"))


async def test_migrations_enable_the_extensions(database):
    async with session_scope() as session:
        extensions = set((await session.scalars(text("SELECT extname FROM pg_extension"))).all())

    assert {"vector", "btree_gist"} <= extensions

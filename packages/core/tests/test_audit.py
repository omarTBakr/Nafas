import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import create_async_engine

from nafas_core import audit
from nafas_core.db import get_engine


async def test_an_entry_is_appended_and_only_the_owner_can_read_it(database):
    patient_id, doctor_id = uuid.uuid4(), uuid.uuid4()

    await audit.record(
        service="test",
        actor=audit.Actor.DOCTOR,
        actor_id=doctor_id,
        action="read_timeline",
        resource_type="patient",
        resource_id=patient_id,
        patient_id=patient_id,
        doctor_id=doctor_id,
        detail={"entries": 3},
    )

    owner = create_async_engine(database)
    try:
        async with owner.connect() as connection:
            rows = (await connection.execute(text("SELECT actor_type, action, patient_id, detail FROM audit.audit_log"))).all()
    finally:
        await owner.dispose()
    assert [(r.actor_type, r.action, r.patient_id, r.detail) for r in rows] == [
        ("doctor", "read_timeline", patient_id, {"entries": 3})
    ]


@pytest.mark.parametrize(
    "statement",
    ["SELECT * FROM audit.audit_log", "UPDATE audit.audit_log SET action = 'x'", "DELETE FROM audit.audit_log"],
)
async def test_services_can_append_but_never_read_change_or_delete(database, statement):
    async with get_engine().connect() as connection:
        with pytest.raises(ProgrammingError, match="permission denied"):
            await connection.execute(text(statement))

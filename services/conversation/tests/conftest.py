import asyncio
import uuid
from dataclasses import dataclass

import pytest
from temporalio.client import Client
from temporalio.testing import WorkflowEnvironment

from nafas_core.config import get_setting
from nafas_core.db import session_scope
from nafas_core.enums.channel import Channel
from nafas_identity.logic.accounts import create_doctor_account
from nafas_identity.logic.patients import register_patient
from nafas_identity.logic.seed import seed_specializations


@pytest.fixture
async def temporal() -> Client:
    """
    A Temporal to run workflows on: the SDK's own test server when it can be
    fetched, otherwise the stack's Temporal on TEMPORAL_HOST (`make up`).
    Without either the test is skipped, as database tests are without Postgres.
    Each test uses its own task queue and ids, so a shared server is fine.
    """
    try:
        env = await WorkflowEnvironment.start_time_skipping()
    except RuntimeError:
        env = None
    if env is not None:
        yield env.client
        await env.shutdown()
        return

    host = get_setting().temporal_host
    try:
        client = await asyncio.wait_for(Client.connect(host), timeout=3)
    except (TimeoutError, RuntimeError, OSError) as exc:
        pytest.skip(f"no Temporal for workflow tests (test server unavailable, nothing at {host}): {exc}")
    yield client


@pytest.fixture
def task_queue() -> str:
    return f"conversation-test-{uuid.uuid4()}"


@dataclass
class Parties:
    doctor_id: uuid.UUID
    patient_id: uuid.UUID
    other_patient_id: uuid.UUID


@pytest.fixture
async def parties(database) -> Parties:
    """A doctor and two of their patients, made through identity's own logic."""
    async with session_scope() as session:
        await seed_specializations(session)
        doctor = await create_doctor_account(
            session,
            email="heart@example.com",
            password="correct horse battery",
            full_name_en="Dr Heart",
            full_name_ar="د. قلب",
            specialization_code="cardiology",
        )
    async with session_scope(doctor_id=doctor.id) as session:
        first = await register_patient(session, doctor_id=doctor.id, full_name="منى", channel=Channel.TELEGRAM, external_id="1")
        second = await register_patient(session, doctor_id=doctor.id, full_name="كريم", channel=Channel.TELEGRAM, external_id="2")
    return Parties(doctor.id, first.id, second.id)

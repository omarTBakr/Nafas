import asyncio
import os
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import make_url, text
from sqlalchemy.ext.asyncio import create_async_engine
from temporalio.client import Client
from temporalio.testing import WorkflowEnvironment

import nafas_core.config
from nafas_core.config import get_setting
from nafas_core.db.session import dispose_engine

# Where the stack must be there (CI, `make test`), a missing Postgres or
# Temporal fails the run instead of quietly skipping a third of the suite.
REQUIRE_SERVICES = os.environ.get("NAFAS_REQUIRE_SERVICES") == "1"


def _unavailable(message: str):
    if REQUIRE_SERVICES:
        pytest.fail(f"{message} (NAFAS_REQUIRE_SERVICES=1)", pytrace=False)
    pytest.skip(message)


# GPU services live outside the workspace with their own environment and
# lockfile; `make test` runs their suites there (`cd services/X && uv run pytest`)
collect_ignore_glob = ["services/dialect_router/*", "services/stt/*", "services/tts/*", "services/embeddings/*"]


@pytest.fixture(autouse=True)
def fresh_settings(monkeypatch, tmp_path):
    """
    Gives every test its own Settings, and its own scratch directory.

    The settings object is a module-level singleton, so without this a test
    that sets an environment variable would either see a cached instance from
    an earlier test or leak its own into a later one. Pointing TEMP_DIR at
    tmp_path keeps `temp_root` from creating `assets/` in the repository.
    """
    nafas_core.config._settings_instance = None
    monkeypatch.setenv("TEMP_DIR", str(tmp_path / "assets"))

    yield

    nafas_core.config._settings_instance = None


class RecordingBookingEvents:
    """Stands in for BookingWorkflow's starter: records what the scheduling API would have told Temporal."""

    def __init__(self):
        self.events: list[tuple[str, str]] = []

    async def held(self, appointment):
        self.events.append(("held", str(appointment.id)))
        return None

    async def confirmed(self, appointment):
        self.events.append(("confirmed", str(appointment.id)))

    async def cancelled(self, appointment, by):
        self.events.append((f"cancelled_by_{by}", str(appointment.id)))

    async def no_show(self, appointment):
        self.events.append(("no_show", str(appointment.id)))


@pytest.fixture(autouse=True)
def booking_events():
    """
    No test reaches Temporal through the scheduling API by accident: a test
    that wants to see what would have been sent takes this fixture.
    """
    from nafas_scheduling import events

    recorder = RecordingBookingEvents()
    events.set_events(recorder)
    yield recorder
    events.set_events(None)


class RecordingEscalationEvents:
    def __init__(self):
        self.answered_ids: list[str] = []

    async def answered(self, escalation):
        self.answered_ids.append(str(escalation.id))


@pytest.fixture(autouse=True)
def escalation_events():
    """No test signals an escalation's workflow through the conversation API by accident."""
    from nafas_conversation import events

    recorder = RecordingEscalationEvents()
    events.set_events(recorder)
    yield recorder
    events.set_events(None)


class RecordingIngestionEvents:
    def __init__(self):
        self.uploaded_ids: list[str] = []

    async def uploaded(self, document_id, doctor_id):
        self.uploaded_ids.append(document_id)
        return True


@pytest.fixture(autouse=True)
def ingestion_events():
    """No test starts an ingestion workflow through the clinical API by accident."""
    from nafas_clinical import events

    recorder = RecordingIngestionEvents()
    events.set_events(recorder)
    yield recorder
    events.set_events(None)


class RecordingConsultationEvents:
    def __init__(self):
        self.events: list[tuple[str, str]] = []

    async def finished(self, consultation_id, doctor_id):
        self.events.append(("finished", consultation_id))
        return True

    async def approved(self, consultation_id):
        self.events.append(("approved", consultation_id))
        return True

    async def discarded(self, consultation_id):
        self.events.append(("discarded", consultation_id))
        return True


@pytest.fixture(autouse=True)
def consultation_events():
    """No test starts or signals a consultation's workflow through its API by accident."""
    from nafas_consultation import events

    recorder = RecordingConsultationEvents()
    events.set_events(recorder)
    yield recorder
    events.set_events(None)


# --- temporal -------------------------------------------------------------


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
        _unavailable(f"no Temporal for workflow tests (test server unavailable, nothing at {host}): {exc}")
    yield client


@pytest.fixture
def task_queue() -> str:
    return f"conversation-test-{uuid.uuid4()}"


# --- the stack's other services --------------------------------------------


def _reachable(host: str, port: int) -> bool:
    import socket

    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except OSError:
        return False


@pytest.fixture
def mailpit() -> str:
    """The stack's Mailpit (SMTP on :1025, its API on :8025): real email, caught before it leaves."""
    if not (_reachable("localhost", 1025) and _reachable("localhost", 8025)):
        _unavailable("no Mailpit for email tests at localhost:1025 (`make up`)")
    import httpx

    httpx.delete("http://localhost:8025/api/v1/messages", timeout=5)
    return "http://localhost:8025"


@pytest.fixture
def s3_bucket(monkeypatch) -> str:
    """A fresh bucket on the stack's S3 (SeaweedFS on :8333), for tests of real object storage."""
    if not _reachable("localhost", 8333):
        _unavailable("no S3 for storage tests at localhost:8333 (`make up`)")
    bucket = f"test-{uuid.uuid4().hex[:12]}"
    monkeypatch.setenv("S3_BUCKET", bucket)
    nafas_core.config._settings_instance = None
    return bucket


# --- database -------------------------------------------------------------
#
# Tests that take the `database` fixture run against a real Postgres, in a
# database of their own (nafas_test on the server DATABASE_URL points at) that
# is created if missing, given the roles, and migrated to head once per run.
# The test then connects as nafas_service, exactly as a service does, so
# row-level security applies. Without a reachable Postgres they are skipped,
# so the rest of the suite runs anywhere.

TEST_DATABASE = "nafas_test"
ROLES_SQL = Path(__file__).parent / "deploy" / "postgres" / "roles.sql"


def _test_urls() -> tuple[str, str]:
    """(app URL, owner URL) for the test database."""
    settings = nafas_core.config.Settings()
    app, owner = (
        make_url(url).set(database=TEST_DATABASE).render_as_string(hide_password=False)
        for url in (settings.database_url, settings.database_owner_url)
    )
    return app, owner


async def _prepare_server(owner_url: str) -> None:
    """Creates the roles and the test database if missing, through the server's `postgres` database."""
    target = make_url(owner_url)
    admin = create_async_engine(target.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        async with admin.connect() as connection:
            await connection.exec_driver_sql(ROLES_SQL.read_text())
            exists = await connection.scalar(text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": target.database})
            if not exists:
                await connection.execute(text(f'CREATE DATABASE "{target.database}"'))
    finally:
        await admin.dispose()


async def _empty_service_tables(owner_url: str) -> None:
    """Truncates every table in every service schema, so each test starts from nothing."""
    engine = create_async_engine(owner_url)
    try:
        async with engine.begin() as connection:
            tables = (
                (
                    await connection.execute(
                        text(
                            "SELECT format('%I.%I', schemaname, tablename) FROM pg_tables"
                            " WHERE schemaname NOT IN ('public', 'pg_catalog', 'information_schema')"
                        )
                    )
                )
                .scalars()
                .all()
            )
            if tables:
                await connection.execute(text(f"TRUNCATE {', '.join(tables)} CASCADE"))
    finally:
        await engine.dispose()


@pytest.fixture(scope="session")
def migrated_database() -> tuple[str, str]:
    app_url, owner_url = _test_urls()
    try:
        asyncio.run(asyncio.wait_for(_prepare_server(owner_url), timeout=5))
    except (OSError, TimeoutError) as exc:
        _unavailable(f"no Postgres for database tests at {make_url(owner_url).render_as_string()}: {exc}")

    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", owner_url)
    command.upgrade(config, "head")

    return app_url, owner_url


@pytest.fixture
async def database(migrated_database, monkeypatch):
    """
    Points nafas_core.db at the empty, migrated test database for one test.

    Yields the owner URL, for the rare test that must set up or inspect rows
    past row-level security; everything else goes through session_scope.
    """
    app_url, owner_url = migrated_database
    await _empty_service_tables(owner_url)

    monkeypatch.setenv("DATABASE_URL", app_url)
    monkeypatch.setenv("DATABASE_OWNER_URL", owner_url)
    await dispose_engine()

    yield owner_url

    await dispose_engine()

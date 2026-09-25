import asyncio
import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import make_url, text
from sqlalchemy.ext.asyncio import create_async_engine

import nafas_core.config
from nafas_core.db.session import dispose_engine

# GPU services live outside the workspace with their own environment and
# lockfile; `make test` runs their suites there (`cd services/X && uv run pytest`)
collect_ignore_glob = ["services/dialect_router/*"]


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


# --- database -------------------------------------------------------------
#
# Tests that take the `database` fixture run against a real Postgres, in a
# database of their own (nafas_test by default, TEST_DATABASE_URL to change it)
# that is created if missing and migrated to head once per run. Without a
# reachable Postgres they are skipped, so the rest of the suite runs anywhere.


def test_database_url() -> str:
    if url := os.environ.get("TEST_DATABASE_URL"):
        return url

    return make_url(nafas_core.config.Settings().database_url).set(database="nafas_test").render_as_string(hide_password=False)


test_database_url.__test__ = False  # a helper, not a test, despite its name


async def _ensure_database(url: str) -> None:
    """Creates the test database through the server's `postgres` database if it is missing."""
    target = make_url(url)
    admin = create_async_engine(target.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        async with admin.connect() as connection:
            exists = await connection.scalar(text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": target.database})
            if not exists:
                await connection.execute(text(f'CREATE DATABASE "{target.database}"'))
    finally:
        await admin.dispose()


@pytest.fixture(scope="session")
def migrated_database_url() -> str:
    url = test_database_url()
    try:
        asyncio.run(asyncio.wait_for(_ensure_database(url), timeout=5))
    except (OSError, TimeoutError) as exc:
        pytest.skip(f"no Postgres for database tests at {make_url(url).render_as_string()}: {exc}")

    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")

    return url


@pytest.fixture
async def database(migrated_database_url, monkeypatch):
    """Points DATABASE_URL, and so nafas_core.db, at the migrated test database for one test."""
    monkeypatch.setenv("DATABASE_URL", migrated_database_url)
    await dispose_engine()

    yield migrated_database_url

    await dispose_engine()

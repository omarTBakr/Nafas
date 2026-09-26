from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from nafas_core.config import get_setting

# the Postgres settings row-level security policies read
CURRENT_DOCTOR_SETTING = "app.current_doctor_id"
CURRENT_PATIENT_SETTING = "app.current_patient_id"

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """A singleton engine for DATABASE_URL; one connection pool per process."""
    global _engine
    if _engine is None:
        # pre_ping: a pooled connection dropped by a Postgres restart is
        # replaced quietly instead of failing the next request
        _engine = create_async_engine(get_setting().database_url, pool_pre_ping=True)

    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        # expire_on_commit off: objects stay readable after the transaction,
        # which an async caller cannot lazily reload anyway
        _sessionmaker = async_sessionmaker(get_engine(), expire_on_commit=False)

    return _sessionmaker


async def dispose_engine() -> None:
    """Closes the pool; for shutdown, and for tests that point at another database."""
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None


@asynccontextmanager
async def session_scope(doctor_id: UUID | None = None, patient_id: UUID | None = None) -> AsyncIterator[AsyncSession]:
    """
    One transaction: committed on success, rolled back on any exception.

    With `doctor_id`, the transaction runs as that doctor: row-level security
    shows their rows. With `patient_id`, it runs as that patient: RLS shows
    the patient's own rows (their profile, their appointments with any
    doctor). The settings are transaction-local (`set_config(..., true)`), so
    they end with the transaction and can never leak onto a pooled connection
    that serves the next caller.

    With neither, RLS-protected tables show nothing — the safe default.
    System jobs that genuinely need every row connect as a role that bypasses
    RLS instead of weakening this.
    """
    async with get_sessionmaker()() as session, session.begin():
        for name, value in ((CURRENT_DOCTOR_SETTING, doctor_id), (CURRENT_PATIENT_SETTING, patient_id)):
            if value is not None:
                await session.execute(text("SELECT set_config(:name, :value, true)"), {"name": name, "value": str(value)})
        yield session

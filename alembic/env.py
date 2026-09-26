"""Alembic environment: migrations run as the owner, DATABASE_OWNER_URL from nafas_core.config.

`uv run alembic upgrade head` to migrate; `uv run alembic revision
--autogenerate -m "..."` to draft a migration from the models, which then gets
read and edited by hand — autogenerate misses exclusion constraints, RLS
policies and extensions, and those are exactly what this schema relies on.

One history covers every service's schema (docs/PLAN.md §4), so migrations
from different services never race each other.
"""

import asyncio
import importlib
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from nafas_core.config import get_setting
from nafas_core.db.base import Base

# Every service's ORM module. Autogenerate only sees tables whose classes are
# imported by the time it reads Base.metadata, so a service's models module is
# added here in the same commit that creates the service.
MODEL_MODULES: list[str] = [
    "nafas_identity.models",
    "nafas_scheduling.models",
    "nafas_conversation.models",
    "nafas_clinical.models",
]

for module in MODEL_MODULES:
    importlib.import_module(module)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def include_name(name, type_, parent_names) -> bool:
    """Compare only the service schemas the models declare; leave public and Postgres's own alone."""
    if type_ == "schema":
        return name in {table.schema for table in target_metadata.tables.values()}

    return True


def include_object(obj, name, type_, reflected, compare_to) -> bool:
    """
    Leave foreign keys into another service's schema out of the comparison.

    Services declare them in their migrations but not on their ORM models, so
    that no service needs another's code to run (see nafas_scheduling.models);
    compared, every one would look like something to drop.
    """
    if type_ == "foreign_key_constraint":
        return obj.referred_table.schema == obj.table.schema

    return True


# every service keeps its tables in a schema of its own, which autogenerate
# only looks at when asked
COMPARE_OPTIONS = {"include_schemas": True, "include_name": include_name, "include_object": include_object}


def database_url() -> str:
    """A URL set on the Config (the test suite does this) wins over DATABASE_OWNER_URL."""
    return config.get_main_option("sqlalchemy.url") or get_setting().database_owner_url


def run_migrations_offline() -> None:
    """Renders the migrations as SQL (`alembic upgrade head --sql`) without connecting."""
    context.configure(
        url=database_url(),
        target_metadata=target_metadata,
        **COMPARE_OPTIONS,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, **COMPARE_OPTIONS)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    engine = create_async_engine(database_url(), poolclass=pool.NullPool)

    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_async_migrations())

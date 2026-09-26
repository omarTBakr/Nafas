"""Database access: the engine, sessions scoped to a doctor, and the ORM base.

Each service defines its own models on `Base`, in a Postgres schema of its
own, and registers the module in alembic/env.py.

Every clinical table carries `doctor_id`, and Postgres row-level security
filters on `app.current_doctor_id`. `session_scope(doctor_id=...)` sets that
for the length of one transaction, so a query that forgets its WHERE clause
still cannot see another doctor's rows.
"""

from nafas_core.db.base import Base
from nafas_core.db.session import enter_scope, get_engine, get_sessionmaker, session_scope

__all__ = ["Base", "enter_scope", "get_engine", "get_sessionmaker", "session_scope"]

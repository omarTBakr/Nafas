"""Database access: the engine, sessions scoped to a doctor, and the ORM models.

Every clinical table carries `doctor_id`, and Postgres row-level security
filters on `app.current_doctor_id`. `session_scope(doctor_id=...)` sets that
for the length of one transaction, so a query that forgets its WHERE clause
still cannot see another doctor's rows.
"""

from utils.db.base import Base
from utils.db.session import get_engine, get_sessionmaker, session_scope

__all__ = ["Base", "get_engine", "get_sessionmaker", "session_scope"]

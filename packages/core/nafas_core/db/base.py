from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# Named constraints, so Alembic can drop or alter them later by name rather
# than guessing at whatever Postgres generated.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """
    Root of every ORM model; its metadata is what Alembic autogenerates from.

    eager_defaults off: SQLAlchemy would otherwise read server defaults back
    with INSERT ... RETURNING, and Postgres applies row-level security *read*
    policies to returned rows, so inserting a row the writer may not yet see
    (a patient before their doctor link) would fail. Models give every
    defaulted column a Python-side default as well, so nothing needs reading back.
    """

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    __mapper_args__ = {"eager_defaults": False}

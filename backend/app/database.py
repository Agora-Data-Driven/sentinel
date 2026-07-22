"""SQLAlchemy 2.0 engine, session factory, and declarative Base.

Works with SQLite (local, zero-setup) or PostgreSQL (prod) transparently via ``DATABASE_URL``.
"""
from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings

_is_sqlite = settings.database_url.startswith("sqlite")

engine = create_engine(
    settings.database_url,
    # check_same_thread only matters for SQLite + threaded servers (uvicorn).
    connect_args={"check_same_thread": False} if _is_sqlite else {},
    pool_pre_ping=not _is_sqlite,
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    """Declarative base shared by every model."""


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency: yields a session and always closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_all() -> None:
    """Create every table, then add any newly-introduced columns (non-destructive migration).

    ``metadata.create_all`` makes MISSING tables but never ALTERs existing ones, so as the models
    grow we add new columns here idempotently — no data wipe, no Alembic run needed for simple adds.
    """
    from . import models  # noqa: F401  (registers all mappers on Base.metadata)

    Base.metadata.create_all(bind=engine)
    _ensure_columns()


# New columns added to already-existing tables (table -> [(column, sql_type)]).
_ADDED_COLUMNS = {
    "users": [("monthly_salary", "FLOAT")],
    "personal_records": [("detail", "VARCHAR(160)")],
}


def _ensure_columns() -> None:
    from sqlalchemy import inspect, text

    insp = inspect(engine)
    tables = set(insp.get_table_names())
    with engine.begin() as conn:
        for table, cols in _ADDED_COLUMNS.items():
            if table not in tables:
                continue
            existing = {c["name"] for c in insp.get_columns(table)}
            for name, sql_type in cols:
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {sql_type}"))

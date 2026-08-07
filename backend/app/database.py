"""SQLAlchemy 2.0 engine, session factory, and declarative Base.

Works with SQLite (local, zero-setup) or PostgreSQL (prod) transparently via ``DATABASE_URL``.
"""
from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings

_is_sqlite = settings.database_url.startswith("sqlite")

# 🔴 THE POOL IS EXPLICIT, and the numbers are a COMPROMISE between two ceilings (2026-08-07).
#
# Every endpoint in this app is a plain `def`, which FastAPI runs in anyio's threadpool — **40 threads
# by default** — against SQLAlchemy's default pool of `pool_size=5, max_overflow=10`, i.e. **15**
# connections. Threads 16+ blocked in `pool_timeout` (30s by default) waiting for one, which is
# invisible while every query is fast and vicious the moment one is not: a board request used to hold
# its connection for the whole multi-second query storm, so a handful of concurrent users turned
# "slow" into "hung" with nothing in the logs but a long request.
#
# 🔴 The answer is NOT "one connection per thread". Cloud SQL `db-f1-micro` allows about **25
# connections in total**, shared with the seed job, migrations and any psql — so a pool sized to the
# threadpool (40) would starve the estate from a single instance, and `x max-instances` would ask for
# hundreds. The real fix was making the HOLD short (`serializers.CardPrefetch` took a board request
# from ~880ms to ~60ms); the pool only has to cover what is genuinely in flight. See `config.py` for
# the numbers and for what to change if a slow endpoint ever appears.
#
# `pool_recycle` is for Cloud SQL, which drops idle connections server-side — `pool_pre_ping` already
# catches that with a round-trip per checkout, and recycling before the far end does means it rarely
# has to. SQLite ignores all of it (single file, `NullPool`-ish semantics via check_same_thread).
_pool_kwargs = {} if _is_sqlite else {
    "pool_size": settings.db_pool_size,
    "max_overflow": settings.db_max_overflow,
    "pool_timeout": settings.db_pool_timeout,
    "pool_recycle": 1800,
}

engine = create_engine(
    settings.database_url,
    # check_same_thread only matters for SQLite + threaded servers (uvicorn).
    connect_args={"check_same_thread": False} if _is_sqlite else {},
    pool_pre_ping=not _is_sqlite,
    future=True,
    **_pool_kwargs,
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

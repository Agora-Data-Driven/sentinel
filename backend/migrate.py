"""Bring the database schema up to date at container startup, safely, in every state.

Sentinel historically created its schema with SQLAlchemy ``create_all`` (see DEPLOY.md), so an
already-running production database has all the tables but no Alembic version stamp. Blindly running
``alembic upgrade head`` there would try to re-create existing tables and fail. This script picks the
right action:

  * fresh/empty DB            -> ``upgrade head``  (migrations build everything)
  * existing schema, unstamped-> ``stamp head``    (adopt what create_all already built)
  * already stamped           -> ``upgrade head``  (apply any pending migrations; no-op if none)

Idempotent and safe to run on every boot.
"""
from __future__ import annotations

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from app.database import engine


def main() -> None:
    tables = set(inspect(engine).get_table_names())
    cfg = Config("alembic.ini")
    already_stamped = "alembic_version" in tables
    # A pre-Alembic schema built by create_all: core tables exist but nothing is stamped yet.
    legacy_unstamped = "users" in tables and not already_stamped

    if legacy_unstamped:
        print("[migrate] existing unstamped schema detected - adopting it with `stamp head`.")
        command.stamp(cfg, "head")
    else:
        print("[migrate] running `upgrade head`.")
        command.upgrade(cfg, "head")
    print("[migrate] done.")


if __name__ == "__main__":
    main()

"""tasks: start_date, completed_at, archived, on_hold/hold_reason/resume_to, review_state/reviewer_id

Stage 2 of docs/TASKBOARD_REBUILD.md — the workflow fields the board was missing (M2–M5). One
revision because they ship as one stage and every one of them is a nullable add on `tasks`:

* `start_date`   (M5) — when the work starts, not when it is owed. Atrium always had it and renders
  the client a Started → Going live timeline; it is part of the client-safe projection.
* `completed_at` (M4) — 🔴 the throughput fix (§2.4h). "Done this week" was counted off
  `updated_at`, so fixing a typo on a task finished in March re-dated its completion to today.
* `archived`     (M4) — Past work. Left in the Completed column, finished services turn it into a
  graveyard and every count on the board stops meaning anything.
* `on_hold` / `hold_reason` / `resume_to` (M3) — parking that REMEMBERS the column it left.
  `hold_reason` is internal and deliberately absent from `task_bridge.SAFE`.
* `review_state` / `reviewer_id` (M2, decision D5) — a team lead's approval gates completion.
  "For Review" was retired as a status on 2026-07-30 and nothing replaced it, so "Done" was one
  person's unilateral claim.

Existing rows read as: never started, never completed, not filed, not on hold, never reviewed —
which is exactly right, and why every column is nullable (booleans defaulted server-side).

EXISTENCE-GUARDED, like a9c4e7f2d5b8 / b6d2f8a4c7e9 / c4e8b1f6a3d7 / d7a2c9e4b8f1:
`main._ensure_columns` is the path these take to production (deploys don't run Alembic reliably), so
by the time this revision runs the columns are often already there and an unguarded add would fail.

Revision ID: e8b3f5c7a2d9
Revises: d7a2c9e4b8f1
Create Date: 2026-08-03 16:40:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'e8b3f5c7a2d9'
down_revision = 'd7a2c9e4b8f1'
branch_labels = None
depends_on = None

_TABLE = 'tasks'

# (column, type, server_default). A server_default is what makes the two booleans safe on an
# existing table: without it every current row would read NULL, and `not None` is not False.
_COLUMNS = (
    ('start_date', sa.Date(), None),
    ('completed_at', sa.DateTime(), None),
    ('archived', sa.Boolean(), sa.text('false')),
    ('on_hold', sa.Boolean(), sa.text('false')),
    ('hold_reason', sa.Text(), None),
    ('resume_to', sa.String(length=32), None),
    ('review_state', sa.String(length=20), None),
    ('reviewer_id', sa.Integer(), None),
)


def _columns() -> set:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table(_TABLE):
        return set()
    return {c['name'] for c in insp.get_columns(_TABLE)}


def _indexes() -> set:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table(_TABLE):
        return set()
    return {i['name'] for i in insp.get_indexes(_TABLE)}


def upgrade() -> None:
    have = _columns()
    if not have:
        return  # table not built yet — create_all / an earlier revision owns that
    for name, type_, default in _COLUMNS:
        if name not in have:
            op.add_column(_TABLE, sa.Column(name, type_, nullable=True, server_default=default))
    # The board filters on `archived` on EVERY list call (it is what separates the board from Past
    # work), so it is the one of the eight worth an index.
    if 'ix_tasks_archived' not in _indexes():
        op.create_index('ix_tasks_archived', _TABLE, ['archived'])

    # Rows that predate the columns: `archived` / `on_hold` must read False, not NULL. The
    # server_default only applies to rows inserted after the ALTER, so backfill explicitly.
    # 🔴 `false`, never `0`: Postgres rejects an integer default (or comparison) on a boolean column
    # -- "default expression is of type integer" -- and SQLite has understood `false` since 3.23.
    # Same literal in _ensure_columns, for the same reason.
    bind = op.get_bind()
    for col in ('archived', 'on_hold'):
        bind.execute(sa.text(f"UPDATE {_TABLE} SET {col} = false WHERE {col} IS NULL"))

    # 🔴 `completed_at` is deliberately NOT backfilled from `updated_at`. That is the very number
    # this column exists to stop trusting: it would date every historically-finished task to
    # whenever someone last edited it, and land a pile of them in "completed this week". A task
    # finished before the stamp existed has no honest completion date, so it keeps none.


def downgrade() -> None:
    have = _columns()
    if 'ix_tasks_archived' in _indexes():
        try:
            op.drop_index('ix_tasks_archived', table_name=_TABLE)
        except Exception:      # index absent, or dropped with the column
            pass
    for name, _type, _default in reversed(_COLUMNS):
        if name in have:
            op.drop_column(_TABLE, name)

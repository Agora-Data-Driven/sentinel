"""composite indexes for the two queries the task board actually runs

`routers/tasks.list_tasks` — the single most-requested endpoint in the app, and the one every SSE
`task` event makes every open tab re-run — is:

    SELECT ... FROM tasks WHERE archived = false ORDER BY updated_at DESC

`archived` had a single-column index and `updated_at` had none, so Postgres could only filter and
then SORT the whole result set on every board load. `ix_tasks_board` answers both halves from one
ordered index scan (read backwards for the DESC).

`ix_tasks_assignee_board` covers the other common shape — the `?assignee_id=` filter and every
per-person rollup, which always also discriminate on `archived`.

Both are plain (non-unique) additions: no data is read, written or moved, and no column changes.
The existing single-column indexes on `archived` and `assigned_to_id` are intentionally kept — other
callers use them, and dropping an index is a separate decision.

EXISTENCE-GUARDED, following a9c4e7f2d5b8: `create_all` runs on every boot and will have already
built these from the model's `__table_args__` on any DB that started after this change, so an
unguarded `create_index` would fail there. On such a DB this is a clean no-op.

🔴 A note for whoever runs this against a much larger table than today's: a plain CREATE INDEX takes
a write lock for its duration. On the current `tasks` table (~800 rows) that is a sub-second pause
during a deploy that is already restarting the service. If this table ever reaches millions of rows,
build these with CREATE INDEX CONCURRENTLY by hand OUTSIDE Alembic instead — it cannot run inside
the transaction Alembic wraps a migration in.

Revision ID: b2e9d5f3a7c1
Revises: a3f7c2e9d4b6
Create Date: 2026-08-13 10:15:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'b2e9d5f3a7c1'
down_revision = 'a3f7c2e9d4b6'
branch_labels = None
depends_on = None


_INDEXES = (
    ('ix_tasks_board', ['archived', 'updated_at']),
    ('ix_tasks_assignee_board', ['assigned_to_id', 'archived']),
)


def _existing() -> set[str]:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table('tasks'):
        return set()
    return {ix['name'] for ix in insp.get_indexes('tasks')}


def upgrade() -> None:
    have = _existing()
    for name, columns in _INDEXES:
        if name not in have:
            op.create_index(name, 'tasks', columns)


def downgrade() -> None:
    have = _existing()
    for name, _columns in _INDEXES:
        if name in have:
            op.drop_index(name, table_name='tasks')

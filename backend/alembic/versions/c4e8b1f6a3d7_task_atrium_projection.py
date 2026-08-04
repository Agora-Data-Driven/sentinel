"""tasks.atrium_task_id + tasks.atrium_sync_error — the Atrium projection

Sharing a task with a client used to set `tasks.atrium_visible = True` and create NOTHING in
Atrium (`atrium_tasks.add_task` was called from nowhere), so the flag referred to a card that did
not exist while the drawer reported "✓ In Atrium". See docs/TASKBOARD_REBUILD.md §1.2.

Two columns make the bridge real:

* `atrium_task_id`  — the Atrium card this row projects onto, returned by /api/internal/task-add.
  Written only once the card really exists, so `atrium_visible AND atrium_task_id IS NULL` is
  exactly the backlog of stale pre-fix rows the reconcile report asks a human about (D15).
* `atrium_sync_error` — why the last client-safe push failed. NULL means the client's card is
  current. A failed push is fail-LOUD by design: a silently stale client card is the defect this
  stage removes, so the reason lives on the row and the board renders it.

EXISTENCE-GUARDED on purpose. `main._ensure_columns` is the path these columns take to
production (prod's boot runs both, and create_all usually wins the race), so by the time this
revision runs the columns are frequently already present — an unguarded add_column would fail
there. Mirrors a9c4e7f2d5b8 and b6d2f8a4c7e9, which exist for the same reason.

Revision ID: c4e8b1f6a3d7
Revises: b6d2f8a4c7e9
Create Date: 2026-08-03 12:10:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'c4e8b1f6a3d7'
down_revision = 'b6d2f8a4c7e9'
branch_labels = None
depends_on = None

_TABLE = 'tasks'


def _columns() -> set:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table(_TABLE):
        return set()
    return {c['name'] for c in insp.get_columns(_TABLE)}


def upgrade() -> None:
    have = _columns()
    if not have:
        return  # no tasks table yet — create_all/earlier revisions own that
    if 'atrium_task_id' not in have:
        op.add_column(_TABLE, sa.Column('atrium_task_id', sa.String(length=64), nullable=True))
        op.create_index('ix_tasks_atrium_task_id', _TABLE, ['atrium_task_id'])
    if 'atrium_sync_error' not in have:
        op.add_column(_TABLE, sa.Column('atrium_sync_error', sa.Text(), nullable=True))


def downgrade() -> None:
    have = _columns()
    if 'atrium_sync_error' in have:
        op.drop_column(_TABLE, 'atrium_sync_error')
    if 'atrium_task_id' in have:
        # The index rides with the column on SQLite's batch path; drop it explicitly where it can.
        try:
            op.drop_index('ix_tasks_atrium_task_id', table_name=_TABLE)
        except Exception:  # index absent or already gone with the column
            pass
        op.drop_column(_TABLE, 'atrium_task_id')

"""task_vocab.vocab_key + task_vocab.stage — the status key/label split

`task_vocab.name` is a LABEL: Manage renames it and cascades the new string onto every task row
(`manage._rename_in_tasks`). But `atrium_tasks.STAGE_BY_STATUS` was a literal dict keyed by that
display string, so renaming a status silently broke the Atrium bridge for every client card — a
move then answered a bare 400 "Invalid status". Renaming "Blocked" to "Parked" walks straight into
it, which is why this lands BEFORE that rename (docs/TASKBOARD_REBUILD.md §5.1).

Two columns give a status an identity its label cannot break:

* `vocab_key` — a stable slug, minted once from the first name and never changed afterwards.
  Named `vocab_key` rather than `key` because a bare `key` is a keyword in enough dialects that it
  is not worth the risk for a column only testable against SQLite locally.
* `stage`     — the Atrium stage a status projects onto. Required for `kind="status"` from now on
  (decision D13); `task_config` backfills the five seeded statuses and falls back to the legacy
  literal map for anything older.

EXISTENCE-GUARDED, like a9c4e7f2d5b8 / b6d2f8a4c7e9 / c4e8b1f6a3d7: `main._ensure_columns` is the
path these take to production, so by the time this revision runs the columns are often already
present and an unguarded add_column would fail.

Revision ID: d7a2c9e4b8f1
Revises: c4e8b1f6a3d7
Create Date: 2026-08-03 13:05:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'd7a2c9e4b8f1'
down_revision = 'c4e8b1f6a3d7'
branch_labels = None
depends_on = None

_TABLE = 'task_vocab'


def _columns() -> set:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table(_TABLE):
        return set()
    return {c['name'] for c in insp.get_columns(_TABLE)}


def upgrade() -> None:
    have = _columns()
    if not have:
        return  # table not built yet — create_all / an earlier revision owns that
    if 'vocab_key' not in have:
        op.add_column(_TABLE, sa.Column('vocab_key', sa.String(length=40), nullable=True))
        op.create_index('ix_task_vocab_vocab_key', _TABLE, ['vocab_key'])
    if 'stage' not in have:
        op.add_column(_TABLE, sa.Column('stage', sa.String(length=24), nullable=True))

    # Backfill the five shipped statuses so an existing board keeps a working bridge the moment
    # this lands. Matched on the CURRENT label, which is still the shipped one at this point.
    seeded = {
        'To Do': ('todo', 'todo'),
        'In Progress': ('in_progress', 'in_progress'),
        'Revision Needed': ('revision', 'revision'),
        'Completed': ('completed', 'completed'),
        'Blocked': ('blocked', 'blocked'),
    }
    bind = op.get_bind()
    for label, (key, stage) in seeded.items():
        bind.execute(
            sa.text(f"UPDATE {_TABLE} SET vocab_key = COALESCE(vocab_key, :k), "
                    f"stage = COALESCE(stage, :s) WHERE kind = 'status' AND name = :n"),
            {"k": key, "s": stage, "n": label},
        )


def downgrade() -> None:
    have = _columns()
    if 'stage' in have:
        op.drop_column(_TABLE, 'stage')
    if 'vocab_key' in have:
        try:
            op.drop_index('ix_task_vocab_vocab_key', table_name=_TABLE)
        except Exception:      # index absent, or dropped with the column
            pass
        op.drop_column(_TABLE, 'vocab_key')

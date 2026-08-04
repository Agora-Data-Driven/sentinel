"""atrium_approvals: drop the three never-written response columns (WP 0.4)

Stage 0.4 of docs/TASKBOARD_REBUILD.md — "retire the dead surface".

`client_response`, `responded_at` and `revision_notes` were added for a client→Sentinel reply path
that was never built. NOTHING has ever written them: a client's reply reaches Atrium's workspace
JSON and comes back over the internal bridge as a COMMENT, never into this table. So all three have
been permanently NULL on every row in every environment, while reading exactly like "no client has
ever responded to anything" — a dead column that looks like an answer is worse than no column.

What replaces them is the reverse channel (D4 / WP 3.5), which lands on `TaskComment`, where the
conversation already lives and where the board already renders it.

`sent_at` and the table itself are KEPT: they are the share log, and `task_bridge` still appends a
row each time a task is published.

EXISTENCE-GUARDED in both directions, like every other revision here. `main._ensure_columns` is the
path schema changes actually take to production (deploys don't run Alembic reliably) — but it only
ever ADDS columns, so unlike an add-migration this one is the ONLY thing that removes them. That
asymmetry is deliberate and safe: an extra nullable column in prod is inert, and the ORM no longer
maps it.

🔴 SQLite needs batch mode for DROP COLUMN (it rebuilds the table). Postgres does not care. Using
`batch_alter_table` covers both, which matters because dev runs SQLite and prod runs Cloud SQL.

Revision ID: f1a6d3c8b5e2
Revises: e8b3f5c7a2d9
Create Date: 2026-08-04 09:20:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'f1a6d3c8b5e2'
down_revision = 'e8b3f5c7a2d9'
branch_labels = None
depends_on = None

_TABLE = 'atrium_approvals'

# (column, type) — the type is only needed to put them back on downgrade.
_COLUMNS = (
    ('client_response', sa.String(length=40)),
    ('responded_at', sa.DateTime()),
    ('revision_notes', sa.Text()),
)


def _columns() -> set:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table(_TABLE):
        return set()
    return {c['name'] for c in insp.get_columns(_TABLE)}


def upgrade() -> None:
    have = _columns()
    if not have:
        return  # table not built yet — create_all / an earlier revision owns that
    doomed = [name for name, _type in _COLUMNS if name in have]
    if not doomed:
        return
    with op.batch_alter_table(_TABLE) as batch:
        for name in doomed:
            batch.drop_column(name)


def downgrade() -> None:
    have = _columns()
    if not have:
        return
    with op.batch_alter_table(_TABLE) as batch:
        for name, type_ in _COLUMNS:
            if name not in have:
                batch.add_column(sa.Column(name, type_, nullable=True))

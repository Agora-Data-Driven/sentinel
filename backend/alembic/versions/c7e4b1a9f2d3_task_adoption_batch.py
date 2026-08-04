"""tasks.adoption_batch: make importing live client cards reversible (WP 3.4)

Adoption imports cards that originated in Atrium into linked Sentinel rows (§4). It is the one
work package that touches LIVE CLIENT DATA, and this single column is what makes it safe to run:
every row a given run creates carries the same batch id, so `task_adoption.revert` can remove
exactly that run and nothing else.

Without it, an import is a one-way door over data nobody can afford to guess about — you would be
left picking adopted rows out of the table by timestamp and hoping.

NULL for every task a human raised, which is almost all of them, so it costs nothing on read.
Indexed because revert queries by it.

Existence-guarded like every revision here: `main._ensure_columns` is the path a column actually
takes to production (deploys don't run Alembic reliably), so by the time this runs the column is
often already present.

Revision ID: c7e4b1a9f2d3
Revises: b5d9e2a7c3f4
Create Date: 2026-08-04 12:20:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'c7e4b1a9f2d3'
down_revision = 'b5d9e2a7c3f4'
branch_labels = None
depends_on = None

_TABLE = 'tasks'
_COLUMN = 'adoption_batch'
_INDEX = 'ix_tasks_adoption_batch'


def _cols() -> set:
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
    have = _cols()
    if not have:
        return
    if _COLUMN not in have:
        op.add_column(_TABLE, sa.Column(_COLUMN, sa.String(length=40), nullable=True))
    if _INDEX not in _indexes():
        op.create_index(_INDEX, _TABLE, [_COLUMN])


def downgrade() -> None:
    if _INDEX in _indexes():
        try:
            op.drop_index(_INDEX, table_name=_TABLE)
        except Exception:      # already gone, or dropped with the column
            pass
    if _COLUMN in _cols():
        op.drop_column(_TABLE, _COLUMN)

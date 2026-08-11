"""tasks.origin — planned ahead, or added during the day

The Sentinel task-placement guidelines split the board's work in two: §1 makes the Team Lead
responsible for placing PLANNED work before the workday starts, §3 makes the worker responsible for
ADDING whatever comes up afterwards, "so Sentinel accurately reflects the actual work completed
during the day". Every task looked equally planned, so a team's reactive load was invisible.

🔴 NULLABLE WITH NO SERVER DEFAULT, deliberately. Every task that predates this column is genuinely
unclassified, and a default of 'planned' would assert something nobody knows about thousands of rows.
NULL reports as unknown and is excluded from both counts — the same contract the on-time rate follows
for undated completions. See `services/task_origin.py` for the classification rule and its limits.

EXISTENCE-GUARDED, like d4a9f1c8e35b and a9c4e7f2d5b8: `main._ensure_columns` is the path this column
takes to production, and it will usually have added it already by the time anyone replays this
revision. An unguarded add_column would fail there.

Revision ID: a3f7c2e9d4b6
Revises: d4a9f1c8e35b
Create Date: 2026-08-11 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'a3f7c2e9d4b6'
down_revision = 'd4a9f1c8e35b'
branch_labels = None
depends_on = None

TABLE = 'tasks'
COLUMN = 'origin'


def _has_column(table: str, column: str) -> bool:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table(table):
        return False
    return any(c['name'] == column for c in insp.get_columns(table))


def upgrade() -> None:
    if _has_column(TABLE, COLUMN):
        return
    op.add_column(TABLE, sa.Column(COLUMN, sa.String(length=12), nullable=True))


def downgrade() -> None:
    if _has_column(TABLE, COLUMN):
        op.drop_column(TABLE, COLUMN)

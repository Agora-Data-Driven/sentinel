"""development_profiles.coach_reads_gym_logs — the Physical tab's coach-visibility toggle

Someone who trains consistently but does not LOG every session was being told by the coach
that they had been inconsistent: the digest shipped `sessions_last_14d` / `completed_last_14d`
and the model read a low count as a fact about training rather than about logging. This column
lets a person withhold the log; the digest then says so explicitly instead of going quiet, so
the coach cannot infer anything from its absence either.

Defaults to TRUE so every existing person's coach behaves exactly as it did.

EXISTENCE-GUARDED, like a9c4e7f2d5b8: `main._ensure_columns` is the path this column takes to
production (prod deploys do not run alembic), and it will usually have added the column already
by the time anyone replays this revision. An unguarded add_column would fail there.

Revision ID: d4a9f1c8e35b
Revises: e2c7a4f9b6d1
Create Date: 2026-08-10 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'd4a9f1c8e35b'
down_revision = 'e2c7a4f9b6d1'
branch_labels = None
depends_on = None

TABLE = 'development_profiles'
COLUMN = 'coach_reads_gym_logs'


def _has_column(table: str, column: str) -> bool:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table(table):
        return False
    return any(c['name'] == column for c in insp.get_columns(table))


def upgrade() -> None:
    if _has_column(TABLE, COLUMN):
        return
    # server_default is what backfills existing rows; the column is NOT NULL, so it is required.
    op.add_column(
        TABLE,
        sa.Column(COLUMN, sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    if _has_column(TABLE, COLUMN):
        op.drop_column(TABLE, COLUMN)

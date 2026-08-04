"""recurring_services: retainer deliverables that generate themselves (WP 6.1, M10)

Monthly deliverables were re-created by hand every month, so they got forgotten in exactly the
months somebody was too busy to remember — which is when the client notices.

🔴 `last_period` is a STRING period key ("2026-08", "2026-W32"), not a timestamp, and that choice
is the safety mechanism rather than a storage detail. The generator asks "have I already made this
period's task?", which answers identically however often the tick runs, on however many instances,
and whether or not it ran late. A `last_run_at` datetime would force every retry, double-tick and
post-outage catch-up to reason about clock windows, and one of them would eventually double-create
a client's deliverable. Duplicated retainer work is worse than late retainer work: somebody does it
twice and bills once.

It is also what prevents BACKFILL — a recurrence created today is stamped with the current period,
so it starts at the next real boundary rather than inventing the months it did not exist for.

Existence-guarded like every revision here: `create_all` / `main._ensure_columns` is the path
schema actually takes to production.

Revision ID: d8a3f6c2e9b5
Revises: c7e4b1a9f2d3
Create Date: 2026-08-04 13:10:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'd8a3f6c2e9b5'
down_revision = 'c7e4b1a9f2d3'
branch_labels = None
depends_on = None

_TABLE = 'recurring_services'


def _has_table() -> bool:
    return sa.inspect(op.get_bind()).has_table(_TABLE)


def upgrade() -> None:
    if _has_table():
        return
    op.create_table(
        _TABLE,
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('client_id', sa.Integer(), sa.ForeignKey('clients.id'), nullable=True),
        sa.Column('service_key', sa.String(length=60), nullable=True),
        sa.Column('assigned_team_id', sa.Integer(), sa.ForeignKey('teams.id'), nullable=True),
        sa.Column('assigned_to_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('priority', sa.String(length=16), nullable=True, server_default='Medium'),
        sa.Column('cadence', sa.String(length=16), nullable=True, server_default='monthly'),
        sa.Column('day_of_period', sa.Integer(), nullable=True, server_default='1'),
        sa.Column('due_in_days', sa.Integer(), nullable=True, server_default='0'),
        # 🔴 `false`, never `0`: Postgres rejects an integer default on a boolean, and SQLite has
        # understood `false` since 3.23. Same literal as everywhere else in this repo.
        sa.Column('is_active', sa.Boolean(), nullable=True, server_default=sa.text('true')),
        sa.Column('last_period', sa.String(length=16), nullable=True),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )
    # The daily tick reads only the active rows.
    op.create_index('ix_recurring_services_is_active', _TABLE, ['is_active'])
    op.create_index('ix_recurring_services_client_id', _TABLE, ['client_id'])


def downgrade() -> None:
    if _has_table():
        op.drop_table(_TABLE)

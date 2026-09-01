"""time_entries — hand-logged minutes against a growth dimension

The Mastery Engine records its own minutes in Firestore; this table holds what it cannot see (a book
on paper, a gym session, a course elsewhere). See app/models/time_entry.py and
services/time_spent.py.

EXISTENCE-GUARDED, like a9c4e7f2d5b8: prod deploys don't run Alembic, so the boot-time create_all
safety net builds this table there first, and an unguarded create_table would then fail. A fresh
Alembic-only DB gets the real table.

Revision ID: b7e2f4a9c1d6
Revises: f3b8c1d29a47
Create Date: 2026-09-01 12:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'b7e2f4a9c1d6'
down_revision = 'f3b8c1d29a47'
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def upgrade() -> None:
    if _has_table('time_entries'):
        return
    op.create_table(
        'time_entries',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('start_hhmm', sa.String(length=5), nullable=False),
        sa.Column('minutes', sa.Integer(), nullable=False),
        sa.Column('dimension', sa.String(length=24), nullable=False),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_time_entries_user_id', 'time_entries', ['user_id'])
    op.create_index('ix_time_entries_date', 'time_entries', ['date'])
    op.create_index('ix_time_entries_dimension', 'time_entries', ['dimension'])


def downgrade() -> None:
    if _has_table('time_entries'):
        op.drop_table('time_entries')

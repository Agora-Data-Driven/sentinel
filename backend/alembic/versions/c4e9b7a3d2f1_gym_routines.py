"""gym_routines — saved workout templates ("Push A", "Legs B")

One new table holding a named exercise list with its sets/reps/weights, plus the weekdays it is the
default for. Additive only: gym logging, the weekly split and the calendar are untouched.

Creation is EXISTENCE-GUARDED like a9c4e7f2d5b8: the app's boot-time ``create_all`` safety net can
build this table before migrations run on a long-lived local DB, and an unguarded create_table would
fail there. On such a DB this is a clean no-op.

Revision ID: c4e9b7a3d2f1
Revises: a9c4e7f2d5b8
Create Date: 2026-07-31 10:15:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'c4e9b7a3d2f1'
down_revision = 'a9c4e7f2d5b8'
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def upgrade() -> None:
    if _has_table('gym_routines'):
        return
    op.create_table(
        'gym_routines',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=60), nullable=False),
        sa.Column('day_type', sa.String(length=16), nullable=False, server_default='Custom'),
        sa.Column('exercises_json', sa.Text(), nullable=False, server_default='[]'),
        sa.Column('weekdays_json', sa.Text(), nullable=False, server_default='[]'),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_gym_routines_user_id', 'gym_routines', ['user_id'])


def downgrade() -> None:
    if _has_table('gym_routines'):
        op.drop_index('ix_gym_routines_user_id', table_name='gym_routines')
        op.drop_table('gym_routines')

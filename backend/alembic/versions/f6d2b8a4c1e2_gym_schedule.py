"""gym schedule (weekly split) + per-date plan overrides

The recurring weekly split (which day-type each weekday is) plus per-date overrides so the calendar
can show a forward workout plan and the coach can edit it. Additive only — no changes to existing
tables; gym logging keeps working untouched.

Revision ID: f6d2b8a4c1e2
Revises: d4b1f6a2c8e1
Create Date: 2026-07-23 09:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'f6d2b8a4c1e2'
down_revision = 'd4b1f6a2c8e1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'gym_schedules',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('week_json', sa.Text(), nullable=False, server_default='{}'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', name='uq_gym_schedule_user'),
    )
    op.create_index('ix_gym_schedules_user_id', 'gym_schedules', ['user_id'])

    op.create_table(
        'gym_plan_overrides',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('day_type', sa.String(length=16), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'date', name='uq_gym_override_user_date'),
    )
    op.create_index('ix_gym_plan_overrides_user_id', 'gym_plan_overrides', ['user_id'])
    op.create_index('ix_gym_plan_overrides_date', 'gym_plan_overrides', ['date'])


def downgrade() -> None:
    op.drop_index('ix_gym_plan_overrides_date', table_name='gym_plan_overrides')
    op.drop_index('ix_gym_plan_overrides_user_id', table_name='gym_plan_overrides')
    op.drop_table('gym_plan_overrides')
    op.drop_index('ix_gym_schedules_user_id', table_name='gym_schedules')
    op.drop_table('gym_schedules')

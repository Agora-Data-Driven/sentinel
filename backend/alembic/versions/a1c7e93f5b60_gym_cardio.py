"""gym plan cardio notes (weekly + per-date)

Lets each planned day carry an optional cardio note (e.g. "5k run", "~10k run", "intervals")
alongside its strength split, so the calendar and the AI coach can see the whole training load.
Additive, nullable — existing plans are unaffected.

Revision ID: a1c7e93f5b60
Revises: f6d2b8a4c1e2
Create Date: 2026-07-23 12:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'a1c7e93f5b60'
down_revision = 'f6d2b8a4c1e2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('gym_schedules', sa.Column('cardio_json', sa.Text(), nullable=False, server_default='{}'))
    op.add_column('gym_plan_overrides', sa.Column('cardio', sa.String(length=120), nullable=True))


def downgrade() -> None:
    op.drop_column('gym_plan_overrides', 'cardio')
    op.drop_column('gym_schedules', 'cardio_json')

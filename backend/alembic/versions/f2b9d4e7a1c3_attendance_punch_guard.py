"""one clock-in / clock-out per person per day (duplicate-punch guard)

Partial unique indexes so a race (two near-simultaneous scans) can't create two clock-ins or two
clock-outs for the same person on the same day. Breaks are exempt. If a prod DB somehow holds a
duplicate already, dedupe those rows before running this.

Revision ID: f2b9d4e7a1c3
Revises: e7c1a9d3f8b2
Create Date: 2026-07-24 10:15:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'f2b9d4e7a1c3'
down_revision = 'e7c1a9d3f8b2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        'uq_att_one_clockin_per_day', 'attendance_events', ['user_id', 'date'], unique=True,
        postgresql_where=sa.text("action = 'clock_in'"), sqlite_where=sa.text("action = 'clock_in'"),
    )
    op.create_index(
        'uq_att_one_clockout_per_day', 'attendance_events', ['user_id', 'date'], unique=True,
        postgresql_where=sa.text("action = 'clock_out'"), sqlite_where=sa.text("action = 'clock_out'"),
    )


def downgrade() -> None:
    op.drop_index('uq_att_one_clockout_per_day', table_name='attendance_events')
    op.drop_index('uq_att_one_clockin_per_day', table_name='attendance_events')

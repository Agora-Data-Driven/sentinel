"""physical_goals — target PRs (lift/run/skill) that drive the Physical ring

Each row is a number the worker is chasing (target_value) and where they are now
(current_value). `direction` 'lower' inverts progress for time-based goals. The Growth
Overview's Physical ring is the mean progress across non-paused goals — the physical
analogue of a Mastery Engine program score.

Revision ID: a2c8e4f6b1d3
Revises: f9b4d7a2c5e8
Create Date: 2026-07-27 14:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'a2c8e4f6b1d3'
down_revision = 'f9b4d7a2c5e8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'physical_goals',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False, index=True),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('kind', sa.String(length=16), nullable=False, server_default='lift'),
        sa.Column('target_value', sa.Float(), nullable=False),
        sa.Column('current_value', sa.Float(), nullable=False, server_default='0'),
        sa.Column('unit', sa.String(length=24), nullable=False, server_default=''),
        sa.Column('direction', sa.String(length=8), nullable=False, server_default='higher'),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=16), nullable=False, server_default='active'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table('physical_goals')

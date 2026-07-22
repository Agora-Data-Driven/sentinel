"""skills pillar

A worker's self-declared skills (often from real project experience, not the Mastery Engine),
so the AI coach knows what they can already do. Additive only.

Revision ID: c3a8e5f1b920
Revises: b7f2a1c9d4e0
Create Date: 2026-07-22 10:15:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'c3a8e5f1b920'
down_revision = 'b7f2a1c9d4e0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'skills',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('level', sa.String(length=16), nullable=False),
        sa.Column('source', sa.String(length=24), nullable=False),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_skills_user_id', 'skills', ['user_id'])


def downgrade() -> None:
    op.drop_table('skills')

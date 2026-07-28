"""mentor_transcripts — full transcripts imported from outside mentors

A worker-built, bottom-up knowledge base (e.g. Atrium creator videos from Nic Saraev,
Carson Reed) so the AI coach can draw on someone else's playbook, not just the Mastery
Engine's own curriculum. Lives at the bottom of the Growth Overview as a "mentor library".

Revision ID: b3f7d9a1c6e2
Revises: a2c8e4f6b1d3
Create Date: 2026-07-28 09:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'b3f7d9a1c6e2'
down_revision = 'a2c8e4f6b1d3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'mentor_transcripts',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False, index=True),
        sa.Column('mentor_name', sa.String(length=120), nullable=False),
        sa.Column('title', sa.String(length=300), nullable=False),
        sa.Column('source_url', sa.String(length=500), nullable=True),
        sa.Column('transcript_text', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table('mentor_transcripts')

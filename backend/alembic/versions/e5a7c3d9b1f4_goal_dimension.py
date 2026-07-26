"""professional_goals.dimension (four growth dimensions)

The Growth hub now organizes goals into four dimensions — spiritual | professional | mental |
physical. Existing rows were all career goals, so they backfill to 'professional'.

Revision ID: e5a7c3d9b1f4
Revises: c9f2a4b7d1e8
Create Date: 2026-07-26 10:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'e5a7c3d9b1f4'
down_revision = 'c9f2a4b7d1e8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'professional_goals',
        sa.Column('dimension', sa.String(length=16), nullable=False, server_default='professional'),
    )


def downgrade() -> None:
    op.drop_column('professional_goals', 'dimension')

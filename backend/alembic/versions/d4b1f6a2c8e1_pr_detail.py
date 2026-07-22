"""personal_records.detail (non-weight PRs)

Lets a personal record hold a cardio/time/distance result (e.g. a 10 km run "~59 min"), not just
weight lifts. Additive nullable column.

Revision ID: d4b1f6a2c8e1
Revises: c3a8e5f1b920
Create Date: 2026-07-22 11:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'd4b1f6a2c8e1'
down_revision = 'c3a8e5f1b920'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('personal_records', sa.Column('detail', sa.String(length=160), nullable=True))


def downgrade() -> None:
    op.drop_column('personal_records', 'detail')

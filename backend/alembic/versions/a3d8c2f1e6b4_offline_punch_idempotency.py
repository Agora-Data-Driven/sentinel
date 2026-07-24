"""offline punch idempotency key (client_uid)

A stable per-punch id from the kiosk so re-syncing the same offline punch (after a lost/partial
response) records it at most once. Nullable + unique: online punches carry no uid and are unaffected
(NULLs are distinct).

Revision ID: a3d8c2f1e6b4
Revises: f2b9d4e7a1c3
Create Date: 2026-07-24 10:45:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'a3d8c2f1e6b4'
down_revision = 'f2b9d4e7a1c3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('attendance_events', sa.Column('client_uid', sa.String(length=64), nullable=True))
    op.create_index('uq_att_client_uid', 'attendance_events', ['client_uid'], unique=True)


def downgrade() -> None:
    op.drop_index('uq_att_client_uid', table_name='attendance_events')
    op.drop_column('attendance_events', 'client_uid')

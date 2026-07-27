"""development_areas (per-dimension deadline + other info) + rename 'mental' -> 'philosophical'

The Growth hub's four dimensions become spiritual | professional | philosophical | physical
(aligning the Overview with the nav tabs, each backed by its own Mastery Engine program).
Two changes:

1. New table `development_areas` — per-user, per-dimension settings: the pace `deadline` the
   whole area races toward (ring % itself now comes from the Mastery Engine, never typed by
   hand) and `other_info`, a free-form dump the worker or the AI coach maintains. Rows are
   created lazily; a missing row means "all defaults".
2. Data migration: goals stored under the old 'mental' dimension move to 'philosophical'.
   Nothing validates the vocabulary at the DB level, but the frontend's dimOf() reclassifies
   unknown values as 'professional', so un-migrated rows would silently change shelf.

Revision ID: f9b4d7a2c5e8
Revises: e5a7c3d9b1f4
Create Date: 2026-07-27 12:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'f9b4d7a2c5e8'
down_revision = 'e5a7c3d9b1f4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'development_areas',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False, index=True),
        sa.Column('dimension', sa.String(length=16), nullable=False),
        sa.Column('deadline', sa.Date(), nullable=True),
        sa.Column('other_info', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.UniqueConstraint('user_id', 'dimension', name='uq_dev_area_user_dim'),
    )
    op.execute("UPDATE professional_goals SET dimension='philosophical' WHERE dimension='mental'")


def downgrade() -> None:
    op.execute("UPDATE professional_goals SET dimension='mental' WHERE dimension='philosophical'")
    op.drop_table('development_areas')

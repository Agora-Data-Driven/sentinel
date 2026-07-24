"""add profile photo storage (in-DB blob) to users

Profile pictures are stored in-DB: there's no object store wired and Cloud Run's filesystem is
ephemeral, so a small client-resized image lives on the ``users`` row and is served by
``GET /api/people/{id}/avatar``. Adds ``profile_pic_data`` (the bytes) and ``profile_pic_type``
(the content type). ``profile_pic_url`` already exists (initial schema) and now points at the
serving endpoint with a ``?v=`` cache-buster.

Revision ID: c9f2a4b7d1e8
Revises: b8e3f1a6c2d5
Create Date: 2026-07-24 16:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'c9f2a4b7d1e8'
down_revision = 'b8e3f1a6c2d5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('users') as b:
        b.add_column(sa.Column('profile_pic_data', sa.LargeBinary(), nullable=True))
        b.add_column(sa.Column('profile_pic_type', sa.String(length=60), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('users') as b:
        b.drop_column('profile_pic_type')
        b.drop_column('profile_pic_data')

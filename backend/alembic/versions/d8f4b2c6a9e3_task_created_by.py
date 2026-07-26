"""add tasks.created_by_id — automatic creator tag

Every task records who created it, set server-side on create (never a form field). It feeds the
task-visibility rule: employees see tasks assigned to them OR created by them, so a quick-added
card never vanishes off its creator's board. Nullable because tasks predate the column; old rows
simply have no creator tag (they remain visible to their assignees as before).

Revision ID: d8f4b2c6a9e3
Revises: c9f2a4b7d1e8
Create Date: 2026-07-26 16:20:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'd8f4b2c6a9e3'
down_revision = 'c9f2a4b7d1e8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('tasks') as b:
        b.add_column(sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True))
    op.create_index('ix_tasks_created_by_id', 'tasks', ['created_by_id'])


def downgrade() -> None:
    op.drop_index('ix_tasks_created_by_id', table_name='tasks')
    with op.batch_alter_table('tasks') as b:
        b.drop_column('created_by_id')

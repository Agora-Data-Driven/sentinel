"""service_templates + task_vocab — the two model tables that rode on create_all

Both tables have existed in app/models/task.py (ServiceTemplate, TaskVocabItem) since the
editable service-recipe / board-vocabulary features shipped, but no migration was ever
written — locally create_all papered over it, and in prod the boot-time create_all safety
net built them. This migration brings the Alembic history back in line with the models
(the repo rule: every model change has a hand-written migration).

Unlike the usual pattern, creation is EXISTENCE-GUARDED: prod and every long-lived local DB
already hold these tables via create_all, and migrations run before the app boots — an
unguarded create_table would fail there. On such DBs this is a clean no-op; a fresh
Alembic-only DB gets the real tables.

Revision ID: a9c4e7f2d5b8
Revises: b3f7d9a1c6e2
Create Date: 2026-07-29 13:40:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'a9c4e7f2d5b8'
down_revision = 'b3f7d9a1c6e2'
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def upgrade() -> None:
    if not _has_table('service_templates'):
        op.create_table(
            'service_templates',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('key', sa.String(length=60), nullable=False),
            sa.Column('label', sa.String(length=120), nullable=False),
            sa.Column('dept', sa.String(length=80), nullable=True),
            sa.Column('content_type', sa.String(length=80), nullable=True),
            sa.Column('maintasks_json', sa.Text(), nullable=False),
            sa.Column('default_priority', sa.String(length=16), nullable=True),
            sa.Column('default_labels_json', sa.Text(), nullable=False),
            sa.Column('default_description', sa.Text(), nullable=True),
            sa.Column('sort_order', sa.Integer(), nullable=False),
            sa.Column('is_active', sa.Boolean(), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
        )
        op.create_index('ix_service_templates_key', 'service_templates', ['key'], unique=True)

    if not _has_table('task_vocab'):
        op.create_table(
            'task_vocab',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('kind', sa.String(length=16), nullable=False),
            sa.Column('name', sa.String(length=80), nullable=False),
            sa.Column('color', sa.String(length=16), nullable=True),
            sa.Column('sort_order', sa.Integer(), nullable=False),
            sa.Column('is_active', sa.Boolean(), nullable=False),
        )
        op.create_index('ix_task_vocab_kind', 'task_vocab', ['kind'])


def downgrade() -> None:
    if _has_table('task_vocab'):
        op.drop_index('ix_task_vocab_kind', table_name='task_vocab')
        op.drop_table('task_vocab')
    if _has_table('service_templates'):
        op.drop_index('ix_service_templates_key', table_name='service_templates')
        op.drop_table('service_templates')

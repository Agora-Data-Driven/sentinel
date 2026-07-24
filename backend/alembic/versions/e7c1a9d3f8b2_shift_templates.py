"""shift templates (reusable schedules) + team/employee assignment

A named, reusable shift (start/end/break/grace) so shift changes are data-driven in the Manage UI
instead of code. Additive only: teams/users get a nullable ``shift_template_id`` FK; the legacy
``shift_start``/``shift_end`` columns stay as a fallback, so existing rows keep working untouched.

Revision ID: e7c1a9d3f8b2
Revises: a1c7e93f5b60
Create Date: 2026-07-24 09:30:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'e7c1a9d3f8b2'
down_revision = 'a1c7e93f5b60'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'shift_templates',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=60), nullable=False),
        sa.Column('start_time', sa.String(length=5), nullable=False, server_default='08:00'),
        sa.Column('end_time', sa.String(length=5), nullable=False, server_default='17:00'),
        sa.Column('break_min', sa.Integer(), nullable=False, server_default='60'),
        sa.Column('grace_min', sa.Integer(), nullable=True),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name', name='uq_shift_template_name'),
    )
    with op.batch_alter_table('teams') as b:
        b.add_column(sa.Column('shift_template_id', sa.Integer(), nullable=True))
        b.create_foreign_key('fk_teams_shift_template', 'shift_templates', ['shift_template_id'], ['id'])
    with op.batch_alter_table('users') as b:
        b.add_column(sa.Column('shift_template_id', sa.Integer(), nullable=True))
        b.create_foreign_key('fk_users_shift_template', 'shift_templates', ['shift_template_id'], ['id'])


def downgrade() -> None:
    with op.batch_alter_table('users') as b:
        b.drop_constraint('fk_users_shift_template', type_='foreignkey')
        b.drop_column('shift_template_id')
    with op.batch_alter_table('teams') as b:
        b.drop_constraint('fk_teams_shift_template', type_='foreignkey')
        b.drop_column('shift_template_id')
    op.drop_table('shift_templates')

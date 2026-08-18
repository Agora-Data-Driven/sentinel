"""user_capabilities — per-PERSON capability exceptions, layered over the role's

The case it exists for: "Maria specifically may run payroll", without inventing a role for one
person. Resolution is role defaults -> role overrides (`role_capabilities`) -> these.

EXISTENCE-GUARDED for the same reason as `e7c3a9f4b812`: prod deploys do not run Alembic, so the
boot-time `create_all` safety net will very likely have built this table before this migration ever
reaches it (AGENTS.md §4). Unguarded, `create_table` would then fail.

Revision ID: f3b8c1d29a47
Revises: e7c3a9f4b812
Create Date: 2026-08-18 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'f3b8c1d29a47'
down_revision = 'e7c3a9f4b812'
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def upgrade() -> None:
    if _has_table('user_capabilities'):
        return
    op.create_table(
        'user_capabilities',
        sa.Column('user_id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('capability', sa.String(length=60), primary_key=True, nullable=False),
        sa.Column('allowed', sa.Boolean(), nullable=False),
        # No FK on either id — `people.delete_person` clears dependants with bulk statements that
        # bypass the ORM, and it calls `permissions.prune_orphans` for this table explicitly. An FK
        # would turn deleting a person into an integrity error on Postgres while passing on SQLite.
        sa.Column('updated_by_id', sa.Integer(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    if _has_table('user_capabilities'):
        op.drop_table('user_capabilities')

"""role_capabilities — the Super Admin's per-role capability OVERRIDES

Backs the Permissions console (`app/capabilities.py` + `routers/permissions.py`). The table stores
only DELTAS from the coded defaults, so an empty table means "exactly what the code ships with" —
which is what makes "Reset to defaults" a single DELETE and what lets a capability added in a later
deploy arrive with its default already applied to every role.

EXISTENCE-GUARDED, following `a9c4e7f2d5b8`: this is a brand-new TABLE, and a new table is the one
schema change `create_all` lands by itself — so prod's boot-time safety net will very likely have
built it before this migration ever runs there (AGENTS.md §4, "Add a database column": prod deploys
do not run Alembic). An unguarded `create_table` would then fail. On such a DB this is a clean
no-op; a fresh Alembic-only DB gets the real table.

Revision ID: e7c3a9f4b812
Revises: c5a8e2b6d941
Create Date: 2026-08-17 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'e7c3a9f4b812'
down_revision = 'c5a8e2b6d941'
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def upgrade() -> None:
    if _has_table('role_capabilities'):
        return
    op.create_table(
        'role_capabilities',
        # Composite PK: one row per (role, capability), enforced by the DB rather than by
        # remembering to check before every insert.
        sa.Column('role', sa.String(length=32), primary_key=True, nullable=False),
        sa.Column('capability', sa.String(length=60), primary_key=True, nullable=False),
        sa.Column('allowed', sa.Boolean(), nullable=False),
        # No FK to users: an override must outlive the Super Admin who set it. Losing the attribution
        # is a nuisance; a delete that cascades away a live permission decision is an outage.
        sa.Column('updated_by_id', sa.Integer(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    if _has_table('role_capabilities'):
        op.drop_table('role_capabilities')

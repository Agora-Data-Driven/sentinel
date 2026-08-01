"""growth_items.dimension — the journal becomes per-dimension (one titled idea per entry)

Each of the four growth dimensions now holds its OWN titled entries, replacing the single shared
journal plus `development_areas.other_info`, a per-dimension free-form blob.

Why it changed: `other_info` had no titles, so it had no index, so the AI coach could only ever be
handed a truncated excerpt of it — and it then reported content the worker could see on their own
screen as non-existent (2026-08-01). Titled entries give the coach a COMPLETE index (every title,
uncapped, every turn) with bodies fetched on demand, which is what lets the journal grow without
bound. `other_info` is intentionally left in place and still readable; the UI surfaces whatever
remains in it as "unfiled" with a one-click path into real entries.

Existing rows backfill to 'spiritual' — where the whole journal rendered before the split — so
nothing appears to jump tabs on upgrade.

🔴 Production deploys do NOT run alembic. `main._ensure_columns` carries the same ADD COLUMN and
backfill and is what actually lands this in prod; this revision is for local and migrated DBs. The
guard below exists because create_all / _ensure_columns may already have added the column.

Revision ID: b6d2f8a4c7e9
Revises: c4e9b7a3d2f1
Create Date: 2026-08-01 12:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'b6d2f8a4c7e9'
down_revision = 'c4e9b7a3d2f1'
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    insp = sa.inspect(op.get_bind())
    if table not in insp.get_table_names():
        return True  # nothing to do; the table itself is absent
    return column in {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    # Existence-guarded: prod's create_all safety net (and _ensure_columns) may have built this
    # already, and a blind ADD COLUMN would then fail the whole migration.
    if not _has_column('growth_items', 'dimension'):
        op.add_column(
            'growth_items',
            sa.Column('dimension', sa.String(length=16), nullable=False, server_default='spiritual'),
        )
    # Idempotent regardless of which path added the column.
    op.execute("UPDATE growth_items SET dimension='spiritual' WHERE dimension IS NULL OR dimension=''")


def downgrade() -> None:
    if _has_column('growth_items', 'dimension'):
        op.drop_column('growth_items', 'dimension')

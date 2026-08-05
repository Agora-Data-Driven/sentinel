"""clients.is_active — Atrium owns the client list, so a dropped client is deactivated not deleted

Sentinel's `clients` table used to be maintained by hand in Manage → Clients, which made it a second
source of truth for something Atrium already knows. Since 2026-08-05 `services/client_sync` mirrors
Atrium's registry into it (Atrium owns CLIENTS; Sentinel owns STAFF), and a client Atrium stops
listing is switched off rather than removed:

    🔴 Deleting a client NULLs `Task.client_id` on every task it ever had, so that client's whole
    history disappears from the reports. An inactive client keeps its history and only leaves the
    pickers.

EXISTENCE-GUARDED, like a9c4e7f2d5b8: `main._ensure_columns` is the path this column takes to
production (prod deploys have a history of not running Alembic), so by the time this revision runs
anywhere the column is usually already there. On such a DB this is a clean no-op.

`server_default` is spelled 'true', never '1' — prod is POSTGRES and rejects an integer default on a
boolean column. SQLite accepts 'true' as well.

Revision ID: c4e8b2f7a9d3
Revises: d8a3f6c2e9b5
Create Date: 2026-08-05 16:20:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'c4e8b2f7a9d3'
down_revision = 'd8a3f6c2e9b5'
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table(table):
        return False
    return column in {c['name'] for c in insp.get_columns(table)}


def upgrade() -> None:
    if not _has_column('clients', 'is_active'):
        op.add_column('clients', sa.Column('is_active', sa.Boolean(), nullable=False,
                                           server_default=sa.text('true')))


def downgrade() -> None:
    if _has_column('clients', 'is_active'):
        op.drop_column('clients', 'is_active')

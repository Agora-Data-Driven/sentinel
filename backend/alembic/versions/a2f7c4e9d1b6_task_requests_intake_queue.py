"""task_requests: the client intake queue (WP 3.3, decision D3)

A client's ASK, before anyone has agreed to do it.

🔴 Why a new table rather than a flag on `tasks`. Atrium's quick-add composer used to write
straight into `ws["tasks"]`, so anything a client typed during a call became a live card on the
delivery board — unowned, unestimated, unscheduled, and indistinguishable from work the agency had
actually committed to. Modelling a request AS a task (with, say, `is_request=True`) would keep
exactly that problem: every board query, every rollup, every count would have to remember to
exclude them, and the first one that forgot would put a client's wish back on the board. A separate
table cannot be forgotten.

`status` is pending -> accepted | declined, and terminal either way: the client has already been
told, so a decision is never un-made. `task_id` links an accepted request to what it became, which
is how Atrium shows the client that their ask turned into real work.

`client_key` is Atrium's WORKSPACE key, not a Sentinel client id: the request arrives from a
workspace, and resolving it to a `Client` row is a lookup that may legitimately fail (an unlinked
workspace). That failure must not lose the request, so `client_id` is nullable and the key is the
thing we always keep.

`source_ref` is Atrium's own id for the composer entry, unique-ish per request, so a retried send
cannot file the same ask twice.

EXISTENCE-GUARDED like every other revision here: `main._ensure_columns` / `create_all` is the path
schema actually takes to production (deploys don't run Alembic reliably), so by the time this runs
the table is often already there.

Revision ID: a2f7c4e9d1b6
Revises: f1a6d3c8b5e2
Create Date: 2026-08-04 10:40:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'a2f7c4e9d1b6'
down_revision = 'f1a6d3c8b5e2'
branch_labels = None
depends_on = None

_TABLE = 'task_requests'


def _has_table() -> bool:
    return sa.inspect(op.get_bind()).has_table(_TABLE)


def upgrade() -> None:
    if _has_table():
        return
    op.create_table(
        _TABLE,
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('client_key', sa.String(length=80), nullable=False),
        sa.Column('client_id', sa.Integer(), sa.ForeignKey('clients.id'), nullable=True),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('details', sa.Text(), nullable=True),
        sa.Column('requester_name', sa.String(length=160), nullable=True),
        sa.Column('requester_email', sa.String(length=200), nullable=True),
        sa.Column('source_ref', sa.String(length=120), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=True, server_default='pending'),
        sa.Column('decided_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('decided_at', sa.DateTime(), nullable=True),
        sa.Column('decline_reason', sa.Text(), nullable=True),
        sa.Column('task_id', sa.Integer(), sa.ForeignKey('tasks.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )
    # The triage view is "pending, newest first", and the bridge de-dupes on source_ref.
    op.create_index('ix_task_requests_status', _TABLE, ['status'])
    op.create_index('ix_task_requests_client_key', _TABLE, ['client_key'])
    op.create_index('ix_task_requests_source_ref', _TABLE, ['source_ref'])
    op.create_index('ix_task_requests_created_at', _TABLE, ['created_at'])


def downgrade() -> None:
    if _has_table():
        op.drop_table(_TABLE)

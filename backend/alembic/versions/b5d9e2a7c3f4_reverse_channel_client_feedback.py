"""The reverse channel: client comments + change requests reach the Sentinel row (D4, WP 3.5)

Three changes, one revision, because they are one feature:

1. `task_comments.author_id` becomes NULLABLE. A CLIENT can now reach the thread, and a client is
   not a Sentinel user — there is no row to point at, and there must never need to be one.
   Minting shadow user accounts for clients would put them in every people picker, every rollup
   and every "assign to" dropdown in the product.
2. `task_comments.client_author` — who said it, as Atrium knows them. Free text for the same
   reason. A comment has EITHER an author_id or a client_author.
3. `tasks.client_changes_open` — how many change requests the client has open.
   🔴 Deliberately NOT reusing `review_state`. That is the INTERNAL approval gate (D5): a team
   lead saying "this is done". A client asking for a revision is a different fact from a different
   person, and folding them together would let a client satisfy — or block — an internal sign-off.

This is what replaces `atrium_approvals`' three dead response columns, dropped in WP 0.4: the same
intent, landing where the conversation already lives instead of in a table nothing ever wrote.

🔴 SQLite cannot ALTER a column's nullability in place — it rebuilds the table — so the author_id
change goes through `batch_alter_table`. Postgres does not care. Dev is SQLite, prod is Cloud SQL,
so both paths have to work.

Existence-guarded like every other revision here: `main._ensure_columns` / `create_all` is the path
schema actually takes to production.

Revision ID: b5d9e2a7c3f4
Revises: a2f7c4e9d1b6
Create Date: 2026-08-04 11:30:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'b5d9e2a7c3f4'
down_revision = 'a2f7c4e9d1b6'
branch_labels = None
depends_on = None


def _cols(table: str) -> dict:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table(table):
        return {}
    return {c['name']: c for c in insp.get_columns(table)}


def upgrade() -> None:
    tasks = _cols('tasks')
    if tasks and 'client_changes_open' not in tasks:
        op.add_column('tasks', sa.Column('client_changes_open', sa.Integer(),
                                         nullable=True, server_default='0'))
        # Existing rows must read 0, not NULL: the board renders a pill on `> 0` and a NULL
        # comparison is neither true nor false in SQL.
        op.get_bind().execute(sa.text(
            "UPDATE tasks SET client_changes_open = 0 WHERE client_changes_open IS NULL"))

    comments = _cols('task_comments')
    if not comments:
        return
    if 'client_author' not in comments:
        op.add_column('task_comments', sa.Column('client_author', sa.String(length=160),
                                                 nullable=True))
    if comments.get('author_id') is not None and not comments['author_id'].get('nullable', True):
        with op.batch_alter_table('task_comments') as batch:
            batch.alter_column('author_id', existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    comments = _cols('task_comments')
    if comments:
        # A client-authored comment has no user to point at, so it cannot survive the column going
        # back to NOT NULL. Drop those rows rather than fail the migration half-way.
        op.get_bind().execute(sa.text("DELETE FROM task_comments WHERE author_id IS NULL"))
        if 'client_author' in comments:
            with op.batch_alter_table('task_comments') as batch:
                batch.drop_column('client_author')
    tasks = _cols('tasks')
    if 'client_changes_open' in tasks:
        op.drop_column('tasks', 'client_changes_open')

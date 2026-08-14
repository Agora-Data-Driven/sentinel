"""user_teams — a person may belong to more than one department

`users.team_id` asserted that everybody belongs to exactly one department. People here do not: a
designer who also sits with Acquisition, or a team lead covering a second department while it has
no lead of its own. Those people could see only their PRIMARY team's board and were absent from the
other department's rollups, with nothing anywhere saying why.

🔴 `users.team_id` IS KEPT and is still the PRIMARY department — it is what decides a person's
shift (and therefore whether a punch is late), their payroll row and the Department column in
People, none of which can answer with a set. This table answers participation only; the union of
the two lives in `services/teams.team_ids` and nowhere else.

EXISTENCE-GUARDED, following b2e9d5f3a7c1 and a9c4e7f2d5b8: `create_all` runs on every boot and
builds this table from the model on any DB that started after the change, so an unguarded
`create_table` would fail there. On such a DB this is a clean no-op.

Revision ID: c5a8e2b6d941
Revises: b2e9d5f3a7c1
Create Date: 2026-08-14 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'c5a8e2b6d941'
down_revision = 'b2e9d5f3a7c1'
branch_labels = None
depends_on = None

TABLE = 'user_teams'


def _has_table(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def upgrade() -> None:
    if _has_table(TABLE):
        return
    op.create_table(
        TABLE,
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), primary_key=True),
        sa.Column('team_id', sa.Integer(), sa.ForeignKey('teams.id'), primary_key=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    # Dropping this loses the additional memberships; the primary department on `users` is
    # untouched, so every person keeps the department they had before the feature.
    if _has_table(TABLE):
        op.drop_table(TABLE)

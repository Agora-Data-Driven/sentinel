"""the thin project layer — projects, project_milestones, tasks.project_id

Named outcomes with dates (the first is Phase One), rolled up from milestones + linked tasks
(models/project.py, 2026-09-02).

EXISTENCE-GUARDED like every migration since a9c4e7f2d5b8: prod deploys don't run Alembic, so
`create_all` lands the two tables and `main._ensure_columns` lands the column at boot; an unguarded
op here would then fail on the next hand-run upgrade.

Revision ID: d4c7e9a2f5b8
Revises: c9e4a7b2d6f1
Create Date: 2026-09-02 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'd4c7e9a2f5b8'
down_revision = 'c9e4a7b2d6f1'
branch_labels = None
depends_on = None


def _insp():
    return sa.inspect(op.get_bind())


def upgrade() -> None:
    insp = _insp()
    if not insp.has_table("projects"):
        op.create_table(
            "projects",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("name", sa.String(160), nullable=False),
            sa.Column("goal", sa.Text, nullable=True),
            sa.Column("owner_id", sa.Integer, sa.ForeignKey("users.id"), nullable=True),
            sa.Column("target_date", sa.Date, nullable=True),
            sa.Column("status", sa.String(16), nullable=True),
            sa.Column("created_at", sa.DateTime, nullable=True),
            sa.Column("updated_at", sa.DateTime, nullable=True),
        )
    if not insp.has_table("project_milestones"):
        op.create_table(
            "project_milestones",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("project_id", sa.Integer, sa.ForeignKey("projects.id"),
                      nullable=False, index=True),
            sa.Column("title", sa.String(200), nullable=False),
            sa.Column("detail", sa.Text, nullable=True),
            sa.Column("target_date", sa.Date, nullable=True),
            sa.Column("done", sa.Boolean, nullable=True),
            sa.Column("done_at", sa.DateTime, nullable=True),
            sa.Column("done_by_id", sa.Integer, sa.ForeignKey("users.id"), nullable=True),
            sa.Column("position", sa.Integer, nullable=True),
            sa.Column("created_at", sa.DateTime, nullable=True),
        )
    if "project_id" not in {c["name"] for c in _insp().get_columns("tasks")}:
        op.add_column("tasks", sa.Column("project_id", sa.Integer, nullable=True))


def downgrade() -> None:
    pass

"""task_supporters — many people on one task, none of them accountable

Closes an asymmetry that had been on the board since the Atrium bridge was built: an **Atrium client
card carries Lead + many Support**, while a Sentinel row had exactly one ownership field
(`assigned_to_id`). Both kinds of card render on the same board, so the only way to put a second name
on a Sentinel task was to invent a checklist step for that person — and since the progress bar is
`done steps / total steps`, staffing a card changed how finished it looked.

One new table, additive only. Nothing about `tasks` changes: the lead stays `assigned_to_id` and every
rule keyed on it (the team triage queue, send-back, bulk-claim, the lead's right to tick another
person's step) is untouched. Support widens "assigned" — `task_perms.assigned_user_ids` — and nothing
else. See sentinel/AGENTS.md §5, "A task has ONE lead and MANY supporters".

Creation is EXISTENCE-GUARDED like c4e9b7a3d2f1 and a9c4e7f2d5b8: prod's boot-time ``create_all``
safety net lands a NEW TABLE by itself and generally wins the race against migrations, so an
unguarded create_table would fail there and on any long-lived local DB. On such a DB this is a clean
no-op.

Revision ID: e2c7a4f9b6d1
Revises: c4e8b2f7a9d3
Create Date: 2026-08-06 17:40:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'e2c7a4f9b6d1'
down_revision = 'c4e8b2f7a9d3'
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def upgrade() -> None:
    if _has_table('task_supporters'):
        return
    op.create_table(
        'task_supporters',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('task_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        # Who staffed them, kept because support IS a delegation decision. Nullable so a row can
        # outlive the person who made it without taking the staffing with it.
        sa.Column('added_by_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['task_id'], ['tasks.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.ForeignKeyConstraint(['added_by_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        # 🔴 One row per (task, person). A resent supporter must not stack a duplicate: it would
        # double-count them on the Monitor and draw their avatar twice on the card. The write path
        # dedupes too — this is the floor under it, not a substitute for it.
        sa.UniqueConstraint('task_id', 'user_id', name='uq_task_supporter'),
    )
    op.create_index('ix_task_supporters_task_id', 'task_supporters', ['task_id'])
    op.create_index('ix_task_supporters_user_id', 'task_supporters', ['user_id'])


def downgrade() -> None:
    if _has_table('task_supporters'):
        op.drop_index('ix_task_supporters_user_id', table_name='task_supporters')
        op.drop_index('ix_task_supporters_task_id', table_name='task_supporters')
        op.drop_table('task_supporters')

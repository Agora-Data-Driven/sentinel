"""operating-system release — task_sessions, certifications, and five columns

Sentinel as Agora's operating system (docs/SENTINEL_OPERATING_SYSTEM.md, 2026-09-02):

* `task_sessions`  — per-task work time, written by Start Work / Pause / clock-out
* `certifications` — credentials a person holds; `service_templates.required_certification` names one
* `tasks.hold_kind`, `tasks.blocked_by_task_id`, `tasks.estimate_minutes`
* `users.stage`, `clients.account_manager_id`
* `service_templates.estimate_minutes`, `service_templates.required_certification`

EXISTENCE-GUARDED, like every migration since a9c4e7f2d5b8: prod deploys don't run Alembic, so
`create_all` lands the two tables and `main._ensure_columns` lands the columns at boot, and an
unguarded op here would then fail on the next hand-run upgrade.

Revision ID: c9e4a7b2d6f1
Revises: b7e2f4a9c1d6
Create Date: 2026-09-02 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'c9e4a7b2d6f1'
down_revision = 'b7e2f4a9c1d6'
branch_labels = None
depends_on = None


def _insp():
    return sa.inspect(op.get_bind())


def _has_table(name: str) -> bool:
    return _insp().has_table(name)


def _has_column(table: str, column: str) -> bool:
    return column in {c["name"] for c in _insp().get_columns(table)}


def _add(table: str, column: sa.Column) -> None:
    if _has_table(table) and not _has_column(table, column.name):
        op.add_column(table, column)


def upgrade() -> None:
    if not _has_table('task_sessions'):
        op.create_table(
            'task_sessions',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('task_id', sa.Integer(), sa.ForeignKey('tasks.id'), nullable=False),
            sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
            sa.Column('started_at', sa.DateTime(), nullable=False),
            sa.Column('ended_at', sa.DateTime(), nullable=True),
            sa.Column('source', sa.String(length=16), nullable=False),
            sa.Column('note', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
        )
        op.create_index('ix_task_sessions_task_id', 'task_sessions', ['task_id'])
        op.create_index('ix_task_sessions_user_id', 'task_sessions', ['user_id'])
        op.create_index('ix_task_sessions_started_at', 'task_sessions', ['started_at'])
    if not _has_table('certifications'):
        op.create_table(
            'certifications',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
            sa.Column('key', sa.String(length=60), nullable=False),
            sa.Column('label', sa.String(length=120), nullable=False),
            sa.Column('granted_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('granted_at', sa.Date(), nullable=False),
            sa.Column('expires_at', sa.Date(), nullable=True),
            sa.Column('evidence_url', sa.String(length=500), nullable=True),
            sa.Column('note', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.UniqueConstraint('user_id', 'key', name='uq_certification_user_key'),
        )
        op.create_index('ix_certifications_user_id', 'certifications', ['user_id'])
        op.create_index('ix_certifications_key', 'certifications', ['key'])
    _add('tasks', sa.Column('hold_kind', sa.String(length=24), nullable=True))
    _add('tasks', sa.Column('blocked_by_task_id', sa.Integer(), nullable=True))
    _add('tasks', sa.Column('estimate_minutes', sa.Integer(), nullable=True))
    _add('users', sa.Column('stage', sa.String(length=24), nullable=True))
    _add('clients', sa.Column('account_manager_id', sa.Integer(), nullable=True))
    _add('service_templates', sa.Column('estimate_minutes', sa.Integer(), nullable=True))
    _add('service_templates', sa.Column('required_certification', sa.String(length=60), nullable=True))


def downgrade() -> None:
    for table in ('certifications', 'task_sessions'):
        if _has_table(table):
            op.drop_table(table)
    with op.batch_alter_table('tasks') as b:
        for col in ('hold_kind', 'blocked_by_task_id', 'estimate_minutes'):
            if _has_column('tasks', col):
                b.drop_column(col)
    if _has_column('users', 'stage'):
        with op.batch_alter_table('users') as b:
            b.drop_column('stage')
    if _has_column('clients', 'account_manager_id'):
        with op.batch_alter_table('clients') as b:
            b.drop_column('account_manager_id')
    with op.batch_alter_table('service_templates') as b:
        for col in ('estimate_minutes', 'required_certification'):
            if _has_column('service_templates', col):
                b.drop_column(col)

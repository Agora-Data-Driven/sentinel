"""unify shifts: default shift template + retire legacy shift_* columns

Makes the Shift Template the single source of truth for a schedule. Adds
``shift_templates.is_default`` (exactly one template is the company default — the base every
shift resolves from). Migrates the legacy per-team / per-employee ``shift_start``/``shift_end``/
``break_duration_min`` columns into real templates, then drops them. After this, shift times live
in exactly one place (the Shift Templates catalog) and are assigned by pointing at a template.

Revision ID: b8e3f1a6c2d5
Revises: a3d8c2f1e6b4
Create Date: 2026-07-24 11:00:00.000000
"""
from datetime import datetime

from alembic import op
import sqlalchemy as sa


revision = 'b8e3f1a6c2d5'
down_revision = 'a3d8c2f1e6b4'
branch_labels = None
depends_on = None


# Lightweight table defs so data migration works off real DB columns (not the ORM models, which no
# longer declare the legacy columns) and adapts booleans/params across SQLite + Postgres.
def _tables() -> tuple:
    meta = sa.MetaData()
    tpl = sa.Table(
        'shift_templates', meta,
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('name', sa.String), sa.Column('start_time', sa.String),
        sa.Column('end_time', sa.String), sa.Column('break_min', sa.Integer),
        sa.Column('grace_min', sa.Integer), sa.Column('active', sa.Boolean),
        sa.Column('is_default', sa.Boolean), sa.Column('created_at', sa.DateTime),
    )
    teams = sa.Table(
        'teams', meta,
        sa.Column('id', sa.Integer, primary_key=True), sa.Column('name', sa.String),
        sa.Column('shift_template_id', sa.Integer), sa.Column('shift_start', sa.String),
        sa.Column('shift_end', sa.String), sa.Column('break_duration_min', sa.Integer),
    )
    users = sa.Table(
        'users', meta,
        sa.Column('id', sa.Integer, primary_key=True), sa.Column('shift_template_id', sa.Integer),
        sa.Column('shift_start', sa.String), sa.Column('shift_end', sa.String),
    )
    settings = sa.Table(
        'system_settings', meta,
        sa.Column('key', sa.String, primary_key=True), sa.Column('value', sa.String),
    )
    return tpl, teams, users, settings


def _unique_name(conn, tpl, hint: str) -> str:
    base = (hint or "Shift").strip() or "Shift"
    name, n = base, 2
    while conn.execute(sa.select(tpl.c.id).where(tpl.c.name == name)).first() is not None:
        name, n = f"{base} ({n})", n + 1
    return name


def _find_or_create(conn, tpl, *, start, end, brk, grace, name_hint) -> int:
    """Return the id of a template matching (start,end,break,grace), creating one if none exists."""
    q = sa.select(tpl.c.id).where(
        tpl.c.start_time == start, tpl.c.end_time == end, tpl.c.break_min == brk,
        (tpl.c.grace_min.is_(None) if grace is None else tpl.c.grace_min == grace),
    )
    row = conn.execute(q).first()
    if row is not None:
        return row[0]
    res = conn.execute(tpl.insert().values(
        name=_unique_name(conn, tpl, name_hint), start_time=start, end_time=end,
        break_min=brk, grace_min=grace, active=True, is_default=False, created_at=datetime.utcnow(),
    ))
    return res.inserted_primary_key[0]


def upgrade() -> None:
    with op.batch_alter_table('shift_templates') as b:
        b.add_column(sa.Column('is_default', sa.Boolean(), nullable=False, server_default=sa.false()))

    conn = op.get_bind()
    tpl, teams, users, settings = _tables()

    smap = dict(conn.execute(sa.select(settings.c.key, settings.c.value)).all())
    d_start = smap.get('work_start', '08:00')
    d_end = smap.get('work_end', '17:00')
    d_break = int(smap.get('break_duration', '60') or 60)
    d_grace = int(smap.get('late_grace', '15') or 15)

    # 1) Ensure a company-default template exists and is the (only) default. Reuse an existing
    #    template matching the default window (ignoring grace, since NULL grace already resolves to
    #    the system default) so we don't create a near-duplicate of a seeded "Day (8AM–5PM)".
    match = conn.execute(sa.select(tpl.c.id).where(
        tpl.c.start_time == d_start, tpl.c.end_time == d_end, tpl.c.break_min == d_break,
    )).first()
    default_id = match[0] if match else _find_or_create(
        conn, tpl, start=d_start, end=d_end, brk=d_break, grace=d_grace, name_hint="Company Default")
    conn.execute(tpl.update().values(is_default=False))
    conn.execute(tpl.update().where(tpl.c.id == default_id).values(is_default=True))

    # 2) Teams: legacy shift_* -> a template. If the legacy shift equals the default, leave blank
    #    (blank = company default). Otherwise find/create a matching template and point at it.
    for t in conn.execute(sa.select(teams)).mappings().all():
        if t['shift_template_id'] is not None:
            continue
        s = t['shift_start'] or d_start
        e = t['shift_end'] or d_end
        brk = t['break_duration_min'] if t['break_duration_min'] is not None else d_break
        if (s, e, brk) == (d_start, d_end, d_break):
            continue
        tid = _find_or_create(conn, tpl, start=s, end=e, brk=brk, grace=None,
                              name_hint=f"{t['name']} shift")
        conn.execute(teams.update().where(teams.c.id == t['id']).values(shift_template_id=tid))

    # 3) Users: legacy per-employee override -> a template (break/grace inherited the base, so use
    #    the company default's break + system grace).
    for u in conn.execute(sa.select(users)).mappings().all():
        if u['shift_template_id'] is not None or (not u['shift_start'] and not u['shift_end']):
            continue
        s = u['shift_start'] or d_start
        e = u['shift_end'] or d_end
        tid = _find_or_create(conn, tpl, start=s, end=e, brk=d_break, grace=None,
                              name_hint="Custom shift")
        conn.execute(users.update().where(users.c.id == u['id']).values(shift_template_id=tid))

    # 4) Retire the legacy columns — shift times now live only in templates.
    with op.batch_alter_table('teams') as b:
        b.drop_column('shift_start')
        b.drop_column('shift_end')
        b.drop_column('break_duration_min')
    with op.batch_alter_table('users') as b:
        b.drop_column('shift_start')
        b.drop_column('shift_end')


def downgrade() -> None:
    # Re-add the legacy columns (structure only; the split-out templates are left in place).
    with op.batch_alter_table('users') as b:
        b.add_column(sa.Column('shift_start', sa.String(length=5), nullable=True))
        b.add_column(sa.Column('shift_end', sa.String(length=5), nullable=True))
    with op.batch_alter_table('teams') as b:
        b.add_column(sa.Column('shift_start', sa.String(length=5), server_default='08:00'))
        b.add_column(sa.Column('shift_end', sa.String(length=5), server_default='17:00'))
        b.add_column(sa.Column('break_duration_min', sa.Integer(), server_default='60'))
    with op.batch_alter_table('shift_templates') as b:
        b.drop_column('is_default')

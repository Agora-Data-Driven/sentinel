"""Recurring / retainer services (WP 6.1, M10).

Monthly deliverables were re-created by hand every month — so they get forgotten in exactly the
months somebody is too busy to remember, which is when the client notices.

🔴 THE PERIOD KEY IS THE WHOLE DESIGN. A recurrence records the last period it generated for as a
STRING ("2026-08", "2026-W32"), not a timestamp. The generator asks "have I already made this
period's task?", and that question answers identically however often the tick runs, on however
many instances, and whether or not it ran late. A `last_run_at` datetime cannot do that: two ticks
in a day, a retry after a partial failure, or a catch-up run after an outage would each have to
reason about clock windows, and one of them would eventually double-create a client's deliverable.
Duplicated retainer work is worse than late retainer work — somebody does it twice and bills once.

🔴 NO BACKFILL, EVER. A recurrence created today does not retro-generate the periods before it
existed, and a tick that has been down for three months generates ONE task on its return, not
three. `_initial_period` seeds `last_period` at creation so the first task lands at the next real
boundary. Eleven months of invented work is a worse Monday than a missing month.
"""
from __future__ import annotations

import calendar
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import RecurringService, Task, User
from . import task_config, task_templates
from . import maintasks as maintasks_svc

MONTHLY = "monthly"
WEEKLY = "weekly"
CADENCES = (MONTHLY, WEEKLY)


def period_key(cadence: str, day: date) -> str:
    """The identity of the period `day` falls in. Stable, comparable, and cheap to store."""
    if cadence == WEEKLY:
        iso = day.isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"
    return f"{day.year}-{day.month:02d}"


def trigger_day(rec: RecurringService, day: date) -> date:
    """The date within `day`'s period on which this recurrence should fire."""
    if rec.cadence == WEEKLY:
        want = max(0, min(6, rec.day_of_period or 0))
        return day - timedelta(days=day.weekday() - want)
    # Monthly: clamp to the month's length so "the 31st" still fires in February rather than
    # silently never firing — a retainer that skips short months is a support ticket.
    last = calendar.monthrange(day.year, day.month)[1]
    return date(day.year, day.month, max(1, min(rec.day_of_period or 1, last)))


def _initial_period(cadence: str, day_of_period: int, today: date) -> str | None:
    """What `last_period` should be for a recurrence created today.

    If this period's trigger day has already passed, claim the period so we do NOT retroactively
    invent work for it. If it is still ahead, leave it unset so the first task lands this period,
    which is what somebody setting up "the 10th" on the 5th expects.
    """
    probe = RecurringService(cadence=cadence, day_of_period=day_of_period)
    return period_key(cadence, today) if trigger_day(probe, today) <= today else None


def is_due(rec: RecurringService, today: date) -> bool:
    if not rec.is_active or rec.cadence not in CADENCES:
        return False
    if rec.last_period == period_key(rec.cadence, today):
        return False                      # already generated for this period
    return today >= trigger_day(rec, today)


def generate_one(db: Session, rec: RecurringService, today: date, actor: User | None) -> Task:
    """Create this period's task and claim the period. Caller commits."""
    statuses = task_config.statuses(db)
    maintasks = task_templates.maintasks_for(db, rec.service_key) if rec.service_key else []
    tpl = task_templates.get(db, rec.service_key) if rec.service_key else None

    task = Task(
        # The period is IN the title on purpose: three "Monthly SEO report" cards on one board are
        # indistinguishable, and the whole point is knowing which month is outstanding.
        title=f"{rec.title} — {period_key(rec.cadence, today)}"[:200],
        client_id=rec.client_id,
        content_type=tpl.content_type if tpl else None,
        assigned_team_id=rec.assigned_team_id,
        assigned_to_id=rec.assigned_to_id,
        created_by_id=actor.id if actor else rec.created_by_id,
        account_manager_id=rec.created_by_id,
        priority=rec.priority or "Medium",
        status=statuses[0] if statuses else "To Do",
        start_date=today,
        due_date=today + timedelta(days=max(0, rec.due_in_days or 0)),
        maintasks_json=maintasks_svc.dumps(maintasks),
    )
    db.add(task)
    db.flush()
    rec.last_period = period_key(rec.cadence, today)
    return task


def run(db: Session, today: date | None = None, actor: User | None = None) -> dict:
    """Generate every recurrence that is due. Idempotent within a period.

    Called from the daily cron, so it must be safe to run repeatedly — a second call on the same
    day generates nothing, because every recurrence has claimed the period.
    """
    day = today or date.today()
    rows = db.execute(
        select(RecurringService).where(RecurringService.is_active.is_(True))
    ).scalars().all()
    created = []
    for rec in rows:
        if not is_due(rec, day):
            continue
        task = generate_one(db, rec, day, actor)
        created.append({"recurring_id": rec.id, "task_id": task.id, "title": task.title})
    if created:
        db.commit()
    return {"created": created, "count": len(created)}


def seed_period(rec: RecurringService, today: date) -> None:
    """Stamp a freshly-created recurrence so it cannot backfill. Call before the first commit."""
    rec.last_period = _initial_period(rec.cadence, rec.day_of_period, today)

"""Derived workload/delivery metrics for the Monitor rollup — no new columns, no new tables.

Monitor answered "how many cards is each person holding?". That is a poor proxy for "who is
drowning?", because **a task carries no size on this board** — no hours, no estimate, no points — so
one card can be a ten-minute copy tweak or a three-week build. Rather than invent an effort field
nobody would fill in (a half-populated estimate produces worse numbers than none), everything here is
derived from data the board already keeps honestly:

    how long work takes them      -> start_date/created_at -> completed_at   (median cycle days)
    whether it lands when promised-> completed_at vs due_date                (on-time rate)
    what is going stale on them   -> created_at / updated_at of OPEN cards   (oldest, untouched)
    whether they are even here    -> approved leave (the same DB)            (capacity)

🔴 **None of these is an effort measure, and the UI must never present them as one.** They are
comparative signals a manager reads together. The one explicit judgement — `load_band` — is defined
strictly RELATIVE to the cohort's own median and is labelled that way on screen; an absolute
"overloaded" verdict is exactly the number that would start lying the first time a team's mix of work
changed.

Two rules inherited from the rest of the board and re-stated because they are easy to lose here:

* **"Done" is a STAGE test** (`task_config.is_completed`), never `status == "Completed"` — statuses
  are renameable and a rename ships in the deploy (AGENTS.md §5).
* **Completion is `completed_at`, never `updated_at`** (§2.4h). A task finished before that column
  existed carries no stamp and is counted in NO window — the honest answer.
"""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..constants import LEAVE_APPROVED
from ..models import LeaveRequest, Task
from ..utils.time import to_ph

# An open card nobody has touched in this long is "sitting". Two weeks is the shortest span that
# survives a normal holiday + handover without crying wolf; it is a display threshold, not a rule.
STALE_DAYS = 14
# How far ahead capacity looks. A fortnight matches STALE_DAYS and covers the usual planning horizon.
LEAVE_LOOKAHEAD_DAYS = 14


def _median(values: list[float]) -> float | None:
    """Median, or None for an empty series.

    Median rather than mean throughout: one six-month epic drags a mean so far that a person's
    typical week becomes unreadable, and long-tailed is exactly how task durations are distributed.
    """
    if not values:
        return None
    s = sorted(values)
    mid = len(s) // 2
    return float(s[mid]) if len(s) % 2 else (s[mid - 1] + s[mid]) / 2.0


def started_on(t: Task) -> date | None:
    """When the work began: the explicit `start_date`, else the day the card was raised.

    Falling back to `created_at` is what makes cycle time available for the whole board instead of
    only the minority of cards somebody dated. It reads slightly long for a card that sat in the
    backlog before anyone picked it up — which is real waiting, and arguably the part worth seeing.
    """
    if getattr(t, "start_date", None):
        return t.start_date
    created = getattr(t, "created_at", None)
    return to_ph(created).date() if created else None


def cycle_days(t: Task) -> int | None:
    """Calendar days from start to completion, or None if either end is unknown.

    Calendar, not working, days: leave and weekends are part of how long a client waited, and the
    board has no per-person calendar to subtract them with anyway. Clamped at 0 — a card completed
    before its own start_date is a data-entry artefact, and a negative would poison the median.
    """
    done = getattr(t, "completed_at", None)
    start = started_on(t)
    if not done or not start:
        return None
    return max(0, (to_ph(done).date() - start).days)


def delivery(tasks: list[Task], window_start: date, done_statuses: set[str]) -> dict:
    """Cycle time + on-time rate over work COMPLETED in the window.

    🔴 `on_time_rate` is None, not 0, when nothing dated was completed. Zero means "everything was
    late", and a person who simply finished nothing datable this month must not be rendered in the
    same red as one who missed every deadline. Undated completions are excluded from the rate
    entirely rather than counted as on time — a card with no due date made no promise to keep.
    """
    cycles: list[float] = []
    dated = on_time = 0
    completed = 0
    for t in tasks:
        if t.status not in done_statuses:
            continue                                  # reopened since: not finished work today
        done_at = getattr(t, "completed_at", None)
        if not done_at:
            continue                                  # finished before the column existed
        done_day = to_ph(done_at).date()
        if done_day < window_start:
            continue
        completed += 1
        c = cycle_days(t)
        if c is not None:
            cycles.append(c)
        if t.due_date:
            dated += 1
            if done_day <= t.due_date:
                on_time += 1
    return {
        "completed_window": completed,
        "median_cycle_days": _median(cycles),
        "on_time_rate": round(100.0 * on_time / dated) if dated else None,
        "on_time_of": dated,
    }


def aging(open_tasks: list[Task], today: date) -> dict:
    """How long the OPEN pile has been sitting: the oldest card, and how many are untouched.

    `oldest_open_days` uses `created_at` (how long this has been owed) while `stale_open` uses
    `updated_at` (how long since anybody moved it). Deliberately two different clocks — a card raised
    in January and worked on yesterday is old but not stale, and only the second is a problem.
    """
    ages: list[int] = []
    stale = 0
    for t in open_tasks:
        created = getattr(t, "created_at", None)
        if created:
            ages.append(max(0, (today - to_ph(created).date()).days))
        touched = getattr(t, "updated_at", None) or created
        if touched and (today - to_ph(touched).date()).days >= STALE_DAYS:
            stale += 1
    return {"oldest_open_days": max(ages) if ages else None, "stale_open": stale}


def leave_context(db: Session, user_ids: list[int], today: date,
                  ahead_days: int = LEAVE_LOOKAHEAD_DAYS) -> dict[int, dict]:
    """Approved leave per person: on leave today, and days booked in the next fortnight.

    This is the piece that turns a count into a judgement. "Nine open cards" means one thing for
    somebody at their desk and another for somebody who is out all next week — and the board already
    holds the answer, one table over. Only APPROVED leave counts: a pending request is a question,
    not a fact about capacity.
    """
    if not user_ids:
        return {}
    horizon = today + timedelta(days=ahead_days)
    rows = db.execute(
        select(LeaveRequest).where(
            LeaveRequest.user_id.in_(user_ids),
            LeaveRequest.status == LEAVE_APPROVED,
            LeaveRequest.start_date <= horizon,
            LeaveRequest.end_date >= today,
        )
    ).scalars().all()
    out: dict[int, dict] = {}
    for r in rows:
        c = out.setdefault(r.user_id, {"on_leave_today": False, "leave_days_ahead": 0})
        if r.start_date <= today <= r.end_date:
            c["on_leave_today"] = True
        # Overlap of the request with [today, horizon], counted in calendar days. Clipped to the
        # window so a three-month sabbatical doesn't report 90 days against a 14-day horizon.
        first = max(r.start_date, today)
        last = min(r.end_date, horizon)
        c["leave_days_ahead"] += max(0, (last - first).days + 1)
    return out


def apply_load_bands(rows: list[dict]) -> None:
    """Tag each row `light` / `steady` / `heavy` **relative to this cohort's median**, in place.

    🔴 Relative on purpose, and the UI says so. An absolute threshold ("more than 8 cards = heavy")
    would be a number invented here rather than measured, and it would mean something different for
    every department on the board. Comparing a team against itself is a claim the data can actually
    support: it answers "who is carrying more than their colleagues right now", which is the question
    asked, and it stays true when the team's mix of work changes.

    Two guards that stop the band from being noise:

    * a cohort whose median is 0 or 1 gets NO band — with almost no work on the board, "double the
      median" is one card, and flagging somebody heavy for that is worse than saying nothing;
    * `overdue` promotes a row to `heavy` regardless of volume. Three cards that are all late is a
      person in trouble, and a purely volumetric band would render them as `light`.
    """
    counts = sorted(r["open_total"] for r in rows)
    med = _median([float(c) for c in counts]) or 0.0
    for r in rows:
        if med < 2:
            r["load_band"] = None
            continue
        if r["open_total"] >= med * 1.5 or r["overdue"] >= 3:
            r["load_band"] = "heavy"
        elif r["open_total"] <= med * 0.5:
            r["load_band"] = "light"
        else:
            r["load_band"] = "steady"

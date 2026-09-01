"""Client HEALTH — red / amber / green per account, derived from the board (2026-09-02).

The AM's "My accounts" table and the COO's Operations page both read this. The colour is a RULE and
the rule is printed on both screens, because a traffic light nobody can explain is a traffic light
nobody trusts:

    RED    = something is overdue, blocked ON US for more than 2 days, or a review has waited > 24h
    AMBER  = something is due today, waiting on the CLIENT, or untouched for 14 days
    GREEN  = none of the above

Every number is derived from Sentinel's own `tasks` rows. Atrium-owned cards that no Sentinel row
has adopted are NOT counted here (they carry no hold kind, no review state and no reliable dates) —
the Task Board still shows them, and `task_adoption` is the way to bring them under this rollup.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..constants import HOLD_KINDS, REVIEW_PENDING
from ..models import Client, Task, TaskHistory, User
from ..serializers import CardPrefetch, task_card, user_public
from ..utils.time import today_ph, utcnow
from . import task_config

STALE_DAYS = 14
BLOCKED_ON_US_DAYS = 2
REVIEW_STALE_HOURS = 24
HEALTH_RULE = ("red = overdue, blocked on us > 2 days, or a review waiting > 24h · "
               "amber = due today, waiting on the client, or untouched 14 days · else green")


def _open_tasks(db: Session) -> list[Task]:
    return db.execute(
        select(Task).where(Task.archived.is_(False), Task.client_id.is_not(None))
    ).scalars().all()


def _stage_map(db: Session, tasks: list[Task]) -> dict[str, str | None]:
    return {s: task_config.stage_for(db, s) for s in {t.status for t in tasks}}


def _last_change(db: Session, task_ids: list[int], field: str, value: str) -> dict[int, datetime]:
    """When each task LAST entered `field == value` — from the history, which is the one honest clock."""
    if not task_ids:
        return {}
    rows = db.execute(
        select(TaskHistory.task_id, TaskHistory.changed_at)
        .where(TaskHistory.task_id.in_(task_ids), TaskHistory.field_changed == field,
               TaskHistory.new_value == value)
        .order_by(TaskHistory.changed_at)
    ).all()
    out: dict[int, datetime] = {}
    for tid, at in rows:
        out[tid] = at            # ordered ascending, so the last write wins
    return out


def hold_since(db: Session, tasks: list[Task]) -> dict[int, datetime]:
    """When each parked task was parked. `park()` logs `on_hold` with the reason as the new value,
    `_sync_hold` logs "parked"; both are 'on_hold' rows that are not 'resumed'."""
    ids = [t.id for t in tasks if getattr(t, "on_hold", False)]
    if not ids:
        return {}
    rows = db.execute(
        select(TaskHistory.task_id, TaskHistory.changed_at, TaskHistory.new_value)
        .where(TaskHistory.task_id.in_(ids), TaskHistory.field_changed == "on_hold")
        .order_by(TaskHistory.changed_at)
    ).all()
    out: dict[int, datetime] = {}
    for tid, at, new in rows:
        if new != "resumed":
            out[tid] = at
    # A hold with no history row (a pre-history DB) falls back to the row's last edit.
    for t in tasks:
        if t.id in ids and t.id not in out:
            out[t.id] = t.updated_at or t.created_at
    return out


def review_since(db: Session, tasks: list[Task]) -> dict[int, datetime]:
    ids = [t.id for t in tasks if getattr(t, "review_state", None) == REVIEW_PENDING]
    out = _last_change(db, ids, "review_state", REVIEW_PENDING)
    for t in tasks:
        if t.id in ids and t.id not in out:
            out[t.id] = t.updated_at or t.created_at
    return out


def classify(rows: dict) -> tuple[str, list[str]]:
    """The rule, in one place. Returns (health, reasons)."""
    why: list[str] = []
    if rows["overdue"]:
        why.append(f"{rows['overdue']} overdue")
    if rows["blocked_on_us_late"]:
        why.append(f"{rows['blocked_on_us_late']} blocked on us > {BLOCKED_ON_US_DAYS}d")
    if rows["review_stale"]:
        why.append(f"{rows['review_stale']} review waiting > {REVIEW_STALE_HOURS}h")
    if why:
        return "red", why
    if rows["due_today"]:
        why.append(f"{rows['due_today']} due today")
    if rows["blocked_on_client"]:
        why.append(f"{rows['blocked_on_client']} waiting on the client")
    if rows["stale"]:
        why.append(f"{rows['stale']} untouched {STALE_DAYS}d")
    if why:
        return "amber", why
    return "green", ["on track"]


def rollup(db: Session, viewer: User | None = None, today: date | None = None) -> list[dict]:
    """One row per ACTIVE client, sorted red → amber → green then by name."""
    today = today or today_ph()
    now = utcnow()
    clients = db.execute(select(Client).where(Client.is_active.is_(True)).order_by(Client.name)).scalars().all()
    tasks = _open_tasks(db)
    stage_of = _stage_map(db, tasks)
    parked_since = hold_since(db, tasks)
    reviewed_since = review_since(db, tasks)
    ams = {u.id: u for u in db.execute(select(User).where(
        User.id.in_([c.account_manager_id for c in clients if c.account_manager_id] or [-1]))).scalars()}
    by_client: dict[int, list[Task]] = {}
    for t in tasks:
        by_client.setdefault(t.client_id, []).append(t)
    out: list[dict] = []
    for c in clients:
        ts = by_client.get(c.id, [])
        open_ts = [t for t in ts if stage_of.get(t.status) != "completed"]
        blocked = [t for t in open_ts if stage_of.get(t.status) == "blocked"]
        on_client = [t for t in blocked if getattr(t, "hold_kind", None) == "client"]
        on_us = [t for t in blocked if getattr(t, "hold_kind", None) != "client"]
        on_us_late = [t for t in on_us
                      if (now - parked_since.get(t.id, now)) >= timedelta(days=BLOCKED_ON_US_DAYS)]
        overdue = [t for t in open_ts if t.due_date and t.due_date < today
                   and stage_of.get(t.status) != "blocked"]
        due_today = [t for t in open_ts if t.due_date == today]
        reviews = [t for t in open_ts if getattr(t, "review_state", None) == REVIEW_PENDING]
        review_stale = [t for t in reviews
                        if (now - reviewed_since.get(t.id, now)) >= timedelta(hours=REVIEW_STALE_HOURS)]
        stale = [t for t in open_ts if stage_of.get(t.status) != "blocked"
                 and (t.updated_at or t.created_at) and (now - (t.updated_at or t.created_at)) >= timedelta(days=STALE_DAYS)]
        counts = {
            "open": len(open_ts), "overdue": len(overdue), "due_today": len(due_today),
            "blocked": len(blocked), "blocked_on_client": len(on_client), "blocked_on_us": len(on_us),
            "blocked_on_us_late": len(on_us_late), "reviews": len(reviews),
            "review_stale": len(review_stale), "stale": len(stale),
            "completed_14d": len([t for t in ts if t.completed_at and (now - t.completed_at) <= timedelta(days=14)]),
        }
        health, why = classify(counts)
        upcoming = sorted([t for t in open_ts if t.due_date and t.due_date >= today], key=lambda t: t.due_date)
        nxt = upcoming[0] if upcoming else None
        am = ams.get(c.account_manager_id) if c.account_manager_id else None
        out.append({
            "client": {"id": c.id, "name": c.name, "atrium_client_id": c.atrium_client_id},
            "account_manager_id": c.account_manager_id,
            "account_manager": user_public(am),
            "health": health,
            "why": why,
            **counts,
            "next": {"task_id": nxt.id, "title": nxt.title, "due_date": nxt.due_date.isoformat()} if nxt else None,
        })
    order = {"red": 0, "amber": 1, "green": 2}
    out.sort(key=lambda r: (order[r["health"]], r["client"]["name"].lower()))
    return out


def overview(db: Session, client: Client, viewer: User, today: date | None = None) -> dict:
    """One client, in depth: the cards by specialist, the blockers and on whom, the reviews, what is
    due in the next fortnight, and what shipped in the last one."""
    today = today or today_ph()
    now = utcnow()
    tasks = db.execute(
        select(Task).where(Task.client_id == client.id, Task.archived.is_(False)).order_by(Task.due_date)
    ).scalars().all()
    stage_of = _stage_map(db, tasks)
    pre = CardPrefetch.for_tasks(db, tasks)
    parked_since = hold_since(db, tasks)
    open_ts = [t for t in tasks if stage_of.get(t.status) != "completed"]
    cards = {t.id: task_card(t, db, viewer=viewer, pre=pre) for t in tasks}
    for t in tasks:
        cards[t.id]["stage"] = stage_of.get(t.status)
    by_lead: dict[str, dict] = {}
    for t in open_ts:
        key = str(t.assigned_to_id or 0)
        slot = by_lead.setdefault(key, {"user": cards[t.id]["assignee"], "tasks": []})
        slot["tasks"].append(cards[t.id])
    blockers = []
    for t in open_ts:
        if stage_of.get(t.status) == "blocked":
            since = parked_since.get(t.id)
            blockers.append({
                **cards[t.id],
                "hold_kind": getattr(t, "hold_kind", None),
                "hold_kind_label": HOLD_KINDS.get(getattr(t, "hold_kind", None) or "", "Parked"),
                "hold_reason": getattr(t, "hold_reason", None),
                "blocked_by_task_id": getattr(t, "blocked_by_task_id", None),
                "blocked_days": (now - since).days if since else None,
            })
    reviews = [cards[t.id] for t in open_ts if getattr(t, "review_state", None) == REVIEW_PENDING]
    completed = [cards[t.id] for t in tasks
                 if t.completed_at and (now - t.completed_at) <= timedelta(days=14)]
    completed.sort(key=lambda c: c["completed_at"] or "", reverse=True)
    horizon = today + timedelta(days=14)
    commitments = [{"task_id": t.id, "title": t.title, "due_date": t.due_date.isoformat(),
                    "assignee": cards[t.id]["assignee"]}
                   for t in open_ts if t.due_date and today <= t.due_date <= horizon]
    row = next((r for r in rollup(db, viewer, today) if r["client"]["id"] == client.id), None)
    return {
        "client": {"id": client.id, "name": client.name, "atrium_client_id": client.atrium_client_id,
                   "account_manager_id": client.account_manager_id,
                   "account_manager": row["account_manager"] if row else None},
        "health": row["health"] if row else "green",
        "why": row["why"] if row else ["on track"],
        "counts": {k: row[k] for k in ("open", "overdue", "due_today", "blocked", "blocked_on_client",
                                       "blocked_on_us", "reviews", "stale", "completed_14d")} if row else {},
        "by_lead": list(by_lead.values()),
        "blockers": blockers,
        "reviews": reviews,
        "commitments": commitments,
        "completed": completed,
        "rule": HEALTH_RULE,
    }

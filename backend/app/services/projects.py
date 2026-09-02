"""PROJECTS — rollups for the thin project layer (models/project.py, 2026-09-02).

Everything here is DERIVED from the milestones and the linked tasks; a project stores nothing the
page computes. Health follows the same printed-rule philosophy as `client_health`: a colour is only
trustworthy when the words beside it say why.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Project, ProjectMilestone, Task, User
from ..serializers import CardPrefetch, task_card, user_public
from ..utils.time import today_ph
from . import task_config

HEALTH_RULE = ("Red = past its target date with work left, or any linked card overdue. "
               "Amber = a milestone past its own date, or linked work parked. Else green.")

STATUSES = ("active", "done", "archived")


def _iso(d) -> str | None:
    return d.isoformat() if d else None


def milestone_dict(m: ProjectMilestone, db: Session) -> dict:
    by = db.get(User, m.done_by_id) if m.done_by_id else None
    return {
        "id": m.id, "project_id": m.project_id, "title": m.title, "detail": m.detail,
        "target_date": _iso(m.target_date), "done": bool(m.done),
        "done_at": (m.done_at.isoformat() + "Z") if m.done_at else None,
        "done_by": user_public(by), "position": m.position,
    }


def _health(p: Project, today: date, open_ts: list[Task],
            stage_of: dict[str, str | None]) -> tuple[str, list[str]]:
    """(colour, why-in-words). A non-active project simply reports its status — no colour theatre."""
    if p.status != "active":
        return p.status, []
    why_red: list[str] = []
    why_amber: list[str] = []
    overdue = [t for t in open_ts if t.due_date and t.due_date < today
               and stage_of.get(t.status) != "blocked"]
    work_left = bool(open_ts) or not all(m.done for m in p.milestones)
    if p.target_date and p.target_date < today and work_left:
        why_red.append(f"past its {p.target_date:%b} {p.target_date.day} target")
    if overdue:
        why_red.append(f"{len(overdue)} linked card{'s' if len(overdue) != 1 else ''} overdue")
    for m in [m for m in p.milestones if not m.done and m.target_date and m.target_date < today][:2]:
        why_amber.append(f"milestone “{m.title}” past its date")
    parked = [t for t in open_ts if stage_of.get(t.status) == "blocked"]
    if parked:
        why_amber.append(f"{len(parked)} linked card{'s' if len(parked) != 1 else ''} parked")
    if why_red:
        return "red", why_red + why_amber
    if why_amber:
        return "amber", why_amber
    return "green", []


def _rollup(db: Session, p: Project, tasks: list[Task], today: date) -> dict:
    stage_of = {s: task_config.stage_for(db, s) for s in {t.status for t in tasks}}
    open_ts = [t for t in tasks if stage_of.get(t.status) != "completed"]
    done_ts = [t for t in tasks if stage_of.get(t.status) == "completed"]
    health, why = _health(p, today, open_ts, stage_of)
    ms = list(p.milestones)
    next_ms = next((m for m in ms if not m.done), None)
    owner = db.get(User, p.owner_id) if p.owner_id else None
    return {
        "id": p.id, "name": p.name, "goal": p.goal, "status": p.status,
        "owner": user_public(owner), "target_date": _iso(p.target_date),
        "created_at": p.created_at.isoformat() + "Z",
        "milestones_total": len(ms), "milestones_done": len([m for m in ms if m.done]),
        "next_milestone": milestone_dict(next_ms, db) if next_ms else None,
        "tasks_open": len(open_ts), "tasks_done": len(done_ts),
        "tasks_overdue": len([t for t in open_ts if t.due_date and t.due_date < today
                              and stage_of.get(t.status) != "blocked"]),
        "tasks_blocked": len([t for t in open_ts if stage_of.get(t.status) == "blocked"]),
        "health": health, "why": why,
    }


def list_projects(db: Session) -> list[dict]:
    today = today_ph()
    projects = db.execute(select(Project).order_by(Project.created_at)).scalars().all()
    linked = db.execute(select(Task).where(Task.project_id.is_not(None))).scalars().all()
    by_project: dict[int, list[Task]] = {}
    for t in linked:
        by_project.setdefault(t.project_id, []).append(t)
    rows = [_rollup(db, p, by_project.get(p.id, []), today) for p in projects]
    # Active first (the point of the page), then done, then archived — creation order within each.
    order = {"active": 0, "done": 1, "archived": 2}
    rows.sort(key=lambda r: order.get(r["status"], 3))
    return rows


def overview(db: Session, p: Project, viewer: User) -> dict:
    """One project in depth: milestones + the linked tasks, as board cards.

    🔴 The task lists go through `task_card(viewer=…)` like the board itself, so `mine`/`can_edit`
    behave identically — but the LIST is deliberately NOT filtered by `can_view`: this page is a
    management surface (capability `projects.view` — manager roles + the viewer seat), and hiding a
    linked card from the person tracking the outcome would make the rollup numbers disagree with
    the list under them.
    """
    today = today_ph()
    tasks = db.execute(select(Task).where(Task.project_id == p.id)
                       .order_by(Task.updated_at.desc())).scalars().all()
    stage_of = {s: task_config.stage_for(db, s) for s in {t.status for t in tasks}}
    open_ts = [t for t in tasks if stage_of.get(t.status) != "completed"]
    done_ts = [t for t in tasks if stage_of.get(t.status) == "completed"]
    pre = CardPrefetch.for_tasks(db, tasks)
    d = _rollup(db, p, tasks, today)
    d.update({
        "milestones": [milestone_dict(m, db) for m in p.milestones],
        "open_tasks": [task_card(t, db, viewer=viewer, pre=pre) for t in open_ts],
        # Done is capped: this page is about what's left; Past work already lists history in full.
        "done_tasks": [task_card(t, db, viewer=viewer, pre=pre) for t in done_ts[:30]],
        "done_truncated": max(0, len(done_ts) - 30),
        "health_rule": HEALTH_RULE,
    })
    return d

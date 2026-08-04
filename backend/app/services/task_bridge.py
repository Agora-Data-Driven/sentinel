"""The Atrium projection: publishing a Sentinel task, and keeping the client's copy current.

Sentinel owns every field of a task. Atrium holds a **copy of the client-safe subset** for the
client's Tasks tab and authors nothing (docs/TASKBOARD_REBUILD.md §4, decisions D1/D2). So the
data flows one way and there is nothing to reconcile:

    publish(task)      mint the Atrium card, store its id on the row
    push(task)         re-send the client-safe subset after any change to it
    push_stage(task)   move the client's card to the stage matching our status

🔴 Two rules this module exists to hold in one place.

1. **Only `SAFE` crosses.** Assignee, team, priority, service charge, internal notes, the creator
   tag and every step's "done when" stay here. `serializers.py` is the field-exposure boundary for
   responses; this is the boundary for the bridge, and `client_safe_fields` is the only thing that
   builds a bridge payload.
2. **A failed push is LOUD.** It records `task.atrium_sync_error` so the row itself knows the
   client's card is stale, the board can say so, and it can be retried. The bug this stage removes
   was exactly the opposite — a success toast over a client tab that stayed empty forever.

Reads stay fail-soft (an Atrium outage hides cards); writes report. That asymmetry is deliberate
and predates this module (see `atrium_tasks._atrium_error`).
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import Client, Task, TaskHistory, User
from . import atrium_tasks
from . import maintasks as MT

# The client-safe subset, in Atrium's own field names. Anything not listed here never crosses.
# `maintasks` is the two-level breakdown reduced to phase names + step text/done — Atrium renders
# it to the client as phases with a count, and the internal `dod` has no equivalent to send.
#
# `start_date` joined the list on 2026-08-03 (M5): it is a schedule fact, and Atrium renders the
# client a Started → Going live timeline from it. `hold_reason` deliberately did NOT join it —
# Sentinel now stores one (M3), but a pause is usually about money, legal, or a client who has gone
# quiet. The client's card shows the STAGE it is parked in; the reason stays internal.
SAFE = ("title", "client_note", "due_date", "start_date", "deliverable_url", "maintasks")


def _dept_label(db: Session, task: Task) -> str:
    """Atrium derives the client-visible label from the department, so send the department name."""
    if not task.assigned_team_id:
        return ""
    from ..models import Team

    team = db.get(Team, task.assigned_team_id)
    return team.name if team else ""


def client_safe_fields(task: Task, db: Session) -> dict:
    """The ONLY payload builder for the bridge. Keys are Atrium's, values are client-safe."""
    out: dict = {
        "title": task.title or "",
        "client_note": task.client_facing_notes or "",
        "due_date": task.due_date.isoformat() if task.due_date else "",
        "start_date": task.start_date.isoformat() if getattr(task, "start_date", None) else "",
        "deliverable_url": task.deliverable_url or "",
    }
    # The breakdown, stripped to what a client may see: the phase's name and each step's text +
    # done flag. No owners, no "done when".
    groups = MT.normalize(getattr(task, "maintasks_json", "[]"), task.checklist_json)
    out["maintasks"] = [
        {
            "text": (g.get("title") or "").strip(),
            "subs": [{"text": (s.get("text") or "").strip(), "done": bool(s.get("done"))}
                     for s in g.get("subs", [])],
        }
        for g in groups
    ]
    return out


def _stage_for(db: Session, task: Task) -> str:
    """Atrium's stage for this row's status, resolved through `task_vocab` (never the label).

    A status can be renamed freely — Manage cascades the new label onto every task row — so the
    only durable question is "which stage does this status carry?". '' means it carries none, and
    every caller refuses rather than guessing a column for the client's card.
    """
    from . import task_config

    return task_config.stage_for(db, task.status)


def _log(db: Session, task: Task, actor_id: int, field: str, old, new) -> None:
    db.add(TaskHistory(
        task_id=task.id, changed_by_id=actor_id, field_changed=field,
        old_value=None if old is None else str(old),
        new_value=None if new is None else str(new),
    ))


def client_key_for(db: Session, task: Task) -> str:
    """The Atrium workspace key for this task's client. '' when the link isn't set."""
    if not task.client_id:
        return ""
    client = db.get(Client, task.client_id)
    return (getattr(client, "atrium_client_id", "") or "").strip() if client else ""


def published(task: Task) -> bool:
    """A task is published only when a real Atrium card backs it. `atrium_visible` on its own is
    the pre-fix flag that referred to nothing."""
    return bool(getattr(task, "atrium_task_id", None))


def publish(db: Session, task: Task, user: User) -> tuple[bool, str]:
    """Mint the client's card and link it to this row. Returns (ok, error).

    Idempotent: publishing an already-published task re-pushes instead of creating a second card.
    """
    if published(task):
        return push(db, task, user)
    key = client_key_for(db, task)
    if not key:
        return False, ("That task has no Atrium client linked, so there is no workspace to share "
                       "it into. Set the client's Atrium workspace first.")
    stage = _stage_for(db, task)
    if not stage:
        return False, f'"{task.status}" has no Atrium stage, so the client\'s card has nowhere to sit.'

    task_id, err = atrium_tasks.add_task(
        key, task.title or "Untitled", stage=stage, client_facing=True,
        priority="Medium",                      # internal; Atrium needs a value, never ours
        department=_dept_label(db, task),
        due_date=task.due_date.isoformat() if task.due_date else "",
        actor=user.email or "", actor_name=user.name or "",
    )
    if err:
        task.atrium_sync_error = err
        return False, err

    task.atrium_task_id = task_id
    task.atrium_visible = True
    task.atrium_sync_error = None
    _log(db, task, user.id, "shared_with_client", "internal", f"atrium:{key}:{task_id}")
    # The card exists now but holds only what add_task accepts, so send the rest immediately —
    # the client note and the breakdown are the whole point of the card.
    ok, push_err = push(db, task, user)
    return (True, "") if ok else (True, push_err)


def push(db: Session, task: Task, user: User) -> tuple[bool, str]:
    """Re-send the client-safe subset. No-op (ok) for a task that isn't published."""
    if not published(task):
        return True, ""
    key = client_key_for(db, task)
    if not key:
        err = "That task's Atrium client link is gone, so its client card can't be updated."
        task.atrium_sync_error = err
        return False, err
    _envelope, err = atrium_tasks.edit_task(
        key, task.atrium_task_id, client_safe_fields(task, db), actor=user.email or "")
    task.atrium_sync_error = err or None
    return (not err), err


def push_stage(db: Session, task: Task, user: User) -> tuple[bool, str]:
    """Move the client's card to the stage matching our status."""
    if not published(task):
        return True, ""
    key = client_key_for(db, task)
    stage = _stage_for(db, task)
    if not key or not stage:
        err = (f'"{task.status}" has no Atrium stage.' if key
               else "That task's Atrium client link is gone.")
        task.atrium_sync_error = err
        return False, err
    ok, err = atrium_tasks.move_task(key, task.atrium_task_id, stage, actor=user.email or "")
    task.atrium_sync_error = None if ok else err
    return ok, err


def touches_client_view(data: dict) -> bool:
    """Does this PATCH body change anything the client can see? Keeps a priority-only edit — or a
    note nobody outside can read — from spending a bridge round trip."""
    watched = {"title", "client_facing_notes", "due_date", "start_date", "deliverable_url",
               "maintasks", "checklist", "assigned_team_id"}
    return bool(watched & set(data or {}))


def stale_shares(db: Session) -> list[dict]:
    """The reconcile backlog (D15): rows claiming to be shared that point at no card.

    Report only — publishing these in bulk would drop months-old, possibly already-delivered work
    onto clients' boards unannounced. A human decides per row.
    """
    from sqlalchemy import select

    rows = db.execute(
        select(Task).where(Task.atrium_visible.is_(True))
    ).scalars().all()
    out = []
    for t in rows:
        if published(t):
            continue
        client = db.get(Client, t.client_id) if t.client_id else None
        out.append({
            "id": t.id,
            "title": t.title,
            "status": t.status,
            "client_id": t.client_id,
            "client_name": client.name if client else None,
            "atrium_client_key": client_key_for(db, t),
            "due_date": t.due_date.isoformat() if t.due_date else None,
            "updated_at": t.updated_at.isoformat() if t.updated_at else None,
            "has_client_note": bool(t.client_facing_notes),
        })
    out.sort(key=lambda r: (r["client_name"] or "", r["id"]))
    return out


def clear_share(db: Session, task: Task, user: User) -> None:
    """Resolve a stale row the other way: it was never really shared, so stop claiming it was."""
    task.atrium_visible = False
    task.atrium_sync_error = None
    _log(db, task, user.id, "atrium", "claimed shared", "internal (never published)")


__all__ = [
    "SAFE", "client_safe_fields", "client_key_for", "published", "publish", "push",
    "push_stage", "touches_client_view", "stale_shares", "clear_share",
]
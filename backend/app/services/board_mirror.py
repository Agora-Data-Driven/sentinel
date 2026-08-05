"""The STAFF mirror of this board, for Atrium's operator console (`/admin/atrium` → Task Board).

🔴 This is not the bridge. Read `task_bridge.SAFE` first, then this docstring, because the two
modules answer opposite questions and confusing them would leak internal fields to clients:

* `task_bridge` builds the **client-safe projection** — what a CLIENT sees in their own workspace
  tab. Six fields cross. Assignee, priority, money, internal notes and hold reasons never do.
* This module builds the **staff mirror** — what a SUPER-ADMIN sees in Atrium's operator console,
  which is a staff-only surface behind `is_superadmin()`. Everything crosses, because the reader
  is the same delivery team that reads it here.

Why it exists. Atrium's admin Task Board used to be assembled from each client's workspace JSON,
i.e. from the client-safe projections — so it could only ever show work somebody had explicitly
shared with a client. Every unpublished row (never shared, or refused because the client had no
`atrium_client_id`) was structurally invisible on a board whose subtitle claims "every client
deliverable across every workspace". Two boards, two different answers to one question.

So the console reads THIS instead, and the shapes are Atrium's own task-dict keys — `stage` not
`status`, `lead_id` not `assigned_to_id`, `client_note` not `client_facing_notes`, emails not user
ids — because the console already has a renderer for that shape (`main._task_board`) and a
translation layer on each side is a translation layer that can disagree with itself.

🔴 `stage`, never the status LABEL. A status is renameable in Manage and the rename cascades onto
every task row, so a label is not an identity (decision D13). `task_config.stage_for` resolves the
column; several Sentinel statuses may legitimately fold onto one Atrium stage, and a custom status
with no stage at all falls back to `todo` rather than vanishing off the mirror — the console has
exactly five columns and a card outside them would be a card nobody can see.

Reads are BULK. Comments and history are relationships, so shaping N tasks one at a time is 2N
queries against Cloud SQL; every lookup here is preloaded into a dict first.
"""
from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Client, Task, TaskComment, TaskHistory, TaskRequest, Team, User
from . import maintasks as MT
from . import task_config

# Atrium's department KEYS (its `main.TASK_DEPARTMENTS`), resolved from a Sentinel Team name by its
# first word lower-cased — the same trick `constants.label_for_department` uses so that Sentinel's
# "Data Analyst" and Atrium's "data" agree without either side hardcoding the other's wording.
_ATRIUM_DEPT_KEYS = ("acquisition", "lifecycle", "data", "development", "bidbrain")


def _dept_key(team_name: str | None) -> str:
    first = (team_name or "").strip().split()
    if not first:
        return ""
    slug = first[0].lower()
    return slug if slug in _ATRIUM_DEPT_KEYS else ""


def _loads(raw, default):
    try:
        v = json.loads(raw) if isinstance(raw, str) else raw
        return v if isinstance(v, type(default)) else default
    except (TypeError, ValueError):
        return default


def _iso_date(d) -> str:
    return d.isoformat() if d else ""


def _iso_dt(d) -> str:
    return d.isoformat() + "Z" if d else ""


def board(db: Session) -> list[dict]:
    """Every LIVE task on this board, in Atrium's task-dict shape.

    Filed work (`archived`) is excluded, matching the board itself: the Completed column is a
    working column and Past work is a separate list, so padding the console's mirror with months of
    filed cards would make its counts mean something different from the counts here.
    """
    tasks = db.execute(
        select(Task).where(Task.archived.is_(False)).order_by(Task.id)
    ).scalars().all()
    if not tasks:
        return []

    ids = [t.id for t in tasks]
    users = {u.id: u for u in db.execute(select(User)).scalars().all()}
    clients = {c.id: c for c in db.execute(select(Client)).scalars().all()}
    teams = {t.id: t for t in db.execute(select(Team)).scalars().all()}

    comments: dict[int, list[TaskComment]] = {}
    for c in db.execute(
        select(TaskComment).where(TaskComment.task_id.in_(ids)).order_by(TaskComment.id)
    ).scalars().all():
        comments.setdefault(c.task_id, []).append(c)

    history: dict[int, list[TaskHistory]] = {}
    for h in db.execute(
        select(TaskHistory).where(TaskHistory.task_id.in_(ids)).order_by(TaskHistory.id)
    ).scalars().all():
        history.setdefault(h.task_id, []).append(h)

    # Which rows began life as a CLIENT'S ask (D3). Atrium renders a "Client req" pill off this, and
    # only an accepted request has a task_id, so this is exactly the set that earns the pill.
    requested = {
        r.task_id: (r.requester_name or "")
        for r in db.execute(
            select(TaskRequest).where(TaskRequest.task_id.in_(ids))
        ).scalars().all() if r.task_id
    }

    # Resolved once, not per task: `stage_for` walks the vocab rows on every call.
    stage_by_status = {s: task_config.stage_for(db, s) for s in {t.status for t in tasks}}

    def email(uid) -> str:
        u = users.get(uid) if uid else None
        return (u.email or "") if u else ""

    out = []
    for t in tasks:
        client = clients.get(t.client_id) if t.client_id else None
        team = teams.get(t.assigned_team_id) if t.assigned_team_id else None
        groups = MT.normalize(getattr(t, "maintasks_json", "[]"), t.checklist_json)
        out.append({
            # 🔴 The DOM key Atrium's console builds every `data-open` / `data-tkd` pair from. It is
            # prefixed because the console renders this mirror ALONGSIDE the Atrium-origin cards no
            # Sentinel row has adopted yet, and a bare integer could collide with an Atrium task id.
            "id": "s%d" % t.id,
            "sentinel_id": t.id,
            # What Sentinel's own board expects in `?open=` — the deep link the console's footer
            # button uses. For a Sentinel row that is the bare row id.
            "open_ref": str(t.id),
            "client_key": (getattr(client, "atrium_client_id", "") or "").strip() if client else "",
            "client_name": (client.name if client else "") or "Unassigned client",
            "stage": stage_by_status.get(t.status) or "todo",
            # The Sentinel column's CURRENT label, so the console can name the real column even when
            # several statuses fold onto one Atrium stage. Display only — never key anything off it.
            "status": t.status or "",
            "title": t.title or "",
            "priority": t.priority or "Medium",
            "due_date": _iso_date(t.due_date),
            "start_date": _iso_date(getattr(t, "start_date", None)),
            "created_at": _iso_dt(t.created_at),
            "department": _dept_key(team.name if team else None),
            "labels": _loads(t.labels_json, []),
            "lead_id": email(t.assigned_to_id),
            # Sentinel has no support list — one assignee owns a row, and phase/step owners are the
            # rest of the team on it. Sent empty rather than invented so the console's person filter
            # never claims somebody is on a task they only own one step of.
            "support_ids": [],
            "account_manager_id": email(t.account_manager_id),
            "maintasks": [
                {
                    # Atrium's phase key is `text`, Sentinel's is `title`.
                    "id": g.get("id") or "",
                    "text": g.get("title") or "",
                    "assignee_id": email(g.get("assignee_id")),
                    "subs": [{"id": s.get("id") or "", "text": s.get("text") or "",
                              "done": bool(s.get("done")),
                              "assignee_id": email(s.get("assignee_id"))}
                             for s in g.get("subs") or []],
                }
                for g in groups
            ],
            "on_hold": bool(getattr(t, "on_hold", False)),
            "hold_reason": getattr(t, "hold_reason", "") or "",
            "service_charge": t.service_charge or "",
            # `client_facing` means "the client can really see this", which is `atrium_task_id` and
            # never `atrium_visible` on its own — that flag spent months pointing at cards that were
            # never minted (models/task.py).
            "client_facing": bool(getattr(t, "atrium_task_id", None)),
            "client_note": t.client_facing_notes or "",
            "internal_notes": t.internal_notes or "",
            "description": t.description or "",
            "deliverable_url": t.deliverable_url or "",
            "campaign": t.campaign or "",
            "content_type": t.content_type or "",
            "comments": [
                {"id": str(c.id),
                 "sender": "client" if (c.client_author and not c.author_id) else "agora",
                 "sender_name": (c.client_author or "") if not c.author_id
                                else (getattr(users.get(c.author_id), "name", "") or ""),
                 "body": c.body or "",
                 # Sentinel counts a client's open change requests on the ROW
                 # (`client_changes_open`) rather than flagging the comment, so every mirrored
                 # comment is a plain comment and `open_changes` below carries the real number.
                 "kind": "comment", "resolved": False,
                 "at": _iso_dt(c.created_at)}
                for c in comments.get(t.id, [])
            ],
            # Oldest-first: the console's Activity list slices `history[-5:]` and reverses it.
            "history": [
                {"actor": email(h.changed_by_id), "field": h.field_changed or "",
                 "old": h.old_value or "", "new": h.new_value or "", "at": _iso_dt(h.changed_at)}
                for h in history.get(t.id, [])
            ],
            "reporter": "client" if t.id in requested else "agora",
            "reporter_name": requested.get(t.id, ""),
            # 🔴 Authoritative, because a mirrored comment carries no `kind` for Atrium's derived
            # count to find. `main._task_board` prefers this over re-deriving from the thread.
            "open_changes": getattr(t, "client_changes_open", 0) or 0,
            "review_state": getattr(t, "review_state", None) or "",
            # The projection's health, so the console can say "this client's copy is stale" instead
            # of showing a card that silently disagrees with what the client sees.
            "atrium_task_id": getattr(t, "atrium_task_id", "") or "",
            "atrium_sync_error": getattr(t, "atrium_sync_error", "") or "",
        })
    return out


__all__ = ["board"]

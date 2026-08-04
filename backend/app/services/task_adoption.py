"""Adopt Atrium-origin cards into linked Sentinel rows (WP 3.4, §4 of docs/TASKBOARD_REBUILD.md).

Cards that originated in Atrium — typed into the old console board, or filed by a client's
quick-add before D3 routed that to intake — have no Sentinel row. With the console board gone no
NEW ones appear, but the existing ones are stranded: the board renders them read-only over the
bridge, they cannot be assigned, reviewed, parked or counted.

🔴 Adoption is only safe BECAUSE of 4.3, not the other way round (the plan had this dependency
backwards). Every row created here carries `atrium_task_id`, and the board drops any Atrium card a
Sentinel row already claims — without that de-duplication each adopted card would render twice, and
the two copies would diverge the moment anybody moved one.

🔴 THIS IS THE ONE WORK PACKAGE THAT TOUCHES LIVE CLIENT DATA. Three rules follow from that, and
they are structural rather than advisory:

1. **PLAN AND APPLY ARE SEPARATE CALLS.** `plan()` performs no writes whatsoever and returns
   exactly what `apply()` would do, per card, with a reason for every skip. There is no
   "dry_run=False" flag on one function that somebody can pass by accident — applying is a
   different function with a different name and an explicit batch id.
2. **REVERSIBLE.** Every row created by a run carries the same `adoption_batch`, so `revert()` can
   remove precisely that run. Revert refuses any row that has been touched since it was adopted
   (a comment, a move, an assignment): once a human has worked on it, undoing the import would
   destroy real work, and the operator needs to hear that rather than have it silently skipped.
3. **PER CLIENT.** `client_key` is required. A single mistake should be one workspace's problem,
   not the estate's.

What adoption does NOT do: it never writes to Atrium. The Atrium card stays exactly as it is and
becomes the projection of the new Sentinel row, which is the target architecture (§4). So the
worst case of a bad run is orphaned Sentinel rows, which `revert()` removes — never damaged
client-visible data.
"""
from __future__ import annotations

import json
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Client, Task, User
from . import atrium_tasks, task_config

# Reasons a card is not adopted. Stable strings: the operator's report groups on them.
SKIP_LINKED = "Already adopted — a Sentinel row is linked to this card"
SKIP_NO_ID = "The card has no Atrium id"
SKIP_NO_STAGE = "Its status has no matching Sentinel column"


def _parse_date(raw) -> date | None:
    try:
        return date.fromisoformat(str(raw)[:10]) if raw else None
    except (TypeError, ValueError):
        return None


def _existing_links(db: Session, client_key: str) -> set[str]:
    """Atrium ids already claimed by a Sentinel row — for THIS workspace.

    🔴 Scoped by client, because `atrium_task_id` holds Atrium's RAW id and that is only unique
    within a workspace (the same trap the reverse channel hit). Comparing globally would report a
    card as "already adopted" because a DIFFERENT client happens to have a card with that id.
    """
    owner = db.execute(
        select(Client).where(Client.atrium_client_id == client_key)
    ).scalars().first()
    q = select(Task.atrium_task_id).where(Task.atrium_task_id.is_not(None))
    if owner:
        q = q.where(Task.client_id == owner.id)
    return {row for (row,) in db.execute(q).all() if row}


def claimed_atrium_ids(db: Session) -> set[tuple[str, str]]:
    """Every `(atrium client key, atrium task id)` a Sentinel row already owns.

    🔴 This is what stops the board rendering the SAME piece of work twice (WP 4.3). A Sentinel row
    linked to an Atrium card — whether the link was made by Send to Atrium (0.1/0.2) or by adoption
    (3.4) — means the card and the row are one thing. The row is the real one: it can be assigned,
    parked, reviewed and counted. But `atrium_tasks.fetch_tasks()` still lists that same card, so
    without this the board appends a second, read-only copy of it, and the pair diverges the instant
    anybody moves one of them.

    🔴 Keyed by `(client_key, id)`, never by the id alone — `atrium_task_id` holds Atrium's RAW id,
    which is unique only WITHIN a workspace (the trap §3.5 hit). A global comparison would hide one
    client's card because a different client happens to own a card with that id, and a card silently
    missing from the board is the worst failure this system has (AGENTS.md §5).

    A row whose client is not linked to a Sentinel `Client` is therefore unattributable and is NOT
    claimed here — it shows as a duplicate rather than risking hiding somebody else's work. `apply()`
    refuses to create such rows in the first place, which is the real fix.
    """
    keys = {c.id: c.atrium_client_id
            for c in db.execute(select(Client)).scalars().all() if c.atrium_client_id}
    rows = db.execute(
        select(Task.atrium_task_id, Task.client_id).where(Task.atrium_task_id.is_not(None))
    ).all()
    return {(keys[cid], tid) for tid, cid in rows if tid and cid in keys}


def plan(db: Session, client_key: str) -> dict:
    """What adoption WOULD do for one workspace. Performs no writes at all.

    Returns {client_key, client_linked, total, adopt: [...], skip: [{atrium_id, title, reason}]}.
    """
    if not client_key:
        raise ValueError("client_key is required — adoption is per client on purpose")

    owner = db.execute(
        select(Client).where(Client.atrium_client_id == client_key)
    ).scalars().first()
    cards = atrium_tasks.fetch_tasks(client_key)
    linked = _existing_links(db, client_key)
    statuses = task_config.statuses(db)

    adopt, skip = [], []
    for card in cards:
        atrium_id = str(card.get("task_id") or card.get("atrium_id") or "").strip()
        title = (card.get("title") or "Untitled").strip()
        if not atrium_id:
            skip.append({"atrium_id": "", "title": title, "reason": SKIP_NO_ID})
            continue
        if atrium_id in linked:
            skip.append({"atrium_id": atrium_id, "title": title, "reason": SKIP_LINKED})
            continue
        status = card.get("status") or ""
        if status not in statuses:
            # Better to report it than to silently file the card in the wrong column: the operator
            # can add or rename the status in Manage and re-run.
            skip.append({"atrium_id": atrium_id, "title": title,
                         "reason": f"{SKIP_NO_STAGE} ({status or 'no status'})"})
            continue
        adopt.append({
            "atrium_id": atrium_id,
            "title": title,
            "status": status,
            "priority": card.get("priority") or "Medium",
            "due_date": card.get("due_date") or None,
            "client_facing": bool(card.get("client_facing")),
        })

    return {
        "client_key": client_key,
        "client_linked": owner is not None,
        "client_name": owner.name if owner else None,
        "total": len(cards),
        "adopt": adopt,
        "skip": skip,
        "counts": {"adopt": len(adopt), "skip": len(skip)},
    }


def apply(db: Session, client_key: str, batch: str, actor: User) -> dict:
    """Create the linked Sentinel rows. A DIFFERENT function from `plan` on purpose.

    Every row is stamped with `batch` so `revert()` can undo exactly this run.

    🔴 Nothing is written to Atrium. The card keeps its content and becomes the projection of the
    new row (§4), so a bad run leaves orphaned Sentinel rows — removable — and never damaged
    client-visible data.
    """
    if not batch:
        raise ValueError("a batch id is required — it is what makes the run reversible")
    todo = plan(db, client_key)
    # 🔴 REFUSE AN UNLINKED WORKSPACE (added with WP 4.3). Rows created for a workspace with no
    # Sentinel `Client` carry `client_id = NULL`, so `claimed_atrium_ids` cannot attribute them and
    # the board's de-duplication cannot see them — every adopted card would then render TWICE, and
    # the two copies diverge the moment anybody moves one. De-duplicating on the bare id instead
    # would be worse: that id is unique only within a workspace, so it would HIDE another client's
    # card. Linking the workspace first is a one-field fix; this is refusing to create a mess that
    # has no good cleanup.
    if not todo["client_linked"]:
        raise ValueError(
            f"“{client_key}” is not linked to a Sentinel client — set that client's "
            "atrium_client_id first, or its adopted cards will appear twice on the board")
    owner = db.execute(
        select(Client).where(Client.atrium_client_id == client_key)).scalars().first()
    owner_id = owner.id if owner else None

    created = []
    for item in todo["adopt"]:
        task = Task(
            title=item["title"][:200],
            client_id=owner_id,
            status=item["status"],
            priority=item["priority"],
            due_date=_parse_date(item["due_date"]),
            created_by_id=actor.id,
            account_manager_id=actor.id,
            # It already exists in Atrium, so it is published by definition — that link is the
            # whole point of adopting it.
            atrium_task_id=item["atrium_id"],
            atrium_visible=True,
            adoption_batch=batch,
            labels_json=json.dumps([]),
        )
        db.add(task)
        db.flush()
        created.append({"task_id": task.id, "atrium_id": item["atrium_id"],
                        "title": task.title})
    db.commit()
    return {**todo, "batch": batch, "created": created,
            "counts": {**todo["counts"], "created": len(created)}}


def revert(db: Session, batch: str) -> dict:
    """Remove the rows a run created. Refuses any that have been worked on since.

    "Worked on" means a comment, a history entry beyond the adoption stamp, an assignee, or a
    status that has moved. Undoing those would destroy real work, so they are reported as
    `kept` with a reason — the operator hears about them instead of losing them.
    """
    if not batch:
        raise ValueError("a batch id is required")
    rows = db.execute(select(Task).where(Task.adoption_batch == batch)).scalars().all()
    removed, kept = [], []
    for task in rows:
        touched = []
        if task.comments:
            touched.append("has comments")
        if task.assigned_to_id or task.assigned_team_id:
            touched.append("has been assigned")
        if len(task.history) > 0:
            touched.append("has history")
        if task.completed_at or task.archived:
            touched.append("has been completed or filed")
        if touched:
            kept.append({"task_id": task.id, "title": task.title, "reason": ", ".join(touched)})
            continue
        removed.append({"task_id": task.id, "title": task.title})
        db.delete(task)
    db.commit()
    return {"batch": batch, "removed": removed, "kept": kept,
            "counts": {"removed": len(removed), "kept": len(kept)}}

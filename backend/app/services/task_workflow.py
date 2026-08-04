"""Task lifecycle: the completion stamp, filing, park/resume, and the review gate.

These are the Stage 2 fields of docs/TASKBOARD_REBUILD.md (M2–M5). They are here rather than in
`routers/tasks.py` because every one of them is a RULE, not a field write, and three of the rules
have to hold no matter which route moved the card:

* **`completed_at` is stamped by the transition, never typed.** Throughput used to be counted off
  `updated_at`, so editing a finished task re-dated its completion (§2.4h).
* **A hold only exists in the blocked stage.** Drag a parked card back onto the board and it is no
  longer on hold — otherwise "On hold" quietly outlives the pause and lies on the card forever.
* **Approval is consumed by completion.** A task that leaves a done column loses its approval and
  must be re-approved, so `approved` always refers to the work as it stands.

🔴 Nothing here compares a status to a LABEL. "Is this done?" is `task_config.is_completed`, which
answers by STAGE — renaming Completed, or adding a second done column, must not change behaviour
(AGENTS.md §5, decision D13).
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..constants import (
    NOTIF_TASK_ASSIGNED,
    NOTIF_TASK_REVIEW,
    REVIEW_APPROVED,
    REVIEW_CHANGES,
    REVIEW_PENDING,
)
from ..models import Task, TaskHistory, User
from ..utils.time import utcnow
from . import notifications as notif
from . import task_config

# The message the review gate refuses with. One string, because the frontend surfaces it verbatim
# and the tests pin it.
NEEDS_REVIEW = ("This task needs a team lead's approval before it can be completed. "
                "Submit it for review, or ask your lead to approve it.")


def _log(db: Session, task: Task, actor_id: int | None, field: str, old, new) -> None:
    db.add(TaskHistory(
        task_id=task.id, changed_by_id=actor_id, field_changed=field,
        old_value=None if old is None else str(old),
        new_value=None if new is None else str(new),
    ))


def _link(task: Task) -> str:
    """Where a notification about this task points. `/tasks`, the board's own page since 2026-08-03
    (decision D7) — `main.dashboard_page` still forwards the `/dashboard?open=` rows minted while the
    board was embedded there, so old and new notifications both land on the card."""
    return f"/tasks?open={task.id}"


def _status_for(db: Session, stage: str) -> str:
    return task_config.status_for_stage(db, stage)


# --- the completion gate ------------------------------------------------------------------------

def review_blocks(db: Session, task: Task, new_status: str) -> bool:
    """Is this move into a done column blocked for want of an approval? (M2, decision D5.)

    The ONE enforced gate on this board — everything else is surfaced, not enforced (§2.2.2). A
    card with six open steps still drops into Completed; a card nobody approved does not, because
    "Done" is the claim the rest of the company reads off this board.
    """
    if not task_config.is_completed(db, new_status):
        return False
    if task_config.is_completed(db, task.status):
        return False                      # already done — this is a rename/no-op, not a completion
    return task.review_state != REVIEW_APPROVED


def on_status_change(db: Session, task: Task, old: str, new: str, actor: User) -> None:
    """Everything that must follow a status move. Call it AFTER setting `task.status`.

    Deliberately idempotent-ish and total: it looks at where the card now is, not at how it got
    there, so a drag, a park, a resume and an API PATCH all leave the row in the same shape.
    """
    stage = task_config.stage_for(db, new)
    done = task_config.is_completed(db, new)
    # 🔴 LEAVING a done column is the event, not "being somewhere that isn't done". An approval is
    # spent by the completion it authorised — but a plain In Progress → To Do move authorises
    # nothing and must keep it, or a lead's approval evaporates the next time anyone drags the card.
    was_done = task_config.is_completed(db, old)

    if done:
        if not task.completed_at:
            task.completed_at = utcnow()
    elif was_done:
        if task.completed_at:
            task.completed_at = None
            _log(db, task, actor.id, "completed_at", "set", None)
        # Reopening un-files the card: it is live work again, so it belongs on the board rather
        # than in Past work (where nobody would look for it).
        if task.archived:
            task.archived = False
            _log(db, task, actor.id, "archived", "filed", "reopened")
        # An approval is spent by the completion it authorised. Moving the work on means the next
        # completion is a new claim about new work, and needs its own approval.
        if task.review_state == REVIEW_APPROVED:
            task.review_state = None
            task.reviewer_id = None
            _log(db, task, actor.id, "review_state", REVIEW_APPROVED, None)

    # A hold is a property of the blocked stage. Moving anywhere else ends it — including a drag,
    # which is how most people will resume work in practice.
    if task.on_hold and stage != "blocked":
        task.on_hold = False
        task.hold_reason = None
        task.resume_to = None
        _log(db, task, actor.id, "on_hold", "on hold", "resumed")


# --- park / resume (M3) -------------------------------------------------------------------------

def park(db: Session, task: Task, actor: User, reason: str = "") -> tuple[str, str]:
    """Pause the task in the blocked column, remembering where it came from. (status, error).

    `hold_reason` is INTERNAL. A park reason is usually about money, legal or a client who has gone
    quiet — Atrium's own card carries such a field, but we deliberately never push ours (the client
    sees the stage, never the reason). See `task_bridge.SAFE`.
    """
    target = _status_for(db, "blocked")
    if not target:
        return "", ("There is no blocked column on this board, so there is nowhere to park work. "
                    "Add a status with the Blocked client stage first.")
    # Parking something already parked just updates the reason — never overwrite the remembered
    # column with the blocked one, or Resume would put the card straight back on hold.
    if not task.on_hold:
        # A card parked FROM the blocked stage has no meaningful column to return to, so it resumes
        # at the front of the queue rather than back into the pause it never left.
        task.resume_to = task.status if task.status != target else (_status_for(db, "todo") or None)
    old = task.status
    task.on_hold = True
    task.hold_reason = (reason or "").strip() or None
    task.status = target
    if old != target:
        _log(db, task, actor.id, "status", old, target)
    _log(db, task, actor.id, "on_hold", None, task.hold_reason or "parked")
    on_status_change(db, task, old, target, actor)
    return target, ""


def resume(db: Session, task: Task, actor: User) -> tuple[str, str]:
    """Put a parked task back in the column it left. (status, error)."""
    if not task.on_hold:
        return "", "That task isn't on hold."
    target = task.resume_to
    if not target or target not in task_config.statuses(db):
        # The remembered column was renamed or retired while the card sat parked. Rather than
        # guessing, resume at the front of the queue — visible, and obviously needing triage.
        target = _status_for(db, "todo") or task_config.statuses(db)[0]
    old = task.status
    task.status = target
    if old != target:
        _log(db, task, actor.id, "status", old, target)
    on_status_change(db, task, old, target, actor)      # this is what clears the hold fields
    return target, ""


# --- filing / Past work (M4) --------------------------------------------------------------------

def archive(db: Session, task: Task, actor: User) -> str:
    """File a finished task into Past work. Returns an error message, or ''.

    Only a completed task may be filed: archiving live work would hide it from the board with no
    trace, which is the failure mode the retired-status bug already taught this board once
    (AGENTS.md §5). Unfinished work that has to leave the board gets PARKED instead.
    """
    if not task_config.is_completed(db, task.status):
        return ("Only completed work can be filed into Past work. Park it instead if it needs to "
                "leave the board unfinished.")
    if task.archived:
        return ""
    task.archived = True
    if not task.completed_at:
        task.completed_at = utcnow()      # a row completed before the column existed
    _log(db, task, actor.id, "archived", None, "filed to Past work")
    return ""


def unarchive(db: Session, task: Task, actor: User) -> None:
    """Pull a filed task back onto the board. Its status (and so its column) is untouched."""
    if not task.archived:
        return
    task.archived = False
    _log(db, task, actor.id, "archived", "filed to Past work", "back on the board")


# --- review (M2, decision D5) -------------------------------------------------------------------

def submit_review(db: Session, task: Task, actor: User) -> str:
    """Ask for approval. Returns an error message, or ''."""
    if task.review_state == REVIEW_PENDING:
        return ""                          # already waiting — asking twice is not an error
    old = task.review_state
    task.review_state = REVIEW_PENDING
    task.reviewer_id = None                # the decision stamps the reviewer, not the request
    _log(db, task, actor.id, "review_state", old, REVIEW_PENDING)
    # 🔴 Leads are found by QUERY, not by a `Team.lead_id` column (decision D9). notify_managers
    # fans out to admins plus every team_lead whose team matches — which is why zero leads and
    # three leads both work and no primary lead has to be invented.
    notif.notify_managers(
        db, type=NOTIF_TASK_REVIEW, title=f"Review requested: {task.title}",
        body=f"{actor.name or 'A teammate'} submitted this for approval.",
        link=_link(task), team_id=task.assigned_team_id, commit=False,
    )
    return ""


def approve(db: Session, task: Task, actor: User) -> str:
    """Approve the work, unblocking completion. Returns an error message, or ''."""
    if task.review_state == REVIEW_APPROVED:
        return ""
    old = task.review_state
    task.review_state = REVIEW_APPROVED
    task.reviewer_id = actor.id
    _log(db, task, actor.id, "review_state", old, REVIEW_APPROVED)
    _notify_owner(db, task, actor, f"Approved: {task.title}",
                  f"{actor.name or 'Your lead'} approved this — it can be completed now.")
    return ""


def request_changes(db: Session, task: Task, actor: User, note: str = "") -> tuple[str, str]:
    """Send the work back with a note. Returns (new_status, error).

    Moves the card to the revision column when the board has one, because "changes requested" that
    leaves the card sitting in In Progress is a state only the drawer can see.
    """
    old_state = task.review_state
    task.review_state = REVIEW_CHANGES
    task.reviewer_id = actor.id
    note = (note or "").strip()
    _log(db, task, actor.id, "review_state", old_state, REVIEW_CHANGES + (f": {note}" if note else ""))
    moved = ""
    target = _status_for(db, "revision")
    if target and task.status != target:
        old = task.status
        task.status = target
        _log(db, task, actor.id, "status", old, target)
        on_status_change(db, task, old, target, actor)
        moved = target
    _notify_owner(db, task, actor, f"Changes requested: {task.title}",
                  note or f"{actor.name or 'Your lead'} asked for changes.")
    return moved, ""


def _notify_owner(db: Session, task: Task, actor: User, title: str, body: str) -> None:
    """Tell whoever holds the work. Silent when nobody does — a review decision on an unassigned
    card has no addressee, and notifying the whole team about it would be noise."""
    if task.assigned_to_id and task.assigned_to_id != actor.id:
        notif.notify(db, user_id=task.assigned_to_id, type=NOTIF_TASK_ASSIGNED,
                     title=title, body=body, link=_link(task), commit=False)


__all__ = [
    "NEEDS_REVIEW", "review_blocks", "on_status_change", "park", "resume", "archive",
    "unarchive", "submit_review", "approve", "request_changes",
]

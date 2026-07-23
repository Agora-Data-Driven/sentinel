"""Task Board: listing, CRUD, status moves (logged), comments, attachments, priority.

Authorization lives in one place — ``app/services/task_perms.py`` — not inline here. Board
vocabulary (statuses / priorities) is read from ``task_config`` (DB-backed, editable in Manage),
not from the enum constants.
"""
from __future__ import annotations

import json
from datetime import timedelta

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..events import broker

from ..constants import (
    NOTIF_TASK_ASSIGNED,
    NOTIF_TASK_REVIEW,
    ROLE_TEAM_LEAD,
    TASK_COMPLETED,
    TASK_FOR_REVIEW,
)
from ..database import get_db
from ..models import AtriumApproval, Task, TaskComment, TaskHistory, User
from ..schemas import (
    CommentIn,
    TaskCreateIn,
    TaskPriorityIn,
    TaskStatusIn,
    TaskUpdateIn,
)
from ..security import get_current_user, is_manager, require_roles
from ..serializers import atrium_payload, comment_dict, task_card, task_detail, user_public
from ..services import audit
from ..services import maintasks as maintasks_svc
from ..services import notifications as notif
from ..services import task_config, task_perms, task_templates
from ..utils.time import today_ph, to_ph, utcnow

router = APIRouter(prefix="/api/tasks", tags=["tasks"])

AM_PLUS = ("account_manager", "admin", "super_admin")
_NOT_FOUND = "Task not found"
_FORBIDDEN = "Not permitted"


def _log(db: Session, task_id: int, actor_id: int, field: str, old, new) -> None:
    db.add(
        TaskHistory(
            task_id=task_id, changed_by_id=actor_id, field_changed=field,
            old_value=None if old is None else str(old),
            new_value=None if new is None else str(new),
        )
    )


def _broadcast(action: str, task: Task, actor_id: int) -> None:
    """Notify live boards that a task changed (SSE). Best-effort; never fails the request."""
    broker.publish({
        "type": "task", "action": action, "task_id": task.id,
        "status": task.status, "actor_id": actor_id,
    })


@router.get("")
def list_tasks(
    client_id: int | None = Query(None),
    team_id: int | None = Query(None),
    assignee_id: int | None = Query(None),
    status: str | None = Query(None),
    priority: str | None = Query(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = select(Task).order_by(Task.updated_at.desc())
    if client_id:
        q = q.where(Task.client_id == client_id)
    if team_id:
        q = q.where(Task.assigned_team_id == team_id)
    if assignee_id:
        q = q.where(Task.assigned_to_id == assignee_id)
    if status:
        q = q.where(Task.status == status)
    if priority:
        q = q.where(Task.priority == priority)
    tasks = [t for t in db.execute(q).scalars().all() if task_perms.can_view(user, t)]
    return [task_card(t, db) for t in tasks]


def _aggregate(pts: list[Task], today, week_start, all_statuses) -> dict:
    """Roll a single person's tasks into the Monitor row's counts."""
    counts = dict.fromkeys(all_statuses, 0)
    overdue = completed_week = 0
    for t in pts:
        counts[t.status] = counts.get(t.status, 0) + 1
        if t.status == TASK_COMPLETED:
            if t.updated_at and to_ph(t.updated_at).date() >= week_start:
                completed_week += 1
        elif t.due_date and t.due_date < today:
            overdue += 1
    open_total = sum(n for st, n in counts.items() if st != TASK_COMPLETED)
    return {"counts": counts, "overdue": overdue, "open_total": open_total,
            "completed_week": completed_week, "total": len(pts)}


@router.get("/summary")
def employee_summary(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Per-employee task rollup for the Monitor view (managers only).

    Scope mirrors the board's `_can_view`: admins / super-admin / account managers see everyone;
    a team lead sees only their own team. Employees / interns get a 403 — monitoring is a
    management surface. Declared BEFORE `/{task_id}` so "summary" isn't parsed as a task id.
    """
    if not is_manager(user):
        raise HTTPException(status_code=403, detail="Only managers can monitor the team")

    # Who this manager may see: all active staff, or (team lead) just their own team.
    people = db.execute(select(User).where(User.is_active.is_(True))).scalars().all()
    if user.role == ROLE_TEAM_LEAD:
        people = [p for p in people if p.team_id == user.team_id]
    people = sorted(people, key=lambda p: (p.name or "").lower())

    tasks = db.execute(select(Task)).scalars().all()
    by_assignee: dict[int, list[Task]] = {}
    for t in tasks:
        if t.assigned_to_id is not None:
            by_assignee.setdefault(t.assigned_to_id, []).append(t)

    today = today_ph()
    week_start = today - timedelta(days=7)
    all_statuses = task_config.statuses(db)
    rows = [{"user": user_public(p), **_aggregate(by_assignee.get(p.id, []), today, week_start, all_statuses)}
            for p in people]
    # Heaviest / most-behind first is what a manager wants to see.
    rows.sort(key=lambda r: (r["overdue"], r["open_total"]), reverse=True)
    return rows


@router.get("/templates")
def list_templates(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Service-template catalog for the New Task picker (DB-backed). Declared before /{task_id}."""
    return task_templates.catalog(db)


@router.get("/{task_id}")
def get_task(task_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    if not task_perms.can_view(user, task):
        raise HTTPException(status_code=403, detail=_FORBIDDEN)
    return task_detail(task, db)


@router.post("")
def create_task(payload: TaskCreateIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # Any staff member can create a task (Sentinel is an internal, employee-facing tool).
    if payload.status not in task_config.statuses(db):
        raise HTTPException(status_code=400, detail="Invalid status")
    is_am = user.role == "account_manager"
    may_delegate = user.role in task_perms.FULL or user.role == ROLE_TEAM_LEAD
    # Employees may only assign a task they create to themselves; delegation is a lead/manager action.
    assigned_to_id = payload.assigned_to_id
    if not may_delegate and assigned_to_id not in (None, user.id):
        assigned_to_id = user.id
    # Priority is honored from a manager (AM/admin/super) or a team lead; others default to Medium.
    priority = payload.priority if may_delegate and payload.priority in task_config.priorities(db) else "Medium"
    # Service template: seed the two-level breakdown (+ content type) from the picked recipe unless
    # the caller supplied their own. A seed, not a lock — the breakdown is editable afterwards.
    tpl = task_templates.get(db, payload.service_key) if payload.service_key else None
    maintasks = maintasks_svc.normalize(payload.maintasks or [], json.dumps([c.model_dump() for c in payload.checklist]))
    if tpl and not maintasks:
        maintasks = task_templates.maintasks_for(db, payload.service_key)
    content_type = payload.content_type or (tpl.content_type if tpl else None)
    # Template defaults fill fields the caller left blank (a seed, not a lock). Priority follows the
    # same role gate as a manually chosen one; labels/description only apply when none were supplied.
    if tpl and may_delegate and priority == "Medium" and tpl.default_priority in task_config.priorities(db):
        priority = tpl.default_priority
    labels = payload.labels
    if tpl and not labels:
        try:
            labels = json.loads(tpl.default_labels_json or "[]")
        except (ValueError, TypeError):
            labels = []
    description = payload.description or (tpl.default_description if tpl else None)
    task = Task(
        title=payload.title,
        description=description,
        client_id=payload.client_id,
        campaign=payload.campaign,
        content_type=content_type,
        account_manager_id=user.id if is_am else None,
        assigned_team_id=payload.assigned_team_id,
        assigned_to_id=assigned_to_id,
        priority=priority,
        status=payload.status,
        due_date=payload.due_date,
        labels_json=json.dumps(labels),
        maintasks_json=maintasks_svc.dumps(maintasks),  # legacy checklist_json no longer written
        deliverable_url=payload.deliverable_url,
        internal_notes=payload.internal_notes,
        client_facing_notes=payload.client_facing_notes,
    )
    db.add(task)
    db.flush()
    _log(db, task.id, user.id, "created", None, task.status)
    db.commit()
    audit.record(db, actor_id=user.id, table_name="tasks", record_id=task.id, action="create",
                 new={"title": task.title, "status": task.status})
    if task.assigned_to_id:
        notif.notify(db, user_id=task.assigned_to_id, type=NOTIF_TASK_ASSIGNED,
                     title=f"New task assigned: {task.title}", link=f"/tasks?open={task.id}")
    _broadcast("created", task, user.id)
    return task_detail(task, db)


@router.patch("/{task_id}")
def update_task(task_id: int, payload: TaskUpdateIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    if not task_perms.can_edit(user, task):
        raise HTTPException(status_code=403, detail=_FORBIDDEN)

    data = payload.model_dump(exclude_unset=True)
    # Field-level guards — everything else (title, dates, breakdown, notes) is free to whoever can edit:
    #  • atrium_visible (client bridge) -> managers only, mirrors /send-to-atrium
    #  • reassigning to someone else    -> team lead+ (delegation), employees can't reassign
    #  • priority                       -> can_prioritize, and must be a configured value
    if data.get("atrium_visible") and not task_perms.can_bridge(user):
        raise HTTPException(status_code=403, detail="Only managers can share a task to Atrium")
    for fld in ("assigned_to_id", "assigned_team_id"):
        if fld in data and data[fld] != getattr(task, fld) and not task_perms.can_reassign(user, task):
            raise HTTPException(status_code=403, detail="Only a team lead or manager can reassign a task")
    if "priority" in data and not (task_perms.can_prioritize(user, task) and data["priority"] in task_config.priorities(db)):
        data.pop("priority")

    prev_assignee = task.assigned_to_id
    for field, value in data.items():
        if field == "labels":
            task.labels_json = json.dumps(value or [])
        elif field == "checklist":
            continue  # legacy flat list is no longer written; the breakdown lives in maintasks
        elif field == "maintasks":
            # Normalize on write so ids/types are always clean regardless of what the client sent.
            task.maintasks_json = maintasks_svc.dumps(maintasks_svc.normalize(value or []))
        else:
            old = getattr(task, field)
            if old != value:
                _log(db, task.id, user.id, field, old, value)
            setattr(task, field, value)
    db.commit()
    if task.assigned_to_id and task.assigned_to_id != prev_assignee:
        notif.notify(db, user_id=task.assigned_to_id, type=NOTIF_TASK_ASSIGNED,
                     title=f"Task assigned to you: {task.title}", link=f"/tasks?open={task.id}")
    _broadcast("updated", task, user.id)
    return task_detail(task, db)


@router.delete("/{task_id}")
def delete_task(task_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Delete a task and everything hanging off it. Team lead (own team) + AM / admin / super_admin."""
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    if not task_perms.can_delete(user, task):
        raise HTTPException(status_code=403, detail=_FORBIDDEN)
    title = task.title
    _broadcast("deleted", task, user.id)  # while the row is still valid
    # comments + history cascade via the relationship; Atrium approvals have no cascade, so clear them.
    db.query(AtriumApproval).filter(AtriumApproval.task_id == task_id).delete()
    db.delete(task)
    db.commit()
    audit.record(db, actor_id=user.id, table_name="tasks", record_id=task_id, action="delete",
                 old={"title": title})
    return {"ok": True}


@router.patch("/{task_id}/status")
def move_status(task_id: int, payload: TaskStatusIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    if payload.status not in task_config.statuses(db):
        raise HTTPException(status_code=400, detail="Invalid status")
    if not task_perms.can_move(user, task):
        raise HTTPException(status_code=403, detail=_FORBIDDEN)
    old = task.status
    if old == payload.status:
        return task_detail(task, db)
    task.status = payload.status
    _log(db, task.id, user.id, "status", old, payload.status)
    db.commit()
    audit.record(db, actor_id=user.id, table_name="tasks", record_id=task.id, action="move",
                 old={"status": old}, new={"status": payload.status})
    # Moving into review pings the AM / admins.
    if payload.status == TASK_FOR_REVIEW and task.account_manager_id:
        notif.notify(db, user_id=task.account_manager_id, type=NOTIF_TASK_REVIEW,
                     title=f"Task ready for review: {task.title}", link=f"/tasks?open={task.id}")
    _broadcast("moved", task, user.id)
    return task_detail(task, db)


@router.patch("/{task_id}/priority")
def set_priority(task_id: int, payload: TaskPriorityIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    # Priority is a management decision: team lead (own team) + AM / admin / super_admin.
    if not task_perms.can_prioritize(user, task):
        raise HTTPException(status_code=403, detail="Only a team lead or manager can set task priority")
    if payload.priority not in task_config.priorities(db):
        raise HTTPException(status_code=400, detail="Invalid priority")
    old = task.priority
    task.priority = payload.priority
    _log(db, task.id, user.id, "priority", old, payload.priority)
    db.commit()
    audit.record(db, actor_id=user.id, table_name="tasks", record_id=task.id, action="priority",
                 old={"priority": old}, new={"priority": payload.priority})
    _broadcast("priority", task, user.id)
    return task_detail(task, db)


@router.post("/{task_id}/comments")
def add_comment(task_id: int, payload: CommentIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    if not task_perms.can_view(user, task):
        raise HTTPException(status_code=403, detail=_FORBIDDEN)
    c = TaskComment(
        task_id=task.id, author_id=user.id, body=payload.body,
        attachments_json=json.dumps(payload.attachments or []),
    )
    db.add(c)
    db.commit()
    _broadcast("comment", task, user.id)  # live boards refresh the comment count
    return comment_dict(c, db)


@router.post("/{task_id}/attachments")
async def add_attachment(task_id: int, file: UploadFile = File(...), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    if not task_perms.can_view(user, task):
        raise HTTPException(status_code=403, detail=_FORBIDDEN)
    content = await file.read()
    # MVP: record metadata as a comment attachment (no blob store wired). Size only, not the bytes.
    meta = {"name": file.filename, "size": len(content), "content_type": file.content_type}
    c = TaskComment(
        task_id=task.id, author_id=user.id, body=f"📎 Attached {file.filename}",
        attachments_json=json.dumps([meta]),
    )
    db.add(c)
    db.commit()
    return comment_dict(c, db)


@router.post("/{task_id}/send-to-atrium", dependencies=[Depends(require_roles(*AM_PLUS))])
def send_to_atrium(task_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Bridge to Atrium: mark visible + record an approval. Only client-facing fields cross over."""
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    task.atrium_visible = True
    approval = AtriumApproval(task_id=task.id, sent_at=utcnow())
    db.add(approval)
    _log(db, task.id, user.id, "atrium", "internal", "sent_to_atrium")
    db.commit()
    audit.record(db, actor_id=user.id, table_name="atrium_approvals", record_id=approval.id,
                 action="send", new=atrium_payload(task, db))
    return {"ok": True, "atrium_payload": atrium_payload(task, db)}

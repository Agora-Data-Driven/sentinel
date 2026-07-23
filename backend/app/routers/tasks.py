"""Task Board: role-filtered listing, CRUD, status moves (logged), comments, attachments, priority.

Priority rule (hard): ONLY the Account Manager may set/change priority. Every other role gets 403
from PATCH /api/tasks/{id}/priority, and priority is ignored on create unless the actor is an AM.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..events import broker

from ..constants import (
    ADMIN_ROLES,
    NOTIF_TASK_ASSIGNED,
    NOTIF_TASK_REVIEW,
    PRIORITIES,
    ROLE_ACCOUNT_MANAGER,
    ROLE_EMPLOYEE,
    ROLE_INTERN,
    ROLE_TEAM_LEAD,
    TASK_FOR_REVIEW,
    TASK_STATUSES,
)
from ..database import get_db
from ..models import AtriumApproval, Client, Task, TaskComment, TaskHistory, Team, User
from ..schemas import (
    CommentIn,
    TaskCreateIn,
    TaskPriorityIn,
    TaskStatusIn,
    TaskUpdateIn,
)
from ..security import get_current_user, is_account_manager, require_roles
from ..serializers import atrium_payload, comment_dict, task_card, task_detail
from ..services import audit
from ..services import notifications as notif
from ..utils.time import utcnow

router = APIRouter(prefix="/api/tasks", tags=["tasks"])

AM_PLUS = ("account_manager", "admin", "super_admin")


def _can_view(user: User, task: Task) -> bool:
    if user.role in ADMIN_ROLES or user.role == ROLE_ACCOUNT_MANAGER:
        return True
    if user.role == ROLE_TEAM_LEAD:
        return task.assigned_team_id == user.team_id or task.assigned_to_id == user.id
    return task.assigned_to_id == user.id  # employees / interns: own tasks only


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
    tasks = [t for t in db.execute(q).scalars().all() if _can_view(user, t)]
    return [task_card(t, db) for t in tasks]


@router.get("/{task_id}")
def get_task(task_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if not _can_view(user, task):
        raise HTTPException(status_code=403, detail="Not permitted to view this task")
    return task_detail(task, db)


@router.post("", dependencies=[Depends(require_roles(*AM_PLUS))])
def create_task(payload: TaskCreateIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if payload.status not in TASK_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid status")
    # Priority only honored from an AM; others default to Medium regardless of what they send.
    priority = payload.priority if is_account_manager(user) and payload.priority in PRIORITIES else "Medium"
    task = Task(
        title=payload.title,
        description=payload.description,
        client_id=payload.client_id,
        campaign=payload.campaign,
        content_type=payload.content_type,
        account_manager_id=user.id if is_account_manager(user) else None,
        assigned_team_id=payload.assigned_team_id,
        assigned_to_id=payload.assigned_to_id,
        priority=priority,
        status=payload.status,
        due_date=payload.due_date,
        labels_json=json.dumps(payload.labels),
        checklist_json=json.dumps([c.model_dump() for c in payload.checklist]),
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
        raise HTTPException(status_code=404, detail="Task not found")
    if not _can_view(user, task):
        raise HTTPException(status_code=403, detail="Not permitted")

    data = payload.model_dump(exclude_unset=True)
    prev_assignee = task.assigned_to_id
    for field, value in data.items():
        if field == "labels":
            task.labels_json = json.dumps(value or [])
        elif field == "checklist":
            task.checklist_json = json.dumps([c if isinstance(c, dict) else c.model_dump() for c in (value or [])])
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


@router.patch("/{task_id}/status")
def move_status(task_id: int, payload: TaskStatusIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if payload.status not in TASK_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid status")
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    # Manager/AM can move any (their scope); assignee can move their own card.
    allowed = user.role in AM_PLUS or user.role == ROLE_TEAM_LEAD or task.assigned_to_id == user.id
    if not allowed or not _can_view(user, task):
        raise HTTPException(status_code=403, detail="Not permitted to move this task")
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
    # HARD RULE: only the Account Manager role may change priority.
    if user.role != ROLE_ACCOUNT_MANAGER:
        raise HTTPException(status_code=403, detail="Only the Account Manager can set task priority")
    if payload.priority not in PRIORITIES:
        raise HTTPException(status_code=400, detail="Invalid priority")
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
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
        raise HTTPException(status_code=404, detail="Task not found")
    if not _can_view(user, task):
        raise HTTPException(status_code=403, detail="Not permitted")
    c = TaskComment(
        task_id=task.id, author_id=user.id, body=payload.body,
        attachments_json=json.dumps(payload.attachments or []),
    )
    db.add(c)
    db.commit()
    return comment_dict(c, db)


@router.post("/{task_id}/attachments")
async def add_attachment(task_id: int, file: UploadFile = File(...), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if not _can_view(user, task):
        raise HTTPException(status_code=403, detail="Not permitted")
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
        raise HTTPException(status_code=404, detail="Task not found")
    task.atrium_visible = True
    approval = AtriumApproval(task_id=task.id, sent_at=utcnow())
    db.add(approval)
    _log(db, task.id, user.id, "atrium", "internal", "sent_to_atrium")
    db.commit()
    audit.record(db, actor_id=user.id, table_name="atrium_approvals", record_id=approval.id,
                 action="send", new=atrium_payload(task, db))
    return {"ok": True, "atrium_payload": atrium_payload(task, db)}

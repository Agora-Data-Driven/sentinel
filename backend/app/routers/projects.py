"""PROJECTS — the thin project layer's API (2026-09-02). Thin; the rollups are `services/projects`.

    GET    /api/projects                     every project + its rollup           [projects.view]
    POST   /api/projects                     create (milestones may ride along)   [projects.manage]
    GET    /api/projects/{id}                one project in depth                 [projects.view]
    PATCH  /api/projects/{id}                name / goal / owner / date / status  [projects.manage]
    DELETE /api/projects/{id}                delete; linked tasks are UNLINKED, never deleted
    POST   /api/projects/{id}/milestones     add a milestone                      [projects.manage]
    PATCH  /api/projects/milestones/{id}     edit / tick a milestone              [projects.manage]
    DELETE /api/projects/milestones/{id}     remove a milestone                   [projects.manage]
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import update
from sqlalchemy.orm import Session

from ..capabilities import CAP_PROJECTS_MANAGE, CAP_PROJECTS_VIEW
from ..database import get_db
from ..models import Project, ProjectMilestone, Task, User
from ..schemas import MilestoneIn, MilestoneUpdateIn, ProjectIn, ProjectUpdateIn
from ..security import get_current_user, require_cap
from ..services import audit
from ..services import projects as projects_svc
from ..utils.time import utcnow

router = APIRouter(prefix="/api/projects", tags=["projects"])


def _project_or_404(db: Session, project_id: int) -> Project:
    p = db.get(Project, project_id)
    if not p:
        raise HTTPException(status_code=404, detail="Project not found")
    return p


@router.get("", dependencies=[Depends(require_cap(CAP_PROJECTS_VIEW))])
def list_projects(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return {"projects": projects_svc.list_projects(db), "rule": projects_svc.HEALTH_RULE}


@router.post("", dependencies=[Depends(require_cap(CAP_PROJECTS_MANAGE))])
def create_project(payload: ProjectIn, user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="A project needs a name.")
    if payload.owner_id is not None:
        owner = db.get(User, payload.owner_id)
        if not owner or not owner.is_active:
            raise HTTPException(status_code=400, detail="That owner isn't an active staff member.")
    p = Project(name=name[:160], goal=(payload.goal or "").strip() or None,
                owner_id=payload.owner_id, target_date=payload.target_date)
    db.add(p)
    db.flush()
    for i, m in enumerate(payload.milestones):
        if m.title.strip():
            db.add(ProjectMilestone(project_id=p.id, title=m.title.strip()[:200],
                                    detail=(m.detail or "").strip() or None,
                                    target_date=m.target_date, position=i))
    db.commit()
    db.refresh(p)
    audit.record(db, actor_id=user.id, table_name="projects", record_id=p.id, action="create",
                 new={"name": p.name, "target_date": str(p.target_date) if p.target_date else None})
    return projects_svc.overview(db, p, user)


# 🔴 The milestone routes are declared ABOVE `/{project_id}` on purpose — the same registration-order
# lesson as gym's `/routines` (AGENTS.md §5): declared below, the int-typed `{project_id}` path
# would swallow `/milestones/...` into a failed int parse and answer 422.

@router.patch("/milestones/{milestone_id}", dependencies=[Depends(require_cap(CAP_PROJECTS_MANAGE))])
def update_milestone(milestone_id: int, payload: MilestoneUpdateIn,
                     user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    m = db.get(ProjectMilestone, milestone_id)
    if not m:
        raise HTTPException(status_code=404, detail="Milestone not found")
    data = payload.model_dump(exclude_unset=True)
    if "title" in data and str(data["title"] or "").strip():
        m.title = str(data["title"]).strip()[:200]
    if "detail" in data:
        m.detail = (data["detail"] or "").strip() or None
    if "target_date" in data:
        m.target_date = data["target_date"]
    if "position" in data and data["position"] is not None:
        m.position = int(data["position"])
    if "done" in data and bool(data["done"]) != bool(m.done):
        # The TRANSITION stamps; the stamp is never typed (same rule as tasks.completed_at).
        m.done = bool(data["done"])
        m.done_at = utcnow() if m.done else None
        m.done_by_id = user.id if m.done else None
        audit.record(db, actor_id=user.id, table_name="project_milestones", record_id=m.id,
                     action="milestone_done" if m.done else "milestone_reopened",
                     new={"title": m.title, "project_id": m.project_id})
    db.commit()
    return projects_svc.milestone_dict(m, db)


@router.delete("/milestones/{milestone_id}", dependencies=[Depends(require_cap(CAP_PROJECTS_MANAGE))])
def delete_milestone(milestone_id: int, user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    m = db.get(ProjectMilestone, milestone_id)
    if not m:
        raise HTTPException(status_code=404, detail="Milestone not found")
    old = {"title": m.title, "project_id": m.project_id}
    db.delete(m)
    db.commit()
    audit.record(db, actor_id=user.id, table_name="project_milestones", record_id=milestone_id,
                 action="milestone_delete", old=old)
    return {"ok": True}


@router.get("/{project_id}", dependencies=[Depends(require_cap(CAP_PROJECTS_VIEW))])
def project_overview(project_id: int, user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    return projects_svc.overview(db, _project_or_404(db, project_id), user)


@router.patch("/{project_id}", dependencies=[Depends(require_cap(CAP_PROJECTS_MANAGE))])
def update_project(project_id: int, payload: ProjectUpdateIn,
                   user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    p = _project_or_404(db, project_id)
    data = payload.model_dump(exclude_unset=True)
    if "name" in data and str(data["name"] or "").strip():
        p.name = str(data["name"]).strip()[:160]
    if "goal" in data:
        p.goal = (data["goal"] or "").strip() or None
    if "owner_id" in data:
        if data["owner_id"] is not None:
            owner = db.get(User, data["owner_id"])
            if not owner or not owner.is_active:
                raise HTTPException(status_code=400, detail="That owner isn't an active staff member.")
        p.owner_id = data["owner_id"]
    if "target_date" in data:
        p.target_date = data["target_date"]
    if "status" in data:
        if data["status"] not in projects_svc.STATUSES:
            raise HTTPException(status_code=400, detail="Status must be active, done or archived.")
        p.status = data["status"]
    db.commit()
    audit.record(db, actor_id=user.id, table_name="projects", record_id=p.id, action="update",
                 new={k: str(v) for k, v in data.items()})
    return projects_svc.overview(db, p, user)


@router.post("/{project_id}/milestones", dependencies=[Depends(require_cap(CAP_PROJECTS_MANAGE))])
def add_milestone(project_id: int, payload: MilestoneIn,
                  user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    p = _project_or_404(db, project_id)
    if not payload.title.strip():
        raise HTTPException(status_code=400, detail="A milestone needs a title.")
    pos = max([m.position for m in p.milestones], default=-1) + 1
    m = ProjectMilestone(project_id=p.id, title=payload.title.strip()[:200],
                         detail=(payload.detail or "").strip() or None,
                         target_date=payload.target_date, position=pos)
    db.add(m)
    db.commit()
    return projects_svc.milestone_dict(m, db)


@router.delete("/{project_id}", dependencies=[Depends(require_cap(CAP_PROJECTS_MANAGE))])
def delete_project(project_id: int, user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    """Delete the project. 🔴 Linked tasks are UNLINKED, never deleted — the work happened; only
    the grouping is being removed (the same reasoning as never deleting a Client)."""
    p = _project_or_404(db, project_id)
    old = {"name": p.name}
    db.execute(update(Task).where(Task.project_id == p.id).values(project_id=None))
    db.delete(p)      # milestones cascade via the relationship
    db.commit()
    audit.record(db, actor_id=user.id, table_name="projects", record_id=project_id,
                 action="delete", old=old)
    return {"ok": True}

"""Manage — Super Admin console for the reference data behind other tabs' dropdowns.

CRUD for: gym exercises (Gym Tracker), clients + departments/teams (Task Board, People),
and leave types (Leave). Super Admin only; every change is audit-logged. Deletes clean up or
null out dependent references so nothing breaks.
"""
from __future__ import annotations

import json
import re

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..constants import GYM_DAY_TYPES, ROLE_SUPER_ADMIN
from ..database import get_db
from ..models import (
    Client,
    ExerciseLibrary,
    LeaveBalance,
    LeaveRequest,
    LeaveType,
    ServiceTemplate,
    Task,
    TaskVocabItem,
    Team,
    User,
)
from ..security import get_current_user, require_roles
from ..serializers import client_dict, leave_type_dict, team_dict
from ..services import audit
from ..services import task_config

router = APIRouter(
    prefix="/api/manage",
    tags=["manage"],
    dependencies=[Depends(require_roles(ROLE_SUPER_ADMIN))],  # whole console is SA-only
)


def _ex_dict(e: ExerciseLibrary) -> dict:
    try:
        days = json.loads(e.day_types_json or "[]")
    except (ValueError, TypeError):
        days = []
    return {
        "id": e.id, "name": e.name, "muscle_group": e.muscle_group,
        "day_types": days, "equipment": e.equipment, "instructions": e.instructions,
    }


# ---------------- Exercises ----------------
@router.get("/exercises")
def list_exercises(db: Session = Depends(get_db)):
    return [_ex_dict(e) for e in db.execute(select(ExerciseLibrary).order_by(ExerciseLibrary.name)).scalars()]


@router.post("/exercises")
def create_exercise(payload: dict, actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "Name is required")
    if db.execute(select(ExerciseLibrary).where(ExerciseLibrary.name == name)).scalar_one_or_none():
        raise HTTPException(409, "An exercise with that name already exists")
    days = [d for d in (payload.get("day_types") or []) if d in GYM_DAY_TYPES]
    e = ExerciseLibrary(
        name=name, muscle_group=payload.get("muscle_group"), day_types_json=json.dumps(days),
        equipment=payload.get("equipment"), instructions=payload.get("instructions"),
    )
    db.add(e)
    db.commit()
    audit.record(db, actor_id=actor.id, table_name="exercise_library", record_id=e.id, action="create", new={"name": name})
    return _ex_dict(e)


@router.patch("/exercises/{item_id}")
def update_exercise(item_id: int, payload: dict, actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    e = db.get(ExerciseLibrary, item_id)
    if not e:
        raise HTTPException(404, "Exercise not found")
    if "name" in payload and payload["name"]:
        e.name = payload["name"].strip()
    if "muscle_group" in payload:
        e.muscle_group = payload["muscle_group"]
    if "day_types" in payload:
        e.day_types_json = json.dumps([d for d in (payload["day_types"] or []) if d in GYM_DAY_TYPES])
    if "equipment" in payload:
        e.equipment = payload["equipment"]
    if "instructions" in payload:
        e.instructions = payload["instructions"]
    db.commit()
    audit.record(db, actor_id=actor.id, table_name="exercise_library", record_id=e.id, action="update", new={"name": e.name})
    return _ex_dict(e)


@router.delete("/exercises/{item_id}")
def delete_exercise(item_id: int, actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    e = db.get(ExerciseLibrary, item_id)
    if not e:
        raise HTTPException(404, "Exercise not found")
    name = e.name
    db.delete(e)  # gym_exercises store the name as text, not a FK — safe to remove from the library
    db.commit()
    audit.record(db, actor_id=actor.id, table_name="exercise_library", record_id=item_id, action="delete", old={"name": name})
    return {"ok": True}


# ---------------- Clients ----------------
@router.get("/clients")
def list_clients(db: Session = Depends(get_db)):
    return [client_dict(c) for c in db.execute(select(Client).order_by(Client.name)).scalars()]


@router.post("/clients")
def create_client(payload: dict, actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "Name is required")
    if db.execute(select(Client).where(Client.name == name)).scalar_one_or_none():
        raise HTTPException(409, "A client with that name already exists")
    c = Client(name=name, contact_email=payload.get("contact_email"), atrium_client_id=payload.get("atrium_client_id"))
    db.add(c)
    db.commit()
    audit.record(db, actor_id=actor.id, table_name="clients", record_id=c.id, action="create", new={"name": name})
    return client_dict(c)


@router.patch("/clients/{item_id}")
def update_client(item_id: int, payload: dict, actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    c = db.get(Client, item_id)
    if not c:
        raise HTTPException(404, "Client not found")
    if "name" in payload and payload["name"]:
        c.name = payload["name"].strip()
    if "contact_email" in payload:
        c.contact_email = payload["contact_email"]
    if "atrium_client_id" in payload:
        c.atrium_client_id = payload["atrium_client_id"]
    db.commit()
    audit.record(db, actor_id=actor.id, table_name="clients", record_id=c.id, action="update", new={"name": c.name})
    return client_dict(c)


@router.delete("/clients/{item_id}")
def delete_client(item_id: int, actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    c = db.get(Client, item_id)
    if not c:
        raise HTTPException(404, "Client not found")
    name = c.name
    db.query(Task).filter(Task.client_id == item_id).update({Task.client_id: None}, synchronize_session=False)
    db.delete(c)
    db.commit()
    audit.record(db, actor_id=actor.id, table_name="clients", record_id=item_id, action="delete", old={"name": name})
    return {"ok": True}


# ---------------- Departments (teams) ----------------
@router.get("/teams")
def list_teams(db: Session = Depends(get_db)):
    return [team_dict(t) for t in db.execute(select(Team).order_by(Team.name)).scalars()]


@router.post("/teams")
def create_team(payload: dict, actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "Name is required")
    if db.execute(select(Team).where(Team.name == name)).scalar_one_or_none():
        raise HTTPException(409, "A department with that name already exists")
    t = Team(
        name=name, shift_start=payload.get("shift_start") or "08:00",
        shift_end=payload.get("shift_end") or "17:00",
        break_duration_min=int(payload.get("break_duration_min") or 60),
    )
    db.add(t)
    db.commit()
    audit.record(db, actor_id=actor.id, table_name="teams", record_id=t.id, action="create", new={"name": name})
    return team_dict(t)


@router.patch("/teams/{item_id}")
def update_team(item_id: int, payload: dict, actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    t = db.get(Team, item_id)
    if not t:
        raise HTTPException(404, "Department not found")
    if "name" in payload and payload["name"]:
        t.name = payload["name"].strip()
    if "shift_start" in payload and payload["shift_start"]:
        t.shift_start = payload["shift_start"]
    if "shift_end" in payload and payload["shift_end"]:
        t.shift_end = payload["shift_end"]
    if "break_duration_min" in payload and payload["break_duration_min"] not in (None, ""):
        t.break_duration_min = int(payload["break_duration_min"])
    db.commit()
    audit.record(db, actor_id=actor.id, table_name="teams", record_id=t.id, action="update", new={"name": t.name})
    return team_dict(t)


@router.delete("/teams/{item_id}")
def delete_team(item_id: int, actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    t = db.get(Team, item_id)
    if not t:
        raise HTTPException(404, "Department not found")
    name = t.name
    db.query(User).filter(User.team_id == item_id).update({User.team_id: None}, synchronize_session=False)
    db.query(Task).filter(Task.assigned_team_id == item_id).update({Task.assigned_team_id: None}, synchronize_session=False)
    db.delete(t)
    db.commit()
    audit.record(db, actor_id=actor.id, table_name="teams", record_id=item_id, action="delete", old={"name": name})
    return {"ok": True}


# ---------------- Leave types ----------------
@router.get("/leave-types")
def list_leave_types(db: Session = Depends(get_db)):
    return [leave_type_dict(lt) for lt in db.execute(select(LeaveType).order_by(LeaveType.id)).scalars()]


@router.post("/leave-types")
def create_leave_type(payload: dict, actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "Name is required")
    if db.execute(select(LeaveType).where(LeaveType.name == name)).scalar_one_or_none():
        raise HTTPException(409, "A leave type with that name already exists")
    lt = LeaveType(
        name=name, annual_balance=float(payload.get("annual_balance", 0) or 0),
        accrual_type=payload.get("accrual_type") or "Yearly",
        requires_approval=payload.get("requires_approval") or "Manager approval",
        carry_over_days=int(payload.get("carry_over_days") or 0),
    )
    db.add(lt)
    db.commit()
    audit.record(db, actor_id=actor.id, table_name="leave_types", record_id=lt.id, action="create", new={"name": name})
    return leave_type_dict(lt)


@router.patch("/leave-types/{item_id}")
def update_leave_type(item_id: int, payload: dict, actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    lt = db.get(LeaveType, item_id)
    if not lt:
        raise HTTPException(404, "Leave type not found")
    if "name" in payload and payload["name"]:
        lt.name = payload["name"].strip()
    if "annual_balance" in payload and payload["annual_balance"] not in (None, ""):
        lt.annual_balance = float(payload["annual_balance"])
    if "accrual_type" in payload:
        lt.accrual_type = payload["accrual_type"]
    if "requires_approval" in payload:
        lt.requires_approval = payload["requires_approval"]
    if "carry_over_days" in payload and payload["carry_over_days"] not in (None, ""):
        lt.carry_over_days = int(payload["carry_over_days"])
    db.commit()
    audit.record(db, actor_id=actor.id, table_name="leave_types", record_id=lt.id, action="update", new={"name": lt.name})
    return leave_type_dict(lt)


@router.delete("/leave-types/{item_id}")
def delete_leave_type(item_id: int, actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    lt = db.get(LeaveType, item_id)
    if not lt:
        raise HTTPException(404, "Leave type not found")
    name = lt.name
    db.query(LeaveBalance).filter(LeaveBalance.leave_type_id == item_id).delete(synchronize_session=False)
    db.query(LeaveRequest).filter(LeaveRequest.leave_type_id == item_id).delete(synchronize_session=False)
    db.delete(lt)
    db.commit()
    audit.record(db, actor_id=actor.id, table_name="leave_types", record_id=item_id, action="delete", old={"name": name})
    return {"ok": True}


# ---------------- Service templates (the low-code service catalog) ----------------
def _svc_dict(t: ServiceTemplate) -> dict:
    try:
        groups = json.loads(t.maintasks_json or "[]")
    except (ValueError, TypeError):
        groups = []
    return {"id": t.id, "key": t.key, "label": t.label, "dept": t.dept,
            "content_type": t.content_type, "maintasks": groups,
            "sort_order": t.sort_order, "is_active": t.is_active}


def _slug(label: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", (label or "").lower()).strip("_")
    return s or "service"


@router.get("/service-templates")
def list_services(db: Session = Depends(get_db)):
    rows = db.execute(select(ServiceTemplate).order_by(ServiceTemplate.sort_order, ServiceTemplate.id)).scalars()
    return [_svc_dict(t) for t in rows]


@router.post("/service-templates")
def create_service(payload: dict, actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    label = (payload.get("label") or "").strip()
    if not label:
        raise HTTPException(400, "Label is required")
    key = (payload.get("key") or _slug(label)).strip()
    if db.execute(select(ServiceTemplate).where(ServiceTemplate.key == key)).scalar_one_or_none():
        raise HTTPException(409, "A service with that key already exists")
    last = db.execute(select(func.max(ServiceTemplate.sort_order))).scalar() or 0
    t = ServiceTemplate(
        key=key, label=label, dept=payload.get("dept") or None,
        content_type=payload.get("content_type") or None,
        maintasks_json=json.dumps(payload.get("maintasks") or []),
        sort_order=last + 1, is_active=payload.get("is_active", True),
    )
    db.add(t)
    db.commit()
    audit.record(db, actor_id=actor.id, table_name="service_templates", record_id=t.id, action="create", new={"label": label})
    return _svc_dict(t)


@router.patch("/service-templates/{item_id}")
def update_service(item_id: int, payload: dict, actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    t = db.get(ServiceTemplate, item_id)
    if not t:
        raise HTTPException(404, "Service not found")
    if payload.get("label"):
        t.label = payload["label"].strip()
    if "dept" in payload:
        t.dept = payload["dept"] or None
    if "content_type" in payload:
        t.content_type = payload["content_type"] or None
    if "maintasks" in payload:
        t.maintasks_json = json.dumps(payload["maintasks"] or [])
    if "sort_order" in payload and payload["sort_order"] not in (None, ""):
        t.sort_order = int(payload["sort_order"])
    if "is_active" in payload:
        t.is_active = bool(payload["is_active"])
    db.commit()
    audit.record(db, actor_id=actor.id, table_name="service_templates", record_id=t.id, action="update", new={"label": t.label})
    return _svc_dict(t)


@router.delete("/service-templates/{item_id}")
def delete_service(item_id: int, actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    t = db.get(ServiceTemplate, item_id)
    if not t:
        raise HTTPException(404, "Service not found")
    label = t.label
    db.delete(t)  # tasks copy the breakdown at creation, so nothing references a template afterwards
    db.commit()
    audit.record(db, actor_id=actor.id, table_name="service_templates", record_id=item_id, action="delete", old={"label": label})
    return {"ok": True}


# ---------------- Task vocabulary: statuses / labels / priorities ----------------
def _vocab_dict(v: TaskVocabItem) -> dict:
    return {"id": v.id, "kind": v.kind, "name": v.name, "color": v.color,
            "sort_order": v.sort_order, "is_active": v.is_active}


def _label_usage(db: Session, name: str) -> int:
    """How many tasks carry this label (labels are a JSON array, so scan in Python)."""
    n = 0
    for (labels_json,) in db.execute(select(Task.labels_json)).all():
        try:
            if name in (json.loads(labels_json or "[]")):
                n += 1
        except (ValueError, TypeError):
            pass
    return n


def _vocab_usage(db: Session, kind: str, name: str) -> int:
    if kind == "status":
        return db.execute(select(func.count(Task.id)).where(Task.status == name)).scalar() or 0
    if kind == "priority":
        return db.execute(select(func.count(Task.id)).where(Task.priority == name)).scalar() or 0
    return _label_usage(db, name)


def _rename_in_tasks(db: Session, kind: str, old: str, new: str) -> None:
    """Cascade a vocab rename onto tasks (values are stored as strings on the task)."""
    if old == new:
        return
    if kind == "status":
        db.query(Task).filter(Task.status == old).update({Task.status: new}, synchronize_session=False)
    elif kind == "priority":
        db.query(Task).filter(Task.priority == old).update({Task.priority: new}, synchronize_session=False)
    else:  # label — rewrite each JSON array that contains it
        for t in db.execute(select(Task)).scalars():
            try:
                arr = json.loads(t.labels_json or "[]")
            except (ValueError, TypeError):
                continue
            if old in arr:
                t.labels_json = json.dumps([new if x == old else x for x in arr])


@router.get("/task-vocab")
def list_vocab(kind: str, db: Session = Depends(get_db)):
    if kind not in task_config.KINDS:
        raise HTTPException(400, "Invalid kind")
    rows = db.execute(
        select(TaskVocabItem).where(TaskVocabItem.kind == kind).order_by(TaskVocabItem.sort_order, TaskVocabItem.id)
    ).scalars()
    return [_vocab_dict(v) for v in rows]


@router.post("/task-vocab")
def create_vocab(payload: dict, actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    kind = payload.get("kind")
    name = (payload.get("name") or "").strip()
    if kind not in task_config.KINDS:
        raise HTTPException(400, "Invalid kind")
    if not name:
        raise HTTPException(400, "Name is required")
    if db.execute(select(TaskVocabItem).where(TaskVocabItem.kind == kind, TaskVocabItem.name == name)).scalar_one_or_none():
        raise HTTPException(409, f"That {kind} already exists")
    last = db.execute(select(func.max(TaskVocabItem.sort_order)).where(TaskVocabItem.kind == kind)).scalar() or 0
    v = TaskVocabItem(kind=kind, name=name, color=payload.get("color") or None, sort_order=last + 1)
    db.add(v)
    db.commit()
    audit.record(db, actor_id=actor.id, table_name="task_vocab", record_id=v.id, action="create", new={"kind": kind, "name": name})
    return _vocab_dict(v)


@router.patch("/task-vocab/{item_id}")
def update_vocab(item_id: int, payload: dict, actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    v = db.get(TaskVocabItem, item_id)
    if not v:
        raise HTTPException(404, "Item not found")
    if payload.get("name") and payload["name"].strip() != v.name:
        new = payload["name"].strip()
        _rename_in_tasks(db, v.kind, v.name, new)  # keep existing tasks consistent
        v.name = new
    if "color" in payload:
        v.color = payload["color"] or None
    if "sort_order" in payload and payload["sort_order"] not in (None, ""):
        v.sort_order = int(payload["sort_order"])
    if "is_active" in payload:
        v.is_active = bool(payload["is_active"])
    db.commit()
    audit.record(db, actor_id=actor.id, table_name="task_vocab", record_id=v.id, action="update", new={"name": v.name})
    return _vocab_dict(v)


@router.delete("/task-vocab/{item_id}")
def delete_vocab(item_id: int, actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    v = db.get(TaskVocabItem, item_id)
    if not v:
        raise HTTPException(404, "Item not found")
    in_use = _vocab_usage(db, v.kind, v.name)
    if in_use:
        raise HTTPException(409, f"{in_use} task(s) still use “{v.name}” — reassign them first")
    kind, name = v.kind, v.name
    db.delete(v)
    db.commit()
    audit.record(db, actor_id=actor.id, table_name="task_vocab", record_id=item_id, action="delete", old={"kind": kind, "name": name})
    return {"ok": True}

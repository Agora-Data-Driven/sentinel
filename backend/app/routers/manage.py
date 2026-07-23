"""Manage — Super Admin console for the reference data behind other tabs' dropdowns.

CRUD for: gym exercises (Gym Tracker), clients + departments/teams (Task Board, People),
and leave types (Leave). Super Admin only; every change is audit-logged. Deletes clean up or
null out dependent references so nothing breaks.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..constants import GYM_DAY_TYPES, ROLE_SUPER_ADMIN
from ..database import get_db
from ..models import (
    Client,
    ExerciseLibrary,
    LeaveBalance,
    LeaveRequest,
    LeaveType,
    Task,
    Team,
    User,
)
from ..security import get_current_user, require_roles
from ..serializers import client_dict, leave_type_dict, team_dict
from ..services import audit

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

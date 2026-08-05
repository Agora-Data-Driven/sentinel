"""Manage — Super Admin console for the reference data behind other tabs' dropdowns.

CRUD for: gym exercises (Gym Tracker), departments/teams (Task Board, People), and leave types
(Leave). Super Admin only; every change is audit-logged. Deletes clean up or null out dependent
references so nothing breaks.

🔴 **CLIENTS ARE READ-ONLY HERE (2026-08-05).** Atrium owns the client list; Sentinel owns staff.
`services/client_sync` mirrors Atrium's registry into the `clients` table — see the section comment
above `list_clients` for why re-adding a write route would reintroduce the bug it removed.
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
    ShiftTemplate,
    Task,
    TaskVocabItem,
    Team,
    User,
)
from ..security import get_current_user, require_roles
from ..serializers import client_dict, leave_type_dict, shift_template_dict, team_dict
from ..services import atrium_bridge
from ..services import atrium_tasks
from ..services import audit
from ..services import client_sync
from ..services import task_config
from ..utils.time import normalize_hhmm


def _shift_time(payload: dict, key: str, default: str | None) -> str | None:
    """Validate + normalize a shift time from a payload; raise 400 on a bad value."""
    if key not in payload:
        return default
    raw = payload.get(key)
    if raw in (None, ""):
        return default
    try:
        return normalize_hhmm(str(raw))
    except ValueError as exc:
        raise HTTPException(400, f"{key}: {exc}") from exc


def _opt_int(payload: dict, key: str, default: int | None) -> int | None:
    if key not in payload or payload.get(key) in (None, ""):
        return default
    try:
        return int(payload[key])
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, f"{key} must be a whole number") from exc

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


# ---------------- Clients — READ-ONLY, mirrored from Atrium ----------------
#
# 🔴 CREATE / PATCH / DELETE were REMOVED on 2026-08-05, by owner decision. Atrium owns the client
# list (each client is a workspace in its registry, created and renamed there); Sentinel owns STAFF.
# Maintaining clients here made this a second source of truth for something Atrium already knew, and
# the two drifted in the one field that matters: `atrium_client_id` is the BRIDGE KEY —
# `atrium_tasks.resolve_client`, `task_bridge`, `board_mirror` and `task_adoption` all address a
# workspace through it, and adoption REFUSES TO RUN without it. Every one of those failures started
# as somebody not typing a workspace key into this form.
#
# `services/client_sync` fills the table now. The table itself STAYS: it is the FK target for
# `Task.client_id` and the local cache the board's client filter reads.
#
# 🔴 Do not re-add a write route here. If a client needs to exist, it needs to exist in ATRIUM — and
# a hand-made row with no `atrium_client_id` is precisely the broken state this removed.


@router.get("/clients")
def list_clients(include_inactive: bool = False, db: Session = Depends(get_db)):
    """The mirrored client list. Inactive clients are hidden unless asked for.

    Deactivated = Atrium no longer lists it. Its tasks and history are intact (deleting would NULL
    `Task.client_id` and blank that client's reporting), it is simply out of the pickers.
    """
    q = select(Client).order_by(Client.name)
    if not include_inactive:
        q = q.where(Client.is_active.is_(True))
    return [client_dict(c) for c in db.execute(q).scalars()]


@router.get("/clients/sync-status")
def clients_sync_status(db: Session = Depends(get_db)):
    """What the read-only Clients pane shows: the mirror's health, and what it cannot address.

    `unlinked` is the actionable part — a client with no `atrium_client_id` is invisible to the
    bridge, so publishing and adoption fail for it. The fix is in Atrium (create/rename the
    workspace so the name matches), never a form here.
    """
    total = len(db.execute(select(Client)).scalars().all())
    active = len(db.execute(select(Client).where(Client.is_active.is_(True))).scalars().all())
    return {
        "total": total,
        "active": active,
        "inactive": total - active,
        "unlinked": client_sync.pending_link_report(db),
        "bridge_configured": atrium_tasks.enabled(),
        # Where clients are actually managed. Derived from the SAME setting the bridge calls, so the
        # link can never point somewhere Sentinel isn't talking to — "manage them in Atrium" is a dead
        # end without an address, and hardcoding one in the frontend is how it goes stale.
        "atrium_console_url": (atrium_bridge.base_url() + "/admin/atrium"
                               if atrium_bridge.base_url() else ""),
    }


@router.post("/clients/sync")
def clients_sync(actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Pull Atrium's client registry now. Idempotent; safe to run repeatedly.

    Also runs on boot (`main._startup`) — this route exists so somebody who just created a workspace
    in Atrium does not have to wait, and so a failure has somewhere to report itself out loud instead
    of only into the logs.
    """
    report = client_sync.sync(db)
    if not report["ok"]:
        # 409, not 500: nothing is broken here — Atrium didn't give us a list we dare act on, and the
        # message says which of the two it was. A 500 would read as a Sentinel bug.
        raise HTTPException(409, report["error"])
    audit.record(db, actor_id=actor.id, table_name="clients", record_id=0, action="sync",
                 new={k: v for k, v in report.items() if k != "skipped"})
    return report


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
        name=name,
        shift_template_id=_opt_int(payload, "shift_template_id", None),
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
    if "shift_template_id" in payload:  # null clears it → falls back to the company-default template
        t.shift_template_id = _opt_int(payload, "shift_template_id", None)
    db.commit()
    audit.record(db, actor_id=actor.id, table_name="teams", record_id=t.id, action="update", new={"name": t.name})
    return team_dict(t)


# ---------------- Shift templates ----------------
def _make_sole_default(db: Session, keep_id: int) -> None:
    """Enforce exactly one company-default template: clear every other, set ``keep_id``."""
    db.query(ShiftTemplate).filter(ShiftTemplate.id != keep_id).update(
        {ShiftTemplate.is_default: False}, synchronize_session=False)
    kept = db.get(ShiftTemplate, keep_id)
    if kept:
        kept.is_default = True


@router.get("/shift-templates")
def list_shift_templates(db: Session = Depends(get_db)):
    return [shift_template_dict(s) for s in db.execute(select(ShiftTemplate).order_by(ShiftTemplate.name)).scalars()]


@router.post("/shift-templates")
def create_shift_template(payload: dict, actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "Name is required")
    if db.execute(select(ShiftTemplate).where(ShiftTemplate.name == name)).scalar_one_or_none():
        raise HTTPException(409, "A shift template with that name already exists")
    s = ShiftTemplate(
        name=name,
        start=_shift_time(payload, "start", "08:00"),
        end=_shift_time(payload, "end", "17:00"),
        break_min=_opt_int(payload, "break_min", 60),
        grace_min=_opt_int(payload, "grace_min", None),
        active=bool(payload.get("active", True)),
        is_default=bool(payload.get("is_default", False)),
    )
    db.add(s)
    db.flush()
    if s.is_default:
        _make_sole_default(db, s.id)
    db.commit()
    audit.record(db, actor_id=actor.id, table_name="shift_templates", record_id=s.id, action="create", new={"name": name})
    return shift_template_dict(s)


@router.patch("/shift-templates/{item_id}")
def update_shift_template(item_id: int, payload: dict, actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    s = db.get(ShiftTemplate, item_id)
    if not s:
        raise HTTPException(404, "Shift template not found")
    if "name" in payload and payload["name"]:
        s.name = payload["name"].strip()
    if "start" in payload and payload["start"]:
        s.start = _shift_time(payload, "start", s.start)
    if "end" in payload and payload["end"]:
        s.end = _shift_time(payload, "end", s.end)
    if "break_min" in payload:
        s.break_min = _opt_int(payload, "break_min", s.break_min)
    if "grace_min" in payload:
        s.grace_min = _opt_int(payload, "grace_min", None)
    if "active" in payload:
        s.active = bool(payload["active"])
    # Making this the default clears any other default. We never let the default be un-set to
    # nothing — there must always be exactly one — so a falsey is_default here is ignored.
    if payload.get("is_default"):
        _make_sole_default(db, s.id)
    db.commit()
    audit.record(db, actor_id=actor.id, table_name="shift_templates", record_id=s.id, action="update", new={"name": s.name})
    return shift_template_dict(s)


@router.delete("/shift-templates/{item_id}")
def delete_shift_template(item_id: int, actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    s = db.get(ShiftTemplate, item_id)
    if not s:
        raise HTTPException(404, "Shift template not found")
    if s.is_default:
        raise HTTPException(409, "This is the company-default shift — make another template the default first")
    name = s.name
    # Detach from anyone using it so their shift cleanly falls back to team/default.
    db.query(Team).filter(Team.shift_template_id == item_id).update({Team.shift_template_id: None}, synchronize_session=False)
    db.query(User).filter(User.shift_template_id == item_id).update({User.shift_template_id: None}, synchronize_session=False)
    db.delete(s)
    db.commit()
    audit.record(db, actor_id=actor.id, table_name="shift_templates", record_id=item_id, action="delete", old={"name": name})
    return {"ok": True}


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
    try:
        labels = json.loads(getattr(t, "default_labels_json", None) or "[]")
    except (ValueError, TypeError):
        labels = []
    return {"id": t.id, "key": t.key, "label": t.label, "dept": t.dept,
            "content_type": t.content_type, "maintasks": groups,
            "default_priority": t.default_priority, "default_labels": labels,
            "default_description": t.default_description,
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
        default_priority=payload.get("default_priority") or None,
        default_labels_json=json.dumps(payload.get("default_labels") or []),
        default_description=payload.get("default_description") or None,
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
    if "default_priority" in payload:
        t.default_priority = payload["default_priority"] or None
    if "default_labels" in payload:
        t.default_labels_json = json.dumps(payload["default_labels"] or [])
    if "default_description" in payload:
        t.default_description = payload["default_description"] or None
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
            "key": v.key, "stage": v.stage,
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
    # 🔴 A NEW STATUS MUST DECLARE ITS ATRIUM STAGE (decision D13). The board is happy to hold any
    # number of statuses, but a client card can only sit in one of Atrium's five stages — so a
    # status with no stage means every attempt to move a published card into it fails. That used to
    # be discoverable only as a bare 400 "Invalid status" long after someone added the column.
    stage = (payload.get("stage") or "").strip() or None
    if kind == "status":
        if not stage:
            raise HTTPException(
                400, "Pick which client stage this status maps to: "
                     + ", ".join(task_config.ATRIUM_STAGES))
        if stage not in task_config.ATRIUM_STAGES:
            raise HTTPException(400, f"Unknown client stage “{stage}”")
    else:
        stage = None                      # only statuses project onto a stage
    last = db.execute(select(func.max(TaskVocabItem.sort_order)).where(TaskVocabItem.kind == kind)).scalar() or 0
    v = TaskVocabItem(kind=kind, name=name, color=payload.get("color") or None,
                      key=task_config.slugify(name), stage=stage, sort_order=last + 1)
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
        # `key` and `stage` deliberately DO NOT move. The label is the renameable facet; the key is
        # this row's identity and the stage is where the client's card sits. Re-slugging the key
        # here would reintroduce exactly the breakage the split exists to prevent — which is what
        # makes "Blocked" -> "Parked" a one-field edit (docs/TASKBOARD_REBUILD.md §5.1).
    if "stage" in payload and v.kind == "status":
        stage = (payload.get("stage") or "").strip()
        if not stage:
            raise HTTPException(400, "A status must keep a client stage")
        if stage not in task_config.ATRIUM_STAGES:
            raise HTTPException(400, f"Unknown client stage “{stage}”")
        v.stage = stage
    if not v.key:
        v.key = task_config.slugify(v.name)   # heal a row seeded before the column existed
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

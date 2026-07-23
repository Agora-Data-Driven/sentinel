"""Model → dict serializers. Central so field exposure (internal vs client-facing) stays consistent.

Datetimes are emitted as ISO strings in Manila time so the frontend can display them directly while
the DB keeps UTC.
"""
from __future__ import annotations

import json
from datetime import date, datetime

from sqlalchemy.orm import Session

from .constants import ROLE_LABELS
from .models import (
    AttendanceRequest,
    BodyMetric,
    CareerAchievement,
    Client,
    DailyAttendanceSummary,
    DevelopmentProfile,
    GrowthItem,
    GymLog,
    LeaveBalance,
    LeaveRequest,
    LeaveType,
    Notification,
    PersonalRecord,
    ProfessionalGoal,
    ReadingItem,
    ReadingProgress,
    Skill,
    Task,
    TaskComment,
    TaskHistory,
    Team,
    User,
)
from .utils.time import to_ph


def _iso(dt: datetime | None) -> str | None:
    return to_ph(dt).isoformat() if dt else None


def _d(d: date | None) -> str | None:
    return d.isoformat() if d else None


def _loads(raw: str | None, default):
    try:
        return json.loads(raw) if raw else default
    except (ValueError, TypeError):
        return default


def user_public(u: User | None) -> dict | None:
    if not u:
        return None
    return {
        "id": u.id,
        "name": u.name,
        "email": u.email,
        "role": u.role,
        "role_label": ROLE_LABELS.get(u.role, u.role),
        "team_id": u.team_id,
        "initials": u.initials,
        "profile_pic_url": u.profile_pic_url,
    }


def user_full(u: User, team: Team | None = None) -> dict:
    d = user_public(u) or {}
    d.update(
        {
            "phone": u.phone,
            "is_active": u.is_active,
            "hired_date": _d(u.hired_date),
            "shift_start": u.shift_start,
            "shift_end": u.shift_end,
            "team_name": team.name if team else None,
        }
    )
    return d


def team_dict(t: Team) -> dict:
    return {
        "id": t.id,
        "name": t.name,
        "shift_start": t.shift_start,
        "shift_end": t.shift_end,
        "break_duration_min": t.break_duration_min,
    }


def client_dict(c: Client) -> dict:
    return {
        "id": c.id,
        "name": c.name,
        "contact_email": c.contact_email,
        "atrium_client_id": c.atrium_client_id,
    }


def maintask_list(t: Task, db: Session) -> list[dict]:
    """The two-level breakdown with assignees resolved to user_public (assignee cached per call)."""
    from .services import maintasks as MT

    mts = MT.normalize(getattr(t, "maintasks_json", "[]"), t.checklist_json)
    cache: dict[int, dict | None] = {}

    def usr(uid):
        if not uid:
            return None
        if uid not in cache:
            cache[uid] = user_public(db.get(User, uid))
        return cache[uid]

    return [{
        "id": m["id"], "title": m["title"],
        "assignee_id": m["assignee_id"], "assignee": usr(m["assignee_id"]),
        "subs": [{"id": s["id"], "text": s["text"], "done": s["done"],
                  "assignee_id": s["assignee_id"], "assignee": usr(s["assignee_id"])} for s in m["subs"]],
    } for m in mts]


def task_card(t: Task, db: Session) -> dict:
    """Compact shape for the Kanban board."""
    from .services import maintasks as MT

    comment_count = len(t.comments)
    attach_count = sum(len(_loads(c.attachments_json, [])) for c in t.comments)
    client = db.get(Client, t.client_id) if t.client_id else None
    assignee = db.get(User, t.assigned_to_id) if t.assigned_to_id else None
    # Progress now spans the two-level breakdown (all sub-tasks of all main tasks); a legacy flat
    # checklist is migrated by normalize(), so the count stays correct for old tasks too.
    done, total = MT.sub_stats(MT.normalize(getattr(t, "maintasks_json", "[]"), t.checklist_json))
    return {
        "id": t.id,
        "title": t.title,
        "status": t.status,
        "priority": t.priority,
        "due_date": _d(t.due_date),
        "labels": _loads(t.labels_json, []),
        "client_id": t.client_id,
        "client_name": client.name if client else None,
        "assigned_to_id": t.assigned_to_id,
        "assignee": user_public(assignee),
        "assigned_team_id": t.assigned_team_id,
        "comment_count": comment_count,
        "attachment_count": attach_count,
        "checklist_total": total,
        "checklist_done": done,
        "atrium_visible": t.atrium_visible,
    }


def task_detail(t: Task, db: Session) -> dict:
    """Full task incl. internal fields (Sentinel users are all internal staff)."""
    d = task_card(t, db)
    am = db.get(User, t.account_manager_id) if t.account_manager_id else None
    team = db.get(Team, t.assigned_team_id) if t.assigned_team_id else None
    d.update(
        {
            "description": t.description,
            "campaign": t.campaign,
            "content_type": t.content_type,
            "account_manager_id": t.account_manager_id,
            "account_manager": user_public(am),
            "assigned_team_name": team.name if team else None,
            "checklist": _loads(t.checklist_json, []),  # legacy flat list (kept for compatibility)
            "maintasks": maintask_list(t, db),
            "deliverable_url": t.deliverable_url,
            "internal_notes": t.internal_notes,
            "client_facing_notes": t.client_facing_notes,
            "comments": [comment_dict(c, db) for c in sorted(t.comments, key=lambda c: c.id)],
            "history": [history_dict(h, db) for h in sorted(t.history, key=lambda h: h.id, reverse=True)],
            "created_at": _iso(t.created_at),
            "updated_at": _iso(t.updated_at),
        }
    )
    return d


def atrium_payload(t: Task, db: Session) -> dict:
    """ONLY client-facing fields — this is what may cross the bridge into Atrium."""
    client = db.get(Client, t.client_id) if t.client_id else None
    return {
        "task_id": t.id,
        "client": client.name if client else None,
        "campaign": t.campaign,
        "content_type": t.content_type,
        "title": t.title,
        "due_date": _d(t.due_date),
        "labels": _loads(t.labels_json, []),
        "deliverable_url": t.deliverable_url,
        "client_notes": t.client_facing_notes,
    }


def comment_dict(c: TaskComment, db: Session) -> dict:
    return {
        "id": c.id,
        "author": user_public(db.get(User, c.author_id)),
        "body": c.body,
        "attachments": _loads(c.attachments_json, []),
        "created_at": _iso(c.created_at),
    }


def history_dict(h: TaskHistory, db: Session) -> dict:
    return {
        "id": h.id,
        "actor": user_public(db.get(User, h.changed_by_id)) if h.changed_by_id else None,
        "field": h.field_changed,
        "old_value": h.old_value,
        "new_value": h.new_value,
        "changed_at": _iso(h.changed_at),
    }


def summary_dict(s: DailyAttendanceSummary, user: User | None = None) -> dict:
    return {
        "id": s.id,
        "user_id": s.user_id,
        "user": user_public(user) if user else None,
        "date": _d(s.date),
        "clock_in": _iso(s.clock_in),
        "clock_out": _iso(s.clock_out),
        "break_duration_min": s.break_duration_min,
        "total_work_hours": s.total_work_hours,
        "status": s.status,
        "handover_note": s.handover_note,
    }


def attendance_request_dict(r: AttendanceRequest, db: Session) -> dict:
    return {
        "id": r.id,
        "user": user_public(db.get(User, r.user_id)),
        "date": _d(r.date),
        "request_type": r.request_type,
        "reason": r.reason,
        "old_value": r.old_value,
        "new_value": r.new_value,
        "status": r.status,
        "created_at": _iso(r.created_at),
    }


def gym_log_dict(g: GymLog, db: Session, with_exercises: bool = False) -> dict:
    d = {
        "id": g.id,
        "user_id": g.user_id,
        "user": user_public(db.get(User, g.user_id)),
        "date": _d(g.date),
        "day_type": g.day_type,
        "start_time": _iso(g.start_time),
        "end_time": _iso(g.end_time),
        "duration_minutes": g.duration_minutes,
        "status": g.status,
        "notes": g.notes,
        "exercise_count": len(g.exercises),
    }
    if with_exercises:
        d["exercises"] = [
            {
                "id": e.id,
                "exercise_name": e.exercise_name,
                "muscle_group": e.muscle_group,
                "weight_value": e.weight_value,
                "weight_unit": e.weight_unit,
                "sets": e.sets,
                "reps": e.reps,
                "set_type": e.set_type,
                "sets_detail": _loads(e.sets_json, []),
                "duration_minutes": e.duration_minutes,
                "notes": e.notes,
            }
            for e in g.exercises
        ]
    return d


# --- Development (holistic) -------------------------------------------------
def body_metric_dict(m: BodyMetric) -> dict:
    return {
        "id": m.id,
        "date": _d(m.date),
        "weight_kg": m.weight_kg,
        "body_fat_pct": m.body_fat_pct,
        "notes": m.notes,
    }


def pr_display(p: PersonalRecord) -> str:
    """Human-readable result: a weight PR shows 'Xkg x Y'; a cardio/other PR shows its free `detail`."""
    if p.weight_value:
        return f"{p.weight_value:g}{p.weight_unit or 'kg'} × {p.reps}"
    if p.detail:
        return p.detail
    return f"× {p.reps}" if p.reps else ""


def personal_record_dict(p: PersonalRecord) -> dict:
    return {
        "id": p.id,
        "exercise_name": p.exercise_name,
        "weight_value": p.weight_value,
        "weight_unit": p.weight_unit,
        "reps": p.reps,
        "detail": p.detail,
        "display": pr_display(p),
        "achieved_on": _d(p.achieved_on),
        "notes": p.notes,
    }


def development_profile_dict(p: DevelopmentProfile | None) -> dict:
    if not p:
        return {"headline": None, "resume_text": None, "resume_file_url": None}
    return {
        "headline": p.headline,
        "resume_text": p.resume_text,
        "resume_file_url": p.resume_file_url,
        "updated_at": _iso(p.updated_at),
    }


def achievement_dict(a: CareerAchievement) -> dict:
    return {
        "id": a.id,
        "title": a.title,
        "description": a.description,
        "achieved_on": _d(a.achieved_on),
    }


def goal_dict(g: ProfessionalGoal) -> dict:
    return {
        "id": g.id,
        "title": g.title,
        "description": g.description,
        "target_date": _d(g.target_date),
        "status": g.status,
        "progress_pct": g.progress_pct,
    }


def growth_item_dict(g: GrowthItem) -> dict:
    return {
        "id": g.id,
        "kind": g.kind,
        "title": g.title,
        "detail": g.detail,
        "status": g.status,
        "created_at": _iso(g.created_at),
    }


def skill_dict(s: Skill) -> dict:
    return {
        "id": s.id,
        "name": s.name,
        "level": s.level,
        "source": s.source,
        "note": s.note,
    }


def reading_item_dict(r: ReadingItem, progress: ReadingProgress | None = None) -> dict:
    """A canon item, optionally merged with the current worker's progress on it."""
    d = {
        "id": r.id,
        "title": r.title,
        "author": r.author,
        "kind": r.kind,
        "url": r.url,
        "summary": r.summary,
        "required": r.required,
        "sort_order": r.sort_order,
    }
    d["progress"] = (
        {
            "status": progress.status,
            "reflection": progress.reflection,
            "rating": progress.rating,
        }
        if progress
        else {"status": "not_started", "reflection": None, "rating": None}
    )
    return d


def leave_type_dict(lt: LeaveType) -> dict:
    return {
        "id": lt.id,
        "name": lt.name,
        "annual_balance": lt.annual_balance,
        "accrual_type": lt.accrual_type,
        "requires_approval": lt.requires_approval,
        "carry_over_days": lt.carry_over_days,
    }


def leave_balance_dict(b: LeaveBalance, lt: LeaveType | None) -> dict:
    return {
        "id": b.id,
        "leave_type_id": b.leave_type_id,
        "leave_type": lt.name if lt else None,
        "year": b.year,
        "used": b.used,
        "remaining": b.remaining,
        "unlimited": bool(lt and lt.annual_balance < 0),
    }


def leave_request_dict(r: LeaveRequest, db: Session) -> dict:
    lt = db.get(LeaveType, r.leave_type_id)
    return {
        "id": r.id,
        "user": user_public(db.get(User, r.user_id)),
        "leave_type": lt.name if lt else None,
        "leave_type_id": r.leave_type_id,
        "start_date": _d(r.start_date),
        "end_date": _d(r.end_date),
        "total_days": r.total_days,
        "reason": r.reason,
        "status": r.status,
        "created_at": _iso(r.created_at),
    }


def notification_dict(n: Notification) -> dict:
    return {
        "id": n.id,
        "type": n.type,
        "title": n.title,
        "body": n.body,
        "link": n.link,
        "is_read": n.is_read,
        "created_at": _iso(n.created_at),
    }

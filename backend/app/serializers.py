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
    Client,
    DailyAttendanceSummary,
    GymLog,
    LeaveBalance,
    LeaveRequest,
    LeaveType,
    Notification,
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


def task_card(t: Task, db: Session) -> dict:
    """Compact shape for the Kanban board."""
    comment_count = len(t.comments)
    attach_count = sum(len(_loads(c.attachments_json, [])) for c in t.comments)
    client = db.get(Client, t.client_id) if t.client_id else None
    assignee = db.get(User, t.assigned_to_id) if t.assigned_to_id else None
    checklist = _loads(t.checklist_json, [])
    done = sum(1 for i in checklist if i.get("done"))
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
        "checklist_total": len(checklist),
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
            "checklist": _loads(t.checklist_json, []),
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

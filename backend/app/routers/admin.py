"""Admin: system settings, audit trail, broadcast announcements, and the dashboard KPIs."""
from __future__ import annotations

import json
from datetime import timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..constants import ADMIN_ROLES
from ..database import get_db
from ..models import (
    AuditLog,
    DailyAttendanceSummary,
    GymLog,
    Notification,
    User,
)
from ..schemas import AnnouncementIn, SettingsIn
from ..capabilities import (
    CAP_ANNOUNCE_SEND,
    CAP_AUDIT_VIEW,
    CAP_INSIGHTS_VIEW,
    CAP_SETTINGS_EDIT,
    CAP_SETTINGS_VIEW,
)
from ..security import get_current_user, require_cap
from ..serializers import summary_dict, user_public
from ..services import attendance as att
from ..services import audit
from ..services import settings as settings_svc
from ..services import notifications as notif
from ..utils.time import today_ph, to_ph

router = APIRouter(prefix="/api", tags=["admin"])


# --- Settings --------------------------------------------------------------
@router.get("/admin/settings")
def get_settings(admin: User = Depends(require_cap(CAP_SETTINGS_VIEW)), db: Session = Depends(get_db)):
    smap = settings_svc.get_map(db)
    return {
        "settings": smap,
        "descriptions": settings_svc.DESCRIPTIONS,
    }


@router.patch("/admin/settings")
def update_settings(payload: SettingsIn, admin: User = Depends(require_cap(CAP_SETTINGS_EDIT)), db: Session = Depends(get_db)):
    for key, value in payload.settings.items():
        old, new = settings_svc.set_value(db, key, value, admin.id)
        if old != new:
            audit.record(db, actor_id=admin.id, table_name="system_settings", record_id=key,
                         action="update", old={key: old}, new={key: new}, commit=False)
    db.commit()
    return {"ok": True, "settings": settings_svc.get_map(db)}


# --- Audit trail -----------------------------------------------------------
@router.get("/audit-logs")
def audit_logs(
    table: str | None = Query(None),
    action: str | None = Query(None),
    actor_id: int | None = Query(None),
    admin: User = Depends(require_cap(CAP_AUDIT_VIEW)),
    db: Session = Depends(get_db),
):
    q = select(AuditLog).order_by(AuditLog.created_at.desc())
    if table:
        q = q.where(AuditLog.table_name == table)
    if action:
        q = q.where(AuditLog.action == action)
    if actor_id:
        q = q.where(AuditLog.actor_id == actor_id)
    rows = db.execute(q.limit(200)).scalars().all()
    return [
        {
            "id": a.id,
            "actor": user_public(db.get(User, a.actor_id)) if a.actor_id else None,
            "table": a.table_name,
            "record_id": a.record_id,
            "action": a.action,
            "old": json.loads(a.old_value_json) if a.old_value_json else None,
            "new": json.loads(a.new_value_json) if a.new_value_json else None,
            "reason": a.reason,
            "created_at": to_ph(a.created_at).isoformat(),
        }
        for a in rows
    ]


# --- Announcements ---------------------------------------------------------
@router.post("/admin/announce")
def announce(payload: AnnouncementIn, admin: User = Depends(require_cap(CAP_ANNOUNCE_SEND)), db: Session = Depends(get_db)):
    sent = notif.broadcast(db, title=payload.title, body=payload.body)
    audit.record(db, actor_id=admin.id, table_name="notifications", action="broadcast",
                 new={"title": payload.title, "recipients": sent})
    return {"ok": True, "recipients": sent}


# --- Insights (dashboard charts) -------------------------------------------
_WD = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


@router.get("/insights")
def insights(admin: User = Depends(require_cap(CAP_INSIGHTS_VIEW)), db: Session = Depends(get_db)):
    """14-day clock-in trend for the dashboard chart.

    Presence only — absence is deliberately not derived here (product call, 2026-07-27:
    the dashboard tracks who showed up, not who didn't). Each day carries its full
    clocked-in roster so the frontend can show "who was in" on bar click without a
    second request; at Agora's headcount that stays a few KB.
    """
    today = today_ph()
    start = today - timedelta(days=13)
    smap = settings_svc.get_map(db)
    workdays = {_WD[d.strip().lower()[:3]] for d in smap.get("work_days", "Mon,Tue,Wed,Thu,Fri").split(",")
                if d.strip()[:3].lower() in _WD} or {0, 1, 2, 3, 4}

    summaries = db.execute(
        select(DailyAttendanceSummary).where(
            DailyAttendanceSummary.date >= start, DailyAttendanceSummary.date <= today,
            DailyAttendanceSummary.clock_in.is_not(None),
        )
    ).scalars().all()
    user_ids = {s.user_id for s in summaries}
    users = {u.id: u for u in db.execute(select(User).where(User.id.in_(user_ids))).scalars()} if user_ids else {}

    by_day: dict = {}
    for s in summaries:
        b = by_day.setdefault(s.date, {"ontime": 0, "late": 0, "people": []})
        if s.status == "Late":
            b["late"] += 1
        else:  # OnTime, HalfDay, MissingClockOut — all clocked in
            b["ontime"] += 1
        b["people"].append({
            "user": user_public(users.get(s.user_id)),
            "clock_in": to_ph(s.clock_in).isoformat(),
            "status": s.status,
        })

    trend = []
    for i in range(14):
        day = start + timedelta(days=i)
        b = by_day.get(day, {"ontime": 0, "late": 0, "people": []})
        b["people"].sort(key=lambda p: p["clock_in"])
        trend.append({
            "date": day.isoformat(),
            "ontime": b["ontime"], "late": b["late"],
            "people": b["people"],
            "workday": day.weekday() in workdays,
        })

    return {"attendance_trend": trend}


# --- Dashboard -------------------------------------------------------------
@router.get("/dashboard")
def dashboard(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Role-aware home. Admins see org KPIs; everyone gets their personal snapshot."""
    today = today_ph()
    is_admin = user.role in ADMIN_ROLES

    payload: dict = {"is_admin": is_admin, "user": user_public(user), "date": today.isoformat()}

    if is_admin:
        headcount = db.execute(select(func.count(User.id)).where(User.is_active.is_(True))).scalar() or 0
        today_summaries = db.execute(
            select(DailyAttendanceSummary).where(DailyAttendanceSummary.date == today)
        ).scalars().all()
        present = sum(1 for s in today_summaries if s.clock_in)
        late = sum(1 for s in today_summaries if s.status == "Late")
        week_start = today - timedelta(days=today.weekday())
        gym_week = db.execute(select(GymLog).where(GymLog.date >= week_start)).scalars().all()
        gym_completed = sum(1 for g in gym_week if g.status == "Completed")

        # Presence-focused on purpose: no absent/task/approval counts here (2026-07-27).
        # Tasks live on the embedded board below; approvals have their own page + bell.
        payload["kpis"] = {
            "headcount": headcount,
            "present_today": present,
            "late_today": late,
            "gym_completed_week": gym_completed,
        }
        # Yesterday's handover notes surface on the dashboard.
        y = today - timedelta(days=1)
        handovers = db.execute(
            select(DailyAttendanceSummary).where(
                DailyAttendanceSummary.date == y, DailyAttendanceSummary.handover_note.is_not(None)
            )
        ).scalars().all()
        payload["handovers"] = [
            {"user": user_public(db.get(User, s.user_id)), "note": s.handover_note}
            for s in handovers if s.handover_note
        ]
        payload["late_today_list"] = [
            summary_dict(s, db.get(User, s.user_id)) for s in today_summaries if s.status == "Late"
        ]

    # Personal snapshot (all roles).
    my_today = db.execute(
        select(DailyAttendanceSummary).where(
            DailyAttendanceSummary.user_id == user.id, DailyAttendanceSummary.date == today
        )
    ).scalar_one_or_none()
    my_gym = db.execute(
        select(GymLog).where(GymLog.user_id == user.id, GymLog.date == today)
    ).scalar_one_or_none()
    unread = db.execute(
        select(func.count(Notification.id)).where(
            Notification.user_id == user.id, Notification.is_read.is_(False)
        )
    ).scalar() or 0
    # Today's punch state drives the Clock In / Clock Out buttons on the dashboard card
    # (self-punch via POST /api/attendance/self-event — no kiosk needed).
    my_events = att._events_for(db, user.id, today)
    # No task payload here — the dashboard embeds the full Task Board, which loads its own data.
    payload["me"] = {
        "attendance_today": summary_dict(my_today, user) if my_today else None,
        "attendance_actions": att.valid_actions(my_events),
        "gym_today": {"status": my_gym.status, "day_type": my_gym.day_type} if my_gym else None,
        "unread_notifications": unread,
    }
    return payload

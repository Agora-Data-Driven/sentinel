"""Attendance: kiosk scan/punch, offline sync, regularization + overtime requests, summaries."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import settings
from ..constants import (
    ACTION_BREAK_END,
    ACTION_CLOCK_IN,
    ACTION_CLOCK_OUT,
    ADMIN_ROLES,
    ATTENDANCE_ACTIONS,
    MANAGER_ROLES,
    NOTIF_APPROVAL,
    REQ_APPROVED,
    REQ_OVERTIME,
    REQ_PENDING,
    ROLE_LABELS,
    ROLE_SUPER_ADMIN,
)
from ..database import get_db
from ..models import (
    AttendanceEvent,
    AttendanceRequest,
    DailyAttendanceSummary,
    QRToken,
    Team,
    User,
)
from ..schemas import AttendanceEditIn, AttendanceRequestIn, EventIn, OfflineSyncIn, RequestDecisionIn, ScanIn
from ..security import get_current_user, get_current_user_optional, require_min_role, require_roles
from ..serializers import attendance_request_dict, summary_dict, user_public
from ..services import attendance as att
from ..services import audit
from ..services import notifications as notif
from ..utils.time import PH_TZ, minutes_between, parse_hhmm, to_ph, today_ph, utcnow
from ..constants import ROLE_TEAM_LEAD

router = APIRouter(prefix="/api/attendance", tags=["attendance"])


# --- Kiosk trust ----------------------------------------------------------
def kiosk_guard(request: Request, user: User | None = Depends(get_current_user_optional)):
    """Gate the punch endpoints. Access is granted by EITHER of two trusted paths:

      * a valid kiosk key (``X-Kiosk-Key`` header or ``?kiosk_key=``) — for an unattended kiosk
        device where employees self-scan without logging in, or
      * an authenticated Super-Admin session — the ``/scanner`` phone tool is Super-Admin-only, so a
        logged-in super_admin is already trusted and needs no separate key (this is the everyday
        path; it means the scanner works out of the box without shipping a secret to the browser).

    Secure-by-default: in PRODUCTION, with neither a key nor a trusted session, the endpoints are
    closed. In dev they stay open when no key is set, for zero-setup local testing.
    """
    if settings.kiosk_key:
        supplied = request.headers.get("X-Kiosk-Key") or request.query_params.get("kiosk_key")
        if supplied == settings.kiosk_key:
            return
    if user is not None and user.role == ROLE_SUPER_ADMIN:
        return
    if not settings.kiosk_key:
        if settings.is_production:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Attendance kiosk is not configured. Sign in as a Super Admin to scan, or set KIOSK_KEY for an unattended kiosk.",
            )
        return  # dev convenience: open on an unset key
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid kiosk key")


def _resolve_token(db: Session, token: str) -> User:
    row = db.execute(
        select(QRToken).where(QRToken.token == token, QRToken.is_active.is_(True))
    ).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown or inactive QR badge")
    user = db.get(User, row.user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee inactive")
    return user


def _scan_payload(db: Session, user: User) -> dict:
    day = today_ph()
    events = att._events_for(db, user.id, day)
    team = db.get(Team, user.team_id) if user.team_id else None
    shift = att.effective_shift(db, user)
    return {
        "user": user_public(user),
        "team_name": team.name if team else None,
        "role_label": ROLE_LABELS.get(user.role, user.role),
        "shift": {"start": shift.start, "end": shift.end, "grace": shift.grace_min,
                  "break": shift.break_min, "name": shift.name},
        "state": att.current_state(events),
        "valid_actions": att.valid_actions(events),
        "punches_today": [
            {"action": e.action, "time": to_ph(e.time).isoformat()} for e in events
        ],
    }


@router.post("/scan", dependencies=[Depends(kiosk_guard)])
def scan(payload: ScanIn, db: Session = Depends(get_db)):
    """QR scanned at the kiosk → who it is + which buttons to show."""
    user = _resolve_token(db, payload.token)
    return _scan_payload(db, user)


def _record_event(
    db: Session,
    user: User,
    action: str,
    device: str,
    instant: datetime,
    late_reason: str | None,
    handover_note: str | None,
    client_uid: str | None = None,
) -> dict:
    day = to_ph(instant).date()
    events = att._events_for(db, user.id, day)

    # Clock-out while on break auto-ends the break first (spec rule).
    if action == ACTION_CLOCK_OUT and att.current_state(events) == "on_break":
        auto = AttendanceEvent(
            user_id=user.id, date=day, time=instant, action=ACTION_BREAK_END, device=device
        )
        db.add(auto)
        db.flush()
        events = att._events_for(db, user.id, day)

    err = att.validate_action(events, action)
    if err:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=err)

    ev = AttendanceEvent(
        user_id=user.id, date=day, time=instant, action=action, device=device,
        late_reason=late_reason, handover_note=handover_note, client_uid=client_uid,
    )
    if action == ACTION_CLOCK_IN:
        shift = att.effective_shift(db, user)
        late_status, late_minutes = att.compute_late(instant, shift)
        ev.late_status = late_status
        ev.late_minutes = late_minutes
    db.add(ev)
    try:
        db.flush()
    except IntegrityError:
        # Lost a race with a concurrent punch that inserted the same clock-in/out first.
        db.rollback()
        dup = "Already clocked in today" if action == ACTION_CLOCK_IN else "Already clocked out today"
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=dup) from None

    summary = att.recompute_summary(db, user, day, commit=False)
    db.commit()
    return {
        "ok": True,
        "action": action,
        "late_status": ev.late_status,
        "late_minutes": ev.late_minutes,
        "summary": summary_dict(summary, user),
        "scan": _scan_payload(db, user),
    }


@router.post("/event", dependencies=[Depends(kiosk_guard)])
def event(payload: EventIn, db: Session = Depends(get_db)):
    if payload.action not in ATTENDANCE_ACTIONS:
        raise HTTPException(status_code=400, detail="Invalid action")
    user = _resolve_token(db, payload.token)
    return _record_event(
        db, user, payload.action, payload.device or "kiosk", utcnow(),
        payload.late_reason, payload.handover_note,
    )


@router.post("/offline-sync", dependencies=[Depends(kiosk_guard)])
def offline_sync(payload: OfflineSyncIn, db: Session = Depends(get_db)):
    """Bulk upload of punches queued in IndexedDB while the kiosk was offline."""
    results = []
    now = utcnow()
    for p in sorted(payload.punches, key=lambda x: x.client_time):
        try:
            user = _resolve_token(db, p.token)
            # Idempotency: if this exact punch (by client_uid) was already recorded, treat it as a
            # success without inserting a duplicate — so a re-sync after a lost response is safe.
            if p.uid and db.execute(
                select(AttendanceEvent.id).where(AttendanceEvent.client_uid == p.uid)
            ).first():
                results.append({"uid": p.uid, "token": p.token, "action": p.action, "ok": True, "duplicate": True})
                continue
            instant = _parse_instant(p.client_time)
            # Anti-tamper: offline punches carry a device timestamp. Reject anything in the future
            # (beyond small skew) or absurdly old, so a wrong/rigged device clock can't backdate a
            # late arrival or postdate a punch.
            if instant > now + timedelta(minutes=10) or instant < now - timedelta(days=14):
                raise HTTPException(status_code=422, detail="Punch time is outside the acceptable window (device clock error).")
            _record_event(db, user, p.action, "offline", instant, p.late_reason, p.handover_note, client_uid=p.uid)
            results.append({"uid": p.uid, "token": p.token, "action": p.action, "ok": True})
        except HTTPException as e:
            # Business rejections (duplicate punch, unknown/inactive badge) won't succeed on retry,
            # so mark them permanent — the kiosk drops them from its queue instead of looping forever.
            results.append({"uid": p.uid, "token": p.token, "action": p.action,
                            "ok": False, "permanent": True, "error": e.detail})
    return {"synced": sum(1 for r in results if r["ok"]), "results": results}


def _parse_instant(iso: str) -> datetime:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return utcnow()
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


# --- Regularization / overtime requests -----------------------------------
@router.post("/request")
def create_request(
    payload: AttendanceRequestIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    req = AttendanceRequest(
        user_id=user.id,
        date=payload.date,
        request_type=payload.request_type,
        reason=payload.reason,
        old_value=payload.old_value,
        new_value=payload.new_value,
        status=REQ_PENDING,
    )
    db.add(req)
    db.flush()  # assign req.id; single atomic commit below
    notif.notify_managers(
        db,
        type=NOTIF_APPROVAL,
        title=f"{payload.request_type.title()} request from {user.name}",
        body=payload.reason,
        link="/attendance",
        team_id=user.team_id,
        commit=False,
    )
    audit.record(db, actor_id=user.id, table_name="attendance_requests", record_id=req.id,
                 action="create", new={"type": payload.request_type, "date": str(payload.date)}, commit=False)
    db.commit()
    return attendance_request_dict(req, db)


@router.get("/requests")
def list_requests(
    status_filter: str | None = Query(None, alias="status"),
    reviewer: User = Depends(require_min_role(ROLE_TEAM_LEAD)),
    db: Session = Depends(get_db),
):
    q = select(AttendanceRequest).order_by(AttendanceRequest.created_at.desc())
    if status_filter:
        q = q.where(AttendanceRequest.status == status_filter)
    rows = db.execute(q).scalars().all()
    return [attendance_request_dict(r, db) for r in rows]


@router.patch("/request/{req_id}")
def decide_request(
    req_id: int,
    payload: RequestDecisionIn,
    reviewer: User = Depends(require_min_role(ROLE_TEAM_LEAD)),
    db: Session = Depends(get_db),
):
    req = db.get(AttendanceRequest, req_id)
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")
    # No self-approval: a reviewer can't decide their own request (Super Admin exempt).
    if reviewer.id == req.user_id and reviewer.role != ROLE_SUPER_ADMIN:
        raise HTTPException(status_code=403, detail="You can't review your own request — ask another approver.")
    old_status = req.status
    req.status = payload.status
    req.reviewed_by_id = reviewer.id
    req.reviewed_at = utcnow()

    notif.notify(
        db, user_id=req.user_id, type=NOTIF_APPROVAL,
        title=f"Your {req.request_type} request was {payload.status.lower()}",
        body=req.reason, link="/attendance", commit=False,
    )
    audit.record(db, actor_id=reviewer.id, table_name="attendance_requests", record_id=req.id,
                 action="decide", old={"status": old_status}, new={"status": payload.status}, commit=False)
    db.commit()  # decision + notification + audit commit atomically
    return attendance_request_dict(req, db)


# --- Summaries -------------------------------------------------------------
@router.get("/summary")
def summaries(
    from_: date | None = Query(None, alias="from"),
    to: date | None = Query(None),
    team_id: int | None = Query(None),
    admin: User = Depends(require_min_role(ROLE_TEAM_LEAD)),
    db: Session = Depends(get_db),
):
    q = select(DailyAttendanceSummary).order_by(DailyAttendanceSummary.date.desc())
    if from_:
        q = q.where(DailyAttendanceSummary.date >= from_)
    if to:
        q = q.where(DailyAttendanceSummary.date <= to)
    rows = db.execute(q).scalars().all()
    out = []
    for s in rows:
        u = db.get(User, s.user_id)
        if team_id and (not u or u.team_id != team_id):
            continue
        # Team leads only see their own team.
        if admin.role == ROLE_TEAM_LEAD and (not u or u.team_id != admin.team_id):
            continue
        out.append(summary_dict(s, u))
    return out


def _ph_to_utc(day: date, hhmm: str) -> datetime:
    """PH-local 'HH:MM' on ``day`` -> naive UTC datetime (matches how punches are stored)."""
    t = parse_hhmm(hhmm)
    local = datetime(day.year, day.month, day.day, t.hour, t.minute, tzinfo=PH_TZ)
    return local.astimezone(timezone.utc).replace(tzinfo=None)


@router.patch("/summary/{summary_id}")
def edit_summary(
    summary_id: int,
    payload: AttendanceEditIn,
    admin: User = Depends(require_roles(ROLE_SUPER_ADMIN)),
    db: Session = Depends(get_db),
):
    """Super Admin manual correction of a day's attendance (fix a wrong/missed scan)."""
    s = db.get(DailyAttendanceSummary, summary_id)
    if not s:
        raise HTTPException(status_code=404, detail="Attendance record not found")
    user = db.get(User, s.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Employee not found")
    old = {"clock_in": to_ph(s.clock_in).strftime("%H:%M") if s.clock_in else None,
           "clock_out": to_ph(s.clock_out).strftime("%H:%M") if s.clock_out else None,
           "status": s.status}
    if payload.clock_out is not None and payload.clock_out.strip() and payload.clock_in is not None \
            and payload.clock_in.strip() and payload.clock_out.strip() <= payload.clock_in.strip():
        raise HTTPException(status_code=400, detail="Clock-out must be after clock-in")

    # A manual correction must rewrite the day's clock-in/out EVENTS, not just the summary row — the
    # summary is a pure projection of events, so editing only the row would be wiped by the nightly
    # recompute or the employee's next scan. We replace the clock-in/out events, then re-derive.
    if payload.clock_in is not None or payload.clock_out is not None:
        day = s.date
        for e in att._events_for(db, user.id, day):
            if payload.clock_in is not None and e.action == ACTION_CLOCK_IN:
                db.delete(e)
            elif payload.clock_out is not None and e.action == ACTION_CLOCK_OUT:
                db.delete(e)
        # Flush the deletes BEFORE inserting replacements. The (user_id, date) partial unique indexes
        # (uq_att_one_clockin/clockout_per_day) allow only one clock-in/out per day; SQLAlchemy's unit
        # of work emits INSERTs before DELETEs, so without this flush the new punch collides with the
        # old row still in the table and Postgres raises UniqueViolation (SQLite dev DBs lack the
        # partial index, so this only ever surfaced in prod).
        db.flush()
        if payload.clock_in is not None and payload.clock_in.strip():
            db.add(AttendanceEvent(user_id=user.id, date=day, time=_ph_to_utc(day, payload.clock_in),
                                   action=ACTION_CLOCK_IN, device="manual", late_reason="Manual correction"))
        if payload.clock_out is not None and payload.clock_out.strip():
            db.add(AttendanceEvent(user_id=user.id, date=day, time=_ph_to_utc(day, payload.clock_out),
                                   action=ACTION_CLOCK_OUT, device="manual"))
        db.flush()
        s = att.recompute_summary(db, user, day, commit=False)

    # An explicit status override (e.g. mark OnLeave) still wins when provided.
    if payload.status:
        s.status = payload.status
    audit.record(db, actor_id=admin.id, table_name="daily_attendance_summary", record_id=s.id,
                 action="edit", old=old,
                 new={"clock_in": payload.clock_in, "clock_out": payload.clock_out, "status": s.status},
                 commit=False)
    db.commit()
    return summary_dict(s, user)


@router.get("/my")
def my_attendance(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.execute(
        select(DailyAttendanceSummary)
        .where(DailyAttendanceSummary.user_id == user.id)
        .order_by(DailyAttendanceSummary.date.desc())
    ).scalars().all()
    day = today_ph()
    events = att._events_for(db, user.id, day)
    return {
        "today": {"state": att.current_state(events), "valid_actions": att.valid_actions(events)},
        "history": [summary_dict(s, user) for s in rows],
    }

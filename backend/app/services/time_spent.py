"""Minutes spent on growth — per person, per dimension, over a window — from TWO sources.

1. THE MASTERY ENGINE records one minute-key per ACTIVE minute per learner (`users/{email}/activity/
   {day}` there; its `/api/activity/beat` defines "active": a visible frame plus a recent signal —
   input, speaking, the AI speaking or streaming, an action). Read back through the `time-spent` /
   `time-detail` HMAC purposes; the engine's programmes are mapped onto Sentinel's dimensions here:

       career programme            -> professional
       the Philosophical tab's pin -> philosophical      (DIM_PROGRAMS, shared with team_growth)
       the Spiritual tab's pin     -> spiritual
       no programme at all         -> coach              (the Coach FAB, or an unscoped screen)
       any other growth programme  -> other

2. MANUAL ENTRIES (`models.TimeEntry`) are what the engine cannot see — a book on paper, a gym
   session, a course elsewhere — typed by the person against any dimension (Physical included, which
   has no engine programme at all). They live here, in Postgres, and are merged with the engine's
   minutes only at read time. Every session row says which it is (`source`).

EDITING. A person may be honest about a recorded session ("I was just moving the mouse"): an engine
session can be DELETED or TRIMMED, never extended or moved — that is one signed POST to the engine's
`time-edit`, which removes minute keys. Adding time is always a manual entry, so a typed row can
never impersonate engine activity. A manual entry is fully editable.

WINDOWS are Sentinel's, computed here in PH time and sent to the engine as DATES (`from`/`to`),
so "today" means the same thing on both sides: the engine stamps minutes in Asia/Manila too.

    today  -> [today, today]
    week   -> [Monday, today]
    30d    -> [today − 29, today]

🔴 ZERO IS A REAL ANSWER HERE, UNLIKE THE PROGRESS ROLLUPS. A person with no minutes has no
activity docs, and "0m" is the truth. The unknown state is reserved for the bridge failing
(`engine_error` set, engine-derived figures `None`) — which the UI renders as "—", never as 0m, for
the same reason `team_growth` insists on it: a column of zeroes reads as "nobody is using it".
Manual minutes are still reported in that state (`manual_minutes`); they don't depend on the engine.
"""

from __future__ import annotations

import re
import time
from datetime import date, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..constants import ADMIN_ROLES, DIM_PHILOSOPHICAL, DIM_PHYSICAL, DIM_PROFESSIONAL, DIM_SPIRITUAL, GROWTH_DIMENSIONS
from ..models import TimeEntry, User
from ..serializers import user_public
from ..utils.time import now_ph, today_ph, to_ph, utcnow
from . import engine_bridge
from .team_growth import DIM_PROGRAMS, ENGINE_BATCH, visible_users

WINDOWS = ("today", "week", "30d")
DEFAULT_WINDOW = "today"

BUCKET_COACH = "coach"
BUCKET_OTHER = "other"
# Display order. The four dimensions (Physical has no engine programme, so its minutes are all
# manual), then the Coach, then anything unmapped.
BUCKETS = (DIM_PROFESSIONAL, DIM_PHILOSOPHICAL, DIM_SPIRITUAL, DIM_PHYSICAL, BUCKET_COACH, BUCKET_OTHER)
# What a manual entry may be filed under: every bucket. `other` is for the honest miscellany.
MANUAL_DIMENSIONS = tuple(GROWTH_DIMENSIONS) + (BUCKET_COACH, BUCKET_OTHER)

MAX_ENTRY_MINUTES = 12 * 60
HHMM = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
# An engine session that ended this recently may still be RUNNING — the next beat would re-stamp
# minutes a delete just removed (the engine keeps no tombstones). Refuse, and say why.
LIVE_GUARD_MINUTES = 5

# One engine round trip per (roster, window); an admin refreshing the Overview should not
# re-read thirty day-docs per head. Short enough that a finished session shows within minutes.
CACHE_TTL_SECONDS = 120
_cache: dict[tuple, tuple[float, dict]] = {}


# --- windows -----------------------------------------------------------------


def normalize_window(win: str | None) -> str:
    w = (win or "").strip().lower()
    return w if w in WINDOWS else DEFAULT_WINDOW


def window_range(win: str, today: date | None = None) -> tuple[date, date]:
    """Inclusive [from, to] in PH dates for a window key."""
    today = today or today_ph()
    win = normalize_window(win)
    if win == "week":
        return today - timedelta(days=today.weekday()), today
    if win == "30d":
        return today - timedelta(days=29), today
    return today, today


# --- buckets -----------------------------------------------------------------


def bucket_of(program_id: str, programs: dict[str, dict]) -> str:
    """Which dimension a programme id's minutes belong to (see the module docstring)."""
    if not program_id:
        return BUCKET_COACH
    for dim, ids in DIM_PROGRAMS.items():
        if program_id in ids:
            return dim
    category = (programs.get(program_id) or {}).get("category") or "career"
    return DIM_PROFESSIONAL if category != "growth" else BUCKET_OTHER


def _empty_buckets(value=0) -> dict[str, int | None]:
    return {b: value for b in BUCKETS}


def engine_buckets(person: dict | None, programs: dict[str, dict]) -> dict[str, int | None]:
    """Engine minutes per bucket for one person payload; every bucket None when it isn't found."""
    if not person or not person.get("found"):
        return _empty_buckets(None)
    out = _empty_buckets(0)
    for pid, minutes in (person.get("byProgram") or {}).items():
        out[bucket_of(str(pid or ""), programs)] += int(minutes or 0)
    return out


def manual_buckets(entries: list[TimeEntry]) -> dict[str, int]:
    out = _empty_buckets(0)
    for e in entries:
        out[e.dimension if e.dimension in BUCKETS else BUCKET_OTHER] += int(e.minutes or 0)
    return out


def _merge_buckets(engine: dict[str, int | None], manual: dict[str, int]) -> dict[str, int | None]:
    """Engine + manual per bucket. An unknown engine (None) stays unknown — manual minutes alone are
    reported separately, never dressed up as the total."""
    return {b: (None if engine.get(b) is None else int(engine.get(b) or 0) + int(manual.get(b) or 0)) for b in BUCKETS}


def _programs_index(payload: dict) -> dict[str, dict]:
    return {str(p.get("id") or ""): p for p in (payload.get("programs") or []) if p.get("id")}


# --- engine calls ------------------------------------------------------------


def fetch_summary(emails: list[str], frm: date, to: date) -> tuple[dict[str, dict], dict[str, dict], str]:
    """Every listed person's summary keyed by lower-cased email, the engine's programme index,
    and an error string ("" on success). Chunked at ENGINE_BATCH like the progress rollup."""
    if not engine_bridge.enabled():
        return {}, {}, "the Mastery Engine bridge isn't configured"
    out: dict[str, dict] = {}
    programs: dict[str, dict] = {}
    errors: list[str] = []
    for i in range(0, len(emails), ENGINE_BATCH):
        chunk = [e for e in emails[i:i + ENGINE_BATCH] if e]
        if not chunk:
            continue
        status, data, err = engine_bridge.call(
            "time-spent", "/api/internal/time-spent",
            params={"emails": ",".join(chunk), "from": frm.isoformat(), "to": to.isoformat()},
            timeout=engine_bridge.TEAM_TIMEOUT,
        )
        if status != 200 or not isinstance(data, dict):
            errors.append(err or f"the Mastery Engine answered {status}")
            continue
        programs.update(_programs_index(data))
        for person in data.get("people") or []:
            email = str(person.get("email") or "").strip().lower()
            if email:
                out[email] = person
    return out, programs, ("; ".join(dict.fromkeys(errors)) if errors else "")


def fetch_detail(email: str, frm: date, to: date) -> tuple[dict, str]:
    """One person's session rows. Returns (payload, error); payload is {} on failure."""
    if not engine_bridge.enabled():
        return {}, "the Mastery Engine bridge isn't configured"
    status, data, err = engine_bridge.call(
        "time-detail", "/api/internal/time-detail",
        params={"email": (email or "").strip().lower(), "from": frm.isoformat(), "to": to.isoformat()},
    )
    if status != 200 or not isinstance(data, dict):
        return {}, err or f"the Mastery Engine answered {status}"
    return data, ""


# --- manual entries ------------------------------------------------------------


def entries_between(db: Session, user_ids: list[int], frm: date, to: date) -> dict[int, list[TimeEntry]]:
    """Every manual entry for these people in [frm, to], keyed by user id. ONE query for the roster."""
    if not user_ids:
        return {}
    rows = db.execute(
        select(TimeEntry).where(TimeEntry.user_id.in_(user_ids), TimeEntry.date >= frm, TimeEntry.date <= to)
        .order_by(TimeEntry.date, TimeEntry.start_hhmm)
    ).scalars().all()
    out: dict[int, list[TimeEntry]] = {}
    for r in rows:
        out.setdefault(r.user_id, []).append(r)
    return out


def _end_hhmm(start: str, minutes: int) -> str:
    h, m = int(start[:2]), int(start[3:])
    total = min(h * 60 + m + int(minutes), 24 * 60 - 1)
    return f"{total // 60:02d}:{total % 60:02d}"


def entry_dict(e: TimeEntry) -> dict:
    return {
        "id": e.id, "source": "manual", "editable": True,
        "day": e.date.isoformat(), "start": e.start_hhmm, "end": _end_hhmm(e.start_hhmm, e.minutes),
        "minutes": int(e.minutes or 0),
        "bucket": e.dimension if e.dimension in BUCKETS else BUCKET_OTHER,
        "dimension": e.dimension, "note": e.note or "",
        "self_reported": e.created_by_id in (None, e.user_id),
    }


def _validate_entry(dimension: str | None, start: str | None, minutes: int | None, day: date | None) -> tuple[str, str, int, date]:
    dim = (dimension or "").strip().lower()
    if dim not in MANUAL_DIMENSIONS:
        raise HTTPException(status_code=400, detail=f"Unknown dimension '{dimension}'")
    if not start or not HHMM.match(start):
        raise HTTPException(status_code=400, detail="Start must be HH:MM")
    if minutes is None or int(minutes) < 1 or int(minutes) > MAX_ENTRY_MINUTES:
        raise HTTPException(status_code=400, detail=f"Minutes must be between 1 and {MAX_ENTRY_MINUTES}")
    if day is None:
        raise HTTPException(status_code=400, detail="A date is required")
    if day > today_ph():
        raise HTTPException(status_code=400, detail="You can't log time in the future")
    return dim, start, int(minutes), day


def add_entry(db: Session, target: User, actor: User, *, day: date, start: str, minutes: int,
              dimension: str, note: str | None) -> dict:
    dim, start, minutes, day = _validate_entry(dimension, start, minutes, day)
    e = TimeEntry(user_id=target.id, date=day, start_hhmm=start, minutes=minutes, dimension=dim,
                  note=(note or "").strip() or None, created_by_id=actor.id)
    db.add(e)
    db.commit()
    _cache.clear()
    return entry_dict(e)


def update_entry(db: Session, entry: TimeEntry, *, day: date | None, start: str | None, minutes: int | None,
                 dimension: str | None, note: str | None) -> dict:
    dim, start, minutes, day = _validate_entry(
        dimension if dimension is not None else entry.dimension,
        start if start is not None else entry.start_hhmm,
        minutes if minutes is not None else entry.minutes,
        day if day is not None else entry.date,
    )
    entry.dimension, entry.start_hhmm, entry.minutes, entry.date = dim, start, minutes, day
    if note is not None:
        entry.note = note.strip() or None
    db.commit()
    _cache.clear()
    return entry_dict(entry)


def delete_entry(db: Session, entry: TimeEntry) -> None:
    db.delete(entry)
    db.commit()
    _cache.clear()


# --- editing the engine's minutes ----------------------------------------------


def _idx(hhmm: str) -> int:
    if not HHMM.match(hhmm or ""):
        raise HTTPException(status_code=400, detail="Times must be HH:MM")
    return int(hhmm[:2]) * 60 + int(hhmm[3:])


def _hhmm(idx: int) -> str:
    return f"{idx // 60:02d}:{idx % 60:02d}"


def edit_engine_session(target: User, *, day: date, start: str, end: str,
                        new_start: str | None, new_end: str | None) -> dict:
    """Delete (no new_*) or TRIM an engine session to [new_start, new_end). Never extends or moves:
    an extension is a manual entry, so a hand-typed minute can never pose as engine activity."""
    a, z = _idx(start), _idx(end)
    if z <= a:
        raise HTTPException(status_code=400, detail="The session's end must be after its start")
    if day == today_ph():
        now = now_ph()
        if z >= now.hour * 60 + now.minute - LIVE_GUARD_MINUTES:
            raise HTTPException(status_code=409, detail="That session may still be running — the engine would "
                                "record the minutes again. Wait a few minutes after it ends, then edit it.")
    remove: list[dict] = []
    if new_start is None and new_end is None:
        remove.append({"start": _hhmm(a), "end": _hhmm(z)})
    else:
        na = _idx(new_start) if new_start is not None else a
        nz = _idx(new_end) if new_end is not None else z
        if na < a or nz > z:
            raise HTTPException(status_code=400, detail="A recorded session can only be shortened. To add time, "
                                "log a manual entry.")
        if nz <= na:
            raise HTTPException(status_code=400, detail="The new end must be after the new start (delete the "
                                "session to remove it entirely)")
        if na > a:
            remove.append({"start": _hhmm(a), "end": _hhmm(na)})
        if nz < z:
            remove.append({"start": _hhmm(nz), "end": _hhmm(z)})
        if not remove:
            return {"ok": True, "removed": 0}
    if not engine_bridge.enabled():
        raise HTTPException(status_code=503, detail="The Mastery Engine bridge isn't configured")
    status, data, err = engine_bridge.post(
        "time-edit", "/api/internal/time-edit",
        {"email": (target.email or "").strip().lower(), "day": day.isoformat(), "remove": remove},
    )
    if status != 200:
        raise HTTPException(status_code=502, detail=err or f"the Mastery Engine answered {status}")
    _cache.clear()
    return {"ok": True, "removed": int((data or {}).get("removed") or 0), "ranges": remove}


def may_write(viewer: User, target: User) -> bool:
    """Who may log or correct somebody's time: the person, or an admin on their behalf."""
    return viewer.id == target.id or viewer.role in ADMIN_ROLES


# --- payloads ----------------------------------------------------------------


def _window_block(win: str, frm: date, to: date) -> dict:
    return {"window": win, "from": frm.isoformat(), "to": to.isoformat()}


def summary(db: Session, user: User, win: str) -> dict:
    """One person's minutes per bucket over the window — what the Overview's strip shows."""
    win = normalize_window(win)
    frm, to = window_range(win)
    email = (user.email or "").strip().lower()
    by_email, programs, error = fetch_summary([email], frm, to)
    person = by_email.get(email)
    found = bool(person and person.get("found")) and not error
    manual = entries_between(db, [user.id], frm, to).get(user.id, [])
    m_buckets = manual_buckets(manual)
    e_buckets = engine_buckets(person if found else None, programs)
    engine_minutes = int(person.get("minutes") or 0) if found else None
    manual_minutes = sum(m_buckets.values())
    by_day: dict[str, int] = dict(person.get("byDay") or {}) if found else {}
    for e in manual:
        by_day[e.date.isoformat()] = by_day.get(e.date.isoformat(), 0) + int(e.minutes or 0)
    return {
        **_window_block(win, frm, to),
        "user": user_public(user),
        "found": found,
        "engine_error": error or (person or {}).get("error") or "",
        "buckets": _merge_buckets(e_buckets, m_buckets),
        "engine_buckets": e_buckets,
        "manual_buckets": m_buckets,
        "total": (engine_minutes + manual_minutes) if found else None,
        "engine_minutes": engine_minutes,
        "manual_minutes": manual_minutes,
        "by_day": by_day,
        "by_view": dict(person.get("byView") or {}) if found else {},
        "last_at": person.get("lastAt") if found else None,
    }


def detail(db: Session, user: User, win: str) -> dict:
    """One person's sessions over the window — engine rows AND manual rows, each tagged with its
    bucket and source — the click-through, and the surface every edit is made from."""
    win = normalize_window(win)
    frm, to = window_range(win)
    email = (user.email or "").strip().lower()
    data, error = fetch_detail(email, frm, to)
    programs = _programs_index(data) if data else {}
    found = bool(data) and not error
    sessions: list[dict] = []
    if found:
        today = today_ph().isoformat()
        now = now_ph()
        live_from = now.hour * 60 + now.minute - LIVE_GUARD_MINUTES
        for s in data.get("sessions") or []:
            pid = str(s.get("program") or "")
            end = str(s.get("end") or "")
            live = s.get("day") == today and HHMM.match(end) is not None and _idx(end) >= live_from
            sessions.append({
                "source": "engine",
                # A session still inside the live guard can't be edited yet (the engine would re-stamp it).
                "editable": not live,
                "live": live,
                "day": s.get("day"), "start": s.get("start"), "end": end,
                "minutes": int(s.get("minutes") or 0),
                "bucket": bucket_of(pid, programs),
                "program": pid,
                "program_name": (programs.get(pid) or {}).get("name") or pid,
                "view": s.get("view") or "app",
                "track": s.get("track") or "", "course": s.get("course") or "",
                "lesson": s.get("lesson") or "", "topics": list(s.get("topics") or []),
            })
    manual = entries_between(db, [user.id], frm, to).get(user.id, [])
    sessions.extend(entry_dict(e) for e in manual)
    sessions.sort(key=lambda s: (s.get("day") or "", s.get("start") or ""))
    m_buckets = manual_buckets(manual)
    e_buckets = engine_buckets({**data, "found": True} if found else None, programs)
    engine_minutes = int(data.get("minutes") or 0) if found else None
    manual_minutes = sum(m_buckets.values())
    return {
        **_window_block(win, frm, to),
        "user": user_public(user),
        "found": found,
        "engine_error": error,
        "buckets": _merge_buckets(e_buckets, m_buckets),
        "manual_buckets": m_buckets,
        "total": (engine_minutes + manual_minutes) if found else None,
        "engine_minutes": engine_minutes,
        "manual_minutes": manual_minutes,
        "dimensions": list(MANUAL_DIMENSIONS),
        "sessions": sessions,
    }


def team(db: Session, viewer: User, win: str, refresh: bool = False) -> dict:
    """Everyone the viewer may see, one row each, cached per (roster, window, day)."""
    win = normalize_window(win)
    people = visible_users(db, viewer)
    key = (tuple(u.id for u in people), win, today_ph().isoformat())
    if not refresh:
        hit = _cache.get(key)
        if hit and (time.time() - hit[0]) < CACHE_TTL_SECONDS:
            return {**hit[1], "cached": True}
    payload = _build_team(db, people, win)
    _cache[key] = (time.time(), payload)
    return {**payload, "cached": False}


def _build_team(db: Session, people: list[User], win: str) -> dict:
    frm, to = window_range(win)
    base = {**_window_block(win, frm, to), "generated_at": to_ph(utcnow()).isoformat()}
    if not people:
        return {**base, "engine_error": "", "rows": []}
    emails = [(u.email or "").strip().lower() for u in people]
    by_email, programs, error = fetch_summary(emails, frm, to)
    manual_by_user = entries_between(db, [u.id for u in people], frm, to)
    rows = []
    for user in people:
        person = by_email.get((user.email or "").strip().lower())
        found = bool(person and person.get("found")) and not error
        m_buckets = manual_buckets(manual_by_user.get(user.id, []))
        e_buckets = engine_buckets(person if found else None, programs)
        engine_minutes = int(person.get("minutes") or 0) if found else None
        manual_minutes = sum(m_buckets.values())
        rows.append({
            "user": user_public(user),
            "found": found,
            "engine_error": (person or {}).get("error") or "",
            "buckets": _merge_buckets(e_buckets, m_buckets),
            "total": (engine_minutes + manual_minutes) if found else None,
            "engine_minutes": engine_minutes,
            "manual_minutes": manual_minutes,
            "last_at": person.get("lastAt") if found else None,
        })
    # Most time first; unknowns (None) sink to the bottom whichever way you read it.
    rows.sort(key=lambda r: (r["total"] is None, -(r["total"] or 0), (r["user"].get("name") or "").lower()))
    return {**base, "engine_error": error, "rows": rows}

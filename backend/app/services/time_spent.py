"""Minutes spent in the Mastery Engine — per person, per growth dimension, over a window.

The engine records one minute-key per ACTIVE minute per learner (`users/{email}/activity/{day}`
there; its `/api/activity/beat` defines "active": a visible frame plus a recent signal — input,
speaking, the AI speaking or streaming, an action). This module reads those minutes back through
two HMAC purposes and maps the engine's programmes onto Sentinel's dimensions:

    career programme            -> professional
    the Philosophical tab's pin -> philosophical      (DIM_PROGRAMS, shared with team_growth)
    the Spiritual tab's pin     -> spiritual
    no programme at all         -> coach              (the Coach FAB, or an unscoped screen)
    any other growth programme  -> other

WINDOWS are Sentinel's, computed here in PH time and sent to the engine as DATES (`from`/`to`),
so "today" means the same thing on both sides: the engine stamps minutes in Asia/Manila too.

    today  -> [today, today]
    week   -> [Monday, today]
    30d    -> [today − 29, today]

🔴 ZERO IS A REAL ANSWER HERE, UNLIKE THE PROGRESS ROLLUPS. A person with no minutes has no
activity docs, and "0m" is the truth. The unknown state is reserved for the bridge failing
(`engine_error` set, every figure `None`) — which the UI renders as "—", never as 0m, for the same
reason `team_growth` insists on it: a column of zeroes reads as "nobody is using it".
"""

from __future__ import annotations

import time
from datetime import date, timedelta

from sqlalchemy.orm import Session

from ..constants import DIM_PHILOSOPHICAL, DIM_PROFESSIONAL, DIM_SPIRITUAL
from ..models import User
from ..serializers import user_public
from ..utils.time import today_ph, to_ph, utcnow
from . import engine_bridge
from .team_growth import DIM_PROGRAMS, ENGINE_BATCH, visible_users

WINDOWS = ("today", "week", "30d")
DEFAULT_WINDOW = "today"

BUCKET_COACH = "coach"
BUCKET_OTHER = "other"
# Display order. The three engine dimensions first (Physical has no engine programme and so no
# minutes here), then the Coach, then anything unmapped.
BUCKETS = (DIM_PROFESSIONAL, DIM_PHILOSOPHICAL, DIM_SPIRITUAL, BUCKET_COACH, BUCKET_OTHER)

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


def buckets_for(person: dict | None, programs: dict[str, dict]) -> dict[str, int | None]:
    """Minutes per bucket for one engine person payload; every bucket None when it isn't found."""
    if not person or not person.get("found"):
        return _empty_buckets(None)
    out = _empty_buckets(0)
    for pid, minutes in (person.get("byProgram") or {}).items():
        out[bucket_of(str(pid or ""), programs)] += int(minutes or 0)
    return out


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


# --- payloads ----------------------------------------------------------------


def _window_block(win: str, frm: date, to: date) -> dict:
    return {"window": win, "from": frm.isoformat(), "to": to.isoformat()}


def summary(user: User, win: str) -> dict:
    """One person's minutes per bucket over the window — what the Overview's strip shows."""
    win = normalize_window(win)
    frm, to = window_range(win)
    email = (user.email or "").strip().lower()
    by_email, programs, error = fetch_summary([email], frm, to)
    person = by_email.get(email)
    found = bool(person and person.get("found")) and not error
    return {
        **_window_block(win, frm, to),
        "user": user_public(user),
        "found": found,
        "engine_error": error or (person or {}).get("error") or "",
        "buckets": buckets_for(person if found else None, programs),
        "total": int(person.get("minutes") or 0) if found else None,
        "by_day": dict(person.get("byDay") or {}) if found else {},
        "by_view": dict(person.get("byView") or {}) if found else {},
        "last_at": person.get("lastAt") if found else None,
    }


def detail(user: User, win: str) -> dict:
    """One person's sessions over the window, each tagged with its bucket — the click-through."""
    win = normalize_window(win)
    frm, to = window_range(win)
    email = (user.email or "").strip().lower()
    data, error = fetch_detail(email, frm, to)
    programs = _programs_index(data) if data else {}
    found = bool(data) and not error
    sessions = []
    if found:
        for s in data.get("sessions") or []:
            pid = str(s.get("program") or "")
            sessions.append({
                "day": s.get("day"), "start": s.get("start"), "end": s.get("end"),
                "minutes": int(s.get("minutes") or 0),
                "bucket": bucket_of(pid, programs),
                "program": pid,
                "program_name": (programs.get(pid) or {}).get("name") or pid,
                "view": s.get("view") or "app",
                "track": s.get("track") or "", "course": s.get("course") or "",
                "lesson": s.get("lesson") or "", "topics": list(s.get("topics") or []),
            })
    return {
        **_window_block(win, frm, to),
        "user": user_public(user),
        "found": found,
        "engine_error": error,
        "buckets": buckets_for({**data, "found": True} if found else None, programs),
        "total": int(data.get("minutes") or 0) if found else None,
        "sessions": sessions,
    }


def team(db: Session, viewer: User, win: str, refresh: bool = False) -> dict:
    """Everyone the viewer may see, one row each, cached per (roster, window)."""
    win = normalize_window(win)
    people = visible_users(db, viewer)
    key = (tuple(u.id for u in people), win, today_ph().isoformat())
    if not refresh:
        hit = _cache.get(key)
        if hit and (time.time() - hit[0]) < CACHE_TTL_SECONDS:
            return {**hit[1], "cached": True}
    payload = _build_team(people, win)
    _cache[key] = (time.time(), payload)
    return {**payload, "cached": False}


def _build_team(people: list[User], win: str) -> dict:
    frm, to = window_range(win)
    base = {**_window_block(win, frm, to), "generated_at": to_ph(utcnow()).isoformat()}
    if not people:
        return {**base, "engine_error": "", "rows": []}
    emails = [(u.email or "").strip().lower() for u in people]
    by_email, programs, error = fetch_summary(emails, frm, to)
    rows = []
    for user in people:
        person = by_email.get((user.email or "").strip().lower())
        found = bool(person and person.get("found")) and not error
        rows.append({
            "user": user_public(user),
            "found": found,
            "engine_error": (person or {}).get("error") or "",
            "buckets": buckets_for(person if found else None, programs),
            "total": int(person.get("minutes") or 0) if found else None,
            "last_at": person.get("lastAt") if found else None,
        })
    # Most time first; unknowns (None) sink to the bottom whichever way you read it.
    rows.sort(key=lambda r: (r["total"] is None, -(r["total"] or 0), (r["user"].get("name") or "").lower()))
    return {**base, "engine_error": error, "rows": rows}

"""The whole team's growth in one payload — what the Overview's admin "Team progress" panel ranks.

`/api/development/team` is the per-person counterpart of the four rings each worker sees for
themselves: the same Mastery Engine numbers, for everybody a manager may see, plus the one thing a
single ring cannot show — **how fast each person is actually moving**.

WHAT "SPEED" MEANS HERE, precisely, because three plausible readings give three different answers:

  * NOT "score ÷ days since the programme began". The start date is a shared constant, so that
    ranks identically to the raw score and tells an admin nothing they can't already see.
  * NOT the ahead/behind pace chip. That compares a score against a CALENDAR, so somebody who
    banked progress in July and has done nothing since still reads "ahead". It is a useful second
    column (and the UI shows it), but it is a position, not a rate.
  * IT IS points of engine mastery gained per week, measured. The engine replays each person's
    attempt log over the window and reports `progressSumThen` beside `progressSum` — the identical
    rollup computed against their stats as they stood when the window opened. now − then, over the
    window, annualised to a week. Someone stuck at 61% and someone climbing through 27% are
    finally distinguishable, which is the entire point of the panel.

Physical is deliberately absent from the speed number and says so in the payload
(`velocity: None`): its ring is the mean progress across target PRs, and a PR carries only a
current value — nothing timestamps the climb, so there is no honest rate to report. Inventing one
by treating "no history" as "no movement" would libel whoever is training hardest.

🔴 AN UNREACHABLE ENGINE IS NOT A ZERO. Every actual/velocity is `None` — never 0.0 — when the
bridge fails, and `engine_error` carries the reason to the top of the payload so the panel can say
so. A table of zeroes reads as "nobody is doing anything", which is a confident lie and precisely
the failure the Watcher bridge's empty state produced twice (see AGENTS.md §5).
"""

from __future__ import annotations

import time
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..constants import (
    ADMIN_ROLES,
    DIM_PHILOSOPHICAL,
    DIM_PHYSICAL,
    DIM_PROFESSIONAL,
    DIM_SPIRITUAL,
    GROWTH_DIMENSIONS,
    GYM_COMPLETED,
    ROLE_TEAM_LEAD,
)
from ..models import (
    DailyAttendanceSummary,
    DevelopmentArea,
    GymLog,
    PhysicalGoal,
    ProfessionalGoal,
    Team,
    User,
)
from ..serializers import physical_goal_progress, user_public
from ..utils.time import today_ph, to_ph, utcnow
from . import engine_bridge
from . import teams as teams_svc

# Which engine programs feed which dimension. MIRRORS `DIM_PROGRAMS` in frontend/static/js/growth.js
# — a worker's own ring and their row in this table must be the same number, so if one side gains a
# dimension the other has to gain it in the same change.
DIM_PROGRAMS: dict[str, tuple[str, ...]] = {
    DIM_PHILOSOPHICAL: ("philosophy",),
    DIM_SPIRITUAL: ("spiritual",),
}

# The engine caps a team-progress call at 60 emails (MAX_TEAM_EMAILS there); stay under it and
# chunk, so a growing roster degrades into a second round trip rather than a 400.
ENGINE_BATCH = 50

# The measurement window for velocity. 30 days is long enough that one quiet week doesn't read as
# a stall, short enough that a month-old burst doesn't keep someone at the top of the table.
DEFAULT_WINDOW_DAYS = 30

# The rollup costs one engine round trip over the whole roster; an admin refreshing the Overview
# should not re-run it. Short enough that "I just finished a quiz" shows up within a coffee break.
CACHE_TTL_SECONDS = 120
_cache: dict[tuple, tuple[float, dict]] = {}


# --- who a manager may see ---------------------------------------------------


def visible_users(db: Session, viewer: User) -> list[User]:
    """Active staff this viewer may see, mirroring `tasks.employee_summary`'s scope.

    Admin / super-admin see everyone; a team lead sees their own team. Anyone else gets nobody —
    the endpoint guards on role as well, this is the second half of the same rule.
    """
    rows = db.execute(select(User).where(User.is_active.is_(True))).scalars().all()
    if viewer.role in ADMIN_ROLES:
        people = list(rows)
    elif viewer.role == ROLE_TEAM_LEAD and teams_svc.team_ids(viewer):
        # All of the lead's departments, and everyone in them (`services/teams`, 2026-08-14).
        mine = teams_svc.member_ids(db, teams_svc.team_ids(viewer))
        people = [u for u in rows if u.id in mine or u.id == viewer.id]
    else:
        people = []
    return sorted(people, key=lambda u: (u.name or u.email or "").lower())


# --- engine rollup -----------------------------------------------------------


def _weighted_pct(programs: list[dict]) -> float | None:
    """Topic-weighted mastery across `programs` — the engine's own "Overall mastery" formula.

    Σ progressSum / Σ topicsTotal, with the same plain-mean fallback growth.js keeps for an engine
    that predates `progressSum`. Returns None (not 0) when there is nothing to average.
    """
    if not programs:
        return None
    total = sum(p.get("topicsTotal") or 0 for p in programs)
    if total and all(p.get("progressSum") is not None for p in programs):
        return sum(p.get("progressSum") or 0 for p in programs) / total
    pcts = [p.get("pct") for p in programs if p.get("pct") is not None]
    return (sum(pcts) / len(pcts)) if pcts else None


def _weighted_pct_then(programs: list[dict]) -> float | None:
    """The same figure as it stood when the window opened, or None if the engine didn't report it.

    No fallback on purpose. `progressSumThen` is the only honest source for "where they were"; a
    guess here would turn into a fabricated velocity, and a made-up rate is worse than a blank one.
    """
    if not programs:
        return None
    total = sum(p.get("topicsTotal") or 0 for p in programs)
    if not total or not all(p.get("progressSumThen") is not None for p in programs):
        return None
    return sum(p.get("progressSumThen") or 0 for p in programs) / total


def _velocity(programs: list[dict], days: int) -> float | None:
    """Points of mastery per week over the window, or None when it can't be measured."""
    now = _weighted_pct(programs)
    then = _weighted_pct_then(programs)
    if now is None or then is None or days <= 0:
        return None
    return round((now - then) / days * 7, 2)


def _programs_for_dim(programs: list[dict], dim: str) -> list[dict]:
    """The engine programs behind one dimension — the same split growth.js's `dimActual` makes."""
    if dim == DIM_PROFESSIONAL:
        return [p for p in programs if (p.get("category") or "career") != "growth"]
    wanted = DIM_PROGRAMS.get(dim, ())
    return [p for p in programs if p.get("id") in wanted]


def fetch_engine(emails: list[str], days: int) -> tuple[dict[str, dict], str]:
    """Every listed person's engine rollup, keyed by lower-cased email. Returns (by_email, error).

    Chunked at ENGINE_BATCH. A chunk that fails contributes nothing and its reason is reported —
    callers must render the affected rows as "unknown", never as zero.
    """
    if not engine_bridge.enabled():
        return {}, "the Mastery Engine bridge isn't configured"
    out: dict[str, dict] = {}
    errors: list[str] = []
    for i in range(0, len(emails), ENGINE_BATCH):
        chunk = emails[i:i + ENGINE_BATCH]
        status, data, err = engine_bridge.call(
            "team-progress", "/api/internal/team-progress",
            params={"emails": ",".join(chunk), "days": days},
            timeout=engine_bridge.TEAM_TIMEOUT,
        )
        if status != 200 or not isinstance(data, dict):
            errors.append(err or f"the Mastery Engine answered {status}")
            continue
        for person in data.get("people") or []:
            email = str(person.get("email") or "").strip().lower()
            if email:
                out[email] = person
    return out, ("; ".join(dict.fromkeys(errors)) if errors else "")


# --- the rollup --------------------------------------------------------------


def _row(user: User, team_name: str | None, engine: dict | None, days: int, *,
         deadlines: dict[str, str | None], targets: list[PhysicalGoal],
         active_goals: dict[str, int], present: bool, late: bool, gym_week: int) -> dict:
    found = bool(engine and engine.get("found"))
    programs = list(engine.get("programs") or []) if found else []
    activity = (engine or {}).get("activity") or {}

    dims: dict[str, dict] = {}
    for dim in GROWTH_DIMENSIONS:
        if dim == DIM_PHYSICAL:
            # No engine program. The ring is the mean progress across the target PRs being chased,
            # paused ones excluded — identical to growth.js's physical branch.
            live = [t for t in targets if t.status != "paused"]
            actual = (sum(physical_goal_progress(t) for t in live) / len(live)) if live else None
            dims[dim] = {
                "actual": round(actual, 1) if actual is not None else None,
                # Nothing timestamps a PR, so there is no rate to report. See the module docstring.
                "velocity": None,
                "measurable": False,
                "targets": len(live),
                "deadline": deadlines.get(dim),
                "active_goals": active_goals.get(dim, 0),
            }
            continue
        mine = _programs_for_dim(programs, dim)
        actual = _weighted_pct(mine) if found else None
        dims[dim] = {
            "actual": round(actual, 1) if actual is not None else None,
            "velocity": _velocity(mine, days) if found else None,
            "measurable": bool(found and mine),
            "programs": len(mine),
            "deadline": deadlines.get(dim),
            "active_goals": active_goals.get(dim, 0),
        }

    overall = _weighted_pct(programs) if found else None
    return {
        "user": user_public(user),
        "team": team_name,
        # `found` false means the engine had nothing to say about this person — an unknown, which
        # the UI must render as "—". It is NOT the same as an engine score of zero.
        "engine": {
            "found": found,
            "error": (engine or {}).get("error") or "",
            # Attempts the engine couldn't attribute to a current catalog topic (a topic re-filed
            # inside the window). Velocity then reads slightly low, so say it out loud.
            "unmatched": activity.get("unmatched") or 0,
        },
        "dimensions": dims,
        "overall": round(overall, 1) if overall is not None else None,
        "velocity": _velocity(programs, days) if found else None,
        "streak": activity.get("streak") or 0,
        "active_days": activity.get("activeDays") or 0,
        "attempts": activity.get("attempts") or 0,
        "last_active": activity.get("lastActive"),
        "present_today": present,
        "late_today": late,
        "gym_week": gym_week,
    }


def team_rows(db: Session, viewer: User, days: int = DEFAULT_WINDOW_DAYS,
              refresh: bool = False) -> dict:
    """The whole panel's payload. Cached for CACHE_TTL_SECONDS per (viewer scope, window)."""
    people = visible_users(db, viewer)
    ids = tuple(u.id for u in people)
    key = (ids, days)
    if not refresh:
        hit = _cache.get(key)
        if hit and (time.time() - hit[0]) < CACHE_TTL_SECONDS:
            return {**hit[1], "cached": True}

    payload = _build(db, people, days)
    # A plain dict write under the GIL. Two admins refreshing at the same instant may both fetch;
    # that costs one extra engine round trip and cannot corrupt anything, which is a better trade
    # than holding a lock across a 30s network call.
    _cache[key] = (time.time(), payload)
    return {**payload, "cached": False}


def _build(db: Session, people: list[User], days: int) -> dict:
    if not people:
        return {"days": days, "generated_at": to_ph(utcnow()).isoformat(), "engine_error": "",
                "rows": []}

    ids = [u.id for u in people]
    by_email, engine_error = fetch_engine([(u.email or "").strip().lower() for u in people], days)

    teams = {t.id: t.name for t in db.execute(select(Team)).scalars()}

    # Everything below is ONE query per fact, keyed by user id — a per-person loop of queries here
    # would be a dozen round trips per dashboard load for data the panel shows all at once.
    deadlines: dict[int, dict[str, str | None]] = {}
    for area in db.execute(select(DevelopmentArea).where(DevelopmentArea.user_id.in_(ids))).scalars():
        deadlines.setdefault(area.user_id, {})[area.dimension] = (
            area.deadline.isoformat() if area.deadline else None
        )

    targets: dict[int, list[PhysicalGoal]] = {}
    for goal in db.execute(select(PhysicalGoal).where(PhysicalGoal.user_id.in_(ids))).scalars():
        targets.setdefault(goal.user_id, []).append(goal)

    goals: dict[int, dict[str, int]] = {}
    for goal in db.execute(
        select(ProfessionalGoal).where(ProfessionalGoal.user_id.in_(ids),
                                       ProfessionalGoal.status == "active")
    ).scalars():
        # Legacy rows predate `dimension` and read as professional — the same fallback growth.js
        # applies in `dimOf`, so the ring's "N active goals" and this column agree.
        dim = goal.dimension if goal.dimension in GROWTH_DIMENSIONS else DIM_PROFESSIONAL
        per = goals.setdefault(goal.user_id, {})
        per[dim] = per.get(dim, 0) + 1

    today = today_ph()
    present: dict[int, DailyAttendanceSummary] = {
        s.user_id: s for s in db.execute(
            select(DailyAttendanceSummary).where(
                DailyAttendanceSummary.date == today,
                DailyAttendanceSummary.user_id.in_(ids),
            )
        ).scalars()
    }

    week_start = today - timedelta(days=today.weekday())
    gym: dict[int, int] = {}
    for log in db.execute(
        select(GymLog).where(GymLog.date >= week_start, GymLog.user_id.in_(ids))
    ).scalars():
        if log.status == GYM_COMPLETED:
            gym[log.user_id] = gym.get(log.user_id, 0) + 1

    rows = []
    for user in people:
        summary = present.get(user.id)
        rows.append(_row(
            user,
            teams.get(user.team_id),
            by_email.get((user.email or "").strip().lower()),
            days,
            deadlines=deadlines.get(user.id, {}),
            targets=targets.get(user.id, []),
            active_goals=goals.get(user.id, {}),
            present=bool(summary and summary.clock_in),
            late=bool(summary and summary.status == "Late"),
            gym_week=gym.get(user.id, 0),
        ))

    return {
        "days": days,
        "generated_at": to_ph(utcnow()).isoformat(),
        # Empty when every chunk answered. Non-empty means some rows are UNKNOWN, not zero.
        "engine_error": engine_error,
        "rows": rows,
    }

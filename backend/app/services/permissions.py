"""Resolving a role's capabilities: coded defaults + the Super Admin's stored deltas.

`app/capabilities.py` owns the registry and the invariants; `models.RoleCapability` stores the
deltas; this module is the only thing that reads them together, and `security.require_cap` is the
only thing that reads this module on the request path.

🔴 **THE CACHE IS PER-PROCESS AND SENTINEL RUNS UP TO THREE INSTANCES.**

`require_cap` runs on every guarded request, so resolving from the DB each time would add a SELECT
to a large share of all traffic on a shared-core `db-f1-micro` (see AGENTS.md §5, "the board has a
QUERY BUDGET"). So the resolved matrix is cached in-process — which means a **revoke** made on
instance A is not seen by instances B and C until their own cache expires. That is a real window
and it is why the TTL is short and configurable rather than "until boot":

- `invalidate()` is called by every write in this module, so the operator who just unticked a box
  sees it immediately on their next request **if it lands on the same instance**.
- `PERMISSIONS_CACHE_SECONDS` (default 15) bounds the window everywhere else. Set it to `0` to
  disable caching entirely, which is the right move if permissions ever become the kind of thing
  that gets revoked in an emergency.
- 🔴 **The console's own read (`matrix`) bypasses the cache.** An operator who saves a change and
  is shown the pre-save grid concludes the save failed and does it again; a permissions console
  that lies about its own state is worse than a slow one.

The window is documented in the console UI too, for the same reason `gym.logs_shared` is stated
rather than implied: a gap somebody knows about is a nuisance, a gap nobody knows about is a bug.
"""
from __future__ import annotations

import json
import logging
import threading
import time

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..capabilities import (
    ALL_CAP_KEYS,
    BY_KEY,
    CAPABILITIES,
    GROUPS,
    default_caps,
    effective_caps,
    is_grantable,
)
from ..config import settings
from ..constants import ALL_ROLES, ROLE_LABELS, ROLE_SUPER_ADMIN
from ..utils.time import to_ph
from ..models import AuditLog, RoleCapability, User, UserCapability
from . import audit

log = logging.getLogger(__name__)

# Resolved {role: frozenset[cap]} plus the wall-clock time it was built. `None` = nothing cached.
_CACHE: dict[str, frozenset[str]] | None = None
# Per-person exceptions ({user_id: {cap: allowed}}), cached alongside and expiring with `_CACHE`.
_USER_CACHE: dict[int, dict[str, bool]] | None = None
_CACHE_AT: float = 0.0
# Serialises cache refills so a cold cache cannot burst the connection pool — see `resolved`.
_REFRESH_LOCK = threading.Lock()


def _ttl() -> float:
    return float(getattr(settings, "permissions_cache_seconds", 15) or 0)


def invalidate() -> None:
    """Drop the cached matrix. Called by every write here; safe to call at any time."""
    global _CACHE, _USER_CACHE, _CACHE_AT
    _CACHE = None
    _USER_CACHE = None
    _CACHE_AT = 0.0


def stored_overrides(db: Session) -> dict[str, dict[str, bool]]:
    """Every stored delta as {role: {capability: allowed}}. Reads the table directly, no cache."""
    out: dict[str, dict[str, bool]] = {}
    for row in db.execute(select(RoleCapability)).scalars():
        out.setdefault(row.role, {})[row.capability] = bool(row.allowed)
    return out


def stored_user_overrides(db: Session) -> dict[int, dict[str, bool]]:
    """Every per-person delta as {user_id: {capability: allowed}}. Reads the table directly."""
    out: dict[int, dict[str, bool]] = {}
    for row in db.execute(select(UserCapability)).scalars():
        out.setdefault(row.user_id, {})[row.capability] = bool(row.allowed)
    return out


def _resolve(db: Session) -> dict[str, frozenset[str]]:
    global _USER_CACHE
    overrides = stored_overrides(db)
    _USER_CACHE = stored_user_overrides(db)
    return {role: effective_caps(role, overrides.get(role)) for role in ALL_ROLES}


def resolved() -> dict[str, frozenset[str]]:
    """{role: frozenset[capability]} for every role, cached for `_ttl()` seconds.

    🔴 **Takes no session, deliberately — it opens its own on a cache miss.** The callers that
    matter most are `services/task_perms`, whose predicates are `(user, task)` and are invoked from
    ~67 places plus `serializers.task_card` (once per card on the board). Threading a `Session`
    through all of them to answer a question about a seven-row table would be a far larger and more
    dangerous change than the feature is worth, and `task_card` taking a new per-card read is exactly
    what the query-budget section of AGENTS.md §5 forbids. Cached, this costs ONE query per process
    per TTL.

    🔴 **A failed read falls back to the CODED DEFAULTS and is not cached.** Denying everything
    would take the whole app down over a blip on a table almost nobody has rows in; allowing
    everything is unthinkable. Falling back to what the code ships with keeps Sentinel usable and
    self-heals on the very next call, at the cost of a stored override being briefly ignored — and
    if this table is unreadable, the DB is down and every other endpoint is failing anyway.
    """
    global _CACHE, _CACHE_AT
    ttl = _ttl()
    if _CACHE is not None and ttl > 0 and (time.monotonic() - _CACHE_AT) < ttl:
        return _CACHE
    from ..database import SessionLocal

    # 🔴 ONE refresher at a time. Every endpoint is a sync `def`, so FastAPI runs them in anyio's
    # 40-thread pool while SQLAlchemy holds 5+15 connections (AGENTS.md §5, "the connection pool and
    # --max-instances are ONE decision"). Without this lock a cold cache — a fresh instance, or the
    # tick after any write — lets every in-flight thread open a SECOND session at the same moment for
    # the same tiny SELECT, on top of the one its request already holds. That is a burst the pool is
    # not sized for, and it would show up as `pool_timeout` on unrelated endpoints.
    with _REFRESH_LOCK:
        # Re-check inside the lock: whoever was ahead of us has just refilled it, and paying for the
        # same query again is exactly what the lock is here to prevent.
        if _CACHE is not None and ttl > 0 and (time.monotonic() - _CACHE_AT) < ttl:
            return _CACHE
        return _refresh(SessionLocal, ttl)


def _refresh(SessionLocal, ttl: float) -> dict[str, frozenset[str]]:
    global _CACHE, _CACHE_AT
    session = None
    try:
        session = SessionLocal()
        fresh = _resolve(session)
    except Exception as exc:  # noqa: BLE001 - see the docstring: never take the app down for this
        log.warning("permissions: falling back to coded defaults (%s)", exc)
        globals()["_USER_CACHE"] = {}
        return {role: default_caps(role) for role in ALL_ROLES}
    finally:
        if session is not None:
            session.close()
    if ttl > 0:
        _CACHE = fresh
        _CACHE_AT = time.monotonic()
    else:
        # TTL 0 = resolve every time; the user layer must not be left holding a stale dict.
        _CACHE = None
    return fresh


def caps_for(role: str) -> frozenset[str]:
    """The capabilities `role` currently holds, before any per-person exception."""
    return resolved().get(role, frozenset())


def user_overrides() -> dict[int, dict[str, bool]]:
    """{user_id: {capability: allowed}} — every per-person exception, cached with the role matrix.

    Shares `_CACHE_AT` and the same TTL: they are read together on every capability question, so
    caching them separately would double the query count and let the two layers disagree mid-request.
    """
    global _USER_CACHE, _CACHE_AT
    ttl = _ttl()
    if _USER_CACHE is not None and ttl > 0 and (time.monotonic() - _CACHE_AT) < ttl:
        return _USER_CACHE
    resolved()  # populates both caches together
    return _USER_CACHE if _USER_CACHE is not None else {}


def caps_for_user(user: User) -> frozenset[str]:
    """What THIS PERSON may do: their role's capabilities, then their own exceptions on top.

    🔴 Every per-person row is re-checked against `is_grantable` FOR THEIR ROLE. A user override is
    an exception to a role's defaults, never an exception to the invariants — so it cannot give a
    viewer a write, cannot touch a locked capability, and is inert for a Super Admin (who holds
    everything already).
    """
    caps = set(caps_for(user.role))
    for cap_key, allowed in (user_overrides().get(user.id) or {}).items():
        ok, _ = is_grantable(user.role, cap_key)
        if not ok:
            continue
        if allowed:
            caps.add(cap_key)
        else:
            caps.discard(cap_key)
    return frozenset(caps)


def has_cap(user: User | None, cap_key: str) -> bool:
    """Does `user` hold `cap_key`? The one question `require_cap` and every task predicate asks.

    🔴 An UNKNOWN capability key is False, never True. A guard naming a capability that no longer
    exists must close the endpoint, not open it — a typo in a `require_cap` should read as "nobody
    can do this any more", which somebody reports within the hour, rather than as "everybody can".
    """
    if user is None or not getattr(user, "is_active", False):
        return False
    if cap_key not in ALL_CAP_KEYS:
        return False
    return cap_key in caps_for_user(user)


# ---------------- The console's read ----------------
def matrix(db: Session) -> dict:
    """Everything the Permissions console renders, in one payload.

    🔴 Resolves from the DB directly rather than through `resolved()` — see the module docstring:
    the console must never show a grid older than the save the operator just made.
    """
    overrides = stored_overrides(db)
    roles = [
        {
            "value": r,
            "label": ROLE_LABELS.get(r, r),
            # The console renders this column read-only and says why, rather than letting somebody
            # tick boxes that `effective_caps` would then ignore.
            "immutable": r == ROLE_SUPER_ADMIN,
        }
        for r in ALL_ROLES
    ]
    caps = []
    for cap in CAPABILITIES:
        row = {
            "key": cap.key,
            "label": cap.label,
            "group": cap.group,
            "description": cap.description,
            "write": cap.write,
            "locked": cap.locked,
            "roles": {},
        }
        for r in ALL_ROLES:
            ok, reason = is_grantable(r, cap.key)
            row["roles"][r] = {
                "allowed": cap.key in effective_caps(r, overrides.get(r)),
                "default": cap.key in default_caps(r),
                "editable": ok,
                # Present only when a box is disabled, so the UI always has the sentence to show.
                "reason": reason,
            }
        caps.append(row)
    return {
        "groups": list(GROUPS),
        "roles": roles,
        "capabilities": caps,
        # How many deviations from the shipped defaults are in force — what "Reset to defaults"
        # would clear, and the number the console leads with.
        "override_count": sum(len(v) for v in overrides.values()),
        "cache_seconds": int(_ttl()),
    }


# ---------------- The console's writes ----------------
def set_overrides(db: Session, actor: User, changes: list[dict]) -> dict:
    """Apply `[{role, capability, allowed}, …]`, audit-logging each accepted change.

    Returns `{"applied": [...], "refused": [{..., "reason": str}]}`.

    🔴 **A refusal is REPORTED, never silently dropped.** A console that accepts a click it did not
    honour teaches the operator that the grid means nothing — the same lie as the "shared with the
    client" flag that pointed at nothing (AGENTS.md §2). The UI re-renders from the response, so a
    refused box visibly springs back with the reason attached.

    A change that restores a capability to its coded default DELETES the row rather than storing
    `allowed=<default>`, so the table stays a list of decisions somebody actually made — see
    `models.RoleCapability`.
    """
    applied: list[dict] = []
    refused: list[dict] = []
    # ONE snapshot, taken before anything is written. Re-reading inside the loop would compare each
    # change against a table the previous iteration had already modified, so a batch touching the
    # same cell twice would report the wrong "changed" and mis-log the audit trail.
    before_all = stored_overrides(db)
    for change in changes:
        role = str(change.get("role") or "")
        cap_key = str(change.get("capability") or "")
        allowed = bool(change.get("allowed"))
        ok, reason = is_grantable(role, cap_key)
        if not ok:
            refused.append({"role": role, "capability": cap_key, "allowed": allowed, "reason": reason})
            continue
        existing = db.get(RoleCapability, {"role": role, "capability": cap_key})
        is_default = allowed == (cap_key in default_caps(role))
        before = cap_key in effective_caps(role, before_all.get(role))
        if is_default:
            if existing is not None:
                db.delete(existing)
        elif existing is None:
            db.add(RoleCapability(role=role, capability=cap_key, allowed=allowed,
                                  updated_by_id=actor.id))
        else:
            existing.allowed = allowed
            existing.updated_by_id = actor.id
        applied.append({"role": role, "capability": cap_key, "allowed": allowed,
                        "is_default": is_default, "changed": before != allowed})
    db.commit()
    invalidate()
    # One audit row per accepted change, not one per request: the audit log is read to answer "who
    # gave Admin the payroll console", and a batched blob makes that a grep through JSON.
    for a in applied:
        if not a["changed"]:
            continue
        audit.record(
            db,
            actor_id=actor.id,
            table_name="role_capabilities",
            record_id=f"{a['role']}:{a['capability']}",
            action="update",
            old={"allowed": not a["allowed"]},
            new={"allowed": a["allowed"], "is_default": a["is_default"]},
        )
    return {"applied": applied, "refused": refused}


def reset(db: Session, actor: User) -> int:
    """Delete every override, returning the whole estate to the coded defaults. Returns the count."""
    rows = list(db.execute(select(RoleCapability)).scalars())
    if not rows:
        return 0
    detail = [{"role": r.role, "capability": r.capability, "allowed": bool(r.allowed)} for r in rows]
    db.execute(delete(RoleCapability))
    db.commit()
    invalidate()
    audit.record(db, actor_id=actor.id, table_name="role_capabilities", record_id="*",
                 action="reset", old={"overrides": detail}, new={"overrides": []})
    return len(rows)


# ---------------- Per-person exceptions ----------------
def people_with_overrides(db: Session) -> list[dict]:
    """Everyone holding at least one per-person exception, for the console's People tab.

    🔴 Rows that are no longer grantable for that person's role are STILL LISTED, marked `inert`.
    They are being ignored at resolution time, and a permission that silently does nothing is
    exactly what an operator needs to see in order to delete it — hiding it would leave a row nobody
    can explain in a table nobody can find.
    """
    rows = stored_user_overrides(db)
    if not rows:
        return []
    users = {u.id: u for u in db.execute(select(User).where(User.id.in_(rows.keys()))).scalars()}
    out = []
    for uid, caps in sorted(rows.items()):
        u = users.get(uid)
        if u is None:
            continue
        out.append({
            "user_id": uid, "name": u.name, "email": u.email, "role": u.role,
            "role_label": ROLE_LABELS.get(u.role, u.role),
            "caps": [
                {"capability": k,
                 "label": BY_KEY[k].label if k in BY_KEY else k,
                 "allowed": v,
                 "inert": not is_grantable(u.role, k)[0],
                 "reason": is_grantable(u.role, k)[1]}
                for k, v in sorted(caps.items())
            ],
        })
    return out


def user_matrix(db: Session, user: User) -> dict:
    """One person's effective capabilities, and which of them are exceptions to their role."""
    role_caps = caps_for(user.role)
    mine = stored_user_overrides(db).get(user.id, {})
    effective = caps_for_user(user)
    caps = []
    for cap in CAPABILITIES:
        ok, reason = is_grantable(user.role, cap.key)
        caps.append({
            "key": cap.key, "label": cap.label, "group": cap.group,
            "description": cap.description, "write": cap.write, "locked": cap.locked,
            "from_role": cap.key in role_caps,
            "override": mine.get(cap.key),
            "allowed": cap.key in effective,
            "editable": ok, "reason": reason,
        })
    return {
        "user": {"id": user.id, "name": user.name, "email": user.email,
                 "role": user.role, "role_label": ROLE_LABELS.get(user.role, user.role)},
        "groups": list(GROUPS), "capabilities": caps, "override_count": len(mine),
    }


def set_user_overrides(db: Session, actor: User, target: User, changes: list[dict]) -> dict:
    """Apply `[{capability, allowed}, ...]` for ONE person. Same contract as `set_overrides`.

    A change that matches what the person's ROLE already gives them deletes the row: an exception
    that is not an exception is noise, and it would silently stop following the role if the role
    later moved.
    """
    applied, refused = [], []
    role_caps = caps_for(target.role)
    existing = stored_user_overrides(db).get(target.id, {})
    before = caps_for_user(target)
    for change in changes:
        cap_key = str(change.get("capability") or "")
        allowed = bool(change.get("allowed"))
        ok, reason = is_grantable(target.role, cap_key)
        if not ok:
            refused.append({"capability": cap_key, "allowed": allowed, "reason": reason})
            continue
        row = db.get(UserCapability, {"user_id": target.id, "capability": cap_key})
        matches_role = allowed == (cap_key in role_caps)
        if matches_role:
            if row is not None:
                db.delete(row)
        elif row is None:
            db.add(UserCapability(user_id=target.id, capability=cap_key, allowed=allowed,
                                  updated_by_id=actor.id))
        else:
            row.allowed = allowed
            row.updated_by_id = actor.id
        applied.append({"capability": cap_key, "allowed": allowed,
                        "matches_role": matches_role,
                        "changed": (cap_key in before) != allowed})
    db.commit()
    invalidate()
    for a in applied:
        if not a["changed"] and a["capability"] not in existing:
            continue
        audit.record(db, actor_id=actor.id, table_name="user_capabilities",
                     record_id=f"{target.id}:{a['capability']}", action="update",
                     old={"allowed": not a["allowed"]},
                     new={"allowed": a["allowed"], "matches_role": a["matches_role"],
                          "user": target.email})
    return {"applied": applied, "refused": refused}


def clear_user_overrides(db: Session, actor: User, target: User) -> int:
    """Drop every exception for one person, returning them to exactly what their role gives."""
    rows = list(db.execute(
        select(UserCapability).where(UserCapability.user_id == target.id)).scalars())
    if not rows:
        return 0
    detail = [{"capability": r.capability, "allowed": bool(r.allowed)} for r in rows]
    db.execute(delete(UserCapability).where(UserCapability.user_id == target.id))
    db.commit()
    invalidate()
    audit.record(db, actor_id=actor.id, table_name="user_capabilities",
                 record_id=str(target.id), action="reset",
                 old={"overrides": detail, "user": target.email}, new={"overrides": []})
    return len(rows)


def prune_orphans(db: Session, user_id: int) -> None:
    """Delete a departing person's exceptions. Called by `people.delete_person`.

    Neither capability table carries an FK (see the models for why), so nothing removes these
    automatically — and a row keyed by a recycled id would silently hand a future person somebody
    else's exceptions.
    """
    db.execute(delete(UserCapability).where(UserCapability.user_id == user_id))


# ---------------- The audit trail, filtered to permission changes ----------------
def recent_changes(db: Session, limit: int = 40) -> list[dict]:
    """The last N permission edits, newest first — role and per-person together.

    The audit log already records these; this is those rows filtered to the two tables and resolved
    to names, so the console can answer "who gave Admin the payroll console" without somebody going
    to Settings and knowing which table name to filter on.
    """
    rows = db.execute(
        select(AuditLog)
        .where(AuditLog.table_name.in_(("role_capabilities", "user_capabilities")))
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
    ).scalars().all()
    ids = {a.actor_id for a in rows if a.actor_id}
    actors = {}
    if ids:
        actors = {u.id: u.name for u in db.execute(select(User).where(User.id.in_(ids))).scalars()}
    out = []
    for a in rows:
        new = json.loads(a.new_value_json) if a.new_value_json else {}
        out.append({
            "id": a.id,
            "actor": actors.get(a.actor_id) or "system",
            "scope": "person" if a.table_name == "user_capabilities" else "role",
            "target": a.record_id,
            "label": new.get("user") or a.record_id,
            "action": a.action,
            "allowed": new.get("allowed"),
            "at": to_ph(a.created_at).isoformat(),
        })
    return out

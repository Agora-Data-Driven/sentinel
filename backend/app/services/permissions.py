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

import time

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..capabilities import (
    ALL_CAP_KEYS,
    CAPABILITIES,
    GROUPS,
    default_caps,
    effective_caps,
    is_grantable,
)
from ..config import settings
from ..constants import ALL_ROLES, ROLE_LABELS, ROLE_SUPER_ADMIN
from ..models import RoleCapability, User
from . import audit

# Resolved {role: frozenset[cap]} plus the wall-clock time it was built. `None` = nothing cached.
_CACHE: dict[str, frozenset[str]] | None = None
_CACHE_AT: float = 0.0


def _ttl() -> float:
    return float(getattr(settings, "permissions_cache_seconds", 15) or 0)


def invalidate() -> None:
    """Drop the cached matrix. Called by every write here; safe to call at any time."""
    global _CACHE, _CACHE_AT
    _CACHE = None
    _CACHE_AT = 0.0


def stored_overrides(db: Session) -> dict[str, dict[str, bool]]:
    """Every stored delta as {role: {capability: allowed}}. Reads the table directly, no cache."""
    out: dict[str, dict[str, bool]] = {}
    for row in db.execute(select(RoleCapability)).scalars():
        out.setdefault(row.role, {})[row.capability] = bool(row.allowed)
    return out


def _resolve(db: Session) -> dict[str, frozenset[str]]:
    overrides = stored_overrides(db)
    return {role: effective_caps(role, overrides.get(role)) for role in ALL_ROLES}


def resolved(db: Session) -> dict[str, frozenset[str]]:
    """{role: frozenset[capability]} for every role, cached for `_ttl()` seconds."""
    global _CACHE, _CACHE_AT
    ttl = _ttl()
    if _CACHE is not None and ttl > 0 and (time.monotonic() - _CACHE_AT) < ttl:
        return _CACHE
    fresh = _resolve(db)
    if ttl > 0:
        _CACHE = fresh
        _CACHE_AT = time.monotonic()
    return fresh


def caps_for(db: Session, role: str) -> frozenset[str]:
    """The capabilities `role` currently holds. An unknown role holds nothing."""
    return resolved(db).get(role, frozenset())


def has_cap(db: Session, user: User | None, cap_key: str) -> bool:
    """Does `user` hold `cap_key`? The one question `require_cap` asks.

    🔴 An UNKNOWN capability key is False, never True. A guard naming a capability that no longer
    exists must close the endpoint, not open it — a typo in a `require_cap` should read as "nobody
    can do this any more", which somebody reports within the hour, rather than as "everybody can".
    """
    if user is None or not getattr(user, "is_active", False):
        return False
    if cap_key not in ALL_CAP_KEYS:
        return False
    return cap_key in caps_for(db, user.role)


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

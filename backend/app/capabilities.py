"""Named CAPABILITIES — "what may this role do", as data instead of 41 hand-written role gates.

Until 2026-08-17 the answer to "what exactly can an Account Manager do here?" existed only as
~41 `require_min_role` / `require_roles` call sites spread over nine routers plus ~30 inline
`user.role == …` comparisons. Nobody — including the person who wrote them — could answer it
without reading all nine. This module is that answer in one place, and it is the thing the
Super Admin's Permissions console reads and writes.

## The split that decides what belongs here

Sentinel has two kinds of permission and only ONE of them is a matrix:

| | Example | Lives |
|---|---|---|
| **Surface access** — role → yes/no | "may open Payroll", "may approve leave" | HERE |
| **Object-scoped rules** — role → yes/no *about this row* | "an employee may edit a task **if they are assigned to it or it is in their team's queue**" | `services/task_perms.py`, and it stays there |

🔴 **Do not migrate `task_perms` into this file.** There is no cell in a role × capability grid
for "assigned only": the second kind needs the task, the user's departments, who created it and
who is named on which step. Forcing it in would either drop that nuance (handing every employee
edit rights over every colleague's card — the exact regression AGENTS.md §5 documents) or turn a
console a human is meant to reason about into a rules engine nobody can read. A capability that
cannot be decided from the role ALONE does not belong here.

## The defaults are a MECHANICAL translation of the guards they replaced

Every `default=` below is the set of roles that satisfied the *original* gate, derived the same
way the original derived it — `_at_least(X)` where the code said `require_min_role(X)`, an
explicit set where it said `require_roles(...)`. That is deliberate: switching 41 endpoints over
to a new mechanism is only safe if the new mechanism provably answers what the old one answered,
and `tests/test_permissions.py` re-derives every one of these from `ROLE_RANK` so a typo here
fails the suite rather than silently opening or closing an endpoint.

## Three invariants that survive the console (`is_grantable`)

1. 🔴 **`super_admin` holds every capability, always, and cannot be edited.** The console is
   reached through a capability; a grid that can revoke it is a grid that can lock the last
   Super Admin out of their own permissions page with no way back in but a DB client.
2. 🔴 **`locked` capabilities are not editable by anyone.** These are the privilege-escalation
   ones (`people.set_role`, `people.create`, `people.delete`) and the console's own
   (`permissions.manage`). Granting an Admin the ability to write the `role` column is granting
   them Super Admin — see the `people.set_role` note below for the hole this closed.
3. 🔴 **`viewer` can never hold a `write` capability.** It is a read-only seat that is
   deliberately OFF the rank ladder (`constants.ROLE_VIEWER`, decision D8) — its floor rank is
   what stops `require_min_role` handing it a write, and this is the same rule for the console.
   One checkbox is otherwise all it takes to undo that whole design.

`effective_caps` re-checks all three at RESOLUTION time, not just at write time, so a row that
reaches `role_capabilities` some other way (a hand-run `INSERT`, a restored backup, a future bug
in the write path) is **inert** rather than obeyed.
"""
from __future__ import annotations

from dataclasses import dataclass

from .constants import (
    ALL_ROLES,
    ROLE_ACCOUNT_MANAGER,
    ROLE_ADMIN,
    ROLE_RANK,
    ROLE_SUPER_ADMIN,
    ROLE_TEAM_LEAD,
    ROLE_VIEWER,
)


def _at_least(minimum: str) -> frozenset[str]:
    """The roles `require_min_role(minimum)` admitted — the same `ROLE_RANK` comparison it made.

    Derived rather than typed out so it can never drift from the ladder. Note this correctly
    EXCLUDES `viewer`, whose rank is the floor (1) precisely so no rank gate reaches it.
    """
    floor = ROLE_RANK[minimum]
    return frozenset(r for r in ALL_ROLES if ROLE_RANK.get(r, 0) >= floor)


# The set `routers/tasks.py` spelled as `AM_PLUS` — an Account Manager and up.
_AM_PLUS = frozenset({ROLE_ACCOUNT_MANAGER, ROLE_ADMIN, ROLE_SUPER_ADMIN})
_SA_ONLY = frozenset({ROLE_SUPER_ADMIN})


@dataclass(frozen=True)
class Capability:
    """One named thing a role may or may not do, plus the metadata the console renders.

    `write` is what keeps `viewer` honest: it means "doing this changes something", so a viewer
    may never hold it. Reads are `write=False` and ARE grantable to a viewer — that is the seat's
    entire purpose. Default `True` because the safe mistake is refusing a viewer a read, not
    handing them a write.

    `locked` means the capability is fixed in code and the console renders it read-only.
    """

    key: str
    label: str
    group: str
    description: str
    default: frozenset[str]
    write: bool = True
    locked: bool = False


CAPABILITIES: tuple[Capability, ...] = (
    # ---------------- People ----------------
    Capability(
        key="people.edit",
        label="Edit employee records",
        group="People",
        description="Change a colleague's name, email, department, shift, phone, hire date or password.",
        default=_at_least(ROLE_ADMIN),
    ),
    Capability(
        key="people.badge",
        label="View and reissue attendance badges",
        group="People",
        description=(
            "See or reprint somebody's QR badge and its typeable code, and issue a replacement."
        ),
        # A badge code PUNCHES that person's attendance, so this is a write however much it looks
        # like a read — which is also why a viewer must never hold it.
        default=_at_least(ROLE_ADMIN),
    ),
    Capability(
        key="people.create",
        label="Add a new employee",
        group="People",
        description="Create a staff account. Locked: the create form sets a role, so this grants role-setting.",
        default=_SA_ONLY,
        locked=True,
    ),
    Capability(
        key="people.delete",
        label="Delete an employee",
        group="People",
        description="Permanently remove an account and its attendance, gym, leave and notifications.",
        default=_SA_ONLY,
        locked=True,
    ),
    Capability(
        key="people.set_role",
        label="Change somebody's role",
        group="People",
        description="Write the `role` column. Locked: whoever can set a role can grant themselves Super Admin.",
        default=_SA_ONLY,
        locked=True,
    ),
    # ---------------- Payroll ----------------
    Capability(
        key="payroll.manage",
        label="Open and run payroll",
        group="Payroll",
        description="See salaries, make adjustments and finalise a payroll run.",
        default=_SA_ONLY,
    ),
    # ---------------- Attendance & Leave ----------------
    Capability(
        key="attendance.approvals",
        label="Approve attendance corrections",
        group="Attendance & Leave",
        description="Review and decide regularization and overtime requests.",
        default=_at_least(ROLE_TEAM_LEAD),
    ),
    Capability(
        key="attendance.records",
        label="See the attendance register",
        group="Attendance & Leave",
        description="Read everyone's daily attendance summaries, filtered by date and department.",
        default=_at_least(ROLE_TEAM_LEAD),
        write=False,
    ),
    Capability(
        key="attendance.edit_records",
        label="Edit an attendance record",
        group="Attendance & Leave",
        description="Correct a stored day summary by hand — clock times, status and paid hours.",
        default=_SA_ONLY,
    ),
    Capability(
        key="leave.approvals",
        label="Approve leave requests",
        group="Attendance & Leave",
        description="Read the leave queue and approve or reject a request.",
        default=_at_least(ROLE_TEAM_LEAD),
    ),
    # ---------------- Task board ----------------
    Capability(
        key="tasks.recurring",
        label="Manage recurring deliverables",
        group="Task board",
        description="Create, edit and run the retainer recurrences that mint cards on a schedule.",
        default=_AM_PLUS,
    ),
    Capability(
        key="tasks.adoption",
        label="Adopt Atrium client cards",
        group="Task board",
        description="Plan, apply and revert the bulk import of a client's cards into Sentinel rows.",
        default=_SA_ONLY,
    ),
    Capability(
        key="tasks.requests",
        label="Decide incoming task requests",
        group="Task board",
        description="See the task-request queue and accept or decline what a client or teammate raised.",
        default=_AM_PLUS,
    ),
    Capability(
        key="tasks.atrium_share",
        label="Publish work to a client",
        group="Task board",
        description="Send a card to Atrium, retry a failed share, and clear or audit an existing one.",
        default=_AM_PLUS,
    ),
    # ---------------- Growth & Gym ----------------
    Capability(
        key="growth.team",
        label="See everyone's growth",
        group="Growth & Gym",
        description="The cross-Agora growth table — each person's four dimensions, ranked by measured speed.",
        default=_at_least(ROLE_ADMIN),
        write=False,
    ),
    Capability(
        key="reading.canon",
        label="Edit the reading canon",
        group="Growth & Gym",
        description="Add, change and remove the company reading list everyone's progress is tracked against.",
        default=_at_least(ROLE_ADMIN),
    ),
    Capability(
        key="gym.rollup",
        label="See the gym rollup",
        group="Growth & Gym",
        description="Everyone's training compliance for a period, not just your own.",
        default=_at_least(ROLE_TEAM_LEAD),
        write=False,
    ),
    Capability(
        key="gym.edit_logs",
        label="Edit somebody's gym log",
        group="Growth & Gym",
        description="Change or delete another person's logged workout.",
        default=_SA_ONLY,
    ),
    # ---------------- System ----------------
    Capability(
        key="settings.view",
        label="See system settings",
        group="System",
        description="Read the company work hours, grace period, work days and timezone.",
        default=_at_least(ROLE_ADMIN),
        write=False,
    ),
    Capability(
        key="settings.edit",
        label="Change system settings",
        group="System",
        description="Edit work hours, late grace, break length, work days and timezone for everyone.",
        default=_at_least(ROLE_ADMIN),
    ),
    Capability(
        key="audit.view",
        label="Read the audit log",
        group="System",
        description="Every recorded change: who changed what, when, and from what to what.",
        default=_at_least(ROLE_ADMIN),
        write=False,
    ),
    Capability(
        key="announce.send",
        label="Send an announcement",
        group="System",
        description="Push a notification to every member of staff.",
        default=_at_least(ROLE_ADMIN),
    ),
    Capability(
        key="insights.view",
        label="See the insights dashboard",
        group="System",
        description="The cross-company attendance, task and growth rollups on the admin block.",
        default=_at_least(ROLE_ADMIN),
        write=False,
    ),
    Capability(
        key="manage.console",
        label="Open the Manage console",
        group="System",
        description=(
            "Edit the reference data behind the app: departments, shift templates, leave types, "
            "gym exercises, services and the task-board vocabulary."
        ),
        default=_SA_ONLY,
    ),
    Capability(
        key="system.run_daily",
        label="Run the daily processing pass",
        group="System",
        description=(
            "Trigger the attendance day-summaries, reminders, recurrences and client mirror by hand."
        ),
        default=_SA_ONLY,
    ),
    Capability(
        key="permissions.view",
        label="See the permissions matrix",
        group="System",
        description="Read which role holds which capability. Harmless on its own — editing is separate.",
        default=_SA_ONLY,
        write=False,
    ),
    Capability(
        key="permissions.manage",
        label="Edit the permissions matrix",
        group="System",
        description="Grant and revoke capabilities per role. Locked: a grid that can revoke this locks you out.",
        default=_SA_ONLY,
        locked=True,
    ),
)

BY_KEY: dict[str, Capability] = {c.key: c for c in CAPABILITIES}
ALL_CAP_KEYS: frozenset[str] = frozenset(BY_KEY)
# Stable render order for the console: groups in declaration order, capabilities within them too.
GROUPS: tuple[str, ...] = tuple(dict.fromkeys(c.group for c in CAPABILITIES))

# Every capability key is referenced by a guard somewhere. Kept as module constants so a router
# imports a name the type checker and a grep can both follow, rather than a bare string literal.
CAP_PEOPLE_EDIT = "people.edit"
CAP_PEOPLE_BADGE = "people.badge"
CAP_PEOPLE_CREATE = "people.create"
CAP_PEOPLE_DELETE = "people.delete"
CAP_PEOPLE_SET_ROLE = "people.set_role"
CAP_PAYROLL_MANAGE = "payroll.manage"
CAP_ATTENDANCE_APPROVALS = "attendance.approvals"
CAP_ATTENDANCE_RECORDS = "attendance.records"
CAP_ATTENDANCE_EDIT_RECORDS = "attendance.edit_records"
CAP_LEAVE_APPROVALS = "leave.approvals"
CAP_TASKS_RECURRING = "tasks.recurring"
CAP_TASKS_ADOPTION = "tasks.adoption"
CAP_TASKS_REQUESTS = "tasks.requests"
CAP_TASKS_ATRIUM_SHARE = "tasks.atrium_share"
CAP_GROWTH_TEAM = "growth.team"
CAP_READING_CANON = "reading.canon"
CAP_GYM_ROLLUP = "gym.rollup"
CAP_GYM_EDIT_LOGS = "gym.edit_logs"
CAP_SETTINGS_VIEW = "settings.view"
CAP_SETTINGS_EDIT = "settings.edit"
CAP_AUDIT_VIEW = "audit.view"
CAP_ANNOUNCE_SEND = "announce.send"
CAP_INSIGHTS_VIEW = "insights.view"
CAP_MANAGE_CONSOLE = "manage.console"
CAP_SYSTEM_RUN_DAILY = "system.run_daily"
CAP_PERMISSIONS_VIEW = "permissions.view"
CAP_PERMISSIONS_MANAGE = "permissions.manage"


def default_caps(role: str) -> frozenset[str]:
    """The capabilities `role` holds with no overrides stored — i.e. what the code ships with."""
    if role == ROLE_SUPER_ADMIN:
        return ALL_CAP_KEYS
    return frozenset(c.key for c in CAPABILITIES if role in c.default)


def is_grantable(role: str, cap_key: str) -> tuple[bool, str | None]:
    """May the console change `cap_key` for `role`? Returns (ok, reason-it-is-refused).

    The reason is rendered in the console as the tooltip on a disabled checkbox, so somebody who
    wonders why a box will not tick gets the answer in place instead of a silent no-op.
    """
    cap = BY_KEY.get(cap_key)
    if cap is None:
        return False, "That capability does not exist."
    if role not in ALL_ROLES:
        return False, "That role does not exist."
    if cap.locked:
        return False, "This capability is fixed in code and cannot be reassigned here."
    if role == ROLE_SUPER_ADMIN:
        return False, "Super Admin always holds every capability — that is what makes this console recoverable."
    if role == ROLE_VIEWER and cap.write:
        return False, "Viewer is a read-only seat: it can be given reads, never writes."
    return True, None


def effective_caps(role: str, overrides: dict[str, bool] | None = None) -> frozenset[str]:
    """`role`'s capabilities after applying its stored overrides.

    🔴 Every override is re-checked against `is_grantable` HERE, not only when it was written. A
    row that violates an invariant is dropped, so a hand-run INSERT, a restored backup or a future
    bug in the write path cannot hand a viewer a write or revoke a Super Admin's console.
    """
    if role == ROLE_SUPER_ADMIN:
        return ALL_CAP_KEYS
    caps = set(default_caps(role))
    for cap_key, allowed in (overrides or {}).items():
        ok, _ = is_grantable(role, cap_key)
        if not ok:
            continue
        if allowed:
            caps.add(cap_key)
        else:
            caps.discard(cap_key)
    return frozenset(caps)

"""Enumerations and shared constants used across models, schemas, and RBAC.

Kept as plain string constants (not Python Enums) so they serialize cleanly to JSON and store as
readable text in the DB — easy to eyeball in a SQLite browser.
"""
from __future__ import annotations

# --- Roles (ordered from most to least privileged) ------------------------
ROLE_SUPER_ADMIN = "super_admin"
ROLE_ADMIN = "admin"
ROLE_ACCOUNT_MANAGER = "account_manager"
ROLE_TEAM_LEAD = "team_lead"
ROLE_EMPLOYEE = "employee"
ROLE_INTERN = "intern"
# 🔴 A READ-ONLY MONITORING SEAT (decision D8, docs/TASKBOARD_REBUILD.md §5.3). It sees everything
# and writes nothing — for a founder, an auditor or a client-side observer who needs the whole board
# without being able to touch it.
#
# It does NOT slot into the ladder below, and that is the whole difficulty: give it a high rank and
# every `require_min_role` write endpoint opens; give it a low one and it cannot see the board. So
# its rank is deliberately the LOWEST (1) — no rank check can ever grant it a write — and the read
# surfaces name it EXPLICITLY (`VIEW_ALL_ROLES`). Never add it to MANAGER_ROLES or ADMIN_ROLES:
# those two gate approvals, exports and record edits, which are writes.
ROLE_VIEWER = "viewer"

ALL_ROLES = [
    ROLE_SUPER_ADMIN,
    ROLE_ADMIN,
    ROLE_ACCOUNT_MANAGER,
    ROLE_TEAM_LEAD,
    ROLE_EMPLOYEE,
    ROLE_INTERN,
    ROLE_VIEWER,
]

# Rank for "at least this role" checks. Higher = more power.
ROLE_RANK = {
    # Viewer sits at the FLOOR on purpose — see ROLE_VIEWER. Its power comes from being named in
    # VIEW_ALL_ROLES, never from out-ranking anybody.
    ROLE_VIEWER: 1,
    ROLE_INTERN: 1,
    ROLE_EMPLOYEE: 1,
    ROLE_TEAM_LEAD: 2,
    ROLE_ACCOUNT_MANAGER: 3,
    ROLE_ADMIN: 4,
    ROLE_SUPER_ADMIN: 5,
}

# Roles considered "admin or above" — can see everyone's data, manage records, export.
ADMIN_ROLES = {ROLE_ADMIN, ROLE_SUPER_ADMIN}
# Roles that can manage/approve people-facing requests (leave, overtime, regularization).
# 🔴 Never add ROLE_VIEWER here: approving is a write.
MANAGER_ROLES = {ROLE_ADMIN, ROLE_SUPER_ADMIN, ROLE_TEAM_LEAD, ROLE_ACCOUNT_MANAGER}
# Roles that may SEE every task and the cross-client rollup, whoever owns it. Read-only surfaces
# only — this set must never be used to authorise a write (that is what ADMIN_ROLES/FULL are for).
VIEW_ALL_ROLES = {ROLE_ADMIN, ROLE_SUPER_ADMIN, ROLE_ACCOUNT_MANAGER, ROLE_VIEWER}

ROLE_LABELS = {
    ROLE_SUPER_ADMIN: "Super Admin",
    ROLE_ADMIN: "Admin",
    ROLE_ACCOUNT_MANAGER: "Account Manager",
    # 🔴 The KEY stays `team_lead` forever (keys never change); the LABEL follows the org
    # chart — "Department Head" since 2026-09-02 (owner decision: one term everywhere).
    ROLE_TEAM_LEAD: "Department Head",
    ROLE_EMPLOYEE: "Employee",
    ROLE_INTERN: "Intern",
    ROLE_VIEWER: "Viewer (read-only)",
}

# --- Attendance ------------------------------------------------------------
ACTION_CLOCK_IN = "clock_in"
ACTION_CLOCK_OUT = "clock_out"
ACTION_BREAK_START = "break_start"
ACTION_BREAK_END = "break_end"
ATTENDANCE_ACTIONS = [ACTION_CLOCK_IN, ACTION_BREAK_START, ACTION_BREAK_END, ACTION_CLOCK_OUT]

STATUS_ON_TIME = "OnTime"
STATUS_LATE = "Late"
STATUS_ABSENT = "Absent"
STATUS_HALF_DAY = "HalfDay"
STATUS_MISSING_CLOCKOUT = "MissingClockOut"
STATUS_ON_LEAVE = "OnLeave"

# --- Growth (holistic development) ------------------------------------------
# The four growth dimensions the hub, its tabs, and the AI coach all organise by.
# Stored on professional_goals.dimension and development_areas.dimension.
# 'philosophical' replaced the original 'mental' on 2026-07-27 (data-migrated).
DIM_SPIRITUAL = "spiritual"
DIM_PROFESSIONAL = "professional"
DIM_PHILOSOPHICAL = "philosophical"
DIM_PHYSICAL = "physical"
GROWTH_DIMENSIONS = [DIM_SPIRITUAL, DIM_PROFESSIONAL, DIM_PHILOSOPHICAL, DIM_PHYSICAL]

# --- Gym -------------------------------------------------------------------
DAY_PUSH = "Push"
DAY_PULL = "Pull"
DAY_LEGS = "Legs"
DAY_CUSTOM = "Custom"
DAY_REST = "Rest"
GYM_DAY_TYPES = [DAY_PUSH, DAY_PULL, DAY_LEGS, DAY_CUSTOM]
# A planned day may also be a Rest day (never logged, just shown on the calendar).
GYM_PLAN_DAY_TYPES = GYM_DAY_TYPES + [DAY_REST]

# Weekday keys for the recurring weekly split (Mon-first, matching date.weekday()).
GYM_WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
# The split a brand-new user starts with — a classic PPL rotation with weekends off.
GYM_DEFAULT_WEEK = {
    "Mon": DAY_PUSH,
    "Tue": DAY_PULL,
    "Wed": DAY_LEGS,
    "Thu": DAY_PUSH,
    "Fri": DAY_PULL,
    "Sat": DAY_LEGS,
    "Sun": DAY_REST,
}

GYM_COMPLETED = "Completed"
GYM_INCOMPLETE = "Incomplete"
GYM_MISSING = "Missing"

SET_NORMAL = "Normal"
SET_WARMUP = "Warm-up"
SET_DROP = "Drop"
SET_FAILURE = "To failure"
SET_TYPES = [SET_NORMAL, SET_WARMUP, SET_DROP, SET_FAILURE]

# --- Tasks -----------------------------------------------------------------
TASK_TODO = "To Do"
TASK_IN_PROGRESS = "In Progress"
TASK_REVISION = "Revision Needed"
TASK_COMPLETED = "Completed"
# WP 1.2 (2026-08-04): the LABEL became "Parked". The key and the Atrium stage are both still
# `blocked` and must never move — this constant is the display string and nothing else, which is
# exactly why the name kept its `TASK_BLOCKED` spelling: renaming the symbol would read as though
# the identity had changed too. Existing boards are migrated by `task_config.rename_statuses`;
# nothing keys off this value (see `task_config.status_for_stage`), it is only the fallback label
# for a DB whose vocab table is empty.
TASK_BLOCKED = "Parked"
# "For Review" and "Waiting for Client" were REMOVED 2026-07-30 at the user's request — both only
# ever meant "blocked on someone", so they fold into Blocked. Atrium retired the matching stages
# first (2026-07-29, workspace._STAGE_ALIASES maps for_review/waiting_client -> blocked), so the two
# boards are back in step: a drag to "For Review" here used to land the client's card on Blocked
# there. Retiring one is not just a list edit — see task_config.RETIRED_STATUSES.
TASK_STATUSES = [
    TASK_TODO,
    TASK_IN_PROGRESS,
    TASK_REVISION,
    TASK_COMPLETED,
    TASK_BLOCKED,
]

# --- Review states (tasks.review_state, decision D5) -------------------------
# A review is a STATE on the task, not a board column: "For Review" was retired as a status on
# 2026-07-30 (both boards) and nothing replaced it, so "Done" was one person's unilateral claim.
# NULL/absent = never submitted. Approval gates entry into a completed-stage status.
REVIEW_PENDING = "pending"
REVIEW_APPROVED = "approved"
REVIEW_CHANGES = "changes_requested"
REVIEW_STATES = [REVIEW_PENDING, REVIEW_APPROVED, REVIEW_CHANGES]

PRIORITY_URGENT = "Urgent"
PRIORITY_MEDIUM = "Medium"
PRIORITY_LOW = "Low"
PRIORITIES = [PRIORITY_URGENT, PRIORITY_MEDIUM, PRIORITY_LOW]

# --- Where a task CAME FROM: planned ahead, or raised during the day (2026-08-11) -------------
#
# The two halves of the Sentinel task-placement guidelines. §1 gives the Team Lead the duty of
# placing PLANNED work before or at the start of the workday; §3 says anything that comes up
# afterwards is ADDED by whoever has to do it, "so Sentinel accurately reflects the actual work
# completed during the day". Without this field that sentence is unanswerable — every task looks
# identically planned, and the reactive load a team actually carries is invisible.
#
# 🔴 These are STAGE-style keys, not renameable labels. Unlike a status (`TaskVocabItem`, which is
# editable in Manage precisely because it is a label) this is a fixed pair the rollups count by —
# see task_vocab's docstring for what keying off a display string cost this board.
ORIGIN_PLANNED = "planned"
ORIGIN_ADDED = "added"

# --- Operating-system release (2026-09-02) -------------------------------------------------------
# WHY a parked card is waiting — structured, so the AM/COO can split "blocked by the client" from
# "blocked by us" without reading every hold reason. Keys are stored on `tasks.hold_kind`; labels are
# what the UI prints. 🔒 Internal like `hold_reason`: never crosses to the client.
HOLD_KINDS: dict[str, str] = {
    "client": "Waiting on client",
    "access": "Waiting for access",
    "asset": "Waiting for an asset",
    "am_decision": "Waiting for AM decision",
    "reviewer": "Waiting for reviewer",
    "task": "Waiting on another task",
    "other": "Other",
}
HOLD_KINDS_ON_US = {"access", "asset", "am_decision", "reviewer", "task", "other"}

# Worker STAGE — readiness, orthogonal to `role` (authority). Shadow → Contributor → Workstream
# Owner → Client Owner. Surfaced on cards and at assignment; a Contributor or Shadow leading live
# client work gets a reviewer flagged as required. Not enforced in v1.
STAGE_SHADOW = "shadow"
STAGE_CONTRIBUTOR = "contributor"
STAGE_WORKSTREAM_OWNER = "workstream_owner"
STAGE_CLIENT_OWNER = "client_owner"
WORKER_STAGES = [STAGE_SHADOW, STAGE_CONTRIBUTOR, STAGE_WORKSTREAM_OWNER, STAGE_CLIENT_OWNER]
STAGE_LABELS = {
    STAGE_SHADOW: "Shadow",
    STAGE_CONTRIBUTOR: "Contributor",
    STAGE_WORKSTREAM_OWNER: "Workstream Owner",
    STAGE_CLIENT_OWNER: "Client Owner",
}
# Stages that always need a reviewer on live client work.
STAGES_NEED_REVIEWER = {STAGE_SHADOW, STAGE_CONTRIBUTOR}
TASK_ORIGINS = [ORIGIN_PLANNED, ORIGIN_ADDED]

# --- Task labels: DERIVED from the department, never chosen (decision D14) -------------------
#
# 🔴 A task carries exactly ONE label and nobody picks it. It is computed from the assigned
# department, which is the same rule Atrium has always used (`main.TASK_DEPT_LABEL` over there) —
# so the two boards finally agree instead of drifting. The old hand-picked vocabulary
# ["Design", "Copy", "Ads", "SEO", "Dev"] is retired: it was a second, unreliable taxonomy that
# said nothing the department did not already say, and half of it was never applied.
#
# Keyed by the FIRST WORD of the team name, lower-cased, so Sentinel's "Data Analyst" and Atrium's
# "data" resolve to the same answer without either side hardcoding the other's wording. An
# unmapped department falls back to TASK_LABEL_DEFAULT, exactly as Atrium's `.get()` does.
TASK_DEPT_LABEL = {
    "acquisition": "Paid Media",
    "lifecycle": "Organic",
    "data": "Website",
    "development": "Website",
    "bidbrain": "Website",
}
TASK_LABEL_DEFAULT = "Website"
# Every label the board can now produce — what the vocabulary endpoint offers and what the
# label-colour map is keyed by. Derived from the mapping so the two can never disagree.
TASK_LABELS = sorted({*TASK_DEPT_LABEL.values(), TASK_LABEL_DEFAULT})


def label_for_department(team_name: str | None) -> str | None:
    """The one label a task in this department carries. None when it has no department yet.

    A task with no team is genuinely unlabelled — inventing "Website" for it would put untriaged
    work into a real bucket and make the board lie about what it is.
    """
    first = (team_name or "").strip().split()
    if not first:
        return None
    return TASK_DEPT_LABEL.get(first[0].lower(), TASK_LABEL_DEFAULT)

# --- Leave -----------------------------------------------------------------
LEAVE_PENDING = "Pending"
LEAVE_APPROVED = "Approved"
LEAVE_REJECTED = "Rejected"

# --- Requests (regularization / overtime) ----------------------------------
REQ_REGULARIZATION = "regularization"
REQ_OVERTIME = "overtime"
REQ_PENDING = "Pending"
REQ_APPROVED = "Approved"
REQ_REJECTED = "Rejected"

# --- Notifications ---------------------------------------------------------
NOTIF_APPROVAL = "approval"
NOTIF_TASK_ASSIGNED = "task_assigned"
# "task_review" was retired with the "For Review" STATUS (2026-07-30) and came back on 2026-08-03 as
# a review STATE (REVIEW_* above): the notification is what tells a team lead there is something
# waiting on their approval. Same type string as the old rows, which is fine — it is only ever
# displayed, never matched on.
NOTIF_TASK_REVIEW = "task_review"
NOTIF_TASK_OVERDUE = "task_overdue"
NOTIF_GYM_MISSING = "gym_missing"
NOTIF_ANNOUNCEMENT = "announcement"

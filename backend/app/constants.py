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

ALL_ROLES = [
    ROLE_SUPER_ADMIN,
    ROLE_ADMIN,
    ROLE_ACCOUNT_MANAGER,
    ROLE_TEAM_LEAD,
    ROLE_EMPLOYEE,
    ROLE_INTERN,
]

# Rank for "at least this role" checks. Higher = more power.
ROLE_RANK = {
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
MANAGER_ROLES = {ROLE_ADMIN, ROLE_SUPER_ADMIN, ROLE_TEAM_LEAD, ROLE_ACCOUNT_MANAGER}

ROLE_LABELS = {
    ROLE_SUPER_ADMIN: "Super Admin",
    ROLE_ADMIN: "Admin",
    ROLE_ACCOUNT_MANAGER: "Account Manager",
    ROLE_TEAM_LEAD: "Team Lead",
    ROLE_EMPLOYEE: "Employee",
    ROLE_INTERN: "Intern",
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
TASK_FOR_REVIEW = "For Review"
TASK_WAITING_CLIENT = "Waiting for Client"
TASK_REVISION = "Revision Needed"
TASK_COMPLETED = "Completed"
TASK_BLOCKED = "Blocked"
TASK_STATUSES = [
    TASK_TODO,
    TASK_IN_PROGRESS,
    TASK_FOR_REVIEW,
    TASK_WAITING_CLIENT,
    TASK_REVISION,
    TASK_COMPLETED,
    TASK_BLOCKED,
]

PRIORITY_URGENT = "Urgent"
PRIORITY_MEDIUM = "Medium"
PRIORITY_LOW = "Low"
PRIORITIES = [PRIORITY_URGENT, PRIORITY_MEDIUM, PRIORITY_LOW]

TASK_LABELS = ["Design", "Copy", "Ads", "SEO", "Dev"]

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
NOTIF_TASK_REVIEW = "task_review"
NOTIF_TASK_OVERDUE = "task_overdue"
NOTIF_GYM_MISSING = "gym_missing"
NOTIF_ANNOUNCEMENT = "announcement"

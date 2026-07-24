"""Pydantic request schemas (validation + OpenAPI). Responses are serialized as plain dicts by the
routers so we keep tight control over which fields are exposed (esp. internal vs client-facing)."""
from __future__ import annotations

import datetime as _dt
from datetime import date
from typing import Annotated, Any

from pydantic import AfterValidator, BaseModel, Field


def _clean_money(v: str | None) -> str | None:
    """Normalize an optional money input to a bare number string ('4200' / '4200.50').

    Lenient on purpose (internal-only field): strip '$', thousands commas and whitespace; blank,
    zero, or non-numeric input all collapse to None (= "no charge set")."""
    if v is None:
        return None
    s = str(v).replace("$", "").replace(",", "").strip()
    if not s:
        return None
    try:
        if float(s) <= 0:
            return None
    except ValueError:
        return None
    return s


# Optional money string, normalized on the way in. Shared by task create/update.
MoneyStr = Annotated[str | None, AfterValidator(_clean_money)]


# --- Auth ------------------------------------------------------------------
class DevLoginIn(BaseModel):
    user_id: int | None = None
    email: str | None = None


class LoginIn(BaseModel):
    email: str
    password: str


class ChangePasswordIn(BaseModel):
    current_password: str | None = None
    new_password: str


# --- Attendance ------------------------------------------------------------
class ScanIn(BaseModel):
    token: str


class EventIn(BaseModel):
    token: str
    action: str
    late_reason: str | None = None
    handover_note: str | None = None
    device: str = "kiosk"


class OfflinePunch(BaseModel):
    token: str
    action: str
    client_time: str  # ISO instant captured on the device while offline
    uid: str | None = None  # client-generated id: lets the kiosk sync each punch exactly once
    late_reason: str | None = None
    handover_note: str | None = None


class OfflineSyncIn(BaseModel):
    punches: list[OfflinePunch] = Field(default_factory=list)


class AttendanceRequestIn(BaseModel):
    date: date
    request_type: str  # regularization | overtime
    reason: str
    old_value: str | None = None
    new_value: str | None = None


class RequestDecisionIn(BaseModel):
    status: str  # Approved | Rejected


class AttendanceEditIn(BaseModel):
    """Super Admin manual correction of a day's summary. Times are PH 'HH:MM' (blank = clear)."""
    clock_in: str | None = None
    clock_out: str | None = None
    status: str | None = None


# --- Gym -------------------------------------------------------------------
class GymAdminEditIn(BaseModel):
    """Super Admin correction of any user's gym session."""
    day_type: str | None = None
    status: str | None = None
    notes: str | None = None


class GymSetIn(BaseModel):
    set: int
    kg: float = 0
    reps: int = 0
    type: str = "Normal"
    done: bool = True
    pr: bool = False


class GymExerciseIn(BaseModel):
    exercise_name: str
    muscle_group: str | None = None
    weight_value: float = 0
    weight_unit: str = "kg"
    sets: int = 0
    reps: int = 0
    set_type: str = "Normal"
    sets_detail: list[GymSetIn] = Field(default_factory=list)
    duration_minutes: int = 0
    notes: str | None = None


class GymDayOpenIn(BaseModel):
    """Open (upsert) a day's editable session. Date defaults to today; day_type to the plan."""
    date: _dt.date | None = None  # _dt.date, not `date`: the field name shadows the bare type
    day_type: str | None = None


class GymSessionEditIn(BaseModel):
    """The user's own no-lock edits to a session's meta (never locks — always re-editable)."""
    day_type: str | None = None
    duration_minutes: int | None = None
    notes: str | None = None
    done: bool | None = None


class GymPlanWeekIn(BaseModel):
    """Replace the recurring weekly split (+ optional per-weekday cardio notes).
    week: {Mon..Sun -> day-type|Rest}; cardio: {Mon..Sun -> free text, e.g. '5k run'}."""
    week: dict[str, str] = Field(default_factory=dict)
    cardio: dict[str, str] | None = None


class GymPlanDayIn(BaseModel):
    """Override the plan for a single date (e.g. move a split, mark Rest, or note a run)."""
    date: _dt.date
    day_type: str
    cardio: str | None = None


# --- Development (holistic) ------------------------------------------------
class BodyMetricIn(BaseModel):
    """A body-composition snapshot. Date defaults to today (PH) when omitted.

    NOTE: the field is named ``date`` but the annotation is qualified as ``_dt.date`` on purpose —
    a field literally named ``date`` with a default assigns ``date = None`` into the class namespace,
    which would shadow the bare ``date`` type when pydantic evaluates the annotation.
    """
    date: _dt.date | None = None
    weight_kg: float | None = Field(default=None, ge=0)
    body_fat_pct: float | None = Field(default=None, ge=0, le=100)
    notes: str | None = None


class PersonalRecordIn(BaseModel):
    exercise_name: str
    weight_value: float = Field(default=0, ge=0)
    weight_unit: str = "kg"
    reps: int = Field(default=1, ge=1)
    detail: str | None = None  # non-weight result, e.g. "10 km in ~59 min"
    achieved_on: date | None = None
    notes: str | None = None


class PersonalRecordUpdateIn(BaseModel):
    exercise_name: str | None = None
    weight_value: float | None = Field(default=None, ge=0)
    weight_unit: str | None = None
    reps: int | None = Field(default=None, ge=1)
    detail: str | None = None
    achieved_on: date | None = None
    notes: str | None = None


class ResumeIn(BaseModel):
    headline: str | None = None
    resume_text: str | None = None
    resume_file_url: str | None = None


class AchievementIn(BaseModel):
    title: str
    description: str | None = None
    achieved_on: date | None = None


class AchievementUpdateIn(BaseModel):
    title: str | None = None
    description: str | None = None
    achieved_on: date | None = None


class GoalIn(BaseModel):
    title: str
    description: str | None = None
    target_date: date | None = None
    status: str = "active"  # active | done | paused
    progress_pct: int = Field(default=0, ge=0, le=100)


class GoalUpdateIn(BaseModel):
    title: str | None = None
    description: str | None = None
    target_date: date | None = None
    status: str | None = None
    progress_pct: int | None = Field(default=None, ge=0, le=100)


class GrowthItemIn(BaseModel):
    kind: str = "reflection"  # obstacle | reflection | note
    title: str
    detail: str | None = None
    status: str = "open"  # open | resolved | archived


class GrowthItemUpdateIn(BaseModel):
    kind: str | None = None
    title: str | None = None
    detail: str | None = None
    status: str | None = None


class ReadingItemIn(BaseModel):
    """Admin: add/curate a canon item (required book/philosophy)."""
    title: str
    author: str | None = None
    kind: str = "book"  # book | philosophy | essay
    url: str | None = None
    summary: str | None = None
    required: bool = True
    sort_order: int = 0


class ReadingItemUpdateIn(BaseModel):
    title: str | None = None
    author: str | None = None
    kind: str | None = None
    url: str | None = None
    summary: str | None = None
    required: bool | None = None
    sort_order: int | None = None


class ReadingProgressIn(BaseModel):
    """Worker: my status + reflection on a canon item (upsert)."""
    status: str | None = None  # not_started | reading | done
    reflection: str | None = None
    rating: int | None = Field(default=None, ge=1, le=5)


class SkillIn(BaseModel):
    name: str
    level: str = "Intermediate"  # Beginner | Intermediate | Advanced
    source: str = "project"  # project | mastery_engine | course | certification | other
    note: str | None = None


class SkillUpdateIn(BaseModel):
    name: str | None = None
    level: str | None = None
    source: str | None = None
    note: str | None = None


# --- Tasks -----------------------------------------------------------------
class ChecklistItem(BaseModel):
    text: str
    done: bool = False


class TaskCreateIn(BaseModel):
    title: str
    description: str | None = None
    client_id: int | None = None
    campaign: str | None = None
    content_type: str | None = None
    service_key: str | None = None  # a task_templates recipe — seeds the checklist + content_type
    assigned_team_id: int | None = None
    assigned_to_id: int | None = None
    priority: str = "Medium"
    status: str = "To Do"
    due_date: date | None = None
    service_charge: MoneyStr = None
    labels: list[str] = Field(default_factory=list)
    checklist: list[ChecklistItem] = Field(default_factory=list)
    maintasks: list[dict[str, Any]] = Field(default_factory=list)
    deliverable_url: str | None = None
    internal_notes: str | None = None
    client_facing_notes: str | None = None


class TaskUpdateIn(BaseModel):
    title: str | None = None
    description: str | None = None
    client_id: int | None = None
    campaign: str | None = None
    content_type: str | None = None
    assigned_team_id: int | None = None
    assigned_to_id: int | None = None
    priority: str | None = None   # honored only for roles that can_prioritize; ignored otherwise
    due_date: date | None = None
    service_charge: MoneyStr = None
    labels: list[str] | None = None
    checklist: list[ChecklistItem] | None = None
    maintasks: list[dict[str, Any]] | None = None   # two-level breakdown (replaces the flat array)
    deliverable_url: str | None = None
    internal_notes: str | None = None
    client_facing_notes: str | None = None
    atrium_visible: bool | None = None


class TaskStatusIn(BaseModel):
    status: str


class TaskPriorityIn(BaseModel):
    priority: str


class CommentIn(BaseModel):
    body: str
    attachments: list[dict[str, Any]] = Field(default_factory=list)


# --- People ----------------------------------------------------------------
class PersonCreateIn(BaseModel):
    name: str
    email: str
    role: str = "employee"
    team_id: int | None = None
    phone: str | None = None
    hired_date: date | None = None
    shift_template_id: int | None = None
    password: str | None = None  # optional initial password


class PersonUpdateIn(BaseModel):
    name: str | None = None
    email: str | None = None
    role: str | None = None
    team_id: int | None = None
    phone: str | None = None
    hired_date: date | None = None
    shift_template_id: int | None = None
    is_active: bool | None = None
    password: str | None = None  # admin set/reset (blank/None = leave unchanged)


# --- Leave -----------------------------------------------------------------
class LeaveRequestIn(BaseModel):
    leave_type_id: int
    start_date: date
    end_date: date
    reason: str


class LeaveDecisionIn(BaseModel):
    status: str  # Approved | Rejected


# --- Admin -----------------------------------------------------------------
class SettingsIn(BaseModel):
    settings: dict[str, str]


class AnnouncementIn(BaseModel):
    title: str
    body: str | None = None


# --- Payroll (Super Admin only) --------------------------------------------
class SalaryIn(BaseModel):
    monthly_salary: float = Field(ge=0)


class PayrollAdjustIn(BaseModel):
    period: str  # "YYYY-MM"
    bonus: float = Field(default=0, ge=0)
    deduction: float = Field(default=0, ge=0)
    note: str | None = None


class PayrollFinalizeIn(BaseModel):
    period: str
    finalized: bool = True

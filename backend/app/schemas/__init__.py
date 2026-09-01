"""Pydantic request schemas (validation + OpenAPI). Responses are serialized as plain dicts by the
routers so we keep tight control over which fields are exposed (esp. internal vs client-facing)."""
from __future__ import annotations

from datetime import date as _date

import datetime as _dt
from datetime import date
from typing import Annotated, Any, Literal

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


class SelfEventIn(BaseModel):
    """Self clock-in/out from the web app (Dashboard). No token — the session is the identity."""
    action: str
    late_reason: str | None = None
    handover_note: str | None = None


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


class GymCoachVisibilityIn(BaseModel):
    """Whether the AI coach may read this person's gym LOG. Its own body, its own endpoint —
    deliberately NOT a field on ResumeIn, which the coach's own action protocol can write."""
    reads_logs: bool


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


class GymRoutineSetIn(BaseModel):
    """One planned set in a routine. No ``done`` flag — a template holds sets to DO, not sets done."""
    kg: float = 0
    reps: int = 0
    type: str = "Normal"


class GymRoutineExerciseIn(BaseModel):
    exercise_name: str
    muscle_group: str | None = None
    sets: list[GymRoutineSetIn] = Field(default_factory=list)
    notes: str | None = None


class GymRoutineIn(BaseModel):
    """Create/update a saved workout template ("Push A").

    Every field is optional so a PATCH can touch one thing. ``from_log_id`` copies the exercises out
    of a logged session instead of sending them — that's both "save today's workout as a routine"
    and "my squat went up, refresh the template from today's numbers".
    """
    name: str | None = None
    day_type: str | None = None
    exercises: list[GymRoutineExerciseIn] | None = None
    weekdays: list[str] | None = None
    notes: str | None = None
    from_log_id: int | None = None


class GymApplyRoutineIn(BaseModel):
    """Drop a routine onto a session. ``replace`` swaps the whole workout in (and adopts its
    split); ``append`` adds it to whatever is already logged."""
    routine_id: int
    mode: str = "replace"


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
    dimension: str = "professional"  # spiritual | professional | philosophical | physical
    description: str | None = None
    target_date: date | None = None
    status: str = "active"  # active | done | paused
    progress_pct: int = Field(default=0, ge=0, le=100)


class GoalUpdateIn(BaseModel):
    title: str | None = None
    dimension: str | None = None
    description: str | None = None
    target_date: date | None = None
    status: str | None = None
    progress_pct: int | None = Field(default=None, ge=0, le=100)


class PhysicalGoalIn(BaseModel):
    """A target PR to chase: a lift, a run, or a skill (calisthenics/boxing)."""

    name: str
    kind: str = "lift"  # lift | run | skill
    target_value: float
    current_value: float = 0
    unit: str = ""  # kg, lb, min, sec, reps, km…
    direction: str = "higher"  # higher | lower (time-based: lower is better)
    notes: str | None = None
    status: str = "active"  # active | achieved | paused


class PhysicalGoalUpdateIn(BaseModel):
    name: str | None = None
    kind: str | None = None
    target_value: float | None = None
    current_value: float | None = None
    unit: str | None = None
    direction: str | None = None
    notes: str | None = None
    status: str | None = None


class AreaUpdateIn(BaseModel):
    """Patch one growth dimension's settings. Fields the client OMITS are left alone; an
    explicit null CLEARS (deadline back to the default, other_info emptied) — the router
    uses exclude_unset to tell the two apart."""

    deadline: date | None = None
    other_info: str | None = None


class TimeEntryIn(BaseModel):
    """A hand-logged block of time against a dimension — what the engine cannot see."""
    date: _date
    start: str            # HH:MM, PH time
    minutes: int
    dimension: str        # spiritual | professional | philosophical | physical | coach | other
    note: str | None = None
    user_id: int | None = None   # an admin logging on somebody's behalf


class TimeEntryUpdateIn(BaseModel):
    date: _date | None = None
    start: str | None = None
    minutes: int | None = None
    dimension: str | None = None
    note: str | None = None


class EngineSessionEditIn(BaseModel):
    """Delete (no new_*) or TRIM one recorded engine session. Never extends — see time_spent."""
    day: _date
    start: str            # HH:MM
    end: str              # HH:MM, exclusive
    new_start: str | None = None
    new_end: str | None = None
    user_id: int | None = None


class GrowthItemIn(BaseModel):
    dimension: str = "spiritual"  # spiritual | professional | philosophical | physical
    kind: str = "reflection"  # obstacle | reflection | note
    title: str
    detail: str | None = None
    status: str = "open"  # open | resolved | archived


class GrowthItemUpdateIn(BaseModel):
    dimension: str | None = None
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


class MentorTranscriptIn(BaseModel):
    mentor_name: str
    title: str
    source_url: str | None = None
    transcript_text: str


class AtriumImportIn(BaseModel):
    channel_id: str
    video_id: str
    mentor_name: str


class AtriumImportAllIn(BaseModel):
    """Import every fetched transcript on one Atrium Watcher creator in a single go."""

    channel_id: str
    mentor_name: str


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
    # SUPPORT — many, none accountable (models.TaskSupporter). Naming anyone but yourself here is
    # DELEGATION and is refused for a role that may not delegate, exactly like `assigned_to_id`.
    support_ids: list[int] = Field(default_factory=list)
    priority: str = "Medium"
    status: str = "To Do"
    due_date: date | None = None
    start_date: date | None = None
    service_charge: MoneyStr = None
    labels: list[str] = Field(default_factory=list)
    checklist: list[ChecklistItem] = Field(default_factory=list)
    maintasks: list[dict[str, Any]] = Field(default_factory=list)
    deliverable_url: str | None = None
    internal_notes: str | None = None
    client_facing_notes: str | None = None
    # Share-on-create (decision D6). None = "decide for me": share when the task has a client, and
    # the caller can force it either way. Tri-state on purpose — `False` must mean "explicitly do
    # not share", which a plain bool default could not express.
    share_with_client: bool | None = None


class TaskBulkIn(BaseModel):
    """Apply ONE change to many tasks (M7). Triage on a 60-card board was one drawer at a time."""

    ids: list[int] = Field(default_factory=list, max_length=200)
    op: Literal["status", "priority", "assignee"]
    # status -> the status name; priority -> the priority name; assignee -> a user id or null
    # (null = unassign, which is a real triage action, so the field is genuinely nullable).
    value: str | int | None = None


class RecurringServiceIn(BaseModel):
    """A retainer deliverable that should exist every period (WP 6.1)."""

    title: str
    client_id: int | None = None
    service_key: str | None = None
    assigned_team_id: int | None = None
    assigned_to_id: int | None = None
    priority: str = "Medium"
    cadence: Literal["monthly", "weekly"] = "monthly"
    # monthly: day of month (clamped to the month's length). weekly: 0=Mon .. 6=Sun.
    day_of_period: int = Field(1, ge=0, le=31)
    due_in_days: int = Field(0, ge=0, le=365)
    is_active: bool = True


class TaskAdoptionApplyIn(BaseModel):
    """Import one workspace's Atrium cards (WP 3.4). `confirm` must repeat `client` exactly —
    this writes rows derived from LIVE client data, and the typed confirmation is what separates
    "I read the plan" from "I posted the wrong body"."""

    client: str
    confirm: str
    batch: str | None = None      # omit and one is minted; it is the handle for reverting


class TaskAdoptionRevertIn(BaseModel):
    batch: str


class TaskRequestDecisionIn(BaseModel):
    """Accepting or declining a client's ask (D3). Everything is optional except, on a decline,
    the reason — enforced in the route so the error can say why it is owed."""

    # accept: the triager may adjust the ask into a real piece of work as they take it on
    title: str | None = None
    assigned_team_id: int | None = None
    assigned_to_id: int | None = None
    priority: str | None = None
    due_date: date | None = None
    # decline
    reason: str | None = None


class TaskUpdateIn(BaseModel):
    title: str | None = None
    description: str | None = None
    client_id: int | None = None
    campaign: str | None = None
    content_type: str | None = None
    assigned_team_id: int | None = None
    assigned_to_id: int | None = None
    # SUPPORT (models.TaskSupporter). 🔴 `None` means "not sent — leave the supporters alone"; `[]`
    # means "remove everyone". A plain `Field(default_factory=list)` here would make every PATCH that
    # omits the field silently CLEAR the support list, which is the kind of quiet data loss the
    # breakdown's owner-diff guard exists to prevent.
    support_ids: list[int] | None = None
    priority: str | None = None   # honored only for roles that can_prioritize; ignored otherwise
    # planned | added (constants.ORIGIN_*). A CORRECTION to what task_origin.classify derived at
    # create time — honored only for `can_reassign`, dropped otherwise, and never offered on create
    # (the classification is the server's, exactly like the creator tag and the label).
    origin: str | None = None
    due_date: date | None = None
    start_date: date | None = None   # a real Sentinel column since 2026-08-03 (was Atrium-only)
    service_charge: MoneyStr = None
    labels: list[str] | None = None
    checklist: list[ChecklistItem] | None = None
    maintasks: list[dict[str, Any]] | None = None   # two-level breakdown (replaces the flat array)
    deliverable_url: str | None = None
    internal_notes: str | None = None
    client_facing_notes: str | None = None
    atrium_visible: bool | None = None
    # --- Atrium-owned cards only (board id "atrium:<client_key>:<task_id>") -------------------
    # Atrium has no Sentinel assignee/team and stores owners as roster EMAILS. These are inert on a
    # Sentinel row: services/atrium_tasks.FIELD_MAP is the only thing that reads them, and the
    # Sentinel branch of the update route drops them (ONLY_ATRIUM).
    #
    # `start_date` LEFT this block on 2026-08-03 — it is a real Sentinel column now (M5), declared
    # above with the other shared fields. `on_hold` / `hold_reason` deliberately did NOT: Sentinel
    # has both columns, but a PATCH must not set them, because a hold is three coupled fields
    # (`on_hold` + `hold_reason` + `resume_to`) and only `POST /{id}/park` sets all three. A PATCH
    # could otherwise leave a card "on hold" with nothing remembering where it came from.
    on_hold: bool | None = None
    hold_reason: str | None = None
    atrium_department: str | None = None
    atrium_lead_id: str | None = None
    atrium_support_ids: list[str] | None = None


class TaskStatusIn(BaseModel):
    status: str


class TaskParkIn(BaseModel):
    """Why the work is paused. 🔒 Internal — never crosses to the client (task_bridge.SAFE)."""
    reason: str = ""


class TaskReviewIn(BaseModel):
    """A reviewer's note, used by "request changes". Optional."""
    note: str = ""


class TaskPriorityIn(BaseModel):
    priority: str


class TaskApplyTemplateIn(BaseModel):
    """Seed an EXISTING task's work breakdown from a service template (2026-08-14).

    Service templates could only ever be applied at CREATE time, which made them unreachable for the
    commonest way a card is raised: somebody types a title, hits enter, and fills the rest in later.
    Those cards could never get a breakdown at all without retyping every phase by hand — so in
    practice the recipe book only served people who happened to open the full New Task form first.

    `mode` is REQUIRED rather than defaulted, because the two modes differ in whether they destroy
    work: `append` adds the template's phases after whatever is there, `replace` discards the current
    breakdown — including every tick and every step owner. A default would pick one of those on the
    caller's behalf, and the wrong guess is unrecoverable.
    """
    service_key: str
    mode: Literal["append", "replace"]


class CommentIn(BaseModel):
    body: str
    attachments: list[dict[str, Any]] = Field(default_factory=list)


# --- People ----------------------------------------------------------------
class PersonCreateIn(BaseModel):
    name: str
    email: str
    role: str = "employee"
    team_id: int | None = None
    # ADDITIONAL departments (models.UserTeam). `team_id` above stays the primary one — the one that
    # decides this person's shift, their payroll row and the Department column in People.
    team_ids: list[int] | None = None
    phone: str | None = None
    hired_date: date | None = None
    shift_template_id: int | None = None
    password: str | None = None  # optional initial password


class PermissionChangeIn(BaseModel):
    role: str
    capability: str
    allowed: bool


class PermissionChangesIn(BaseModel):
    """A BATCH of grants/revokes. The console saves a whole grid, not one checkbox at a time, so a
    change that is only coherent with another (grant the read, grant the write) lands together."""

    changes: list[PermissionChangeIn]


class UserPermissionChangeIn(BaseModel):
    capability: str
    allowed: bool


class UserPermissionChangesIn(BaseModel):
    """A batch of per-PERSON exceptions. The user id is in the path, not repeated per change."""

    changes: list[UserPermissionChangeIn]


class PersonUpdateIn(BaseModel):
    name: str | None = None
    email: str | None = None
    role: str | None = None
    team_id: int | None = None
    # 🔴 `None` means NOT SENT and leaves the memberships untouched; `[]` really does remove them
    # all. Same contract as `support_ids` (AGENTS.md §5) and for the same reason: a plain `[]`
    # default would make every unrelated PATCH — a phone number, a shift, a password reset — quietly
    # empty somebody's additional departments and shrink their board.
    team_ids: list[int] | None = None
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

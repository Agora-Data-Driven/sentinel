"""tasks, task_supporters, task_comments, task_history, atrium_approvals."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..constants import PRIORITY_MEDIUM, TASK_TODO
from ..database import Base
from ..utils.time import utcnow


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id"), nullable=True, index=True)
    campaign: Mapped[str | None] = mapped_column(String(160), nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(80), nullable=True)

    # Internal-only ownership fields (NEVER exposed to clients / Atrium).
    account_manager_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    assigned_team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"), nullable=True, index=True)
    assigned_to_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    # Who created the task — tagged automatically on create (never a form field). Drives the
    # "own tasks" visibility rule: an employee always keeps sight of tasks they made, even
    # while unassigned or after a manager reassigns them. Nullable: tasks predating the column.
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    # 🔴 PLANNED AHEAD, or RAISED DURING THE DAY (2026-08-11) — `constants.ORIGIN_*`.
    #
    # The one fact the task-placement guidelines need that this board could not report: §1 makes the
    # Team Lead responsible for placing planned work before the day starts, §3 makes the worker
    # responsible for adding whatever comes up afterwards, and the stated reason is that Sentinel must
    # "accurately reflect the actual work completed during the day". Every task looked equally planned,
    # so a team's reactive load was invisible on every surface.
    #
    # 🔴 NULLABLE, and it stays null for the rows that predate it. A default of "planned" would assert
    # that thousands of historical tasks were planned, which nobody knows — `None` reports as unknown
    # and is excluded from both counts, the same contract `on_time_rate` follows for undated work.
    #
    # Set ONCE at create time by `services/task_origin.classify` (never a form field, like
    # `created_by_id`) and correctable afterwards by whoever could reassign the card — see that
    # module for why a derived answer needs a correction path.
    origin: Mapped[str | None] = mapped_column(String(12), nullable=True)
    priority: Mapped[str] = mapped_column(String(16), default=PRIORITY_MEDIUM)  # AM-only to change
    status: Mapped[str] = mapped_column(String(32), default=TASK_TODO, index=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # When the work STARTS, as opposed to when it is owed. Atrium has always had this and renders
    # the client a Started → Going live timeline from it; Sentinel had only `due_date`, so a task
    # had no duration and no schedule view was possible (docs/TASKBOARD_REBUILD.md M5).
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # --- Completion + filing (M4) -------------------------------------------------------------
    # 🔴 When the task actually reached a completed-stage status. Throughput used to be counted off
    # `updated_at`, so editing a finished task re-dated its completion and inflated this week's
    # numbers (§2.4h). Set/cleared by `task_workflow.on_status_change`, never by a form.
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Filed away into Past work. The Completed column is a working column, not an archive: left
    # alone it becomes a graveyard and every count on the board stops meaning anything.
    archived: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    # --- Park / resume (M3) -------------------------------------------------------------------
    # Parking is a status move that REMEMBERS. `resume_to` holds the status the card left, so
    # resuming puts it back where the work actually was instead of dumping it in To Do.
    # `hold_reason` is INTERNAL and never crosses the bridge — see task_bridge.SAFE.
    on_hold: Mapped[bool] = mapped_column(Boolean, default=False)
    hold_reason: Mapped[str | None] = mapped_column(Text, nullable=True)   # 🔒 internal
    resume_to: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # --- Review gate (M2, decision D5) --------------------------------------------------------
    # NULL = never submitted. Otherwise pending | approved | changes_requested (constants.REVIEW_*).
    # A task may not enter a completed-stage status without `approved` — the one gate on this board
    # that is enforced rather than surfaced, because "Done" was otherwise one person's unilateral
    # claim. `reviewer_id` is who decided, stamped on the decision, not on the request.
    review_state: Mapped[str | None] = mapped_column(String(20), nullable=True)
    reviewer_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    # Which adoption run created this row (WP 3.4). NULL for every task a human raised.
    # 🔴 This column is what makes importing live client cards REVERSIBLE: `task_adoption.revert`
    # removes exactly one run's rows and nothing else. Without it an import would be a one-way
    # door over data nobody can afford to guess about.
    adoption_batch: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    # How many change requests the CLIENT has open on this card (D4 / WP 3.5).
    # 🔴 Deliberately NOT `review_state`. That field is the internal approval gate (D5): a team
    # lead saying "this is done". A client asking for a revision is a different fact from a
    # different person, and folding them together would mean a client could satisfy — or block —
    # an internal sign-off. They are counted separately and displayed separately.
    client_changes_open: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Internal-only money field (never crosses to Atrium). Optional; stored bare — digits with an
    # optional decimal, no "$" or thousands commas. Empty/blank = no charge set.
    service_charge: Mapped[str | None] = mapped_column(String(32), nullable=True)
    labels_json: Mapped[str] = mapped_column(Text, default="[]")  # ["Design","Ads",...]
    checklist_json: Mapped[str] = mapped_column(Text, default="[]")  # [{text,done}] — legacy flat list
    # Two-level work breakdown: [{id,title,assignee_id,subs:[{id,text,done,assignee_id}]}].
    # Supersedes checklist_json (a legacy flat list is migrated into one main task on read).
    maintasks_json: Mapped[str] = mapped_column(Text, default="[]")

    # Visibility bridge: whether this task's client-facing fields are shared to Atrium.
    #
    # 🔴 `atrium_visible` alone used to be the WHOLE bridge, and it referred to nothing:
    # /send-to-atrium set it True and never created the Atrium card, so every True row pointed at
    # a card that did not exist while the drawer showed "✓ In Atrium" (see docs/TASKBOARD_REBUILD.md
    # §1.2). It is now only meaningful together with `atrium_task_id`.
    atrium_visible: Mapped[bool] = mapped_column(Boolean, default=False)
    # The Atrium card this row projects onto — Atrium's own task id, returned by /api/internal/
    # task-add. Set ONLY once the card really exists, so `atrium_visible and not atrium_task_id`
    # is exactly the set of rows the reconcile report has to ask a human about (D15).
    atrium_task_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # Why the last projection push failed. NULL = the client's card is current. A push is
    # fail-LOUD by design: a silently stale client card is the bug this whole stage removes, so
    # the failure is stored on the row, surfaced on the board, and retryable.
    atrium_sync_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    deliverable_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    internal_notes: Mapped[str | None] = mapped_column(Text, nullable=True)  # 🔒 internal
    client_facing_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    comments: Mapped[list["TaskComment"]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )
    history: Mapped[list["TaskHistory"]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )
    # SUPPORT — the people helping, who are not accountable. See TaskSupporter.
    # `lazy="selectin"` because every board read needs it: the card renders their avatars and
    # `task_perms.assigned_user_ids` counts them, so a default lazy load would be one extra query
    # per card on a list of eighty.
    supporters: Mapped[list["TaskSupporter"]] = relationship(
        back_populates="task", cascade="all, delete-orphan", lazy="selectin"
    )

    @property
    def support_ids(self) -> list[int]:
        """Supporter user ids, ordered so the UI and the API never disagree about sequence."""
        return sorted(s.user_id for s in (self.supporters or []))


class TaskSupporter(Base):
    """One person supporting one task — MANY per task, none of them accountable for it.

    Why this exists (2026-08-06). A Sentinel task had exactly ONE ownership field,
    `assigned_to_id`, while the Atrium client cards it sits beside on the same board have carried
    Lead + many Support since the bridge was built. So the only way to put a second name on a
    Sentinel card was to **invent a checklist step for them** — and because the progress bar is
    `done steps / total steps`, that made STAFFING a card change its completion percentage. Adding a
    helper made the work look less finished.

    🔴 SUPPORT IS VISIBILITY, NOT AUTHORITY, and that split is the whole design:

    | Support DOES get | Support does NOT get |
    |---|---|
    | the card on their board (`can_view` → `is_assigned`) | accountability — `assigned_to_id` stays the one neck |
    | it counted in "My work" and on the Monitor | the lead's right to tick somebody ELSE's step (`can_tick_step`) |
    | a lane in By Employee, marked "supporting" | claiming the card out of its team's triage queue (`_team_queue` still tests `assigned_to_id`) |
    | `?assignee_id=` is unaffected — that stays a precise field filter on the LEAD |

    A TABLE rather than a `support_ids_json` column, for a reason specific to this repo: prod does
    not reliably run Alembic, and `create_all` lands a new **table** by itself while a new **column**
    on an existing table only arrives via `main._ensure_columns` (see AGENTS.md §4 and the gym-routines
    note in §5). It also keeps the FK honest — a JSON blob of ids rots silently when a user is
    deactivated, and it makes "every card X supports" a real query for whatever needs it next.

    🔴 Naming somebody here is DELEGATION and is guarded where the field is WRITTEN (`routers/tasks.py`,
    `_support_change_needs_delegation`), exactly like the breakdown's owner diff. That guard has been
    missed twice on this board — once for `maintasks[].assignee_id` and once for owner SETS vs slots —
    so a second writer to this table needs the same check or it walks straight past it.
    """

    __tablename__ = "task_supporters"
    # One row per (task, person): re-sending the same supporter must not stack duplicates, which would
    # double-count them on the Monitor and render their avatar twice on the card.
    __table_args__ = (UniqueConstraint("task_id", "user_id", name="uq_task_supporter"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    # Who added them, and when — support is a delegation decision, so it leaves a trace like every
    # other one. (The human-readable record is a TaskHistory row; this is the durable attribution.)
    added_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    task: Mapped[Task] = relationship(back_populates="supporters")


class TaskComment(Base):
    __tablename__ = "task_comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), nullable=False, index=True)
    # 🔴 NULLABLE since 2026-08-04 (D4 / WP 3.5). A CLIENT can now reach this thread over the
    # reverse channel, and a client is not a Sentinel user — there is no row to point at, and
    # there must never need to be one (creating shadow user accounts for clients would put them
    # in every people picker and every rollup). A comment therefore has EITHER an author_id (a
    # colleague) or a client_author name; `serializers.comment_dict` resolves whichever is set.
    author_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    client_author: Mapped[str | None] = mapped_column(String(160), nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    attachments_json: Mapped[str] = mapped_column(Text, default="[]")  # [{name,url}]
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    task: Mapped[Task] = relationship(back_populates="comments")


class TaskHistory(Base):
    __tablename__ = "task_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), nullable=False, index=True)
    changed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    field_changed: Mapped[str] = mapped_column(String(60), nullable=False)
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    changed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    task: Mapped[Task] = relationship(back_populates="history")


class ServiceTemplate(Base):
    """A super-admin-editable service recipe (was hardcoded in task_templates.py).

    `maintasks_json` holds the grouped breakdown [{"title","subs":[{"text"}]}] the New Task form
    seeds into a task's two-level work breakdown. `dept` matches a Team name.
    """
    __tablename__ = "service_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    dept: Mapped[str | None] = mapped_column(String(80), nullable=True)  # Team name
    content_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    maintasks_json: Mapped[str] = mapped_column(Text, default="[]")
    # Defaults auto-filled onto a new task when this service is picked (a seed, not a lock —
    # each is still editable on the task afterwards; the form pre-fills them client-side too).
    default_priority: Mapped[str | None] = mapped_column(String(16), nullable=True)
    default_labels_json: Mapped[str] = mapped_column(Text, default="[]")  # ["Design","Ads",...]
    default_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class TaskVocabItem(Base):
    """Super-admin-editable board vocabulary: statuses, labels, and priorities (was constants).

    One row per value; `kind` partitions the three vocabularies. `color` is a hex used for inline
    rendering so custom names still get a colour.

    🔴 `name` is a LABEL and may be renamed at will (Manage cascades a rename onto every task row
    via `manage._rename_in_tasks`). Nothing may therefore be keyed off it. Two columns exist so a
    status has an identity the label cannot break:

    * `key`   — a stable slug, minted once from the first name and never changed afterwards.
    * `stage` — for `kind="status"`, the Atrium stage this status projects onto. REQUIRED for a
      status (decision D13): the bridge maps stage-by-stage, and a status with no stage means a
      published card has nowhere to sit, which used to surface as a bare 400 "Invalid status".

    Before these existed, `atrium_tasks.STAGE_BY_STATUS` was a literal dict keyed by the DISPLAY
    STRING, so renaming a status in Manage silently broke the bridge for every client card.
    """
    __tablename__ = "task_vocab"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, index=True)  # status|label|priority
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    # Stable identity, independent of the label. Nullable for rows seeded before it existed —
    # task_config backfills those from the name on read.
    # 🔴 The DB column is `vocab_key`, not `key`: `_ensure_columns` builds a raw
    # `ALTER TABLE … ADD COLUMN <name> …`, and a bare `key` is a keyword in enough dialects that
    # it is not worth the risk for a column we can only test against SQLite locally.
    key: Mapped[str | None] = mapped_column("vocab_key", String(40), nullable=True, index=True)
    # Atrium stage (statuses only): todo | in_progress | revision | blocked | completed.
    stage: Mapped[str | None] = mapped_column(String(24), nullable=True)
    color: Mapped[str | None] = mapped_column(String(16), nullable=True)  # #RRGGBB
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class TaskRequest(Base):
    """A CLIENT'S ASK, before anyone has agreed to do it (decision D3, WP 3.3).

    🔴 A request is deliberately NOT a task. Atrium's quick-add composer used to write straight
    into `ws["tasks"]`, so anything a client typed during a call became a live card on the delivery
    board — unowned, unestimated, unscheduled, and indistinguishable from work the agency had
    actually committed to. The board stopped meaning "what we are doing".

    So the composer now FILES here instead, and a human turns it into a task by accepting it. That
    keeps the one thing clients genuinely use (capturing an ask mid-call) without letting them
    write onto the delivery board.

    `status`: pending -> accepted | declined. Terminal either way; a decision is never un-made,
    because the client has already been told. `task_id` links an accepted request to what it
    became, which is what lets Atrium show the client that their ask turned into real work.

    The client is identified by the ATRIUM workspace key, not a Sentinel client id: the request
    arrives over the bridge from a workspace, and mapping it to a `Client` row is a lookup that may
    legitimately fail (an unlinked workspace) — which must not lose the request.
    """

    __tablename__ = "task_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_key: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Who asked, as Atrium knows them. Free text on purpose: the requester is a CLIENT, so there is
    # no Sentinel user row to point at, and there must never need to be one.
    requester_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    requester_email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Atrium's own id for the composer entry, so a re-send cannot file the same ask twice.
    source_ref: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)

    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    decided_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    decline_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id"), nullable=True, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class RecurringService(Base):
    """A retainer deliverable that should exist every period (WP 6.1, M10).

    Monthly deliverables were re-created by hand every month, which means they get forgotten in
    the months somebody is busy — exactly when the client notices.

    🔴 `last_period` is the whole safety mechanism, and it is a STRING KEY ("2026-08"), not a
    timestamp. The generator asks "have I already made the task for THIS period?" and a period key
    answers that identically no matter how often the tick runs, how many instances run it, or
    whether it ran late. A `last_run_at` datetime would not: two ticks in one day, a retry, or a
    catch-up run after an outage would each have to reason about clock windows, and one of them
    would eventually double-create a client's deliverable.

    🔴 It also means NO BACKFILL. A recurrence created today does not retro-generate the months it
    did not exist for — `last_period` starts at the current period, so the first task appears at
    the NEXT boundary. Waking up to eleven months of invented work is worse than a missing month.
    """

    __tablename__ = "recurring_services"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id"), nullable=True, index=True)
    service_key: Mapped[str | None] = mapped_column(String(60), nullable=True)  # ServiceTemplate.key
    assigned_team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"), nullable=True)
    assigned_to_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    priority: Mapped[str] = mapped_column(String(16), default=PRIORITY_MEDIUM)

    # "monthly" | "weekly". Deliberately only two: a retainer is billed monthly or run weekly, and
    # every extra cadence is another way for the period key to be computed inconsistently.
    cadence: Mapped[str] = mapped_column(String(16), default="monthly")
    # monthly: day of month (clamped to the month's length). weekly: 0=Mon .. 6=Sun.
    day_of_period: Mapped[int] = mapped_column(Integer, default=1)
    # How many days after generation the task is due. 0 = due the day it appears.
    due_in_days: Mapped[int] = mapped_column(Integer, default=0)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    last_period: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AtriumApproval(Base):
    """A LOG of each time a task was shared with its client. Send events only.

    🔴 The three response columns (`client_response`, `responded_at`, `revision_notes`) were
    retired 2026-08-04 (WP 0.4). Nothing ever wrote them: Atrium's client replies arrive as
    comments over the internal bridge, never into this table, so they were permanently NULL and
    read as "no client has ever responded to anything". A dead column that looks like an answer is
    worse than no column. The real client→Sentinel path is the reverse channel (D4 / WP 3.5),
    which lands on `TaskComment` where the conversation already lives.
    Kept deliberately: `sent_at` is the share history, and `task_bridge` still appends a row.
    """

    __tablename__ = "atrium_approvals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), nullable=False, index=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

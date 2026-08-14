"""Model → dict serializers. Central so field exposure (internal vs client-facing) stays consistent.

Datetimes are emitted as ISO strings in Manila time so the frontend can display them directly while
the DB keeps UTC.
"""
from __future__ import annotations

import json
from datetime import date, datetime

from sqlalchemy.orm import Session

from .constants import ROLE_LABELS
from .models import (
    AttendanceRequest,
    BodyMetric,
    CareerAchievement,
    Client,
    DailyAttendanceSummary,
    DevelopmentProfile,
    GrowthItem,
    GymLog,
    GymRoutine,
    LeaveBalance,
    LeaveRequest,
    LeaveType,
    DevelopmentArea,
    MentorTranscript,
    Notification,
    PersonalRecord,
    PhysicalGoal,
    ProfessionalGoal,
    ReadingItem,
    ReadingProgress,
    Skill,
    Task,
    TaskComment,
    TaskHistory,
    Team,
    User,
)
from .utils.time import to_ph


def _iso(dt: datetime | None) -> str | None:
    return to_ph(dt).isoformat() if dt else None


def _d(d: date | None) -> str | None:
    return d.isoformat() if d else None


def _money(raw: str | None) -> str | None:
    """Display string ('$4,200' / '$4,200.50') from a stored bare charge; None for empty/zero/junk.
    Internal-only — never included in the Atrium (client-facing) payload."""
    if not raw:
        return None
    try:
        f = float(str(raw).replace(",", "").replace("$", ""))
    except ValueError:
        return None
    if f <= 0:
        return None
    return f"${f:,.0f}" if f == int(f) else f"${f:,.2f}"


def _loads(raw: str | None, default):
    try:
        return json.loads(raw) if raw else default
    except (ValueError, TypeError):
        return default


def user_public(u: User | None) -> dict | None:
    if not u:
        return None
    return {
        "id": u.id,
        "name": u.name,
        "email": u.email,
        "role": u.role,
        "role_label": ROLE_LABELS.get(u.role, u.role),
        "team_id": u.team_id,
        "initials": u.initials,
        "profile_pic_url": u.profile_pic_url,
    }


def user_full(u: User, team: Team | None = None) -> dict:
    d = user_public(u) or {}
    d.update(
        {
            "phone": u.phone,
            "is_active": u.is_active,
            "hired_date": _d(u.hired_date),
            "shift_template_id": u.shift_template_id,
            "team_name": team.name if team else None,
            # 🔴 EVERY department this person takes part in, primary FIRST (2026-08-14). `team_id`
            # above is still their primary one and still what `team_name`, their shift and their
            # payroll row follow — this is participation, which is a set (see `services/teams`).
            #
            # Deliberately NOT on `user_public`: that shape is serialized once per CARD for every
            # assignee and supporter on the board, and this needs the `extra_teams` relationship —
            # a per-user read on any surface that did not fetch users in bulk. The places that
            # actually need the set (`/api/auth/me`, the People directory, the board's people list)
            # all go through `user_full`, all fetch in bulk, and all already load `/api/teams` to
            # turn these ids into names. See AGENTS.md §5, "the board has a QUERY BUDGET".
            "team_ids": _team_ids_ordered(u),
        }
    )
    return d


def _team_ids_ordered(u: User) -> list[int]:
    """The user's departments with the PRIMARY one first, then the rest alphabetically by id.

    Order is part of the contract: the UI prints these as "Design + Acquisition" and the first name
    is the one that answers "which department are they in?" on a form with room for one answer.
    """
    extra = sorted({t.team_id for t in (getattr(u, "extra_teams", None) or [])
                    if t.team_id is not None and t.team_id != u.team_id})
    return ([u.team_id] if u.team_id is not None else []) + extra


def team_dict(t: Team) -> dict:
    return {
        "id": t.id,
        "name": t.name,
        "shift_template_id": t.shift_template_id,
    }


def shift_template_dict(t) -> dict:
    st, en = t.start, t.end
    # Paid hours = span (overnight-aware) minus break, for a legible "8.0h" hint in the UI.
    sh, sm = (int(x) for x in (st.split(":") + ["0"])[:2])
    eh, em = (int(x) for x in (en.split(":") + ["0"])[:2])
    span = (eh * 60 + em) - (sh * 60 + sm)
    if span <= 0:
        span += 24 * 60
    paid = max(0, span - min(t.break_min or 0, span))
    return {
        "id": t.id,
        "name": t.name,
        "start": st,
        "end": en,
        "break_min": t.break_min,
        "grace_min": t.grace_min,
        "active": t.active,
        "is_default": t.is_default,
        "paid_hours": round(paid / 60.0, 2),
    }


def client_dict(c: Client) -> dict:
    return {
        "id": c.id,
        "name": c.name,
        "contact_email": c.contact_email,
        # 🔴 The BRIDGE KEY, and the field the read-only Clients pane exists to surface: a client with
        # no workspace key is invisible to `resolve_client` / `task_bridge` / `task_adoption`. Since
        # 2026-08-05 `client_sync` fills it from Atrium rather than a human typing it.
        "atrium_client_id": c.atrium_client_id,
        # False = Atrium stopped listing this client. Never deleted (that would NULL `Task.client_id`
        # on every past task and blank its reporting) — just out of the pickers.
        "is_active": bool(getattr(c, "is_active", True)),
    }


def _chunks(seq: list, size: int = 400):
    """`seq` in batches. Every `IN (...)` below is chunked because SQLite caps the number of bound
    parameters in one statement (999 before 3.32) — a 900-card board would raise, not slow down."""
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


class CardPrefetch:
    """The rows every board card needs, loaded ONCE for a whole list of tasks.

    🔴 This exists because `task_card` was issuing ~3.7 queries PER CARD, and two of the three
    reasons are not obvious (measured 2026-08-07, 801 cards → 2,946 queries, 780 ms on SQLite; on
    Cloud SQL every one of those is a socket round-trip, so the same board costs seconds):

    1. `len(t.comments)` is a LAZY LOAD — one SELECT per card, purely to count rows. Unlike
       `Task.supporters` (`lazy="selectin"`, 1 query for the whole board) nothing batched it.
    2. **SQLAlchemy's identity map holds WEAK references.** `task_card` returns a plain dict and
       keeps no reference to the `User` / `Client` it read, so each one was garbage-collected before
       the next card asked for it and `db.get()` went back to the database. That is why the same
       FOUR clients cost **703 SELECTs** on an 800-card board — a cache that looks like it should
       work and does not. Holding the rows in this object is what makes the identity map effective,
       so keep the dicts alive for as long as the cards are being built.

    Every accessor FALLS BACK to a direct read when an id was not prefetched, so a card built
    without a prefetch (`task_detail`, which serializes exactly one row) stays correct — just as
    chatty as it was. Correctness never depends on the cache being warm.
    """

    __slots__ = ("users", "clients", "counts")

    def __init__(self) -> None:
        self.users: dict[int, User] = {}
        self.clients: dict[int, Client] = {}
        # task_id -> (comment_count, attachment_count). Absent means "not prefetched", which is
        # different from 0 and must fall back rather than report an empty thread.
        self.counts: dict[int, tuple[int, int]] = {}

    @classmethod
    def for_tasks(cls, db: Session, tasks: list[Task]) -> "CardPrefetch":
        """Three queries total, whatever the board's size."""
        from sqlalchemy import select as _select

        pre = cls()
        if not tasks:
            return pre

        user_ids: set[int] = set()
        client_ids: set[int] = set()
        for t in tasks:
            for uid in (t.assigned_to_id, getattr(t, "created_by_id", None)):
                if uid:
                    user_ids.add(uid)
            # `supporters` is already selectin-loaded, so this costs nothing extra.
            user_ids.update(s.user_id for s in (getattr(t, "supporters", None) or []))
            if t.client_id:
                client_ids.add(t.client_id)

        for batch in _chunks(sorted(user_ids)):
            for u in db.execute(_select(User).where(User.id.in_(batch))).scalars().all():
                pre.users[u.id] = u
        for batch in _chunks(sorted(client_ids)):
            for c in db.execute(_select(Client).where(Client.id.in_(batch))).scalars().all():
                pre.clients[c.id] = c

        # Counts only — deliberately NOT `selectinload(Task.comments)`. The card needs two integers;
        # eager-loading the relationship would pull every comment BODY on the board (thousands of
        # rows of prose) to count them.
        task_ids = [t.id for t in tasks if t.id]
        pre.counts = {tid: (0, 0) for tid in task_ids}
        for batch in _chunks(task_ids):
            rows = db.execute(_select(TaskComment.task_id, TaskComment.attachments_json)
                              .where(TaskComment.task_id.in_(batch))).all()
            for tid, attachments in rows:
                have, files = pre.counts[tid]
                pre.counts[tid] = (have + 1, files + len(_loads(attachments, [])))
        return pre

    def user(self, db: Session, uid: int | None) -> User | None:
        if not uid:
            return None
        found = self.users.get(uid)
        if found is None:
            found = db.get(User, uid)
            if found is not None:
                self.users[uid] = found      # hold it, so the next card is free (see the docstring)
        return found

    def client(self, db: Session, cid: int | None) -> Client | None:
        if not cid:
            return None
        found = self.clients.get(cid)
        if found is None:
            found = db.get(Client, cid)
            if found is not None:
                self.clients[cid] = found
        return found

    def comment_counts(self, t: Task) -> tuple[int, int]:
        counted = self.counts.get(t.id)
        if counted is not None:
            return counted
        return (len(t.comments),
                sum(len(_loads(c.attachments_json, [])) for c in t.comments))


def maintask_list(t: Task, db: Session) -> list[dict]:
    """The two-level breakdown with assignees resolved to user_public (assignee cached per call)."""
    from .services import maintasks as MT

    mts = MT.normalize(getattr(t, "maintasks_json", "[]"), t.checklist_json)
    cache: dict[int, dict | None] = {}

    def usr(uid):
        if not uid:
            return None
        if uid not in cache:
            cache[uid] = user_public(db.get(User, uid))
        return cache[uid]

    return [{
        "id": m["id"], "title": m["title"],
        "assignee_id": m["assignee_id"], "assignee": usr(m["assignee_id"]),
        "subs": [{"id": s["id"], "text": s["text"], "done": s["done"],
                  "assignee_id": s["assignee_id"], "assignee": usr(s["assignee_id"])} for s in m["subs"]],
    } for m in mts]


def task_card(t: Task, db: Session, viewer: User | None = None,
              pre: "CardPrefetch | None" = None) -> dict:
    """Compact shape for the Kanban board.

    `viewer` adds the two viewer-relative fields below. They are **absent, never faked**, when no
    viewer is named (people.py's profile card lists somebody else's work, where "mine" answers
    nothing) — the same rule the Atrium bridge follows for fields the other side lacks.

    `pre` is a `CardPrefetch` covering the whole list being serialized. Optional and purely a
    performance concern — read its docstring before removing it, because two of the three costs it
    removes are invisible in this function's source.
    """
    from .services import maintasks as MT
    from .services import task_perms

    pre = pre if pre is not None else CardPrefetch()
    comment_count, attach_count = pre.comment_counts(t)
    client = pre.client(db, t.client_id)
    assignee = pre.user(db, t.assigned_to_id)
    creator = pre.user(db, getattr(t, "created_by_id", None))
    # Progress now spans the two-level breakdown (all sub-tasks of all main tasks); a legacy flat
    # checklist is migrated by normalize(), so the count stays correct for old tasks too.
    done, total = MT.sub_stats(MT.normalized(t))
    # 🔴 "Is this work on ME?" answered by the SERVER, from the one definition every permission in
    # task_perms already uses (2026-08-05). The Overview's strip and the board's "My work" button both
    # re-derived it as `assigned_to_id === me`, which is the narrower rule — so a card led by a
    # colleague with a step named to you sat on your board while the strip said "nothing on you right
    # now". `my_slots` is what lets a surface explain that: the card's lead is somebody else, and
    # these many phases/steps of it are yours.
    mine: dict = {}
    if viewer is not None:
        mine = {"mine": task_perms.is_assigned(viewer, t),
                "my_slots": task_perms.my_slot_count(viewer, t),
                # WHICH HAT the viewer wears on this card. `mine` alone cannot say: it is true whether
                # you lead the work, support it, or hold one step of it, and a list that renders all
                # three identically is indistinguishable from the July 2026 bug where a board showed
                # other people's work. The support half of what `my_slots` does for the breakdown.
                "supporting": task_perms.is_supporting(viewer, t),
                # 🔴 MAY THIS VIEWER TOUCH THIS CARD? Added 2026-08-14 with the department-read
                # branch in `task_perms.can_view`, and required by it. Before that, everything on an
                # employee's board was editable by definition (`can_edit` was `can_view` minus the
                # viewer seat), so the frontend could infer it and never asked. Now an employee's
                # board carries their whole DEPARTMENT, most of which is read-only to them — and a
                # card that renders draggable, then 403s on drop, is exactly the "the button is
                # broken" report this release is fixing elsewhere. The server answers instead of the
                # client guessing, so there is no second copy of the rule to drift.
                #
                # Viewer-relative, so it lives in this dict and follows the same absent-never-faked
                # contract as `mine`: people.py's profile card names no viewer and publishes neither.
                "can_edit": task_perms.can_edit(viewer, t)}
    # SUPPORT — many people, none accountable (models.TaskSupporter). On the CARD, not just the
    # drawer: the board has to show who is on a piece of work, and the whole reason this field exists
    # is that people were inventing checklist steps to get a second name onto a card.
    supporters = [user_public(u) for u in
                  (pre.user(db, sid) for sid in t.support_ids) if u is not None]
    return {
        **mine,
        # 🔴 Internal-only, like every other ownership field here — staffing never crosses to a
        # client. `task_bridge.SAFE` is the six client-safe fields and support is not one of them.
        "support_ids": t.support_ids,
        "support": supporters,
        "id": t.id,
        "title": t.title,
        "status": t.status,
        "priority": t.priority,
        "due_date": _d(t.due_date),
        "start_date": _d(getattr(t, "start_date", None)),
        "labels": _loads(t.labels_json, []),
        "client_id": t.client_id,
        "client_name": client.name if client else None,
        # 🔴 ON THE CARD, not just the drawer (2026-08-11). `campaign` is the optional grouping field
        # (docs/TASKBOARD_REBUILD.md §7), and per §4 of the task-placement guidelines it is the ONLY
        # thing that still connects work raised after a campaign launched: each of those is its own
        # one-line card by design. It reached `task_detail` alone, so the board could neither search
        # nor group by it — a grouping field only the drawer receives groups nothing.
        "campaign": t.campaign,
        "assigned_to_id": t.assigned_to_id,
        "assignee": user_public(assignee),
        "assigned_team_id": t.assigned_team_id,
        "created_by_id": getattr(t, "created_by_id", None),
        "created_by": user_public(creator),  # automatic creator tag (internal; never crosses to Atrium)
        # Planned ahead vs added during the day (services/task_origin). 🔴 `None` for the rows that
        # predate the column — genuinely unclassified, and the UI must print "—" rather than guess.
        # Internal, like every other field on this line: it says how the AGENCY works, not what the
        # client asked for, so it is not in `task_bridge.SAFE`.
        "origin": getattr(t, "origin", None),
        "comment_count": comment_count,
        "attachment_count": attach_count,
        "checklist_total": total,
        "checklist_done": done,
        "atrium_visible": t.atrium_visible,
        # The projection's real state, not just the old boolean: `atrium_task_id` proves a client
        # card exists, and `atrium_sync_error` non-null means that card is STALE. The board renders
        # the difference — a share that never happened must never look like a share that did.
        "atrium_task_id": getattr(t, "atrium_task_id", None),
        "atrium_sync_error": getattr(t, "atrium_sync_error", None),
        "atrium_shared": bool(getattr(t, "atrium_task_id", None)),
        # 🔴 The batch that adopted this row (WP 3.4), or null if a human raised it. Exposed because
        # it is the ONLY handle `task_adoption.revert()` takes, and nothing else surfaced it — the
        # runbook said "write the batch id down" and an operator who lost it (or who re-ran apply, so
        # the id they kept came from the no-op second run and is stamped on nothing) had no way to
        # recover it. Read-only and inert: it identifies a run, it does not change how the row behaves.
        "adoption_batch": getattr(t, "adoption_batch", None),
        # The workflow state a CARD has to show (Stage 2): a pause, a filed task, and where the
        # review stands. `hold_reason` is NOT here — it is internal prose and belongs in the drawer,
        # not on a card 60 people scroll past.
        "on_hold": bool(getattr(t, "on_hold", False)),
        "archived": bool(getattr(t, "archived", False)),
        "review_state": getattr(t, "review_state", None),
        # The client's open change requests (D4). Named to match the field an Atrium-owned card
        # already reports, so the board's pill renders identically whoever owns the row.
        "open_changes": getattr(t, "client_changes_open", 0) or 0,
        "completed_at": _iso(getattr(t, "completed_at", None)),
    }


def task_detail(t: Task, db: Session) -> dict:
    """Full task incl. internal fields (Sentinel users are all internal staff)."""
    d = task_card(t, db)
    am = db.get(User, t.account_manager_id) if t.account_manager_id else None
    team = db.get(Team, t.assigned_team_id) if t.assigned_team_id else None
    reviewer = db.get(User, t.reviewer_id) if getattr(t, "reviewer_id", None) else None
    d.update(
        {
            # Internal-only workflow detail (the drawer's, not the card's): why it is paused, where
            # Resume will put it back, and who decided the review.
            "hold_reason": getattr(t, "hold_reason", None),   # 🔒 internal — never crosses to Atrium
            "resume_to": getattr(t, "resume_to", None),
            "reviewer_id": getattr(t, "reviewer_id", None),
            "reviewer": user_public(reviewer),
            "description": t.description,
            # 🔴 `campaign` is NOT re-mapped here — `task_card` above already carries it (2026-08-11).
            # Two derivations of one field is exactly how this board's card and drawer disagreed about
            # an Atrium lead (AGENTS.md §2), and the drawer is fed by `task_card`'s output.
            "content_type": t.content_type,
            "service_charge": t.service_charge,               # internal-only; raw value for the edit form
            "service_charge_label": _money(t.service_charge),  # internal-only; "$4,200" for display

            "account_manager_id": t.account_manager_id,
            "account_manager": user_public(am),
            "assigned_team_name": team.name if team else None,
            # 🔴 `checklist` (the legacy flat list) was dropped from this payload 2026-08-04 (WP
            # 0.4). `maintasks` is the two-level breakdown every surface actually renders, and
            # `MT.normalize` migrates the old flat rows into it on read — so shipping both meant
            # sending the SAME steps twice, in two shapes, one of them stale the moment anybody
            # edited the breakdown. `checklist_json` stays on the model as the migration source.
            "maintasks": maintask_list(t, db),
            "deliverable_url": t.deliverable_url,
            "internal_notes": t.internal_notes,
            "client_facing_notes": t.client_facing_notes,
            "comments": [comment_dict(c, db) for c in sorted(t.comments, key=lambda c: c.id)],
            "history": [history_dict(h, db) for h in sorted(t.history, key=lambda h: h.id, reverse=True)],
            "created_at": _iso(t.created_at),
            "updated_at": _iso(t.updated_at),
        }
    )
    return d


def atrium_payload(t: Task, db: Session) -> dict:
    """The client-facing view of a task, for the audit trail and the share response.

    🔴 This is NOT the bridge payload. `task_bridge.client_safe_fields` is the one function that
    builds what actually crosses (in Atrium's field names) — keeping two builders in step failed
    once already, so this one is only ever read by humans.
    """
    client = db.get(Client, t.client_id) if t.client_id else None
    return {
        "task_id": t.id,
        "client": client.name if client else None,
        "campaign": t.campaign,
        "content_type": t.content_type,
        "title": t.title,
        "due_date": _d(t.due_date),
        "start_date": _d(getattr(t, "start_date", None)),
        "labels": _loads(t.labels_json, []),
        "deliverable_url": t.deliverable_url,
        "client_notes": t.client_facing_notes,
    }


def comment_dict(c: TaskComment, db: Session) -> dict:
    """One comment. EITHER a colleague or the client wrote it (D4 / WP 3.5).

    A client has no `users` row — and must not need one — so a client comment carries a
    `client_author` name instead of an `author_id`. `is_client` is what the UI keys off: a
    client's words on an internal thread need to be unmistakable, because the reply is written
    differently depending on who is going to read it.
    """
    author = user_public(db.get(User, c.author_id)) if c.author_id else None
    client_name = getattr(c, "client_author", None)
    return {
        "id": c.id,
        "author": author or ({"id": None, "name": client_name, "initials":
                              (client_name or "?")[:1].upper()} if client_name else None),
        "is_client": bool(client_name and not c.author_id),
        "body": c.body,
        "attachments": _loads(c.attachments_json, []),
        "created_at": _iso(c.created_at),
    }


def history_dict(h: TaskHistory, db: Session) -> dict:
    return {
        "id": h.id,
        "actor": user_public(db.get(User, h.changed_by_id)) if h.changed_by_id else None,
        "field": h.field_changed,
        "old_value": h.old_value,
        "new_value": h.new_value,
        "changed_at": _iso(h.changed_at),
    }


def summary_dict(s: DailyAttendanceSummary, user: User | None = None) -> dict:
    return {
        "id": s.id,
        "user_id": s.user_id,
        "user": user_public(user) if user else None,
        "date": _d(s.date),
        "clock_in": _iso(s.clock_in),
        "clock_out": _iso(s.clock_out),
        "break_duration_min": s.break_duration_min,
        "total_work_hours": s.total_work_hours,
        "status": s.status,
        "handover_note": s.handover_note,
    }


def attendance_request_dict(r: AttendanceRequest, db: Session) -> dict:
    return {
        "id": r.id,
        "user": user_public(db.get(User, r.user_id)),
        "date": _d(r.date),
        "request_type": r.request_type,
        "reason": r.reason,
        "old_value": r.old_value,
        "new_value": r.new_value,
        "status": r.status,
        "created_at": _iso(r.created_at),
    }


def gym_log_dict(g: GymLog, db: Session, with_exercises: bool = False) -> dict:
    d = {
        "id": g.id,
        "user_id": g.user_id,
        "user": user_public(db.get(User, g.user_id)),
        "date": _d(g.date),
        "day_type": g.day_type,
        "start_time": _iso(g.start_time),
        "end_time": _iso(g.end_time),
        "duration_minutes": g.duration_minutes,
        "status": g.status,
        "notes": g.notes,
        "exercise_count": len(g.exercises),
    }
    if with_exercises:
        d["exercises"] = [
            {
                "id": e.id,
                "exercise_name": e.exercise_name,
                "muscle_group": e.muscle_group,
                "weight_value": e.weight_value,
                "weight_unit": e.weight_unit,
                "sets": e.sets,
                "reps": e.reps,
                "set_type": e.set_type,
                "sets_detail": _loads(e.sets_json, []),
                "duration_minutes": e.duration_minutes,
                "notes": e.notes,
            }
            for e in g.exercises
        ]
    return d


def gym_routine_dict(r: GymRoutine) -> dict:
    """A saved workout template. ``total_sets`` is precomputed so the routine list can show the
    shape of a session without the frontend re-walking every set."""
    exercises = _loads(r.exercises_json, [])
    return {
        "id": r.id,
        "name": r.name,
        "day_type": r.day_type,
        "weekdays": _loads(r.weekdays_json, []),
        "exercises": exercises,
        "exercise_count": len(exercises),
        "total_sets": sum(len(e.get("sets") or []) for e in exercises if isinstance(e, dict)),
        "notes": r.notes,
        "updated_at": _iso(r.updated_at),
    }


# --- Development (holistic) -------------------------------------------------
def body_metric_dict(m: BodyMetric) -> dict:
    return {
        "id": m.id,
        "date": _d(m.date),
        "weight_kg": m.weight_kg,
        "body_fat_pct": m.body_fat_pct,
        "notes": m.notes,
    }


def pr_display(p: PersonalRecord) -> str:
    """Human-readable result: a weight PR shows 'Xkg x Y'; a cardio/other PR shows its free `detail`."""
    if p.weight_value:
        return f"{p.weight_value:g}{p.weight_unit or 'kg'} × {p.reps}"
    if p.detail:
        return p.detail
    return f"× {p.reps}" if p.reps else ""


def personal_record_dict(p: PersonalRecord) -> dict:
    return {
        "id": p.id,
        "exercise_name": p.exercise_name,
        "weight_value": p.weight_value,
        "weight_unit": p.weight_unit,
        "reps": p.reps,
        "detail": p.detail,
        "display": pr_display(p),
        "achieved_on": _d(p.achieved_on),
        "notes": p.notes,
    }


def development_profile_dict(p: DevelopmentProfile | None) -> dict:
    if not p:
        return {"headline": None, "resume_text": None, "resume_file_url": None}
    return {
        "headline": p.headline,
        "resume_text": p.resume_text,
        "resume_file_url": p.resume_file_url,
        "updated_at": _iso(p.updated_at),
    }


def achievement_dict(a: CareerAchievement) -> dict:
    return {
        "id": a.id,
        "title": a.title,
        "description": a.description,
        "achieved_on": _d(a.achieved_on),
    }


def goal_dict(g: ProfessionalGoal) -> dict:
    return {
        "id": g.id,
        "dimension": g.dimension or "professional",
        "title": g.title,
        "description": g.description,
        "target_date": _d(g.target_date),
        "status": g.status,
        "progress_pct": g.progress_pct,
        # created_at lets the hub compute expected-by-today pace against target_date.
        "created_at": _iso(g.created_at),
    }


def physical_goal_progress(g: PhysicalGoal) -> int:
    """0–100 progress toward a target PR. 'higher' = current/target; 'lower' (times)
    = target/current. Achieved pins to 100; degenerate values clamp rather than error."""
    if g.status == "achieved":
        return 100
    cur, tgt = g.current_value or 0, g.target_value or 0
    if g.direction == "lower":
        ratio = (tgt / cur) if cur > 0 else 0.0
    else:
        ratio = (cur / tgt) if tgt > 0 else 0.0
    return max(0, min(100, round(ratio * 100)))


def physical_goal_dict(g: PhysicalGoal) -> dict:
    return {
        "id": g.id,
        "name": g.name,
        "kind": g.kind,
        "target_value": g.target_value,
        "current_value": g.current_value,
        "unit": g.unit or "",
        "direction": g.direction or "higher",
        "notes": g.notes,
        "status": g.status,
        "progress_pct": physical_goal_progress(g),
        "created_at": _iso(g.created_at),
    }


def development_area_dict(a: DevelopmentArea) -> dict:
    """One growth dimension's settings. Ring % is NOT here — it comes from the Mastery Engine."""
    return {
        "dimension": a.dimension,
        "deadline": _d(a.deadline),
        "other_info": a.other_info,
        "updated_at": _iso(a.updated_at),
    }


def growth_item_dict(g: GrowthItem) -> dict:
    return {
        "id": g.id,
        # Legacy rows predate the column; they read as 'spiritual', where the journal used to live.
        "dimension": g.dimension or "spiritual",
        "kind": g.kind,
        "title": g.title,
        "detail": g.detail,
        "status": g.status,
        "created_at": _iso(g.created_at),
        "updated_at": _iso(g.updated_at),
    }


def skill_dict(s: Skill) -> dict:
    return {
        "id": s.id,
        "name": s.name,
        "level": s.level,
        "source": s.source,
        "note": s.note,
    }


def mentor_transcript_dict(t: MentorTranscript, full: bool = False) -> dict:
    """A mentor library entry. `full=False` (the list/hub view) omits `transcript_text` —
    it can be a whole video's worth of text — so the Growth page's /me payload stays light.
    The single-item endpoint passes full=True to return the text for viewing."""
    d = {
        "id": t.id,
        "mentor_name": t.mentor_name,
        "title": t.title,
        "source_url": t.source_url,
        "created_at": _iso(t.created_at),
    }
    if full:
        d["transcript_text"] = t.transcript_text
    return d


def reading_item_dict(r: ReadingItem, progress: ReadingProgress | None = None) -> dict:
    """A canon item, optionally merged with the current worker's progress on it."""
    d = {
        "id": r.id,
        "title": r.title,
        "author": r.author,
        "kind": r.kind,
        "url": r.url,
        "summary": r.summary,
        "required": r.required,
        "sort_order": r.sort_order,
    }
    d["progress"] = (
        {
            "status": progress.status,
            "reflection": progress.reflection,
            "rating": progress.rating,
        }
        if progress
        else {"status": "not_started", "reflection": None, "rating": None}
    )
    return d


def leave_type_dict(lt: LeaveType) -> dict:
    return {
        "id": lt.id,
        "name": lt.name,
        "annual_balance": lt.annual_balance,
        "accrual_type": lt.accrual_type,
        "requires_approval": lt.requires_approval,
        "carry_over_days": lt.carry_over_days,
    }


def leave_balance_dict(b: LeaveBalance, lt: LeaveType | None) -> dict:
    return {
        "id": b.id,
        "leave_type_id": b.leave_type_id,
        "leave_type": lt.name if lt else None,
        "year": b.year,
        "used": b.used,
        "remaining": b.remaining,
        "unlimited": bool(lt and lt.annual_balance < 0),
    }


def leave_request_dict(r: LeaveRequest, db: Session) -> dict:
    lt = db.get(LeaveType, r.leave_type_id)
    return {
        "id": r.id,
        "user": user_public(db.get(User, r.user_id)),
        "leave_type": lt.name if lt else None,
        "leave_type_id": r.leave_type_id,
        "start_date": _d(r.start_date),
        "end_date": _d(r.end_date),
        "total_days": r.total_days,
        "reason": r.reason,
        "status": r.status,
        "created_at": _iso(r.created_at),
    }


def notification_dict(n: Notification) -> dict:
    return {
        "id": n.id,
        "type": n.type,
        "title": n.title,
        "body": n.body,
        "link": n.link,
        "is_read": n.is_read,
        "created_at": _iso(n.created_at),
    }

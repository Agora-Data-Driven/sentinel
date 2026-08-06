"""Task Board: listing, CRUD, status moves (logged), comments, attachments, priority.

Authorization lives in one place — ``app/services/task_perms.py`` — not inline here. Board
vocabulary (statuses / priorities) is read from ``task_config`` (DB-backed, editable in Manage),
not from the enum constants.
"""
from __future__ import annotations

import json
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..events import broker

from ..constants import (
    NOTIF_TASK_ASSIGNED,
    ROLE_TEAM_LEAD,
    label_for_department,
)
from ..database import get_db
from ..models import (AtriumApproval, Client, RecurringService, Task, TaskComment, TaskHistory,
                      TaskRequest, TaskSupporter, Team, User)
from ..schemas import (
    CommentIn,
    RecurringServiceIn,
    TaskAdoptionApplyIn,
    TaskAdoptionRevertIn,
    TaskBulkIn,
    TaskCreateIn,
    TaskParkIn,
    TaskPriorityIn,
    TaskRequestDecisionIn,
    TaskReviewIn,
    TaskStatusIn,
    TaskUpdateIn,
)
from ..security import get_current_user, is_manager, require_roles
from ..serializers import atrium_payload, comment_dict, task_card, task_detail, user_public
from ..services import atrium_tasks
from ..services import audit
from ..services import task_analytics
from ..services import maintasks as maintasks_svc
from ..services import notifications as notif
from ..services import atrium_identity
from ..services import (task_adoption, task_bridge, task_config, task_perms, task_recurring,
                        task_templates, task_workflow)
from ..utils.time import today_ph, to_ph, utcnow

router = APIRouter(prefix="/api/tasks", tags=["tasks"])

AM_PLUS = ("account_manager", "admin", "super_admin")
_NOT_FOUND = "Task not found"
_FORBIDDEN = "Not permitted"


def _loads_labels(raw: str | None) -> list[str]:
    try:
        val = json.loads(raw or "[]")
    except (ValueError, TypeError):
        return []
    return [str(x) for x in val] if isinstance(val, list) else []


def _derived_labels(db: Session, team_id: int | None) -> list[str]:
    """The task's label list, computed from its department (decision D14).

    Always zero or one entry. Nobody picks a label any more: the old free vocabulary
    (Design/Copy/Ads/SEO/Dev) was a second taxonomy that duplicated the department and drifted from
    Atrium's, which derives the client-visible label the same way. An unrouted task gets NO label —
    inventing one would file untriaged work into a real bucket.
    """
    if not team_id:
        return []
    team = db.get(Team, team_id)
    lbl = label_for_department(team.name if team else None)
    return [lbl] if lbl else []


def _support_delegates(task: Task, want: list[int], actor_id: int) -> bool:
    """Does this support change involve anybody but the actor? (i.e. is it DELEGATION?)

    🔴 The same shape as `maintasks_svc.foreign_owner_changes`, and for the same reason: putting a
    name on a card puts that card on their board (`task_perms.assigned_user_ids`), so choosing WHO is
    a delegation decision even when the field looks like a plain list. This board has already shipped
    that hole twice — once for `maintasks[].assignee_id`, once for comparing owner SETS instead of
    slots — so the check lives where the field is WRITTEN, never in the UI.

    What stays open to every role is **joining and leaving yourself**: adding your own id, or removing
    it. That mirrors self-assignment on a step, and without it support would be unusable by the people
    who actually pick work up.
    """
    return bool((set(task.support_ids) ^ set(want)) - {actor_id})


def _apply_support(db: Session, task: Task, want: list[int], user: User) -> list[int]:
    """Reconcile `task_supporters` to `want`. Returns the ids newly ADDED (for notification).

    Only the difference is touched — an unchanged supporter keeps their original row, so
    `added_by_id`/`created_at` stay true instead of being rewritten by every unrelated PATCH that
    happens to resend the same list.

    Silently drops ids that are not active users rather than 400ing the whole edit: the list arrives
    from a multi-select that a stale page may have rendered before somebody was deactivated, and
    losing an entire edit to one dead id would be worse than staffing one fewer person. Deduplicated
    because the unique constraint would otherwise turn a double-selected name into an IntegrityError.
    """
    valid = {u.id for u in db.execute(
        select(User).where(User.id.in_(set(want)), User.is_active.is_(True))).scalars().all()} if want else set()
    have = set(task.support_ids)
    add, drop = valid - have, have - valid
    for row in list(task.supporters):
        if row.user_id in drop:
            db.delete(row)
    for uid in sorted(add):
        db.add(TaskSupporter(task_id=task.id, user_id=uid, added_by_id=user.id))
    if add or drop:
        names = lambda ids: ", ".join(  # noqa: E731 — local formatting helper, one use each side
            sorted((db.get(User, i).name if db.get(User, i) else str(i)) for i in ids)) or None
        _log(db, task.id, user.id, "support", names(have), names(valid))
    return sorted(add)


def _apply_status(db: Session, task: Task, new_status: str, user: User) -> str:
    """Move a Sentinel-owned task and leave the row in the canonical shape. Returns the old status.

    🔴 ONE definition, shared by `PATCH /{id}/status` and the bulk endpoint. Everything here is a
    consequence of the move rather than of the route that made it — the history entry, the
    completion stamp / approval spend / hold end (`on_status_change`), the client's card following
    ours across their board, the audit row and the SSE broadcast. A second copy in the bulk path
    would drift, and the first thing to rot would be the projection: cards moved in bulk would
    quietly stop matching what the client sees.

    Caller-owned, deliberately: existence, `can_move`, status validity and the review gate (D5).
    Bulk needs to SKIP a task that fails those, while the single route needs to raise.
    """
    old = task.status
    task.status = new_status
    _log(db, task.id, user.id, "status", old, new_status)
    task_workflow.on_status_change(db, task, old, new_status, user)
    if task_bridge.published(task):
        task_bridge.push_stage(db, task, user)
    db.commit()
    audit.record(db, actor_id=user.id, table_name="tasks", record_id=task.id, action="move",
                 old={"status": old}, new={"status": new_status})
    # (The "moving into review pings the AM" notification retired with the "For Review" status on
    # 2026-07-30 — there is no review column left to move into.)
    _broadcast("moved", task, user.id)
    return old


def _log(db: Session, task_id: int, actor_id: int, field: str, old, new) -> None:
    db.add(
        TaskHistory(
            task_id=task_id, changed_by_id=actor_id, field_changed=field,
            old_value=None if old is None else str(old),
            new_value=None if new is None else str(new),
        )
    )


def _broadcast(action: str, task: Task, actor_id: int) -> None:
    """Notify live boards that a task changed (SSE). Best-effort; never fails the request."""
    broker.publish({
        "type": "task", "action": action, "task_id": task.id,
        "status": task.status, "actor_id": actor_id,
    })


def _require_atrium(user: User) -> None:
    """Guard a READ of an Atrium-owned card. Scoping the board LIST (task_perms.can_view_atrium)
    would be theatre if the id still opened the card for someone the board hides it from — RBAC
    belongs on the endpoint, not in the rendering (AGENTS.md §3)."""
    if not task_perms.can_view_atrium(user):
        raise HTTPException(status_code=403, detail=_FORBIDDEN)


def _require_atrium_write(user: User) -> None:
    """Guard a WRITE to an Atrium-owned card.

    🔴 Every Atrium branch — read and write alike — used to call `_require_atrium`, i.e. "can you see
    client cards?". That was fine while seeing implied editing, and became a hole the moment a
    read-only seat existed (decision D8): a viewer could edit, move, comment on and resolve client
    work. `can_edit_atrium` is no longer an alias of `can_view_atrium`; this is where the difference
    is enforced.
    """
    if not task_perms.can_edit_atrium(user):
        raise HTTPException(status_code=403, detail=_FORBIDDEN)


def _atrium_error(err: str) -> HTTPException:
    """Turn a bridge failure into the right status. 404 ONLY when Atrium says the card is gone --
    a timeout or an unconfigured bridge must never reach the user as "that card was deleted"."""
    gone = err in (atrium_tasks.GONE, atrium_tasks.GONE_COMMENT)
    return HTTPException(status_code=404 if gone else 502, detail=err)


def _owner_index(db: Session) -> atrium_identity.Resolver:
    """The Atrium-roster -> Sentinel-user resolver, over every ACTIVE user.

    Built from the whole active roster, not from the caller's visible subset: whether a client card
    has a real owner is a fact about the card, not about who is looking at it. Scoping happens
    afterwards, where it belongs.
    """
    users = db.execute(select(User).where(User.is_active.is_(True))).scalars().all()
    return atrium_identity.build(users)


def _atrium_owner(index: atrium_identity.Resolver, task: dict) -> dict | None:
    """`user_public` of the Sentinel user this card's Atrium lead is, or None if unresolvable."""
    return user_public(index.resolve(task.get("lead_id"), task.get("lead_name")))


def _atrium_detail(db: Session, envelope: dict) -> dict:
    """An Atrium envelope as a Sentinel task_detail, with its client resolved the same way the
    board card resolves it (Client.atrium_client_id, then an unambiguous name match), and its lead
    resolved to the Sentinel user who is that person (so the drawer shows the same owner and photo
    the board card does — two surfaces disagreeing about the owner is the bug this all started as)."""
    clients = db.execute(select(Client)).scalars().all()
    task = envelope.get("task") or {}
    client = atrium_tasks.resolve_client(clients, task.get("client_key", ""),
                                         task.get("client_name", ""))
    return atrium_tasks.as_task_detail(envelope, client, _atrium_owner(_owner_index(db), task))


def _resolve_task(db: Session, task_id: str) -> Task | None:
    """Look up a Sentinel task by id. The board also renders Atrium-bridged cards, whose id is
    "atrium:<client_key>:<task_id>" (see atrium_tasks.as_board_card) -- not a Sentinel primary
    key, since those cards have no local Task row. A path param typed `int` would reject that
    id with a raw Pydantic 422 before this code ever runs; typing it `str` and parsing here
    turns it into an ordinary 404 instead (mirrors move_status's handling of the same id shape)."""
    try:
        return db.get(Task, int(task_id))
    except (TypeError, ValueError):
        return None


@router.get("")
def list_tasks(
    client_id: int | None = Query(None),
    team_id: int | None = Query(None),
    assignee_id: int | None = Query(None),
    unassigned: bool = Query(False, description="Only cards with no assignee (the board's "
                                                "'Unassigned' choice in the assignee filter)."),
    status: str | None = Query(None),
    priority: str | None = Query(None),
    archived: bool = Query(False, description="Past work instead of the live board: filed tasks "
                                              "ONLY. The board never mixes the two."),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = select(Task).order_by(Task.updated_at.desc())
    # Filed work is a SEPARATE list, not extra cards on the board (M4). Left in the Completed
    # column, finished services turn it into a graveyard and every count stops meaning anything —
    # so the default board excludes them and `?archived=1` is the Past work drawer.
    q = q.where(Task.archived.is_(True)) if archived else q.where(Task.archived.is_(False))
    if client_id:
        q = q.where(Task.client_id == client_id)
    if team_id:
        q = q.where(Task.assigned_team_id == team_id)
    if assignee_id:
        q = q.where(Task.assigned_to_id == assignee_id)
    # "Unassigned" is a real answer to "who is this on?", and it cannot be expressed as an id --
    # a manager triaging the board needs it more than any single name. Ignored when an actual
    # assignee was named (a card can't be both).
    if unassigned and not assignee_id:
        q = q.where(Task.assigned_to_id.is_(None))
    if status:
        q = q.where(Task.status == status)
    if priority:
        q = q.where(Task.priority == priority)
    tasks = [t for t in db.execute(q).scalars().all() if task_perms.can_view(user, t)]
    # `viewer=user` is what puts `mine`/`my_slots` on each card — the server's own "assigned" rule
    # (task_perms.is_assigned, which is also what filtered this list), so no surface has to guess it.
    cards = [task_card(t, db, viewer=user) for t in tasks]
    # ATRIUM BRIDGE: Atrium owns the client-facing tasks (one workspace JSON per client), so a card
    # typed into a client's Atrium board must appear here too -- this board is the team's
    # cross-client window onto the same work, not a second system. Best-effort: if the bridge is
    # off or Atrium is unreachable, the board still renders Sentinel's own rows.
    # MANAGERS ONLY (task_perms.can_view_atrium): these cards belong to no Sentinel user, so on an
    # employee's/intern's board -- which shows the work assigned to them -- they are pure noise.
    # ...and never on the Past work list: filing is a SENTINEL act (tasks.archived), so an Atrium
    # card cannot be filed and must not pad a list that claims to show what was.
    if atrium_tasks.enabled() and task_perms.can_view_atrium(user) and not archived:
        # Resolve each Atrium workspace to its Sentinel Client so the board's client filter and
        # client name work on Atrium cards too: Client.atrium_client_id is the explicit bridge,
        # with an unambiguous name match as a fallback while those links are still unset.
        clients = db.execute(select(Client)).scalars().all()
        # 🔴 WP 4.3 — ONE piece of work is ONE card. A Sentinel row that carries `atrium_task_id`
        # IS the card Atrium is about to hand back, so appending the bridge's copy too would render
        # it twice: once as the real row (assignable, parkable, reviewable, counted) and once as a
        # read-only ghost that drifts away from it the moment either is moved. This closes a hole
        # that opened the day Send to Atrium began really publishing (2026-08-03) and that adoption
        # (3.4) would have widened to every client card at once. The linked row wins because it is
        # the one that can do anything; the ghost is dropped.
        linked = task_adoption.claimed_atrium_ids(db)
        # One resolver for the whole board — it indexes the user table once, not once per card.
        owners = _owner_index(db)
        for a in atrium_tasks.fetch_tasks():
            if (a.get("client_key", ""), str(a.get("task_id") or "")) in linked:
                continue
            # `viewer_id` is what puts `mine` on the card — the board's "My work" button dropped every
            # client card without it, while the same card sat in that person's By Employee lane.
            card = atrium_tasks.as_board_card(
                a, atrium_tasks.resolve_client(clients, a.get("client_key", ""),
                                               a.get("client_name", "")),
                _atrium_owner(owners, a), viewer_id=user.id)
            if status and card["status"] != status:
                continue
            if priority and card["priority"] != priority:
                continue
            if client_id and card["client_id"] != client_id:
                continue
            # An Atrium card still has no Sentinel TEAM, so that filter excludes it. The ASSIGNEE
            # filter now agrees with what the card renders (2026-08-05): a card whose Atrium lead
            # resolved to a Sentinel user claims that assignee, so filtering by that person must
            # KEEP it — dropping it while the card visibly shows their name and photo is the same
            # class of contradiction the "Unassigned" bug was. An unresolved card claims nobody and
            # is still excluded from a by-person filter, exactly as before.
            if team_id:
                continue
            if assignee_id and card["assigned_to_id"] != assignee_id:
                continue
            cards.append(card)
    return cards


def _aggregate(pts: list[Task], today, week_start, all_statuses, done_statuses: set[str],
               person_id: int | None = None) -> dict:
    """Roll a single person's tasks into the Monitor row's counts.

    Two things this gets right that it used to get wrong:

    * **"Done" is decided by STAGE, not by the label `Completed`** (`done_statuses` comes from
      `task_config.is_completed`), so renaming the column — or adding a second done column — keeps
      the numbers honest.
    * **Throughput counts `completed_at`, not `updated_at`** (§2.4h). Off `updated_at`, fixing a
      typo on a task finished in March re-dated its completion to today and inflated this week.
      Rows completed before the column existed have no stamp and are simply not counted, which is
      the honest answer — better than counting them on whatever day someone last touched them.

    Filed work (`archived`) is off the plate, so it adds no column count and no overdue — but it
    STILL counts toward this week's throughput. Filing a shipped task must not erase the fact that
    it shipped, which is what excluding archived rows outright would do.
    """
    counts = dict.fromkeys(all_statuses, 0)
    overdue = completed_week = live = stepped = supporting = 0
    for t in pts:
        if t.status in done_statuses:
            done_on = getattr(t, "completed_at", None)
            if done_on and to_ph(done_on).date() >= week_start:
                completed_week += 1
        if getattr(t, "archived", False):
            continue
        live += 1
        counts[t.status] = counts.get(t.status, 0) + 1
        if t.status not in done_statuses:
            # WHY a row's number is what it is. A row reading "12 open" where 9 are somebody else's
            # cards is a different working life from 12 of your own, and until 2026-08-05 this rollup
            # could not see those at all.
            #
            # 🔴 The two are counted SEPARATELY and do not overlap (2026-08-06). Support used to fall
            # into `stepped`, which the UI renders as "N as steps" — so a person put on a card as
            # SUPPORT was described as owning steps of it, which may be zero steps. The label has to
            # match the reason, or the Monitor is confidently wrong about how somebody's day is spent.
            # Support wins the tie: being named on the card is the bigger fact than holding a step of it.
            if person_id is not None and t.assigned_to_id != person_id:
                if person_id in {s.user_id for s in (t.supporters or [])}:
                    supporting += 1
                else:
                    stepped += 1
            if t.due_date and t.due_date < today:
                overdue += 1
    open_total = sum(n for st, n in counts.items() if st not in done_statuses)
    return {"counts": counts, "overdue": overdue, "open_total": open_total,
            "completed_week": completed_week, "total": live, "stepped": stepped,
            "supporting": supporting}


@router.get("/summary")
def employee_summary(days: int = Query(30, ge=7, le=180,
                                       description="Trailing window (days) for cycle time and the "
                                                   "on-time rate. The column counts are always LIVE."),
                     user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Per-employee task rollup for the Monitor view (managers only).

    Scope mirrors the board's `_can_view`: admins / super-admin / account managers see everyone;
    a team lead sees only their own team. Employees / interns get a 403 — monitoring is a
    management surface. Declared BEFORE `/{task_id}` so "summary" isn't parsed as a task id.

    🔴 **Bucketed by `task_perms.assigned_user_ids`, not by `assigned_to_id` (2026-08-05).** This
    rollup used to key on the card's lead alone, so anyone whose work arrives as phases/steps of
    colleagues' cards — which is how delegation on this board actually looks — read as **idle** on
    the Monitor, and any KPI layered on top inherited that. It is the same blind spot the Overview's
    "my work" strip had; there is one definition of "assigned" now and both surfaces use it.

    🔴 **Consequence: the rows do NOT sum to the number of tasks.** A card with a build phase on one
    person and a QA step on another is on two plates and is counted on both — which is the truth
    about shared work. `stepped` says how much of a row arrived that way, and the UI labels the
    total accordingly. Do not "fix" this by attributing each card to one person: picking a winner
    would re-hide exactly the work this change surfaced.

    Everything beyond the counts is DERIVED (`services/task_analytics.py`) — no new columns. A task
    on this board carries no size, so none of these is an effort measure and `load_band` is
    explicitly relative to this cohort's own median. See that module's docstring before adding to it.
    """
    # A READ, so the read-only seat belongs here — monitoring is the entire point of that seat (D8).
    # `is_manager` alone would have excluded it, which is the shape of mistake §5.3 warns about:
    # a viewer must be added to every read surface EXPLICITLY, because its rank grants nothing.
    if not (is_manager(user) or task_perms.is_read_only(user)):
        raise HTTPException(status_code=403, detail="Only managers can monitor the team")

    # Who this manager may see: all active staff, or (team lead) just their own team.
    people = db.execute(select(User).where(User.is_active.is_(True))).scalars().all()
    if user.role == ROLE_TEAM_LEAD:
        people = [p for p in people if p.team_id == user.team_id]
    people = sorted(people, key=lambda p: (p.name or "").lower())

    # Filed rows are fetched too: they are off people's plates but they are exactly what "Done · 7d"
    # is counting. `_aggregate` draws that line, not this query.
    tasks = db.execute(select(Task)).scalars().all()
    by_person: dict[int, list[Task]] = {}
    for t in tasks:
        # One parse of the breakdown per TASK (not per person per task) — that is what the set form
        # of the rule exists for. A card lands in every plate it is actually on.
        for uid in task_perms.assigned_user_ids(t):
            by_person.setdefault(uid, []).append(t)

    today = today_ph()
    week_start = today - timedelta(days=7)
    window_start = today - timedelta(days=days)
    all_statuses = task_config.statuses(db)
    done_statuses = {s for s in all_statuses if task_config.is_completed(db, s)}
    leave = task_analytics.leave_context(db, [p.id for p in people], today)

    # 🔴 ATRIUM CLIENT WORK COUNTS TOO (2026-08-05). This rollup queried Sentinel's own `tasks` table
    # only, so every card Atrium owns — the bulk of delivery for some people — counted toward NOBODY's
    # workload: a person holding fifteen client cards read as idle on the table a manager staffs from.
    # Joined on the Atrium lead's EMAIL, the only honest key (an Atrium owner is a roster email, not a
    # Sentinel id); a lead with no Sentinel account matches nothing and is counted for no one.
    #
    # FAIL-SOFT, like every other read of this bridge: `fetch_tasks` returns [] on an unset secret, a
    # timeout, a non-200 or a malformed body. An Atrium outage must cost a manager the client half of
    # these numbers, never the whole page.
    client_counts: dict[int, int] = {}
    if atrium_tasks.enabled():
        # 🔴 Resolved through `atrium_identity`, NOT by an exact email match. Atrium's roster and
        # Sentinel's users disagree on the domain for the same human (@agoradatadriven.com vs
        # @agora.ph vs @100.digital, plus Gmail-based portal accounts), so `email ==` resolved almost
        # nobody and client work counted toward nobody — which is exactly what "the Monitor says
        # Unassigned" was. The resolver's ladder and its refuse-when-ambiguous rule live in that
        # module; `people` bounds it to whom this caller may see.
        index = atrium_identity.build(people)
        # Cards already CLAIMED by a Sentinel row are that row now — counting both double-counts the
        # same work, exactly as it would render twice on the board (WP 4.3).
        claimed = task_adoption.claimed_atrium_ids(db)
        fresh = [c for c in atrium_tasks.fetch_tasks()
                 if (c.get("client_key", ""), str(c.get("task_id") or "")) not in claimed]
        # Resolve Atrium's STAGE to Sentinel's current label — never trust the label it sends, which
        # is renameable on both sides (D13). An unresolvable stage keeps whatever Atrium called it and
        # simply renders no segment on the workload bar.
        def _status_of(card):
            return task_config.status_for_stage(db, card.get("stage") or "") or card.get("status")

        for uid, rows in task_analytics.atrium_workload(fresh, index, _status_of).items():
            by_person.setdefault(uid, []).extend(rows)
            client_counts[uid] = len(rows)

    rows = []
    for p in people:
        mine = by_person.get(p.id, [])
        live_open = [t for t in mine
                     if not getattr(t, "archived", False) and t.status not in done_statuses]
        rows.append({
            "user": user_public(p),
            **_aggregate(mine, today, week_start, all_statuses, done_statuses, person_id=p.id),
            **task_analytics.delivery(mine, window_start, done_statuses),
            **task_analytics.aging(live_open, today),
            **leave.get(p.id, {"on_leave_today": False, "leave_days_ahead": 0}),
            # The threshold `stale_open` was counted with, so the UI can LABEL the column instead of
            # hardcoding "14d" beside a number the server might later compute differently. Repeated
            # per row rather than wrapped in an envelope: the list shape is what four test files and
            # `renderMonitor` already consume, and a gratuitous reshape is how a stale
            # cached script starts rendering "undefined" (AGENTS.md §5).
            "stale_days": task_analytics.STALE_DAYS,
            # How many of this row's cards are Atrium's. Exposed because those cards carry no
            # `completed_at`, so they are in Open/Overdue/Sitting and NOT in Cycle/On-time/Done —
            # without saying so, somebody who delivers mostly client work looks like they never ship.
            "client_cards": client_counts.get(p.id, 0),
        })
    # Relative bands are computed across the rows the CALLER can see, so a team lead is compared
    # against their own team rather than against the whole company — the cohort on screen is the
    # cohort the comparison claims to be about.
    task_analytics.apply_load_bands(rows)
    # Heaviest / most-behind first is what a manager wants to see.
    rows.sort(key=lambda r: (r["overdue"], r["open_total"]), reverse=True)
    return rows


def _recurring_dict(r, db: Session) -> dict:
    client = db.get(Client, r.client_id) if r.client_id else None
    team = db.get(Team, r.assigned_team_id) if r.assigned_team_id else None
    return {
        "id": r.id, "title": r.title, "cadence": r.cadence,
        "day_of_period": r.day_of_period, "due_in_days": r.due_in_days,
        "priority": r.priority, "is_active": bool(r.is_active),
        "service_key": r.service_key,
        "client_id": r.client_id, "client_name": client.name if client else None,
        "assigned_team_id": r.assigned_team_id, "team_name": team.name if team else None,
        "assignee": user_public(db.get(User, r.assigned_to_id)) if r.assigned_to_id else None,
        # The period already generated. Surfaced because "why hasn't this month's appeared?" is
        # the only question anyone ever asks about a recurrence, and this is the answer.
        "last_period": r.last_period,
        "next_due": task_recurring.trigger_day(r, today_ph()).isoformat(),
    }


# 🔴 Declared BEFORE `GET /{task_id}` or FastAPI matches "recurring" as a task id (AGENTS.md §5).
@router.get("/recurring", dependencies=[Depends(require_roles(*AM_PLUS))])
def list_recurring(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Retainer deliverables that generate themselves (WP 6.1, M10)."""
    rows = db.execute(select(RecurringService).order_by(RecurringService.title)).scalars().all()
    return [_recurring_dict(r, db) for r in rows]


@router.post("/recurring", dependencies=[Depends(require_roles(*AM_PLUS))])
def create_recurring(payload: RecurringServiceIn,
                     user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Set up a recurrence.

    🔴 It is stamped with the CURRENT period on creation whenever this period's trigger day has
    already passed, so it can never retro-generate work for months it did not exist for. Setting
    up "the 10th" on the 5th still fires this month; setting it up on the 20th starts next month.
    """
    if payload.priority not in task_config.priorities(db):
        raise HTTPException(status_code=400, detail="Invalid priority")
    rec = RecurringService(
        title=payload.title[:200], client_id=payload.client_id,
        service_key=payload.service_key, assigned_team_id=payload.assigned_team_id,
        assigned_to_id=payload.assigned_to_id, priority=payload.priority,
        cadence=payload.cadence, day_of_period=payload.day_of_period,
        due_in_days=payload.due_in_days, is_active=payload.is_active,
        created_by_id=user.id,
    )
    task_recurring.seed_period(rec, today_ph())
    db.add(rec)
    db.commit()
    db.refresh(rec)
    audit.record(db, actor_id=user.id, table_name="recurring_services", record_id=rec.id,
                 action="create", new={"title": rec.title, "cadence": rec.cadence})
    return _recurring_dict(rec, db)


@router.patch("/recurring/{rec_id}", dependencies=[Depends(require_roles(*AM_PLUS))])
def update_recurring(rec_id: int, payload: RecurringServiceIn,
                     user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rec = db.get(RecurringService, rec_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Recurring service not found")
    for field in ("title", "client_id", "service_key", "assigned_team_id", "assigned_to_id",
                  "priority", "cadence", "day_of_period", "due_in_days", "is_active"):
        setattr(rec, field, getattr(payload, field))
    # 🔴 `last_period` is deliberately NOT reset by an edit. Renaming a recurrence, or fixing its
    # owner, must never cause this period's task to be generated a second time.
    db.commit()
    return _recurring_dict(rec, db)


@router.delete("/recurring/{rec_id}", dependencies=[Depends(require_roles(*AM_PLUS))])
def delete_recurring(rec_id: int, user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    """Stop a recurrence. Tasks it already generated are ordinary tasks and are left alone."""
    rec = db.get(RecurringService, rec_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Recurring service not found")
    db.delete(rec)
    db.commit()
    audit.record(db, actor_id=user.id, table_name="recurring_services", record_id=rec_id,
                 action="delete", old={"title": rec.title})
    return {"ok": True}


@router.post("/recurring/run", dependencies=[Depends(require_roles(*AM_PLUS))])
def run_recurring_now(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Generate anything due right now, without waiting for the nightly tick.

    Safe to press twice: each recurrence claims its period, so the second press creates nothing.
    """
    return task_recurring.run(db, today_ph(), user)


_SUPER = ("super_admin",)


@router.get("/adoption/plan", dependencies=[Depends(require_roles(*_SUPER))])
def adoption_plan(client: str = Query(..., min_length=1),
                  user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """What adopting this workspace's Atrium cards WOULD do (WP 3.4). Writes nothing.

    Super-admin only, and `client` is required: adoption is the one work package that touches live
    client data, so a mistake should be one workspace's problem rather than the estate's.
    """
    try:
        return task_adoption.plan(db, client)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/adoption/apply", dependencies=[Depends(require_roles(*_SUPER))])
def adoption_apply(payload: TaskAdoptionApplyIn,
                   user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Actually import them. A DIFFERENT endpoint from the plan, on purpose.

    🔴 Requires `confirm` to equal the client key. Not ceremony: this writes rows derived from live
    client data, and a typed confirmation is the difference between "I ran the plan and read it"
    and "I posted the wrong body". There is deliberately no `dry_run=false` flag anywhere — the
    safe call and the dangerous one are different URLs.

    Reversible via `POST /adoption/revert` with the returned batch id.
    """
    if payload.confirm != payload.client:
        raise HTTPException(
            status_code=400,
            detail="To apply, `confirm` must repeat the client key exactly. Run the plan first.")
    batch = payload.batch or f"adopt-{payload.client}-{int(utcnow().timestamp())}"
    try:
        result = task_adoption.apply(db, payload.client, batch, user)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    audit.record(db, actor_id=user.id, table_name="tasks", record_id=0, action="adopt",
                 new={"client": payload.client, "batch": batch,
                      "created": result["counts"]["created"]})
    return result


@router.post("/adoption/revert", dependencies=[Depends(require_roles(*_SUPER))])
def adoption_revert(payload: TaskAdoptionRevertIn,
                    user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Undo one adoption run. Rows that have been worked on since are KEPT and reported."""
    try:
        result = task_adoption.revert(db, payload.batch)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    audit.record(db, actor_id=user.id, table_name="tasks", record_id=0, action="adopt-revert",
                 new={"batch": payload.batch, **result["counts"]})
    return result


@router.get("/throughput")
def throughput_history(weeks: int = Query(8, ge=2, le=26),
                       user: User = Depends(get_current_user),
                       db: Session = Depends(get_db)):
    """Completed work over TIME, plus a per-client rollup (WP 6.2, §2.4i).

    Monitor computed everything from the live table: a snapshot with no trend, no history, and no
    per-client view — so "are we getting faster?" and "which client is eating the team?" were
    questions the board could not answer at all.

    🔴 Counted off `completed_at`, never `updated_at` (§2.4h). Off `updated_at`, fixing a typo on a
    task finished in March re-dates its completion to today. Rows finished before that column
    existed carry no stamp and are simply not counted — the honest answer, and better than
    attributing them to whenever somebody last touched them.

    🔴 The CURRENT week is partial and is flagged `complete: false`. A 2-day week against a 7-day
    mean reads as a collapse in throughput; the caller may chart it but must not compare it. This
    is the same trap the report deck hit (`_weeks`/`pressure` there) and it is worth the extra
    field to make un-missable.

    Weeks are Asia/Manila and start on Monday, matching the business rule the rest of the board
    uses. Archived tasks still count: filing shipped work must never erase that it shipped.
    """
    if not (is_manager(user) or task_perms.is_read_only(user)):
        raise HTTPException(status_code=403, detail="Only managers can monitor the team")

    today = today_ph()
    this_week_start = today - timedelta(days=today.weekday())      # Monday
    first_week_start = this_week_start - timedelta(weeks=weeks - 1)

    # Same scope as the Monitor rollup: a team lead sees their own team, AM+ sees everyone.
    visible_ids = None
    if user.role == ROLE_TEAM_LEAD:
        visible_ids = {u.id for u in db.execute(
            select(User).where(User.team_id == user.team_id)).scalars().all()}

    done_statuses = {s for s in task_config.statuses(db) if task_config.is_completed(db, s)}
    rows = db.execute(select(Task).where(Task.completed_at.is_not(None))).scalars().all()

    buckets = {first_week_start + timedelta(weeks=i): 0 for i in range(weeks)}
    per_person: dict[int, int] = {}
    per_client: dict[int | None, int] = {}

    for t in rows:
        if t.status not in done_statuses:
            continue                       # reopened since: not finished work today
        if visible_ids is not None and t.assigned_to_id not in visible_ids:
            continue
        done_on = to_ph(t.completed_at).date()
        wk = done_on - timedelta(days=done_on.weekday())
        if wk not in buckets:
            continue                       # outside the window
        buckets[wk] += 1
        if t.assigned_to_id:
            per_person[t.assigned_to_id] = per_person.get(t.assigned_to_id, 0) + 1
        per_client[t.client_id] = per_client.get(t.client_id, 0) + 1

    series = [{"week_start": wk.isoformat(),
               "week_end": (wk + timedelta(days=6)).isoformat(),
               "completed": n,
               # The one field that stops a partial week being read as a crash.
               "complete": wk != this_week_start}
              for wk, n in sorted(buckets.items())]

    finished = [w["completed"] for w in series if w["complete"]]
    people = {p.id: p for p in db.execute(select(User)).scalars().all()}
    clients = {c.id: c for c in db.execute(select(Client)).scalars().all()}

    return {
        "weeks": series,
        # Averaged over COMPLETE weeks only, for the same reason.
        "weekly_average": round(sum(finished) / len(finished), 1) if finished else 0,
        "by_person": sorted(
            [{"user": user_public(people[uid]), "completed": n}
             for uid, n in per_person.items() if uid in people],
            key=lambda r: r["completed"], reverse=True),
        "by_client": sorted(
            [{"client_id": cid,
              "client_name": clients[cid].name if cid in clients else "No client",
              "completed": n}
             for cid, n in per_client.items()],
            key=lambda r: r["completed"], reverse=True),
    }


@router.get("/templates")
def list_templates(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Service-template catalog for the New Task picker (DB-backed). Declared before /{task_id}."""
    return task_templates.catalog(db)


@router.get("/filed-by-me")
def filed_by_me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Where the work I raised for someone else ended up (§2.4d, decision D10).

    🔴 This list exists because of a deliberate gap, not to fill a hole in `can_view`. Routing a card
    to another team takes it OFF the filer's board — the creator tag stopped granting board
    visibility in July 2026, and reversing that is what put other people's work back on an intern's
    board. But "I filed it and now I can't find it" is its own bug, so the answer is a SEPARATE list
    that answers only "where did it go": team, current owner or *awaiting triage*, status, client.

    No internal fields. Not priority, not the charge, not the internal notes, not the breakdown — the
    filer may have no business seeing those on a card that is now another department's.

    Declared BEFORE `GET /{task_id}` on purpose: FastAPI matches in declaration order, so a
    single-segment literal written after it is swallowed and answers 404/422 instead (AGENTS.md §5,
    the same trap `/api/gym/routines` hit).
    """
    rows = db.execute(
        select(Task).where(Task.created_by_id == user.id, Task.archived.is_(False))
        .order_by(Task.updated_at.desc())
    ).scalars().all()
    out = []
    for t in rows:
        # A refusal is the one thing the filer MUST be told, and it lives in history rather than in
        # two columns on `tasks` (D11). Internal means "never crosses to the client", not "hidden
        # from the person whose card it is".
        bounce = db.execute(
            select(TaskHistory).where(TaskHistory.task_id == t.id,
                                      TaskHistory.field_changed == "sent_back")
            .order_by(TaskHistory.id.desc())
        ).scalars().first()
        # Only work that LEFT me — a card I raised and still hold is just my work, already on my
        # board. The ONE exception is a card that was sent BACK to me: a bounce re-assigns it to me,
        # so the plain filter would hide the very row that explains why it returned.
        if t.assigned_to_id == user.id and not bounce:
            continue
        team = db.get(Team, t.assigned_team_id) if t.assigned_team_id else None
        owner = db.get(User, t.assigned_to_id) if t.assigned_to_id else None
        client = db.get(Client, t.client_id) if t.client_id else None
        out.append({
            "id": t.id,
            "title": t.title,
            "status": t.status,
            "client_name": client.name if client else None,
            "team_name": team.name if team else None,
            "owner_name": owner.name if owner else None,
            "awaiting_triage": t.assigned_to_id is None and t.assigned_team_id is not None,
            "on_hold": bool(t.on_hold),
            "sent_back_reason": bounce.new_value if bounce else None,
            "updated_at": to_ph(t.updated_at).isoformat() if t.updated_at else None,
        })
    return out


def _request_dict(r: TaskRequest, db: Session) -> dict:
    client = db.get(Client, r.client_id) if r.client_id else None
    return {
        "id": r.id, "title": r.title, "details": r.details,
        "client_key": r.client_key, "client_id": r.client_id,
        "client_name": client.name if client else None,
        "requester_name": r.requester_name, "requester_email": r.requester_email,
        "status": r.status, "task_id": r.task_id, "decline_reason": r.decline_reason,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "decided_at": r.decided_at.isoformat() if r.decided_at else None,
        "decided_by": user_public(db.get(User, r.decided_by_id)) if r.decided_by_id else None,
    }


# 🔴 Declared BEFORE `GET /{task_id}` or FastAPI matches "requests" as a task id (AGENTS.md §5).
@router.get("/requests", dependencies=[Depends(require_roles(*AM_PLUS))])
def list_requests(status_filter: str = Query("pending", alias="status"),
                  user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """The intake queue (D3, WP 3.3): what clients have asked for, awaiting triage.

    Manager-only. A request is a client's ask, not work — deciding whether the agency takes it on
    is a commercial call, not something to leave on an employee's board.
    """
    q = select(TaskRequest).order_by(TaskRequest.created_at.desc())
    if status_filter and status_filter != "all":
        q = q.where(TaskRequest.status == status_filter)
    rows = db.execute(q).scalars().all()
    pending = db.execute(
        select(func.count(TaskRequest.id)).where(TaskRequest.status == "pending")
    ).scalar() or 0
    return {"requests": [_request_dict(r, db) for r in rows], "pending": pending}


@router.post("/requests/{request_id}/accept", dependencies=[Depends(require_roles(*AM_PLUS))])
def accept_request(request_id: int, payload: TaskRequestDecisionIn,
                   user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Turn a client's ask into a real task. THIS is the moment it reaches the delivery board.

    Everything the triager sets here is optional except the decision itself — the point is that a
    human looked at it and said yes, not that they filled a form. The new task is an ordinary
    Sentinel task in every respect, including D14's derived label and D6's share-on-create, so an
    accepted request is indistinguishable from work the team raised itself.

    🔴 A decision is TERMINAL. The client has already been told; re-deciding would mean telling
    them something different later, so a request that is not pending is a 409, not an overwrite.
    """
    req = db.get(TaskRequest, request_id)
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")
    if req.status != "pending":
        raise HTTPException(status_code=409, detail=f"That request was already {req.status}.")

    team_id = payload.assigned_team_id
    task = Task(
        title=payload.title or req.title,
        description=req.details,
        client_id=req.client_id,
        assigned_team_id=team_id,
        assigned_to_id=payload.assigned_to_id,
        account_manager_id=user.id,
        created_by_id=user.id,
        priority=payload.priority or "Medium",
        status=task_config.statuses(db)[0],
        due_date=payload.due_date,
        labels_json=json.dumps(_derived_labels(db, team_id)),
        # The client asked for this, so they are told about it by default (D6) — the ask becoming
        # visible work is the whole answer to "what happened to my request?".
        client_facing_notes=req.details,
    )
    db.add(task)
    db.flush()
    _log(db, task.id, user.id, "created", None, f"accepted client request #{req.id}")

    req.status = "accepted"
    req.decided_by_id = user.id
    req.decided_at = utcnow()
    req.task_id = task.id
    db.commit()

    if task.client_id is not None and task_perms.can_bridge(user):
        task_bridge.publish(db, task, user)
        db.commit()

    audit.record(db, actor_id=user.id, table_name="task_requests", record_id=req.id,
                 action="accept", new={"task_id": task.id})
    if task.assigned_to_id:
        notif.notify(db, user_id=task.assigned_to_id, type=NOTIF_TASK_ASSIGNED,
                     title=f"New task assigned: {task.title}", link=f"/tasks?open={task.id}")
    elif task.assigned_team_id:
        _notify_team_routed(db, task, user)
        db.commit()
    _broadcast("created", task, user.id)
    return {"ok": True, "request": _request_dict(req, db), "task": task_detail(task, db)}


@router.post("/requests/{request_id}/decline", dependencies=[Depends(require_roles(*AM_PLUS))])
def decline_request(request_id: int, payload: TaskRequestDecisionIn,
                    user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Say no, on the record, with a reason.

    Declining is a first-class outcome, not a delete: "we are not doing this, because…" is an
    answer the client is owed and the agency should be able to point at later. A request that
    quietly disappears is how the same ask gets raised four times.
    """
    req = db.get(TaskRequest, request_id)
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")
    if req.status != "pending":
        raise HTTPException(status_code=409, detail=f"That request was already {req.status}.")
    reason = (payload.reason or "").strip()
    if not reason:
        raise HTTPException(status_code=400, detail="Give a reason — the client is owed one.")
    req.status = "declined"
    req.decided_by_id = user.id
    req.decided_at = utcnow()
    req.decline_reason = reason
    db.commit()
    audit.record(db, actor_id=user.id, table_name="task_requests", record_id=req.id,
                 action="decline", new={"reason": reason})
    return {"ok": True, "request": _request_dict(req, db)}


@router.get("/{task_id}")
def get_task(task_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # An Atrium-owned card (id "atrium:<client_key>:<task_id>") has no local row -- its detail is
    # read across the bridge and mapped into the same shape the drawer already renders. It used to
    # be a dead end here ("open it in Atrium to view or edit"), which is not an answer: the team
    # works this board, so the board edits the work. Sentinel remains the source of truth for
    # nothing about it -- every write below goes back to Atrium.
    a_key, a_task = atrium_tasks.split_id(str(task_id))
    if a_key:
        _require_atrium(user)
        envelope, err = atrium_tasks.fetch_task(a_key, a_task)
        if err:
            raise _atrium_error(err)
        return _atrium_detail(db, envelope)
    task = _resolve_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    if not task_perms.can_view(user, task):
        raise HTTPException(status_code=403, detail=_FORBIDDEN)
    return task_detail(task, db)


@router.post("")
def create_task(payload: TaskCreateIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # Any staff member can create a task (Sentinel is an internal, employee-facing tool) — except the
    # read-only seat, which by definition raises nothing (D8). Checked here because there is no task
    # yet for a `task_perms` predicate to take.
    if task_perms.is_read_only(user):
        raise HTTPException(status_code=403, detail="A viewer account can't create tasks.")
    if payload.status not in task_config.statuses(db):
        raise HTTPException(status_code=400, detail="Invalid status")
    is_am = user.role == "account_manager"
    # 🔴 A TEAM LEAD MAY ONLY STAFF THEIR OWN DEPARTMENT'S WORK (2026-08-05). This was
    # `role == ROLE_TEAM_LEAD` with no team test, so create was strictly more permissive than edit:
    # `task_perms.can_reassign` lets a lead name somebody only while the card is routed to their own
    # team (`_leads_team`), yet the same lead could CREATE a card for another department with a name
    # already on it. Same rule, both doors: the card has to belong to their department.
    may_delegate = user.role in task_perms.FULL or (
        user.role == ROLE_TEAM_LEAD and payload.assigned_team_id is not None
        and payload.assigned_team_id == user.team_id)
    # 🔴 A non-delegating role may route to a TEAM, never to a person (decision D10).
    #
    # Naming a colleague is delegation and stays a lead/manager act. But filing into a DEPARTMENT's
    # queue is not: nobody is made responsible, the team's leads are notified, and the card is owned
    # by no one until they triage it. An Acquisition employee who spots a website bug should not have
    # to own the fix — before this they did, because everything they created was force-assigned to
    # them (§2.4d).
    #
    # So: a team named → routed and UNASSIGNED (the team's queue, visible via
    # task_perms._team_queue). No team → self-assigned, exactly as before.
    #
    # 🔴 NAMING SOMEBODY YOU MAY NOT DELEGATE TO IS NOW A 403, not a silent correction (2026-08-05).
    # This used to drop `assigned_to_id` on the floor and answer 200, so the form let an employee pick
    # a colleague, said "created", and put the card on their own board instead — the same class of
    # quiet lie as the old Send to Atrium. The UI no longer offers the picker to these roles
    # (taskboard.js gates it exactly like Priority), so reaching this line means the caller really did
    # try. Naming YOURSELF is not delegation and goes through untouched, even alongside a department:
    # filing work into a queue that you intend to do yourself is a real thing.
    assigned_to_id = payload.assigned_to_id
    if not may_delegate:
        if assigned_to_id is not None and assigned_to_id != user.id:
            raise HTTPException(
                status_code=403,
                detail="Only a team lead or manager can assign a task to somebody else. "
                       "Pick a department instead — its leads will triage it.")
        if assigned_to_id is None:
            assigned_to_id = None if payload.assigned_team_id else user.id
    # SUPPORT on create follows the SAME rule as the lead: naming anybody but yourself is delegation
    # (models.TaskSupporter). Refused rather than silently dropped — dropping it is the quiet lie that
    # `assigned_to_id` used to tell, where the form let you pick a colleague, said "created", and put
    # the card somewhere else. Adding yourself as support on work you raise is always allowed.
    if payload.support_ids and not may_delegate and set(payload.support_ids) - {user.id}:
        raise HTTPException(
            status_code=403,
            detail="Only a team lead or manager can put somebody else on a task. "
                   "You can add yourself as support.")
    # Priority is honored from a manager (AM/admin/super) or a team lead; others default to Medium.
    # 🔴 Deliberately NOT `may_delegate`: priority is not delegation, and a lead filing work for
    # another department may still say how urgent it is. Tying it to the team test above would have
    # silently downgraded those cards to Medium.
    may_prioritize = user.role in task_perms.FULL or user.role == ROLE_TEAM_LEAD
    priority = payload.priority if may_prioritize and payload.priority in task_config.priorities(db) else "Medium"
    # Service template: seed the two-level breakdown (+ content type) from the picked recipe unless
    # the caller supplied their own. A seed, not a lock — the breakdown is editable afterwards.
    tpl = task_templates.get(db, payload.service_key) if payload.service_key else None
    maintasks = maintasks_svc.normalize(payload.maintasks or [], json.dumps([c.model_dump() for c in payload.checklist]))
    if tpl and not maintasks:
        maintasks = task_templates.maintasks_for(db, payload.service_key)
    content_type = payload.content_type or (tpl.content_type if tpl else None)
    # Template defaults fill fields the caller left blank (a seed, not a lock). Priority follows the
    # same role gate as a manually chosen one; labels/description only apply when none were supplied.
    if tpl and may_prioritize and priority == "Medium" and tpl.default_priority in task_config.priorities(db):
        priority = tpl.default_priority
    # 🔴 The label is DERIVED from the department, never supplied (decision D14). Anything the
    # caller sent in `payload.labels` — and the template's `default_labels_json` — is ignored:
    # one label, always right, no manual step, and the same rule Atrium applies to the same card.
    labels = _derived_labels(db, payload.assigned_team_id)
    description = payload.description or (tpl.default_description if tpl else None)
    task = Task(
        title=payload.title,
        description=description,
        client_id=payload.client_id,
        campaign=payload.campaign,
        content_type=content_type,
        account_manager_id=user.id if is_am else None,
        assigned_team_id=payload.assigned_team_id,
        assigned_to_id=assigned_to_id,
        created_by_id=user.id,  # automatic creator tag — never a form field

        priority=priority,
        status=payload.status,
        due_date=payload.due_date,
        start_date=payload.start_date,
        service_charge=payload.service_charge,  # already normalized by the schema (blank/zero → None)
        labels_json=json.dumps(labels),
        maintasks_json=maintasks_svc.dumps(maintasks),  # legacy checklist_json no longer written
        deliverable_url=payload.deliverable_url,
        internal_notes=payload.internal_notes,
        client_facing_notes=payload.client_facing_notes,
    )
    db.add(task)
    db.flush()          # need the PK before task_supporters rows can point at it
    support_added = _apply_support(db, task, payload.support_ids, user) if payload.support_ids else []
    _log(db, task.id, user.id, "created", None, task.status)
    # 🔴 CREATING A CARD IN A COLUMN IS A MOVE INTO IT (2026-08-06). The board offers "Add card" at the
    # foot of EVERY column, and this route wrote `status` as a plain field — it never called
    # `task_workflow.on_status_change`. So a task created straight into a done column got no
    # `completed_at`, and per §2.4h a completed row with no stamp is counted on NO day: it sat in
    # Completed while being invisible to Throughput, the on-time rate and cycle time, and showed "—"
    # in Past work. One created in the blocked column was "parked" with `on_hold` False — the same
    # split-brain `_sync_hold` fixes for drags.
    #
    # `old=""` is the honest previous status: there wasn't one. It resolves to no stage, so nothing in
    # `on_status_change` takes a "was_done"/"was_blocked" branch — which is right, because a brand-new
    # card is not leaving anywhere. The review gate is deliberately NOT applied: `review_blocks` is
    # about a claim that existing work is finished, and refusing to let anyone FILE already-delivered
    # work (which is what creating in Completed usually is) would only push them to create it in To Do
    # and drag it across, arriving at the same place with an extra step.
    task_workflow.on_status_change(db, task, "", task.status, user)
    db.commit()
    audit.record(db, actor_id=user.id, table_name="tasks", record_id=task.id, action="create",
                 new={"title": task.title, "status": task.status})
    # SHARE ON CREATE (decision D6): a client-facing service is shared from day one, so the client
    # watches it cross the board instead of first seeing it when it is already finished. Default ON
    # whenever the task HAS a client and the actor is allowed to bridge; `share_with_client=False`
    # opts a single task out.
    #
    # 🔴 Failure is reported, never raised. The task is already committed and is perfectly valid
    # unshared — turning a bridge outage into a failed create would lose the AM's typing. The
    # reason lands on `atrium_sync_error`, the drawer shows the stale pill, and Retry is one click
    # (the same contract `push` uses on edit — §4). This is only safe because 0.1/0.2 made
    # publishing real: before them it would have set a flag pointing at nothing.
    share = payload.share_with_client
    if share is None:
        share = task.client_id is not None
    if share and task.client_id is not None and task_perms.can_bridge(user):
        ok, err = task_bridge.publish(db, task, user)
        db.commit()
        if ok:
            audit.record(db, actor_id=user.id, table_name="tasks", record_id=task.id,
                         action="share-on-create", new=atrium_payload(task, db))

    for uid in support_added:
        if uid == user.id:
            continue
        notif.notify(db, user_id=uid, type=NOTIF_TASK_ASSIGNED,
                     title=f"You're supporting: {task.title}", link=f"/tasks?open={task.id}")
    if task.assigned_to_id:
        notif.notify(db, user_id=task.assigned_to_id, type=NOTIF_TASK_ASSIGNED,
                     title=f"New task assigned: {task.title}", link=f"/tasks?open={task.id}")
    elif task.assigned_team_id:
        # Filed into a team's queue with no owner — the team's leads hear about it (D9). Without this
        # the card is invisible work: routed-but-unassigned is a real state, not a gap (§2.4c-bis).
        _notify_team_routed(db, task, user)
        db.commit()
    _broadcast("created", task, user.id)
    return task_detail(task, db)


@router.patch("/{task_id}")
def update_task(task_id: str, payload: TaskUpdateIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # Atrium-owned card: the edit is written THERE (Atrium owns client-facing work), through the
    # same workspace helpers its own console form calls. The two field-level guards below are the
    # same two decisions Sentinel reserves for managers -- client visibility and priority.
    a_key, a_task = atrium_tasks.split_id(str(task_id))
    if a_key:
        _require_atrium_write(user)
        data = payload.model_dump(exclude_unset=True)
        if data.get("atrium_visible") is not None and not task_perms.can_bridge(user):
            raise HTTPException(status_code=403, detail="Only managers can change what the client sees")
        if "priority" in data and not (task_perms.can_manage_atrium(user)
                                       and data["priority"] in task_config.priorities(db)):
            data.pop("priority")
        envelope, err = atrium_tasks.edit_task(a_key, a_task, atrium_tasks.to_atrium_fields(data),
                                               actor=user.email or "")
        if err:
            raise _atrium_error(err)
        return _atrium_detail(db, envelope)

    task = _resolve_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    if not task_perms.can_edit(user, task):
        raise HTTPException(status_code=403, detail=_FORBIDDEN)

    data = payload.model_dump(exclude_unset=True)
    for fld in atrium_tasks.ONLY_ATRIUM:      # inert on a Sentinel row — it has no such columns
        data.pop(fld, None)
    # Field-level guards — everything else (title, dates, breakdown, notes) is free to whoever can edit:
    #  • atrium_visible (client bridge) -> managers only, mirrors /send-to-atrium
    #  • reassigning to someone else    -> team lead+ (delegation), employees can't reassign
    #  • priority                       -> can_prioritize, and must be a configured value
    if data.get("atrium_visible") and not task_perms.can_bridge(user):
        raise HTTPException(status_code=403, detail="Only managers can share a task to Atrium")
    for fld in ("assigned_to_id", "assigned_team_id"):
        if fld in data and data[fld] != getattr(task, fld) and not task_perms.can_reassign(user, task):
            raise HTTPException(status_code=403, detail="Only a team lead or manager can reassign a task")
    # 🔴 SUPPORT IS DELEGATION when it involves anybody but you (models.TaskSupporter). Popped out of
    # `data` here and applied AFTER the field loop, because `Task.support_ids` is a read-only property
    # over a relationship — leaving it in would `setattr` onto a property with no setter and 500.
    # `None` means the field was never sent, which must leave the supporters alone; `[]` means clear.
    support_want = data.pop("support_ids", None)
    if support_want is not None and _support_delegates(task, support_want, user.id) \
            and not task_perms.can_reassign(user, task):
        raise HTTPException(
            status_code=403,
            detail="Only a team lead or manager can put somebody else on a task. "
                   "You can add or remove yourself.")
    if "priority" in data and not (task_perms.can_prioritize(user, task) and data["priority"] in task_config.priorities(db)):
        data.pop("priority")
    # 🔴 STEP-LEVEL ASSIGNMENT IS DELEGATION TOO (§2.4e). Until 2026-08-03 the two guards above
    # covered `assigned_to_id`/`assigned_team_id` only, while `maintasks` went through its own branch
    # below with NO assignee check — so an employee who cannot reassign a task could still put any
    # card on any colleague's board by naming them on a sub-task, because `task_perms.is_assigned`
    # counts step owners for visibility. Gated where the field is WRITTEN, not in the UI.
    #
    # Renaming a step, adding one, deleting one all stay open to anyone who can edit — only a change
    # to WHO OWNS a phase or step is delegation. A change that involves nobody but the actor (picking
    # up an unowned step, dropping their own) is self-assignment, which every role may do.
    # (TICKING used to be on that open list too; since 2026-08-05 it is scoped separately below.)
    #
    # 🔴 SLOT BY SLOT, NOT AS A SET (2026-08-05). This compared `{owner ids} before` with
    # `{owner ids} after`, which passed every edit that left the set intact: an employee could move a
    # colleague's ownership from one step to another, pile them onto five more steps, or swap two
    # colleagues' steps — all 200, all of it delegation. The six tests that pinned the original fix
    # each ADD or REMOVE a person, so none of them could see it.
    if "maintasks" in data:
        before = maintasks_svc.slots(
            maintasks_svc.normalize(task.maintasks_json, task.checklist_json))
        after = maintasks_svc.slots(maintasks_svc.normalize(data["maintasks"] or []))
        if not task_perms.can_reassign(user, task) and \
                maintasks_svc.foreign_owner_changes(before, after, user.id):
            raise HTTPException(
                status_code=403,
                detail="Only a team lead or manager can assign a step to someone else.")
        # TICKING SOMEBODY ELSE'S STEP is its own decision (2026-08-05) — see
        # `task_perms.can_tick_step`. Everything else about a step (its text, whether it exists at
        # all) stays open to whoever can edit the card; only the claim "this is done" is scoped,
        # because a card with several owners handed that claim to all of them.
        for change in maintasks_svc.tick_changes(before, after):
            if task_perms.can_tick_step(user, task, change["owner"]):
                continue
            owner = db.get(User, change["owner"])
            who = (owner.name if owner else None) or "its owner"
            raise HTTPException(
                status_code=403,
                detail=f"“{change['text']}” is {who}'s step — only they or a lead can tick it.")

    prev_assignee = task.assigned_to_id
    prev_team = task.assigned_team_id
    for field, value in data.items():
        if field == "labels":
            continue  # derived from the department (D14) — see the recompute below
        elif field == "checklist":
            continue  # legacy flat list is no longer written; the breakdown lives in maintasks
        elif field == "maintasks":
            # Normalize on write so ids/types are always clean regardless of what the client sent.
            task.maintasks_json = maintasks_svc.dumps(maintasks_svc.normalize(value or []))
        else:
            old = getattr(task, field)
            if old != value:
                _log(db, task.id, user.id, field, old, value)
            setattr(task, field, value)
    # Support, after the field loop (it writes rows, not a column) and before the commit below.
    support_added = _apply_support(db, task, support_want, user) if support_want is not None else []
    # The label FOLLOWS the department (D14). Recomputed after the field loop so it reacts to a
    # team change in this very PATCH, and logged like any other field so the history explains why
    # the chip changed. Re-routing a task is the only thing that can relabel it.
    if task.assigned_team_id != prev_team:
        new_labels = _derived_labels(db, task.assigned_team_id)
        old_labels = _loads_labels(task.labels_json)
        if old_labels != new_labels:
            _log(db, task.id, user.id, "labels", ", ".join(old_labels) or None,
                 ", ".join(new_labels) or None)
            task.labels_json = json.dumps(new_labels)
            data["labels"] = new_labels   # so the projection below sees it as a client-view change

    # PROJECTION (docs/TASKBOARD_REBUILD.md §4): Sentinel owns every field; a published task's
    # client-safe subset is re-sent whenever one of those fields moved. A failure is recorded on
    # the row (atrium_sync_error) rather than raised — the edit itself succeeded, and a stale
    # client card is surfaced + retryable, never silent.
    if task_bridge.published(task) and task_bridge.touches_client_view(data):
        task_bridge.push(db, task, user)
    db.commit()
    if task.assigned_to_id and task.assigned_to_id != prev_assignee:
        notif.notify(db, user_id=task.assigned_to_id, type=NOTIF_TASK_ASSIGNED,
                     title=f"Task assigned to you: {task.title}", link=f"/tasks?open={task.id}")
    # A new supporter is TOLD, for the same reason a new assignee is: the card silently appears on
    # their board otherwise, and the whole point of the field is that somebody decided they are on
    # this work. Never for adding YOURSELF — you already know, and self-notification is noise.
    for uid in support_added:
        if uid == user.id:
            continue
        notif.notify(db, user_id=uid, type=NOTIF_TASK_ASSIGNED,
                     title=f"You're supporting: {task.title}", link=f"/tasks?open={task.id}")
    # 🔴 ROUTING TO A TEAM USED TO NOTIFY NOBODY (§2.4c-bis, decision D9). Only `assigned_to_id` was
    # ever notified, so the natural flow — AM files it, routes it to Acquisition, the lead delegates —
    # left the card sitting in a queue waiting for somebody to happen to look. `notify_managers` finds
    # the leads by QUERY (role team_lead + matching team_id) plus admins, which is why no
    # `Team.lead_id` column is needed and why zero leads and three leads both work.
    if task.assigned_team_id and task.assigned_team_id != prev_team:
        _notify_team_routed(db, task, user)
        db.commit()          # notify_managers is called with commit=False — this is what persists it
    _broadcast("updated", task, user.id)
    return task_detail(task, db)


def _notify_team_routed(db: Session, task: Task, actor: User) -> None:
    """Tell a team that work has landed in their queue. Silent when it is already owned — a card with
    an assignee is somebody's job, not a queue item, and that person was notified directly."""
    if task.assigned_to_id:
        return
    team = db.get(Team, task.assigned_team_id)
    notif.notify_managers(
        db, type=NOTIF_TASK_ASSIGNED,
        title=f"New work for {team.name if team else 'your team'}: {task.title}",
        body=f"Routed by {actor.name or 'a teammate'} and waiting for triage — nobody owns it yet.",
        link=f"/tasks?open={task.id}", team_id=task.assigned_team_id, commit=False,
    )


@router.delete("/{task_id}")
def delete_task(task_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Delete a task and everything hanging off it. Team lead (own team) + AM / admin / super_admin."""
    # An Atrium card is deleted in Atrium, where it soft-deletes into that console's Bin (30 days).
    # Managers only: there is no creator tag on a card Sentinel doesn't own, so the "clean up your
    # own mistake" branch of can_delete has nothing to stand on.
    a_key, a_task = atrium_tasks.split_id(str(task_id))
    if a_key:
        if not task_perms.can_manage_atrium(user):
            raise HTTPException(status_code=403, detail="Only a manager can delete a client card")
        ok, err = atrium_tasks.remove_task(a_key, a_task, actor=user.email or "")
        if not ok:
            raise _atrium_error(err)
        return {"ok": True}
    task = _resolve_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    if not task_perms.can_delete(user, task):
        raise HTTPException(status_code=403, detail=_FORBIDDEN)
    title = task.title
    _broadcast("deleted", task, user.id)  # while the row is still valid
    # comments + history cascade via the relationship; Atrium approvals have no cascade, so clear them.
    db.query(AtriumApproval).filter(AtriumApproval.task_id == task.id).delete()
    db.delete(task)
    db.commit()
    audit.record(db, actor_id=user.id, table_name="tasks", record_id=task.id, action="delete",
                 old={"title": title})
    return {"ok": True}


@router.patch("/{task_id}/status")
def move_status(task_id: str, payload: TaskStatusIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # An Atrium-owned card (id "atrium:<client_key>:<task_id>") lives in Atrium, so the move is
    # written THERE -- Atrium is the source of truth for client-facing work. Atrium's own guards
    # (open sub-tasks / unresolved change requests block completion) are surfaced verbatim.
    a_key, a_task = atrium_tasks.split_id(str(task_id))
    if a_key:
        _require_atrium_write(user)
        # Resolved through task_vocab so a RENAMED status still moves the client's card. The old
        # label-keyed literal is why renaming a status used to 400 every move (§2.2.1).
        stage = task_config.stage_for(db, payload.status)
        if not stage:
            raise HTTPException(
                status_code=400,
                detail=f'"{payload.status}" has no Atrium stage, so a client card cannot move into it.')
        ok, err = atrium_tasks.move_task(a_key, a_task, stage, actor=user.email or "")
        if not ok:
            raise HTTPException(status_code=409, detail=err)
        return {"ok": True, "id": str(task_id), "status": payload.status}
    try:
        task = db.get(Task, int(task_id))
    except (TypeError, ValueError):
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    if not task:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    if payload.status not in task_config.statuses(db):
        raise HTTPException(status_code=400, detail="Invalid status")
    if not task_perms.can_move(user, task):
        raise HTTPException(status_code=403, detail=_FORBIDDEN)
    old = task.status
    if old == payload.status:
        return task_detail(task, db)
    # 🔴 The ONE enforced gate on this board (decision D5): nothing reaches a done column without a
    # team lead's approval. Everything else is surfaced, not enforced — a card with six open steps
    # still drops into Completed — but "Done" is the claim the whole company reads off this board,
    # and it used to be one person's unilateral drag.
    if task_workflow.review_blocks(db, task, payload.status):
        raise HTTPException(status_code=409, detail=task_workflow.NEEDS_REVIEW)
    _apply_status(db, task, payload.status, user)
    return task_detail(task, db)


@router.post("/{task_id}/resolve-client-changes")
def resolve_client_changes(task_id: str, user: User = Depends(get_current_user),
                           db: Session = Depends(get_db)):
    """Clear the client's open change requests on this card (D4 / WP 3.5).

    The counter is a FLAG, not a log: the conversation itself stays in the thread forever, and
    this only says "we have dealt with what they asked". Gated on `can_edit` — answering a client
    is part of doing the work, not a management act.

    Idempotent: resolving an already-clear card is a no-op success, because two people clicking it
    is a normal race and neither deserves an error.
    """
    task = _resolve_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    if not task_perms.can_edit(user, task):
        raise HTTPException(status_code=403, detail=_FORBIDDEN)
    if (task.client_changes_open or 0) == 0:
        return task_detail(task, db)
    _log(db, task.id, user.id, "client_changes", str(task.client_changes_open), "0")
    task.client_changes_open = 0
    db.commit()
    _broadcast("updated", task, user.id)
    return task_detail(task, db)


@router.post("/bulk")
def bulk_update(payload: TaskBulkIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Apply one change to many tasks (M7, WP 5.4). Triage was one drawer at a time.

    🔴 PARTIAL SUCCESS IS THE CONTRACT, not a compromise. A selection is a rectangle drawn over a
    board; it will routinely contain a card the actor may not move, one already in the target
    column, and one a lead has not approved for Completed yet. Refusing the whole batch because of
    one such card would make the feature useless on exactly the boards it exists for — so every
    task is judged on its own and the response says precisely what happened to each.

    Every permission is the SAME per-task predicate the single-task routes use (`can_move`,
    `can_prioritize`, `can_reassign`) and the move runs through the SAME `_apply_status`, so bulk
    can never become a way around a guard — including the one enforced gate, the D5 review
    requirement before a done column.

    Atrium-owned ids are refused outright: they are composite strings, they live in another system,
    and a bulk write across the bridge is not something to do behind one click.
    """
    ids = list(dict.fromkeys(payload.ids))      # de-dupe, keep the caller's order
    if not ids:
        raise HTTPException(status_code=400, detail="No tasks selected")

    op, value = payload.op, payload.value
    # Validate the target ONCE. A bad value is the caller's mistake, not a per-task outcome.
    if op == "status":
        if value not in task_config.statuses(db):
            raise HTTPException(status_code=400, detail="Invalid status")
    elif op == "priority":
        if value not in task_config.priorities(db):
            raise HTTPException(status_code=400, detail="Invalid priority")
    else:
        if value is not None:
            target = db.get(User, int(value)) if str(value).isdigit() else None
            if not target or not target.is_active:
                raise HTTPException(status_code=400, detail="Unknown person")
            value = target.id

    updated: list[int] = []
    skipped: list[dict] = []

    def skip(tid, why):
        skipped.append({"id": tid, "reason": why})

    for tid in ids:
        task = db.get(Task, tid)
        if not task or task.archived:
            skip(tid, "Not found")
            continue
        if op == "status":
            if not task_perms.can_move(user, task):
                skip(tid, "Not yours to move")
            elif task.status == value:
                skip(tid, "Already there")
            elif task_workflow.review_blocks(db, task, value):
                skip(tid, task_workflow.NEEDS_REVIEW)
            else:
                _apply_status(db, task, value, user)
                updated.append(tid)
        elif op == "priority":
            if not task_perms.can_prioritize(user, task):
                skip(tid, "Only a team lead or manager can set priority")
            elif task.priority == value:
                skip(tid, "Already there")
            else:
                old = task.priority
                task.priority = value
                _log(db, task.id, user.id, "priority", old, value)
                db.commit()
                audit.record(db, actor_id=user.id, table_name="tasks", record_id=task.id,
                             action="priority", old={"priority": old}, new={"priority": value})
                _broadcast("priority", task, user.id)
                updated.append(tid)
        else:
            # Assigning to anyone but yourself is delegation — the same rule single-task edits use.
            #
            # 🔴 "…but yourself" is not the whole test (fixed 2026-08-05). The condition was
            # `value != user.id`, so an employee could TAKE a card a colleague already owned onto
            # their own board: picking work up out of a queue and lifting it off the person doing it
            # are not the same act, and only the first one is self-assignment. Claiming is allowed
            # only while the card is UNOWNED — which is exactly the state `_team_queue` makes visible
            # to them. (The bulk bar only offers this control to team_lead+, so this was reachable via
            # the API rather than the UI. The guard belongs here either way.)
            may_claim = value == user.id and task.assigned_to_id is None
            if not task_perms.can_reassign(user, task) and not may_claim:
                skip(tid, "Only a team lead or manager can assign someone else")
            elif task.assigned_to_id == value:
                skip(tid, "Already there")
            else:
                old = task.assigned_to_id
                task.assigned_to_id = value
                _log(db, task.id, user.id, "assigned_to_id", old, value)
                # A published card shows the client nothing about WHO owns it, so no bridge push.
                db.commit()
                audit.record(db, actor_id=user.id, table_name="tasks", record_id=task.id,
                             action="assign", old={"assigned_to_id": old},
                             new={"assigned_to_id": value})
                if value:
                    notif.notify(db, user_id=value, type=NOTIF_TASK_ASSIGNED,
                                 title=f"Task assigned to you: {task.title}",
                                 link=f"/tasks?open={task.id}")
                _broadcast("updated", task, user.id)
                updated.append(tid)

    db.commit()
    return {"updated": updated, "skipped": skipped,
            "counts": {"updated": len(updated), "skipped": len(skipped)}}


@router.patch("/{task_id}/priority")
def set_priority(task_id: str, payload: TaskPriorityIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    a_key, a_task = atrium_tasks.split_id(str(task_id))
    if a_key:
        if not task_perms.can_manage_atrium(user):
            raise HTTPException(status_code=403, detail="Only a team lead or manager can set task priority")
        if payload.priority not in task_config.priorities(db):
            raise HTTPException(status_code=400, detail="Invalid priority")
        envelope, err = atrium_tasks.edit_task(a_key, a_task, {"priority": payload.priority},
                                               actor=user.email or "")
        if err:
            raise _atrium_error(err)
        return _atrium_detail(db, envelope)
    task = _resolve_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    # Priority is a management decision: team lead (own team) + AM / admin / super_admin.
    if not task_perms.can_prioritize(user, task):
        raise HTTPException(status_code=403, detail="Only a team lead or manager can set task priority")
    if payload.priority not in task_config.priorities(db):
        raise HTTPException(status_code=400, detail="Invalid priority")
    old = task.priority
    task.priority = payload.priority
    _log(db, task.id, user.id, "priority", old, payload.priority)
    db.commit()
    audit.record(db, actor_id=user.id, table_name="tasks", record_id=task.id, action="priority",
                 old={"priority": old}, new={"priority": payload.priority})
    _broadcast("priority", task, user.id)
    return task_detail(task, db)


# --- The lifecycle actions: park / resume / file / review (Stage 2) -----------------------------
# All four are Sentinel-only. An Atrium-owned card has no local row to hold `on_hold`, `archived` or
# `review_state`, and inventing a projection of them into a store nobody may write is exactly the
# split-ownership model D1/D2 removed. They 400 with a reason instead of pretending.

def _own_row(db: Session, task_id: str, user: User, permit, what: str) -> Task:
    """Resolve a SENTINEL task for a lifecycle action, or raise the right error."""
    a_key, _ = atrium_tasks.split_id(str(task_id))
    if a_key:
        raise HTTPException(status_code=400,
                            detail=f"A client card Atrium owns can't be {what} from here.")
    task = _resolve_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    if not permit(user, task):
        raise HTTPException(status_code=403, detail=_FORBIDDEN)
    return task


def _after_move(db: Session, task: Task, user: User, action: str) -> dict:
    """Commit a lifecycle change, project the move, broadcast it, and answer with the task.

    The push is fire-and-record like every other projection: the local change SAVED, and a failure
    lands in `atrium_sync_error` so the client's stale copy is loud and retryable (§4, invariant 2).
    """
    if task_bridge.published(task):
        task_bridge.push_stage(db, task, user)
    db.commit()
    audit.record(db, actor_id=user.id, table_name="tasks", record_id=task.id, action=action,
                 new={"status": task.status})
    _broadcast(action, task, user.id)
    return task_detail(task, db)


@router.post("/{task_id}/park")
def park_task(task_id: str, payload: TaskParkIn, user: User = Depends(get_current_user),
              db: Session = Depends(get_db)):
    """Pause the work in the blocked column, remembering the column it came from (M3).

    The reason is INTERNAL and never crosses the bridge: the client's card shows the stage it is
    parked in, never that we are waiting on their invoice.
    """
    task = _own_row(db, task_id, user, task_perms.can_move, "parked")
    _status, err = task_workflow.park(db, task, user, payload.reason)
    if err:
        raise HTTPException(status_code=409, detail=err)
    return _after_move(db, task, user, "park")


@router.post("/{task_id}/resume")
def resume_task(task_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Put a parked task back in the column it left (M3)."""
    task = _own_row(db, task_id, user, task_perms.can_move, "resumed")
    _status, err = task_workflow.resume(db, task, user)
    if err:
        raise HTTPException(status_code=409, detail=err)
    return _after_move(db, task, user, "resume")


@router.post("/{task_id}/archive")
def archive_task(task_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """File a completed task into Past work (M4). Only completed work may be filed."""
    task = _own_row(db, task_id, user, task_perms.can_move, "filed")
    err = task_workflow.archive(db, task, user)
    if err:
        raise HTTPException(status_code=409, detail=err)
    db.commit()
    audit.record(db, actor_id=user.id, table_name="tasks", record_id=task.id, action="archive",
                 new={"archived": True})
    # Filing is INTERNAL: the client's card stays exactly where it is. Atrium has no archive in this
    # bridge, and quietly moving or hiding a delivered card would rewrite what the client was told.
    _broadcast("archived", task, user.id)
    return task_detail(task, db)


@router.post("/{task_id}/unarchive")
def unarchive_task(task_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Pull a filed task back onto the board, in the column it still holds."""
    task = _own_row(db, task_id, user, task_perms.can_move, "unfiled")
    task_workflow.unarchive(db, task, user)
    db.commit()
    _broadcast("updated", task, user.id)
    return task_detail(task, db)


@router.post("/{task_id}/send-back")
def send_back(task_id: str, payload: TaskParkIn, user: User = Depends(get_current_user),
              db: Session = Depends(get_db)):
    """Refuse queued work and return it to whoever filed it, with a reason (decision D11, §2.4g).

    D10 lets anyone file into another team's queue, which makes "this isn't ours" a normal event —
    and without a way to say it, a wrongly-routed card just rots. Three rules keep it honest:

    * **Only while UNASSIGNED.** Once somebody on the team picks it up they own it, and the right
      move is to reassign or re-route, not to bounce.
    * **Ownership is never left vague.** The bounce clears `assigned_team_id` AND assigns the card
      back to the filer, so refused work is always held by someone. A card that lands nowhere is the
      failure mode this avoids.
    * **The reason is internal and recorded.** It goes in history (read back by `filed-by-me`) and
      never near the projection push — a client learning that two departments disagreed about their
      work is exactly the leak the client-safe split exists to prevent.

    A consequence that looks like a bug and is not: the moment a lead sends a card back **they can no
    longer see it** — the team link is gone and it is not theirs — because refusing work stops it
    being yours.
    """
    task = _own_row(db, task_id, user, task_perms.can_review, "sent back")
    if task.assigned_to_id is not None:
        raise HTTPException(
            status_code=409,
            detail="Somebody on the team already owns this. Reassign or re-route it instead of "
                   "sending it back.")
    if not task.created_by_id:
        raise HTTPException(status_code=409,
                            detail="Nothing records who filed this, so there is nobody to send it "
                                   "back to. Re-route it to the right team instead.")
    reason = (payload.reason or "").strip()
    old_team = task.assigned_team_id
    task.assigned_team_id = None
    task.assigned_to_id = task.created_by_id
    _log(db, task.id, user.id, "sent_back", old_team, reason or "no reason given")
    filer = db.get(User, task.created_by_id)
    notif.notify(db, user_id=task.created_by_id, type=NOTIF_TASK_ASSIGNED,
                 title=f"Sent back to you: {task.title}",
                 body=reason or f"{user.name or 'A lead'} sent this back without a reason.",
                 link=f"/tasks?open={task.id}", commit=False)
    db.commit()
    audit.record(db, actor_id=user.id, table_name="tasks", record_id=task.id, action="send_back",
                 old={"assigned_team_id": old_team}, new={"assigned_to_id": task.assigned_to_id})
    _broadcast("updated", task, user.id)
    return {"ok": True, "returned_to": filer.name if filer else None,
            "task": task_detail(task, db)}


@router.post("/{task_id}/review/submit")
def submit_for_review(task_id: str, user: User = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    """Ask a lead to approve this work (M2). Anyone who can edit the task may ask about it."""
    task = _own_row(db, task_id, user, task_perms.can_edit, "submitted for review")
    err = task_workflow.submit_review(db, task, user)
    if err:
        raise HTTPException(status_code=409, detail=err)
    db.commit()
    _broadcast("updated", task, user.id)
    return task_detail(task, db)


@router.post("/{task_id}/review/approve")
def approve_review(task_id: str, user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    """Approve the work, unblocking completion (D5). Team lead within their team, AM+ anywhere."""
    task = _own_row(db, task_id, user, task_perms.can_review, "approved")
    err = task_workflow.approve(db, task, user)
    if err:
        raise HTTPException(status_code=409, detail=err)
    db.commit()
    audit.record(db, actor_id=user.id, table_name="tasks", record_id=task.id, action="approve",
                 new={"review_state": task.review_state})
    _broadcast("updated", task, user.id)
    return task_detail(task, db)


@router.post("/{task_id}/review/request-changes")
def request_review_changes(task_id: str, payload: TaskReviewIn,
                           user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Send the work back with a note (M2). Moves the card to the revision column if there is one."""
    task = _own_row(db, task_id, user, task_perms.can_review, "sent back")
    _moved, err = task_workflow.request_changes(db, task, user, payload.note)
    if err:
        raise HTTPException(status_code=409, detail=err)
    return _after_move(db, task, user, "request_changes")


@router.post("/{task_id}/comments")
def add_comment(task_id: str, payload: CommentIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # A comment on an Atrium card is a TEAM comment in Atrium's own thread -- on a client-facing
    # card it reaches the client's Progress tab and notifies them, exactly as it would from Atrium's
    # console. The author echoed back is the Sentinel user, so their avatar appears immediately.
    a_key, a_task = atrium_tasks.split_id(str(task_id))
    if a_key:
        _require_atrium_write(user)
        comment, err = atrium_tasks.comment_task(a_key, a_task, payload.body,
                                                 actor=user.email or "", actor_name=user.name or "")
        if err:
            raise _atrium_error(err)
        return {"id": comment.get("id"), "author": user_public(user), "body": comment.get("body", ""),
                "attachments": [], "created_at": comment.get("created_at")}
    task = _resolve_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    # can_EDIT, not can_view: writing on a task's thread is a write (D8). A viewer reads the thread
    # in the response of GET /{id} and adds nothing to it.
    if not task_perms.can_edit(user, task):
        raise HTTPException(status_code=403, detail=_FORBIDDEN)
    c = TaskComment(
        task_id=task.id, author_id=user.id, body=payload.body,
        attachments_json=json.dumps(payload.attachments or []),
    )
    db.add(c)
    db.commit()
    _broadcast("comment", task, user.id)  # live boards refresh the comment count
    return comment_dict(c, db)


@router.post("/{task_id}/comments/{comment_id}/resolve")
def resolve_change_request(task_id: str, comment_id: str, user: User = Depends(get_current_user),
                           db: Session = Depends(get_db)):
    """Mark a client's "Request changes" comment resolved — Atrium cards only.

    Raising a change request is a CLIENT power (they do it on their Progress tab); clearing it is a
    team action, and the team works here. A Sentinel row has no such thing, so it 404s."""
    a_key, a_task = atrium_tasks.split_id(str(task_id))
    if not a_key:
        raise HTTPException(status_code=404, detail="Change requests only exist on client cards")
    _require_atrium_write(user)
    ok, err = atrium_tasks.resolve_change_request(a_key, a_task, comment_id, actor=user.email or "")
    if not ok:
        raise _atrium_error(err)
    return {"ok": True}


# 🔴 `POST /{task_id}/attachments` was REMOVED 2026-08-04 (WP 0.4). It read the uploaded file,
# THREW THE BYTES AWAY, and recorded the name/size as a comment — so the board showed a paperclip
# count for files that had never been stored anywhere and could never be opened. No frontend ever
# called it; the only attachment code in `taskboard.js` is the read-side count pill.
#
# The READ plumbing is deliberately kept (`TaskComment.attachments_json`, `attach_count` /
# `attachment_count` in `serializers.py`, the pill): it is the shape a real implementation fills
# in, and today it simply reports 0. Wiring attachments for real means GCS private objects + an
# authed redirect, exactly like Atrium's creatives — see §7 of docs/TASKBOARD_REBUILD.md. Do NOT
# reinstate a version that discards the bytes.


@router.post("/{task_id}/send-to-atrium", dependencies=[Depends(require_roles(*AM_PLUS))])
def send_to_atrium(task_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Share a task with its client: MINT the Atrium card, link it, and send the client-safe subset.

    🔴 Until 2026-08-03 this set `atrium_visible = True`, wrote an AtriumApproval row and created
    NOTHING in Atrium — so the AM got a success toast, the drawer said "✓ In Atrium", and the
    client's Tasks tab stayed empty forever (docs/TASKBOARD_REBUILD.md §1.2). It now fails LOUD:
    if the card cannot be created the row is not marked shared and the reason is returned.
    """
    task = _resolve_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    already = task_bridge.published(task)
    ok, err = task_bridge.publish(db, task, user)
    if not ok:
        db.commit()          # keep atrium_sync_error — the failure is part of the record
        raise HTTPException(status_code=502, detail=err)
    approval = AtriumApproval(task_id=task.id, sent_at=utcnow())
    db.add(approval)
    db.commit()
    audit.record(db, actor_id=user.id, table_name="atrium_approvals", record_id=approval.id,
                 action="send", new=atrium_payload(task, db))
    _broadcast("updated", task, user.id)
    return {"ok": True, "atrium_task_id": task.atrium_task_id, "already_shared": already,
            "sync_error": task.atrium_sync_error, "atrium_payload": atrium_payload(task, db)}


@router.post("/{task_id}/atrium-retry", dependencies=[Depends(require_roles(*AM_PLUS))])
def retry_atrium_push(task_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Re-send the client-safe subset after a failed push. The board offers this on a stale card."""
    task = _resolve_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    if not task_bridge.published(task):
        raise HTTPException(status_code=400, detail="That task has never been shared with a client.")
    ok, err = task_bridge.push(db, task, user)
    if ok:
        ok, err = task_bridge.push_stage(db, task, user)
    db.commit()
    if not ok:
        raise HTTPException(status_code=502, detail=err)
    _broadcast("updated", task, user.id)
    return {"ok": True, "sync_error": None}


@router.get("/atrium/stale-shares", dependencies=[Depends(require_roles(*AM_PLUS))])
def list_stale_shares(db: Session = Depends(get_db)):
    """The reconcile backlog (D15): rows claiming to be shared that point at no Atrium card.

    Report only. Bulk-publishing these would drop months-old — sometimes already delivered — work
    onto clients' boards unannounced, so each one is a human decision: publish, or clear the claim.

    Two path segments, so `GET /{task_id}` (one segment) cannot swallow it wherever it is declared —
    unlike the `/api/gym/routines*` case that had to be hoisted above `/{log_id}` (AGENTS.md §5).
    """
    return task_bridge.stale_shares(db)


@router.post("/{task_id}/atrium-clear-share", dependencies=[Depends(require_roles(*AM_PLUS))])
def clear_stale_share(task_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Resolve a stale row the other way: it was never really shared, so stop claiming it was."""
    task = _resolve_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    if task_bridge.published(task):
        raise HTTPException(status_code=409,
                            detail="That task really is shared — unshare it in Atrium instead.")
    task_bridge.clear_share(db, task, user)
    db.commit()
    _broadcast("updated", task, user.id)
    return {"ok": True}

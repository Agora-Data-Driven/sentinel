"""What is happening on the TASK BOARD, digested for the Mastery Engine AI coach.

The coach already knows the worker's whole-person development (`services/development.holistic_digest`
→ `/api/internal/holistic-profile`). This is the other half of their working life: the board. It is
what lets "what should I do today?", "am I behind?" and "who on my team is buried?" be answered from
the same chat box, instead of the coach talking about goals while blind to the work.

    work_digest(db, user)          -> the board as THIS person is allowed to see it
    work_detail(db, user, ids)     -> full bodies (description, breakdown, notes, comments) for
                                      specific cards — the "big" half of small-to-big retrieval

🔴 **THIS DIGEST IS ROLE-SCOPED, AND THAT IS THE WHOLE DESIGN.** Every other internal endpoint the
coach calls is the user's OWN data, so `holistic-profile` can say "no manager check applies here".
The board is not that: it is other people's work, under a real permission model
(`services/task_perms.py`). An intern sees what is on them plus their team's unowned queue; a team
lead sees their team; an AM/admin/viewer sees the estate. So every card here goes through
`task_perms.can_view(user, task)` — the SAME predicate `list_tasks` filters the real board with —
and the per-person rollup copies `/api/tasks/summary`'s cohort rule. A digest that skipped that
would make the Coach FAB an RBAC bypass with a chat box on it: an intern asking their coach "what is
everyone working on?" would get the whole company's delivery board, service charges and all.

Two rules inherited from the growth-journal incident (see `development.py` and AGENTS.md §5), because
the failure mode is identical — the coach denying work the person can see on their own screen:

  * **THE INDEX OF THEIR OWN WORK IS COMPLETE AND UNCAPPED.** `mine` lists every card on them. The
    coach infers "you have nothing about X" from its absence, so a cap turns that inference into a
    confident lie. Bodies are lazy (`work_detail`); the index is not.
  * **A TRUNCATION IS DECLARED, NEVER SILENT.** The wider board CAN be capped (an AM sees the whole
    estate), so it carries `truncated` — how many cards did not fit — and the engine prints that gap
    so a miss reads as "there are 40 more I cannot see from here", not as "there are none".

What deliberately does NOT cross, even though the viewer could read it in the drawer:

  * `service_charge` — what the agency bills. Not needed to coach anybody about their work, and the
    one field on this table whose leak into a chat transcript is a commercial problem.
  * `internal_notes` / `hold_reason` — internal prose, and pure volume on a 60-card board. Both are
    available per-card from `work_detail`, once the conversation is actually about that card.

And nothing here is keyed off a status LABEL (decision D13): `stage` comes from
`task_config.stage_for` and "done" is `task_config.is_completed`, so renaming a column — as WP 1.2
renamed Blocked to Parked — leaves this digest correct.
"""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..constants import (
    ADMIN_ROLES,
    MANAGER_ROLES,
    ROLE_ACCOUNT_MANAGER,
    ROLE_LABELS,
    ROLE_TEAM_LEAD,
)
from ..models import Client, Task, TaskRequest, Team, User
from ..utils.time import to_ph, today_ph
from . import atrium_identity, atrium_tasks, task_adoption, task_analytics, task_config, task_perms
from . import maintasks as MT

# The wider board is capped; the viewer's OWN work never is (see the module docstring). 300 is far
# above any real board — the live estate runs in the tens — so this is a runaway guard, not a budget,
# and whatever it drops is reported in `truncated` rather than silently missing.
MAX_BOARD_CARDS = 300

# How many cards one `work_detail` call may hydrate. A ceiling on the REQUEST, never on any card's
# text: whatever comes back comes back whole. A half-loaded description reads to the model exactly
# like a complete one and gets summarised as though it were the card.
MAX_WORK_DETAIL_IDS = 25

# Who may read a per-person rollup at all, and who may see the pending client asks. Spelled out as
# sets rather than composed with set arithmetic on MANAGER_ROLES: the ordering of the checks matters
# (a team lead must fall through to the narrower branch), and `A | B - C` reads as though it does
# something other than what Python's precedence makes it do.
_SEES_ESTATE = ADMIN_ROLES | {ROLE_ACCOUNT_MANAGER}          # AM, admin, super_admin
_TRIAGES_ASKS = _SEES_ESTATE                                 # the roles that may accept a client ask


def _stager(db: Session):
    """A memoised `status -> stage` lookup. One vocab read per digest, not one per card."""
    cache: dict[str, str] = {}

    def stage(status: str) -> str:
        if status not in cache:
            cache[status] = task_config.stage_for(db, status)
        return cache[status]

    return stage


def _card(t: Task, user: User, stage, names: dict[int, str], clients: dict[int, str],
          teams: dict[int, str], today) -> dict:
    """One board card, compact — the shape the coach reasons over.

    Deliberately NOT `serializers.task_card`: that one is the browser's contract (photo URLs,
    colour-driving ids, `adoption_batch`) and half of it is noise in a prompt, while the two things a
    coach needs most — how overdue a card is, and how long it has sat untouched — are derived here.
    Reusing it would also couple the prompt to a shape that exists to be re-rendered, not read.
    """
    done, total = MT.sub_stats(MT.normalize(getattr(t, "maintasks_json", "[]"), t.checklist_json))
    st = t.status
    stg = stage(st)
    card = {
        "id": t.id,
        "title": t.title,
        "status": st,
        "stage": stg,
        "priority": t.priority,
        "client": clients.get(t.client_id) if t.client_id else None,
        "lead": names.get(t.assigned_to_id) if t.assigned_to_id else None,
        "team": teams.get(t.assigned_team_id) if t.assigned_team_id else None,
        "due": t.due_date.isoformat() if t.due_date else None,
        "steps": f"{done}/{total}" if total else None,
        # Viewer-relative, from the ONE definition of "this is on me" (task_perms.is_assigned). The
        # coach must be able to say "this one is Ana's card, two steps of it are yours" — that
        # distinction is exactly what the Overview got wrong before 2026-08-05.
        "mine": task_perms.is_assigned(user, t),
        "my_steps": task_perms.my_slot_count(user, t),
    }
    if stg != "completed" and t.due_date and t.due_date < today:
        card["overdue_days"] = (today - t.due_date).days
    if t.on_hold:
        # The FACT of the pause travels; `hold_reason` is internal prose and waits for work_detail.
        card["parked"] = True
    if t.review_state:
        card["review"] = t.review_state
    if t.archived:
        card["filed"] = True
    # How long it has sat. Two clocks on purpose, exactly as the Monitor keeps them: `age_days` is
    # how long the work has been owed, `idle_days` is how long nobody has touched it. Old is not
    # stale, and a coach that conflates them nags about the wrong card.
    if t.created_at:
        card["age_days"] = (today - to_ph(t.created_at).date()).days
    if t.updated_at and stg != "completed":
        card["idle_days"] = (today - to_ph(t.updated_at).date()).days
    if getattr(t, "atrium_task_id", None):
        # A share is only real when the id is set (§5, "Send to Atrium used to publish NOTHING") —
        # so this reports the id's presence, never `atrium_visible`.
        card["client_facing"] = True
        if getattr(t, "atrium_sync_error", None):
            card["client_copy_stale"] = True
    return card


def _atrium_cards(db: Session, user: User, clients: list[Client], today) -> list[dict]:
    """The client's own cards from Atrium, for the viewers allowed to see them.

    Mirrors `list_tasks`: manager-and-up only (`can_view_atrium` — these cards belong to no Sentinel
    user, so no ownership rule could scope them), claimed ids dropped (WP 4.3 — a linked Sentinel row
    IS that card, and counting both is the double-render bug in prompt form), and FAIL-SOFT, so an
    Atrium outage costs the coach the client half of the board and never the whole digest.
    """
    if not (atrium_tasks.enabled() and task_perms.can_view_atrium(user)):
        return []
    try:
        fetched = atrium_tasks.fetch_tasks()
    except Exception:                                   # noqa: BLE001  (fail-soft, see docstring)
        return []
    if not fetched:
        return []
    claimed = task_adoption.claimed_atrium_ids(db)
    owners = atrium_identity.build(db.execute(
        select(User).where(User.is_active.is_(True))).scalars().all())
    out: list[dict] = []
    for a in fetched:
        if (a.get("client_key", ""), str(a.get("task_id") or "")) in claimed:
            continue
        owner = owners.resolve(a.get("lead_id"), a.get("lead_name"))
        client = atrium_tasks.resolve_client(clients, a.get("client_key", ""), a.get("client_name", ""))
        # Never trust the label Atrium sends — it is renameable on both sides (D13). Resolve its
        # STAGE to whatever this board calls that column today.
        stage = a.get("stage") or ""
        status = task_config.status_for_stage(db, stage) or a.get("status") or ""
        card = {
            "id": atrium_tasks.ATRIUM_ID_PREFIX + (a.get("atrium_id") or ""),
            "title": a.get("title") or "",
            "status": status,
            "stage": stage,
            "priority": a.get("priority") or None,
            "client": getattr(client, "name", None) or a.get("client_name") or a.get("client_key"),
            "lead": (getattr(owner, "name", None)
                     or (a.get("lead_name") or "").strip()
                     or atrium_tasks.owner_label(a.get("lead_id") or "") or None),
            "due": a.get("due_date") or None,
            # This card is ON the viewer only when its Atrium lead resolved to them. An Atrium owner
            # is a roster EMAIL, so this is the resolver's answer, never an `==` on the address.
            "mine": bool(owner is not None and owner.id == user.id),
            "my_steps": 0,
            # 🔴 The card belongs to Atrium, which keeps no completion stamp we can read here — so it
            # can be Open/Overdue/Idle and NOTHING else. Said out loud because a coach that treated
            # silence as "never ships" would misjudge whoever delivers mostly client work.
            "owner_system": "atrium",
        }
        due = task_analytics._as_date(a.get("due_date"))
        if stage != "completed" and due and due < today:
            card["overdue_days"] = (today - due).days
        out.append(card)
    return out


def _people_rollup(db: Session, user: User, today) -> list[dict]:
    """Who is holding what — the Monitor's numbers, for the seats allowed to monitor.

    Cohort rule copied from `/api/tasks/summary`: admins / super-admin / AM see everyone, a team lead
    sees their own team, and the read-only seat monitors (that is its entire purpose, D8). Employees
    and interns get `[]` — monitoring is a management surface, and the coach must not become the way
    around that.

    🔴 **The rows do not sum to the number of cards.** Bucketed by `assigned_user_ids`, so a card with
    a build phase on one person and a QA step on another is counted on BOTH plates — which is the
    truth about shared work. `stepped` says how much of a row arrived that way, and the engine's
    prompt repeats the warning, because a coach that adds these up will invent a workload.
    """
    if not (user.role in MANAGER_ROLES or task_perms.is_read_only(user)):
        return []
    people = db.execute(select(User).where(User.is_active.is_(True))).scalars().all()
    if user.role == ROLE_TEAM_LEAD:
        people = [p for p in people if p.team_id == user.team_id]
    if not people:
        return []
    people = sorted(people, key=lambda p: (p.name or "").lower())

    tasks = db.execute(select(Task)).scalars().all()
    by_person: dict[int, list] = {}
    for t in tasks:
        for uid in task_perms.assigned_user_ids(t):
            by_person.setdefault(uid, []).append(t)

    all_statuses = task_config.statuses(db)
    done_statuses = {s for s in all_statuses if task_config.is_completed(db, s)}
    leave = task_analytics.leave_context(db, [p.id for p in people], today)

    # Client work counts toward the lead it resolves to — the same join the Monitor makes, and for
    # the same reason: without it, somebody holding fifteen client cards reads as idle.
    client_counts: dict[int, int] = {}
    if atrium_tasks.enabled():
        try:
            fetched = atrium_tasks.fetch_tasks()
        except Exception:                               # noqa: BLE001  (fail-soft)
            fetched = []
        if fetched:
            index = atrium_identity.build(people)
            claimed = task_adoption.claimed_atrium_ids(db)
            fresh = [c for c in fetched
                     if (c.get("client_key", ""), str(c.get("task_id") or "")) not in claimed]

            def _status_of(card):
                return task_config.status_for_stage(db, card.get("stage") or "") or card.get("status")

            for uid, rows in task_analytics.atrium_workload(fresh, index, _status_of).items():
                by_person.setdefault(uid, []).extend(rows)
                client_counts[uid] = len(rows)

    week_start = today - timedelta(days=7)
    rows = []
    for p in people:
        mine = by_person.get(p.id, [])
        live_open = [t for t in mine
                     if not getattr(t, "archived", False) and t.status not in done_statuses]
        overdue = sum(1 for t in live_open if t.due_date and t.due_date < today)
        stepped = sum(1 for t in live_open if t.assigned_to_id != p.id)
        done_week = 0
        for t in mine:
            if t.status in done_statuses:
                stamp = getattr(t, "completed_at", None)
                # `completed_at`, never `updated_at` (§2.4h): off `updated_at`, fixing a typo on a
                # task finished in March re-dates its completion to today.
                if stamp and to_ph(stamp).date() >= week_start:
                    done_week += 1
        row = {
            "name": p.name or p.email,
            "role": ROLE_LABELS.get(p.role, p.role),
            # `open_total` is the key `apply_load_bands` bands on — it reads that exact name, so this
            # is the analytics module's vocabulary, not a choice.
            "open_total": len(live_open),
            "overdue": overdue,
            "stepped": stepped,
            "done_last_7d": done_week,
            "client_cards": client_counts.get(p.id, 0),
            **leave.get(p.id, {"on_leave_today": False, "leave_days_ahead": 0}),
        }
        row.update(task_analytics.aging(live_open, today))
        rows.append(row)
    # Relative to the cohort the CALLER can see, so a team lead is compared against their own team.
    task_analytics.apply_load_bands(rows)
    rows.sort(key=lambda r: (r["overdue"], r["open_total"]), reverse=True)
    return rows


def _scope_note(user: User) -> str:
    """One sentence telling the coach WHAT IT IS LOOKING AT, in this viewer's terms.

    Load-bearing, not commentary. Without it the model reads a short board as "the company has four
    tasks" and says so to an intern whose board is scoped to four tasks — turning a correct
    permission boundary into a false statement about the business.
    """
    if user.role in _SEES_ESTATE:
        return ("every task board across every client — this person is a manager and sees the whole "
                "estate")
    if user.role == ROLE_TEAM_LEAD:
        return ("their own team's work, the cards they raised, and untriaged client work — NOT the "
                "whole company")
    if task_perms.is_read_only(user):
        return "the whole board, read-only — this is a monitoring seat"
    return ("ONLY the work assigned to them plus their team's unclaimed queue. This is NOT the whole "
            "company's board, so never describe it as such or total it up as company workload")


def work_digest(db: Session, user: User) -> dict:
    """The task board as `user` is permitted to see it, shaped for an LLM prompt."""
    today = today_ph()
    stage = _stager(db)
    all_statuses = task_config.statuses(db)
    done_statuses = {s for s in all_statuses if task_config.is_completed(db, s)}

    names = {u.id: (u.name or u.email) for u in db.execute(select(User)).scalars().all()}
    client_rows = db.execute(select(Client)).scalars().all()
    clients = {c.id: c.name for c in client_rows}
    teams = {t.id: t.name for t in db.execute(select(Team)).scalars().all()}

    # The board the viewer would actually see: live rows only, filtered by the same predicate
    # `list_tasks` uses. Filed work is a separate list there and a separate list here.
    rows = db.execute(select(Task).where(Task.archived.is_(False))
                      .order_by(Task.updated_at.desc())).scalars().all()
    visible = [t for t in rows if task_perms.can_view(user, t)]

    mine_rows = [t for t in visible if task_perms.is_assigned(user, t)]
    mine_ids = {t.id for t in mine_rows}
    other_rows = [t for t in visible if t.id not in mine_ids]

    def _sort_key(c: dict):
        # Most pressing first: overdue by how much, then a due date, then undated.
        return (-c.get("overdue_days", 0), c.get("due") or "9999-12-31")

    mine = sorted((_card(t, user, stage, names, clients, teams, today) for t in mine_rows),
                  key=_sort_key)
    others = [_card(t, user, stage, names, clients, teams, today) for t in other_rows]
    others.extend(_atrium_cards(db, user, client_rows, today))
    others.sort(key=_sort_key)

    # 🔴 `mine` is NEVER capped (module docstring). Only the wider board is, and the overflow is
    # counted so the engine can say how much it could not see.
    truncated = max(0, len(others) - MAX_BOARD_CARDS)
    others = others[:MAX_BOARD_CARDS]

    open_mine = [c for c in mine if c["stage"] != "completed"]
    columns = []
    for st in all_statuses:
        n = sum(1 for c in mine + others if c["status"] == st)
        columns.append({"status": st, "stage": stage(st), "cards": n})

    # 🔴 EVERYTHING THEY HAVE FINISHED, not just this week's — and this list is the reason the query
    # above cannot be the only one. A completed card is dropped from `open`, and a FILED one is not in
    # `rows` at all, so without this a card the person delivered last month exists nowhere in the
    # digest while `work_detail` will happily hydrate it: the coach would answer "you have nothing
    # about the Acme June report" about work they did and can still see on their Past-work list. Caught
    # by probing the two endpoints against each other on a seeded board (2026-08-05), and it is the
    # growth-journal incident exactly — an incomplete index turns a gap into a confident denial.
    #
    # Filed rows are included ON PURPOSE: filing a delivered task must not erase the fact that it
    # shipped. `on` is `completed_at`, never `updated_at` (§2.4h) — and a row finished before that
    # column existed carries no stamp, which is reported as null rather than guessed at.
    done_rows = [t for t in db.execute(select(Task).where(Task.status.in_(done_statuses)))
                 .scalars().all() if task_perms.is_assigned(user, t)]
    done_rows.sort(key=lambda t: (getattr(t, "completed_at", None) or t.updated_at or t.created_at),
                   reverse=True)
    done = [{"id": t.id, "title": t.title,
             "client": clients.get(t.client_id) if t.client_id else None,
             "on": (to_ph(t.completed_at).date().isoformat()
                    if getattr(t, "completed_at", None) else None),
             **({"filed": True} if getattr(t, "archived", False) else {})}
            for t in done_rows[:MAX_BOARD_CARDS]]
    done_truncated = max(0, len(done_rows) - MAX_BOARD_CARDS)

    digest: dict = {
        "as_of": today.isoformat(),
        "viewer": {
            "name": user.name or user.email,
            "role": ROLE_LABELS.get(user.role, user.role),
            "team": teams.get(user.team_id) if user.team_id else None,
            "sees": _scope_note(user),
        },
        "mine": {
            "open": open_mine,
            "open_total": len(open_mine),
            "overdue_total": sum(1 for c in open_mine if c.get("overdue_days")),
            "parked": sum(1 for c in open_mine if c.get("parked")),
            # Their whole finished history, newest first — see the comment where it is built.
            "done": done,
            "done_truncated": done_truncated,
        },
        "board": {
            "columns": columns,
            "visible_total": len(mine) + len(others),
            "others": others,
            "truncated": truncated,
        },
        "people": _people_rollup(db, user, today),
    }

    # Client asks awaiting triage — an AM-and-up concern (the same roles that may accept one), and
    # the one queue on this board that is somebody's job to empty rather than to work through.
    if user.role in _TRIAGES_ASKS:
        pending = db.execute(
            select(TaskRequest).where(TaskRequest.status == "pending")
            .order_by(TaskRequest.created_at.desc())
        ).scalars().all()
        if pending:
            digest["client_asks_pending"] = [
                {"title": r.title, "client": clients.get(r.client_id) if r.client_id else None,
                 "asked": r.created_at.date().isoformat() if r.created_at else None}
                for r in pending[:25]
            ]
    return digest


def work_detail(db: Session, user: User, ids: list[int]) -> list[dict]:
    """Full bodies for specific cards — the "big" half of small-to-big retrieval.

    `work_digest` ships every card the viewer may see as a compact line; this returns the prose for
    the handful a conversation actually turned out to be about: the description, the internal notes,
    the pause reason, the whole breakdown with its owners, and the comment thread.

    Cards come back WHOLE — never excerpted. A partial description is indistinguishable to the model
    from a complete one, and it will summarise the fragment as if it were the card.

    🔴 **Every id is re-checked against `task_perms.can_view`.** The caller names ids it read out of
    an index we scoped, but this endpoint must not trust that: an id is just an integer, and a coach
    (or a prompt injection reaching one) could name any of them. An id the viewer may not see is
    simply absent, exactly as an unknown id is — so the two are indistinguishable from outside and
    nobody can walk the table by guessing.
    """
    wanted = [i for i in dict.fromkeys(ids) if isinstance(i, int)][:MAX_WORK_DETAIL_IDS]
    if not wanted:
        return []
    rows = db.execute(select(Task).where(Task.id.in_(wanted))).scalars().all()
    by_id = {t.id: t for t in rows if task_perms.can_view(user, t)}
    names = {u.id: (u.name or u.email) for u in db.execute(select(User)).scalars().all()}
    out = []
    # Preserve the caller's order — it asked most-relevant-first, and earlier context carries more
    # weight in the prompt.
    for i in wanted:
        t = by_id.get(i)
        if t is None:
            continue
        breakdown = []
        for m in MT.normalize(getattr(t, "maintasks_json", "[]"), t.checklist_json):
            breakdown.append({
                "phase": m.get("title") or "",
                "owner": names.get(m.get("assignee_id")) if m.get("assignee_id") else None,
                "steps": [
                    {"text": s.get("text") or "", "done": bool(s.get("done")),
                     "owner": names.get(s.get("assignee_id")) if s.get("assignee_id") else None}
                    for s in m.get("subs", [])
                ],
            })
        detail = {
            "id": t.id,
            "title": t.title,
            "status": t.status,
            "description": (t.description or "").strip() or None,
            "internal_notes": (t.internal_notes or "").strip() or None,
            "client_note": (t.client_facing_notes or "").strip() or None,
            "deliverable_url": t.deliverable_url or None,
            "breakdown": breakdown,
            # A comment has EITHER an author_id (a colleague) or a `client_author` name — a client
            # reaching the thread over the reverse channel is not a Sentinel user and must never need
            # a row (D4/WP 3.5). Marked as the client, because "the client is asking for a change"
            # and "a colleague left a note" are different facts about the same card.
            "comments": [
                {"by": (names.get(c.author_id) if c.author_id
                        else f"{c.client_author or 'the client'} (client)"),
                 "on": c.created_at.date().isoformat() if c.created_at else None,
                 "text": (c.body or "").strip()}
                for c in sorted(t.comments, key=lambda c: c.created_at or t.created_at)
            ],
        }
        if t.on_hold:
            detail["parked_because"] = (t.hold_reason or "").strip() or "no reason recorded"
        out.append(detail)
    return out

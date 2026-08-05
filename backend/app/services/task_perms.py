"""Centralized task-board permission model — the one place task RBAC lives.

The rules (higher roles inherit lower ones):

    | action        | employee/intern | team_lead        | account_manager | admin/super_admin |
    | view          | assigned + team queue | team + own | all             | all               |
    | create        | yes             | yes              | yes             | yes               |
    | edit fields   | assigned        | team + own       | all             | all               |
    | tick a step   | own + unowned   | team             | all             | all               |
    | reassign      | self only       | team             | all             | all               |
    | priority      | no              | team (scoped)    | all             | all               |
    | review/approve| no              | team (scoped)    | all             | all               |
    | delete        | own created     | team + created   | all             | all               |
    | move status   | assigned        | team             | all             | all               |
    | bridge/Atrium | no              | no               | AM              | admin/super       |
    | see Atrium    | no              | yes              | yes             | yes               |

"assigned" = task.assigned_to_id == user.id, or assigned to one of the task's sub-tasks. For an
employee/intern that is the rule for OWNED work: someone else's card is not on their board, nor is
one they created themselves (2026-07-30; before that the automatic creator tag also granted sight,
which meant a card an intern raised and a manager then delegated stayed on the intern's board).
"team queue" (added 2026-08-03, §2.4c) is the one addition: work routed to their team that NOBODY
owns yet. Unassigned team work is a shared queue and belongs on every member's board; the moment it
is owned it is that person's job and leaves everyone else's. See `_team_queue`.
"own"  = "assigned", or task.created_by_id == user.id (the automatic creator tag) — a team lead
keeps sight of what they raised for another team.
"team" = task.assigned_team_id == user.team_id (a team lead's own team).
"""
from __future__ import annotations

from ..constants import (
    ADMIN_ROLES,
    MANAGER_ROLES,
    ROLE_ACCOUNT_MANAGER,
    ROLE_TEAM_LEAD,
    ROLE_VIEWER,
    VIEW_ALL_ROLES,
)
from ..models import Task, User
from . import maintasks as MT

# Full-authority roles: see/do everything, anywhere.
FULL = ADMIN_ROLES | {ROLE_ACCOUNT_MANAGER}          # account_manager, admin, super_admin
BRIDGE = ADMIN_ROLES | {ROLE_ACCOUNT_MANAGER}        # who may push a task to Atrium
# The read-only seat (decision D8). Kept as a set so a second such role is one entry, not a rewrite.
READ_ONLY = {ROLE_VIEWER}


def _is_full(user: User) -> bool:
    return user.role in FULL


def is_read_only(user: User) -> bool:
    """Public name for the read-only seat, for the few guards that take no task (create, the Monitor
    rollup). Same test as `_is_viewer` — one definition, two audiences."""
    return _is_viewer(user)


def _is_viewer(user: User) -> bool:
    """🔴 Tested FIRST in every write predicate, before `_is_full` (§5.3).

    A viewer is not "an admin minus some things" and it is not "an employee plus some things" — it is
    an orthogonal seat: **sees everything, writes nothing**. Ordering matters because the whole point
    is that no future widening of FULL, MANAGER_ROLES or ROLE_RANK can accidentally hand it a write.
    """
    return user.role in READ_ONLY


def _leads_team(user: User, task: Task) -> bool:
    return user.role == ROLE_TEAM_LEAD and task.assigned_team_id is not None and task.assigned_team_id == user.team_id


def _assigned(user: User, task: Task) -> bool:
    if task.assigned_to_id == user.id:
        return True
    # A user assigned to any sub-task of the breakdown can also see/act on the task.
    for m in MT.normalize(getattr(task, "maintasks_json", "[]"), task.checklist_json):
        if m.get("assignee_id") == user.id or any(s.get("assignee_id") == user.id for s in m.get("subs", [])):
            return True
    return False


def _created(user: User, task: Task) -> bool:
    """The automatic creator tag, set on create — never a form field. It grants sight to a team lead
    (work they raised for another team) and lets any creator delete their own card; on its own it no
    longer keeps a delegated card on an employee's/intern's board (see can_view)."""
    return getattr(task, "created_by_id", None) == user.id


def _team_queue(user: User, task: Task) -> bool:
    """Work sitting in MY team's queue, owned by nobody yet (§2.4c, decision D10/D12).

    🔴 The narrow condition is the point. Routing a card to a team used to surface it to nobody but
    managers, so the natural flow — AM files it → routes it to Acquisition → the lead delegates the
    steps — left the card invisible during the middle step. But making *every* team card visible to
    every member would undo the July 2026 fix that stopped an employee's board carrying other
    people's work.

    So: **unassigned** team work is a shared queue and shows; the moment somebody owns it, it is
    their job and drops off everyone else's board. That is what makes "routed but unassigned" a
    first-class state rather than a gap.
    """
    return (task.assigned_team_id is not None
            and task.assigned_team_id == user.team_id
            and task.assigned_to_id is None)


def _unowned_client_work(task: Task) -> bool:
    """A row linked to a client's Atrium card that nobody owns and no team has been given.

    🔴 This is the state ADOPTION creates (WP 3.4/4.3), and it is why collapsing the two permission
    models is not just deleting the Atrium ones. An adopted card becomes an ordinary Sentinel row —
    but one with no assignee, no team and a creator tag naming whichever super-admin ran the import.
    Every clause of `can_view` is written in terms of those three, so a team lead who can see that
    client's card TODAY (via the role-based `can_view_atrium`) would stop seeing it the moment it
    was adopted. Client work would quietly leave the boards of the people who deliver it.

    So the manager surface survives the collapse as a STATE rather than as a card source: unowned,
    unrouted client work is everybody-senior's to triage, exactly like `_team_queue` but with no
    team to key on yet. The moment somebody owns it or it is routed, the ordinary rules take over
    and it leaves the boards it is not on — which is the same rule the rest of this module follows.
    """
    return (getattr(task, "atrium_task_id", None) is not None
            and task.assigned_to_id is None
            and task.assigned_team_id is None)


def can_view(user: User, task: Task) -> bool:
    # A viewer sees the whole board — that is the seat's entire purpose (D8). Cross-client, because
    # it is a monitoring seat and a per-team viewer would answer no useful question.
    if user.role in VIEW_ALL_ROLES:
        return True
    if user.role == ROLE_TEAM_LEAD:
        return (_leads_team(user, task) or _assigned(user, task) or _created(user, task)
                or _unowned_client_work(task))
    # Employee / intern: what is handed to them, plus their team's untriaged queue. Their board still
    # answers "what am I working on" -- it just no longer pretends work routed to their team doesn't
    # exist until somebody names them on it.
    return _assigned(user, task) or _team_queue(user, task)


def can_edit(user: User, task: Task) -> bool:
    """Edit a task's own fields (title, dates, breakdown, labels, notes) — anyone who can see it,
    EXCEPT the read-only seat.

    🔴 This was `can_edit = can_view`, a bare alias, until 2026-08-03 (§2.4b). That alias is exactly
    why no read-only seat could exist: anyone who could see a card could rewrite its title, dates,
    breakdown and notes. Splitting the two IS decision D8 — keep them separate functions even though
    the bodies look near-identical, because the next person to add a role needs the seam to be here.
    """
    if _is_viewer(user):
        return False
    return can_view(user, task)


def can_move(user: User, task: Task) -> bool:
    """Move a card between statuses — same scope as edit."""
    return can_edit(user, task)


def can_reassign(user: User, task: Task) -> bool:
    """Change the assignee/team to SOMEONE ELSE (delegation) — team_lead within their team, and up."""
    if _is_viewer(user):
        return False
    return _is_full(user) or _leads_team(user, task)


def can_tick_step(user: User, task: Task, step_owner_id: int | None) -> bool:
    """Tick / untick ONE step of the breakdown (2026-08-05).

    Editing the work — renaming a step, adding one, deleting one, reordering — stays open to whoever
    can edit the card. Marking a step **done** is different: it is a claim about work somebody else
    performed, it is what the progress bar and the D5 review gate read, and on a card with several
    owners it was silently available to all of them. So:

        no owner        -> anyone who can edit (this is how the team queue is worked through)
        the owner       -> yes, obviously
        the card's lead -> yes; `assigned_to_id` is accountable for the card as a whole
        can_reassign    -> yes; a lead/AM already decides who holds the step, so they may close it
                           out for somebody on leave without reassigning it first
        anyone else     -> no

    🔴 Caller must have `can_edit` already — this narrows that permission, it never widens it, and it
    is deliberately NOT reachable for the read-only seat (which `can_edit` refuses first).
    """
    if not step_owner_id:
        return True
    if step_owner_id == user.id:
        return True
    if task.assigned_to_id == user.id:
        return True
    return can_reassign(user, task)


def can_prioritize(user: User, task: Task) -> bool:
    """Set priority — a management call. Team lead within their team, AM/admin/super anywhere."""
    if _is_viewer(user):
        return False
    return _is_full(user) or _leads_team(user, task)


def can_review(user: User, task: Task) -> bool:
    """Approve / send back work (decision D5) — team lead within their team, AM/admin/super anywhere.

    Submitting FOR review needs no special power (it is `can_edit` — you may ask about your own
    work); deciding is a management call, so it lands on the same scope as priority.

    🔴 A submitter with this power may approve their own task. That is deliberate, not an oversight:
    leads are found by QUERY (decision D9), so a team can legitimately have ZERO leads — and a hard
    self-approval block would then make the Completed column unreachable for that team forever.
    Every approval stamps `reviewer_id` and writes history, so a self-approval is visible rather
    than impossible.
    """
    return _is_full(user) or _leads_team(user, task)


def can_delete(user: User, task: Task) -> bool:
    """Delete — destructive. Team lead within their team, AM/admin/super anywhere, and the
    creator for their own tasks (anyone can quick-add a card, so anyone can clean up their
    own mistake — but never someone else's work).

    The creator branch is gated on `can_view`: once a card has left your board (a manager took it
    off you) it is no longer "your own mistake" to clean up, and deleting what you can't even see
    is never the intent."""
    if _is_viewer(user):
        return False
    return _is_full(user) or _leads_team(user, task) or (_created(user, task) and can_view(user, task))


def can_bridge(user: User) -> bool:
    """Share a task's client-safe fields to Atrium."""
    if _is_viewer(user):
        return False
    return user.role in BRIDGE


# --- Atrium-owned cards ----------------------------------------------------
# 🔴 SCOPE NARROWED BY WP 4.3: these three now govern ONLY a card with no Sentinel row — one that
# has never been shared from here and has not been adopted. Every card is governed by exactly one
# model, and which one is decided by a fact about the card (does a linked row exist?) rather than by
# which list it arrived in. That is the "collapse" 4.3 asked for; the two models no longer overlap.
#
# The board list drops any Atrium card already claimed by a Sentinel row
# (`task_adoption.claimed_atrium_ids`), so an adopted or shared card reaches these predicates never
# — it is a `Task` and answers `can_view` / `can_edit` / `can_move` like anything else, with
# `_unowned_client_work` above keeping it on the managers' boards until somebody owns it.
#
# What is left below is the genuinely unadopted card, which still has no local Task row: no
# assignee, no team, no creator tag. Every rule above is written in terms of those three, so none of
# them can apply — the only honest way to scope it is by role. These stay until adoption has run
# everywhere; they are not dead code, they are the pre-adoption path.
#
# Visibility is a MANAGER surface (team lead and up). Until 2026-07-30 `list_tasks` appended every
# Atrium card to every board unfiltered, so an intern's "your tasks" board filled up with unassigned
# client work from clients they don't touch — which is what this fixes.
#
# Editing a card's content follows visibility exactly (never "you may look at client work but not
# fix it" — that dead end is what the in-place editor replaced). The three decisions that are not
# the editor's to make stay with FULL, mirroring can_prioritize / can_bridge / can_delete for work
# nobody on the team owns.


def can_view_atrium(user: User) -> bool:
    """See client cards Atrium owns on this board — team lead and up.

    Managers work across clients, so the cross-client client-facing board is theirs. An
    employee's/intern's board is the work assigned to *them*, and an Atrium card is assigned to
    nobody here (its owners are Atrium roster emails, not Sentinel users)."""
    return user.role in MANAGER_ROLES or _is_viewer(user)


def can_edit_atrium(user: User) -> bool:
    """Edit an Atrium card's content (title, dates, breakdown, notes, comments) — whoever sees it,
    EXCEPT the read-only seat.

    🔴 The second bare alias split by D8. `routers/tasks.py` guarded every Atrium branch — read AND
    write — with `_require_atrium` (i.e. `can_view_atrium`), so the moment a viewer could SEE client
    cards it could also edit, move, comment on and resolve them. The write branches call
    `_require_atrium_write` now; this predicate is what it asks.
    """
    if _is_viewer(user):
        return False
    return can_view_atrium(user)


def can_manage_atrium(user: User) -> bool:
    """Priority, client visibility and deletion on an Atrium card — AM / admin / super_admin."""
    if _is_viewer(user):
        return False
    return user.role in FULL

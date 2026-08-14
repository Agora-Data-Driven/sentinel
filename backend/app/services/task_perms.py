"""Centralized task-board permission model — the one place task RBAC lives.

The rules (higher roles inherit lower ones):

    | action        | employee/intern | team_lead        | account_manager | admin/super_admin |
    | view          | assigned + team queue + DEPARTMENT | team + own | all  | all               |
    | create        | yes             | yes              | yes             | yes               |
    | edit fields   | assigned + team queue | anything visible | all       | all               |
    | tick a step   | own + unowned   | anything visible | all             | all               |
    | reassign      | self only       | anything visible | all             | all               |
    | priority      | no              | anything visible | all             | all               |
    | review/approve| no              | anything visible | all             | all               |
    | delete        | own created     | team + created   | all             | all               |
    | move status   | assigned + team queue | anything visible | all       | all               |
    | bridge/Atrium | no              | no               | AM              | admin/super       |
    | see Atrium    | no              | yes              | yes             | yes               |

🔴 TWO ROWS IN THAT TABLE DISAGREE WITH EACH OTHER ON PURPOSE (2026-08-14), and both are load-bearing:

* an employee **views** their whole department and **edits** far less than they view. `can_edit` is
  therefore no longer `can_view` minus the viewer seat — see its docstring. A department you can read
  but not touch is the point; making the two match would hand every employee write access to every
  colleague's card, which is not what "let me see my department" asked for.
* a team lead **delete**s less than they can otherwise act on. See `can_delete` — delete is the one
  irreversible act here, and `can_view` reaches a lead through branches as thin as owning one step.

"assigned" = task.assigned_to_id == user.id, **a supporter of the task**, or assigned to one of the
task's sub-tasks (`is_assigned` — public, because "what is on me" is asked by more than this module).

🔴 SUPPORT (2026-08-06) widens "assigned" and NOTHING else. A supporter can see, edit and move the
card exactly as a step owner already could; they do not become accountable for it. Every rule below
that says `assigned_to_id` still means the ONE lead — the triage queue, send-back, bulk-claim, and
the lead's right to tick another person's step. See `assigned_user_ids` and `models.TaskSupporter`.

For an
employee/intern that is the rule for OWNED work: someone else's card is not on their board, nor is
one they created themselves (2026-07-30; before that the automatic creator tag also granted sight,
which meant a card an intern raised and a manager then delegated stayed on the intern's board).
"team queue" (added 2026-08-03, §2.4c) is the one addition: work routed to their team that NOBODY
owns yet. Unassigned team work is a shared queue and belongs on every member's board; the moment it
is owned it is that person's job and leaves everyone else's. See `_team_queue`.
"own"  = "assigned", or task.created_by_id == user.id (the automatic creator tag) — a team lead
keeps sight of what they raised for another team.
"team" = task.assigned_team_id is one of the user's DEPARTMENTS.

🔴 "one of" is literal: a person may belong to SEVERAL departments (2026-08-14, `models.UserTeam`).
`users.team_id` is still their primary one — it is what decides their shift, their payroll row and
the Department column in People — but participation is a SET, and every rule in this module tests
the set through `services/teams.team_ids`. Nothing here compares two team ids directly any more;
if you add a rule that does, it will be correct for the estate's single-department majority and
quietly wrong for exactly the people this was written for.
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
from . import teams as TEAMS

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


def _dept(user: User, task: Task) -> bool:
    """This work is routed to ONE OF the user's departments. Read-relevant for everyone.

    🔴 Split out of `_leads_team` on 2026-08-14 because two different questions were sharing one
    function: "does this belong to my department?" (a fact about the card, true for every member)
    and "am I the lead of the department it belongs to?" (a permission). An employee now needs the
    first one — see `can_view` — and giving them the second would be a role escalation.

    🔴 **A PERSON MAY BE IN SEVERAL DEPARTMENTS (2026-08-14, later the same day).** This was
    `task.assigned_team_id == user.team_id`, one integer against one integer — which silently
    asserted that everybody belongs to exactly one team. People here do not: a designer who also
    sits with Acquisition, or a lead covering a second department while it has no lead of its own,
    could see only their PRIMARY team's board and were invisible to the other one's rollups. The
    union lives in `services/teams.team_ids`, which is also where `users.team_id`'s surviving job
    (shift, payroll, the directory column) is written down. Ask that function; never re-derive it.
    """
    return task.assigned_team_id is not None and task.assigned_team_id in TEAMS.team_ids(user)


def _leads_team(user: User, task: Task) -> bool:
    """This user is a team lead AND the card is routed to one of THEIR departments.

    A lead of two departments leads both — the role is a property of the person and `_dept` is now a
    set test (`services/teams`), so nothing here had to change to support that. What it deliberately
    does NOT mean is "a lead of any department may act on any department's card": the `_dept` half
    is still the whole point of this predicate, which is why `can_delete` keeps asking it while
    every other lead power moved to `_lead_may_act`.
    """
    return user.role == ROLE_TEAM_LEAD and _dept(user, task)


def is_assigned(user: User, task: Task) -> bool:
    """🔴 The ONE definition of "this work is on me" — the card's lead **or** any slot of its
    breakdown.

    Public since 2026-08-05, because it was being re-derived. Every SURFACE that answers "what is on
    me" has to ask this exact question, and the Overview's "my work" strip asked a narrower one
    (`assigned_to_id === me`, in JS). So a card led by a colleague with a step named to YOU was on
    your Task Board — `can_view` calls this — and simultaneously absent from the strip that claims to
    count your open work: "0 open tasks · nothing on you right now", with the card one click away.
    Naming somebody on a sub-task IS delegation (§5, `maintasks.slots`); a surface that doesn't count
    it tells the delegate their plate is empty.

    So: no second copy of this rule, in any language. `serializers.task_card` publishes the answer as
    `mine` and the frontend filters on that.
    """
    return user.id in assigned_user_ids(task)


def assigned_user_ids(task: Task) -> set[int]:
    """Everyone this work sits on: the card's lead, its **supporters**, and every phase/step owner.

    The set form of `is_assigned`, and `is_assigned` is defined in terms of it so the two can never
    drift — the whole point of making that rule public was that a second copy of it had already gone
    wrong once. This direction exists for the rollups (`/api/tasks/summary`), which need "who is this
    card on?" once per task rather than "is it on X?" once per person per task.

    🔴 A card can be in MORE THAN ONE person's set, so per-person totals built from this **do not sum
    to the number of cards**. That is the truth about a shared card, not an error to normalise away:
    a build phase owned by one person and a QA step owned by another really is on both plates. Any
    surface that adds these up has to say so.

    🔴 **SUPPORT JOINS HERE, AND ONLY HERE (2026-08-06).** This one line is what gives supporters the
    card on their board, in "My work", in their By Employee lane and in their Monitor row — because
    every one of those surfaces already asks this function and nothing else. Adding support to any of
    them individually would have been the second copy of the rule that this function exists to
    prevent. What support deliberately does NOT reach is anything keyed on `assigned_to_id` itself:
    accountability (`can_tick_step`'s lead clause), the team triage queue (`_team_queue`), send-back,
    bulk-claim, and the `?assignee_id=` field filter. Support is who is ON the work; the lead is who
    ANSWERS for it, and those are different questions.
    """
    ids: set[int] = set()
    if task.assigned_to_id:
        ids.add(task.assigned_to_id)
    ids.update(s.user_id for s in (getattr(task, "supporters", None) or []))
    for m in MT.normalized(task):
        if m.get("assignee_id"):
            ids.add(m["assignee_id"])
        ids.update(s["assignee_id"] for s in m.get("subs", []) if s.get("assignee_id"))
    return ids


def is_supporting(user: User, task: Task) -> bool:
    """`user` is on this card as SUPPORT — helping, not accountable.

    Public so a surface can SAY which hat somebody is wearing. `mine` alone cannot: a card is "mine"
    whether I lead it, support it, or own one step of it, and a list that renders all three
    identically reads as the July 2026 regression where a board showed other people's work. This is
    the support half of what `my_slot_count` does for the breakdown.
    """
    return any(s.user_id == user.id for s in (getattr(task, "supporters", None) or []))


def my_slot_count(user: User, task: Task) -> int:
    """How many phases/steps of the breakdown name `user` — 0 when only `assigned_to_id` does.

    Exists so a surface can SAY WHY a card led by somebody else is on your list. Without it, "my
    work" silently lists a card whose Assigned-to reads another name, which looks like the bug this
    replaced rather than the fix for it.
    """
    n = 0
    for m in MT.normalized(task):
        if m.get("assignee_id") == user.id:
            n += 1
        n += sum(1 for s in m.get("subs", []) if s.get("assignee_id") == user.id)
    return n


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

    🔴 Reads ALL of the user's departments (`_dept`), not just their primary one — somebody who
    takes part in two departments is in both triage queues, which is the whole reason they are in
    both departments.
    """
    return _dept(user, task) and task.assigned_to_id is None


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
        return (_leads_team(user, task) or is_assigned(user, task) or _created(user, task)
                or _unowned_client_work(task))
    # Employee / intern: what is handed to them, their team's untriaged queue, and — since
    # 2026-08-14 — everything else their DEPARTMENT is carrying.
    #
    # 🔴 `_dept` here is a READ ONLY. It is deliberately absent from `can_edit` below, and that
    # asymmetry is the whole design. The July 2026 fix that stopped an employee's board carrying
    # other people's work was about ACCOUNTABILITY — a board that lists ten colleagues' cards no
    # longer answers "what am I working on". But it also made a department opaque to the people in
    # it: you could not see what your own team was carrying, who was drowning, or whether the thing
    # you were about to raise already existed. Those are two different needs and they were being
    # answered by one predicate.
    #
    # So: an employee SEES their department's work and CANNOT touch it. `mine` / "My work" still
    # answers the accountability question (`is_assigned`), and the board's scope selector defaults
    # to it — the department is a place you go to look, not the pile you are handed.
    return is_assigned(user, task) or _team_queue(user, task) or _dept(user, task)


def can_edit(user: User, task: Task) -> bool:
    """Edit a task's own fields (title, dates, breakdown, labels, notes) — anyone who can see it,
    EXCEPT the read-only seat.

    🔴 This was `can_edit = can_view`, a bare alias, until 2026-08-03 (§2.4b). That alias is exactly
    why no read-only seat could exist: anyone who could see a card could rewrite its title, dates,
    breakdown and notes. Splitting the two IS decision D8 — keep them separate functions even though
    the bodies look near-identical, because the next person to add a role needs the seam to be here.

    🔴 AND THE BODIES NO LONGER LOOK ALIKE, ON PURPOSE (2026-08-14). `can_view` gained a DEPARTMENT
    branch for employees/interns so a team is not opaque to its own members. Had this stayed an alias,
    that one read would have silently handed every employee edit and move rights over every
    colleague's card in their department — a far bigger change than the one being made, arriving as a
    side effect of it. This is the exact seam D8 predicted somebody would need, so it is being used
    rather than widened: an employee writes only to work that is genuinely on them, or to their team's
    unowned queue.

    Anyone who can act on the department as a whole (team lead, AM, admin, super) keeps the old
    equivalence, because for them `can_view`'s branches ARE their authority.
    """
    if _is_viewer(user):
        return False
    if _is_full(user) or user.role == ROLE_TEAM_LEAD:
        return can_view(user, task)
    return is_assigned(user, task) or _team_queue(user, task)


def can_move(user: User, task: Task) -> bool:
    """Move a card between statuses — same scope as edit."""
    return can_edit(user, task)


def _lead_may_act(user: User, task: Task) -> bool:
    """🔴 A TEAM LEAD'S MANAGEMENT POWERS FOLLOW VISIBILITY, NOT THE TEAM FIELD (2026-08-14).

    This is the fix for "the Team Lead can't assign" and "the Team Lead can't approve" — one bug
    reported twice. Every lead power (`can_reassign`, `can_review`, `can_prioritize`) used to ask
    `_leads_team`, i.e. `task.assigned_team_id == user.team_id`. But `can_view` grants a lead sight
    of a card through FOUR different branches, and only that one of them carried any authority. So
    the board routinely handed a lead a card whose every control was dead:

    * a card with **no department at all** — the default for anything quick-added, including work
      assigned to the lead personally. `assigned_team_id is None` fails the `is not None` test;
    * an **adopted Atrium card**, which `_unowned_client_work` shows leads *precisely because* it has
      no team and no owner — the state that predicate exists to describe is the state that disabled
      every button on it;
    * a card the lead **raised for another department** (`_created`);
    * a card led by somebody else with a **step named to the lead** (`is_assigned`);
    * and the flat case — the lead's own `users.team_id` never set, which killed all of it everywhere
      and looked exactly like an application bug.

    The failure was silent in the worst way: `taskboard.js` mirrors these predicates, so the assignee
    picker rendered `disabled` and Approve was never drawn at all. Nobody saw a 403; they saw a
    feature that did not exist.

    A lead only ever RECEIVES cards `can_view` already let through, so "anything they can see" is the
    honest statement of the authority they were always meant to have. `_leads_team` survives for the
    places that really are about the department (below) — it is not dead.
    """
    return user.role == ROLE_TEAM_LEAD and can_view(user, task)


def can_reassign(user: User, task: Task) -> bool:
    """Change the assignee/team to SOMEONE ELSE (delegation) — a team lead on any card they can see,
    and up. See `_lead_may_act`."""
    if _is_viewer(user):
        return False
    return _is_full(user) or _lead_may_act(user, task)


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
    """Set priority — a management call. A team lead on any card they can see (`_lead_may_act`),
    AM/admin/super anywhere."""
    if _is_viewer(user):
        return False
    return _is_full(user) or _lead_may_act(user, task)


def can_review(user: User, task: Task) -> bool:
    """Approve / send back work (decision D5) — team lead within their team, AM/admin/super anywhere.

    Submitting FOR review needs no special power (it is `can_edit` — you may ask about your own
    work); deciding is a management call, so it lands on the same scope as priority.

    🔴 A submitter with this power may approve their own task. That is deliberate, not an oversight:
    leads are found by QUERY (decision D9), so a team can legitimately have ZERO leads — and a hard
    self-approval block would then make the Completed column unreachable for that team forever.
    Every approval stamps `reviewer_id` and writes history, so a self-approval is visible rather
    than impossible.

    🔴 Scope widened to `_lead_may_act` on 2026-08-14 — read that docstring. The team-only test made
    the Completed column unreachable for exactly the cards a lead is most likely to be asked about:
    anything with no department set, and every adopted client card.
    """
    return _is_full(user) or _lead_may_act(user, task)


def can_delete(user: User, task: Task) -> bool:
    """Delete — destructive. Team lead within their team, AM/admin/super anywhere, and the
    creator for their own tasks (anyone can quick-add a card, so anyone can clean up their
    own mistake — but never someone else's work).

    The creator branch is gated on `can_view`: once a card has left your board (a manager took it
    off you) it is no longer "your own mistake" to clean up, and deleting what you can't even see
    is never the intent.

    🔴 DELIBERATELY STILL `_leads_team`, not `_lead_may_act` (2026-08-14). Assign, approve and
    prioritise were widened to everything a lead can SEE, because withholding them produced dead
    buttons on cards the lead was accountable for. Delete is not symmetrical with those: it is the
    one irreversible act on this board, and `can_view` reaches a lead through branches as thin as
    "somebody named you on one step of this card". Losing another department's work to a misclick
    from a lead who holds one step of it is a worse failure than the friction of asking an AM. The
    creator branch below already covers the ordinary "clean up my own mistake" case."""
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

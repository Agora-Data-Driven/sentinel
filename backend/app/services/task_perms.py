"""Centralized task-board permission model — the one place task RBAC lives.

The rules (higher roles inherit lower ones):

    | action        | employee/intern | team_lead        | account_manager | admin/super_admin |
    | view          | assigned        | team + own       | all             | all               |
    | create        | yes             | yes              | yes             | yes               |
    | edit fields   | assigned        | team + own       | all             | all               |
    | reassign      | self only       | team             | all             | all               |
    | priority      | no              | team (scoped)    | all             | all               |
    | delete        | own created     | team + created   | all             | all               |
    | move status   | assigned        | team             | all             | all               |
    | bridge/Atrium | no              | no               | AM              | admin/super       |
    | see Atrium    | no              | yes              | yes             | yes               |

"assigned" = task.assigned_to_id == user.id, or assigned to one of the task's sub-tasks. That is
the WHOLE rule for an employee/intern: their board is their own work queue, so a card that is
unassigned, or someone else's, is not on it — even one they created themselves (2026-07-30; before
that the automatic creator tag also granted sight, which meant a card an intern raised and a
manager then delegated stayed on the intern's board).
"own"  = "assigned", or task.created_by_id == user.id (the automatic creator tag) — a team lead
keeps sight of what they raised for another team.
"team" = task.assigned_team_id == user.team_id (a team lead's own team).
"""
from __future__ import annotations

from ..constants import ADMIN_ROLES, MANAGER_ROLES, ROLE_ACCOUNT_MANAGER, ROLE_TEAM_LEAD
from ..models import Task, User
from . import maintasks as MT

# Full-authority roles: see/do everything, anywhere.
FULL = ADMIN_ROLES | {ROLE_ACCOUNT_MANAGER}          # account_manager, admin, super_admin
BRIDGE = ADMIN_ROLES | {ROLE_ACCOUNT_MANAGER}        # who may push a task to Atrium


def _is_full(user: User) -> bool:
    return user.role in FULL


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


def can_view(user: User, task: Task) -> bool:
    if _is_full(user):
        return True
    if user.role == ROLE_TEAM_LEAD:
        return _leads_team(user, task) or _assigned(user, task) or _created(user, task)
    # Employee / intern: assignment is the whole rule. Their board answers "what am I working on",
    # so it must not carry work nobody handed them -- see the module docstring.
    return _assigned(user, task)


# Editing a task's own fields (title, dates, breakdown, labels, notes) = anyone who can see it.
can_edit = can_view


def can_move(user: User, task: Task) -> bool:
    """Move a card between statuses — same scope as edit."""
    return can_view(user, task)


def can_reassign(user: User, task: Task) -> bool:
    """Change the assignee/team to SOMEONE ELSE (delegation) — team_lead within their team, and up."""
    return _is_full(user) or _leads_team(user, task)


def can_prioritize(user: User, task: Task) -> bool:
    """Set priority — a management call. Team lead within their team, AM/admin/super anywhere."""
    return _is_full(user) or _leads_team(user, task)


def can_delete(user: User, task: Task) -> bool:
    """Delete — destructive. Team lead within their team, AM/admin/super anywhere, and the
    creator for their own tasks (anyone can quick-add a card, so anyone can clean up their
    own mistake — but never someone else's work).

    The creator branch is gated on `can_view`: once a card has left your board (a manager took it
    off you) it is no longer "your own mistake" to clean up, and deleting what you can't even see
    is never the intent."""
    return _is_full(user) or _leads_team(user, task) or (_created(user, task) and can_view(user, task))


def can_bridge(user: User) -> bool:
    """Share a task's client-safe fields to Atrium."""
    return user.role in BRIDGE


# --- Atrium-owned cards ----------------------------------------------------
# A card Atrium owns (board id "atrium:<client_key>:<task_id>") has no local Task row: no assignee,
# no team, no creator tag. Every rule above is written in terms of those three, so none of them can
# apply — these three are the whole model for that kind of card, and the only honest way to scope
# them is by role.
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
    return user.role in MANAGER_ROLES


def can_edit_atrium(user: User) -> bool:
    """Edit an Atrium card's content (title, dates, breakdown, notes, comments) — whoever sees it."""
    return can_view_atrium(user)


def can_manage_atrium(user: User) -> bool:
    """Priority, client visibility and deletion on an Atrium card — AM / admin / super_admin."""
    return user.role in FULL

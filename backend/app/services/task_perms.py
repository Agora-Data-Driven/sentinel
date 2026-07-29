"""Centralized task-board permission model — the one place task RBAC lives.

The rules (higher roles inherit lower ones):

    | action        | employee/intern | team_lead        | account_manager | admin/super_admin |
    | view          | own             | team + own       | all             | all               |
    | create        | yes             | yes              | yes             | yes               |
    | edit fields   | own             | team + own       | all             | all               |
    | reassign      | self only       | team             | all             | all               |
    | priority      | no              | team (scoped)    | all             | all               |
    | delete        | own created     | team + created   | all             | all               |
    | move status   | own             | team             | all             | all               |
    | bridge/Atrium | no              | no               | AM              | admin/super       |

"own" = task.assigned_to_id == user.id (or assigned to one of the user's sub-tasks), OR
task.created_by_id == user.id — the creator tag is set automatically on create, so a task an
employee quick-adds stays on their board even while unassigned or after a manager reassigns it.
"team" = task.assigned_team_id == user.team_id (a team lead's own team).
"""
from __future__ import annotations

from ..constants import ADMIN_ROLES, ROLE_ACCOUNT_MANAGER, ROLE_TEAM_LEAD
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
    """The automatic creator tag — whoever made the task never loses sight of it."""
    return getattr(task, "created_by_id", None) == user.id


def can_view(user: User, task: Task) -> bool:
    return _is_full(user) or _leads_team(user, task) or _assigned(user, task) or _created(user, task)


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
    own mistake — but never someone else's work)."""
    return _is_full(user) or _leads_team(user, task) or _created(user, task)


def can_bridge(user: User) -> bool:
    """Share a task's client-safe fields to Atrium."""
    return user.role in BRIDGE


# --- Atrium-owned cards ----------------------------------------------------
# A card Atrium owns (board id "atrium:<client_key>:<task_id>") has no local Task row: no assignee,
# no team, no creator tag. Every rule above is written in terms of those three, so none of them can
# apply — these two are the whole model for that kind of card.
#
# Everyone who loads the board already SEES every Atrium card (list_tasks appends them unfiltered),
# so hiding the editor behind a role would only mean "you may look at client work but not fix it" —
# which is what the old "open it in Atrium" dead end amounted to. Editing content is therefore open
# to any staff member, exactly like `can_edit` on a Sentinel task you can see.
#
# The three decisions that are not the editor's to make stay with managers, mirroring
# can_prioritize / can_bridge / can_delete for work nobody on the team owns.


def can_edit_atrium(user: User) -> bool:
    """Edit an Atrium card's content (title, dates, breakdown, notes, comments) — any staff."""
    return True


def can_manage_atrium(user: User) -> bool:
    """Priority, client visibility and deletion on an Atrium card — AM / admin / super_admin."""
    return user.role in FULL

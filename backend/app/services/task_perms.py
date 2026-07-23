"""Centralized task-board permission model — the one place task RBAC lives.

The rules (higher roles inherit lower ones):

    | action        | employee/intern | team_lead        | account_manager | admin/super_admin |
    | view          | own             | team + own       | all             | all               |
    | create        | yes             | yes              | yes             | yes               |
    | edit fields   | own             | team + own       | all             | all               |
    | reassign      | self only       | team             | all             | all               |
    | priority      | no              | team (scoped)    | all             | all               |
    | delete        | no              | team (scoped)    | all             | all               |
    | move status   | own             | team             | all             | all               |
    | bridge/Atrium | no              | no               | AM              | admin/super       |

"own" = task.assigned_to_id == user.id (or assigned to one of the user's sub-tasks).
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


def can_view(user: User, task: Task) -> bool:
    return _is_full(user) or _leads_team(user, task) or _assigned(user, task)


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
    """Delete — destructive. Team lead within their team, AM/admin/super anywhere."""
    return _is_full(user) or _leads_team(user, task)


def can_bridge(user: User) -> bool:
    """Share a task's client-safe fields to Atrium."""
    return user.role in BRIDGE

"""The task-board predicates that became CAPABILITIES (2026-08-18).

The whole risk of that change is that a rewrite silently widens or narrows an authority, so this
file's centre of gravity is `test_*_is_unchanged_for_every_role`: it re-implements each predicate's
ORIGINAL body and asserts the new one agrees, for every role, against a matrix of task shapes.
"""
from __future__ import annotations

import pytest

from app import constants as C
from app.capabilities import BY_KEY
from app.models import RoleCapability, Task
from app.services import permissions as perms_svc
from app.services import task_perms as TP

FULL = {C.ROLE_ACCOUNT_MANAGER, C.ROLE_ADMIN, C.ROLE_SUPER_ADMIN}


# --- the ORIGINAL bodies, kept verbatim so the equivalence is checked and not asserted ----------
def _orig_lead_may_act(u, t):
    return u.role == C.ROLE_TEAM_LEAD and TP.can_view(u, t)


def _orig_managerial(u, t):
    """What can_reassign / can_prioritize / can_review all used to be."""
    if TP.is_read_only(u):
        return False
    return (u.role in FULL) or _orig_lead_may_act(u, t)


def _orig_can_delete(u, t):
    if TP.is_read_only(u):
        return False
    return ((u.role in FULL) or TP._leads_team(u, t)
            or (TP._created(u, t) and TP.can_view(u, t)))


def _orig_view_atrium(u):
    return u.role in C.MANAGER_ROLES or u.role == C.ROLE_VIEWER


@pytest.fixture
def board(db, make_team, make_user):
    """One card per interesting shape, plus a user of every role in/out of the department."""
    team = make_team("Creative")
    other = make_team("Acquisition")
    owner = make_user(C.ROLE_EMPLOYEE, team_id=team.id, email="owner@t.ph")
    users = {r: make_user(r, team_id=team.id, email=f"{r}@t.ph") for r in C.ALL_ROLES}
    outsiders = {r: make_user(r, team_id=other.id, email=f"out-{r}@t.ph") for r in C.ALL_ROLES}
    shapes = {}
    for name, kwargs in {
        "in_dept_assigned_to_owner": dict(assigned_team_id=team.id, assigned_to_id=owner.id),
        "in_dept_unclaimed": dict(assigned_team_id=team.id, assigned_to_id=None),
        "other_dept": dict(assigned_team_id=other.id, assigned_to_id=None),
        "no_dept_no_owner": dict(assigned_team_id=None, assigned_to_id=None),
    }.items():
        t = Task(title=name, status=C.TASK_TODO, **kwargs)
        db.add(t)
        shapes[name] = t
    db.commit()
    return {"users": users, "outsiders": outsiders, "shapes": shapes, "team": team}


_PREDICATES = [
    ("can_reassign", TP.can_reassign, _orig_managerial),
    ("can_prioritize", TP.can_prioritize, _orig_managerial),
    ("can_review", TP.can_review, _orig_managerial),
    ("can_delete", TP.can_delete, _orig_can_delete),
]


@pytest.mark.parametrize("name,new,orig", _PREDICATES, ids=[p[0] for p in _PREDICATES])
def test_predicate_is_unchanged_for_every_role(name, new, orig, board):
    """🔴 THE LOAD-BEARING TEST. With no overrides stored, the capability rewrite must agree with the
    original body for every (role, card shape, in/out of department) combination."""
    checked = 0
    for pool in ("users", "outsiders"):
        for role, u in board[pool].items():
            for shape, t in board["shapes"].items():
                assert new(u, t) == orig(u, t), f"{name} changed for {role} on {shape} ({pool})"
                checked += 1
    assert checked == len(C.ALL_ROLES) * 4 * 2


def test_the_collapse_premise_still_holds():
    """`_may_act_on_visible` is only equivalent to the old body because FULL ⊆ VIEW_ALL_ROLES, which
    makes `can_view` unconditionally True for those roles. If that stops being true the three
    managerial predicates silently NARROW, so the premise is pinned here in its own right."""
    assert FULL <= C.VIEW_ALL_ROLES


@pytest.mark.parametrize("role", sorted(C.ALL_ROLES))
def test_atrium_predicates_unchanged(role, make_user):
    u = make_user(role, email=f"atr-{role}@t.ph")
    assert TP.can_view_atrium(u) == _orig_view_atrium(u)
    assert TP.can_edit_atrium(u) == (_orig_view_atrium(u) and role != C.ROLE_VIEWER)
    assert TP.can_manage_atrium(u) == (role in FULL)
    assert TP.can_bridge(u) == (role in FULL)


# --- the new powers the rewrite buys ------------------------------------------------------------
def test_granting_review_to_an_employee_is_scoped_to_what_they_can_see(db, board):
    """The point of the change: the grant carries `can_view` with it, so it is not a blanket power."""
    emp = board["users"][C.ROLE_EMPLOYEE]
    mine = board["shapes"]["in_dept_unclaimed"]
    theirs = board["shapes"]["other_dept"]
    assert TP.can_review(emp, mine) is False

    db.add(RoleCapability(role=C.ROLE_EMPLOYEE, capability="tasks.review", allowed=True))
    db.commit()
    perms_svc.invalidate()

    assert TP.can_review(emp, mine) is True          # their department's queue — they can see it
    assert TP.can_review(emp, theirs) is False       # another department — invisible, so refused


def test_revoking_review_from_an_account_manager_takes_effect(db, board):
    am = board["users"][C.ROLE_ACCOUNT_MANAGER]
    card = board["shapes"]["other_dept"]
    assert TP.can_review(am, card) is True
    db.add(RoleCapability(role=C.ROLE_ACCOUNT_MANAGER, capability="tasks.review", allowed=False))
    db.commit()
    perms_svc.invalidate()
    assert TP.can_review(am, card) is False


def test_delete_scope_rides_with_the_grant(db, board):
    """A granted employee may tidy their DEPARTMENT, never everything they can see."""
    emp = board["users"][C.ROLE_EMPLOYEE]
    db.add(RoleCapability(role=C.ROLE_EMPLOYEE, capability="tasks.delete", allowed=True))
    db.commit()
    perms_svc.invalidate()
    assert TP.can_delete(emp, board["shapes"]["in_dept_unclaimed"]) is True
    assert TP.can_delete(emp, board["shapes"]["other_dept"]) is False
    assert TP.can_delete(emp, board["shapes"]["no_dept_no_owner"]) is False


def test_creator_may_always_delete_their_own_card_without_the_capability(db, board):
    emp = board["users"][C.ROLE_EMPLOYEE]
    t = Task(title="my mistake", status=C.TASK_TODO, created_by_id=emp.id,
             assigned_team_id=board["team"].id)
    db.add(t)
    db.commit()
    assert perms_svc.has_cap(emp, "tasks.delete") is False
    assert TP.can_delete(emp, t) is True


# --- the viewer seat survives all of it ---------------------------------------------------------
@pytest.mark.parametrize("cap_key", ["tasks.review", "tasks.reassign", "tasks.prioritize",
                                     "tasks.delete", "atrium.bridge", "atrium.edit", "atrium.manage"])
def test_viewer_cannot_be_granted_any_of_the_new_writes(cap_key, db, board):
    assert BY_KEY[cap_key].write is True
    viewer = board["users"][C.ROLE_VIEWER]
    db.add(RoleCapability(role=C.ROLE_VIEWER, capability=cap_key, allowed=True))
    db.commit()
    perms_svc.invalidate()
    for t in board["shapes"].values():
        assert TP.can_review(viewer, t) is False
        assert TP.can_reassign(viewer, t) is False
        assert TP.can_prioritize(viewer, t) is False
        assert TP.can_delete(viewer, t) is False
    assert TP.can_bridge(viewer) is False
    assert TP.can_edit_atrium(viewer) is False
    assert TP.can_manage_atrium(viewer) is False


def test_atrium_view_is_a_read_the_viewer_keeps():
    assert BY_KEY["atrium.view"].write is False
    assert C.ROLE_VIEWER in BY_KEY["atrium.view"].default

"""Task visibility: an employee/intern board carries the work ASSIGNED to them — nothing else.

Two rules meet here, both learned from a real intern board (2026-07-30) that showed seven cards,
every one of them someone else's:

  * A Sentinel row is visible to an employee/intern only when it is assigned to them (or to one of
    its sub-tasks). The automatic creator tag no longer grants sight on its own — it used to, so a
    card an intern raised and a manager then delegated stayed on the intern's board.
  * An **Atrium** client card is assigned to nobody in Sentinel (its owners are Atrium roster
    emails), so it is a manager surface: team lead and up. `list_tasks` used to append every one of
    them to every board unfiltered.

Team-lead team scope and manager see-everything are unchanged (see services/task_perms.py).
"""
from __future__ import annotations

import pytest

from app import constants as C
from app.models import Task
from app.services import atrium_tasks

ATRIUM_CARD = {
    "atrium_id": "melo-yelo:tk_1", "task_id": "tk_1", "client_key": "melo-yelo",
    "client_name": "Melo Yelo", "title": "No brainer campaign", "status": "To Do",
    "priority": "Medium",
}


def _mk(db, **kw):
    t = Task(title=kw.pop("title", "T"), **kw)
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def _ids(resp):
    assert resp.status_code == 200
    return {t["id"] for t in resp.json()}


@pytest.fixture
def bridge_on(monkeypatch):
    """A working Atrium bridge serving exactly one client card."""
    monkeypatch.setattr(atrium_tasks, "enabled", lambda: True)
    monkeypatch.setattr(atrium_tasks, "fetch_tasks", lambda client_key="": [ATRIUM_CARD])
    return ATRIUM_CARD


def test_employee_sees_only_tasks_assigned_to_them(client, db, make_user, auth):
    emp = make_user(C.ROLE_EMPLOYEE)
    other = make_user(C.ROLE_EMPLOYEE)
    mine = _mk(db, title="assigned to me", assigned_to_id=emp.id)
    mine_created = _mk(db, title="created by me", created_by_id=emp.id)  # unassigned
    theirs = _mk(db, title="someone else's", assigned_to_id=other.id)
    unowned = _mk(db, title="nobody's")
    auth(emp)
    ids = _ids(client.get("/api/tasks"))
    assert mine.id in ids
    assert mine_created.id not in ids   # created, then taken off them -- not their work any more
    assert theirs.id not in ids
    assert unowned.id not in ids


def test_employee_create_is_auto_assigned_and_tagged(client, make_user, auth):
    """Quick-add still lands on the adder's own board: create auto-assigns it to them."""
    emp = make_user(C.ROLE_EMPLOYEE)
    auth(emp)
    body = client.post("/api/tasks", json={"title": "quick add"}).json()
    assert body["assigned_to_id"] == emp.id       # auto-added to their own board
    assert body["created_by_id"] == emp.id        # tagged automatically, no form field
    assert body["created_by"]["id"] == emp.id
    assert body["id"] in _ids(client.get("/api/tasks"))


def test_reassignment_takes_the_card_off_the_creators_board(client, make_user, auth):
    """The other half of "only what's assigned to me": delegate it away and it leaves."""
    emp = make_user(C.ROLE_EMPLOYEE)
    other = make_user(C.ROLE_EMPLOYEE)
    admin = make_user(C.ROLE_ADMIN)
    auth(emp)
    tid = client.post("/api/tasks", json={"title": "made by emp"}).json()["id"]
    auth(admin)
    assert client.patch(f"/api/tasks/{tid}", json={"assigned_to_id": other.id}).status_code == 200
    auth(emp)
    assert client.get(f"/api/tasks/{tid}").status_code == 403
    assert tid not in _ids(client.get("/api/tasks"))
    # ...and it is no longer theirs to delete either (can_delete's creator branch follows can_view).
    assert client.delete(f"/api/tasks/{tid}").status_code == 403


def test_employee_cannot_open_someone_elses_task(client, db, make_user, auth):
    other = make_user(C.ROLE_EMPLOYEE)
    t = _mk(db, title="private", assigned_to_id=other.id, created_by_id=other.id)
    auth(make_user(C.ROLE_EMPLOYEE))
    assert client.get(f"/api/tasks/{t.id}").status_code == 403


def test_admin_and_am_still_see_everything(client, db, make_user, auth):
    emp = make_user(C.ROLE_EMPLOYEE)
    t1 = _mk(db, title="a", assigned_to_id=emp.id)
    t2 = _mk(db, title="b")  # unassigned, untagged (pre-column legacy shape)
    for role in (C.ROLE_ADMIN, C.ROLE_ACCOUNT_MANAGER):
        auth(make_user(role))
        assert {t1.id, t2.id} <= _ids(client.get("/api/tasks"))


def test_team_lead_scope_unchanged(client, db, make_user, make_team, auth):
    team = make_team(name="A")
    lead = make_user(C.ROLE_TEAM_LEAD, team_id=team.id)
    team_task = _mk(db, title="team work", assigned_team_id=team.id)
    foreign = _mk(db, title="other team's")
    auth(lead)
    ids = _ids(client.get("/api/tasks"))
    assert team_task.id in ids
    assert foreign.id not in ids


# --- Atrium client cards are a manager surface ----------------------------
@pytest.mark.parametrize("role", [C.ROLE_INTERN, C.ROLE_EMPLOYEE])
def test_atrium_cards_are_absent_from_a_non_manager_board(client, make_user, auth, bridge_on, role):
    auth(make_user(role))
    assert _ids(client.get("/api/tasks")) == set()


@pytest.mark.parametrize("role", [C.ROLE_TEAM_LEAD, C.ROLE_ACCOUNT_MANAGER, C.ROLE_ADMIN,
                                  C.ROLE_SUPER_ADMIN])
def test_atrium_cards_are_present_for_managers(client, make_user, auth, bridge_on, role):
    auth(make_user(role))
    assert "atrium:melo-yelo:tk_1" in _ids(client.get("/api/tasks"))


@pytest.mark.parametrize("role", [C.ROLE_INTERN, C.ROLE_EMPLOYEE])
def test_a_non_manager_cannot_reach_an_atrium_card_by_id(client, make_user, auth, monkeypatch, role):
    """Hiding the card from the LIST would be theatre if its id still opened or edited it."""
    def _boom(*a, **kw):                      # the bridge must never even be called
        raise AssertionError("bridge called for a user who may not see Atrium cards")
    for fn in ("fetch_task", "edit_task", "move_task", "comment_task", "resolve_change_request"):
        monkeypatch.setattr(atrium_tasks, fn, _boom)
    auth(make_user(role))
    cid = "atrium:melo-yelo:tk_1"
    assert client.get(f"/api/tasks/{cid}").status_code == 403
    assert client.patch(f"/api/tasks/{cid}", json={"title": "nope"}).status_code == 403
    assert client.patch(f"/api/tasks/{cid}/status", json={"status": "In Progress"}).status_code == 403
    assert client.post(f"/api/tasks/{cid}/comments", json={"body": "hi"}).status_code == 403
    assert client.post(f"/api/tasks/{cid}/comments/c1/resolve").status_code == 403
    assert client.delete(f"/api/tasks/{cid}").status_code == 403


# --- The admin filters ----------------------------------------------------
def test_admin_can_filter_by_client_assignee_and_priority(client, db, make_user, auth):
    from app.models import Client as ClientRow
    acme = ClientRow(name="Acme")
    other = ClientRow(name="Other")
    db.add_all([acme, other])
    db.commit()
    emp = make_user(C.ROLE_EMPLOYEE)
    mate = make_user(C.ROLE_EMPLOYEE)
    hit = _mk(db, title="hit", client_id=acme.id, assigned_to_id=emp.id, priority=C.PRIORITY_URGENT)
    wrong_client = _mk(db, title="c", client_id=other.id, assigned_to_id=emp.id, priority=C.PRIORITY_URGENT)
    wrong_person = _mk(db, title="p", client_id=acme.id, assigned_to_id=mate.id, priority=C.PRIORITY_URGENT)
    wrong_prio = _mk(db, title="r", client_id=acme.id, assigned_to_id=emp.id, priority="Medium")
    auth(make_user(C.ROLE_ADMIN))
    ids = _ids(client.get(f"/api/tasks?client_id={acme.id}&assignee_id={emp.id}"
                          f"&priority={C.PRIORITY_URGENT}"))
    assert ids == {hit.id}
    assert {wrong_client.id, wrong_person.id, wrong_prio.id} & ids == set()


def test_unassigned_is_its_own_assignee_choice(client, db, make_user, auth, bridge_on):
    """"Unassigned" can't be expressed as an id, and it's what a manager triaging the board needs.
    An Atrium card reads Unassigned here, so it belongs in that answer too."""
    emp = make_user(C.ROLE_EMPLOYEE)
    taken = _mk(db, title="taken", assigned_to_id=emp.id)
    free = _mk(db, title="free")
    auth(make_user(C.ROLE_ADMIN))
    ids = _ids(client.get("/api/tasks?unassigned=1"))
    assert free.id in ids and "atrium:melo-yelo:tk_1" in ids
    assert taken.id not in ids
    # Naming a person wins over the flag (a card cannot be both), and excludes Atrium cards.
    named = _ids(client.get(f"/api/tasks?unassigned=1&assignee_id={emp.id}"))
    assert named == {taken.id}

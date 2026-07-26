"""Task visibility: employees see only their own board — assigned to them or created by them.

The creator tag (``tasks.created_by_id``) is set automatically on create — never a form field —
so a quick-added card never vanishes off its creator's board, even while unassigned or after a
manager reassigns it. Manager/AM see-everything and team-lead team scope are unchanged
(see services/task_perms.py for the full table).
"""
from __future__ import annotations

from app import constants as C
from app.models import Task


def _mk(db, **kw):
    t = Task(title=kw.pop("title", "T"), **kw)
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def _ids(resp):
    assert resp.status_code == 200
    return {t["id"] for t in resp.json()}


def test_employee_sees_only_assigned_or_created(client, db, make_user, auth):
    emp = make_user(C.ROLE_EMPLOYEE)
    other = make_user(C.ROLE_EMPLOYEE)
    mine_assigned = _mk(db, title="assigned to me", assigned_to_id=emp.id)
    mine_created = _mk(db, title="created by me", created_by_id=emp.id)  # unassigned
    theirs = _mk(db, title="someone else's", assigned_to_id=other.id)
    unowned = _mk(db, title="nobody's")
    auth(emp)
    ids = _ids(client.get("/api/tasks"))
    assert mine_assigned.id in ids
    assert mine_created.id in ids
    assert theirs.id not in ids
    assert unowned.id not in ids


def test_employee_create_is_auto_assigned_and_tagged(client, make_user, auth):
    emp = make_user(C.ROLE_EMPLOYEE)
    auth(emp)
    body = client.post("/api/tasks", json={"title": "quick add"}).json()
    assert body["assigned_to_id"] == emp.id       # auto-added to their own board
    assert body["created_by_id"] == emp.id        # tagged automatically, no form field
    assert body["created_by"]["id"] == emp.id
    assert body["id"] in _ids(client.get("/api/tasks"))


def test_creator_keeps_sight_after_reassignment(client, make_user, auth):
    emp = make_user(C.ROLE_EMPLOYEE)
    other = make_user(C.ROLE_EMPLOYEE)
    admin = make_user(C.ROLE_ADMIN)
    auth(emp)
    tid = client.post("/api/tasks", json={"title": "made by emp"}).json()["id"]
    auth(admin)
    assert client.patch(f"/api/tasks/{tid}", json={"assigned_to_id": other.id}).status_code == 200
    auth(emp)
    assert client.get(f"/api/tasks/{tid}").status_code == 200   # the creator tag keeps it visible
    assert tid in _ids(client.get("/api/tasks"))


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

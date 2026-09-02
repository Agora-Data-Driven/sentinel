"""\"Act as user\" (2026-09-02): a SUPER ADMIN browses Sentinel as another active user.

What must stay true:

* Only a super admin can start an act — and the gate reads the REAL person, so an acted-as employee
  cannot re-point the act.
* While acting, every dependency resolves to the TARGET: /me answers as them (with `acting_as.real`
  naming the true person), the board is their board, and their capabilities apply — acting is only
  ever a NARROWING.
* TIME is never written while acting (the Mastery Engine's own rule): punches, timer sessions,
  manual entries and engine edits all 403 with an explanation.
* A stale act (target deactivated) silently dissolves; logout clears it; start and stop are audited.
"""
from __future__ import annotations

import pytest

from app import constants as C
from app.config import settings
from app.models import AuditLog, Task, TaskSession


@pytest.fixture
def team(make_team):
    return make_team(name="Acquisition")


@pytest.fixture
def super_admin(make_user):
    return make_user(C.ROLE_SUPER_ADMIN, name="Lance")


@pytest.fixture
def worker(make_user, team):
    return make_user(C.ROLE_EMPLOYEE, team_id=team.id, name="Zhen")


def _act(client, uid):
    return client.post("/api/auth/act-as", json={"user_id": uid})


def test_only_a_super_admin_may_act(client, auth, worker, make_user):
    lead = make_user(C.ROLE_TEAM_LEAD, name="Ehjay")
    for u in (worker, lead):
        auth(u)
        assert _act(client, worker.id).status_code == 403


def test_acting_swaps_the_whole_current_user(client, db, auth, super_admin, worker, team):
    t = Task(title="Zhen's card", status=C.TASK_TODO, assigned_team_id=team.id, assigned_to_id=worker.id)
    other = Task(title="Someone else's card", status=C.TASK_TODO)
    db.add_all([t, other])
    db.commit()
    auth(super_admin)
    r = _act(client, worker.id)
    assert r.status_code == 200 and r.json()["acting_as"]["id"] == worker.id
    me = client.get("/api/auth/me").json()
    assert me["email"] == worker.email
    assert me["acting_as"]["real"]["id"] == super_admin.id
    # The board is the employee's board — their card and their team's queue, not the estate.
    ids = {x["id"] for x in client.get("/api/tasks").json()}
    assert t.id in ids and other.id not in ids
    # And their capabilities: an employee may not read the Monitor rollup.
    assert client.get("/api/tasks/summary").status_code == 403


def test_repointing_while_acting_switches_targets(client, auth, super_admin, worker, make_user):
    """The gate reads the REAL person (get_real_user) — deliberately. If it read the acted-as user,
    a super admin acting as an employee could neither switch targets nor STOP (the role check would
    see 'employee' and 403 the only way out). So re-pointing mid-act simply switches who you are."""
    other = make_user(C.ROLE_EMPLOYEE, name="Jerome")
    auth(super_admin)
    _act(client, worker.id)
    assert client.get("/api/auth/me").json()["email"] == worker.email
    assert _act(client, other.id).status_code == 200
    me = client.get("/api/auth/me").json()
    assert me["email"] == other.email
    assert me["acting_as"]["real"]["id"] == super_admin.id


def test_time_is_never_written_while_acting(client, db, auth, super_admin, worker, team):
    t = Task(title="Zhen's card", status=C.TASK_TODO, assigned_team_id=team.id, assigned_to_id=worker.id)
    db.add(t)
    db.commit()
    auth(super_admin)
    _act(client, worker.id)
    assert client.post(f"/api/tasks/{t.id}/sessions/start").status_code == 403
    assert client.post("/api/tasks/sessions/pause").status_code == 403
    assert client.post("/api/attendance/self-event", json={"action": "clock_in"}).status_code == 403
    assert client.post("/api/development/time/entries",
                       json={"date": "2026-09-01", "start": "08:00", "minutes": 30,
                             "dimension": "professional"}).status_code == 403
    assert db.query(TaskSession).count() == 0
    # Everything ELSE works as the target — acting exists to fix their board.
    assert client.post(f"/api/tasks/{t.id}/park", json={"reason": "x", "kind": "client"}).status_code == 200


def test_stop_and_logout_both_end_the_act(client, auth, super_admin, worker):
    auth(super_admin)
    _act(client, worker.id)
    assert client.get("/api/auth/me").json()["email"] == worker.email
    r = client.post("/api/auth/act-as", json={"user_id": None})
    assert r.status_code == 200 and r.json()["acting_as"] is None
    assert client.get("/api/auth/me").json()["email"] == super_admin.email
    # Logout clears the cookie too, so a fresh sign-in can never wake up acting.
    _act(client, worker.id)
    client.post("/api/auth/logout")
    assert settings.act_as_cookie_name not in {c.name for c in client.cookies.jar if c.value}


def test_a_deactivated_target_dissolves_the_act(client, db, auth, super_admin, worker):
    auth(super_admin)
    _act(client, worker.id)
    worker.is_active = False
    db.commit()
    assert client.get("/api/auth/me").json()["email"] == super_admin.email


def test_acting_refuses_unknown_and_inactive_targets(client, db, auth, super_admin, make_user):
    auth(super_admin)
    assert _act(client, 99999).status_code == 404
    gone = make_user(C.ROLE_EMPLOYEE, active=False, name="Left")
    assert _act(client, gone.id).status_code == 400


def test_start_and_stop_are_audited_to_the_real_person(client, db, auth, super_admin, worker):
    auth(super_admin)
    _act(client, worker.id)
    client.post("/api/auth/act-as", json={"user_id": None})
    rows = db.query(AuditLog).filter(AuditLog.action.in_(("act_as_start", "act_as_stop"))).all()
    assert {r.action for r in rows} == {"act_as_start", "act_as_stop"}
    assert all(r.actor_id == super_admin.id for r in rows)
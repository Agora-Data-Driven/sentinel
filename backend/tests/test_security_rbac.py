"""RBAC is enforced server-side, not just in the UI. These tests assert real 401/403s per role.

The endpoints here use dependency guards that run before the handler, so they reject on role alone
without any seeded data — exactly the property we want to protect against regressions.
"""
from __future__ import annotations

import pytest

from app import constants as C

ALL = [C.ROLE_INTERN, C.ROLE_EMPLOYEE, C.ROLE_TEAM_LEAD, C.ROLE_ACCOUNT_MANAGER, C.ROLE_ADMIN, C.ROLE_SUPER_ADMIN]


def test_unauthenticated_is_401(client):
    assert client.get("/api/auth/me").status_code == 401
    # A protected resource with no cookie is rejected too.
    assert client.get("/api/admin/settings").status_code == 401


def test_me_returns_current_user(client, make_user, auth):
    auth(make_user(C.ROLE_EMPLOYEE, name="Ana Reyes"))
    r = client.get("/api/auth/me")
    assert r.status_code == 200
    assert r.json()["name"] == "Ana Reyes"


@pytest.mark.parametrize("role", [C.ROLE_INTERN, C.ROLE_EMPLOYEE, C.ROLE_TEAM_LEAD, C.ROLE_ACCOUNT_MANAGER])
def test_admin_settings_forbidden_below_admin(client, make_user, auth, role):
    auth(make_user(role))
    assert client.get("/api/admin/settings").status_code == 403


@pytest.mark.parametrize("role", [C.ROLE_ADMIN, C.ROLE_SUPER_ADMIN])
def test_admin_settings_allowed_for_admins(client, make_user, auth, role):
    auth(make_user(role))
    assert client.get("/api/admin/settings").status_code == 200


@pytest.mark.parametrize("role", [C.ROLE_INTERN, C.ROLE_EMPLOYEE])
def test_attendance_summary_forbidden_below_team_lead(client, make_user, auth, role):
    auth(make_user(role))
    assert client.get("/api/attendance/summary").status_code == 403


@pytest.mark.parametrize("role", [C.ROLE_TEAM_LEAD, C.ROLE_ADMIN, C.ROLE_SUPER_ADMIN])
def test_attendance_summary_allowed_for_team_lead_and_up(client, make_user, auth, role):
    auth(make_user(role))
    assert client.get("/api/attendance/summary").status_code == 200


# --- Priority is a management decision: team lead (own team) + AM/admin/super. Staff cannot. ------
def _a_task(db):
    from app.models import Task
    t = Task(title="P")
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


@pytest.mark.parametrize("role", [C.ROLE_INTERN, C.ROLE_EMPLOYEE])
def test_priority_change_forbidden_for_staff(client, db, make_user, auth, role):
    t = _a_task(db)
    auth(make_user(role))
    assert client.patch(f"/api/tasks/{t.id}/priority", json={"priority": C.PRIORITY_URGENT}).status_code == 403


@pytest.mark.parametrize("role", [C.ROLE_ACCOUNT_MANAGER, C.ROLE_ADMIN, C.ROLE_SUPER_ADMIN])
def test_priority_change_allowed_for_managers(client, db, make_user, auth, role):
    t = _a_task(db)
    auth(make_user(role))
    assert client.patch(f"/api/tasks/{t.id}/priority", json={"priority": C.PRIORITY_URGENT}).status_code == 200


def test_inactive_user_cannot_authenticate(client, make_user, auth):
    auth(make_user(C.ROLE_ADMIN, active=False))
    assert client.get("/api/auth/me").status_code == 401

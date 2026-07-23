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


# --- The headline rule: only the Account Manager may change task priority --
@pytest.mark.parametrize("role", [C.ROLE_INTERN, C.ROLE_EMPLOYEE, C.ROLE_TEAM_LEAD, C.ROLE_ADMIN, C.ROLE_SUPER_ADMIN])
def test_priority_change_forbidden_for_non_account_manager(client, make_user, auth, role):
    auth(make_user(role))
    r = client.patch("/api/tasks/1/priority", json={"priority": C.PRIORITY_URGENT})
    assert r.status_code == 403, f"{role} must not set priority"


def test_priority_change_passes_role_gate_for_account_manager(client, make_user, auth):
    # AM clears the role gate; the task doesn't exist, so we expect 404 (not 403).
    auth(make_user(C.ROLE_ACCOUNT_MANAGER))
    r = client.patch("/api/tasks/1/priority", json={"priority": C.PRIORITY_URGENT})
    assert r.status_code == 404


def test_inactive_user_cannot_authenticate(client, make_user, auth):
    auth(make_user(C.ROLE_ADMIN, active=False))
    assert client.get("/api/auth/me").status_code == 401

"""Per-PERSON capability exceptions, the reports capabilities, and the two UI/API mismatches closed.

The per-person layer is the one that most invites a hole: it is a permission grant that bypasses the
role, so most of this file is about proving it does NOT bypass the invariants.
"""
from __future__ import annotations

import pytest

from app import constants as C
from app.models import RoleCapability, UserCapability
from app.services import permissions as perms_svc


# --------------------------------------------------------------------------------------
# 1. The layering: role defaults -> role overrides -> person.
# --------------------------------------------------------------------------------------
def test_a_person_override_grants_beyond_their_role(client, db, auth, make_user):
    emp = make_user(C.ROLE_EMPLOYEE)
    auth(emp)
    assert client.get("/api/reports/attendance").status_code == 403

    db.add(UserCapability(user_id=emp.id, capability="reports.attendance", allowed=True))
    db.commit()
    perms_svc.invalidate()

    assert client.get("/api/reports/attendance").status_code == 200
    assert "reports.attendance" in client.get("/api/auth/me").json()["caps"]


def test_a_person_override_revokes_within_their_role(client, db, auth, make_user):
    admin = make_user(C.ROLE_ADMIN)
    auth(admin)
    assert client.get("/api/admin/settings").status_code == 200
    db.add(UserCapability(user_id=admin.id, capability="settings.view", allowed=False))
    db.commit()
    perms_svc.invalidate()
    assert client.get("/api/admin/settings").status_code == 403


def test_the_person_layer_wins_over_the_role_layer(db, make_user):
    """Role says no via an override, the person says yes: the person is applied last."""
    emp = make_user(C.ROLE_EMPLOYEE)
    db.add(RoleCapability(role=C.ROLE_EMPLOYEE, capability="reports.gym", allowed=False))
    db.add(UserCapability(user_id=emp.id, capability="reports.gym", allowed=True))
    db.commit()
    perms_svc.invalidate()
    assert perms_svc.has_cap(emp, "reports.gym") is True


def test_an_override_only_affects_that_person(db, make_user):
    a = make_user(C.ROLE_EMPLOYEE, email="a@t.ph")
    b = make_user(C.ROLE_EMPLOYEE, email="b@t.ph")
    db.add(UserCapability(user_id=a.id, capability="payroll.manage", allowed=True))
    db.commit()
    perms_svc.invalidate()
    assert perms_svc.has_cap(a, "payroll.manage") is True
    assert perms_svc.has_cap(b, "payroll.manage") is False


# --------------------------------------------------------------------------------------
# 2. The invariants survive the person layer. This is the part that matters.
# --------------------------------------------------------------------------------------
def test_a_person_override_cannot_give_a_viewer_a_write(db, make_user):
    v = make_user(C.ROLE_VIEWER)
    db.add(UserCapability(user_id=v.id, capability="payroll.manage", allowed=True))
    db.add(UserCapability(user_id=v.id, capability="tasks.review", allowed=True))
    db.commit()
    perms_svc.invalidate()
    assert perms_svc.has_cap(v, "payroll.manage") is False
    assert perms_svc.has_cap(v, "tasks.review") is False


def test_a_person_override_can_give_a_viewer_a_READ(db, make_user):
    v = make_user(C.ROLE_VIEWER)
    db.add(UserCapability(user_id=v.id, capability="reports.attendance", allowed=True))
    db.commit()
    perms_svc.invalidate()
    assert perms_svc.has_cap(v, "reports.attendance") is True


def test_a_person_override_cannot_touch_a_locked_capability(db, make_user):
    emp = make_user(C.ROLE_EMPLOYEE)
    db.add(UserCapability(user_id=emp.id, capability="people.set_role", allowed=True))
    db.add(UserCapability(user_id=emp.id, capability="permissions.manage", allowed=True))
    db.commit()
    perms_svc.invalidate()
    assert perms_svc.has_cap(emp, "people.set_role") is False
    assert perms_svc.has_cap(emp, "permissions.manage") is False


def test_a_person_override_cannot_strip_a_super_admin(db, make_user):
    sa = make_user(C.ROLE_SUPER_ADMIN)
    db.add(UserCapability(user_id=sa.id, capability="permissions.manage", allowed=False))
    db.add(UserCapability(user_id=sa.id, capability="payroll.manage", allowed=False))
    db.commit()
    perms_svc.invalidate()
    assert perms_svc.has_cap(sa, "permissions.manage") is True
    assert perms_svc.has_cap(sa, "payroll.manage") is True


def test_an_override_goes_inert_when_the_role_changes_and_is_still_visible(client, db, auth, make_user):
    """A grant follows the person, not the seat — but demoting them to viewer must neutralise a
    write, and the console must still SHOW the row so somebody can remove it."""
    emp = make_user(C.ROLE_EMPLOYEE)
    db.add(UserCapability(user_id=emp.id, capability="payroll.manage", allowed=True))
    db.commit()
    perms_svc.invalidate()
    assert perms_svc.has_cap(emp, "payroll.manage") is True

    emp.role = C.ROLE_VIEWER
    db.commit()
    perms_svc.invalidate()
    assert perms_svc.has_cap(emp, "payroll.manage") is False

    auth(make_user(C.ROLE_SUPER_ADMIN))
    people = client.get("/api/permissions/people").json()["people"]
    row = next(p for p in people if p["user_id"] == emp.id)
    assert row["caps"][0]["inert"] is True
    assert row["caps"][0]["reason"]


# --------------------------------------------------------------------------------------
# 3. The console API for people.
# --------------------------------------------------------------------------------------
def test_person_endpoints_need_the_console_capabilities(client, auth, make_user):
    target = make_user(C.ROLE_EMPLOYEE)
    auth(make_user(C.ROLE_ADMIN))
    assert client.get("/api/permissions/people").status_code == 403
    assert client.put(f"/api/permissions/people/{target.id}",
                      json={"changes": []}).status_code == 403
    auth(make_user(C.ROLE_SUPER_ADMIN))
    assert client.get("/api/permissions/people").status_code == 200


def test_put_person_matrix_round_trip(client, db, auth, make_user):
    target = make_user(C.ROLE_EMPLOYEE)
    auth(make_user(C.ROLE_SUPER_ADMIN))
    body = client.put(f"/api/permissions/people/{target.id}", json={
        "changes": [{"capability": "reports.attendance", "allowed": True}]}).json()
    assert body["refused"] == []
    assert body["matrix"]["override_count"] == 1
    cap = next(c for c in body["matrix"]["capabilities"] if c["key"] == "reports.attendance")
    assert cap["allowed"] is True and cap["from_role"] is False and cap["override"] is True


def test_setting_a_person_back_to_their_role_deletes_the_row(client, db, auth, make_user):
    target = make_user(C.ROLE_EMPLOYEE)
    auth(make_user(C.ROLE_SUPER_ADMIN))
    url = f"/api/permissions/people/{target.id}"
    client.put(url, json={"changes": [{"capability": "reports.attendance", "allowed": True}]})
    assert db.query(UserCapability).count() == 1
    client.put(url, json={"changes": [{"capability": "reports.attendance", "allowed": False}]})
    assert db.query(UserCapability).count() == 0


def test_person_reset_clears_only_that_person(client, db, auth, make_user):
    a = make_user(C.ROLE_EMPLOYEE, email="pa@t.ph")
    b = make_user(C.ROLE_EMPLOYEE, email="pb@t.ph")
    auth(make_user(C.ROLE_SUPER_ADMIN))
    for u in (a, b):
        client.put(f"/api/permissions/people/{u.id}",
                   json={"changes": [{"capability": "reports.gym", "allowed": True}]})
    assert db.query(UserCapability).count() == 2
    assert client.post(f"/api/permissions/people/{a.id}/reset").json()["cleared"] == 1
    assert db.query(UserCapability).count() == 1


def test_refusals_are_reported_for_a_person_too(client, auth, make_user):
    v = make_user(C.ROLE_VIEWER)
    auth(make_user(C.ROLE_SUPER_ADMIN))
    body = client.put(f"/api/permissions/people/{v.id}", json={"changes": [
        {"capability": "payroll.manage", "allowed": True},
        {"capability": "people.set_role", "allowed": True},
    ]}).json()
    assert body["applied"] == []
    assert len(body["refused"]) == 2
    assert all(r["reason"] for r in body["refused"])


def test_deleting_a_person_prunes_their_overrides(client, db, auth, make_user):
    target = make_user(C.ROLE_EMPLOYEE)
    auth(make_user(C.ROLE_SUPER_ADMIN))
    client.put(f"/api/permissions/people/{target.id}",
               json={"changes": [{"capability": "reports.gym", "allowed": True}]})
    assert db.query(UserCapability).count() == 1
    assert client.delete(f"/api/people/{target.id}").status_code == 200
    assert db.query(UserCapability).count() == 0


# --------------------------------------------------------------------------------------
# 4. The audit feed.
# --------------------------------------------------------------------------------------
def test_audit_feed_shows_role_and_person_changes(client, auth, make_user):
    target = make_user(C.ROLE_EMPLOYEE)
    auth(make_user(C.ROLE_SUPER_ADMIN))
    client.put("/api/permissions", json={
        "changes": [{"role": C.ROLE_ADMIN, "capability": "payroll.manage", "allowed": True}]})
    client.put(f"/api/permissions/people/{target.id}",
               json={"changes": [{"capability": "reports.gym", "allowed": True}]})
    changes = client.get("/api/permissions/audit").json()["changes"]
    scopes = {c["scope"] for c in changes}
    assert scopes == {"role", "person"}
    assert all(c["actor"] for c in changes)


def test_audit_feed_is_readable_with_view_only(client, db, auth, make_user):
    admin = make_user(C.ROLE_ADMIN)
    db.add(RoleCapability(role=C.ROLE_ADMIN, capability="permissions.view", allowed=True))
    db.commit()
    perms_svc.invalidate()
    auth(admin)
    assert client.get("/api/permissions/audit").status_code == 200


# --------------------------------------------------------------------------------------
# 5. Reports: one capability per report, and an unknown report is CLOSED.
# --------------------------------------------------------------------------------------
_REPORT_DEFAULTS = {
    "attendance": {C.ROLE_ADMIN, C.ROLE_SUPER_ADMIN},
    "gym": {C.ROLE_ADMIN, C.ROLE_SUPER_ADMIN},
    "leave": {C.ROLE_ADMIN, C.ROLE_SUPER_ADMIN},
    "team": {C.ROLE_ADMIN, C.ROLE_SUPER_ADMIN, C.ROLE_ACCOUNT_MANAGER},
    "overdue": {C.ROLE_ADMIN, C.ROLE_SUPER_ADMIN, C.ROLE_TEAM_LEAD},
    "tasks": set(C.ALL_ROLES),
}


@pytest.mark.parametrize("report,allowed", sorted(_REPORT_DEFAULTS.items()))
def test_report_access_is_unchanged_for_every_role(report, allowed, client, auth, make_user):
    for role in C.ALL_ROLES:
        auth(make_user(role, email=f"{role}-{report}@t.ph"))
        got = client.get(f"/api/reports/{report}").status_code
        want_ok = role in allowed
        assert (got != 403) == want_ok, f"{role} on {report}: got {got}"


def test_an_unknown_report_is_404_not_an_empty_report(client, auth, make_user):
    """It used to fall through the access check and return nothing, so a report added later with no
    rule would have been world-readable. The default is closed now."""
    auth(make_user(C.ROLE_SUPER_ADMIN))
    assert client.get("/api/reports/salaries").status_code == 404


def test_a_report_can_be_granted_to_an_employee(client, db, auth, make_user):
    emp = make_user(C.ROLE_EMPLOYEE)
    auth(emp)
    assert client.get("/api/reports/gym").status_code == 403
    db.add(RoleCapability(role=C.ROLE_EMPLOYEE, capability="reports.gym", allowed=True))
    db.commit()
    perms_svc.invalidate()
    assert client.get("/api/reports/gym").status_code == 200


# --------------------------------------------------------------------------------------
# 6. The two UI/API mismatches that are now closed.
# --------------------------------------------------------------------------------------
def test_dashboard_is_admin_follows_insights_view(client, db, auth, make_user):
    """Granting `insights.view` used to open the API while the Overview block stayed hidden."""
    lead = make_user(C.ROLE_TEAM_LEAD)
    auth(lead)
    assert client.get("/api/dashboard").json()["is_admin"] is False
    db.add(RoleCapability(role=C.ROLE_TEAM_LEAD, capability="insights.view", allowed=True))
    db.commit()
    perms_svc.invalidate()
    assert client.get("/api/dashboard").json()["is_admin"] is True
    assert client.get("/api/insights").status_code == 200


def test_dashboard_is_admin_is_true_for_an_admin_by_default(client, auth, make_user):
    auth(make_user(C.ROLE_ADMIN))
    assert client.get("/api/dashboard").json()["is_admin"] is True


@pytest.fixture
def kiosk_key(monkeypatch):
    """`kiosk_guard` is deliberately OPEN in non-production when no KIOSK_KEY is set (zero-setup
    local scanning), so the session path is only observable once a key exists."""
    from app.config import settings
    monkeypatch.setattr(settings, "kiosk_key", "test-kiosk-key")
    return "test-kiosk-key"


def test_the_kiosk_can_be_granted_without_super_admin(client, db, auth, make_user, kiosk_key):
    lead = make_user(C.ROLE_TEAM_LEAD)
    auth(lead)
    assert client.post("/api/attendance/scan", json={"token": "nope"}).status_code == 401

    db.add(RoleCapability(role=C.ROLE_TEAM_LEAD, capability="attendance.kiosk", allowed=True))
    db.commit()
    perms_svc.invalidate()

    # Past the guard now: the failure is the unknown badge, not the permission.
    assert client.post("/api/attendance/scan", json={"token": "nope"}).status_code == 404


def test_a_super_admin_still_runs_the_kiosk(client, auth, make_user, kiosk_key):
    auth(make_user(C.ROLE_SUPER_ADMIN))
    assert client.post("/api/attendance/scan", json={"token": "nope"}).status_code == 404

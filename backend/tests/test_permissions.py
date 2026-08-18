"""The capability layer, the Permissions console, and the privilege-escalation hole it closed.

Weighted toward the REFUSALS and toward proving the migration was behaviour-preserving, because
those are the two ways this feature can go wrong: it can open something that used to be shut, or it
can let the console open something that must never be opened.
"""
from __future__ import annotations

import pytest

from app import capabilities as caps
from app import constants as C
from app.models import RoleCapability
from app.services import permissions as perms_svc


# --------------------------------------------------------------------------------------
# 1. The defaults are a faithful translation of the guards they replaced.
# --------------------------------------------------------------------------------------
# Each entry is (capability, the ORIGINAL gate). `min:<role>` == the old
# `require_min_role(<role>)`; a tuple == the old `require_roles(*tuple)`. Re-derived from
# ROLE_RANK here rather than copied, so a typo in `capabilities.py` fails this test instead of
# silently opening or closing an endpoint.
_ORIGINAL_GATES = [
    ("people.edit", "min:admin"),
    ("people.badge", "min:admin"),
    ("people.create", (C.ROLE_SUPER_ADMIN,)),
    ("people.delete", (C.ROLE_SUPER_ADMIN,)),
    ("payroll.manage", (C.ROLE_SUPER_ADMIN,)),
    ("attendance.approvals", "min:team_lead"),
    ("attendance.records", "min:team_lead"),
    ("attendance.edit_records", (C.ROLE_SUPER_ADMIN,)),
    ("leave.approvals", "min:team_lead"),
    ("tasks.recurring", (C.ROLE_ACCOUNT_MANAGER, C.ROLE_ADMIN, C.ROLE_SUPER_ADMIN)),
    ("tasks.requests", (C.ROLE_ACCOUNT_MANAGER, C.ROLE_ADMIN, C.ROLE_SUPER_ADMIN)),
    ("tasks.atrium_share", (C.ROLE_ACCOUNT_MANAGER, C.ROLE_ADMIN, C.ROLE_SUPER_ADMIN)),
    ("tasks.adoption", (C.ROLE_SUPER_ADMIN,)),
    ("growth.team", "min:admin"),
    ("reading.canon", "min:admin"),
    ("gym.rollup", "min:team_lead"),
    ("gym.edit_logs", (C.ROLE_SUPER_ADMIN,)),
    ("settings.view", "min:admin"),
    ("settings.edit", "min:admin"),
    ("audit.view", "min:admin"),
    ("announce.send", "min:admin"),
    ("insights.view", "min:admin"),
    ("manage.console", (C.ROLE_SUPER_ADMIN,)),
    ("system.run_daily", (C.ROLE_SUPER_ADMIN,)),
]


def _roles_passing(gate) -> set[str]:
    if isinstance(gate, tuple):
        return set(gate)
    minimum = gate.split(":", 1)[1]
    floor = C.ROLE_RANK[minimum]
    return {r for r in C.ALL_ROLES if C.ROLE_RANK.get(r, 0) >= floor}


@pytest.mark.parametrize("cap_key,gate", _ORIGINAL_GATES, ids=[c for c, _ in _ORIGINAL_GATES])
def test_default_matches_the_guard_it_replaced(cap_key, gate):
    cap = caps.BY_KEY[cap_key]
    assert set(cap.default) == _roles_passing(gate), (
        f"{cap_key}'s default no longer matches the original gate — this endpoint's access changed"
    )


def test_every_capability_is_reachable_and_uniquely_keyed():
    keys = [c.key for c in caps.CAPABILITIES]
    assert len(keys) == len(set(keys))
    assert caps.ALL_CAP_KEYS == set(keys)


def test_every_cap_constant_names_a_real_capability():
    """A `CAP_*` constant that no longer matches a registry key would silently CLOSE its endpoint
    (`has_cap` answers False for an unknown key), so it must fail here instead."""
    for name in dir(caps):
        if name.startswith("CAP_"):
            assert getattr(caps, name) in caps.ALL_CAP_KEYS, name


# --------------------------------------------------------------------------------------
# 2. The three invariants — enforced at write time AND at resolution time.
# --------------------------------------------------------------------------------------
def test_super_admin_holds_every_capability():
    assert caps.default_caps(C.ROLE_SUPER_ADMIN) == caps.ALL_CAP_KEYS
    assert caps.effective_caps(C.ROLE_SUPER_ADMIN) == caps.ALL_CAP_KEYS


def test_a_revoke_stored_against_super_admin_is_inert():
    """Defence in depth: a hand-run INSERT must not be able to lock the last Super Admin out."""
    got = caps.effective_caps(C.ROLE_SUPER_ADMIN, {"permissions.manage": False, "manage.console": False})
    assert got == caps.ALL_CAP_KEYS


def test_super_admin_cells_are_not_editable():
    for cap in caps.CAPABILITIES:
        ok, reason = caps.is_grantable(C.ROLE_SUPER_ADMIN, cap.key)
        assert ok is False and reason


@pytest.mark.parametrize("cap", [c for c in caps.CAPABILITIES if c.write], ids=lambda c: c.key)
def test_viewer_can_never_be_granted_a_write(cap):
    ok, reason = caps.is_grantable(C.ROLE_VIEWER, cap.key)
    assert ok is False
    assert reason
    # A LOCKED write is refused by the lock first, so only an unlocked one proves the viewer rule
    # itself is what bites. Both are refusals; the distinction is only about which sentence shows.
    if not cap.locked:
        assert "read-only" in reason
    # And the refusal holds even when a row exists anyway.
    assert cap.key not in caps.effective_caps(C.ROLE_VIEWER, {cap.key: True})


@pytest.mark.parametrize("cap", [c for c in caps.CAPABILITIES if not c.write], ids=lambda c: c.key)
def test_viewer_CAN_be_granted_a_read(cap):
    """That is the seat's entire purpose — it sees everything and writes nothing (decision D8)."""
    ok, _ = caps.is_grantable(C.ROLE_VIEWER, cap.key)
    assert ok is True
    assert cap.key in caps.effective_caps(C.ROLE_VIEWER, {cap.key: True})


@pytest.mark.parametrize("cap", [c for c in caps.CAPABILITIES if c.locked], ids=lambda c: c.key)
def test_a_locked_capability_is_never_editable_for_any_role(cap):
    for role in C.ALL_ROLES:
        ok, reason = caps.is_grantable(role, cap.key)
        assert ok is False and reason
        # And an override row against it changes nothing.
        assert (cap.key in caps.effective_caps(role, {cap.key: True})) == (role in cap.default or role == C.ROLE_SUPER_ADMIN)


def test_the_console_capability_is_locked():
    """If this ever became grantable, a Super Admin could hand away the power to grant everything."""
    assert caps.BY_KEY["permissions.manage"].locked is True


def test_role_setting_is_locked():
    assert caps.BY_KEY["people.set_role"].locked is True


def test_unknown_capability_and_role_are_refused():
    assert caps.is_grantable(C.ROLE_ADMIN, "nope.nope")[0] is False
    assert caps.is_grantable("wizard", "settings.view")[0] is False


# --------------------------------------------------------------------------------------
# 3. Overrides actually move a real endpoint.
# --------------------------------------------------------------------------------------
def test_granting_a_capability_opens_a_real_endpoint(client, db, auth, make_user):
    admin = make_user(C.ROLE_ADMIN)
    auth(admin)
    # ?period= is required by the route itself — without it the answer is 422 whatever the
    # permission says, which would make this test pass for the wrong reason.
    url = "/api/payroll?period=2026-08"
    assert client.get(url).status_code == 403

    db.add(RoleCapability(role=C.ROLE_ADMIN, capability="payroll.manage", allowed=True))
    db.commit()
    perms_svc.invalidate()

    assert client.get(url).status_code == 200


def test_revoking_a_capability_closes_a_real_endpoint(client, db, auth, make_user):
    admin = make_user(C.ROLE_ADMIN)
    auth(admin)
    assert client.get("/api/admin/settings").status_code == 200

    db.add(RoleCapability(role=C.ROLE_ADMIN, capability="settings.view", allowed=False))
    db.commit()
    perms_svc.invalidate()

    assert client.get("/api/admin/settings").status_code == 403


def test_an_unknown_capability_key_closes_rather_than_opens(db, make_user):
    sa = make_user(C.ROLE_SUPER_ADMIN)
    assert perms_svc.has_cap(db, sa, "typo.not.a.capability") is False


def test_an_inactive_user_holds_nothing(db, make_user):
    sa = make_user(C.ROLE_SUPER_ADMIN, active=False)
    assert perms_svc.has_cap(db, sa, "settings.view") is False


# --------------------------------------------------------------------------------------
# 4. The console API.
# --------------------------------------------------------------------------------------
def test_matrix_is_super_admin_only_by_default(client, auth, make_user):
    auth(make_user(C.ROLE_ADMIN))
    assert client.get("/api/permissions").status_code == 403
    auth(make_user(C.ROLE_SUPER_ADMIN))
    assert client.get("/api/permissions").status_code == 200


def test_matrix_shape(client, auth, make_user):
    auth(make_user(C.ROLE_SUPER_ADMIN))
    m = client.get("/api/permissions").json()
    assert len(m["capabilities"]) == len(caps.CAPABILITIES)
    assert [r["value"] for r in m["roles"]] == list(C.ALL_ROLES)
    assert m["override_count"] == 0
    row = next(c for c in m["capabilities"] if c["key"] == "payroll.manage")
    assert row["roles"][C.ROLE_ADMIN] == {
        "allowed": False, "default": False, "editable": True, "reason": None,
    }
    # A disabled cell always carries the sentence the UI shows in its place.
    locked = next(c for c in m["capabilities"] if c["key"] == "people.set_role")
    assert locked["roles"][C.ROLE_ADMIN]["editable"] is False
    assert locked["roles"][C.ROLE_ADMIN]["reason"]


def test_put_grants_and_reports_the_fresh_matrix(client, auth, make_user):
    auth(make_user(C.ROLE_SUPER_ADMIN))
    res = client.put("/api/permissions", json={
        "changes": [{"role": C.ROLE_ADMIN, "capability": "payroll.manage", "allowed": True}],
    })
    assert res.status_code == 200
    body = res.json()
    assert body["refused"] == []
    assert body["applied"][0]["changed"] is True
    assert body["matrix"]["override_count"] == 1
    row = next(c for c in body["matrix"]["capabilities"] if c["key"] == "payroll.manage")
    assert row["roles"][C.ROLE_ADMIN]["allowed"] is True


def test_a_refused_change_is_reported_not_silently_dropped(client, auth, make_user):
    auth(make_user(C.ROLE_SUPER_ADMIN))
    body = client.put("/api/permissions", json={"changes": [
        {"role": C.ROLE_VIEWER, "capability": "payroll.manage", "allowed": True},
        {"role": C.ROLE_ADMIN, "capability": "people.set_role", "allowed": True},
        {"role": C.ROLE_SUPER_ADMIN, "capability": "manage.console", "allowed": False},
    ]}).json()
    assert body["applied"] == []
    assert len(body["refused"]) == 3
    assert all(r["reason"] for r in body["refused"])
    assert body["matrix"]["override_count"] == 0


def test_restoring_the_default_deletes_the_row(client, db, auth, make_user):
    auth(make_user(C.ROLE_SUPER_ADMIN))
    client.put("/api/permissions", json={
        "changes": [{"role": C.ROLE_ADMIN, "capability": "payroll.manage", "allowed": True}]})
    assert db.query(RoleCapability).count() == 1
    client.put("/api/permissions", json={
        "changes": [{"role": C.ROLE_ADMIN, "capability": "payroll.manage", "allowed": False}]})
    # Back to the coded default, so the DELTA is gone rather than stored as allowed=False.
    assert db.query(RoleCapability).count() == 0


def test_reset_clears_every_override(client, db, auth, make_user):
    auth(make_user(C.ROLE_SUPER_ADMIN))
    client.put("/api/permissions", json={"changes": [
        {"role": C.ROLE_ADMIN, "capability": "payroll.manage", "allowed": True},
        {"role": C.ROLE_TEAM_LEAD, "capability": "settings.view", "allowed": True},
    ]})
    assert db.query(RoleCapability).count() == 2
    body = client.post("/api/permissions/reset").json()
    assert body["cleared"] == 2
    assert body["matrix"]["override_count"] == 0
    assert db.query(RoleCapability).count() == 0


def test_a_change_is_audit_logged(client, auth, make_user):
    auth(make_user(C.ROLE_SUPER_ADMIN))
    client.put("/api/permissions", json={
        "changes": [{"role": C.ROLE_ADMIN, "capability": "payroll.manage", "allowed": True}]})
    logs = client.get("/api/audit-logs?table=role_capabilities").json()
    assert len(logs) == 1
    assert logs[0]["record_id"] == "admin:payroll.manage"
    assert logs[0]["new"]["allowed"] is True


def test_view_without_manage_cannot_write(client, db, auth, make_user):
    """`permissions.view` is grantable; `permissions.manage` is locked. The read must not imply the write."""
    admin = make_user(C.ROLE_ADMIN)
    db.add(RoleCapability(role=C.ROLE_ADMIN, capability="permissions.view", allowed=True))
    db.commit()
    perms_svc.invalidate()
    auth(admin)
    assert client.get("/api/permissions").status_code == 200
    assert client.put("/api/permissions", json={"changes": []}).status_code == 403
    assert client.post("/api/permissions/reset").status_code == 403


# --------------------------------------------------------------------------------------
# 5. The privilege-escalation hole PATCH /api/people/{id} used to be.
# --------------------------------------------------------------------------------------
def test_an_admin_cannot_promote_themselves_to_super_admin(client, auth, make_user):
    """🔴 THE BUG. `require_min_role("admin")` + a generic setattr loop meant `role` was writable
    exactly like `phone`, so any Admin could take payroll, Manage and the delete button."""
    admin = make_user(C.ROLE_ADMIN)
    auth(admin)
    res = client.patch(f"/api/people/{admin.id}", json={"role": C.ROLE_SUPER_ADMIN})
    assert res.status_code == 403
    assert "Super Admin" in res.json()["detail"]
    assert client.get("/api/auth/me").json()["role"] == C.ROLE_ADMIN


def test_an_admin_cannot_promote_anybody_else_either(client, auth, make_user):
    auth(make_user(C.ROLE_ADMIN))
    victim = make_user(C.ROLE_EMPLOYEE)
    assert client.patch(f"/api/people/{victim.id}",
                        json={"role": C.ROLE_SUPER_ADMIN}).status_code == 403


def test_an_admin_may_still_edit_every_other_field(client, auth, make_user):
    """The fix must not cost an Admin the ability to do their job — People edits still work, and the
    Manage form submits `role` unchanged on every save, which must not 403."""
    auth(make_user(C.ROLE_ADMIN))
    target = make_user(C.ROLE_EMPLOYEE)
    res = client.patch(f"/api/people/{target.id}",
                       json={"phone": "0917", "role": C.ROLE_EMPLOYEE})
    assert res.status_code == 200
    assert res.json()["phone"] == "0917"


def test_a_super_admin_can_still_change_a_role(client, auth, make_user):
    auth(make_user(C.ROLE_SUPER_ADMIN))
    target = make_user(C.ROLE_EMPLOYEE)
    res = client.patch(f"/api/people/{target.id}", json={"role": C.ROLE_TEAM_LEAD})
    assert res.status_code == 200
    assert res.json()["role"] == C.ROLE_TEAM_LEAD


def test_the_role_write_guard_cannot_be_granted_away(client, db, auth, make_user):
    """`people.set_role` is locked, so even an override row cannot open the escalation path."""
    admin = make_user(C.ROLE_ADMIN)
    db.add(RoleCapability(role=C.ROLE_ADMIN, capability="people.set_role", allowed=True))
    db.commit()
    perms_svc.invalidate()
    auth(admin)
    assert client.patch(f"/api/people/{admin.id}",
                        json={"role": C.ROLE_SUPER_ADMIN}).status_code == 403


# --------------------------------------------------------------------------------------
# 6. The last Super Admin cannot be removed.
# --------------------------------------------------------------------------------------
def test_the_only_super_admin_cannot_be_demoted(client, auth, make_user):
    sa = make_user(C.ROLE_SUPER_ADMIN)
    auth(sa)
    res = client.patch(f"/api/people/{sa.id}", json={"role": C.ROLE_ADMIN})
    assert res.status_code == 409
    assert "only active Super Admin" in res.json()["detail"]


def test_the_only_super_admin_cannot_be_deactivated(client, auth, make_user):
    sa = make_user(C.ROLE_SUPER_ADMIN)
    auth(sa)
    assert client.patch(f"/api/people/{sa.id}", json={"is_active": False}).status_code == 409


def test_a_super_admin_can_be_demoted_once_another_exists(client, auth, make_user):
    first = make_user(C.ROLE_SUPER_ADMIN)
    second = make_user(C.ROLE_SUPER_ADMIN)
    auth(second)
    res = client.patch(f"/api/people/{first.id}", json={"role": C.ROLE_ADMIN})
    assert res.status_code == 200
    assert res.json()["role"] == C.ROLE_ADMIN


def test_an_inactive_super_admin_does_not_count_as_cover(client, auth, make_user):
    """Two SA rows but only one usable one — demoting the active one still locks everybody out."""
    make_user(C.ROLE_SUPER_ADMIN, active=False)
    live = make_user(C.ROLE_SUPER_ADMIN)
    auth(live)
    assert client.patch(f"/api/people/{live.id}", json={"role": C.ROLE_ADMIN}).status_code == 409


# --------------------------------------------------------------------------------------
# 7. /api/auth/me ships capabilities for the frontend to gate on.
# --------------------------------------------------------------------------------------
def test_me_ships_caps(client, auth, make_user):
    auth(make_user(C.ROLE_SUPER_ADMIN))
    me = client.get("/api/auth/me").json()
    assert set(me["caps"]) == caps.ALL_CAP_KEYS


def test_me_caps_follow_an_override(client, db, auth, make_user):
    admin = make_user(C.ROLE_ADMIN)
    auth(admin)
    assert "payroll.manage" not in client.get("/api/auth/me").json()["caps"]
    db.add(RoleCapability(role=C.ROLE_ADMIN, capability="payroll.manage", allowed=True))
    db.commit()
    perms_svc.invalidate()
    assert "payroll.manage" in client.get("/api/auth/me").json()["caps"]


def test_an_employee_ships_a_small_cap_set(client, auth, make_user):
    auth(make_user(C.ROLE_EMPLOYEE))
    assert client.get("/api/auth/me").json()["caps"] == []

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


# --- 🔴 Step-level assignment is delegation (docs/TASKBOARD_REBUILD.md §2.4e, WP 4.2f) -----------
#
# This was a LIVE HOLE, not a design gap. `update_task`'s delegation guard covered `assigned_to_id`
# and `assigned_team_id` only; `maintasks` went through its own branch with no assignee check. And
# `task_perms.is_assigned` counts STEP owners for visibility — so an employee who could not reassign a
# task could still put any card on any colleague's board by naming them on a sub-task. Fixed where
# the field is written, and pinned here.

def _task_with_a_step(db, owner_id=None, assignee_id=None):
    from app.models import Task
    t = Task(title="Has a breakdown", assigned_to_id=assignee_id,
             maintasks_json='[{"id":"m1","title":"Phase","assignee_id":null,'
                            '"subs":[{"id":"s1","text":"Step","done":false,"assignee_id":'
                            + (str(owner_id) if owner_id else "null") + '}]}]')
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def _breakdown(step_owner=None, phase_owner=None):
    return [{"id": "m1", "title": "Phase", "assignee_id": phase_owner,
             "subs": [{"id": "s1", "text": "Step", "done": False, "assignee_id": step_owner}]}]


def test_employee_cannot_put_a_step_on_a_colleague(client, db, make_user, auth):
    """The hole itself: naming someone on a sub-task is delegation, because it puts the card on
    their board."""
    victim = make_user(C.ROLE_EMPLOYEE, name="Colleague")
    me = make_user(C.ROLE_EMPLOYEE, name="Me")
    t = _task_with_a_step(db, assignee_id=me.id)
    auth(me)
    r = client.patch(f"/api/tasks/{t.id}", json={"maintasks": _breakdown(step_owner=victim.id)})
    assert r.status_code == 403
    assert "someone else" in r.json()["detail"]


def test_employee_cannot_put_a_PHASE_on_a_colleague_either(client, db, make_user, auth):
    victim = make_user(C.ROLE_EMPLOYEE)
    me = make_user(C.ROLE_EMPLOYEE)
    t = _task_with_a_step(db, assignee_id=me.id)
    auth(me)
    assert client.patch(f"/api/tasks/{t.id}",
                        json={"maintasks": _breakdown(phase_owner=victim.id)}).status_code == 403


def test_employee_cannot_strip_a_colleagues_step_ownership(client, db, make_user, auth):
    """Taking work OFF someone is the same power as giving it to them."""
    victim = make_user(C.ROLE_EMPLOYEE)
    me = make_user(C.ROLE_EMPLOYEE)
    t = _task_with_a_step(db, owner_id=victim.id, assignee_id=me.id)
    auth(me)
    assert client.patch(f"/api/tasks/{t.id}",
                        json={"maintasks": _breakdown(step_owner=None)}).status_code == 403


def test_an_employee_may_still_pick_up_and_drop_their_OWN_step(client, db, make_user, auth):
    """Self-assignment is not delegation — every role may do it, or the board stops working."""
    me = make_user(C.ROLE_EMPLOYEE)
    t = _task_with_a_step(db, assignee_id=me.id)
    auth(me)
    assert client.patch(f"/api/tasks/{t.id}",
                        json={"maintasks": _breakdown(step_owner=me.id)}).status_code == 200
    assert client.patch(f"/api/tasks/{t.id}",
                        json={"maintasks": _breakdown(step_owner=None)}).status_code == 200


def test_an_employee_may_still_tick_and_rename_steps(client, db, make_user, auth):
    """Only the OWNER field is gated. Editing the work itself stays open to whoever can edit."""
    me = make_user(C.ROLE_EMPLOYEE)
    t = _task_with_a_step(db, assignee_id=me.id)
    auth(me)
    r = client.patch(f"/api/tasks/{t.id}", json={"maintasks": [
        {"id": "m1", "title": "Phase renamed", "assignee_id": None,
         "subs": [{"id": "s1", "text": "Step renamed", "done": True, "assignee_id": None}]}]})
    assert r.status_code == 200
    assert r.json()["maintasks"][0]["subs"][0]["done"] is True


def test_a_team_lead_may_assign_a_step_within_their_team(client, db, make_user, make_team, auth):
    team = make_team(name="Acquisition")
    lead = make_user(C.ROLE_TEAM_LEAD, team_id=team.id)
    member = make_user(C.ROLE_EMPLOYEE, team_id=team.id)
    from app.models import Task
    t = Task(title="Team work", assigned_team_id=team.id,
             maintasks_json='[{"id":"m1","title":"Phase","assignee_id":null,'
                            '"subs":[{"id":"s1","text":"Step","done":false,"assignee_id":null}]}]')
    db.add(t)
    db.commit()
    auth(lead)
    assert client.patch(f"/api/tasks/{t.id}",
                        json={"maintasks": _breakdown(step_owner=member.id)}).status_code == 200


# --- 🔴 …and comparing the owner SET was not enough (2026-08-05) ---------------------------------
#
# The fix above diffed `{owner ids} before` against `{owner ids} after`, so every edit that left the
# set intact answered 200 — and each of the six cases above ADDS or REMOVES a person, which is
# precisely why none of them could see it. An employee could therefore still rearrange a colleague's
# work: move their step, pile more onto them, swap two colleagues over. The diff is per SLOT now
# (`maintasks.slots` / `foreign_owner_changes`), so these hold the owner of each phase and step.

def _task_with_two_steps(db, owners=(None, None), assignee_id=None, team_id=None):
    from app.models import Task
    subs = ",".join(
        '{"id":"s%d","text":"Step %d","done":false,"assignee_id":%s}'
        % (i + 1, i + 1, o if o else "null") for i, o in enumerate(owners))
    t = Task(title="Two steps", assigned_to_id=assignee_id, assigned_team_id=team_id,
             maintasks_json='[{"id":"m1","title":"Phase","assignee_id":null,"subs":[' + subs + "]}]")
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def _two_steps(owners, done=(False, False), text=("Step 1", "Step 2")):
    return [{"id": "m1", "title": "Phase", "assignee_id": None, "subs": [
        {"id": f"s{i + 1}", "text": text[i], "done": done[i], "assignee_id": owners[i]}
        for i in range(2)]}]


def test_employee_cannot_move_a_colleagues_step_to_another_step(client, db, make_user, auth):
    """The set-diff hole: {victim} before, {victim} after — and the victim now holds different work."""
    victim = make_user(C.ROLE_EMPLOYEE, name="Colleague")
    me = make_user(C.ROLE_EMPLOYEE, name="Me")
    t = _task_with_two_steps(db, owners=(victim.id, None), assignee_id=me.id)
    auth(me)
    r = client.patch(f"/api/tasks/{t.id}", json={"maintasks": _two_steps((None, victim.id))})
    assert r.status_code == 403
    assert "someone else" in r.json()["detail"]


def test_employee_cannot_pile_more_steps_onto_a_colleague(client, db, make_user, auth):
    """Doubling somebody's workload does not change the owner SET at all."""
    victim = make_user(C.ROLE_EMPLOYEE)
    me = make_user(C.ROLE_EMPLOYEE)
    t = _task_with_two_steps(db, owners=(victim.id, None), assignee_id=me.id)
    auth(me)
    assert client.patch(f"/api/tasks/{t.id}",
                        json={"maintasks": _two_steps((victim.id, victim.id))}).status_code == 403


def test_employee_cannot_swap_two_colleagues_steps(client, db, make_user, auth):
    victim_a = make_user(C.ROLE_EMPLOYEE)
    victim_b = make_user(C.ROLE_EMPLOYEE)
    me = make_user(C.ROLE_EMPLOYEE)
    t = _task_with_two_steps(db, owners=(victim_a.id, victim_b.id), assignee_id=me.id)
    auth(me)
    assert client.patch(f"/api/tasks/{t.id}",
                        json={"maintasks": _two_steps((victim_b.id, victim_a.id))}).status_code == 403


def test_editing_the_work_around_a_colleagues_step_still_saves(client, db, make_user, auth):
    """The other side of the same rule: leave the owners alone and the breakdown is ordinary data."""
    victim = make_user(C.ROLE_EMPLOYEE)
    me = make_user(C.ROLE_EMPLOYEE)
    t = _task_with_two_steps(db, owners=(victim.id, None), assignee_id=me.id)
    auth(me)
    r = client.patch(f"/api/tasks/{t.id}", json={
        "maintasks": _two_steps((victim.id, None), text=("Step 1 reworded", "Step 2 reworded"))})
    assert r.status_code == 200
    assert r.json()["maintasks"][0]["subs"][0]["text"] == "Step 1 reworded"


def test_a_lead_may_rearrange_their_teams_steps(client, db, make_user, make_team, auth):
    team = make_team(name="Acquisition")
    lead = make_user(C.ROLE_TEAM_LEAD, team_id=team.id)
    member = make_user(C.ROLE_EMPLOYEE, team_id=team.id)
    t = _task_with_two_steps(db, owners=(member.id, None), team_id=team.id)
    auth(lead)
    assert client.patch(f"/api/tasks/{t.id}",
                        json={"maintasks": _two_steps((None, member.id))}).status_code == 200


# --- 🔴 Ticking somebody else's step (2026-08-05, task_perms.can_tick_step) -----------------------
#
# "Done" is a claim about work another person performed, and it is what the progress bar and the D5
# review gate read. It used to be open to anyone who could edit the card, so on a card with several
# owners every one of them could close each other's steps. Everything ELSE about a step — its text,
# whether it exists at all — is still open to whoever can edit.

def test_employee_cannot_tick_a_colleagues_step(client, db, make_user, auth):
    victim = make_user(C.ROLE_EMPLOYEE, name="Zhen")
    me = make_user(C.ROLE_EMPLOYEE, name="Me")
    t = _task_with_two_steps(db, owners=(victim.id, me.id))
    auth(me)
    r = client.patch(f"/api/tasks/{t.id}",
                     json={"maintasks": _two_steps((victim.id, me.id), done=(True, False))})
    assert r.status_code == 403
    assert "Zhen" in r.json()["detail"]          # name the owner, or the refusal is a riddle


def test_anyone_on_the_card_may_tick_an_UNOWNED_step(client, db, make_user, auth):
    """This is how a team's queue gets worked through — an unowned step is nobody's to protect."""
    me = make_user(C.ROLE_EMPLOYEE)
    t = _task_with_two_steps(db, owners=(None, None), assignee_id=me.id)
    auth(me)
    assert client.patch(f"/api/tasks/{t.id}", json={
        "maintasks": _two_steps((None, None), done=(True, False))}).status_code == 200


def test_you_may_always_tick_your_own_step(client, db, make_user, auth):
    victim = make_user(C.ROLE_EMPLOYEE)
    me = make_user(C.ROLE_EMPLOYEE)
    t = _task_with_two_steps(db, owners=(victim.id, me.id))
    auth(me)
    r = client.patch(f"/api/tasks/{t.id}",
                     json={"maintasks": _two_steps((victim.id, me.id), done=(False, True))})
    assert r.status_code == 200
    assert r.json()["maintasks"][0]["subs"][1]["done"] is True


def test_the_cards_lead_may_tick_anybodys_step(client, db, make_user, auth):
    """`assigned_to_id` is accountable for the card as a whole, so they may close it out."""
    victim = make_user(C.ROLE_EMPLOYEE)
    me = make_user(C.ROLE_EMPLOYEE)
    t = _task_with_two_steps(db, owners=(victim.id, None), assignee_id=me.id)
    auth(me)
    assert client.patch(f"/api/tasks/{t.id}", json={
        "maintasks": _two_steps((victim.id, None), done=(True, False))}).status_code == 200


def test_a_team_lead_may_tick_within_their_team(client, db, make_user, make_team, auth):
    """Somebody on leave must not be able to block the column — a lead already decides who holds the
    step, so they may also close it."""
    team = make_team(name="Acquisition")
    lead = make_user(C.ROLE_TEAM_LEAD, team_id=team.id)
    member = make_user(C.ROLE_EMPLOYEE, team_id=team.id)
    t = _task_with_two_steps(db, owners=(member.id, None), team_id=team.id)
    auth(lead)
    assert client.patch(f"/api/tasks/{t.id}", json={
        "maintasks": _two_steps((member.id, None), done=(True, False))}).status_code == 200


def test_deleting_a_colleagues_step_is_still_refused(client, db, make_user, auth):
    """Removing the slot removes their hold on it, which is the same power as granting it."""
    victim = make_user(C.ROLE_EMPLOYEE)
    me = make_user(C.ROLE_EMPLOYEE)
    t = _task_with_two_steps(db, owners=(victim.id, None), assignee_id=me.id)
    auth(me)
    r = client.patch(f"/api/tasks/{t.id}", json={"maintasks": [
        {"id": "m1", "title": "Phase", "assignee_id": None,
         "subs": [{"id": "s2", "text": "Step 2", "done": False, "assignee_id": None}]}]})
    assert r.status_code == 403


def test_a_tick_reads_the_owner_from_BEFORE_the_edit():
    """Unit-level, because no role can reach it through the API (changing the owner is refused
    first): clearing a step's owner in the same PATCH must not present the tick as unowned. The two
    guards must not be able to launder each other."""
    from app.services import maintasks as MT
    before = MT.slots(MT.normalize(_two_steps((7, None))))
    after = MT.slots(MT.normalize(_two_steps((None, None), done=(True, False))))
    assert [c["owner"] for c in MT.tick_changes(before, after)] == [7]


# --- The read-only seat (decision D8, docs/TASKBOARD_REBUILD.md §5.3, WP 4.4) --------------------
#
# A viewer SEES everything and WRITES nothing. §5.3 is explicit that the audit is the work, not the
# role — so this block walks every task write surface, including the ones guarded by
# `require_roles` / `is_manager` rather than by `task_perms`. If you add a task write, add it here.

def _viewer(make_user):
    return make_user(C.ROLE_VIEWER, name="Dana (observer)")


def test_viewer_sees_the_whole_board_including_other_peoples_work(
        client, db, make_user, make_team, auth):
    """Cross-client on purpose: a per-team viewer answers no useful question."""
    team = make_team(name="Acquisition")
    someone = make_user(C.ROLE_EMPLOYEE, team_id=team.id)
    from app.models import Task
    db.add(Task(title="Not the viewer's work", assigned_to_id=someone.id, assigned_team_id=team.id))
    db.commit()
    auth(_viewer(make_user))
    r = client.get("/api/tasks")
    assert r.status_code == 200 and len(r.json()) == 1


def test_viewer_gets_the_monitor_rollup(client, make_user, auth):
    """Monitoring is the seat's entire purpose, and `is_manager` alone would have excluded it —
    the exact shape of mistake §5.3 warns about."""
    auth(_viewer(make_user))
    assert client.get("/api/tasks/summary").status_code == 200


def test_viewer_can_open_a_task(client, db, make_user, auth):
    t = _a_task(db)
    auth(_viewer(make_user))
    assert client.get(f"/api/tasks/{t.id}").status_code == 200


@pytest.mark.parametrize("method,path,body", [
    ("post",  "",                       {"title": "Nope"}),
    ("patch", "/{id}",                  {"title": "renamed"}),
    ("patch", "/{id}/status",           {"status": C.TASK_IN_PROGRESS}),
    ("patch", "/{id}/priority",         {"priority": C.PRIORITY_URGENT}),
    ("post",  "/{id}/comments",         {"body": "hi"}),
    ("post",  "/{id}/park",             {"reason": "x"}),
    ("post",  "/{id}/resume",           {}),
    ("post",  "/{id}/archive",          {}),
    ("post",  "/{id}/unarchive",        {}),
    ("post",  "/{id}/review/submit",    {}),
    ("post",  "/{id}/review/approve",   {}),
    ("post",  "/{id}/review/request-changes", {"note": "x"}),
    ("post",  "/{id}/send-back",        {"reason": "x"}),
    ("post",  "/{id}/sessions/start",   {}),
    ("post",  "/{id}/sessions/pause",   {}),
    ("post",  "/{id}/send-to-atrium",   {}),
    ("post",  "/{id}/atrium-retry",     {}),
    ("post",  "/{id}/atrium-clear-share", {}),
    ("delete", "/{id}",                 None),
])
def test_viewer_is_refused_every_task_write(client, db, make_user, auth, method, path, body):
    """🔴 The whole point of the seat. Every one of these is a WRITE; a viewer must get 403 from all
    of them, whether the guard is `task_perms`, `require_roles` or a rank check."""
    t = _a_task(db)
    auth(_viewer(make_user))
    url = "/api/tasks" + path.replace("{id}", str(t.id))
    call = getattr(client, method)
    r = call(url) if body is None else call(url, json=body)
    assert r.status_code == 403, f"{method.upper()} {url} answered {r.status_code}, not 403"


def test_viewer_cannot_write_an_atrium_card_but_may_read_one(client, make_user, auth, monkeypatch):
    """🔴 `can_edit_atrium` used to be a bare alias of `can_view_atrium`, so letting a viewer SEE
    client cards would have let it edit, move, comment on and resolve them."""
    from app.services import atrium_tasks
    monkeypatch.setattr(atrium_tasks, "enabled", lambda: True)
    monkeypatch.setattr(atrium_tasks, "fetch_task",
                        lambda k, t: ({"task": {"atrium_id": "honeytribe:tk_1", "title": "Client work"}}, ""))
    auth(_viewer(make_user))
    assert client.get("/api/tasks/atrium:honeytribe:tk_1").status_code == 200
    assert client.patch("/api/tasks/atrium:honeytribe:tk_1",
                        json={"title": "hacked"}).status_code == 403
    assert client.patch("/api/tasks/atrium:honeytribe:tk_1/status",
                        json={"status": C.TASK_COMPLETED}).status_code == 403
    assert client.post("/api/tasks/atrium:honeytribe:tk_1/comments",
                       json={"body": "hi"}).status_code == 403
    assert client.post("/api/tasks/atrium:honeytribe:tk_1/comments/c1/resolve").status_code == 403


def test_viewer_cannot_reach_the_manage_screens_or_approvals(client, make_user, auth):
    """The seat must not inherit anything by rank. Manage is super-admin; approvals are MANAGER_ROLES,
    which ROLE_VIEWER is deliberately absent from."""
    auth(_viewer(make_user))
    assert client.get("/api/manage/task-vocab").status_code == 403
    assert client.post("/api/manage/task-vocab",
                       json={"kind": "label", "name": "X"}).status_code == 403


def test_the_viewer_role_is_the_lowest_rank_so_no_min_role_gate_opens(make_user):
    """🔴 §5.3: give the seat a high rank and every `require_min_role` write endpoint opens. Its power
    comes from being NAMED in VIEW_ALL_ROLES, never from out-ranking anybody."""
    assert C.ROLE_RANK[C.ROLE_VIEWER] == min(C.ROLE_RANK.values())
    assert C.ROLE_VIEWER not in C.MANAGER_ROLES
    assert C.ROLE_VIEWER not in C.ADMIN_ROLES
    assert C.ROLE_VIEWER in C.VIEW_ALL_ROLES


def test_can_edit_is_no_longer_an_alias_of_can_view(make_user):
    """The alias is what made a read-only seat impossible (§2.4b). If someone re-aliases them, this
    fails — which is the point."""
    from app.services import task_perms
    assert task_perms.can_edit is not task_perms.can_view
    assert task_perms.can_edit_atrium is not task_perms.can_view_atrium

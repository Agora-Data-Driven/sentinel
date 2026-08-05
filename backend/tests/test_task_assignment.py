"""The assignment ladder: routing to a team, who can see queued work, and refusing it.

Stage 4 of docs/TASKBOARD_REBUILD.md (§2.4c / c-bis / d / g, decisions D9–D11). The shape being
pinned, in order:

    service type -> department (the form)
    department   -> visible to that TEAM, owned by NOBODY          <- 4.2 / 4.2b
                    ...and its leads are notified                  <- 4.2c, by QUERY not a column
    per-step owners + assigned_to_id                               <- the lead
    "not ours"   -> back to the filer, with an internal reason      <- 4.2e / D11

Two rules that are easy to get backwards and are therefore tested from both sides:

* an employee may route work to a TEAM but never to a PERSON (D10);
* team work is shared only while it is UNASSIGNED — the moment someone owns it, it is their job and
  leaves everybody else's board (the July 2026 "an intern's board showed seven cards, none of them
  theirs" regression must not come back).
"""
from __future__ import annotations

import pytest

from app import constants as C
from app.models import Notification, Task, TaskHistory, User


@pytest.fixture
def acq(make_team):
    return make_team(name="Acquisition")


@pytest.fixture
def dev(make_team):
    return make_team(name="Development")


@pytest.fixture
def acq_lead(make_user, acq):
    return make_user(C.ROLE_TEAM_LEAD, team_id=acq.id, name="Ehjay")


@pytest.fixture
def acq_member(make_user, acq):
    return make_user(C.ROLE_EMPLOYEE, team_id=acq.id, name="Zhen")


# --- 4.2 / 4.2b: routed-but-unassigned is a real state -------------------------------------------

def test_team_work_with_no_owner_is_visible_to_the_team(client, auth, db, acq, acq_member):
    """§2.4c: routing to a team used to surface the card to NOBODY but managers, so the natural flow
    (file → route → the lead delegates) left it invisible during the middle step."""
    t = Task(title="Website bug", assigned_team_id=acq.id)
    db.add(t)
    db.commit()
    auth(acq_member)
    assert t.id in [c["id"] for c in client.get("/api/tasks").json()]


def test_once_owned_it_leaves_everybody_elses_board(client, auth, db, acq, acq_member, make_user):
    """🔴 The July 2026 regression in reverse. Shared while unowned; private once owned — otherwise an
    employee's board fills up with their colleagues' work again."""
    other = make_user(C.ROLE_EMPLOYEE, team_id=acq.id, name="Someone else")
    t = Task(title="Owned by a colleague", assigned_team_id=acq.id, assigned_to_id=other.id)
    db.add(t)
    db.commit()
    auth(acq_member)
    assert t.id not in [c["id"] for c in client.get("/api/tasks").json()]


def test_another_teams_queue_is_not_my_business(client, auth, db, dev, acq_member):
    t = Task(title="Someone else's queue", assigned_team_id=dev.id)
    db.add(t)
    db.commit()
    auth(acq_member)
    assert t.id not in [c["id"] for c in client.get("/api/tasks").json()]


# --- 4.2c: routing notifies the team's leads, found by QUERY (D9) --------------------------------

def test_routing_to_a_team_notifies_its_leads_and_admins(
        client, auth, db, acq, acq_lead, make_user):
    """🔴 D9: there is no `Team.lead_id`. `notify_managers(team_id=…)` finds leads by role + team,
    which is why zero leads and three leads both work. Before this, a team-routed card notified
    nobody and sat in a queue until somebody happened to look."""
    second = make_user(C.ROLE_TEAM_LEAD, team_id=acq.id, name="Justine")
    admin = make_user(C.ROLE_ADMIN)
    other_lead = make_user(C.ROLE_TEAM_LEAD, team_id=None, name="Nobody's lead")
    am = make_user(C.ROLE_ACCOUNT_MANAGER)
    auth(am)

    r = client.post("/api/tasks", json={"title": "Route me", "assigned_team_id": acq.id})
    assert r.status_code == 200
    notified = {n.user_id for n in db.query(Notification)}
    assert {acq_lead.id, second.id, admin.id} <= notified
    assert other_lead.id not in notified          # different team — not their queue


def test_re_routing_an_existing_task_notifies_the_new_team(client, auth, db, acq, acq_lead, make_user):
    auth(make_user(C.ROLE_ACCOUNT_MANAGER))
    t = Task(title="Move me")
    db.add(t)
    db.commit()
    assert client.patch(f"/api/tasks/{t.id}", json={"assigned_team_id": acq.id}).status_code == 200
    assert acq_lead.id in {n.user_id for n in db.query(Notification)}


def test_an_owned_card_does_not_ping_the_team(client, auth, db, acq, acq_lead, acq_member, make_user):
    """A card with an assignee is somebody's job, not a queue item — and that person was already
    notified directly. Pinging the leads too is noise."""
    auth(make_user(C.ROLE_ACCOUNT_MANAGER))
    client.post("/api/tasks", json={"title": "Owned on arrival", "assigned_team_id": acq.id,
                                    "assigned_to_id": acq_member.id})
    lead_notes = [n for n in db.query(Notification) if n.user_id == acq_lead.id]
    assert lead_notes == []


# --- 4.2d / D10: an employee routes to a TEAM, never to a person ---------------------------------

def test_an_employee_may_route_work_to_another_team(client, auth, db, dev, acq_member):
    """An Acquisition employee who spots a website bug should not have to own the fix (§2.4d).
    Before this, everything a non-delegating role created was force-assigned to them."""
    auth(acq_member)
    r = client.post("/api/tasks", json={"title": "Homepage is broken", "assigned_team_id": dev.id})
    assert r.status_code == 200
    body = r.json()
    assert body["assigned_team_id"] == dev.id
    assert body["assigned_to_id"] is None          # routed, not delegated
    assert body["created_by_id"] == acq_member.id  # ...but recorded as theirs


def test_an_employee_still_cannot_name_a_person(client, auth, db, dev, acq_member, make_user):
    """🔴 A 403, not a silent correction (2026-08-05). This used to drop `assigned_to_id` and answer
    200, so the form let them pick a colleague, said "created", and quietly put the card on their own
    board instead — the same shape of lie as the old Send to Atrium. The picker is gated in the UI
    now, so reaching this means the caller really did try."""
    victim = make_user(C.ROLE_EMPLOYEE, team_id=dev.id)
    auth(acq_member)
    r = client.post("/api/tasks", json={"title": "Do this for me", "assigned_team_id": dev.id,
                                        "assigned_to_id": victim.id})
    assert r.status_code == 403
    assert "somebody else" in r.json()["detail"]
    assert db.query(Task).filter(Task.title == "Do this for me").count() == 0   # nothing was filed


def test_an_employee_may_still_name_THEMSELVES(client, auth, dev, acq_member):
    """Naming yourself is not delegation. Filing work into a department that you intend to do
    yourself is a real thing, and dropping that to None would be the silent correction again."""
    auth(acq_member)
    r = client.post("/api/tasks", json={"title": "I'll take this one", "assigned_team_id": dev.id,
                                        "assigned_to_id": acq_member.id})
    assert r.status_code == 200
    assert r.json()["assigned_to_id"] == acq_member.id


def test_an_employees_own_quick_task_still_self_assigns(client, auth, acq_member):
    """No team implied = it is mine. The quick-add path must keep landing on my own board."""
    auth(acq_member)
    r = client.post("/api/tasks", json={"title": "My own note to self"})
    assert r.json()["assigned_to_id"] == acq_member.id


# --- 4.2g bis / 2026-08-05: a team lead staffs THEIR OWN department's work ------------------------
#
# 🔴 Create was strictly more permissive than edit. `task_perms.can_reassign` lets a lead name
# somebody only while the card is routed to their own team (`_leads_team`) — but `create_task` tested
# the ROLE alone, so the same lead could file a card for another department with a name already on
# it. Same rule, both doors.

def test_a_lead_may_name_someone_on_their_own_departments_card(client, auth, acq, acq_lead, acq_member):
    auth(acq_lead)
    r = client.post("/api/tasks", json={"title": "Campaign build", "assigned_team_id": acq.id,
                                        "assigned_to_id": acq_member.id})
    assert r.status_code == 200
    assert r.json()["assigned_to_id"] == acq_member.id


def test_a_lead_cannot_name_someone_in_another_department(client, auth, db, dev, acq_lead, make_user):
    victim = make_user(C.ROLE_EMPLOYEE, team_id=dev.id)
    auth(acq_lead)
    r = client.post("/api/tasks", json={"title": "Fix the site", "assigned_team_id": dev.id,
                                        "assigned_to_id": victim.id})
    assert r.status_code == 403


def test_a_lead_filing_for_another_department_keeps_their_priority(client, auth, dev, acq_lead):
    """Priority is NOT delegation, so it must not be collateral damage of the rule above — tying it to
    the same team test would silently downgrade those cards to Medium."""
    auth(acq_lead)
    r = client.post("/api/tasks", json={"title": "Urgent site fix", "assigned_team_id": dev.id,
                                        "priority": C.PRIORITY_URGENT})
    assert r.status_code == 200
    assert r.json()["priority"] == C.PRIORITY_URGENT
    assert r.json()["assigned_to_id"] is None      # routed to Development's queue, owned by nobody


def test_filed_by_me_shows_where_the_work_went(client, auth, db, dev, acq_member, make_user):
    """Routing takes the card OFF the filer's board by design, so this list is the answer to "I
    filed it and now I can't find it" — where it went, and nothing internal."""
    auth(acq_member)
    tid = client.post("/api/tasks", json={"title": "Homepage is broken",
                                          "assigned_team_id": dev.id}).json()["id"]
    rows = client.get("/api/tasks/filed-by-me").json()
    row = next(r for r in rows if r["id"] == tid)
    assert row["team_name"] == "Development"
    assert row["awaiting_triage"] is True
    assert row["owner_name"] is None
    # ...and none of the internal vocabulary leaks into this shape.
    assert not ({"priority", "service_charge", "internal_notes", "maintasks", "assigned_to_id"}
                & set(row))


def test_filed_by_me_omits_work_i_still_hold(client, auth, acq_member):
    auth(acq_member)
    client.post("/api/tasks", json={"title": "Still mine"})
    assert client.get("/api/tasks/filed-by-me").json() == []


def test_filed_by_me_is_not_swallowed_by_the_task_id_route(client, auth, acq_member):
    """🔴 FastAPI matches in declaration order: a single-segment literal declared after
    `GET /{task_id}` answers 404/422 instead of listing (AGENTS.md §5)."""
    auth(acq_member)
    r = client.get("/api/tasks/filed-by-me")
    assert r.status_code == 200 and isinstance(r.json(), list)


# --- 4.2e / D11: send it back -------------------------------------------------------------------

def test_a_lead_can_send_queued_work_back_to_the_filer(
        client, auth, db, dev, acq_member, make_user):
    """D11: refusing work must be expressible, or a wrongly-routed card just rots in a queue."""
    dev_lead = make_user(C.ROLE_TEAM_LEAD, team_id=dev.id, name="Charles")
    auth(acq_member)
    tid = client.post("/api/tasks", json={"title": "Not our job",
                                          "assigned_team_id": dev.id}).json()["id"]
    auth(dev_lead)
    r = client.post(f"/api/tasks/{tid}/send-back",
                    json={"reason": "This is a Lifecycle email, not a website change."})
    assert r.status_code == 200
    assert r.json()["returned_to"] == "Zhen"

    db.expire_all()
    t = db.get(Task, tid)
    # Ownership is never left vague: the team link is cleared AND the filer holds it again.
    assert t.assigned_team_id is None
    assert t.assigned_to_id == acq_member.id


def test_the_bounce_reason_is_recorded_and_reaches_the_filer(
        client, auth, db, dev, acq_member, make_user):
    dev_lead = make_user(C.ROLE_TEAM_LEAD, team_id=dev.id)
    auth(acq_member)
    tid = client.post("/api/tasks", json={"title": "Wrong queue",
                                          "assigned_team_id": dev.id}).json()["id"]
    auth(dev_lead)
    client.post(f"/api/tasks/{tid}/send-back", json={"reason": "Belongs to Lifecycle."})

    hist = db.query(TaskHistory).filter(TaskHistory.task_id == tid,
                                        TaskHistory.field_changed == "sent_back").one()
    assert hist.new_value == "Belongs to Lifecycle."
    # The filer is told, and their Filed-by-me row says so.
    assert any("Sent back" in (n.title or "") for n in db.query(Notification)
               if n.user_id == acq_member.id)
    auth(acq_member)
    row = next(r for r in client.get("/api/tasks/filed-by-me").json() if r["id"] == tid)
    assert row["sent_back_reason"] == "Belongs to Lifecycle."


def test_the_bounce_reason_never_crosses_to_the_client(db, dev, acq_member, make_user):
    """The reason is INTERNAL: a client learning that two departments disagreed about their work is
    exactly the leak the client-safe split exists to prevent."""
    from app.services import task_bridge
    t = Task(title="Wrong queue", created_by_id=acq_member.id, atrium_task_id="t_x")
    db.add(t)
    db.commit()
    blob = repr(task_bridge.client_safe_fields(t, db))
    assert "sent_back" not in blob and "Belongs to" not in blob


def test_work_somebody_already_owns_cannot_be_bounced(client, auth, db, dev, acq_member, make_user):
    """Only while unassigned. Once you pick it up you own it, and the right move is to reassign."""
    dev_lead = make_user(C.ROLE_TEAM_LEAD, team_id=dev.id)
    dev_member = make_user(C.ROLE_EMPLOYEE, team_id=dev.id)
    auth(acq_member)
    tid = client.post("/api/tasks", json={"title": "Taken",
                                          "assigned_team_id": dev.id}).json()["id"]
    auth(dev_lead)
    client.patch(f"/api/tasks/{tid}", json={"assigned_to_id": dev_member.id})
    r = client.post(f"/api/tasks/{tid}/send-back", json={"reason": "changed my mind"})
    assert r.status_code == 409
    assert "already owns" in r.json()["detail"]


def test_an_employee_cannot_bounce_work(client, auth, db, dev, acq_member, make_user):
    """Refusing on a team's behalf is the lead's call — it follows can_review."""
    dev_member = make_user(C.ROLE_EMPLOYEE, team_id=dev.id)
    auth(acq_member)
    tid = client.post("/api/tasks", json={"title": "Not yours to refuse",
                                          "assigned_team_id": dev.id}).json()["id"]
    auth(dev_member)
    assert client.post(f"/api/tasks/{tid}/send-back", json={"reason": "nope"}).status_code == 403


def test_after_bouncing_the_lead_can_no_longer_see_it(client, auth, db, dev, acq_member, make_user):
    """Looks like a bug, is the point: refusing work stops it being yours."""
    dev_lead = make_user(C.ROLE_TEAM_LEAD, team_id=dev.id)
    auth(acq_member)
    tid = client.post("/api/tasks", json={"title": "Bounced",
                                          "assigned_team_id": dev.id}).json()["id"]
    auth(dev_lead)
    client.post(f"/api/tasks/{tid}/send-back", json={"reason": "not ours"})
    assert tid not in [c["id"] for c in client.get("/api/tasks").json()]
    # ...and it IS back on the filer's board.
    auth(acq_member)
    assert tid in [c["id"] for c in client.get("/api/tasks").json()]


def test_an_atrium_card_cannot_be_sent_back(client, auth, make_user):
    auth(make_user(C.ROLE_ACCOUNT_MANAGER))
    r = client.post("/api/tasks/atrium:honeytribe:tk_1/send-back", json={"reason": "x"})
    assert r.status_code == 400

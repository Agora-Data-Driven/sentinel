"""The assignment ladder: routing to a team, who can see queued work, and refusing it.

Stage 4 of docs/TASKBOARD_REBUILD.md (§2.4c / c-bis / d / g, decisions D9–D11). The shape being
pinned, in order:

    service type -> department (the form)
    department   -> visible to that TEAM, owned by NOBODY          <- 4.2 / 4.2b
                    ...and its leads are notified                  <- 4.2c, by QUERY not a column
    per-step owners + assigned_to_id                               <- the lead
    "not ours"   -> back to the filer, with an internal reason      <- 4.2e / D11

Three rules that are easy to get backwards and are therefore tested from both sides:

* an employee may route work to a TEAM but never to a PERSON (D10);
* an employee SEES their whole department and may WRITE to almost none of it (2026-08-14). The July
  2026 regression — "an intern's board showed seven cards, none of them theirs" — was about
  accountability, not secrecy, so it is now pinned on `mine` / `can_edit` rather than on the card
  being absent. Asserting only one half of that lets the other half regress silently;
* whatever a team lead may do to an EXISTING card, `create_task` must let them do to a new one. That
  invariant has been enforced at two different settings; the settings are allowed to move, the
  agreement between the two doors is not.
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


def test_a_colleagues_card_is_visible_to_the_department_but_read_only(
        client, auth, db, acq, acq_member, make_user):
    """🔴 REPLACES `test_once_owned_it_leaves_everybody_elses_board` (2026-08-14).

    That test pinned "shared while unowned, INVISIBLE once owned", which is the July 2026 fix stated
    as a visibility rule. The fix was really about ACCOUNTABILITY — a board listing ten colleagues'
    cards stops answering "what am I working on" — and stating it as visibility made a department
    opaque to its own members: you could not see what your team was carrying or whether the thing you
    were about to raise already existed.

    So the rule moved to where it belongs. The card is VISIBLE (`task_perms._dept`) and READ-ONLY
    (`can_edit` no longer follows `can_view` for employees). Both halves are asserted here, because
    either one alone is a bug: visibility without the read-only half hands every employee write access
    to the whole department, and the read-only half without visibility is the opacity being fixed.
    """
    other = make_user(C.ROLE_EMPLOYEE, team_id=acq.id, name="Someone else")
    t = Task(title="Owned by a colleague", assigned_team_id=acq.id, assigned_to_id=other.id)
    db.add(t)
    db.commit()
    auth(acq_member)

    card = next((c for c in client.get("/api/tasks").json() if c["id"] == t.id), None)
    assert card is not None, "an employee should see their own department's work"
    # ...but it is somebody else's job, and the board must say so on the card itself.
    assert card["mine"] is False
    assert card["can_edit"] is False

    # And the server enforces it — the flag is a courtesy to the UI, never the gate.
    assert client.patch(f"/api/tasks/{t.id}", json={"title": "hijacked"}).status_code == 403
    assert client.patch(f"/api/tasks/{t.id}/status",
                        json={"status": C.TASK_COMPLETED}).status_code == 403


def test_the_department_read_does_not_reach_another_department(client, auth, db, dev, acq_member):
    """The widened read is scoped to the viewer's OWN department — it is not a board-wide unlock."""
    other_teams = Task(title="Development's owned work", assigned_team_id=dev.id, assigned_to_id=None)
    db.add(other_teams)
    db.commit()
    auth(acq_member)
    assert other_teams.id not in [c["id"] for c in client.get("/api/tasks").json()]


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


# --- 4.2g bis: create and edit must agree about who a lead may staff ------------------------------
#
# The rule this section pins has been at two settings, and the INVARIANT is what matters: whatever
# `task_perms` lets a lead do to an existing card, `create_task` must let them do to a new one.
#
# 2026-08-05 enforced that at the NARROW setting (own department only), because create tested the
# role alone while `can_reassign` asked `_leads_team`. 2026-08-14 enforces it at the WIDE setting:
# `can_reassign` now asks `_lead_may_act` (anything the lead can SEE), and `can_view` shows a lead
# everything they CREATED whatever department it went to — so the narrow create test had become
# stricter than edit, and refused a lead's own form with "Only a team lead or manager can assign".
#
# What has never moved, and is the real content of D10: an EMPLOYEE may route to a department but
# never name a person.

def test_a_lead_may_name_someone_on_their_own_departments_card(client, auth, acq, acq_lead, acq_member):
    auth(acq_lead)
    r = client.post("/api/tasks", json={"title": "Campaign build", "assigned_team_id": acq.id,
                                        "assigned_to_id": acq_member.id})
    assert r.status_code == 200
    assert r.json()["assigned_to_id"] == acq_member.id


def test_a_lead_may_name_someone_in_another_department_and_keeps_the_card(
        client, auth, db, dev, acq_lead, make_user):
    """The other half of the invariant above: a lead files cross-department work with an owner on it,
    and — because `_created` keeps it visible to them — can still restaff it afterwards. Refusing the
    create while allowing the edit was the inconsistency, and it read as "assign is broken"."""
    other = make_user(C.ROLE_EMPLOYEE, team_id=dev.id, name="Dev person")
    auth(acq_lead)
    r = client.post("/api/tasks", json={"title": "Fix the site", "assigned_team_id": dev.id,
                                        "assigned_to_id": other.id})
    assert r.status_code == 200
    assert r.json()["assigned_to_id"] == other.id

    tid = r.json()["id"]
    second = make_user(C.ROLE_EMPLOYEE, team_id=dev.id, name="Other dev person")
    assert client.patch(f"/api/tasks/{tid}", json={"assigned_to_id": second.id}).status_code == 200


def test_an_employee_still_cannot_name_a_person_in_another_department(
        client, auth, db, dev, acq_member, make_user):
    """D10 is untouched by the 2026-08-14 widening — it only ever moved for team_lead and up."""
    victim = make_user(C.ROLE_EMPLOYEE, team_id=dev.id)
    auth(acq_member)
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


# --- 2026-08-14: the "Team Lead can't assign / can't approve" bug ---------------------------------
#
# 🔴 Reported as two separate faults; it was one predicate. Every lead power asked `_leads_team`
# (`task.assigned_team_id == user.team_id`) while `can_view` let a lead reach a card through FOUR
# branches — so the board routinely handed a lead a card with every control dead, and because
# `taskboard.js` mirrors these predicates the picker rendered `disabled` and Approve was never drawn.
# Nobody ever saw a 403; they saw a feature that appeared not to exist.
#
# One test per way in, because each is a genuinely different route to the same dead card and a fix
# that only covers the obvious one leaves the report alive. See `task_perms._lead_may_act`.

# 🔴 The parametrisation lists the ways a lead genuinely REACHES a card, which is not the same as
# "every card with no department". A departmentless card that is unowned, uncreated and unlinked is
# invisible to everyone below AM — `can_view` has no branch for it — so there was never a dead button
# there to fix. Writing the obvious-looking scenario first is what surfaced that; each case below is
# asserted visible before it is asserted actionable, so a future change that quietly removes one of
# `can_view`'s branches fails here loudly instead of turning this into a test of nothing.
@pytest.mark.parametrize("reached_via", ["is_assigned", "created_by_the_lead", "lead_has_no_team"])
def test_a_lead_can_staff_a_card_they_can_see(client, auth, db, acq, dev, acq_lead, acq_member,
                                              reached_via):
    t = Task(title="Quick-added, no department chosen")
    if reached_via == "is_assigned":
        # The commonest report: work handed straight to the lead, department left blank.
        t.assigned_to_id = acq_lead.id
    if reached_via == "created_by_the_lead":
        # A lead raises work for another department; `_created` keeps it on their board.
        t.assigned_team_id = dev.id
        t.created_by_id = acq_lead.id
    if reached_via == "lead_has_no_team":
        # The flat case: nobody ever filled in the lead's own department on their profile, which used
        # to disable their entire role everywhere at once, on every card.
        t.assigned_team_id = acq.id
        t.assigned_to_id = acq_lead.id
        acq_lead.team_id = None
    db.add(t)
    db.commit()
    auth(acq_lead)

    assert t.id in [c["id"] for c in client.get("/api/tasks").json()], "precondition: it is visible"
    # Priority first — it was dead for exactly the same reason as assignment.
    assert client.patch(f"/api/tasks/{t.id}/priority",
                        json={"priority": C.PRIORITY_URGENT}).status_code == 200
    # #1 — assign. 🔴 LAST ON PURPOSE. Because a lead's powers now follow VISIBILITY, handing a card
    # to somebody else can be the act that ends the lead's own sight of it (here: the card reached
    # them via `is_assigned`, and they just assigned it away). That is the same deliberate property
    # as `test_after_bouncing_the_lead_can_no_longer_see_it` — delegating is giving it away — but it
    # makes these calls order-dependent, which a reader of this test needs to know.
    assert client.patch(f"/api/tasks/{t.id}",
                        json={"assigned_to_id": acq_member.id}).status_code == 200


def test_a_lead_can_approve_a_card_with_no_department(client, auth, db, acq_lead, acq_member):
    """#3 — the approval half. Submitting for review needs only `can_edit`, so work could be pushed
    into `pending` and then approved by nobody below AM: the lead saw the card (they raised it) and
    the Approve button was never drawn. That is a review state with no reachable exit."""
    t = Task(title="Undepartmented work", assigned_to_id=acq_member.id, created_by_id=acq_lead.id)
    db.add(t)
    db.commit()
    auth(acq_member)
    assert client.post(f"/api/tasks/{t.id}/review/submit").status_code == 200
    auth(acq_lead)
    assert client.post(f"/api/tasks/{t.id}/review/approve").status_code == 200


def test_a_lead_still_cannot_touch_a_card_they_cannot_see(client, auth, db, dev, acq_lead, make_user):
    """🔴 The widening is "anything they CAN SEE" — it is not "anything". Another department's owned
    work is invisible to this lead, and every power must stay refused on it."""
    dev_member = make_user(C.ROLE_EMPLOYEE, team_id=dev.id)
    t = Task(title="Development's own work", assigned_team_id=dev.id, assigned_to_id=dev_member.id)
    db.add(t)
    db.commit()
    auth(acq_lead)
    assert t.id not in [c["id"] for c in client.get("/api/tasks").json()]
    assert client.patch(f"/api/tasks/{t.id}", json={"assigned_to_id": acq_lead.id}).status_code == 403
    assert client.post(f"/api/tasks/{t.id}/review/approve").status_code == 403
    assert client.patch(f"/api/tasks/{t.id}/priority",
                        json={"priority": C.PRIORITY_URGENT}).status_code == 403


def test_delete_is_deliberately_not_widened_with_the_rest(client, auth, db, acq_lead, make_user):
    """🔴 Assign/approve/prioritise follow `can_view`; DELETE deliberately does not (`can_delete`
    still asks `_leads_team`). `can_view` reaches a lead through branches as thin as "somebody named
    you on one step", and delete is the only irreversible act on this board. If this test starts
    failing, that asymmetry was removed — make sure it was on purpose."""
    owner = make_user(C.ROLE_EMPLOYEE, name="Owner")
    t = Task(title="Card the lead merely holds a step on", assigned_to_id=owner.id,
             maintasks_json='[{"id":"m1","title":"Phase","assignee_id":%d,"subs":[]}]' % acq_lead.id)
    db.add(t)
    db.commit()
    auth(acq_lead)
    assert t.id in [c["id"] for c in client.get("/api/tasks").json()]
    assert client.patch(f"/api/tasks/{t.id}", json={"assigned_to_id": acq_lead.id}).status_code == 200
    assert client.delete(f"/api/tasks/{t.id}").status_code == 403

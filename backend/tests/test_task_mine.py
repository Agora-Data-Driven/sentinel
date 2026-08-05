"""`mine` — the server's answer to "is this work on ME?" (2026-08-05).

The bug this closes: an employee held a sub-task of a card LED by a colleague. The Task Board showed
that card (`task_perms.can_view` → `is_assigned`, which counts step owners), and the Overview's "my
work" strip said **"0 open tasks · nothing on you right now"** — because it re-derived "assigned" in
JS as `assigned_to_id === me`, the narrower rule. Two surfaces, two definitions, one of them telling
a delegate their plate was empty while the work sat one click away.

So there is now exactly ONE definition, `task_perms.is_assigned`, and `serializers.task_card`
publishes it as `mine`. What these tests pin:

* `mine` is TRUE for a step owner, a phase owner and the card's lead — the three ways work lands on
  a person;
* it stays FALSE for a card merely visible to you (a team queue, a card you created, a manager's
  cross-client sight). "I can see it" is not "it is mine", and conflating them is how the strip
  would start counting the whole company's board as one person's plate;
* `my_slots` counts the breakdown slots you hold, which is how a surface explains a card whose
  Assigned-to names somebody else;
* the fields are **absent, never faked**, where no viewer is named.
"""
from __future__ import annotations

import pytest

from app import constants as C
from app.models import Task


def _card(client, task_id):
    for c in client.get("/api/tasks").json():
        if c["id"] == task_id:
            return c
    return None


def _breakdown(step_owner=None, phase_owner=None, extra_steps=()):
    subs = [{"id": "s1", "text": "Step", "done": False, "assignee_id": step_owner}]
    for i, owner in enumerate(extra_steps, start=2):
        subs.append({"id": f"s{i}", "text": f"Step {i}", "done": False, "assignee_id": owner})
    return [{"id": "m1", "title": "Phase", "assignee_id": phase_owner, "subs": subs}]


@pytest.fixture
def team(make_team):
    return make_team(name="Bidbrain")


@pytest.fixture
def lead_user(make_user, team):
    """The colleague who LEADS the card — `assigned_to_id`."""
    return make_user(C.ROLE_EMPLOYEE, team_id=team.id, name="Jerome")


@pytest.fixture
def me(make_user, team):
    return make_user(C.ROLE_EMPLOYEE, team_id=team.id, name="Christian")


def _task(db, **kw):
    from app.services import maintasks as MT
    if "maintasks" in kw:
        kw["maintasks_json"] = MT.dumps(kw.pop("maintasks"))
    t = Task(title=kw.pop("title", "Bidbrain-Analytics Ticketing Setup"), **kw)
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


# --- the reported bug ----------------------------------------------------------------------------

def test_a_step_on_me_makes_the_card_mine(client, auth, db, team, lead_user, me):
    """🔴 THE REGRESSION. Led by Jerome, one sub-task named to Christian: the card was on his board
    and his Overview counted it nowhere."""
    t = _task(db, assigned_to_id=lead_user.id, assigned_team_id=team.id,
              maintasks=_breakdown(step_owner=me.id))
    auth(me)
    card = _card(client, t.id)
    assert card is not None, "the board showed this card even before the fix"
    assert card["mine"] is True
    assert card["my_slots"] == 1
    # And the card's lead is still somebody else — which is exactly what the strip has to say.
    assert card["assigned_to_id"] == lead_user.id


def test_a_phase_on_me_counts_too(client, auth, db, lead_user, me):
    t = _task(db, assigned_to_id=lead_user.id, maintasks=_breakdown(phase_owner=me.id))
    auth(me)
    assert _card(client, t.id)["mine"] is True


def test_being_the_lead_is_still_mine(client, auth, db, me):
    t = _task(db, assigned_to_id=me.id)
    auth(me)
    card = _card(client, t.id)
    assert card["mine"] is True
    # No slot of the breakdown names me — `my_slots` is about the breakdown, not the card.
    assert card["my_slots"] == 0


def test_my_slots_counts_every_slot_i_hold(client, auth, db, lead_user, me):
    """The number the "N steps on you" pill renders. A phase plus two of its steps = 3."""
    t = _task(db, assigned_to_id=lead_user.id,
              maintasks=_breakdown(step_owner=me.id, phase_owner=me.id, extra_steps=(me.id,)))
    auth(me)
    assert _card(client, t.id)["my_slots"] == 3


# --- "I can see it" is NOT "it is mine" ----------------------------------------------------------

def test_the_team_queue_is_visible_but_not_mine(client, auth, db, team, me):
    """Unowned team work is on every member's board (§2.4c) and belongs to none of them yet. If
    `mine` said yes here, one triage queue would land on everybody's Overview as their own plate."""
    t = _task(db, assigned_team_id=team.id)
    auth(me)
    card = _card(client, t.id)
    assert card is not None
    assert card["mine"] is False


def test_a_colleagues_card_i_merely_lead_the_team_of_is_not_mine(client, auth, db, team,
                                                                lead_user, make_user):
    boss = make_user(C.ROLE_TEAM_LEAD, team_id=team.id, name="Lead")
    t = _task(db, assigned_to_id=lead_user.id, assigned_team_id=team.id)
    auth(boss)
    card = _card(client, t.id)
    assert card is not None, "a lead sees their team's work"
    assert card["mine"] is False, "seeing your team's work is not holding it"


def test_a_managers_whole_board_is_not_their_plate(client, auth, db, lead_user, make_user):
    """An AM sees every card; `mine` must stay the ownership question or the Overview's "open tasks"
    tile becomes a company-wide total on one person's morning page."""
    am = make_user(C.ROLE_ACCOUNT_MANAGER, name="Leo")
    t = _task(db, assigned_to_id=lead_user.id)
    auth(am)
    assert _card(client, t.id)["mine"] is False


def test_creating_a_card_does_not_make_it_mine_once_delegated(client, auth, db, team,
                                                              lead_user, make_user):
    """The creator tag grants a team lead SIGHT of what they raised — never ownership of it."""
    boss = make_user(C.ROLE_TEAM_LEAD, team_id=team.id, name="Lead")
    t = _task(db, assigned_to_id=lead_user.id, created_by_id=boss.id)
    auth(boss)
    assert _card(client, t.id)["mine"] is False


# --- absent, never faked -------------------------------------------------------------------------

def test_the_profile_card_omits_the_viewer_relative_fields(client, auth, db, me, make_user):
    """`GET /api/people/{id}` lists that PERSON's tasks, where "mine" answers nothing. The keys are
    absent rather than a hardcoded false — a false would be a claim, and the wrong one."""
    admin = make_user(C.ROLE_ADMIN, name="Maria")
    _task(db, assigned_to_id=me.id, status=C.TASK_TODO)
    auth(admin)
    r = client.get(f"/api/people/{me.id}")
    assert r.status_code == 200
    cards = r.json()["tasks"]
    assert cards, "the profile lists this person's open work"
    assert "mine" not in cards[0]
    assert "my_slots" not in cards[0]

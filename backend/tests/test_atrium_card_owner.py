"""An Atrium client card must show WHO HOLDS IT on the board, not "Unassigned" (2026-08-05).

The bug: `as_board_card` hardcoded `assignee: None`, so a client card whose **Lead** was set in
Atrium rendered "Unassigned" on Sentinel's board — while opening that same card showed
"Lead: Charles". Two surfaces reading the same card, disagreeing about whether anyone owns it.

The cause was an asymmetry in the bridge: Atrium's LIST payload carries `lead_id` (a roster email)
and only its DETAIL payload resolved names, so the board genuinely had no name to print and fell
through to the empty state. "Absent, never faked" was being applied to the wrong field — not
inventing a Sentinel **user id** is right; hiding the **name** is not.

What is pinned here:

* the lead reaches the CARD, from a resolved name or (fallback) from the email;
* `assigned_to_id` stays **None** — that is what keeps these cards out of every assignee-keyed
  filter and off employees' boards, and nothing may join on an Atrium owner;
* the card and the drawer cannot drift again, because both derive from `as_board_card`.
"""
from __future__ import annotations

from app.services import atrium_tasks


def _list_payload(**over):
    """What Atrium's /api/internal/tasks sends for one card."""
    p = {
        "atrium_id": "rooming-house:tk_4", "task_id": "tk_4", "client_key": "rooming-house",
        "client_name": "Rooming House Experts", "title": "ActiveCampaign manual list fix",
        "status": "In Progress", "priority": "Medium", "client_facing": True,
    }
    p.update(over)
    return p


# --- the reported bug ----------------------------------------------------------------------------

def test_the_lead_reaches_the_card_from_a_resolved_name():
    card = atrium_tasks.as_board_card(_list_payload(lead_id="charles@agora.ph",
                                                    lead_name="Charles Uy"))
    assert card["assignee"]["name"] == "Charles Uy"
    assert card["atrium_lead_name"] == "Charles Uy"


def test_the_lead_reaches_the_card_from_the_EMAIL_when_atrium_sent_no_name():
    """🔴 The path that fixes this WITHOUT waiting on an Atrium deploy — the list payload carried
    only `lead_id` until the same date, and a fail-soft bridge means Sentinel may ship first."""
    card = atrium_tasks.as_board_card(_list_payload(lead_id="charles.uy@agora.ph"))
    assert card["assignee"]["name"] == "Charles Uy"
    assert card["atrium_lead_name"] == "Charles Uy"


def test_a_genuinely_unowned_client_card_still_reads_unassigned():
    """The empty state has to survive — it was the WRONG answer, not a wrong feature."""
    card = atrium_tasks.as_board_card(_list_payload())
    assert card["assignee"] is None
    assert card["atrium_lead_name"] == ""


# --- what must NOT change ------------------------------------------------------------------------

def test_assigned_to_id_stays_none_so_nothing_joins_on_an_atrium_owner():
    """🔴 The load-bearing half. An Atrium owner is a roster email, not a Sentinel user: every filter
    keyed on `assigned_to_id` must keep excluding these cards, which is what stops them landing on
    employees' boards (the July 2026 regression) and in the per-person rollups."""
    card = atrium_tasks.as_board_card(_list_payload(lead_id="charles@agora.ph",
                                                    lead_name="Charles Uy"))
    assert card["assigned_to_id"] is None
    assert card["assignee"]["id"] is None, "an id here would be a fake Sentinel user"
    assert card["assigned_team_id"] is None


def test_support_names_fall_back_to_emails_too():
    card = atrium_tasks.as_board_card(_list_payload(support_ids=["ian@agora.ph", "mae.cruz@agora.ph"]))
    assert card["atrium_support_names"] == ["Ian", "Mae Cruz"]
    # Resolved names win when Atrium sends them.
    card2 = atrium_tasks.as_board_card(_list_payload(support_ids=["ian@agora.ph"],
                                                     support_names=["Ian Vasquez"]))
    assert card2["atrium_support_names"] == ["Ian Vasquez"]


def test_owner_label_is_a_display_fallback_not_an_identity():
    assert atrium_tasks.owner_label("charles.uy@agora.ph") == "Charles Uy"
    assert atrium_tasks.owner_label("mae_cruz@agora.ph") == "Mae Cruz"
    assert atrium_tasks.owner_label("jo-anne@agora.ph") == "Jo Anne"
    assert atrium_tasks.owner_label("") == ""
    assert atrium_tasks.owner_label(None) == ""


# --- the card and the drawer must agree ----------------------------------------------------------

def test_the_drawer_and_the_card_report_the_same_owner():
    """They were derived in two places and disagreed — that IS the bug. `as_task_detail` builds on
    `as_board_card`, so one derivation now feeds both."""
    task = _list_payload(lead_id="charles@agora.ph", lead_name="Charles Uy",
                         support_ids=["ian@agora.ph"], support_names=["Ian Vasquez"],
                         department="acquisition", department_label="Acquisition")
    card = atrium_tasks.as_board_card(task)
    detail = atrium_tasks.as_task_detail({"task": task, "roster": [], "departments": []})
    assert detail["atrium_lead_name"] == card["atrium_lead_name"] == "Charles Uy"
    assert detail["atrium_support_names"] == card["atrium_support_names"] == ["Ian Vasquez"]
    assert detail["atrium_lead_id"] == card["atrium_lead_id"] == "charles@agora.ph"
    # And the drawer's edit form still gets the picker's current value.
    assert detail["atrium_department"] == "acquisition"

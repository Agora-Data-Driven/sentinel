"""`campaign` reaches the BOARD CARD, on both kinds of card, from exactly one place (2026-08-11).

Why this file exists. `campaign` is the optional grouping field (docs/TASKBOARD_REBUILD.md §7), and
§4 of the Sentinel task-placement guidelines makes it load-bearing: once a campaign has launched,
every new request is deliberately its OWN one-line card, so `campaign` is the only thing that still
connects them. It was serialized into `task_detail` / `as_task_detail` alone — so the board could
neither search nor group by it, and a grouping field that only the drawer receives groups nothing.

Three things are pinned, and the third is the one that will otherwise regress:

* a Sentinel row publishes `campaign` on its CARD (`serializers.task_card`);
* an ATRIUM client card publishes it too (`atrium_tasks.as_board_card`) — the board's filter and its
  search read one field across both kinds of card, and a key missing from one of them is falsy, which
  is precisely how `mine` silently dropped every client card until 2026-08-06 (AGENTS.md §5);
* neither DETAIL mapper re-derives it. Both build on the card mapper, and two derivations of one
  field is how this board's card and drawer came to disagree about an Atrium card's owner.

The legacy-duplicate half of this feature (`campaign == title` on every task created before
2026-08-04, deliberately never backfilled) is suppressed in the FRONTEND, in `campaignOf` — the rows
really do hold that value and the API must keep reporting it honestly.
"""
from __future__ import annotations

from app import serializers
from app.models import Client, Task
from app.services import atrium_tasks


def _atrium_payload(**over):
    """What Atrium's /api/internal/tasks sends for one card."""
    p = {
        "atrium_id": "stratos:tk_9", "task_id": "tk_9", "client_key": "stratos",
        "client_name": "Stratos", "title": "Analyze lead performance",
        "status": "In Progress", "priority": "Medium",
    }
    p.update(over)
    return p


# --- a Sentinel row -------------------------------------------------------------------------------

def test_the_card_carries_the_campaign(db):
    t = Task(title="Increase daily budget", campaign="Stratos", status="To Do")
    db.add(t)
    db.commit()

    assert serializers.task_card(t, db)["campaign"] == "Stratos"


def test_a_task_in_no_campaign_reports_None_not_a_blank_string(db):
    """The column is nullable and the API says so. `campaignOf` in taskboard.js treats both as
    'no campaign', but inventing a "" here would make the field look set to anything else reading it."""
    t = Task(title="Monthly performance report", status="To Do")
    db.add(t)
    db.commit()

    assert serializers.task_card(t, db)["campaign"] is None


def test_the_detail_does_not_re_derive_it(db, monkeypatch):
    """🔴 `task_detail` builds on `task_card`, so it must INHERIT this field rather than map it
    again. Two derivations of one value is the bug pattern AGENTS.md §2 records for the Atrium
    owner: they agree until somebody edits one of them.

    Asserted by making the card mapper the only possible source — stub its answer and the detail must
    carry the stub. A second `"campaign": t.campaign` in `task_detail` would overwrite it and fail.
    """
    t = Task(title="Increase daily budget", campaign="Stratos", status="To Do")
    db.add(t)
    db.commit()
    assert serializers.task_detail(t, db)["campaign"] == "Stratos"

    real = serializers.task_card
    monkeypatch.setattr(serializers, "task_card",
                        lambda *a, **k: {**real(*a, **k), "campaign": "FROM THE CARD MAPPER"})
    assert serializers.task_detail(t, db)["campaign"] == "FROM THE CARD MAPPER"


def test_the_campaign_survives_a_client_being_attached(db):
    """The two fields are independent: a campaign belongs to a client, but the naming rule (§5) is
    that the CLIENT is shown above the title and the campaign beside it — neither replaces the other."""
    c = Client(name="Stratos")
    db.add(c)
    db.flush()
    t = Task(title="Refresh static ads", campaign="Stratos Q3", client_id=c.id, status="To Do")
    db.add(t)
    db.commit()

    card = serializers.task_card(t, db)
    assert card["client_name"] == "Stratos"
    assert card["campaign"] == "Stratos Q3"


# --- an Atrium client card ------------------------------------------------------------------------

def test_an_atrium_card_carries_the_campaign_too():
    """🔴 One field, both kinds of card. The board's campaign filter is a single client-side test;
    if only Sentinel rows carried the key, picking a campaign would silently drop every client card
    in it — the same one-surface-disagrees split `mine` had until 2026-08-06."""
    card = atrium_tasks.as_board_card(_atrium_payload(campaign="Stratos"))
    assert card["campaign"] == "Stratos"


def test_an_atrium_card_with_no_campaign_reports_a_blank_string():
    """Atrium's payload is strings, and every other absent field in this mapper comes back "" —
    matching the module's own convention matters more than matching Sentinel's None."""
    assert atrium_tasks.as_board_card(_atrium_payload())["campaign"] == ""


def test_the_atrium_detail_inherits_it_from_the_card_mapper(monkeypatch):
    """`as_task_detail` calls `as_board_card`; it must not map this field a second time. Same proof as
    the Sentinel half: stub the card mapper and the drawer has to carry the stub's value."""
    payload = {"task": _atrium_payload(campaign="Stratos")}
    assert atrium_tasks.as_task_detail(payload)["campaign"] == "Stratos"

    real = atrium_tasks.as_board_card
    monkeypatch.setattr(atrium_tasks, "as_board_card",
                        lambda *a, **k: {**real(*a, **k), "campaign": "FROM THE CARD MAPPER"})
    assert atrium_tasks.as_task_detail(payload)["campaign"] == "FROM THE CARD MAPPER"

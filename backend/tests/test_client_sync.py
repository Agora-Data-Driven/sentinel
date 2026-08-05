"""Mirroring ATRIUM's client registry into Sentinel (`services/client_sync`, 2026-08-05).

**The division of ownership, by owner decision:** Sentinel owns EMPLOYEES; **Atrium owns CLIENTS.**
Sentinel's `clients` table was maintained by hand in Manage → Clients, which made it a second source
of truth for something Atrium already knew — and the two drifted in the field that matters:
`atrium_client_id` is the BRIDGE KEY (`resolve_client`, `task_bridge`, `board_mirror`, and
`task_adoption`, which REFUSES to run without it). Every one of those failures started as somebody
not typing a workspace key into a form.

The properties pinned here, in rough order of how much damage getting them wrong would do:

1. 🔴 **An empty or failed answer is REFUSED.** Deactivation is driven by absence, so "Atrium didn't
   answer" must never read as "Atrium has no clients" — that confusion would switch off every client
   in the estate in one pass.
2. 🔴 **Orphans are DEACTIVATED, never deleted.** Deleting NULLs `Task.client_id` on every past task
   and blanks that client's reporting.
3. An unlinked client whose NAME unambiguously matches gets linked; an ambiguous one does not.
4. The write routes are GONE — from `manage.py` *and* from `meta.py`, which had a second one.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app import constants as C
from app.models import Client, Task
from app.services import atrium_tasks, client_sync


def _atrium(monkeypatch, rows, err=""):
    monkeypatch.setattr(atrium_tasks, "fetch_clients", lambda: (rows, err))


def _row(key, name, email=""):
    return {"key": key, "name": name, "contact_email": email}


# --- 1. 🔴 refuse to act on an answer we don't trust ---------------------------------------------

def test_a_bridge_failure_changes_NOTHING(db, monkeypatch):
    """The whole estate would otherwise be deactivated by one timeout."""
    db.add(Client(name="Rooming House", atrium_client_id="rooming-house"))
    db.commit()
    _atrium(monkeypatch, [], "Atrium didn't answer the client list — nothing was changed.")
    report = client_sync.sync(db)
    assert report["ok"] is False
    assert report["error"]
    assert db.execute(select(Client)).scalars().all()[0].is_active is True


def test_an_EMPTY_list_is_refused_even_without_an_error(db, monkeypatch):
    """🔴 A registry that reads empty is a storage problem, not news. Absence drives deactivation, so
    a zero-length list is indistinguishable from a silent outage and must not be acted on."""
    db.add(Client(name="Rooming House", atrium_client_id="rooming-house"))
    db.commit()
    _atrium(monkeypatch, [])
    report = client_sync.sync(db)
    assert report["ok"] is False
    assert "deactivate every client" in report["error"]


# --- 2. 🔴 orphans are switched off, not deleted --------------------------------------------------

def test_a_client_atrium_dropped_is_deactivated_and_keeps_its_tasks(db, monkeypatch):
    gone = Client(name="Departed Co", atrium_client_id="departed")
    db.add(gone)
    db.commit()
    db.add(Task(title="Work we did for them", client_id=gone.id, status=C.TASK_COMPLETED))
    db.commit()

    _atrium(monkeypatch, [_row("rooming-house", "Rooming House Experts")])
    report = client_sync.sync(db)
    assert report["ok"] is True
    assert report["deactivated"] == 1
    db.refresh(gone)
    assert gone.is_active is False
    assert gone.id is not None, "the row survives"
    task = db.execute(select(Task)).scalars().first()
    assert task.client_id == gone.id, "history keeps its client — deleting would blank the reports"


def test_a_client_that_comes_back_is_reactivated(db, monkeypatch):
    c = Client(name="Rooming House", atrium_client_id="rooming-house", is_active=False)
    db.add(c)
    db.commit()
    _atrium(monkeypatch, [_row("rooming-house", "Rooming House")])
    report = client_sync.sync(db)
    assert report["reactivated"] == 1
    db.refresh(c)
    assert c.is_active is True


# --- 3. upsert + the name-match adoption ---------------------------------------------------------

def test_a_new_atrium_client_is_created_and_linked(db, monkeypatch):
    _atrium(monkeypatch, [_row("honey-tribe", "Honey Tribe", "hi@honeytribe.com")])
    report = client_sync.sync(db)
    assert report["created"] == 1
    c = db.execute(select(Client)).scalars().one()
    assert c.atrium_client_id == "honey-tribe"
    assert c.name == "Honey Tribe"
    assert c.contact_email == "hi@honeytribe.com"


def test_an_unlinked_client_is_ADOPTED_by_an_unambiguous_name_match(db, monkeypatch):
    """🔴 The migration path for every client already in Sentinel. Writes down the link the board was
    already inferring at read time (`atrium_tasks.resolve_client`'s name fallback) — so nobody has to
    hand-type a workspace key, which is the whole point of removing the form."""
    existing = Client(name="Rooming House Experts")          # no atrium_client_id
    db.add(existing)
    db.commit()
    _atrium(monkeypatch, [_row("rooming-house", "Rooming House Experts")])
    report = client_sync.sync(db)
    assert report["linked"] == 1
    assert report["created"] == 0, "it must not create a duplicate of a client already here"
    db.refresh(existing)
    assert existing.atrium_client_id == "rooming-house"


def test_an_AMBIGUOUS_name_is_not_linked(db, monkeypatch):
    """Two unlinked clients with the same name: linking the wrong one would publish one client's work
    onto another client's board. Same refuse-to-guess rule as `atrium_identity`."""
    db.add_all([Client(name="Acme"), Client(name="Acme (old)")])
    db.commit()
    _atrium(monkeypatch, [_row("acme", "Acme"), _row("acme-2", "Acme")])
    report = client_sync.sync(db)
    # The first Atrium row links to the one exact-name match; the second finds no free exact match
    # and is created under a disambiguated name rather than stealing the same row.
    assert report["linked"] == 1
    assert report["created"] == 1
    names = {c.name for c in db.execute(select(Client)).scalars().all()}
    assert "Acme (acme-2)" in names, "the unique constraint on Client.name is respected"


def test_a_rename_in_atrium_follows_through(db, monkeypatch):
    c = Client(name="Old Name", atrium_client_id="rooming-house")
    db.add(c)
    db.commit()
    _atrium(monkeypatch, [_row("rooming-house", "Rooming House Experts")])
    client_sync.sync(db)
    db.refresh(c)
    assert c.name == "Rooming House Experts"


def test_the_sync_is_idempotent(db, monkeypatch):
    _atrium(monkeypatch, [_row("honey-tribe", "Honey Tribe")])
    first = client_sync.sync(db)
    second = client_sync.sync(db)
    assert first["created"] == 1
    assert second["created"] == 0 and second["updated"] == 0 and second["deactivated"] == 0


def test_pending_link_report_names_what_the_bridge_cannot_address(db):
    db.add_all([Client(name="Linked", atrium_client_id="linked"), Client(name="Orphan")])
    db.commit()
    names = [c["name"] for c in client_sync.pending_link_report(db)]
    assert names == ["Orphan"]


# --- 4. the write routes are gone ----------------------------------------------------------------

def test_the_manage_client_write_routes_are_removed(client, make_user, auth):
    """🔴 A client row created here had no `atrium_client_id` — the exact state that makes adoption
    refuse to run and Send to Atrium unable to address a workspace.

    405 for POST (the collection still answers GET) and 404 for the per-id verbs (that path is gone
    entirely). Asserting the exact codes on purpose: a 200 here would mean somebody re-added a writer.
    """
    auth(make_user(C.ROLE_SUPER_ADMIN))
    assert client.post("/api/manage/clients", json={"name": "Hand-made"}).status_code == 405
    assert client.patch("/api/manage/clients/1", json={"name": "x"}).status_code == 404
    assert client.delete("/api/manage/clients/1").status_code == 404


def test_the_second_client_create_route_is_removed_too(client, make_user, auth):
    """The quieter of the two: `POST /api/clients` (the meta router, prefix `/api`) let any AM mint an
    UNLINKED client straight from the New Task form's picker."""
    auth(make_user(C.ROLE_ACCOUNT_MANAGER))
    assert client.post("/api/clients", json={"name": "Hand-made"}).status_code == 405


def test_the_picker_hides_a_client_atrium_no_longer_lists(client, db, make_user, auth):
    """Offering it would let somebody file fresh work against a client that has left."""
    db.add_all([Client(name="Live", atrium_client_id="live"),
                Client(name="Departed", atrium_client_id="departed", is_active=False)])
    db.commit()
    auth(make_user(C.ROLE_ACCOUNT_MANAGER))
    names = {c["name"] for c in client.get("/api/clients").json()}
    assert names == {"Live"}


def test_manage_can_still_SEE_an_inactive_client(client, db, make_user, auth):
    """The read-only pane shows them (with a 'Not in Atrium' pill) — hiding them entirely is how a
    sync problem becomes invisible."""
    db.add(Client(name="Departed", atrium_client_id="departed", is_active=False))
    db.commit()
    auth(make_user(C.ROLE_SUPER_ADMIN))
    assert client.get("/api/manage/clients").json() == []
    assert len(client.get("/api/manage/clients?include_inactive=1").json()) == 1


@pytest.mark.parametrize("role", [C.ROLE_EMPLOYEE, C.ROLE_TEAM_LEAD, C.ROLE_ACCOUNT_MANAGER])
def test_the_sync_route_stays_super_admin_only(client, make_user, auth, role):
    auth(make_user(role))
    assert client.post("/api/manage/clients/sync").status_code == 403

"""Publishing a Sentinel task to a client, and keeping that client's card current.

These pin the fix for the defect in docs/TASKBOARD_REBUILD.md §1.2: `/send-to-atrium` used to set
`atrium_visible = True`, write an AtriumApproval row and create NOTHING in Atrium, so an AM got a
success toast, the drawer said "✓ In Atrium", and the client's Tasks tab stayed empty forever.

What must stay true:

* a share MINTS a real card and stores its id — no id, not shared;
* a bridge failure is LOUD (502 + the reason on the row), never a silent success;
* only the client-safe subset crosses — assignee, team, priority, charge, internal notes and every
  step's "done when" stay in Sentinel;
* a change to a client-visible field re-pushes; an internal-only change does not;
* the pre-fix rows are reported for a human, never bulk-published (D15).

The transport is stubbed (test_atrium_bridge.py covers signing/mapping).
"""
from __future__ import annotations

from datetime import date

import pytest

from app import constants as C
from app.models import Client, Task
from app.services import atrium_tasks


@pytest.fixture
def linked_client(db):
    """A Sentinel client with its Atrium workspace linked — without the link there is nowhere
    to publish to, which is itself a tested failure mode below."""
    c = Client(name="Honey Tribe", atrium_client_id="honeytribe")
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


@pytest.fixture
def task(db, linked_client, make_team):
    team = make_team(name="Acquisition")
    t = Task(
        title="Spring drop — Meta campaign",
        client_id=linked_client.id,
        assigned_team_id=team.id,
        status=C.TASK_IN_PROGRESS,
        priority="Urgent",
        due_date=date(2026, 8, 19),
        service_charge="980",
        internal_notes="Watching CPL before we scale.",
        client_facing_notes="Creatives are in production.",
        maintasks_json=(
            '[{"id":"m1","title":"Campaign build","assignee_id":7,'
            '"subs":[{"id":"s1","text":"Audience research","done":true,"assignee_id":7,'
            '"dod":"Sheet linked on the card"},'
            '{"id":"s2","text":"Load creatives","done":false,"assignee_id":9,'
            '"dod":"Every approved asset loaded"}]}]'
        ),
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def _capture_add(monkeypatch, task_id="t_ab12cd", err=""):
    """Stub task-add, recording the payload it was handed."""
    seen: dict = {}

    def _add(client_key, title, **kw):
        seen["client_key"] = client_key
        seen["title"] = title
        seen.update(kw)
        return (task_id, err)

    monkeypatch.setattr(atrium_tasks, "add_task", _add)
    return seen


def _capture_edit(monkeypatch, err=""):
    seen: dict = {}

    def _edit(client_key, atrium_task_id, fields, actor=""):
        seen["client_key"] = client_key
        seen["task_id"] = atrium_task_id
        seen["fields"] = fields
        seen["actor"] = actor
        return ({}, err)

    monkeypatch.setattr(atrium_tasks, "edit_task", _edit)
    return seen


def _capture_move(monkeypatch, ok=True, err=""):
    seen: dict = {}

    def _move(client_key, atrium_task_id, stage, actor=""):
        seen["client_key"] = client_key
        seen["task_id"] = atrium_task_id
        seen["stage"] = stage
        return (ok, err)

    monkeypatch.setattr(atrium_tasks, "move_task", _move)
    return seen


# --- publishing ------------------------------------------------------------------------------

def test_sharing_mints_a_card_and_stores_its_id(client, auth, make_user, db, task, monkeypatch):
    """The whole fix: a share creates a real card, and the row remembers which one."""
    auth(make_user(C.ROLE_ACCOUNT_MANAGER))
    added = _capture_add(monkeypatch, task_id="t_ab12cd")
    _capture_edit(monkeypatch)

    r = client.post(f"/api/tasks/{task.id}/send-to-atrium")
    assert r.status_code == 200
    assert r.json()["atrium_task_id"] == "t_ab12cd"

    db.expire_all()
    row = db.get(Task, task.id)
    assert row.atrium_task_id == "t_ab12cd"     # ← the id that used to be thrown away
    assert row.atrium_visible is True
    assert row.atrium_sync_error is None
    # it went to the client's own workspace, as the client's card
    assert added["client_key"] == "honeytribe"
    assert added["client_facing"] is True
    assert added["stage"] == "in_progress"      # mapped from our status, not sent raw


def test_a_failed_share_is_loud_and_leaves_the_row_unshared(client, auth, make_user, db, task, monkeypatch):
    """The bug inverted: no card, no claim. The reason is returned AND recorded."""
    auth(make_user(C.ROLE_ACCOUNT_MANAGER))
    _capture_add(monkeypatch, task_id="", err="Atrium rejected that card.")

    r = client.post(f"/api/tasks/{task.id}/send-to-atrium")
    assert r.status_code == 502
    assert "rejected" in r.json()["detail"]

    db.expire_all()
    row = db.get(Task, task.id)
    assert row.atrium_task_id is None
    assert row.atrium_visible is False          # never claim a share that did not happen
    assert row.atrium_sync_error                # the row knows why


def test_an_ok_with_no_task_id_counts_as_failure(db, task, make_user, monkeypatch):
    """A card we can never address again would recreate the same lie one row at a time."""
    from app.services import task_bridge

    monkeypatch.setattr(atrium_tasks, "add_task", lambda *a, **k: ("", "no id returned"))
    ok, err = task_bridge.publish(db, task, make_user(C.ROLE_ACCOUNT_MANAGER))
    assert ok is False and err
    assert task.atrium_task_id is None


def test_sharing_without_an_atrium_client_link_explains_itself(client, auth, make_user, db, monkeypatch):
    auth(make_user(C.ROLE_ACCOUNT_MANAGER))
    unlinked = Client(name="No Workspace Yet")
    db.add(unlinked)
    db.commit()
    t = Task(title="orphan", client_id=unlinked.id, status=C.TASK_TODO)
    db.add(t)
    db.commit()
    db.refresh(t)
    called = {"n": 0}
    monkeypatch.setattr(atrium_tasks, "add_task",
                        lambda *a, **k: (called.__setitem__("n", called["n"] + 1), ("x", ""))[1])

    r = client.post(f"/api/tasks/{t.id}/send-to-atrium")
    assert r.status_code == 502
    assert "no Atrium client" in r.json()["detail"]
    assert called["n"] == 0                     # never guess a workspace key


def test_sharing_twice_does_not_create_a_second_card(client, auth, make_user, db, task, monkeypatch):
    auth(make_user(C.ROLE_ACCOUNT_MANAGER))
    adds = {"n": 0}

    def _add(*a, **k):
        adds["n"] += 1
        return ("t_once", "")

    monkeypatch.setattr(atrium_tasks, "add_task", _add)
    _capture_edit(monkeypatch)

    assert client.post(f"/api/tasks/{task.id}/send-to-atrium").status_code == 200
    second = client.post(f"/api/tasks/{task.id}/send-to-atrium")
    assert second.status_code == 200
    assert second.json()["already_shared"] is True
    assert adds["n"] == 1


def test_only_managers_can_share(client, auth, make_user, task):
    auth(make_user(C.ROLE_TEAM_LEAD))
    assert client.post(f"/api/tasks/{task.id}/send-to-atrium").status_code == 403


# --- the client-safe split -------------------------------------------------------------------

def test_the_push_carries_client_safe_fields_only(db, task, make_user, monkeypatch):
    """The bridge payload is the narrowest place to enforce the split, so pin it there."""
    from app.services import task_bridge

    fields = task_bridge.client_safe_fields(task, db)
    # `start_date` joined the subset on 2026-08-03 (M5) — a schedule fact Atrium renders as the
    # client's Started → Going live timeline. `hold_reason` did NOT, and never will.
    assert set(fields) == {"title", "client_note", "due_date", "start_date", "deliverable_url",
                           "maintasks"}
    assert set(fields) == set(task_bridge.SAFE), "SAFE and the builder must not drift apart"

    blob = repr(fields)
    for internal in ("980", "Watching CPL", "assignee_id", "dod", "Sheet linked", "Urgent"):
        assert internal not in blob, f"{internal!r} must never cross the bridge"

    # the breakdown reaches the client as phases: a name, and each step's text + done
    phase = fields["maintasks"][0]
    assert phase["text"] == "Campaign build"
    assert phase["subs"][0] == {"text": "Audience research", "done": True}


def test_editing_a_client_visible_field_repushes(client, auth, make_user, db, task, monkeypatch):
    auth(make_user(C.ROLE_ACCOUNT_MANAGER))
    _capture_add(monkeypatch)
    edits = _capture_edit(monkeypatch)
    client.post(f"/api/tasks/{task.id}/send-to-atrium")
    edits.clear()

    r = client.patch(f"/api/tasks/{task.id}", json={"client_facing_notes": "Now live on the 19th."})
    assert r.status_code == 200
    assert edits["fields"]["client_note"] == "Now live on the 19th."


def test_an_internal_only_edit_does_not_touch_the_client_card(client, auth, make_user, db, task, monkeypatch):
    """A priority change is nobody's business but ours — and must not spend a round trip."""
    auth(make_user(C.ROLE_ACCOUNT_MANAGER))
    _capture_add(monkeypatch)
    edits = _capture_edit(monkeypatch)
    client.post(f"/api/tasks/{task.id}/send-to-atrium")
    edits.clear()

    r = client.patch(f"/api/tasks/{task.id}", json={"internal_notes": "still watching CPL",
                                                   "priority": "Low"})
    assert r.status_code == 200
    assert edits == {}


def test_moving_a_shared_task_moves_the_clients_card(client, auth, make_user, db, task, monkeypatch):
    auth(make_user(C.ROLE_ACCOUNT_MANAGER))
    _capture_add(monkeypatch)
    _capture_edit(monkeypatch)
    moves = _capture_move(monkeypatch)
    client.post(f"/api/tasks/{task.id}/send-to-atrium")

    # Completing needs an approval since 2026-08-03 (decision D5, tests/test_task_workflow.py).
    # This test is about the STAGE push, so satisfy the gate rather than re-testing it.
    task.review_state = C.REVIEW_APPROVED
    db.commit()
    r = client.patch(f"/api/tasks/{task.id}/status", json={"status": C.TASK_COMPLETED})
    assert r.status_code == 200
    assert moves["stage"] == "completed"
    assert moves["task_id"] == "t_ab12cd"


def test_a_failed_push_marks_the_card_stale_and_can_be_retried(client, auth, make_user, db, task, monkeypatch):
    auth(make_user(C.ROLE_ACCOUNT_MANAGER))
    _capture_add(monkeypatch)
    _capture_edit(monkeypatch)
    client.post(f"/api/tasks/{task.id}/send-to-atrium")

    # the bridge goes down mid-edit: the edit still succeeds, the client's card is flagged stale
    _capture_edit(monkeypatch, err="Atrium didn't confirm that edit in time")
    r = client.patch(f"/api/tasks/{task.id}", json={"title": "Spring drop — v2"})
    assert r.status_code == 200
    db.expire_all()
    assert db.get(Task, task.id).atrium_sync_error

    # and it is retryable, which clears the flag
    _capture_edit(monkeypatch)
    _capture_move(monkeypatch)
    r = client.post(f"/api/tasks/{task.id}/atrium-retry")
    assert r.status_code == 200
    db.expire_all()
    assert db.get(Task, task.id).atrium_sync_error is None


def test_the_board_can_tell_a_real_share_from_the_old_flag(client, auth, make_user, db, task):
    """`atrium_visible` alone is the pre-fix lie, so the serializer exposes the real state too."""
    auth(make_user(C.ROLE_ACCOUNT_MANAGER))
    task.atrium_visible = True          # a pre-fix row: claims shared, points at nothing
    db.commit()

    d = client.get(f"/api/tasks/{task.id}").json()
    assert d["atrium_visible"] is True
    assert d["atrium_shared"] is False  # ← what the UI must believe
    assert d["atrium_task_id"] is None


# --- the reconcile backlog (D15) -------------------------------------------------------------

def test_stale_shares_are_reported_not_published(client, auth, make_user, db, task, linked_client):
    auth(make_user(C.ROLE_ACCOUNT_MANAGER))
    task.atrium_visible = True
    db.commit()

    rows = client.get("/api/tasks/atrium/stale-shares").json()
    assert [r["id"] for r in rows] == [task.id]
    assert rows[0]["client_name"] == "Honey Tribe"
    assert rows[0]["atrium_client_key"] == "honeytribe"


def test_a_real_share_is_not_in_the_backlog(client, auth, make_user, db, task, monkeypatch):
    auth(make_user(C.ROLE_ACCOUNT_MANAGER))
    _capture_add(monkeypatch)
    _capture_edit(monkeypatch)
    client.post(f"/api/tasks/{task.id}/send-to-atrium")

    assert client.get("/api/tasks/atrium/stale-shares").json() == []


def test_clearing_a_stale_claim_leaves_the_task_internal(client, auth, make_user, db, task):
    auth(make_user(C.ROLE_ACCOUNT_MANAGER))
    task.atrium_visible = True
    db.commit()

    assert client.post(f"/api/tasks/{task.id}/atrium-clear-share").status_code == 200
    db.expire_all()
    row = db.get(Task, task.id)
    assert row.atrium_visible is False and row.atrium_task_id is None


def test_a_genuinely_shared_task_cannot_be_cleared_here(client, auth, make_user, db, task, monkeypatch):
    auth(make_user(C.ROLE_ACCOUNT_MANAGER))
    _capture_add(monkeypatch)
    _capture_edit(monkeypatch)
    client.post(f"/api/tasks/{task.id}/send-to-atrium")

    r = client.post(f"/api/tasks/{task.id}/atrium-clear-share")
    assert r.status_code == 409

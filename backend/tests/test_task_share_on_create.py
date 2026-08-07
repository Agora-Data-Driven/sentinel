"""Share-on-create defaults ON for a client-facing task (decision D6, WP 5.2).

The client should watch the work cross their board from day one, not meet it already finished. So
a task that HAS a client is published to Atrium as part of its creation, unless the AM explicitly
opts that one task out.

`share_with_client` is tri-state on purpose:

* absent / null -> "decide for me": share when the task has a client;
* True          -> share (still needs a client and the bridge permission);
* False         -> explicitly keep it internal.

A plain bool default could not tell "the caller said no" from "the caller said nothing", and the
frontend only sends the field on create — so absent must NOT collapse to False.

🔴 A bridge failure is REPORTED, never raised: the task is committed and perfectly valid unshared,
and failing the create would throw away the AM's typing over an outage somewhere else. The reason
lands on `atrium_sync_error` and Retry is one click.

This only became safe once WP 0.1/0.2 made publishing real — before them it set a flag that
pointed at nothing (§1.2).
"""
from __future__ import annotations

from unittest.mock import patch

from app import constants as C
from app.models import Client


def _client_row(db, key="acme"):
    row = Client(name="Acme", atrium_client_id=key)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _mk(client, **kw):
    body = {"title": "Launch"}
    body.update(kw)
    return client.post("/api/tasks", json=body)


# --- the default ------------------------------------------------------------------------------

def test_a_task_with_a_client_is_shared_automatically(client, auth, make_user, db):
    auth(make_user(C.ROLE_ADMIN))
    row = _client_row(db)
    with patch("app.services.task_bridge.publish", return_value=(True, "")) as pub:
        r = _mk(client, client_id=row.id)
    assert r.status_code in (200, 201), r.text
    assert pub.called, "a client-facing task must publish on create (D6)"


def test_a_task_with_no_client_is_not_shared(client, auth, make_user):
    # Nothing to share it INTO — publishing would be an error, not a default.
    auth(make_user(C.ROLE_ADMIN))
    with patch("app.services.task_bridge.publish", return_value=(True, "")) as pub:
        _mk(client)
    assert not pub.called


def test_absent_is_not_the_same_as_false(client, auth, make_user, db):
    """The whole reason the field is tri-state."""
    auth(make_user(C.ROLE_ADMIN))
    row = _client_row(db)
    with patch("app.services.task_bridge.publish", return_value=(True, "")) as pub:
        _mk(client, client_id=row.id)                       # field absent
    assert pub.called
    with patch("app.services.task_bridge.publish", return_value=(True, "")) as pub:
        _mk(client, client_id=row.id, share_with_client=None)   # explicit null
    assert pub.called


# --- opting out -------------------------------------------------------------------------------

def test_false_keeps_the_task_internal(client, auth, make_user, db):
    auth(make_user(C.ROLE_ADMIN))
    row = _client_row(db)
    with patch("app.services.task_bridge.publish", return_value=(True, "")) as pub:
        r = _mk(client, client_id=row.id, share_with_client=False)
    assert r.status_code in (200, 201)
    assert not pub.called


def test_true_without_a_client_still_does_not_publish(client, auth, make_user):
    auth(make_user(C.ROLE_ADMIN))
    with patch("app.services.task_bridge.publish", return_value=(True, "")) as pub:
        _mk(client, share_with_client=True)
    assert not pub.called


# --- permission -------------------------------------------------------------------------------

def test_a_role_that_cannot_bridge_never_publishes(client, auth, make_user, db, make_team):
    """Sharing is a manager decision (can_bridge). An employee filing work does not get to make it,
    even though the default would otherwise say yes."""
    team = make_team("Acquisition")
    auth(make_user(C.ROLE_EMPLOYEE, team_id=team.id))
    row = _client_row(db)
    with patch("app.services.task_bridge.publish", return_value=(True, "")) as pub:
        r = _mk(client, client_id=row.id, share_with_client=True)
    assert r.status_code in (200, 201)
    assert not pub.called


# --- failure is reported, not raised ------------------------------------------------------------

def test_a_bridge_failure_does_not_fail_the_create(client, auth, make_user, db):
    auth(make_user(C.ROLE_ADMIN))
    row = _client_row(db)
    with patch("app.services.task_bridge.publish", return_value=(False, "Atrium is down")):
        r = _mk(client, client_id=row.id)
    # 🔴 The task survives. Losing typed work because a different system is unreachable is the
    # failure mode this contract exists to prevent.
    assert r.status_code in (200, 201), r.text
    assert r.json()["title"] == "Launch"


# --- it runs AFTER the response (2026-08-07) -----------------------------------------------------

def test_the_publish_runs_in_its_own_session_and_persists_the_error(client, auth, make_user, db):
    """🔴 The publish moved to a BackgroundTask, so it no longer has the request's session — FastAPI
    tears that down before background tasks run. Opening its own session is what makes the failure
    contract survive the move: without the fresh session + commit, `atrium_sync_error` would be
    written to a closed session and thrown away, and the drawer's "stale, click Retry" pill would
    have nothing behind it.

    The bridge is unconfigured under test, so `publish` really fails here — no mock. That is the
    point: this exercises the whole path, including the commit.
    """
    from app.models import Task

    auth(make_user(C.ROLE_ADMIN))
    row = _client_row(db)
    r = _mk(client, client_id=row.id)
    assert r.status_code in (200, 201), r.text
    # The response itself never reported the publish result, before or after the move.
    assert r.json()["atrium_task_id"] is None

    db.expire_all()                            # read what the BACKGROUND session committed
    task = db.get(Task, r.json()["id"])
    assert task.atrium_sync_error, "the failure must be recorded on the row, not just logged"
    assert task.atrium_task_id is None, "nothing was published, so nothing may claim to be"


def test_a_task_with_no_client_schedules_no_background_work(client, auth, make_user, db):
    """The cheap create stays cheap: no client means no bridge round trip to schedule at all."""
    from app.models import Task

    auth(make_user(C.ROLE_ADMIN))
    r = _mk(client)
    db.expire_all()
    task = db.get(Task, r.json()["id"])
    assert task.atrium_sync_error is None

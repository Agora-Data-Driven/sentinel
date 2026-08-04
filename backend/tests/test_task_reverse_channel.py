"""The reverse channel: a client's words reach the Sentinel row (decision D4, WP 3.5).

Sentinel has pushed cards TO the client since WP 0.1/0.2, but anything the client said back lived
only in Atrium's workspace JSON — so the team found out by re-reading a client's board, which
nobody does. This is the half that makes the projection a conversation instead of a broadcast.

It is also what replaces `atrium_approvals`' three response columns, dropped in WP 0.4: the same
intent, landing where the conversation already lives rather than in a table nothing ever wrote.

What must stay true:

* a client comment lands on the linked task, attributed BY NAME — a client has no `users` row and
  must never need one (shadow accounts would put clients in every people picker);
* a change request ALSO raises `client_changes_open`, which is what puts the pill on the card;
* 🔴 that counter is NOT `review_state` — the internal approval gate (D5). A client must not be
  able to satisfy or block a team lead's sign-off;
* the bridge is idempotent, or a retry would keep climbing the counter and it could never clear;
* only a PUBLISHED card can receive feedback (found by `atrium_task_id`), and a stray id creates
  nothing.
"""
from __future__ import annotations

import hashlib
import hmac
import time

from app import constants as C
from app.config import settings
from app.models import Task, TaskComment

SECRET = "test-internal-secret"


def _sig(purpose: str) -> dict:
    ts = str(int(time.time()))
    return {"X-Academy-Ts": ts,
            "X-Academy-Sig": hmac.new(SECRET.encode(), f"{purpose}:{ts}".encode(),
                                      hashlib.sha256).hexdigest()}


def _published(db, user, **kw):
    body = {"title": "Hero banner", "status": "To Do", "priority": "Medium",
            "created_by_id": user.id, "atrium_task_id": "atrium:acme:t1"}
    body.update(kw)
    t = Task(**body)
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def _send(api, monkeypatch, **body):
    monkeypatch.setattr(settings, "platform_sso_secret", SECRET, raising=False)
    payload = {"atrium_task_id": "atrium:acme:t1", "body": "Can we try it in green?",
               "kind": "comment", "author_name": "Dana (Acme)"}
    payload.update(body)
    return api.post("/api/internal/task-feedback", json=payload, headers=_sig("task-feedback"))


# --- a comment --------------------------------------------------------------------------------

def test_a_client_comment_lands_on_the_task(client, db, monkeypatch, make_user):
    u = make_user(C.ROLE_ADMIN)
    task = _published(db, u)
    r = _send(client, monkeypatch)
    assert r.status_code == 200, r.text
    c = db.query(TaskComment).filter(TaskComment.task_id == task.id).one()
    assert "Can we try it in green?" in c.body


def test_the_client_is_attributed_without_a_user_row(client, db, monkeypatch, make_user):
    u = make_user(C.ROLE_ADMIN)
    _published(db, u)
    _send(client, monkeypatch)
    c = db.query(TaskComment).one()
    assert c.author_id is None            # 🔴 no shadow user account was minted
    assert c.client_author == "Dana (Acme)"


def test_the_thread_marks_a_client_comment_as_theirs(client, db, monkeypatch, make_user, auth):
    u = make_user(C.ROLE_ADMIN)
    task = _published(db, u)
    _send(client, monkeypatch)
    auth(u)
    detail = client.get(f"/api/tasks/{task.id}").json()
    said = detail["comments"][-1]
    assert said["is_client"] is True
    assert said["author"]["name"] == "Dana (Acme)"


# --- a change request -------------------------------------------------------------------------

def test_a_change_request_raises_the_counter(client, db, monkeypatch, make_user):
    u = make_user(C.ROLE_ADMIN)
    task = _published(db, u)
    r = _send(client, monkeypatch, kind="changes", source_ref="c1")
    assert r.json()["open_changes"] == 1
    db.refresh(task)
    assert task.client_changes_open == 1


def test_a_plain_comment_does_not_raise_the_counter(client, db, monkeypatch, make_user):
    u = make_user(C.ROLE_ADMIN)
    task = _published(db, u)
    _send(client, monkeypatch, kind="comment", source_ref="c1")
    db.refresh(task)
    assert task.client_changes_open == 0


def test_a_client_can_never_touch_the_internal_approval_gate(client, db, monkeypatch, make_user):
    """🔴 D5's review_state is a team lead saying "this is done". A client asking for a revision is
    a different fact from a different person; conflating them would let a client satisfy — or
    block — an internal sign-off."""
    u = make_user(C.ROLE_ADMIN)
    task = _published(db, u, review_state="approved")
    _send(client, monkeypatch, kind="changes", source_ref="c1")
    db.refresh(task)
    assert task.review_state == "approved"        # untouched
    assert task.client_changes_open == 1          # counted separately


def test_the_card_reports_open_changes(client, db, monkeypatch, make_user, auth):
    u = make_user(C.ROLE_ADMIN)
    task = _published(db, u)
    _send(client, monkeypatch, kind="changes", source_ref="c1")
    auth(u)
    card = next(t for t in client.get("/api/tasks").json() if t["id"] == task.id)
    assert card["open_changes"] == 1


# --- idempotency + guards -----------------------------------------------------------------------

def test_a_retry_does_not_double_count(client, db, monkeypatch, make_user):
    """Otherwise the pill climbs on every retry and can never be cleared honestly."""
    u = make_user(C.ROLE_ADMIN)
    task = _published(db, u)
    first = _send(client, monkeypatch, kind="changes", source_ref="same-comment")
    again = _send(client, monkeypatch, kind="changes", source_ref="same-comment")
    assert again.json()["duplicate"] is True
    assert first.json()["comment_id"] == again.json()["comment_id"]
    db.refresh(task)
    assert task.client_changes_open == 1
    assert db.query(TaskComment).count() == 1


def test_two_clients_sharing_an_atrium_id_do_not_cross_post(client, db, monkeypatch, make_user):
    """🔴 `atrium_task_id` holds Atrium's RAW id, which is only unique WITHIN a workspace. Without
    the client key narrowing the lookup, one client's feedback could land on another's card."""
    from app.models import Client as ClientRow

    acme = ClientRow(name="Acme", atrium_client_id="acme")
    other = ClientRow(name="Other", atrium_client_id="other")
    db.add_all([acme, other])
    db.commit()
    u = make_user(C.ROLE_ADMIN)
    a_task = _published(db, u, atrium_task_id="t1", client_id=acme.id, title="Acme card")
    o_task = _published(db, u, atrium_task_id="t1", client_id=other.id, title="Other card")

    _send(client, monkeypatch, atrium_task_id="t1", **{"client": "other"},
          kind="changes", source_ref="x1")

    db.refresh(a_task)
    db.refresh(o_task)
    assert o_task.client_changes_open == 1
    assert a_task.client_changes_open == 0, "feedback landed on the wrong client's card"


def test_feedback_for_an_unpublished_card_is_a_404(client, db, monkeypatch, make_user):
    make_user(C.ROLE_ADMIN)
    r = _send(client, monkeypatch, atrium_task_id="atrium:acme:nope")
    assert r.status_code == 404
    assert db.query(TaskComment).count() == 0


def test_an_empty_body_is_rejected(client, db, monkeypatch, make_user):
    u = make_user(C.ROLE_ADMIN)
    _published(db, u)
    assert _send(client, monkeypatch, body="   ").status_code == 400


def test_an_unknown_kind_is_rejected(client, db, monkeypatch, make_user):
    u = make_user(C.ROLE_ADMIN)
    _published(db, u)
    assert _send(client, monkeypatch, kind="approve").status_code == 400


def test_the_channel_is_hmac_gated(client, db, monkeypatch, make_user):
    u = make_user(C.ROLE_ADMIN)
    _published(db, u)
    monkeypatch.setattr(settings, "platform_sso_secret", SECRET, raising=False)
    assert client.post("/api/internal/task-feedback",
                       json={"atrium_task_id": "atrium:acme:t1", "body": "x"}).status_code == 401


# --- resolving ----------------------------------------------------------------------------------

def test_the_team_can_clear_the_flag(client, db, monkeypatch, make_user, auth):
    u = make_user(C.ROLE_ADMIN)
    task = _published(db, u)
    _send(client, monkeypatch, kind="changes", source_ref="c1")
    auth(u)
    r = client.post(f"/api/tasks/{task.id}/resolve-client-changes")
    assert r.status_code == 200
    db.refresh(task)
    assert task.client_changes_open == 0
    # The conversation itself survives — the counter is a flag, not a log.
    assert db.query(TaskComment).count() == 1


def test_resolving_twice_is_a_no_op_success(client, db, make_user, auth):
    """Two people clicking it is a normal race; neither deserves an error."""
    u = make_user(C.ROLE_ADMIN)
    task = _published(db, u)
    auth(u)
    assert client.post(f"/api/tasks/{task.id}/resolve-client-changes").status_code == 200
    assert client.post(f"/api/tasks/{task.id}/resolve-client-changes").status_code == 200


def test_a_viewer_cannot_clear_the_flag(client, db, monkeypatch, make_user, auth):
    u = make_user(C.ROLE_ADMIN)
    task = _published(db, u)
    _send(client, monkeypatch, kind="changes", source_ref="c1")
    auth(make_user("viewer"))
    assert client.post(f"/api/tasks/{task.id}/resolve-client-changes").status_code == 403

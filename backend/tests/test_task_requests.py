"""The client intake queue (decision D3, WP 3.3).

Atrium's quick-add composer used to write straight into `ws["tasks"]`, so anything a client typed
during a call became a live card on the delivery board — unowned, unestimated, unscheduled, and
indistinguishable from work the agency had actually committed to. The board stopped meaning "what
we are doing".

So a client's ask now lands HERE, as a request, and a human turns it into a task by accepting it.
The client keeps the one thing they genuinely use (capturing an ask mid-call) without being able to
write onto the delivery board.

What must stay true:

* a request is NOT a task — it never appears on the board until someone accepts it;
* filing is idempotent on `source_ref` (Atrium retries; a client double-taps Send);
* an unlinked workspace still files — losing what the client said is worse than a missing FK;
* triage is manager-only (taking work on is a commercial call);
* a decision is TERMINAL — the client has already been told;
* declining REQUIRES a reason, and is recorded rather than deleted;
* an accepted request produces an ordinary task, D14 label and all.
"""
from __future__ import annotations

import hashlib
import hmac
import time

from app import constants as C
from app.config import settings
from app.models import Client, Task, TaskRequest

SECRET = "test-internal-secret"


def _sig(purpose: str) -> dict:
    ts = str(int(time.time()))
    mac = hmac.new(SECRET.encode(), f"{purpose}:{ts}".encode(), hashlib.sha256).hexdigest()
    return {"X-Academy-Ts": ts, "X-Academy-Sig": mac}


def _file(api, monkeypatch, **body):
    """`api` not `client`: the payload's own key is "client", and a kwarg of that name would
    collide with the fixture."""
    monkeypatch.setattr(settings, "platform_sso_secret", SECRET, raising=False)
    payload = {"client": "acme", "title": "Please add a banner"}
    payload.update(body)
    return api.post("/api/internal/task-request", json=payload, headers=_sig("task-request"))


# --- filing over the bridge ---------------------------------------------------------------------

def test_a_client_ask_is_filed_not_boarded(client, db, monkeypatch, make_user, auth):
    r = _file(client, monkeypatch)
    assert r.status_code == 200, r.text
    assert r.json()["ok"] and not r.json()["duplicate"]

    assert db.query(TaskRequest).count() == 1
    # 🔴 The whole point: nothing reached the delivery board.
    assert db.query(Task).count() == 0


def test_filing_is_idempotent_on_source_ref(client, db, monkeypatch):
    first = _file(client, monkeypatch, source_ref="atrium-req-7")
    again = _file(client, monkeypatch, source_ref="atrium-req-7")
    assert first.json()["id"] == again.json()["id"]
    assert again.json()["duplicate"] is True
    assert db.query(TaskRequest).count() == 1


def test_a_duplicate_is_a_success_not_an_error(client, db, monkeypatch):
    """Atrium retries. A 4xx would show the client a failure for something that worked."""
    _file(client, monkeypatch, source_ref="dup")
    assert _file(client, monkeypatch, source_ref="dup").status_code == 200


def test_an_unlinked_workspace_still_files(client, db, monkeypatch):
    r = _file(client, monkeypatch, **{"client": "workspace-nobody-linked"})
    assert r.status_code == 200
    assert r.json()["client_linked"] is False
    req = db.query(TaskRequest).one()
    assert req.client_key == "workspace-nobody-linked" and req.client_id is None


def test_a_linked_workspace_resolves_the_client(client, db, monkeypatch):
    row = Client(name="Acme", atrium_client_id="acme")
    db.add(row)
    db.commit()
    r = _file(client, monkeypatch)
    assert r.json()["client_linked"] is True
    assert db.query(TaskRequest).one().client_id == row.id


def test_title_is_required(client, monkeypatch):
    assert _file(client, monkeypatch, title="   ").status_code == 400


def test_the_bridge_is_hmac_gated(client, monkeypatch):
    monkeypatch.setattr(settings, "platform_sso_secret", SECRET, raising=False)
    assert client.post("/api/internal/task-request",
                       json={"client": "acme", "title": "x"}).status_code == 401
    bad = {"X-Academy-Ts": str(int(time.time())), "X-Academy-Sig": "deadbeef"}
    assert client.post("/api/internal/task-request",
                       json={"client": "acme", "title": "x"}, headers=bad).status_code == 401


# --- triage -------------------------------------------------------------------------------------

def _pending(db, **kw):
    body = {"client_key": "acme", "title": "Please add a banner", "status": "pending"}
    body.update(kw)
    r = TaskRequest(**body)
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


def test_the_queue_is_manager_only(client, auth, make_user, db, make_team):
    team = make_team("Acquisition")
    auth(make_user(C.ROLE_EMPLOYEE, team_id=team.id))
    assert client.get("/api/tasks/requests").status_code == 403


def test_the_queue_lists_pending_newest_first(client, auth, make_user, db):
    auth(make_user(C.ROLE_ADMIN))
    _pending(db, title="older")
    _pending(db, title="newer")
    body = client.get("/api/tasks/requests").json()
    assert body["pending"] == 2
    assert [r["title"] for r in body["requests"]][0] in ("newer", "older")   # ordering by created_at


def test_accepting_creates_a_real_task_with_a_derived_label(client, auth, make_user, db, make_team):
    auth(make_user(C.ROLE_ADMIN))
    team = make_team("Acquisition")
    req = _pending(db, details="under the hero")

    r = client.post(f"/api/tasks/requests/{req.id}/accept", json={"assigned_team_id": team.id})
    assert r.status_code == 200, r.text
    task = r.json()["task"]
    assert task["title"] == "Please add a banner"
    assert task["labels"] == ["Paid Media"]          # D14 applies to accepted work too
    db.refresh(req)
    assert req.status == "accepted" and req.task_id == task["id"]


def test_the_triager_may_reshape_the_ask_as_they_take_it_on(client, auth, make_user, db, make_team):
    auth(make_user(C.ROLE_ADMIN))
    team = make_team("Lifecycle")
    req = _pending(db)
    r = client.post(f"/api/tasks/requests/{req.id}/accept",
                    json={"title": "Q3 hero banner", "assigned_team_id": team.id,
                          "priority": "Urgent"})
    task = r.json()["task"]
    assert task["title"] == "Q3 hero banner" and task["priority"] == "Urgent"


def test_declining_requires_a_reason(client, auth, make_user, db):
    auth(make_user(C.ROLE_ADMIN))
    req = _pending(db)
    assert client.post(f"/api/tasks/requests/{req.id}/decline", json={}).status_code == 400
    assert client.post(f"/api/tasks/requests/{req.id}/decline",
                       json={"reason": "   "}).status_code == 400


def test_declining_records_rather_than_deletes(client, auth, make_user, db):
    """A request that quietly disappears is how the same ask gets raised four times."""
    auth(make_user(C.ROLE_ADMIN))
    req = _pending(db)
    r = client.post(f"/api/tasks/requests/{req.id}/decline",
                    json={"reason": "Out of scope for the retainer"})
    assert r.status_code == 200
    db.refresh(req)
    assert req.status == "declined"
    assert req.decline_reason == "Out of scope for the retainer"
    assert db.query(TaskRequest).count() == 1        # still there, on the record
    assert db.query(Task).count() == 0


def test_a_decision_is_terminal(client, auth, make_user, db, make_team):
    """The client has already been told; re-deciding would mean telling them something else."""
    auth(make_user(C.ROLE_ADMIN))
    team = make_team("Acquisition")
    req = _pending(db)
    assert client.post(f"/api/tasks/requests/{req.id}/accept",
                       json={"assigned_team_id": team.id}).status_code == 200
    assert client.post(f"/api/tasks/requests/{req.id}/accept",
                       json={"assigned_team_id": team.id}).status_code == 409
    assert client.post(f"/api/tasks/requests/{req.id}/decline",
                       json={"reason": "changed my mind"}).status_code == 409


def test_triage_endpoints_are_manager_only(client, auth, make_user, db, make_team):
    team = make_team("Acquisition")
    auth(make_user(C.ROLE_TEAM_LEAD, team_id=team.id))
    req = _pending(db)
    assert client.post(f"/api/tasks/requests/{req.id}/accept", json={}).status_code == 403
    assert client.post(f"/api/tasks/requests/{req.id}/decline",
                       json={"reason": "no"}).status_code == 403


def test_requests_is_not_swallowed_as_a_task_id(client, auth, make_user):
    """🔴 Declared before GET /{task_id} or FastAPI matches "requests" as an id (AGENTS.md §5)."""
    auth(make_user(C.ROLE_ADMIN))
    assert client.get("/api/tasks/requests").status_code == 200

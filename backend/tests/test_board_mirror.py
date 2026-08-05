"""The STAFF mirror Atrium's operator console reads (`GET /api/internal/board`).

The bug this exists to prevent coming back: Atrium's `/admin/atrium` Task Board was assembled from
each client's workspace JSON, i.e. from the client-safe projections `task_bridge` pushes. So a task
nobody had shared with a client — the majority of the board — was structurally invisible on a
console whose subtitle claims "every client deliverable across every workspace", and the two systems
disagreed about how much work the agency had.

What must stay true:

* an UNPUBLISHED task appears in the mirror (that is the entire point);
* the column comes from the STAGE, so renaming a status in Manage cannot move a card (D13);
* filed work (`archived`) stays out, matching the board itself;
* people are EMAILS, because Atrium's roster is keyed by email, not by Sentinel user id;
* the shape uses Atrium's own key names, so the console needs no translation layer;
* it is HMAC-gated like every other `/api/internal/*` endpoint, and fails CLOSED.

🔴 And the boundary that matters most: this is a STAFF payload and carries internal fields. The test
that pins the CLIENT side is `test_task_publish.py` / `task_bridge.SAFE` — six fields. If a change
makes these two look alike, the client one is the one that is wrong.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import date

from app import constants as C
from app.config import settings
from app.models import Client, Task, TaskComment, TaskVocabItem
from app.services import board_mirror

SECRET = "test-internal-secret"


def _sig(purpose: str = "board") -> dict:
    ts = str(int(time.time()))
    mac = hmac.new(SECRET.encode(), f"{purpose}:{ts}".encode(), hashlib.sha256).hexdigest()
    return {"X-Academy-Ts": ts, "X-Academy-Sig": mac}


def _client_row(db, name="Honey Tribe", key="honey-tribe"):
    row = Client(name=name, atrium_client_id=key)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _task(db, **kw):
    fields = {"title": "Organic Email Content", "status": C.TASK_TODO, "priority": "Medium"}
    fields.update(kw)
    t = Task(**fields)
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


# --- the bug ------------------------------------------------------------------------------------

def test_unpublished_task_is_in_the_mirror(db):
    """🔴 THE regression. No `atrium_task_id` means no client card — and the console still sees it."""
    c = _client_row(db)
    _task(db, client_id=c.id, title="Never shared with anyone")

    rows = board_mirror.board(db)
    assert len(rows) == 1
    row = rows[0]
    assert row["title"] == "Never shared with anyone"
    # It is honest about the client not being able to see it...
    assert row["client_facing"] is False and row["atrium_task_id"] == ""
    # ...while still naming the workspace it belongs to, so the console's client filter works.
    assert row["client_key"] == "honey-tribe" and row["client_name"] == "Honey Tribe"


def test_task_with_no_client_still_crosses(db):
    """An unlinked client (or none at all) is exactly the case `publish()` REFUSES. The projection
    therefore never held these, which is half of what went missing. The mirror carries them."""
    _task(db, title="Internal tooling spike")
    unlinked = Client(name="No Workspace Yet", atrium_client_id=None)
    db.add(unlinked)
    db.commit()
    _task(db, client_id=unlinked.id, title="Work for an unbridged client")

    titles = {r["title"]: r for r in board_mirror.board(db)}
    assert "Internal tooling spike" in titles
    assert titles["Internal tooling spike"]["client_key"] == ""
    # A client with no Atrium key still names itself, rather than showing as nothing.
    assert titles["Work for an unbridged client"]["client_name"] == "No Workspace Yet"


# --- the column is a stage, never a label -------------------------------------------------------

def test_column_survives_a_status_rename(db):
    """D13: `status` is a renameable LABEL. The mirror must key the column off `stage`."""
    c = _client_row(db)
    t = _task(db, client_id=c.id, status=C.TASK_IN_PROGRESS)
    assert board_mirror.board(db)[0]["stage"] == "in_progress"

    row = db.query(TaskVocabItem).filter_by(kind="status", name=C.TASK_IN_PROGRESS).one()
    row.name = "Cooking"
    t.status = "Cooking"
    db.commit()

    out = board_mirror.board(db)[0]
    assert out["stage"] == "in_progress", "renaming a status moved the card to another column"
    # ...and the console can still name the real column.
    assert out["status"] == "Cooking"


def test_custom_status_with_no_stage_lands_in_todo_not_nowhere(db):
    """Atrium has exactly five columns. A status carrying no stage must still be VISIBLE — a card
    outside every column is a card nobody can see, which is the failure mode this mirror replaces."""
    db.add(TaskVocabItem(kind="status", name="Ideas", key="ideas", stage=None, sort_order=99))
    db.commit()
    _task(db, status="Ideas", title="Loose idea")

    row = board_mirror.board(db)[0]
    assert row["stage"] == "todo" and row["status"] == "Ideas"


# --- what stays out ------------------------------------------------------------------------------

def test_filed_work_stays_out(db):
    c = _client_row(db)
    _task(db, client_id=c.id, title="Live work")
    _task(db, client_id=c.id, title="Filed months ago", archived=True)

    assert [r["title"] for r in board_mirror.board(db)] == ["Live work"]


# --- Atrium's shape ------------------------------------------------------------------------------

def test_people_are_emails_and_breakdown_uses_atrium_keys(db, make_team, make_user):
    """Atrium's roster is keyed by EMAIL (`main._team_roster`), and its phase key is `text`, not
    `title`. Getting either wrong renders the board with every owner blank."""
    team = make_team(name="Lifecycle")
    lead = make_user(role=C.ROLE_EMPLOYEE, email="mai@agoradatadriven.com", name="Mai")
    step_owner = make_user(role=C.ROLE_EMPLOYEE, email="jun@agoradatadriven.com", name="Jun")
    c = _client_row(db)
    _task(db, client_id=c.id, assigned_to_id=lead.id, assigned_team_id=team.id,
          service_charge="4200", client_facing_notes="Draft goes out Friday",
          internal_notes="never leaves this board", hold_reason="waiting on invoice",
          due_date=date(2026, 8, 20), start_date=date(2026, 8, 1),
          maintasks_json=json.dumps([{
              "id": "mt_1", "title": "Write it", "assignee_id": lead.id,
              "subs": [{"id": "st_1", "text": "First draft", "done": True,
                        "assignee_id": step_owner.id}],
          }]))

    row = board_mirror.board(db)[0]
    assert row["lead_id"] == "mai@agoradatadriven.com"
    phase = row["maintasks"][0]
    assert phase["text"] == "Write it", "Atrium renders m.text, not m.title"
    assert phase["assignee_id"] == "mai@agoradatadriven.com"
    assert phase["subs"][0]["assignee_id"] == "jun@agoradatadriven.com"
    assert phase["subs"][0]["done"] is True
    # Atrium's own field names, and the internal fields a STAFF console is allowed to see.
    assert row["client_note"] == "Draft goes out Friday"
    assert row["internal_notes"] == "never leaves this board"
    assert row["hold_reason"] == "waiting on invoice"
    assert row["service_charge"] == "4200"
    assert row["due_date"] == "2026-08-20" and row["start_date"] == "2026-08-01"
    # The label is DERIVED from the department (D14), and the dept key is Atrium's.
    assert row["department"] == "lifecycle"


def test_open_changes_is_the_rows_count_not_the_thread(db, make_user):
    """Sentinel counts a client's open change requests on the ROW; its comments carry no `kind`.
    Atrium's `_task_board` prefers this number precisely because re-deriving it would give 0."""
    author = make_user(role=C.ROLE_EMPLOYEE)
    c = _client_row(db)
    t = _task(db, client_id=c.id, client_changes_open=2)
    db.add(TaskComment(task_id=t.id, author_id=author.id, body="on it"))
    db.add(TaskComment(task_id=t.id, client_author="Nina", body="please change the header"))
    db.commit()

    row = board_mirror.board(db)[0]
    assert row["open_changes"] == 2
    senders = {c["sender"] for c in row["comments"]}
    assert senders == {"agora", "client"}


def test_ids_are_prefixed_and_carry_a_sentinel_deep_link(db):
    """The console renders this mirror ALONGSIDE unadopted Atrium cards, so a bare integer id could
    collide with an Atrium task id — and `?open=` needs Sentinel's own board id, not a composite."""
    c = _client_row(db)
    t = _task(db, client_id=c.id)

    row = board_mirror.board(db)[0]
    assert row["id"] == f"s{t.id}" and row["sentinel_id"] == t.id
    assert row["open_ref"] == str(t.id)


def test_published_rows_expose_the_id_the_console_dedupes_on(db):
    """Atrium drops a workspace card a Sentinel row already claims (`main._operator_board_tasks`),
    and `atrium_task_id` is the only handle it has for that."""
    c = _client_row(db)
    _task(db, client_id=c.id, atrium_task_id="tk_77", atrium_visible=True,
          atrium_sync_error="Atrium timed out")

    row = board_mirror.board(db)[0]
    assert row["atrium_task_id"] == "tk_77"
    assert row["client_facing"] is True
    assert row["atrium_sync_error"] == "Atrium timed out"


# --- the gate ------------------------------------------------------------------------------------

def test_endpoint_requires_a_valid_signature(client, db, monkeypatch):
    monkeypatch.setattr(settings, "platform_sso_secret", SECRET, raising=False)
    c = _client_row(db)
    _task(db, client_id=c.id, title="Unshared work")

    assert client.get("/api/internal/board").status_code == 401
    assert client.get("/api/internal/board", headers={
        "X-Academy-Ts": str(int(time.time())), "X-Academy-Sig": "0" * 64}).status_code == 401
    # A stale timestamp is a replay.
    stale = str(int(time.time()) - 4000)
    mac = hmac.new(SECRET.encode(), f"board:{stale}".encode(), hashlib.sha256).hexdigest()
    assert client.get("/api/internal/board", headers={
        "X-Academy-Ts": stale, "X-Academy-Sig": mac}).status_code == 401

    r = client.get("/api/internal/board", headers=_sig())
    assert r.status_code == 200, r.text
    assert [t["title"] for t in r.json()["tasks"]] == ["Unshared work"]


def test_fails_closed_without_a_secret(client, monkeypatch):
    monkeypatch.setattr(settings, "platform_sso_secret", "", raising=False)
    assert client.get("/api/internal/board", headers=_sig()).status_code == 503

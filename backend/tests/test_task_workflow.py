"""The task lifecycle: start date, completion, filing, park/resume, and the review gate.

Stage 2 of docs/TASKBOARD_REBUILD.md (M2–M5). What must stay true:

* `start_date` is a REAL Sentinel column — it used to be silently dropped from every Sentinel PATCH
  (`atrium_tasks.ONLY_ATRIUM`) because only Atrium cards had one;
* `completed_at` is stamped by the TRANSITION. Throughput came off `updated_at`, so editing a
  finished task re-dated its completion and inflated this week (§2.4h);
* nothing enters a done column without an approval (decision D5) — the one enforced gate here;
* an approval is SPENT by the completion it authorised;
* a hold only exists in the blocked stage, and Resume remembers the column the card left;
* only completed work may be FILED, and filing never touches the client's card;
* every one of those rules is keyed off the status's STAGE, never its label.

The Atrium transport is stubbed (test_atrium_bridge.py covers signing/mapping).
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from app import constants as C
from app.models import Client, Notification, Task, TaskVocabItem, User
from app.services import atrium_tasks, task_config, task_workflow
from app.utils.time import utcnow


# --- fixtures -----------------------------------------------------------------------------------

@pytest.fixture
def team(make_team):
    return make_team(name="Acquisition")


@pytest.fixture
def lead(make_user, team):
    return make_user(C.ROLE_TEAM_LEAD, team_id=team.id, name="Ehjay")


@pytest.fixture
def worker(make_user, team):
    return make_user(C.ROLE_EMPLOYEE, team_id=team.id, name="Zhen")


@pytest.fixture
def task(db, team, worker):
    t = Task(title="Spring drop — Meta campaign", status=C.TASK_IN_PROGRESS,
             assigned_team_id=team.id, assigned_to_id=worker.id)
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def _published(db, task, key="honeytribe", atrium_id="t_ab12cd"):
    """Make `task` a published projection of a client card."""
    c = Client(name="Honey Tribe", atrium_client_id=key)
    db.add(c)
    db.commit()
    task.client_id = c.id
    task.atrium_task_id = atrium_id
    task.atrium_visible = True
    db.commit()
    return task


def _stub_bridge(monkeypatch):
    """Record every move/edit the bridge is asked to make."""
    seen: dict = {"moves": [], "edits": []}
    monkeypatch.setattr(atrium_tasks, "move_task",
                        lambda k, t, stage, actor="": (seen["moves"].append(stage), (True, ""))[1])
    monkeypatch.setattr(atrium_tasks, "edit_task",
                        lambda k, t, fields, actor="": (seen["edits"].append(fields), ({}, ""))[1])
    return seen


def _approve(db, task, reviewer):
    task.review_state = C.REVIEW_APPROVED
    task.reviewer_id = reviewer.id
    db.commit()


# --- M5: start_date ------------------------------------------------------------------------------

def test_start_date_saves_on_a_sentinel_task(client, auth, task, worker, db):
    """It used to be dropped: `start_date` was in ONLY_ATRIUM because only Atrium cards had one."""
    auth(worker)
    r = client.patch(f"/api/tasks/{task.id}", json={"start_date": "2026-08-10"})
    assert r.status_code == 200
    assert r.json()["start_date"] == "2026-08-10"
    db.expire_all()
    assert db.get(Task, task.id).start_date == date(2026, 8, 10)


def test_start_date_crosses_to_the_client_but_a_hold_reason_never_does(
        client, auth, make_user, task, db, monkeypatch):
    """A schedule fact is client-safe; why we paused is not."""
    _published(db, task)
    task.hold_reason = "Client hasn't paid the media budget"
    db.commit()
    seen = _stub_bridge(monkeypatch)
    auth(make_user(C.ROLE_ACCOUNT_MANAGER))

    r = client.patch(f"/api/tasks/{task.id}", json={"start_date": "2026-08-10"})
    assert r.status_code == 200
    assert seen["edits"], "a client-visible change must re-push"
    fields = seen["edits"][-1]
    assert fields["start_date"] == "2026-08-10"
    assert "hold_reason" not in fields
    assert "paid" not in repr(fields)


# --- M4: completed_at, and the throughput bug ---------------------------------------------------

def test_completing_stamps_completed_at(client, auth, make_user, task, db, lead):
    _approve(db, task, lead)
    auth(make_user(C.ROLE_ACCOUNT_MANAGER))
    r = client.patch(f"/api/tasks/{task.id}/status", json={"status": C.TASK_COMPLETED})
    assert r.status_code == 200
    assert r.json()["completed_at"]
    db.expire_all()
    assert db.get(Task, task.id).completed_at is not None


def test_reopening_clears_the_stamp(client, auth, make_user, task, db, lead):
    _approve(db, task, lead)
    auth(make_user(C.ROLE_ACCOUNT_MANAGER))
    client.patch(f"/api/tasks/{task.id}/status", json={"status": C.TASK_COMPLETED})
    client.patch(f"/api/tasks/{task.id}/status", json={"status": C.TASK_IN_PROGRESS})
    db.expire_all()
    assert db.get(Task, task.id).completed_at is None


def test_editing_a_finished_task_does_not_re_date_its_completion(
        client, auth, make_user, task, db, worker):
    """🔴 §2.4h. Off `updated_at`, fixing a typo on a task finished in March landed it in THIS
    week's throughput. The stamp is what the rollup counts now."""
    long_ago = utcnow() - timedelta(days=90)
    task.status = C.TASK_COMPLETED
    task.completed_at = long_ago
    db.commit()

    auth(make_user(C.ROLE_ACCOUNT_MANAGER))
    client.patch(f"/api/tasks/{task.id}", json={"title": "Spring drop — Meta campaign (v2)"})

    db.expire_all()
    row = db.get(Task, task.id)
    assert row.completed_at == long_ago          # the edit moved updated_at, not this
    assert row.updated_at > long_ago

    rows = client.get("/api/tasks/summary").json()
    mine = next(r for r in rows if r["user"]["id"] == worker.id)
    assert mine["completed_week"] == 0           # finished 90 days ago, not this week


def test_a_task_completed_this_week_counts(client, auth, make_user, task, db, worker):
    task.status = C.TASK_COMPLETED
    task.completed_at = utcnow()
    db.commit()
    auth(make_user(C.ROLE_ACCOUNT_MANAGER))
    rows = client.get("/api/tasks/summary").json()
    mine = next(r for r in rows if r["user"]["id"] == worker.id)
    assert mine["completed_week"] == 1


def test_a_completion_with_no_stamp_is_not_counted(client, auth, make_user, task, db, worker):
    """A row finished before the column existed has no honest date, so it claims none — better than
    counting it on whatever day someone last touched it (which is the bug)."""
    task.status = C.TASK_COMPLETED
    task.completed_at = None
    db.commit()
    auth(make_user(C.ROLE_ACCOUNT_MANAGER))
    rows = client.get("/api/tasks/summary").json()
    mine = next(r for r in rows if r["user"]["id"] == worker.id)
    assert mine["completed_week"] == 0


# --- M4: filing / Past work ---------------------------------------------------------------------

def test_only_completed_work_can_be_filed(client, auth, make_user, task):
    auth(make_user(C.ROLE_ACCOUNT_MANAGER))
    r = client.post(f"/api/tasks/{task.id}/archive")
    assert r.status_code == 409
    assert "Park it instead" in r.json()["detail"]


def test_filing_moves_a_task_off_the_board_into_past_work(
        client, auth, make_user, task, db, lead):
    _approve(db, task, lead)
    auth(make_user(C.ROLE_ACCOUNT_MANAGER))
    client.patch(f"/api/tasks/{task.id}/status", json={"status": C.TASK_COMPLETED})

    r = client.post(f"/api/tasks/{task.id}/archive")
    assert r.status_code == 200 and r.json()["archived"] is True

    board = client.get("/api/tasks").json()
    assert [c["id"] for c in board if c.get("source") != "atrium"] == []
    past = client.get("/api/tasks?archived=1").json()
    assert [c["id"] for c in past] == [task.id]


def test_unfiling_puts_it_back_in_the_column_it_still_holds(
        client, auth, make_user, task, db, lead):
    _approve(db, task, lead)
    auth(make_user(C.ROLE_ACCOUNT_MANAGER))
    client.patch(f"/api/tasks/{task.id}/status", json={"status": C.TASK_COMPLETED})
    client.post(f"/api/tasks/{task.id}/archive")

    r = client.post(f"/api/tasks/{task.id}/unarchive")
    assert r.status_code == 200
    assert r.json()["archived"] is False and r.json()["status"] == C.TASK_COMPLETED
    assert [c["id"] for c in client.get("/api/tasks").json()] == [task.id]


def test_reopening_a_filed_task_unfiles_it(client, auth, make_user, task, db, lead):
    """Live work belongs on the board, not in Past work — where nobody would look for it."""
    _approve(db, task, lead)
    auth(make_user(C.ROLE_ACCOUNT_MANAGER))
    client.patch(f"/api/tasks/{task.id}/status", json={"status": C.TASK_COMPLETED})
    client.post(f"/api/tasks/{task.id}/archive")

    r = client.patch(f"/api/tasks/{task.id}/status", json={"status": C.TASK_IN_PROGRESS})
    assert r.status_code == 200
    assert r.json()["archived"] is False


def test_filing_never_touches_the_clients_card(client, auth, make_user, task, db, lead, monkeypatch):
    """Filing is internal bookkeeping. Quietly moving or hiding a delivered card would rewrite what
    the client was told."""
    _published(db, task)
    _approve(db, task, lead)
    seen = _stub_bridge(monkeypatch)
    auth(make_user(C.ROLE_ACCOUNT_MANAGER))
    client.patch(f"/api/tasks/{task.id}/status", json={"status": C.TASK_COMPLETED})
    seen["moves"].clear()

    client.post(f"/api/tasks/{task.id}/archive")
    assert seen["moves"] == [] and seen["edits"] == []


def test_filed_work_still_counts_toward_this_weeks_throughput(
        client, auth, make_user, task, db, lead, worker):
    """Filing a shipped task must not erase the fact that it shipped."""
    _approve(db, task, lead)
    auth(make_user(C.ROLE_ACCOUNT_MANAGER))
    client.patch(f"/api/tasks/{task.id}/status", json={"status": C.TASK_COMPLETED})
    client.post(f"/api/tasks/{task.id}/archive")

    mine = next(r for r in client.get("/api/tasks/summary").json()
                if r["user"]["id"] == worker.id)
    assert mine["completed_week"] == 1
    assert mine["counts"][C.TASK_COMPLETED] == 0    # ...but it is off their plate
    assert mine["total"] == 0


# --- M3: park / resume ---------------------------------------------------------------------------

def test_park_remembers_the_column_and_the_reason(client, auth, task, db, lead):
    auth(lead)
    r = client.post(f"/api/tasks/{task.id}/park", json={"reason": "Waiting on brand assets"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == C.TASK_BLOCKED
    assert body["on_hold"] is True
    assert body["hold_reason"] == "Waiting on brand assets"
    assert body["resume_to"] == C.TASK_IN_PROGRESS


def test_resume_puts_it_back_and_ends_the_hold(client, auth, task, lead):
    auth(lead)
    client.post(f"/api/tasks/{task.id}/park", json={"reason": "Waiting on assets"})
    r = client.post(f"/api/tasks/{task.id}/resume")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == C.TASK_IN_PROGRESS
    assert body["on_hold"] is False
    assert body["hold_reason"] is None and body["resume_to"] is None


def test_resuming_something_that_is_not_parked_is_refused(client, auth, task, lead):
    auth(lead)
    r = client.post(f"/api/tasks/{task.id}/resume")
    assert r.status_code == 409
    assert "isn't on hold" in r.json()["detail"]


def test_parking_from_the_blocked_column_resumes_at_the_front_of_the_queue(
        client, auth, task, db, lead):
    """`resume_to` must never be the blocked column itself, or Resume would re-park the card."""
    task.status = C.TASK_BLOCKED
    db.commit()
    auth(lead)
    r = client.post(f"/api/tasks/{task.id}/park", json={"reason": "Client went quiet"})
    assert r.json()["resume_to"] == C.TASK_TODO


def test_parking_twice_keeps_the_original_column(client, auth, task, lead, db):
    auth(lead)
    client.post(f"/api/tasks/{task.id}/park", json={"reason": "first"})
    r = client.post(f"/api/tasks/{task.id}/park", json={"reason": "second"})
    assert r.json()["resume_to"] == C.TASK_IN_PROGRESS      # not "Blocked"
    assert r.json()["hold_reason"] == "second"


def test_resume_falls_back_when_the_remembered_column_is_gone(client, auth, task, db, lead):
    """The card sat parked while someone retired the column it left. Resume at the front of the
    queue rather than guessing — visible, and obviously needing triage."""
    auth(lead)
    client.post(f"/api/tasks/{task.id}/park", json={"reason": "waiting"})
    db.expire_all()
    db.get(Task, task.id).resume_to = "A Column Nobody Kept"
    db.commit()

    r = client.post(f"/api/tasks/{task.id}/resume")
    assert r.json()["status"] == C.TASK_TODO


def test_dragging_a_parked_card_out_of_blocked_ends_the_hold(client, auth, task, lead, db):
    """Most people will resume by dragging. "On hold" must not outlive the pause."""
    auth(lead)
    client.post(f"/api/tasks/{task.id}/park", json={"reason": "waiting"})
    r = client.patch(f"/api/tasks/{task.id}/status", json={"status": C.TASK_IN_PROGRESS})
    assert r.status_code == 200
    assert r.json()["on_hold"] is False
    assert r.json()["hold_reason"] is None


# 🔴 …and the same rule INTO the column (task_workflow._sync_hold, 2026-08-06). Only the exit was
# implemented, so the board carried two kinds of parked card: one that went through `park()` and one
# that was dragged, whose `on_hold` was still False — no ⏸ pill, no remembered column, and a drawer
# still offering "Park…" for a card already in the parked column. `push_stage` moved the CLIENT's card
# to the blocked stage either way, so the client read "Paused" for work this row denied was paused.

def test_dragging_a_card_INTO_blocked_puts_it_on_hold(client, auth, task, lead):
    auth(lead)
    r = client.patch(f"/api/tasks/{task.id}/status", json={"status": C.TASK_BLOCKED})
    assert r.status_code == 200
    body = r.json()
    assert body["on_hold"] is True
    # Where Resume will put it back — the column it actually came from, exactly as park records it.
    assert body["resume_to"] == C.TASK_IN_PROGRESS
    # No reason, because nobody was asked for one. Inventing "dragged here" would be worse.
    assert body["hold_reason"] is None


def test_a_dragged_hold_resumes_to_where_it_came_from(client, auth, task, lead):
    auth(lead)
    client.patch(f"/api/tasks/{task.id}/status", json={"status": C.TASK_BLOCKED})
    r = client.post(f"/api/tasks/{task.id}/resume")
    assert r.status_code == 200
    assert r.json()["status"] == C.TASK_IN_PROGRESS
    assert r.json()["on_hold"] is False


def test_dragging_into_blocked_does_not_overwrite_a_typed_reason(client, auth, task, lead, db):
    """Park it with a reason, then move it WITHIN the blocked stage. The reason is somebody's typing;
    a generic status move must not clear it. (This is what the `not task.on_hold` guard protects.)"""
    auth(lead)
    client.post(f"/api/tasks/{task.id}/park", json={"reason": "Waiting on brand assets"})
    # A second blocked column, so a move can stay inside the stage. `sort_order` puts it AFTER the
    # seeded blocked column, so `status_for_stage("blocked")` — and therefore Park — is unaffected.
    db.add(TaskVocabItem(kind="status", name="Snagged", key="snagged", stage="blocked",
                         sort_order=99))
    db.commit()
    r = client.patch(f"/api/tasks/{task.id}/status", json={"status": "Snagged"})
    assert r.status_code == 200
    assert r.json()["on_hold"] is True
    assert r.json()["hold_reason"] == "Waiting on brand assets"
    assert r.json()["resume_to"] == C.TASK_IN_PROGRESS      # still the column it originally left


# --- creating a card straight into a column is a MOVE into it (2026-08-06) -----------------------
# `create_task` wrote `status` as a plain field and never called `on_status_change`. The board offers
# "Add card" at the foot of EVERY column, so a task created in a done column got no `completed_at` —
# and per §2.4h a completed row with no stamp is counted on NO day: it sat in Completed while being
# invisible to Throughput, the on-time rate and cycle time, and showed "—" in Past work.

def test_creating_a_task_in_a_done_column_stamps_completed_at(client, auth, lead):
    auth(lead)
    r = client.post("/api/tasks", json={"title": "Retro-filed deliverable",
                                        "status": C.TASK_COMPLETED})
    assert r.status_code == 200
    assert r.json()["completed_at"] is not None


def test_creating_a_task_in_the_blocked_column_puts_it_on_hold(client, auth, lead):
    auth(lead)
    r = client.post("/api/tasks", json={"title": "Blocked on legal", "status": C.TASK_BLOCKED})
    assert r.status_code == 200
    assert r.json()["on_hold"] is True


def test_creating_an_ordinary_task_stamps_nothing(client, auth, lead):
    """The guard rails only fire for the two loaded stages — a normal create is untouched."""
    auth(lead)
    r = client.post("/api/tasks", json={"title": "Write the brief", "status": C.TASK_TODO})
    assert r.status_code == 200
    assert r.json()["completed_at"] is None
    assert r.json()["on_hold"] is False


def test_parking_moves_the_clients_card_to_the_blocked_stage(
        client, auth, make_user, task, db, monkeypatch):
    _published(db, task)
    seen = _stub_bridge(monkeypatch)
    auth(make_user(C.ROLE_ACCOUNT_MANAGER))
    client.post(f"/api/tasks/{task.id}/park", json={"reason": "internal only"})
    assert seen["moves"] == ["blocked"]


def test_an_employee_can_park_their_own_work(client, auth, task, worker):
    """Parking is a move, so it follows can_move — you may pause the work you hold."""
    auth(worker)
    assert client.post(f"/api/tasks/{task.id}/park", json={"reason": "blocked on the client"}).status_code == 200


def test_someone_elses_task_cannot_be_parked(client, auth, make_user, task):
    auth(make_user(C.ROLE_EMPLOYEE))          # not assigned, no team
    assert client.post(f"/api/tasks/{task.id}/park", json={"reason": "x"}).status_code == 403


# --- M2 / D5: the review gate --------------------------------------------------------------------

def test_completing_without_an_approval_is_refused(client, auth, make_user, task):
    auth(make_user(C.ROLE_ACCOUNT_MANAGER))
    r = client.patch(f"/api/tasks/{task.id}/status", json={"status": C.TASK_COMPLETED})
    assert r.status_code == 409
    assert "approval" in r.json()["detail"]


def test_submit_then_approve_then_complete(client, auth, task, worker, lead, db):
    auth(worker)
    r = client.post(f"/api/tasks/{task.id}/review/submit")
    assert r.status_code == 200 and r.json()["review_state"] == C.REVIEW_PENDING

    auth(lead)
    r = client.post(f"/api/tasks/{task.id}/review/approve")
    assert r.status_code == 200
    assert r.json()["review_state"] == C.REVIEW_APPROVED
    assert r.json()["reviewer"]["id"] == lead.id

    r = client.patch(f"/api/tasks/{task.id}/status", json={"status": C.TASK_COMPLETED})
    assert r.status_code == 200 and r.json()["status"] == C.TASK_COMPLETED


def test_an_approval_is_spent_by_the_completion_it_authorised(
        client, auth, make_user, task, db, lead):
    """Reopened work is new work: the next "Done" is a new claim and needs its own approval."""
    _approve(db, task, lead)
    auth(make_user(C.ROLE_ACCOUNT_MANAGER))
    client.patch(f"/api/tasks/{task.id}/status", json={"status": C.TASK_COMPLETED})
    r = client.patch(f"/api/tasks/{task.id}/status", json={"status": C.TASK_IN_PROGRESS})
    assert r.json()["review_state"] is None
    assert r.json()["reviewer"] is None

    r = client.patch(f"/api/tasks/{task.id}/status", json={"status": C.TASK_COMPLETED})
    assert r.status_code == 409


def test_a_move_between_two_unfinished_columns_keeps_the_approval(
        client, auth, make_user, task, db, lead):
    _approve(db, task, lead)
    auth(make_user(C.ROLE_ACCOUNT_MANAGER))
    r = client.patch(f"/api/tasks/{task.id}/status", json={"status": C.TASK_TODO})
    assert r.json()["review_state"] == C.REVIEW_APPROVED


def test_an_employee_may_ask_for_review_but_not_decide_it(client, auth, task, worker):
    auth(worker)
    assert client.post(f"/api/tasks/{task.id}/review/submit").status_code == 200
    assert client.post(f"/api/tasks/{task.id}/review/approve").status_code == 403


def test_a_lead_of_another_team_cannot_approve(client, auth, make_user, make_team, task):
    other = make_team(name="Lifecycle")
    auth(make_user(C.ROLE_TEAM_LEAD, team_id=other.id))
    assert client.post(f"/api/tasks/{task.id}/review/approve").status_code == 403


def test_submitting_notifies_the_leads_by_query_not_by_a_lead_column(
        client, auth, task, worker, lead, db, make_user):
    """🔴 Decision D9: there is no `Team.lead_id`. `notify_managers(team_id=…)` finds leads by role +
    team, which is why zero leads and three leads both work."""
    second_lead = make_user(C.ROLE_TEAM_LEAD, team_id=task.assigned_team_id, name="Justine")
    admin = make_user(C.ROLE_ADMIN)
    auth(worker)
    client.post(f"/api/tasks/{task.id}/review/submit")

    notified = {n.user_id for n in db.query(Notification)
                .filter(Notification.type == C.NOTIF_TASK_REVIEW)}
    assert {lead.id, second_lead.id, admin.id} <= notified
    assert worker.id not in notified


def test_request_changes_sends_the_card_to_the_revision_column_with_the_note(
        client, auth, task, lead, db, worker):
    auth(lead)
    r = client.post(f"/api/tasks/{task.id}/review/request-changes",
                    json={"note": "Hook is too long — reshoot the first 3s."})
    assert r.status_code == 200
    body = r.json()
    assert body["review_state"] == C.REVIEW_CHANGES
    assert body["status"] == C.TASK_REVISION
    assert any("reshoot" in (h["new_value"] or "") for h in body["history"])
    # ...and the person holding the work hears about it.
    assert db.query(Notification).filter(Notification.user_id == worker.id).count() >= 1


def test_changes_requested_still_blocks_completion(client, auth, task, lead):
    auth(lead)
    client.post(f"/api/tasks/{task.id}/review/request-changes", json={"note": "no"})
    assert client.patch(f"/api/tasks/{task.id}/status",
                        json={"status": C.TASK_COMPLETED}).status_code == 409


def test_a_task_already_in_a_done_column_can_still_be_edited_and_moved_within_it(
        client, auth, make_user, task, db):
    """The gate is on the TRANSITION into done. A row that is already there (a legacy one, or one
    completed before the gate shipped) must not become unmovable."""
    task.status = C.TASK_COMPLETED
    db.commit()
    auth(make_user(C.ROLE_ACCOUNT_MANAGER))
    assert client.patch(f"/api/tasks/{task.id}", json={"title": "renamed"}).status_code == 200


# --- everything above must key off the STAGE, not the label -------------------------------------

def test_renaming_the_done_column_keeps_the_gate_and_the_stamp(
        client, auth, make_user, task, db, lead):
    """Rename Completed → Shipped in Manage: the gate, the stamp and the rollup all follow, because
    every one of them asks `task_config.is_completed` (stage), never the label (AGENTS.md §5)."""
    row = db.query(TaskVocabItem).filter(
        TaskVocabItem.kind == "status", TaskVocabItem.name == C.TASK_COMPLETED).one()
    row.name = "Shipped"
    db.commit()
    assert task_config.is_completed(db, "Shipped")

    auth(make_user(C.ROLE_ACCOUNT_MANAGER))
    r = client.patch(f"/api/tasks/{task.id}/status", json={"status": "Shipped"})
    assert r.status_code == 409                       # the gate still bites

    _approve(db, task, lead)
    r = client.patch(f"/api/tasks/{task.id}/status", json={"status": "Shipped"})
    assert r.status_code == 200 and r.json()["completed_at"]
    assert client.post(f"/api/tasks/{task.id}/archive").status_code == 200


def test_park_refuses_when_the_board_has_no_blocked_column(client, auth, task, db, lead):
    """Nothing invents a column: if the blocked stage carries no status there is nowhere to park."""
    row = db.query(TaskVocabItem).filter(
        TaskVocabItem.kind == "status", TaskVocabItem.name == C.TASK_BLOCKED).one()
    db.delete(row)
    db.commit()
    auth(lead)
    r = client.post(f"/api/tasks/{task.id}/park", json={"reason": "x"})
    assert r.status_code == 409
    assert "nowhere to park" in r.json()["detail"]


# --- an Atrium-owned card has no local row to hold any of this ----------------------------------

@pytest.mark.parametrize("path", ["park", "archive", "unarchive", "resume",
                                  "review/submit", "review/approve"])
def test_lifecycle_actions_refuse_an_atrium_card(client, auth, make_user, path):
    auth(make_user(C.ROLE_ACCOUNT_MANAGER))
    r = client.post(f"/api/tasks/atrium:honeytribe:tk_1/{path}", json={})
    assert r.status_code == 400
    assert "Atrium owns" in r.json()["detail"]

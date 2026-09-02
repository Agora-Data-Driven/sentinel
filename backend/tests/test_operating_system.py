"""The operating-system release (2026-09-02): work sessions, structured holds, client health, the
calendar projection, the COO's exceptions, AI drafting's validation, certifications and worker stage.

What must stay true:

* Start Work opens ONE session per person, closes the previous one, and moves a To Do card to In
  Progress through the ordinary move path; Pause / Submit / Park / clock-out all close it.
* A runaway session is capped and flagged, never trusted.
* Park records WHY (hold_kind) and resume clears it with the rest of the hold.
* Client health is a printed rule: red / amber / green derive from the board alone.
* The calendar has no table — it is the board's dates, recurring trigger days and approved leave.
* AI proposals are validated against Sentinel's roster; a viewer can start nothing.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from app import constants as C
from app.models import Certification, Client, LeaveRequest, LeaveType, RecurringService, Task, TaskSession
from app.services import ai_draft, calendar_view, client_health, operations, task_sessions
from app.utils.time import today_ph, utcnow


@pytest.fixture
def team(make_team):
    return make_team(name="Acquisition")


@pytest.fixture
def lead(make_user, team):
    return make_user(C.ROLE_TEAM_LEAD, team_id=team.id, name="Bong Cruz")


@pytest.fixture
def worker(make_user, team):
    return make_user(C.ROLE_EMPLOYEE, team_id=team.id, name="Earl Santos", stage="contributor")


@pytest.fixture
def am(make_user):
    return make_user(C.ROLE_ACCOUNT_MANAGER, name="Leo Vasquez")


@pytest.fixture
def admin(make_user):
    return make_user(C.ROLE_ADMIN, name="Maria Santos")


@pytest.fixture
def client_row(db, am):
    c = Client(name="The Contract Shop", atrium_client_id="tcs", account_manager_id=am.id)
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


@pytest.fixture
def task(db, team, worker, client_row):
    t = Task(title="Fix Meta attribution", status=C.TASK_TODO, assigned_team_id=team.id,
             assigned_to_id=worker.id, client_id=client_row.id, due_date=today_ph(), estimate_minutes=90)
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def _fresh(db, obj):
    db.expire_all()
    return db.get(type(obj), obj.id)


# --- sessions ---------------------------------------------------------------------------------

def test_start_work_opens_a_session_and_moves_the_card(client, db, auth, worker, task):
    auth(worker)
    r = client.post(f"/api/tasks/{task.id}/sessions/start")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["moved"] is True
    assert body["active"]["task_id"] == task.id and body["active"]["running"]
    assert _fresh(db, task).status == C.TASK_IN_PROGRESS
    # The strip's read sees the same session.
    a = client.get("/api/tasks/sessions/active").json()["active"]
    assert a and a["task_id"] == task.id


def test_one_open_session_per_person(client, db, auth, worker, team, client_row, task):
    other = Task(title="Second card", status=C.TASK_IN_PROGRESS, assigned_team_id=team.id,
                 assigned_to_id=worker.id, client_id=client_row.id)
    db.add(other)
    db.commit()
    auth(worker)
    client.post(f"/api/tasks/{task.id}/sessions/start")
    r = client.post(f"/api/tasks/{other.id}/sessions/start")
    assert r.status_code == 200
    assert len(r.json()["closed"]) == 1 and r.json()["closed"][0]["task_id"] == task.id
    opens = db.query(TaskSession).filter(TaskSession.ended_at.is_(None)).all()
    assert len(opens) == 1 and opens[0].task_id == other.id


def test_starting_the_same_card_twice_is_one_session(client, db, auth, worker, task):
    auth(worker)
    client.post(f"/api/tasks/{task.id}/sessions/start")
    client.post(f"/api/tasks/{task.id}/sessions/start")
    assert db.query(TaskSession).count() == 1


def test_pause_submit_and_park_all_close_the_session(client, db, auth, worker, task):
    auth(worker)
    client.post(f"/api/tasks/{task.id}/sessions/start")
    r = client.post("/api/tasks/sessions/pause")
    assert r.status_code == 200 and len(r.json()["closed"]) == 1
    assert task_sessions.active_for(db, worker.id) is None
    client.post(f"/api/tasks/{task.id}/sessions/start")
    client.post(f"/api/tasks/{task.id}/review/submit")
    assert task_sessions.active_for(db, worker.id) is None
    # Park closes it too (and records why).
    t2 = Task(title="Another", status=C.TASK_IN_PROGRESS, assigned_to_id=worker.id, assigned_team_id=task.assigned_team_id)
    db.add(t2)
    db.commit()
    client.post(f"/api/tasks/{t2.id}/sessions/start")
    r = client.post(f"/api/tasks/{t2.id}/park", json={"reason": "no creatives", "kind": "client"})
    assert r.status_code == 200, r.text
    assert task_sessions.active_for(db, worker.id) is None
    t2 = _fresh(db, t2)
    assert t2.on_hold and t2.hold_kind == "client"


def test_clock_out_closes_the_running_session(client, db, auth, worker, task):
    auth(worker)
    client.post("/api/attendance/self-event", json={"action": "clock_in"})
    client.post(f"/api/tasks/{task.id}/sessions/start")
    r = client.post("/api/attendance/self-event", json={"action": "clock_out"})
    assert r.status_code == 200, r.text
    s = db.query(TaskSession).one()
    assert s.ended_at is not None and s.source == "auto_clockout"


def test_a_runaway_session_is_capped_and_flagged(db, worker, task):
    s = TaskSession(task_id=task.id, user_id=worker.id, started_at=utcnow() - timedelta(hours=9))
    db.add(s)
    db.commit()
    closed = task_sessions.close_open(db, worker.id)
    db.commit()
    assert closed[0].source == "auto_cap"
    assert closed[0].minutes == 240
    assert "capped" in (closed[0].note or "")


def test_start_refuses_a_completed_or_parked_card(client, db, auth, worker, task):
    auth(worker)
    task.status = C.TASK_BLOCKED
    task.on_hold = True
    db.commit()
    assert client.post(f"/api/tasks/{task.id}/sessions/start").status_code == 409


def test_a_colleague_cannot_start_work_on_someone_elses_card(client, db, auth, make_user, team, task):
    stranger = make_user(C.ROLE_EMPLOYEE, team_id=team.id, name="Faye")
    auth(stranger)
    # Visible (same department) but not editable.
    assert client.post(f"/api/tasks/{task.id}/sessions/start").status_code == 403


def test_task_detail_carries_sessions_and_estimate(client, db, auth, worker, task):
    auth(worker)
    client.post(f"/api/tasks/{task.id}/sessions/start")
    d = client.get(f"/api/tasks/{task.id}").json()
    assert d["estimate_minutes"] == 90
    assert len(d["sessions"]) == 1 and d["sessions"][0]["running"]


# --- structured holds ----------------------------------------------------------------------------

def test_park_rejects_an_unknown_kind_and_resume_clears_it(client, db, auth, worker, task):
    auth(worker)
    assert client.post(f"/api/tasks/{task.id}/park", json={"reason": "x", "kind": "weather"}).status_code == 409
    r = client.post(f"/api/tasks/{task.id}/park", json={"reason": "waiting on Leo", "kind": "am_decision"})
    assert r.status_code == 200
    assert r.json()["hold_kind"] == "am_decision" and r.json()["hold_kind_label"] == "Waiting for AM decision"
    client.post(f"/api/tasks/{task.id}/resume")
    t = _fresh(db, task)
    assert t.hold_kind is None and not t.on_hold


def test_waiting_on_another_task_names_it(client, db, auth, worker, task, team):
    other = Task(title="Upstream", status=C.TASK_IN_PROGRESS, assigned_to_id=worker.id, assigned_team_id=team.id)
    db.add(other)
    db.commit()
    auth(worker)
    r = client.post(f"/api/tasks/{task.id}/park", json={"kind": "task", "blocked_by_task_id": other.id})
    assert r.status_code == 200 and r.json()["blocked_by_task_id"] == other.id
    assert client.post(f"/api/tasks/{other.id}/park", json={"kind": "task", "blocked_by_task_id": 99999}).status_code == 400


# --- client health --------------------------------------------------------------------------------

def test_health_rule_red_amber_green(db, am, worker, team, client_row):
    today = today_ph()
    rows = client_health.rollup(db, am, today)
    assert rows[0]["health"] == "green" and rows[0]["account_manager"]["id"] == am.id
    # due today → amber
    db.add(Task(title="Due", status=C.TASK_TODO, client_id=client_row.id, assigned_to_id=worker.id,
                assigned_team_id=team.id, due_date=today))
    db.commit()
    assert client_health.rollup(db, am, today)[0]["health"] == "amber"
    # overdue → red, with the reason in words
    db.add(Task(title="Late", status=C.TASK_IN_PROGRESS, client_id=client_row.id, assigned_to_id=worker.id,
                assigned_team_id=team.id, due_date=today - timedelta(days=2)))
    db.commit()
    row = client_health.rollup(db, am, today)[0]
    assert row["health"] == "red" and "1 overdue" in row["why"]


def test_waiting_on_the_client_is_amber_not_red(db, am, worker, team, client_row):
    t = Task(title="Blocked", status=C.TASK_BLOCKED, on_hold=True, hold_kind="client",
             client_id=client_row.id, assigned_to_id=worker.id, assigned_team_id=team.id,
             due_date=today_ph() - timedelta(days=3))
    db.add(t)
    db.commit()
    row = client_health.rollup(db, am)[0]
    # An overdue date on a PARKED card is not "overdue" — it is waiting on the client.
    assert row["health"] == "amber" and row["blocked_on_client"] == 1 and row["overdue"] == 0


def test_clients_endpoints_follow_the_capability(client, db, auth, am, worker, client_row, task):
    auth(worker)
    assert client.get("/api/ops/clients").status_code == 403
    auth(am)
    r = client.get("/api/ops/clients")
    assert r.status_code == 200 and r.json()["clients"][0]["client"]["name"] == "The Contract Shop"
    o = client.get(f"/api/ops/clients/{client_row.id}").json()
    assert o["by_lead"][0]["tasks"][0]["id"] == task.id
    r = client.patch(f"/api/ops/clients/{client_row.id}/account-manager", json={"account_manager_id": None})
    assert r.status_code == 200 and r.json()["account_manager"] is None


# --- calendar -----------------------------------------------------------------------------------

def test_calendar_projects_due_dates_recurrences_and_leave(client, db, auth, worker, lead, task, team, client_row):
    today = today_ph()
    db.add(RecurringService(title="Weekly Google opt", client_id=client_row.id, service_key="x",
                            assigned_team_id=team.id, assigned_to_id=worker.id, cadence="weekly",
                            day_of_period=today.weekday(), due_in_days=0, created_by_id=lead.id))
    lt = LeaveType(name="Vacation", annual_balance=10)
    db.add(lt)
    db.commit()
    db.add(LeaveRequest(user_id=worker.id, leave_type_id=lt.id, start_date=today + timedelta(days=1),
                        end_date=today + timedelta(days=2), reason="trip", status=C.LEAVE_APPROVED))
    db.commit()
    auth(worker)
    r = client.get(f"/api/ops/calendar?from={today}&to={today + timedelta(days=6)}&mine=1")
    assert r.status_code == 200
    kinds = {e["kind"] for e in r.json()["events"]}
    assert {"due", "recurring", "leave"} <= kinds
    due = next(e for e in r.json()["events"] if e["kind"] == "due")
    assert due["task_id"] == task.id and due["late"] is False


def test_calendar_is_scoped_by_can_view(client, db, auth, make_user, make_team, task):
    other_team = make_team(name="Lifecycle")
    outsider = make_user(C.ROLE_EMPLOYEE, team_id=other_team.id)
    auth(outsider)
    today = today_ph()
    r = client.get(f"/api/ops/calendar?from={today}&to={today}")
    assert all(e["kind"] != "due" for e in r.json()["events"])


# --- operations ---------------------------------------------------------------------------------

def test_exceptions_name_a_red_client_and_require_the_capability(client, db, auth, admin, am, worker, team, client_row):
    db.add(Task(title="Late", status=C.TASK_IN_PROGRESS, client_id=client_row.id, assigned_to_id=worker.id,
                assigned_team_id=team.id, due_date=today_ph() - timedelta(days=2)))
    db.commit()
    auth(am)
    assert client.get("/api/ops/exceptions").status_code == 403
    auth(admin)
    r = client.get("/api/ops/exceptions")
    assert r.status_code == 200
    body = r.json()
    kinds = [e["kind"] for e in body["exceptions"]]
    assert "client" in kinds
    red = next(e for e in body["exceptions"] if e["kind"] == "client")
    assert red["owner"]["id"] == am.id and red["severity"] == "red"
    assert body["stats"]["overdue"] == 1
    assert any(row["user"]["id"] == worker.id for row in body["capacity"])


def test_a_stale_review_surfaces_as_an_exception(client, db, auth, admin, worker, task):
    task.review_state = C.REVIEW_PENDING
    db.commit()
    from app.models import TaskHistory
    db.add(TaskHistory(task_id=task.id, changed_by_id=worker.id, field_changed="review_state",
                       new_value=C.REVIEW_PENDING, changed_at=utcnow() - timedelta(hours=30)))
    db.commit()
    auth(admin)
    body = client.get("/api/ops/exceptions").json()
    assert any(e["kind"] == "review" for e in body["exceptions"])
    assert body["stats"]["reviews_stale"] == 1


# --- today ---------------------------------------------------------------------------------------

def test_today_reports_the_three_kinds_of_time(client, db, auth, worker, task, monkeypatch):
    from app.services import time_spent
    monkeypatch.setattr(time_spent, "summary", lambda db_, u, w: {"total": 25, "engine_error": ""})
    auth(worker)
    client.post("/api/attendance/self-event", json={"action": "clock_in"})
    client.post(f"/api/tasks/{task.id}/sessions/start")
    r = client.get("/api/ops/today")
    assert r.status_code == 200
    t = r.json()["time"]
    assert t["attendance"]["clock_in"] and t["attendance"]["minutes"] is not None
    assert t["learning_minutes"] == 25
    assert t["active_session"]["task_id"] == task.id
    assert t["unallocated_minutes"] is not None


def test_today_learning_is_unknown_not_zero_when_the_engine_is_down(client, auth, worker, monkeypatch):
    from app.services import time_spent
    monkeypatch.setattr(time_spent, "summary", lambda db_, u, w: {"total": None, "engine_error": "down"})
    auth(worker)
    t = client.get("/api/ops/today").json()["time"]
    assert t["learning_minutes"] is None and t["learning_error"] == "down"


# --- AI drafting ---------------------------------------------------------------------------------

def test_ai_draft_is_503_when_not_enabled(client, auth, am, monkeypatch):
    monkeypatch.setattr(ai_draft, "enabled", lambda: False)
    auth(am)
    r = client.post("/api/ops/ai/draft-tasks", json={"text": "we promised TCS a report"})
    assert r.status_code == 503


def test_ai_draft_validates_against_the_roster(client, db, auth, am, worker, lead, team, client_row, monkeypatch):
    monkeypatch.setattr(ai_draft, "enabled", lambda: True)
    answer = {"tasks": [
        {"title": "Analyze September Meta", "department": "Acquisition", "assignee_id": worker.id,
         "reviewer_id": None, "due_date": "2000-01-01", "estimate_minutes": 90, "depends_on": None,
         "why": "Earl holds the Meta work."},
        {"title": "Add findings to report", "department": "Nope", "assignee_id": 999999,
         "due_date": (today_ph() + timedelta(days=2)).isoformat(), "estimate_minutes": 45, "depends_on": 1},
        {"title": ""},
    ]}
    import json
    monkeypatch.setattr(ai_draft, "_generate_text", lambda s, u: (json.dumps(answer), ""))
    auth(am)
    r = client.post("/api/ops/ai/draft-tasks", json={"text": "September Meta before Thursday", "client_id": client_row.id})
    assert r.status_code == 200, r.text
    props = r.json()["proposals"]
    assert len(props) == 2
    first, second = props
    assert first["assigned_team_id"] == team.id and first["assigned_to_id"] == worker.id
    assert first["due_date"] == today_ph().isoformat()            # a past date is pulled up to today
    assert any("reviewer is required" in w for w in first["warnings"])   # contributor, no reviewer
    assert second["assigned_team_id"] is None and second["assigned_to_id"] is None
    assert second["depends_on"] == 1


def test_ai_draft_needs_the_capability(client, auth, worker):
    auth(worker)
    assert client.post("/api/ops/ai/draft-tasks", json={"text": "anything at all"}).status_code == 403


# --- certifications + stage ---------------------------------------------------------------------

def test_certifications_are_granted_by_a_lead_and_read_by_the_person(client, db, auth, lead, worker):
    auth(lead)
    r = client.post(f"/api/ops/certifications/{worker.id}",
                    json={"key": "Meta Campaign Deployment", "label": "Meta Campaign Deployment"})
    assert r.status_code == 200 and r.json()["key"] == "meta_campaign_deployment" and r.json()["valid"]
    # Re-granting updates, never duplicates.
    client.post(f"/api/ops/certifications/{worker.id}",
                json={"key": "meta_campaign_deployment", "label": "Meta Campaign Deployment", "expires_at": "2020-01-01"})
    assert db.query(Certification).count() == 1
    auth(worker)
    mine = client.get("/api/ops/certifications").json()["certifications"]
    assert len(mine) == 1 and mine[0]["valid"] is False
    assert client.post(f"/api/ops/certifications/{worker.id}", json={"key": "x", "label": "y"}).status_code == 403


def test_stage_is_set_through_people_and_shows_on_cards(client, db, auth, admin, worker, task):
    auth(admin)
    assert client.patch(f"/api/people/{worker.id}", json={"stage": "astronaut"}).status_code == 400
    r = client.patch(f"/api/people/{worker.id}", json={"stage": "workstream_owner"})
    assert r.status_code == 200 and r.json()["stage"] == "workstream_owner"
    card = client.get(f"/api/tasks/{task.id}").json()
    assert card["assignee"]["stage"] == "workstream_owner"


def test_meta_lists_hold_kinds_and_stages(client, auth, worker):
    auth(worker)
    m = client.get("/api/ops/meta").json()
    assert m["hold_kinds"]["client"] == "Waiting on client"
    assert [s["key"] for s in m["stages"]] == C.WORKER_STAGES


def test_a_worked_on_and_waited_on_card_can_still_be_deleted(client, db, auth, make_user, make_team):
    """Found 2026-09-02, the go-live wipe: `task_sessions` carries a bare FK to tasks (no cascade),
    so deleting any card that ever had Start Work pressed raised an FK violation on Postgres — and a
    card another task was parked "waiting on" hit the same wall via `blocked_by_task_id`. The delete
    route clears both."""
    from app import constants as C
    from app.models import Task, TaskSession

    team = make_team(name="Ops")
    boss = make_user(C.ROLE_SUPER_ADMIN, name="Boss")
    worker = make_user(C.ROLE_EMPLOYEE, team_id=team.id, name="W")
    auth(worker)
    t1 = Task(title="Worked on", status=C.TASK_TODO, assigned_team_id=team.id, assigned_to_id=worker.id)
    db.add(t1)
    db.commit()
    assert client.post(f"/api/tasks/{t1.id}/sessions/start").status_code == 200
    auth(boss)
    t2 = client.post("/api/tasks", json={"title": "Waits on it"}).json()
    assert client.post(f"/api/tasks/{t2['id']}/park",
                       json={"kind": "task", "blocked_by_task_id": t1.id, "reason": "x"}).status_code == 200
    assert client.delete(f"/api/tasks/{t1.id}").json()["ok"]
    assert db.query(TaskSession).filter(TaskSession.task_id == t1.id).count() == 0
    left = db.get(Task, t2["id"])
    db.refresh(left)
    assert left.blocked_by_task_id is None

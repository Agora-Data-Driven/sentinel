"""The thin project layer (2026-09-02): named outcomes with milestones and linked tasks.

What must stay true:

* `projects.view` is a management read (team lead+ and the viewer seat); `projects.manage` is AM+.
  An employee gets a real 403, not hidden UI.
* Rollups are DERIVED: linking a task via `tasks.project_id` moves the counts; an overdue linked
  card turns the project red with the reason in words.
* Milestone "done" is a stamped transition (done_at / done_by), cleared on reopen — never typed.
* Deleting a project UNLINKS its tasks; the work itself survives.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from app import constants as C
from app.models import Task


@pytest.fixture
def am(make_user):
    return make_user(C.ROLE_ACCOUNT_MANAGER, name="Leo")


def _mk(client, **kw):
    body = {"name": "Phase One", "goal": "A replicable pod by October 1",
            "target_date": "2026-10-01",
            "milestones": [{"title": "Report Standard v1 used live"},
                           {"title": "Every client audited", "target_date": "2026-08-20"}]}
    body.update(kw)
    return client.post("/api/projects", json=body)


def test_view_is_managerial_and_manage_is_am_plus(client, auth, make_user):
    emp = make_user(C.ROLE_EMPLOYEE, name="Ana")
    lead = make_user(C.ROLE_TEAM_LEAD, name="Bong")
    auth(emp)
    assert client.get("/api/projects").status_code == 403
    assert _mk(client).status_code == 403
    auth(lead)
    assert client.get("/api/projects").status_code == 200
    assert _mk(client).status_code == 403        # a lead tracks, an AM+ shapes


def test_create_returns_the_whole_outcome(client, auth, am):
    auth(am)
    r = _mk(client)
    assert r.status_code == 200
    d = r.json()
    assert d["name"] == "Phase One" and d["status"] == "active"
    assert d["milestones_total"] == 2 and d["milestones_done"] == 0
    assert [m["title"] for m in d["milestones"]][0] == "Report Standard v1 used live"
    assert d["health"] == "amber"                # milestone "Every client audited" is past its date
    assert any("Every client audited" in w for w in d["why"])


def test_milestone_done_is_a_stamped_transition(client, auth, am):
    auth(am)
    mid = _mk(client).json()["milestones"][0]["id"]
    m = client.patch(f"/api/projects/milestones/{mid}", json={"done": True}).json()
    assert m["done"] and m["done_at"] and m["done_by"]["name"] == "Leo"
    m = client.patch(f"/api/projects/milestones/{mid}", json={"done": False}).json()
    assert not m["done"] and m["done_at"] is None and m["done_by"] is None


def test_linked_tasks_drive_the_rollup_and_the_health(client, db, auth, am):
    auth(am)
    pid = _mk(client, milestones=[]).json()["id"]
    t = client.post("/api/tasks", json={"title": "Audit Acme", "project_id": pid,
                                        "due_date": (date.today() - timedelta(days=3)).isoformat()})
    assert t.status_code == 200 and t.json()["project_id"] == pid
    d = client.get(f"/api/projects/{pid}").json()
    assert d["tasks_open"] == 1 and d["tasks_overdue"] == 1
    assert d["health"] == "red" and any("overdue" in w for w in d["why"])
    assert [x["id"] for x in d["open_tasks"]] == [t.json()["id"]]
    # The board can answer "this project's cards" too.
    ids = {x["id"] for x in client.get(f"/api/tasks?project_id={pid}").json()}
    assert ids == {t.json()["id"]}


def test_an_unknown_project_is_refused_not_dropped(client, auth, am):
    auth(am)
    r = client.post("/api/tasks", json={"title": "Orphan", "project_id": 99999})
    assert r.status_code == 400


def test_delete_unlinks_the_work_instead_of_deleting_it(client, db, auth, am):
    auth(am)
    pid = _mk(client, milestones=[]).json()["id"]
    tid = client.post("/api/tasks", json={"title": "Survives", "project_id": pid}).json()["id"]
    assert client.delete(f"/api/projects/{pid}").json()["ok"]
    task = db.get(Task, tid)
    db.refresh(task)
    assert task is not None and task.project_id is None


def test_status_moves_and_is_validated(client, auth, am):
    auth(am)
    pid = _mk(client).json()["id"]
    assert client.patch(f"/api/projects/{pid}", json={"status": "shipped"}).status_code == 400
    d = client.patch(f"/api/projects/{pid}", json={"status": "done"}).json()
    assert d["status"] == "done" and d["health"] == "done" and d["why"] == []

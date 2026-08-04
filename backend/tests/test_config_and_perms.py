"""Low-code config CRUD (services + task vocab) and the refined permission model."""
from __future__ import annotations

import pytest

from app import constants as C
from app.models import Task


def _task(db, **kw):
    t = Task(title=kw.pop("title", "T"), **kw)
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


# --- Config is seeded + served from the DB -------------------------------
def test_vocab_served_from_db_with_colors(client, make_user, auth):
    auth(make_user(C.ROLE_EMPLOYEE))
    v = client.get("/api/vocab").json()
    assert "To Do" in v["task_statuses"] and "Urgent" in v["priorities"]
    assert v["colors"]["priorities"]["Urgent"]  # a colour is present


def test_manage_config_is_super_admin_only(client, make_user, auth):
    auth(make_user(C.ROLE_ADMIN))  # admin is NOT super_admin
    assert client.get("/api/manage/service-templates").status_code == 403
    assert client.get("/api/manage/task-vocab?kind=status").status_code == 403


# --- Service templates CRUD ----------------------------------------------
def test_service_template_crud_and_seeding_into_task(client, make_user, auth):
    auth(make_user(C.ROLE_SUPER_ADMIN))
    # seeded catalog is present
    assert any(s["key"] == "google_meta_campaign" for s in client.get("/api/manage/service-templates").json())
    # create a new service with a recipe
    created = client.post("/api/manage/service-templates", json={
        "label": "Podcast Episode", "dept": "Lifecycle", "content_type": "Audio",
        "maintasks": [{"title": "Produce", "subs": [{"text": "Record"}, {"text": "Edit"}]}],
    })
    assert created.status_code == 200
    key = created.json()["key"]
    # it shows up in the New Task template catalog immediately (no redeploy)
    assert any(t["key"] == key for t in client.get("/api/tasks/templates").json())
    # creating a task from it seeds the breakdown
    task = client.post("/api/tasks", json={"title": "Ep 1", "service_key": key}).json()
    assert [m["title"] for m in task["maintasks"]] == ["Produce"]
    assert task["checklist_total"] == 2


def test_service_template_defaults_autofill_a_new_task(client, make_user, auth):
    """A service template can carry a default priority/description that seed onto a new task.

    🔴 `default_labels` is NOT one of them any more (decision D14, 2026-08-04): a task's single
    label is derived from its DEPARTMENT, so a per-template default can only ever be ignored. The
    column and the API field survive so old rows still read, but nothing applies them — asserted
    below, and in full in tests/test_task_labels.py.
    """
    auth(make_user(C.ROLE_SUPER_ADMIN))
    created = client.post("/api/manage/service-templates", json={
        "label": "Urgent Website Fix", "dept": "Development", "content_type": "Website",
        "maintasks": [{"title": "Fix", "subs": [{"text": "Patch"}]}],
        "default_priority": "Urgent", "default_labels": ["Dev"],
        "default_description": "Standard hotfix brief.",
    })
    assert created.status_code == 200
    body = created.json()
    assert body["default_priority"] == "Urgent"
    key = body["key"]
    # catalog exposes the defaults so the form can pre-fill them
    cat = next(t for t in client.get("/api/tasks/templates").json() if t["key"] == key)
    assert cat["default_priority"] == "Urgent"
    assert cat["default_description"] == "Standard hotfix brief."
    # a manager creating from it (leaving those fields blank) gets the defaults applied
    task = client.post("/api/tasks", json={"title": "Site down", "service_key": key}).json()
    assert task["priority"] == "Urgent"
    assert task["description"] == "Standard hotfix brief."
    # The template's stored "Dev" label is inert. No department was routed on this create, so the
    # task is genuinely unlabelled rather than wearing a retired vocabulary word.
    assert task["labels"] == []


def test_the_label_follows_the_routed_department_not_the_template(client, make_user, auth, make_team):
    """D14, stated against the service-template path: routing is what labels a task."""
    auth(make_user(C.ROLE_SUPER_ADMIN))
    team = make_team("Acquisition")
    key = client.post("/api/manage/service-templates", json={
        "label": "Campaign", "dept": "Acquisition",
        "maintasks": [{"title": "Build", "subs": [{"text": "Step"}]}],
        "default_labels": ["Ads"],
    }).json()["key"]
    task = client.post("/api/tasks", json={
        "title": "Q3", "service_key": key, "assigned_team_id": team.id,
    }).json()
    assert task["labels"] == ["Paid Media"]


def test_caller_values_win_over_template_defaults(client, make_user, auth):
    """Explicit fields on the create request are never overwritten by the template's defaults.

    Labels are the ONE exception, and deliberately so (D14): they are derived, so neither the
    template nor the caller gets a say.
    """
    auth(make_user(C.ROLE_SUPER_ADMIN))
    key = client.post("/api/manage/service-templates", json={
        "label": "Low Priority Job", "dept": "Lifecycle",
        "maintasks": [{"title": "Do", "subs": [{"text": "Step"}]}],
        "default_priority": "Urgent", "default_labels": ["Dev"], "default_description": "template brief",
    }).json()["key"]
    task = client.post("/api/tasks", json={
        "title": "Override", "service_key": key,
        "priority": "Low", "labels": ["Copy"], "description": "my brief",
    }).json()
    assert task["priority"] == "Low"
    assert task["description"] == "my brief"
    assert task["labels"] == []      # the caller's "Copy" is ignored; no department was routed


# --- Task vocab: create, rename-cascade, delete guard ---------------------
def test_status_rename_cascades_to_tasks(client, db, make_user, auth):
    auth(make_user(C.ROLE_SUPER_ADMIN))
    t = _task(db, status="To Do")
    todo = next(s for s in client.get("/api/manage/task-vocab?kind=status").json() if s["name"] == "To Do")
    assert client.patch(f"/api/manage/task-vocab/{todo['id']}", json={"name": "Backlog"}).status_code == 200
    db.expire_all()
    assert db.get(Task, t.id).status == "Backlog"       # existing task followed the rename


def test_delete_status_in_use_is_blocked(client, db, make_user, auth):
    auth(make_user(C.ROLE_SUPER_ADMIN))
    _task(db, status=C.TASK_BLOCKED)
    blocked = next(s for s in client.get("/api/manage/task-vocab?kind=status").json() if s["name"] == C.TASK_BLOCKED)
    assert client.delete(f"/api/manage/task-vocab/{blocked['id']}").status_code == 409  # in use


def test_retired_statuses_are_gone_and_their_tasks_moved(client, db, make_user, auth):
    """Retiring a status has to do BOTH halves, or work disappears.

    Dropping the name from the code defaults leaves the seeded `task_vocab` row in charge, so the
    column keeps rendering; deleting the row while a task still holds the name drops that task off
    the board entirely (renderBoard groups by the current status list). `retire_statuses` moves
    first, then deletes — and it runs on every boot, which is how this lands in prod.
    """
    from app.services import task_config

    auth(make_user(C.ROLE_SUPER_ADMIN))
    stranded = _task(db, status="For Review")
    # The retired names are re-created here to simulate a DB seeded before the removal.
    for name in task_config.RETIRED_STATUSES:
        client.post("/api/manage/task-vocab", json={"kind": "status", "name": name})

    task_config.retire_statuses(db)

    live = client.get("/api/vocab").json()["task_statuses"]
    assert not (set(task_config.RETIRED_STATUSES) & set(live))
    db.expire_all()
    assert db.get(Task, stranded.id).status == C.TASK_BLOCKED     # moved, not stranded
    assert db.get(Task, stranded.id).status in live               # ...onto a column that exists


def test_add_custom_priority_then_use_it(client, make_user, auth):
    auth(make_user(C.ROLE_SUPER_ADMIN))
    client.post("/api/manage/task-vocab", json={"kind": "priority", "name": "Critical", "color": "#B91C1C"})
    tid = client.post("/api/tasks", json={"title": "hot"}).json()["id"]
    # the new priority is now a valid value
    assert client.patch(f"/api/tasks/{tid}/priority", json={"priority": "Critical"}).status_code == 200


# --- Permission model refinements ----------------------------------------
def test_employee_create_cannot_assign_to_someone_else(client, db, make_user, auth):
    me = make_user(C.ROLE_EMPLOYEE)
    other = make_user(C.ROLE_EMPLOYEE)
    auth(me)
    task = client.post("/api/tasks", json={"title": "mine", "assigned_to_id": other.id}).json()
    assert task["assigned_to_id"] == me.id  # forced back to self


def test_employee_cannot_reassign_via_patch(client, db, make_user, auth):
    me = make_user(C.ROLE_EMPLOYEE)
    other = make_user(C.ROLE_EMPLOYEE)
    t = _task(db, assigned_to_id=me.id)
    auth(me)
    assert client.patch(f"/api/tasks/{t.id}", json={"assigned_to_id": other.id}).status_code == 403


def test_team_lead_can_prioritize_and_delete_own_team_only(client, db, make_user, make_team, auth):
    team_a = make_team(name="A")
    team_b = make_team(name="B")
    lead = make_user(C.ROLE_TEAM_LEAD, team_id=team_a.id)
    mine = _task(db, assigned_team_id=team_a.id)
    theirs = _task(db, assigned_team_id=team_b.id)
    auth(lead)
    assert client.patch(f"/api/tasks/{mine.id}/priority", json={"priority": C.PRIORITY_URGENT}).status_code == 200
    assert client.patch(f"/api/tasks/{theirs.id}/priority", json={"priority": C.PRIORITY_URGENT}).status_code == 403
    assert client.delete(f"/api/tasks/{mine.id}").status_code == 200
    assert client.delete(f"/api/tasks/{theirs.id}").status_code == 403


def test_sub_task_assignee_can_view_the_task(client, db, make_user, auth):
    import json
    helper = make_user(C.ROLE_EMPLOYEE)
    owner = make_user(C.ROLE_EMPLOYEE)
    mt = [{"id": "mt1", "title": "Phase", "subs": [{"id": "s1", "text": "do", "done": False, "assignee_id": helper.id}]}]
    t = _task(db, assigned_to_id=owner.id, maintasks_json=json.dumps(mt))
    auth(helper)  # not the task assignee, but assigned to a sub-task
    assert client.get(f"/api/tasks/{t.id}").status_code == 200

"""Service templates — GET /api/tasks/templates + auto-seeding the checklist on create.

Picking a service type on the New Task form seeds the whole checklist (and content type) server-side,
so a department gets a filled-in task instead of a blank one.
"""
from __future__ import annotations

from app import constants as C
from app.services import task_templates


def test_templates_catalog_endpoint(client, make_user, auth):
    auth(make_user(C.ROLE_ACCOUNT_MANAGER))
    r = client.get("/api/tasks/templates")
    assert r.status_code == 200
    cat = r.json()
    assert cat, "catalog should not be empty"
    keys = {t["key"] for t in cat}
    assert "google_meta_campaign" in keys
    depts = {t["dept"] for t in cat}
    # Every template's department is one of Sentinel's seeded teams.
    assert depts <= {"Acquisition", "Lifecycle", "Data Analyst", "Development"}


def test_create_seeds_maintasks_from_service_key(client, make_user, auth):
    auth(make_user(C.ROLE_ACCOUNT_MANAGER))
    r = client.post("/api/tasks", json={"title": "Q3 launch", "service_key": "google_meta_campaign"})
    assert r.status_code == 200
    task = r.json()
    tpl = task_templates.SEED_TEMPLATES["google_meta_campaign"]         # the seeded recipe
    assert task["content_type"] == tpl["content_type"]                 # content type auto-filled
    # Two-level breakdown: one main task per group, subs match the recipe.
    assert [m["title"] for m in task["maintasks"]] == [g[0] for g in tpl["groups"]]
    total_subs = sum(len(g[1]) for g in tpl["groups"])
    assert task["checklist_total"] == total_subs                       # progress counts all subs
    assert task["maintasks"][0]["subs"][0]["text"] == tpl["groups"][0][1][0]
    assert all(s["done"] is False for m in task["maintasks"] for s in m["subs"])


def test_explicit_checklist_wins_over_template(client, make_user, auth):
    auth(make_user(C.ROLE_ACCOUNT_MANAGER))
    r = client.post("/api/tasks", json={
        "title": "Custom", "service_key": "google_meta_campaign",
        "checklist": [{"text": "Only this", "done": False}],
    })
    assert r.status_code == 200
    assert r.json()["checklist_total"] == 1


def test_unknown_service_key_is_harmless(client, make_user, auth):
    auth(make_user(C.ROLE_ACCOUNT_MANAGER))
    r = client.post("/api/tasks", json={"title": "Blank", "service_key": "nope"})
    assert r.status_code == 200
    assert r.json()["checklist_total"] == 0


# --- Two-level breakdown editing -----------------------------------------
def test_maintasks_edit_assign_and_progress(client, make_user, auth):
    owner = make_user(C.ROLE_ACCOUNT_MANAGER)
    sub_owner = make_user(C.ROLE_EMPLOYEE, name="Sub Owner")
    auth(owner)
    tid = client.post("/api/tasks", json={"title": "Build"}).json()["id"]
    # Set a breakdown: one main task with two subs, one done, one assigned.
    r = client.patch(f"/api/tasks/{tid}", json={"maintasks": [
        {"title": "Phase 1", "assignee_id": owner.id, "subs": [
            {"text": "step a", "done": True},
            {"text": "step b", "done": False, "assignee_id": sub_owner.id},
        ]},
    ]})
    assert r.status_code == 200
    task = r.json()
    assert len(task["maintasks"]) == 1
    m = task["maintasks"][0]
    assert m["title"] == "Phase 1"
    assert m["assignee"]["id"] == owner.id           # main-task owner resolved
    assert m["subs"][0]["id"] and m["subs"][1]["id"]  # ids assigned server-side
    assert m["subs"][1]["assignee"]["name"] == "Sub Owner"  # sub-task assignee resolved
    assert task["checklist_total"] == 2 and task["checklist_done"] == 1  # progress spans subs


def test_legacy_flat_checklist_migrates_to_a_main_task(client, db, make_user, auth):
    from app.models import Task
    t = Task(title="Legacy", checklist_json='[{"text": "old", "done": true}]', maintasks_json="[]")
    db.add(t); db.commit(); db.refresh(t)
    auth(make_user(C.ROLE_ADMIN))
    task = client.get(f"/api/tasks/{t.id}").json()
    assert len(task["maintasks"]) == 1
    assert task["maintasks"][0]["subs"][0]["text"] == "old"
    assert task["checklist_total"] == 1 and task["checklist_done"] == 1

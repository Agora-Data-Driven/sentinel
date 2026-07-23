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


def test_create_seeds_checklist_from_service_key(client, make_user, auth):
    auth(make_user(C.ROLE_ACCOUNT_MANAGER))
    r = client.post("/api/tasks", json={"title": "Q3 launch", "service_key": "google_meta_campaign"})
    assert r.status_code == 200
    task = r.json()
    expected = task_templates.get("google_meta_campaign")
    assert task["content_type"] == expected["content_type"]          # content type auto-filled
    assert task["checklist_total"] == len(expected["checklist"])     # checklist seeded in full
    assert all(item["done"] is False for item in task["checklist"])
    assert task["checklist"][0]["text"] == expected["checklist"][0]


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

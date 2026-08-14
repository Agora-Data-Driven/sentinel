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


# --- Applying a template to an EXISTING task (2026-08-14) ----------------------------------------
#
# 🔴 Templates could only ever be applied at CREATE time, so the commonest card on this board — a
# quick-added title, which §3 of the task-placement guidelines says is the RIGHT way to log work that
# comes up during the day — could never be given a breakdown without retyping every step. The recipe
# book only served people who opened the full New Task form first.

def _quick_task(client, title="Something that came up"):
    """A card raised the common way: a title and nothing else."""
    r = client.post("/api/tasks", json={"title": title})
    assert r.status_code == 200
    assert r.json()["maintasks"] == [], "precondition: a quick-added card has no breakdown"
    return r.json()["id"]


def test_a_template_can_be_applied_to_an_existing_task(client, make_user, auth):
    auth(make_user(C.ROLE_ACCOUNT_MANAGER))
    tid = _quick_task(client)
    r = client.post(f"/api/tasks/{tid}/apply-template",
                    json={"service_key": "google_meta_campaign", "mode": "append"})
    assert r.status_code == 200
    tpl = task_templates.SEED_TEMPLATES["google_meta_campaign"]
    body = r.json()
    assert [m["title"] for m in body["maintasks"]] == [g[0] for g in tpl["groups"]]
    assert body["content_type"] == tpl["content_type"]   # filled a blank
    assert body["checklist_total"] == sum(len(g[1]) for g in tpl["groups"])


def test_append_keeps_the_work_already_there_including_ticks(client, make_user, auth, db):
    """`append` must be genuinely non-destructive — that is the only reason it is the mode the drawer
    offers on a card that already has a breakdown."""
    auth(make_user(C.ROLE_ACCOUNT_MANAGER))
    tid = _quick_task(client)
    client.patch(f"/api/tasks/{tid}", json={"maintasks": [
        {"title": "Work already done", "subs": [{"text": "First step", "done": True}]}]})

    r = client.post(f"/api/tasks/{tid}/apply-template",
                    json={"service_key": "website_fix", "mode": "append"})
    assert r.status_code == 200
    mts = r.json()["maintasks"]
    assert mts[0]["title"] == "Work already done"
    assert mts[0]["subs"][0]["done"] is True, "an existing tick must survive"
    assert len(mts) == 1 + len(task_templates.SEED_TEMPLATES["website_fix"]["groups"])


def test_replace_discards_the_old_breakdown(client, make_user, auth):
    auth(make_user(C.ROLE_ACCOUNT_MANAGER))
    tid = _quick_task(client)
    client.patch(f"/api/tasks/{tid}", json={"maintasks": [
        {"title": "Wrong recipe", "subs": [{"text": "Nope"}]}]})
    r = client.post(f"/api/tasks/{tid}/apply-template",
                    json={"service_key": "website_fix", "mode": "replace"})
    assert r.status_code == 200
    titles = [m["title"] for m in r.json()["maintasks"]]
    assert "Wrong recipe" not in titles
    assert titles == [g[0] for g in task_templates.SEED_TEMPLATES["website_fix"]["groups"]]


def test_mode_is_required_because_one_of_them_destroys_work(client, make_user, auth):
    """🔴 No default. `append` and `replace` differ in whether they discard ticks and step owners, and
    a wrong guess there is unrecoverable — so the caller has to say which one they mean."""
    auth(make_user(C.ROLE_ACCOUNT_MANAGER))
    tid = _quick_task(client)
    assert client.post(f"/api/tasks/{tid}/apply-template",
                       json={"service_key": "website_fix"}).status_code == 422


def test_the_seeded_steps_are_unowned_so_this_is_not_a_delegation_hole(client, make_user, auth, db):
    """🔴 Naming somebody on a step puts the card on their board (`task_perms.is_assigned`), so any
    new writer of `maintasks` is a potential way past the delegation guard — this board has shipped
    that hole twice. This route is safe only because the recipe carries no owners. If a template ever
    grows default owners, this test fails and the route needs `foreign_owner_changes`."""
    auth(make_user(C.ROLE_ACCOUNT_MANAGER))
    tid = _quick_task(client)
    r = client.post(f"/api/tasks/{tid}/apply-template",
                    json={"service_key": "google_meta_campaign", "mode": "append"})
    mts = r.json()["maintasks"]
    assert all(m.get("assignee_id") is None for m in mts)
    assert all(s.get("assignee_id") is None for m in mts for s in m["subs"])
    assert all(s["done"] is False for m in mts for s in m["subs"])


def test_an_employee_cannot_reshape_a_colleagues_card(client, auth, make_user, make_team, db):
    """It follows `can_edit`, which since 2026-08-14 is NOT `can_view` for an employee — their board
    carries the whole department read-only."""
    team = make_team(name="Acquisition")
    owner = make_user(C.ROLE_EMPLOYEE, team_id=team.id, name="Owner")
    bystander = make_user(C.ROLE_EMPLOYEE, team_id=team.id, name="Bystander")
    auth(owner)
    tid = client.post("/api/tasks", json={"title": "Mine", "assigned_team_id": team.id,
                                          "assigned_to_id": owner.id}).json()["id"]
    auth(bystander)
    assert tid in [c["id"] for c in client.get("/api/tasks").json()], "visible to the department"
    assert client.post(f"/api/tasks/{tid}/apply-template",
                       json={"service_key": "website_fix", "mode": "replace"}).status_code == 403


def test_an_unknown_or_deactivated_service_is_a_404(client, make_user, auth):
    auth(make_user(C.ROLE_ACCOUNT_MANAGER))
    tid = _quick_task(client)
    assert client.post(f"/api/tasks/{tid}/apply-template",
                       json={"service_key": "no_such_service", "mode": "append"}).status_code == 404


def test_an_atrium_card_is_refused_with_a_reason(client, make_user, auth):
    """Its breakdown lives in Atrium's workspace JSON, not in `maintasks_json` — `_own_row` refuses
    every lifecycle action on one, and this route inherits that rather than half-working."""
    auth(make_user(C.ROLE_ACCOUNT_MANAGER))
    r = client.post("/api/tasks/atrium:honeytribe:tk_1/apply-template",
                    json={"service_key": "website_fix", "mode": "append"})
    assert r.status_code == 400

"""Editing an Atrium-owned card from Sentinel's board (the routes, not the transport).

Before 2026-07-29 the board could show a client's Atrium card and drag it, but opening one said
"Card details live in Atrium — open it there to view or edit". These pin the behaviour that
replaced that dead end: every task route recognises the "atrium:<client_key>:<task_id>" id and
routes the write to Atrium, with the two manager-only decisions still gated, and a bridge failure
never disguised as a missing card.

The bridge itself is stubbed here (test_atrium_bridge.py covers the transport + the mapping).

An Atrium card is a MANAGER surface since 2026-07-30 (task_perms.can_view_atrium — it belongs to no
Sentinel user, so it has no place on an intern's "assigned to me" board), which is why the actors
below start at team lead. test_task_visibility.py pins that scoping itself.
"""
from __future__ import annotations

from app import constants as C
from app.services import atrium_tasks

CARD = "atrium:riverdance-rv:tk_9"


def _envelope(**over):
    task = {
        "atrium_id": "riverdance-rv:tk_9", "task_id": "tk_9", "client_key": "riverdance-rv",
        "client_name": "Riverdance RV", "title": "audit ads", "status": "In Progress",
        "priority": "Medium", "client_facing": True, "department": "acquisition",
        "department_label": "Acquisition", "lead_id": "leo@agora.ph", "lead_name": "Leo",
        "maintasks": [], "comments": [], "history": [],
    }
    task.update(over)
    return {"task": task, "roster": [{"id": "leo@agora.ph", "name": "Leo"}],
            "departments": [{"key": "acquisition", "label": "Acquisition"}]}


def test_opening_a_client_card_returns_a_drawer_shaped_detail(client, auth, make_user, monkeypatch):
    auth(make_user(C.ROLE_TEAM_LEAD))
    monkeypatch.setattr(atrium_tasks, "fetch_task", lambda k, t: (_envelope(), ""))
    r = client.get(f"/api/tasks/{CARD}")
    assert r.status_code == 200
    d = r.json()
    assert d["source"] == "atrium" and d["id"] == CARD
    assert d["atrium_roster"] and d["atrium_departments"]     # the pickers the form renders from


def test_a_broken_bridge_is_never_reported_as_a_deleted_card(client, auth, make_user, monkeypatch):
    auth(make_user(C.ROLE_ADMIN))
    monkeypatch.setattr(atrium_tasks, "fetch_task", lambda k, t: ({}, "Couldn't reach Atrium"))
    assert client.get(f"/api/tasks/{CARD}").status_code == 502
    monkeypatch.setattr(atrium_tasks, "fetch_task", lambda k, t: ({}, atrium_tasks.GONE))
    assert client.get(f"/api/tasks/{CARD}").status_code == 404


def test_an_edit_is_translated_and_written_to_atrium(client, auth, make_user, monkeypatch):
    auth(make_user(C.ROLE_ACCOUNT_MANAGER))
    seen = {}

    def _edit(key, tid, fields, actor=""):
        seen.update({"key": key, "tid": tid, "fields": fields, "actor": actor})
        return _envelope(title=fields.get("title", "audit ads")), ""

    monkeypatch.setattr(atrium_tasks, "edit_task", _edit)
    r = client.patch(f"/api/tasks/{CARD}", json={
        "title": "Renamed here", "client_facing_notes": "client reads this",
        "atrium_department": "acquisition", "atrium_lead_id": "leo@agora.ph",
        "due_date": "2026-09-30", "on_hold": True, "hold_reason": "waiting on assets",
    })
    assert r.status_code == 200
    assert (seen["key"], seen["tid"]) == ("riverdance-rv", "tk_9")
    # Atrium's field names go over the wire, and nothing Sentinel-only tags along.
    assert seen["fields"]["client_note"] == "client reads this"
    assert seen["fields"]["department"] == "acquisition"
    assert seen["fields"]["due_date"] == "2026-09-30" and seen["fields"]["on_hold"] is True
    assert r.json()["title"] == "Renamed here"


def test_client_visibility_and_priority_stay_manager_decisions(client, auth, make_user, monkeypatch):
    """Everyone who SEES the card may edit its content; these two are management calls, the same way
    they are on a Sentinel row (can_bridge / can_prioritize). A team lead is the test's non-manager:
    they see client cards, but neither of these two decisions is theirs."""
    seen = {}

    def _edit(key, tid, fields, actor=""):
        seen["fields"] = fields
        return _envelope(), ""

    monkeypatch.setattr(atrium_tasks, "edit_task", _edit)

    auth(make_user(C.ROLE_TEAM_LEAD))
    assert client.patch(f"/api/tasks/{CARD}", json={"atrium_visible": True}).status_code == 403
    # A priority they may not set is dropped, not an error — the rest of the edit still saves.
    r = client.patch(f"/api/tasks/{CARD}", json={"title": "still fine", "priority": "Urgent"})
    assert r.status_code == 200 and "priority" not in seen["fields"]
    assert seen["fields"]["title"] == "still fine"

    auth(make_user(C.ROLE_ADMIN, email="boss@test.ph"))
    r = client.patch(f"/api/tasks/{CARD}", json={"atrium_visible": False, "priority": "Urgent"})
    assert r.status_code == 200
    assert seen["fields"]["client_facing"] is False and seen["fields"]["priority"] == "Urgent"


def test_only_a_manager_may_delete_a_client_card(client, auth, make_user, monkeypatch):
    calls = []
    monkeypatch.setattr(atrium_tasks, "remove_task",
                        lambda k, t, actor="": (calls.append((k, t)), (True, ""))[1])
    auth(make_user(C.ROLE_TEAM_LEAD))
    assert client.delete(f"/api/tasks/{CARD}").status_code == 403
    assert calls == []                      # refused before the bridge was ever called
    auth(make_user(C.ROLE_ACCOUNT_MANAGER, email="am@test.ph"))
    assert client.delete(f"/api/tasks/{CARD}").status_code == 200
    assert calls == [("riverdance-rv", "tk_9")]


def test_a_comment_goes_to_atriums_thread_under_the_sentinel_author(client, auth, make_user, monkeypatch):
    user = auth(make_user(C.ROLE_TEAM_LEAD, name="Ana Cruz"))
    seen = {}

    def _comment(key, tid, body, actor="", actor_name=""):
        seen.update({"body": body, "actor": actor, "actor_name": actor_name})
        return {"id": "cm_1", "body": body, "created_at": "2026-07-29T01:00:00Z"}, ""

    monkeypatch.setattr(atrium_tasks, "comment_task", _comment)
    r = client.post(f"/api/tasks/{CARD}/comments", json={"body": "on it"})
    assert r.status_code == 200
    assert seen["body"] == "on it" and seen["actor"] == user.email and seen["actor_name"] == "Ana Cruz"
    # Echoed back as the Sentinel user, so their avatar appears in the thread immediately.
    assert r.json()["author"]["name"] == "Ana Cruz"


def test_a_change_request_can_be_resolved_here_but_only_exists_on_client_cards(
        client, auth, make_user, monkeypatch, db):
    from app.models import Task

    auth(make_user(C.ROLE_ACCOUNT_MANAGER))
    monkeypatch.setattr(atrium_tasks, "resolve_change_request",
                        lambda k, t, c, actor="": (True, ""))
    assert client.post(f"/api/tasks/{CARD}/comments/cm_1/resolve").status_code == 200

    row = Task(title="internal", status="To Do", priority="Medium")
    db.add(row)
    db.commit()
    assert client.post(f"/api/tasks/{row.id}/comments/cm_1/resolve").status_code == 404


def test_atrium_only_fields_never_touch_a_sentinel_row(client, auth, make_user, db):
    """TaskUpdateIn carries a few Atrium-only fields. Sent at a Sentinel task they must be dropped,
    not setattr'd onto a model that has no such column."""
    from app.models import Task

    auth(make_user(C.ROLE_ADMIN))
    row = Task(title="internal", status="To Do", priority="Medium")
    db.add(row)
    db.commit()
    r = client.patch(f"/api/tasks/{row.id}", json={
        "title": "renamed", "start_date": "2026-09-30", "on_hold": True,
        "atrium_department": "acquisition", "atrium_lead_id": "leo@agora.ph",
    })
    assert r.status_code == 200 and r.json()["title"] == "renamed"
    db.expire_all()
    fresh = db.get(Task, row.id)
    assert fresh.title == "renamed"
    assert not hasattr(fresh, "atrium_department")

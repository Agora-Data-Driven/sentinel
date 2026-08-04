"""Bulk actions (M7, WP 5.4): one change applied to many tasks.

Triage on a 60-card board used to be one drawer at a time.

🔴 PARTIAL SUCCESS IS THE CONTRACT. A selection is a rectangle drawn over a board, so it will
routinely contain a card the actor may not move, one already in the target column, and one the
review gate (D5) is holding back. Refusing the whole batch over one of those would make the
feature useless on exactly the boards it exists for — so each task is judged alone and the
response says what happened to each.

The guarantee that matters: bulk is NOT a way around a guard. Every permission is the same
per-task predicate the single-task routes use, and a bulk move runs through the same
`_apply_status`, so the history, the completion stamp, the Atrium projection and the audit row are
identical however the move was made.
"""
from __future__ import annotations

from app import constants as C
from app.models import Task


def _task(db, user, **kw):
    body = {"title": "T", "status": "To Do", "priority": "Medium", "created_by_id": user.id}
    body.update(kw)
    t = Task(**body)
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def _bulk(client, ids, op, value):
    return client.post("/api/tasks/bulk", json={"ids": ids, "op": op, "value": value})


# --- the happy path -----------------------------------------------------------------------------

def test_moves_many_tasks_at_once(client, auth, make_user, db):
    u = auth(make_user(C.ROLE_ADMIN))
    ids = [_task(db, u).id for _ in range(3)]

    r = _bulk(client, ids, "status", "In Progress")
    assert r.status_code == 200, r.text
    assert sorted(r.json()["updated"]) == sorted(ids)
    for tid in ids:
        assert db.get(Task, tid).status == "In Progress"


def test_sets_priority_in_bulk(client, auth, make_user, db):
    u = auth(make_user(C.ROLE_ADMIN))
    ids = [_task(db, u).id for _ in range(2)]
    assert _bulk(client, ids, "priority", "Urgent").json()["counts"]["updated"] == 2
    assert all(db.get(Task, i).priority == "Urgent" for i in ids)


def test_assigns_and_unassigns_in_bulk(client, auth, make_user, db, make_team):
    team = make_team("Acquisition")
    u = auth(make_user(C.ROLE_ADMIN))
    victim = make_user(C.ROLE_EMPLOYEE, team_id=team.id)
    ids = [_task(db, u).id for _ in range(2)]

    assert _bulk(client, ids, "assignee", victim.id).json()["counts"]["updated"] == 2
    assert all(db.get(Task, i).assigned_to_id == victim.id for i in ids)

    # Unassigning is a real triage action, so null is a legitimate value, not a missing one.
    assert _bulk(client, ids, "assignee", None).json()["counts"]["updated"] == 2
    assert all(db.get(Task, i).assigned_to_id is None for i in ids)


# --- partial success ----------------------------------------------------------------------------

def test_a_task_already_in_the_target_is_skipped_not_failed(client, auth, make_user, db):
    u = auth(make_user(C.ROLE_ADMIN))
    moving = _task(db, u)
    already = _task(db, u, status="In Progress")

    body = _bulk(client, [moving.id, already.id], "status", "In Progress").json()
    assert body["updated"] == [moving.id]
    assert [s["id"] for s in body["skipped"]] == [already.id]
    assert body["skipped"][0]["reason"] == "Already there"


def test_an_unknown_id_is_skipped_and_the_rest_still_move(client, auth, make_user, db):
    u = auth(make_user(C.ROLE_ADMIN))
    real = _task(db, u)
    body = _bulk(client, [real.id, 999999], "status", C.TASK_BLOCKED).json()
    assert body["updated"] == [real.id]
    assert body["skipped"] == [{"id": 999999, "reason": "Not found"}]


def test_duplicate_ids_are_collapsed(client, auth, make_user, db):
    u = auth(make_user(C.ROLE_ADMIN))
    t = _task(db, u)
    body = _bulk(client, [t.id, t.id, t.id], "status", C.TASK_BLOCKED).json()
    assert body["updated"] == [t.id]      # not three moves, and no "Already there" noise


# --- bulk is not a way around a guard -------------------------------------------------------------

def test_permission_is_enforced_per_task(client, auth, make_user, db, make_team):
    """An employee's selection may include a colleague's card; only their own may move."""
    team = make_team("Acquisition")
    me = auth(make_user(C.ROLE_EMPLOYEE, team_id=team.id))
    mine = _task(db, me, assigned_to_id=me.id)
    someone_else = _task(db, me, assigned_to_id=make_user(C.ROLE_EMPLOYEE, team_id=team.id).id)

    body = _bulk(client, [mine.id, someone_else.id], "status", "In Progress").json()
    assert body["updated"] == [mine.id]
    assert [s["id"] for s in body["skipped"]] == [someone_else.id]
    assert db.get(Task, someone_else.id).status == "To Do"


def test_priority_still_needs_a_lead_or_manager(client, auth, make_user, db, make_team):
    team = make_team("Acquisition")
    me = auth(make_user(C.ROLE_EMPLOYEE, team_id=team.id))
    t = _task(db, me, assigned_to_id=me.id)
    body = _bulk(client, [t.id], "priority", "Urgent").json()
    assert body["updated"] == []
    assert db.get(Task, t.id).priority == "Medium"


def test_assigning_someone_else_still_needs_delegation_rights(client, auth, make_user, db, make_team):
    team = make_team("Acquisition")
    me = auth(make_user(C.ROLE_EMPLOYEE, team_id=team.id))
    other = make_user(C.ROLE_EMPLOYEE, team_id=team.id)
    t = _task(db, me, assigned_to_id=me.id)

    assert _bulk(client, [t.id], "assignee", other.id).json()["updated"] == []
    # ...but picking work up yourself is self-assignment, which everyone may do.
    t2 = _task(db, me)
    assert _bulk(client, [t2.id], "assignee", me.id).json()["updated"] == [t2.id]


# --- validation ---------------------------------------------------------------------------------

def test_an_invalid_target_is_the_callers_mistake_not_a_per_task_outcome(client, auth, make_user, db):
    u = auth(make_user(C.ROLE_ADMIN))
    t = _task(db, u)
    assert _bulk(client, [t.id], "status", "Nonexistent").status_code == 400
    assert _bulk(client, [t.id], "priority", "Nonexistent").status_code == 400
    assert _bulk(client, [t.id], "assignee", 999999).status_code == 400


def test_an_empty_selection_is_rejected(client, auth, make_user):
    auth(make_user(C.ROLE_ADMIN))
    assert _bulk(client, [], "status", C.TASK_BLOCKED).status_code == 400


def test_an_unknown_op_is_rejected_by_the_schema(client, auth, make_user, db):
    u = auth(make_user(C.ROLE_ADMIN))
    t = _task(db, u)
    assert client.post("/api/tasks/bulk",
                       json={"ids": [t.id], "op": "delete", "value": "x"}).status_code == 422


def test_bulk_writes_history_like_a_single_move(client, auth, make_user, db):
    """The whole point of routing through _apply_status: a bulk move is indistinguishable from a
    drag afterwards, so nothing downstream has to know which one happened."""
    u = auth(make_user(C.ROLE_ADMIN))
    t = _task(db, u)
    _bulk(client, [t.id], "status", "In Progress")
    detail = client.get(f"/api/tasks/{t.id}").json()
    assert any(h["field"] == "status" and h["new_value"] == "In Progress" for h in detail["history"])

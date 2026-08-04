"""Adopting Atrium-origin cards into linked Sentinel rows (WP 3.4, §4).

Cards typed into the old console board — or filed by a client before D3 routed that to intake —
have no Sentinel row. They render read-only over the bridge, cannot be assigned, reviewed, parked
or counted, and 4.3 is blocked until they have Sentinel assignees to be scoped by.

🔴 This is the one work package that touches LIVE CLIENT DATA, so the safety properties are the
thing under test, not an afterthought:

* plan() writes NOTHING and says exactly what apply() would do, with a reason for every skip;
* plan and apply are DIFFERENT functions — there is no `dry_run=False` to pass by accident;
* every created row carries a batch id, so a run is reversible;
* revert() refuses rows that have been worked on since — undoing those would destroy real work;
* nothing is ever written to Atrium, so the worst case is orphaned Sentinel rows, not damaged
  client-visible data;
* adoption is PER CLIENT: a mistake is one workspace's problem.

Atrium is stubbed throughout — a test must never depend on a live sister service.
"""
from __future__ import annotations

from unittest.mock import patch

from app import constants as C
from app.models import Client, Task, TaskComment
from app.services import task_adoption

CARDS = [
    {"task_id": "a1", "title": "Homepage banner", "status": "To Do",
     "priority": "Medium", "due_date": "2026-09-01", "client_facing": True},
    {"task_id": "a2", "title": "Email flow", "status": "In Progress",
     "priority": "Urgent", "client_facing": True},
]


def _stub(cards=None):
    return patch("app.services.atrium_tasks.fetch_tasks", return_value=list(
        CARDS if cards is None else cards))


def _client(db, key="acme"):
    row = Client(name="Acme", atrium_client_id=key)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


# --- plan writes nothing ---------------------------------------------------------------------

def test_plan_reports_what_would_happen_and_writes_nothing(db, make_user):
    _client(db)
    make_user(C.ROLE_SUPER_ADMIN)
    with _stub():
        out = task_adoption.plan(db, "acme")
    assert out["counts"]["adopt"] == 2
    assert [c["atrium_id"] for c in out["adopt"]] == ["a1", "a2"]
    assert db.query(Task).count() == 0, "plan must not create anything"


def test_plan_requires_a_client(db):
    try:
        task_adoption.plan(db, "")
    except ValueError:
        return
    raise AssertionError("adoption must be per client")


def test_plan_explains_every_skip(db, make_user):
    _client(db)
    make_user(C.ROLE_SUPER_ADMIN)
    cards = [
        {"task_id": "", "title": "no id", "status": "To Do"},
        {"task_id": "a9", "title": "bad status", "status": "Nonexistent Column"},
    ]
    with _stub(cards):
        out = task_adoption.plan(db, "acme")
    assert out["counts"]["adopt"] == 0
    reasons = [s["reason"] for s in out["skip"]]
    assert any(task_adoption.SKIP_NO_ID in r for r in reasons)
    assert any(task_adoption.SKIP_NO_STAGE in r for r in reasons)


def test_an_already_adopted_card_is_skipped(db, make_user):
    owner = _client(db)
    u = make_user(C.ROLE_SUPER_ADMIN)
    db.add(Task(title="already", status="To Do", priority="Medium", created_by_id=u.id,
                client_id=owner.id, atrium_task_id="a1"))
    db.commit()
    with _stub():
        out = task_adoption.plan(db, "acme")
    assert out["counts"]["adopt"] == 1
    assert out["skip"][0]["reason"] == task_adoption.SKIP_LINKED


def test_another_clients_card_does_not_look_already_adopted(db, make_user):
    """🔴 `atrium_task_id` is only unique WITHIN a workspace. Comparing globally would report a
    card as adopted because a DIFFERENT client happens to have one with the same id."""
    acme = _client(db, "acme")
    other = Client(name="Other", atrium_client_id="other")
    db.add(other)
    db.commit()
    u = make_user(C.ROLE_SUPER_ADMIN)
    db.add(Task(title="other's a1", status="To Do", priority="Medium", created_by_id=u.id,
                client_id=other.id, atrium_task_id="a1"))
    db.commit()
    with _stub():
        out = task_adoption.plan(db, "acme")
    assert out["counts"]["adopt"] == 2, "acme's a1 was wrongly treated as adopted"
    assert acme is not None


# --- apply ---------------------------------------------------------------------------------------

def test_apply_creates_linked_rows_stamped_with_the_batch(db, make_user):
    owner = _client(db)
    u = make_user(C.ROLE_SUPER_ADMIN)
    with _stub():
        out = task_adoption.apply(db, "acme", "batch-1", u)
    assert out["counts"]["created"] == 2
    rows = db.query(Task).all()
    assert {t.atrium_task_id for t in rows} == {"a1", "a2"}
    assert all(t.adoption_batch == "batch-1" for t in rows)
    assert all(t.client_id == owner.id for t in rows)
    assert all(t.atrium_visible for t in rows), "an existing Atrium card is published by definition"


def test_apply_never_writes_to_atrium(db, make_user):
    """The card stays as it is and becomes the projection (§4). The worst case of a bad run is
    orphaned Sentinel rows, which revert removes — never damaged client-visible data."""
    _client(db)
    u = make_user(C.ROLE_SUPER_ADMIN)
    with _stub(), \
         patch("app.services.atrium_tasks.edit_task") as edit, \
         patch("app.services.atrium_tasks.add_task") as add, \
         patch("app.services.atrium_tasks.move_task") as move, \
         patch("app.services.atrium_tasks.remove_task") as rm:
        task_adoption.apply(db, "acme", "batch-1", u)
    assert not edit.called and not add.called and not move.called and not rm.called


def test_apply_is_not_reachable_by_passing_a_flag_to_plan():
    """plan and apply are different functions on purpose — there is no dry_run to get wrong."""
    import inspect
    assert "dry_run" not in inspect.signature(task_adoption.plan).parameters
    assert "dry_run" not in inspect.signature(task_adoption.apply).parameters


def test_apply_needs_a_batch_id(db, make_user):
    _client(db)
    u = make_user(C.ROLE_SUPER_ADMIN)
    with _stub():
        try:
            task_adoption.apply(db, "acme", "", u)
        except ValueError:
            return
    raise AssertionError("a run with no batch id would not be reversible")


def test_running_twice_does_not_duplicate(db, make_user):
    _client(db)
    u = make_user(C.ROLE_SUPER_ADMIN)
    with _stub():
        task_adoption.apply(db, "acme", "batch-1", u)
        second = task_adoption.apply(db, "acme", "batch-2", u)
    assert second["counts"]["created"] == 0
    assert db.query(Task).count() == 2


# --- revert ----------------------------------------------------------------------------------------

def test_revert_removes_exactly_that_run(db, make_user):
    _client(db)
    u = make_user(C.ROLE_SUPER_ADMIN)
    db.add(Task(title="human's own", status="To Do", priority="Medium", created_by_id=u.id))
    db.commit()
    with _stub():
        task_adoption.apply(db, "acme", "batch-1", u)

    out = task_adoption.revert(db, "batch-1")
    assert out["counts"]["removed"] == 2
    remaining = db.query(Task).all()
    assert len(remaining) == 1 and remaining[0].title == "human's own"


def test_revert_keeps_a_row_somebody_has_worked_on(db, make_user):
    """🔴 Undoing an import must never destroy real work — and the operator has to HEAR about it,
    not have it silently skipped."""
    _client(db)
    u = make_user(C.ROLE_SUPER_ADMIN)
    with _stub():
        task_adoption.apply(db, "acme", "batch-1", u)
    worked_on = db.query(Task).filter(Task.atrium_task_id == "a1").one()
    db.add(TaskComment(task_id=worked_on.id, author_id=u.id, body="started on this"))
    db.commit()

    out = task_adoption.revert(db, "batch-1")
    assert out["counts"]["removed"] == 1
    assert out["counts"]["kept"] == 1
    assert "comments" in out["kept"][0]["reason"]
    assert db.query(Task).filter(Task.id == worked_on.id).count() == 1


def test_revert_keeps_an_assigned_row(db, make_user, make_team):
    team = make_team("Acquisition")
    _client(db)
    u = make_user(C.ROLE_SUPER_ADMIN)
    with _stub():
        task_adoption.apply(db, "acme", "batch-1", u)
    row = db.query(Task).filter(Task.atrium_task_id == "a2").one()
    row.assigned_team_id = team.id
    db.commit()
    out = task_adoption.revert(db, "batch-1")
    assert [k["task_id"] for k in out["kept"]] == [row.id]


# --- the endpoints ------------------------------------------------------------------------------

def test_the_endpoints_are_super_admin_only(client, auth, make_user):
    auth(make_user(C.ROLE_ADMIN))            # admin is NOT enough
    assert client.get("/api/tasks/adoption/plan?client=acme").status_code == 403
    assert client.post("/api/tasks/adoption/apply",
                       json={"client": "acme", "confirm": "acme"}).status_code == 403
    assert client.post("/api/tasks/adoption/revert", json={"batch": "b"}).status_code == 403


def test_apply_refuses_without_a_matching_confirmation(client, auth, make_user, db):
    _client(db)
    auth(make_user(C.ROLE_SUPER_ADMIN))
    with _stub():
        r = client.post("/api/tasks/adoption/apply", json={"client": "acme", "confirm": "wrong"})
    assert r.status_code == 400
    assert db.query(Task).count() == 0


def test_the_plan_endpoint_writes_nothing(client, auth, make_user, db):
    _client(db)
    auth(make_user(C.ROLE_SUPER_ADMIN))
    with _stub():
        r = client.get("/api/tasks/adoption/plan?client=acme")
    assert r.status_code == 200 and r.json()["counts"]["adopt"] == 2
    assert db.query(Task).count() == 0


def test_the_full_endpoint_round_trip(client, auth, make_user, db):
    _client(db)
    auth(make_user(C.ROLE_SUPER_ADMIN))
    with _stub():
        applied = client.post("/api/tasks/adoption/apply",
                              json={"client": "acme", "confirm": "acme", "batch": "b7"})
    assert applied.status_code == 200 and applied.json()["counts"]["created"] == 2
    reverted = client.post("/api/tasks/adoption/revert", json={"batch": "b7"})
    assert reverted.json()["counts"]["removed"] == 2
    assert db.query(Task).count() == 0

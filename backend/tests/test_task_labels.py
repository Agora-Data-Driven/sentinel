"""Labels are DERIVED from the department, never chosen (decision D14).

A task carries exactly ONE label and nobody picks it: it is computed from the assigned department,
using the same mapping Atrium has always used (`main.TASK_DEPT_LABEL` there,
`constants.TASK_DEPT_LABEL` here). The old hand-picked vocabulary — Design / Copy / Ads / SEO /
Dev — was a second taxonomy that said nothing the department did not already say, drifted from
Atrium's, and was half-applied in practice (docs/TASKBOARD_REBUILD.md §2.2.3).

What must stay true:

* the mapping matches Atrium's, including "Data Analyst" and "data" landing on the same answer;
* creating a task derives the label and IGNORES anything the caller sent;
* re-routing a task to another department relabels it, and logs why;
* a task with no department has NO label (inventing one would file untriaged work in a real bucket);
* `reconcile_labels` retires the old vocabulary, adds the derived one, relabels every task — and is
  idempotent, because it runs on every boot.
"""
from __future__ import annotations

import json

from app import constants as C
from app.models import Task, TaskVocabItem
from app.services import task_config


# --- the mapping ------------------------------------------------------------------------------

def test_mapping_matches_atriums():
    # These five are the literal keys in atrium/services/portal/dash/main.py TASK_DEPT_LABEL.
    assert C.TASK_DEPT_LABEL["acquisition"] == "Paid Media"
    assert C.TASK_DEPT_LABEL["lifecycle"] == "Organic"
    assert C.TASK_DEPT_LABEL["data"] == "Website"
    assert C.TASK_DEPT_LABEL["development"] == "Website"
    assert C.TASK_DEPT_LABEL["bidbrain"] == "Website"


def test_sentinels_team_names_resolve_through_the_first_word():
    # Sentinel names the team "Data Analyst"; Atrium's key is "data". Both must answer the same,
    # without either side hardcoding the other's wording.
    assert C.label_for_department("Data Analyst") == "Website"
    assert C.label_for_department("Acquisition") == "Paid Media"
    assert C.label_for_department("lifecycle") == "Organic"
    assert C.label_for_department("  Development  ") == "Website"


def test_an_unmapped_department_falls_back_to_website():
    assert C.label_for_department("Partnerships") == C.TASK_LABEL_DEFAULT == "Website"


def test_no_department_means_no_label():
    # Not "Website" — an unrouted task is genuinely unlabelled.
    assert C.label_for_department(None) is None
    assert C.label_for_department("") is None
    assert C.label_for_department("   ") is None


def test_the_vocabulary_is_derived_from_the_mapping():
    # TASK_LABELS must never be able to disagree with what the mapping can produce.
    assert set(C.TASK_LABELS) == {*C.TASK_DEPT_LABEL.values(), C.TASK_LABEL_DEFAULT}
    assert "Design" not in C.TASK_LABELS and "SEO" not in C.TASK_LABELS
    # Every derived label needs a colour, or the board renders an uncoloured chip.
    for name in C.TASK_LABELS:
        assert task_config.DEFAULT_LABEL_COLORS.get(name), name


# --- create / update --------------------------------------------------------------------------

def _mk(client, **kw):
    body = {"title": "T"}
    body.update(kw)
    return client.post("/api/tasks", json=body)


def _detail(client, tid):
    r = client.get(f"/api/tasks/{tid}")
    assert r.status_code == 200, r.text
    return r.json()


def test_create_derives_the_label_from_the_department(client, auth, make_user, make_team):
    auth(make_user(C.ROLE_ADMIN))
    team = make_team("Acquisition")
    r = _mk(client, assigned_team_id=team.id)
    assert r.status_code in (200, 201), r.text
    assert r.json()["labels"] == ["Paid Media"]


def test_create_ignores_labels_sent_by_the_caller(client, auth, make_user, make_team):
    # The field still exists on the schema; it simply has no effect. A caller cannot paint a task
    # with a label its department does not imply.
    auth(make_user(C.ROLE_ADMIN))
    team = make_team("Lifecycle")
    r = _mk(client, assigned_team_id=team.id, labels=["Design", "SEO"])
    assert r.json()["labels"] == ["Organic"]


def test_create_without_a_department_has_no_label(client, auth, make_user):
    auth(make_user(C.ROLE_ADMIN))
    assert _mk(client).json()["labels"] == []


def test_rerouting_relabels_the_task_and_logs_it(client, auth, make_user, make_team):
    auth(make_user(C.ROLE_ADMIN))
    acq, life = make_team("Acquisition"), make_team("Lifecycle")
    tid = _mk(client, assigned_team_id=acq.id).json()["id"]
    assert _detail(client, tid)["labels"] == ["Paid Media"]

    r = client.patch(f"/api/tasks/{tid}", json={"assigned_team_id": life.id})
    assert r.status_code == 200, r.text
    detail = _detail(client, tid)
    assert detail["labels"] == ["Organic"]
    # The chip changed; the history has to say why.
    assert any(h["field"] == "labels" for h in detail["history"])


def test_clearing_the_department_clears_the_label(client, auth, make_user, make_team):
    auth(make_user(C.ROLE_ADMIN))
    team = make_team("Acquisition")
    tid = _mk(client, assigned_team_id=team.id).json()["id"]
    client.patch(f"/api/tasks/{tid}", json={"assigned_team_id": None})
    assert _detail(client, tid)["labels"] == []


def test_an_edit_that_does_not_move_the_team_leaves_the_label_alone(client, auth, make_user, make_team):
    auth(make_user(C.ROLE_ADMIN))
    team = make_team("Acquisition")
    tid = _mk(client, assigned_team_id=team.id).json()["id"]
    client.patch(f"/api/tasks/{tid}", json={"title": "renamed"})
    d = _detail(client, tid)
    assert d["labels"] == ["Paid Media"]
    assert not any(h["field"] == "labels" for h in d["history"])


# --- the boot reconcile -----------------------------------------------------------------------

def test_reconcile_retires_the_old_vocabulary_and_adds_the_derived_one(db, make_team):
    for i, name in enumerate(["Design", "Copy", "Ads", "SEO", "Dev"]):
        db.add(TaskVocabItem(kind="label", name=name, color="#000000", sort_order=i))
    db.commit()

    out = task_config.reconcile_labels(db)
    assert out["retired"] >= 5

    rows = db.query(TaskVocabItem).filter(TaskVocabItem.kind == "label").all()
    active = {r.name for r in rows if r.is_active}
    assert active == set(C.TASK_LABELS)
    # Retired, never deleted — old history rows still reference them.
    assert {"Design", "SEO"} <= {r.name for r in rows}
    assert not any(r.is_active for r in rows if r.name in {"Design", "Copy", "Ads", "SEO", "Dev"})


def test_reconcile_relabels_existing_tasks_from_their_team(db, make_team, make_user):
    team = make_team("Acquisition")
    u = make_user("admin")
    t = Task(title="stale", status="To Do", priority="Medium", created_by_id=u.id,
             assigned_team_id=team.id, labels_json=json.dumps(["Design"]))
    db.add(t)
    db.commit()

    task_config.reconcile_labels(db)
    db.refresh(t)
    assert json.loads(t.labels_json) == ["Paid Media"]


def test_reconcile_is_idempotent(db, make_team, make_user):
    team = make_team("Lifecycle")
    u = make_user("admin")
    db.add(Task(title="x", status="To Do", priority="Medium", created_by_id=u.id,
                assigned_team_id=team.id, labels_json=json.dumps(["Ads"])))
    db.commit()

    first = task_config.reconcile_labels(db)
    assert any(first.values())
    # 🔴 It runs on EVERY boot, so a second pass writing anything would mean churn on every deploy.
    assert task_config.reconcile_labels(db) == {"retired": 0, "added": 0, "relabelled": 0}


def test_reconcile_survives_a_corrupt_labels_json(db, make_team, make_user):
    team = make_team("Acquisition")
    u = make_user("admin")
    t = Task(title="bad", status="To Do", priority="Medium", created_by_id=u.id,
             assigned_team_id=team.id, labels_json="not json at all")
    db.add(t)
    db.commit()

    task_config.reconcile_labels(db)
    db.refresh(t)
    assert json.loads(t.labels_json) == ["Paid Media"]

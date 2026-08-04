"""The status key/label split: a status may be renamed without breaking the Atrium bridge.

Statuses are DB-backed and editable in Manage, and `manage._rename_in_tasks` cascades a rename onto
every task row — so `tasks.status` always holds the CURRENT label. The bug this closes is that
`atrium_tasks.STAGE_BY_STATUS` was a literal dict keyed by that display string, so renaming a status
silently broke every client card's move with a bare 400 "Invalid status"
(docs/TASKBOARD_REBUILD.md §2.2.1). Renaming "Blocked" to "Parked" walks straight into it.

What must stay true:

* a status carries a stable `key` and an Atrium `stage`; the label is free to change;
* after a rename, the bridge still resolves the right stage;
* a NEW status must declare its stage (D13) — no silent stage-less column;
* a rename never moves the key or the stage;
* `retire_statuses` finds the surviving column by STAGE, never by a hardcoded label — otherwise a
  boot-time sweep files live cards under a status that has no column;
* `rename_statuses` (WP 1.2) applies a shipped label change to boards that already exist, keyed by
  `key` and refusing to overwrite a label a team has chosen for itself.
"""
from __future__ import annotations

from app import constants as C
from app.models import Task, TaskVocabItem
from app.services import task_config


def _status(db, name):
    return db.query(TaskVocabItem).filter(
        TaskVocabItem.kind == "status", TaskVocabItem.name == name).one()


# --- the seed ---------------------------------------------------------------------------------

def test_seeded_statuses_carry_a_key_and_a_stage(db):
    for name, key, stage in task_config.STATUS_SEED:
        row = _status(db, name)
        assert row.key == key
        assert row.stage == stage


def test_stage_resolves_from_the_db_not_the_label_literal(db):
    assert task_config.stage_for(db, "In Progress") == "in_progress"
    assert task_config.stage_for(db, C.TASK_BLOCKED) == "blocked"
    assert task_config.stage_for(db, "Nonexistent") == ""


def test_status_for_stage_is_the_inverse(db):
    assert task_config.status_for_stage(db, "blocked") == C.TASK_BLOCKED
    assert task_config.status_for_stage(db, "completed") == "Completed"


# --- renaming: the whole point ----------------------------------------------------------------

def test_renaming_a_status_keeps_the_bridge_working(client, auth, make_user, db):
    """Rename the blocked column again, to a label nothing in the codebase has heard of.

    🔴 The destination is deliberately NOT "Parked" any more: WP 1.2 made that the SHIPPED name, so
    renaming to it would prove nothing — the assertions would pass on a board where the rename
    silently did nothing at all. A label no constant, seed or legacy map knows is the only kind that
    can distinguish "the rename worked" from "the value was already right".
    """
    auth(make_user(C.ROLE_SUPER_ADMIN))
    blocked = _status(db, C.TASK_BLOCKED)
    t = Task(title="waiting on assets", status=C.TASK_BLOCKED)
    db.add(t)
    db.commit()

    r = client.patch(f"/api/manage/task-vocab/{blocked.id}", json={"name": "On Ice"})
    assert r.status_code == 200
    assert r.json()["name"] == "On Ice"
    assert r.json()["key"] == "blocked"        # identity did NOT follow the label
    assert r.json()["stage"] == "blocked"

    db.expire_all()
    # the rename cascaded onto the task row...
    assert db.get(Task, t.id).status == "On Ice"
    # ...and the bridge still knows where the client's card sits
    assert task_config.stage_for(db, "On Ice") == "blocked"
    assert task_config.stage_for(db, C.TASK_BLOCKED) == "blocked"   # legacy literal still resolves
    assert task_config.status_for_stage(db, "blocked") == "On Ice"


def test_a_renamed_status_still_moves_a_client_card(client, auth, make_user, db, monkeypatch):
    """The exact failure: a move on an Atrium card 400'd once the label no longer matched."""
    from app.services import atrium_tasks

    # Renaming is a Manage action (admin+); moving a card is the AM's. Two different seats, so the
    # rename goes in directly and the AM only does the move.
    blocked = _status(db, C.TASK_BLOCKED)
    blocked.name = "On Ice"       # a label no constant, seed or legacy map knows -- see above
    db.commit()
    auth(make_user(C.ROLE_ACCOUNT_MANAGER))

    seen = {}
    monkeypatch.setattr(atrium_tasks, "move_task",
                        lambda k, t, stage, actor="": (seen.update(stage=stage), (True, ""))[1])

    r = client.patch("/api/tasks/atrium:honeytribe:tk_1/status", json={"status": "On Ice"})
    assert r.status_code == 200
    assert seen["stage"] == "blocked"          # the KEY's stage, not the new label


def test_a_renamed_status_still_projects_a_sentinel_row(db, make_user, monkeypatch):
    from app.services import atrium_tasks, task_bridge

    blocked = _status(db, C.TASK_BLOCKED)
    blocked.name = "On Ice"       # a label no constant, seed or legacy map knows -- see above
    db.commit()
    t = Task(title="paused", status="On Ice", atrium_task_id="t_x")
    db.add(t)
    db.commit()

    seen = {}
    monkeypatch.setattr(atrium_tasks, "move_task",
                        lambda k, tid, stage, actor="": (seen.update(stage=stage), (True, ""))[1])
    monkeypatch.setattr(task_bridge, "client_key_for", lambda *_a: "honeytribe")

    ok, err = task_bridge.push_stage(db, t, make_user(C.ROLE_ACCOUNT_MANAGER))
    assert ok and not err
    assert seen["stage"] == "blocked"


# --- D13: a new status must declare its stage --------------------------------------------------

def test_a_new_status_without_a_stage_is_refused(client, auth, make_user):
    auth(make_user(C.ROLE_SUPER_ADMIN))
    r = client.post("/api/manage/task-vocab", json={"kind": "status", "name": "On Hold"})
    assert r.status_code == 400
    assert "client stage" in r.json()["detail"]


def test_a_new_status_with_a_bogus_stage_is_refused(client, auth, make_user):
    auth(make_user(C.ROLE_SUPER_ADMIN))
    r = client.post("/api/manage/task-vocab",
                    json={"kind": "status", "name": "On Hold", "stage": "limbo"})
    assert r.status_code == 400


def test_a_new_status_with_a_stage_works_and_bridges(client, auth, make_user, db):
    auth(make_user(C.ROLE_SUPER_ADMIN))
    r = client.post("/api/manage/task-vocab",
                    json={"kind": "status", "name": "Client Review", "stage": "revision"})
    assert r.status_code == 200
    assert r.json()["key"] == "client_review" and r.json()["stage"] == "revision"
    assert task_config.stage_for(db, "Client Review") == "revision"


def test_labels_and_priorities_need_no_stage(client, auth, make_user):
    auth(make_user(C.ROLE_SUPER_ADMIN))
    for kind, name in (("label", "Motion"), ("priority", "Someday")):
        r = client.post("/api/manage/task-vocab", json={"kind": kind, "name": name})
        assert r.status_code == 200, r.text
        assert r.json()["stage"] is None


def test_a_status_cannot_have_its_stage_blanked(client, auth, make_user, db):
    auth(make_user(C.ROLE_SUPER_ADMIN))
    todo = _status(db, "To Do")
    r = client.patch(f"/api/manage/task-vocab/{todo.id}", json={"stage": ""})
    assert r.status_code == 400


# --- the boot-time sweep must not name a label -------------------------------------------------

def test_retiring_a_status_targets_the_stage_not_a_literal_label(db):
    """`retire_statuses` runs on EVERY boot. Hardcoding "Blocked" meant that once the label became
    "Parked" it would move live cards onto a status with no column — off the board, no error."""
    blocked = _status(db, C.TASK_BLOCKED)
    blocked.name = "On Ice"       # a label no constant, seed or legacy map knows -- see above
    db.commit()

    stranded = Task(title="old review card", status="For Review")
    db.add(stranded)
    db.commit()

    task_config.retire_statuses(db)
    db.expire_all()
    assert db.get(Task, stranded.id).status == "On Ice"      # the surviving column's CURRENT name
    assert "On Ice" in task_config.statuses(db)


# --- the backfill (how the columns reach an existing board) ------------------------------------

def test_backfill_heals_rows_that_predate_the_columns(db):
    for row in db.query(TaskVocabItem).filter(TaskVocabItem.kind == "status"):
        row.key = None
        row.stage = None
    custom = TaskVocabItem(kind="status", name="Ad Hoc", sort_order=99)
    db.add(custom)
    db.commit()

    task_config.backfill_status_meta(db)
    db.expire_all()

    assert _status(db, C.TASK_BLOCKED).stage == "blocked"
    assert _status(db, "To Do").key == "todo"
    # a custom status gets a stable key, but NOT a guessed stage — guessing would file a client's
    # card in the wrong column, so it stays empty and `publish` refuses instead.
    healed = _status(db, "Ad Hoc")
    assert healed.key == "ad_hoc"
    assert healed.stage is None


def test_vocab_endpoint_exposes_the_stage(client, auth, make_user):
    auth(make_user(C.ROLE_EMPLOYEE))
    meta = client.get("/api/vocab").json()["task_status_meta"]
    by_name = {m["name"]: m for m in meta}
    assert by_name["In Progress"]["stage"] == "in_progress"
    assert by_name["In Progress"]["key"] == "in_progress"


# --- several Sentinel columns may share ONE Atrium stage -----------------------------------------

def test_many_sentinel_statuses_can_share_one_atrium_stage(client, auth, make_user, db):
    """Atrium has exactly five stages; this board may have any number of columns folding onto them.
    That is what `stage` is for — the two boards do NOT have to have the same columns."""
    auth(make_user(C.ROLE_SUPER_ADMIN))
    r = client.post("/api/manage/task-vocab",
                    json={"kind": "status", "name": "Waiting on client", "stage": "blocked"})
    assert r.status_code == 200
    assert task_config.stage_for(db, "Waiting on client") == "blocked"
    assert task_config.stage_for(db, C.TASK_BLOCKED) == "blocked"


def test_the_column_a_stage_resolves_BACK_to_is_the_left_most_one(client, auth, make_user, db):
    """🔴 `status_for_stage` is the reverse direction, and it has exactly one right answer: Park has
    to move work into a specific column, and `retire_statuses` has to file stranded cards under one.
    With two columns on the same stage it must be the LEFT-MOST (lowest sort_order) — deterministic,
    and the one a human would point at. Unordered it was whatever the DB returned first."""
    auth(make_user(C.ROLE_SUPER_ADMIN))
    # Give the newcomer a LOWER sort_order than the shipped blocked column, i.e. further left.
    client.post("/api/manage/task-vocab",
                json={"kind": "status", "name": "Waiting on client", "stage": "blocked"})
    newcomer = _status(db, "Waiting on client")
    blocked = _status(db, C.TASK_BLOCKED)
    newcomer.sort_order = blocked.sort_order - 1
    db.commit()
    assert task_config.status_for_stage(db, "blocked") == "Waiting on client"

    # Move it to the right and the answer follows the board, not the insertion order.
    newcomer.sort_order = blocked.sort_order + 1
    db.commit()
    assert task_config.status_for_stage(db, "blocked") == C.TASK_BLOCKED


# --- WP 1.2: the shipped rename reaches boards that already exist --------------------------------

def _blocked_row(db):
    return db.query(TaskVocabItem).filter(
        TaskVocabItem.kind == "status", TaskVocabItem.key == "blocked").one()


def test_the_shipped_blocked_column_is_called_parked(db):
    """WP 1.2. The label is "Parked"; the key and the stage are both still `blocked`."""
    row = _blocked_row(db)
    assert row.name == "Parked" == C.TASK_BLOCKED
    assert row.key == "blocked" and row.stage == "blocked"


def test_rename_migrates_an_existing_board_and_its_tasks(db):
    """The state every real board was in before this shipped: the row still says "Blocked"."""
    row = _blocked_row(db)
    row.name = "Blocked"
    t = Task(title="waiting on legal", status="Blocked")
    db.add(t)
    db.commit()

    done = task_config.rename_statuses(db)
    db.expire_all()
    assert done == ["Blocked -> Parked (1 task(s))"]
    assert _blocked_row(db).name == "Parked"
    # 🔴 The task row moves in the SAME sweep. `tasks.status` stores the label, so a rename that
    # updated only the vocab row would leave every parked card grouped under a column that no
    # longer exists — off the board, no error (AGENTS.md §5).
    assert db.get(Task, t.id).status == "Parked"


def test_rename_is_idempotent(db):
    row = _blocked_row(db)
    row.name = "Blocked"
    db.commit()
    assert task_config.rename_statuses(db)
    assert task_config.rename_statuses(db) == []      # the second boot does nothing
    assert task_config.rename_statuses(db) == []


def test_rename_never_overwrites_a_label_the_team_chose(db):
    """🔴 The guard that makes a boot-time sweep acceptable at all.

    A label is the one facet of a status that belongs to the people using the board. This migration
    corrects a DEFAULT nobody had touched; a team that renamed their blocked column to something of
    their own must find it unchanged after every deploy, forever."""
    row = _blocked_row(db)
    row.name = "Snoozed"
    t = Task(title="theirs", status="Snoozed")
    db.add(t)
    db.commit()

    assert task_config.rename_statuses(db) == []
    db.expire_all()
    assert _blocked_row(db).name == "Snoozed"
    assert db.get(Task, t.id).status == "Snoozed"


def test_rename_finds_the_row_by_key_not_by_position(db):
    """Keyed by `key` (D13) — the label is the facet that moves, so it cannot also be the handle."""
    row = _blocked_row(db)
    row.name = "Blocked"
    row.sort_order = 99
    db.commit()
    assert task_config.rename_statuses(db)
    assert _blocked_row(db).name == "Parked"


def test_an_unmigrated_board_still_gets_its_key_and_stage_backfilled(db):
    """🔴 The ordering hazard in `main._startup`: `rename_statuses` matches on `key`, so a board
    seeded before that column existed must be backfilled FIRST or the rename silently misses it —
    on exactly the oldest boards, which are the ones that need it. `LEGACY_STATUS_NAMES` is what
    lets the backfill recognise the row while it is still wearing the old label."""
    row = _blocked_row(db)
    row.name = "Blocked"
    row.key = None
    row.stage = None
    db.commit()

    task_config.backfill_status_meta(db)
    db.expire_all()
    healed = db.query(TaskVocabItem).filter(
        TaskVocabItem.kind == "status", TaskVocabItem.name == "Blocked").one()
    assert healed.key == "blocked" and healed.stage == "blocked"
    assert task_config.rename_statuses(db) == ["Blocked -> Parked (0 task(s))"]

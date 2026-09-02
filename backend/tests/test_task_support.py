"""Support (many people per task, none accountable) — `models.TaskSupporter`, 2026-08-06.

Why the field exists: a Sentinel task had exactly ONE ownership field while the Atrium client cards
beside it on the same board have carried Lead + many Support since the bridge was built. So the only
way to put a second name on a Sentinel card was to invent a checklist step for them — and because
the progress bar is `done steps / total steps`, that made STAFFING a card change how finished it
looked.

These tests are weighted toward the two things that make it safe, not the happy path:

1. **Naming somebody is DELEGATION**, guarded where the field is WRITTEN. This board has shipped
   that hole twice (`maintasks[].assignee_id` in 2026-08-03; owner SETS vs slots in 2026-08-05),
   both times because a new way to put a name on a card walked past the check.
2. **Support widens "assigned" and NOTHING else.** Everything keyed on `assigned_to_id` — the team
   triage queue, the lead's right to tick another person's step, the `?assignee_id=` filter — must
   behave exactly as it did before.
"""
from __future__ import annotations

import pytest

from app import constants as C
from app.models import Task, TaskSupporter
from app.services import task_perms


@pytest.fixture
def cast(make_team, make_user):
    """A lead and a helper on one team, plus the roles that may and may not delegate."""
    team = make_team(name="Creative")
    return {
        "team": team,
        "lead": make_user(C.ROLE_EMPLOYEE, name="Lead Person", team_id=team.id),
        "helper": make_user(C.ROLE_EMPLOYEE, name="Helper Person", team_id=team.id),
        "team_lead": make_user(C.ROLE_TEAM_LEAD, name="Team Lead", team_id=team.id),
        "am": make_user(C.ROLE_ACCOUNT_MANAGER, name="Account Manager"),
        "viewer": make_user(C.ROLE_VIEWER, name="Viewer"),
    }


def _task(db, **kw) -> Task:
    t = Task(title=kw.pop("title", "Ship the thing"), status=C.TASK_TODO, **kw)
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def _support(db, task: Task, *user_ids: int) -> None:
    for uid in user_ids:
        db.add(TaskSupporter(task_id=task.id, user_id=uid))
    db.commit()
    db.refresh(task)


def _card(client, task_id):
    for c in client.get("/api/tasks").json():
        if c["id"] == task_id:
            return c
    return None


# --- What support DOES get --------------------------------------------------------------------

def test_a_supporter_is_assigned_and_can_see_the_card(db, cast):
    """The single hook: support joins `assigned_user_ids`, so every surface that asks "is this on
    me?" inherits it — the board, My work, By Employee, the Monitor. No second copy of the rule."""
    helper, lead = cast["helper"], cast["lead"]
    t = _task(db, assigned_to_id=lead.id)
    assert task_perms.can_view(helper, t) is False        # not theirs yet
    _support(db, t, helper.id)
    assert helper.id in task_perms.assigned_user_ids(t)
    assert task_perms.is_assigned(helper, t) is True
    assert task_perms.is_supporting(helper, t) is True
    assert task_perms.can_view(helper, t) is True
    assert task_perms.can_edit(helper, t) is True
    assert task_perms.can_move(helper, t) is True


def test_the_api_publishes_support_and_which_hat_the_viewer_wears(client, auth, db, cast):
    """`mine` alone cannot say WHY a card is on your list — lead, support, or one step of it. A list
    that renders all three identically is indistinguishable from the July 2026 bug where a board
    showed other people's work."""
    helper, lead = cast["helper"], cast["lead"]
    t = _task(db, assigned_to_id=lead.id)
    _support(db, t, helper.id)

    auth(helper)
    card = _card(client, t.id)
    assert card["support_ids"] == [helper.id]
    assert [p["name"] for p in card["support"]] == [helper.name]
    assert card["mine"] is True
    assert card["supporting"] is True
    assert card["my_slots"] == 0                     # support is not a breakdown slot

    # The LEAD is mine-but-not-supporting: the two flags answer different questions.
    auth(lead)
    lead_card = _card(client, t.id)
    assert (lead_card["mine"], lead_card["supporting"]) == (True, False)


def test_support_is_counted_separately_from_steps_on_the_monitor(client, auth, db, cast):
    """🔴 Support used to fall into `stepped`, which the UI renders as "N as steps" — so somebody
    named as support was described as owning steps of a card, possibly zero steps. The label has to
    match the reason or the row is confidently wrong about how a person's day is spent."""
    lead, helper = cast["lead"], cast["helper"]
    t = _task(db, assigned_to_id=lead.id, assigned_team_id=cast["team"].id)
    _support(db, t, helper.id)

    auth(cast["am"])
    rows = client.get("/api/tasks/summary").json()
    row = next(r for r in rows if r["user"]["id"] == helper.id)
    assert row["supporting"] == 1
    assert row["stepped"] == 0
    assert row["open_total"] >= 1


# --- What support does NOT get ----------------------------------------------------------------

def test_support_does_not_claim_the_card_out_of_its_team_queue(db, cast):
    """🔴 The queue means "nobody is ACCOUNTABLE yet". Support is help, not ownership, so the card
    stays visible to the whole team until a LEAD is named — `_team_queue` still tests
    `assigned_to_id`. Otherwise work with helpers but no owner would quietly vanish from the one
    list the team watches."""
    member, helper = cast["lead"], cast["helper"]
    t = _task(db, assigned_team_id=cast["team"].id)        # routed, unowned
    assert task_perms.can_view(member, t) is True          # the queue
    _support(db, t, helper.id)
    assert t.assigned_to_id is None
    assert task_perms._team_queue(member, t) is True       # STILL in the queue
    assert task_perms.can_view(member, t) is True


def test_a_supporter_may_not_tick_somebody_elses_step(db, cast):
    """Accountability stays with the lead. `can_tick_step`'s "the card's lead may close anyone's
    step" clause is keyed on `assigned_to_id`, and support must not inherit it."""
    lead, helper = cast["lead"], cast["helper"]
    t = _task(db, assigned_to_id=lead.id)
    _support(db, t, helper.id)
    assert task_perms.can_tick_step(helper, t, lead.id) is False    # the lead's own step
    assert task_perms.can_tick_step(helper, t, helper.id) is True   # their own
    assert task_perms.can_tick_step(helper, t, None) is True        # unowned: queue behaviour
    assert task_perms.can_tick_step(lead, t, helper.id) is True     # the lead still may


def test_assignee_filter_stays_a_lead_only_field_filter(client, auth, db, cast):
    """"What is on Jerome?" is a precise question a manager needs answered precisely. `?assignee_id=`
    is documented as a FIELD filter on `assigned_to_id`; support must not widen it, or widening one
    would silently widen the other."""
    lead, helper = cast["lead"], cast["helper"]
    t = _task(db, assigned_to_id=lead.id)
    _support(db, t, helper.id)
    auth(cast["am"])
    ids = [r["id"] for r in client.get(f"/api/tasks?assignee_id={helper.id}").json()]
    assert t.id not in ids


# --- Naming somebody is delegation -------------------------------------------------------------

def test_an_employee_cannot_put_a_colleague_on_a_task(client, auth, db, cast):
    lead, helper = cast["lead"], cast["helper"]
    t = _task(db, assigned_to_id=lead.id)
    auth(lead)
    r = client.patch(f"/api/tasks/{t.id}", json={"support_ids": [helper.id]})
    assert r.status_code == 403
    assert "department head or manager" in r.json()["detail"]
    db.refresh(t)
    assert t.support_ids == []


def test_an_employee_can_add_and_remove_THEMSELVES(client, auth, db, cast):
    """Joining and leaving work yourself has to stay open, or the field is unusable by the people who
    actually pick work up. Mirrors self-assignment on a breakdown step.

    The card here is their team's UNOWNED queue work, which is the realistic shape: picking something
    up off the team queue is exactly the moment you add yourself to it. See the test below for why it
    has to be a card they can already see.
    """
    helper = cast["helper"]
    t = _task(db, assigned_team_id=cast["team"].id)      # routed, unowned == visible to the team
    auth(helper)
    assert client.patch(f"/api/tasks/{t.id}", json={"support_ids": [helper.id]}).status_code == 200
    db.refresh(t)
    assert t.support_ids == [helper.id]
    # 🔴 And it does NOT claim the card: still unowned, so it stays in the team's queue (see
    # test_support_does_not_claim_the_card_out_of_its_team_queue).
    assert t.assigned_to_id is None
    assert client.patch(f"/api/tasks/{t.id}", json={"support_ids": []}).status_code == 200
    db.refresh(t)
    assert t.support_ids == []


def test_you_cannot_join_a_card_you_cannot_see(client, auth, db, cast):
    """🔴 Self-join is not a way IN. `update_task` checks `can_edit` before it looks at any field, so
    "adding yourself is always allowed" is scoped to cards already on your board — a colleague's card
    is not one of them. Without this, support would be a hole straight through `can_view`: name
    yourself on any id and the card becomes yours to read and edit."""
    lead, helper = cast["lead"], cast["helper"]
    t = _task(db, assigned_to_id=lead.id)              # owned by a colleague, no team
    assert task_perms.can_view(helper, t) is False
    auth(helper)
    assert client.patch(f"/api/tasks/{t.id}", json={"support_ids": [helper.id]}).status_code == 403
    db.refresh(t)
    assert t.support_ids == []


def test_an_employee_cannot_remove_a_colleague_while_adding_themselves(client, auth, db, cast):
    """🔴 The diff is over the SYMMETRIC difference, so a change that adds you AND drops somebody
    else is still delegation. This is the shape that defeated the first version of the breakdown
    guard, which compared owner sets and passed anything leaving the set size intact."""
    lead, helper = cast["lead"], cast["helper"]
    t = _task(db, assigned_to_id=lead.id)
    _support(db, t, helper.id)
    other = cast["team_lead"]           # somebody already on it who the actor is not
    auth(lead)
    r = client.patch(f"/api/tasks/{t.id}", json={"support_ids": [lead.id]})
    assert r.status_code == 403
    db.refresh(t)
    assert t.support_ids == [helper.id]
    assert other.id not in t.support_ids


@pytest.mark.parametrize("who", ["team_lead", "am"])
def test_delegators_may_name_anyone(client, auth, db, cast, who):
    actor = cast[who]
    t = _task(db, assigned_team_id=cast["team"].id)
    auth(actor)
    want = sorted([cast["lead"].id, cast["helper"].id])
    r = client.patch(f"/api/tasks/{t.id}", json={"support_ids": want})
    assert r.status_code == 200, r.json()
    assert sorted(r.json()["support_ids"]) == want


def test_a_viewer_is_refused(client, auth, db, cast):
    """The read-only seat sees everything and writes nothing (D8)."""
    t = _task(db, assigned_to_id=cast["lead"].id)
    auth(cast["viewer"])
    assert client.patch(f"/api/tasks/{t.id}",
                        json={"support_ids": [cast["helper"].id]}).status_code == 403


def test_create_refuses_naming_a_colleague_rather_than_dropping_them(client, auth, cast):
    """🔴 A 403, not a silent drop. Dropping it is the quiet lie `assigned_to_id` used to tell: the
    form let you pick a colleague, said "created", and put the card on your own board instead."""
    auth(cast["lead"])
    r = client.post("/api/tasks", json={"title": "Mine", "support_ids": [cast["helper"].id]})
    assert r.status_code == 403


def test_create_allows_adding_yourself_as_support(client, auth, cast):
    me = cast["lead"]
    auth(me)
    r = client.post("/api/tasks", json={"title": "Helping out", "support_ids": [me.id]})
    assert r.status_code == 200
    assert r.json()["support_ids"] == [me.id]


# --- The write path's own edge cases -----------------------------------------------------------

def test_omitting_the_field_leaves_supporters_alone(client, auth, db, cast):
    """🔴 `None` (absent) means "don't touch"; `[]` means "remove everyone". A plain list default on
    the schema would make every unrelated PATCH silently clear the support list."""
    t = _task(db, assigned_to_id=cast["lead"].id)
    _support(db, t, cast["helper"].id)
    auth(cast["am"])
    assert client.patch(f"/api/tasks/{t.id}", json={"title": "Renamed"}).status_code == 200
    db.refresh(t)
    assert t.support_ids == [cast["helper"].id]


def test_resending_the_same_list_keeps_the_original_row(client, auth, db, cast):
    """Only the difference is touched, so `added_by_id`/`created_at` stay true instead of being
    rewritten by every PATCH that happens to resend the list. And the unique constraint means a
    resend must not stack a duplicate — which would double-count them on the Monitor."""
    helper = cast["helper"]
    t = _task(db, assigned_to_id=cast["lead"].id)
    auth(cast["am"])
    client.patch(f"/api/tasks/{t.id}", json={"support_ids": [helper.id]})
    db.refresh(t)
    stamp, added_by = t.supporters[0].created_at, t.supporters[0].added_by_id
    client.patch(f"/api/tasks/{t.id}", json={"support_ids": [helper.id]})
    db.refresh(t)
    assert len(t.supporters) == 1
    assert (t.supporters[0].created_at, t.supporters[0].added_by_id) == (stamp, added_by)


def test_a_duplicated_id_in_one_request_does_not_explode(client, auth, db, cast):
    """The unique constraint would turn a double-selected name into an IntegrityError, so the write
    path dedupes. A multi-select can genuinely submit the same value twice."""
    helper = cast["helper"]
    t = _task(db, assigned_to_id=cast["lead"].id)
    auth(cast["am"])
    r = client.patch(f"/api/tasks/{t.id}", json={"support_ids": [helper.id, helper.id]})
    assert r.status_code == 200
    db.refresh(t)
    assert t.support_ids == [helper.id]


def test_an_inactive_user_is_dropped_rather_than_failing_the_whole_edit(client, auth, db, cast,
                                                                       make_user):
    """The list comes from a multi-select a stale page may have rendered before somebody was
    deactivated. Losing an entire edit to one dead id is worse than staffing one fewer person."""
    ghost = make_user(C.ROLE_EMPLOYEE, name="Gone", active=False)
    t = _task(db, assigned_to_id=cast["lead"].id)
    auth(cast["am"])
    r = client.patch(f"/api/tasks/{t.id}", json={"support_ids": [ghost.id, cast["helper"].id]})
    assert r.status_code == 200
    assert r.json()["support_ids"] == [cast["helper"].id]


def test_a_support_change_is_recorded_in_history(client, auth, db, cast):
    """Support is a delegation decision, so it leaves a trace like every other one."""
    t = _task(db, assigned_to_id=cast["lead"].id)
    auth(cast["am"])
    client.patch(f"/api/tasks/{t.id}", json={"support_ids": [cast["helper"].id]})
    detail = client.get(f"/api/tasks/{t.id}").json()
    assert any(h["field"] == "support" for h in detail["history"])


def test_deleting_the_task_removes_its_supporter_rows(db, cast):
    """cascade="all, delete-orphan" — an orphaned row would keep counting toward somebody's workload
    for a card that no longer exists."""
    t = _task(db, assigned_to_id=cast["lead"].id)
    _support(db, t, cast["helper"].id)
    tid = t.id
    db.delete(t)
    db.commit()
    assert db.query(TaskSupporter).filter_by(task_id=tid).count() == 0


# --- The staff mirror ------------------------------------------------------------------------

def test_support_reaches_atriums_staff_mirror_but_never_the_client(db, cast):
    """The mirror hands Atrium's operator console everything (§2); the client projection is six
    client-safe fields and staffing is not one of them. `board_mirror` had `support_ids: []`
    hardcoded, with a comment reading "Sentinel has no support list" — this is that gap closed."""
    from app.services import board_mirror, task_bridge

    t = _task(db, assigned_to_id=cast["lead"].id)
    _support(db, t, cast["helper"].id)
    # `id` is prefixed ("s1") so it cannot collide with an Atrium task id in the console; the bare
    # row id travels as `sentinel_id`.
    row = next(r for r in board_mirror.board(db) if r["sentinel_id"] == t.id)
    assert row["support_ids"] == [cast["helper"].email]
    # The client's copy must not learn who is staffed on the work.
    assert "support_ids" not in task_bridge.SAFE
    assert "support_ids" not in task_bridge.client_safe_fields(t, db)

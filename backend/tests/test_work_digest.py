"""The task board as the AI coach sees it — and above all, WHOSE board it is.

Every other internal endpoint the coach calls is the worker's own data, so it needs no permission
model. This one is other people's work, which makes the scoping the security property rather than a
nicety: the Coach FAB is a chat box that can ask Sentinel questions, so if `work_digest` widened
`task_perms.can_view` by a single clause, an intern could ask their coach what the whole company is
working on and get an answer.

So the cases below are deliberately weighted toward refusals:

  * an employee's digest contains their own work and their team's UNCLAIMED queue — and nothing a
    colleague owns;
  * a team lead is scoped to their team, an AM to the estate;
  * the per-person rollup is a MANAGER surface — employees get none of it, and a team lead's cohort
    is their own team;
  * `work_detail` re-checks every id, so naming a card you cannot see returns nothing (and is
    indistinguishable from naming one that does not exist).

Plus the two contract rules inherited from the growth-journal incident: the viewer's own index is
complete and uncapped, and any truncation of the wider board is declared rather than silent.
"""
from __future__ import annotations

import hashlib
import hmac
import time
from datetime import timedelta

import pytest

from app import constants as C
from app.config import settings
from app.models import Task, TaskComment
from app.services import maintasks as MT
from app.services import work_digest
from app.utils.time import today_ph, utcnow

SECRET = "shared-platform-sso-key-for-tests"


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    monkeypatch.setattr(settings, "platform_sso_secret", SECRET)


@pytest.fixture(autouse=True)
def _no_atrium(monkeypatch):
    """Keep the bridge out of these tests: they are about Sentinel's OWN permission model, and a
    fail-soft `fetch_tasks` would otherwise make the assertions depend on network conditions."""
    from app.services import atrium_tasks

    monkeypatch.setattr(atrium_tasks, "enabled", lambda: False)


def _sig(purpose: str, ts: str | None = None) -> dict:
    ts = ts or str(int(time.time()))
    mac = hmac.new(SECRET.encode(), f"{purpose}:{ts}".encode(), hashlib.sha256).hexdigest()
    return {"X-Academy-Ts": ts, "X-Academy-Sig": mac}


def _task(db, *, title="A task", assignee=None, team_id=None, status=C.TASK_TODO,
          due=None, creator=None, **extra) -> Task:
    t = Task(title=title, status=status, priority=C.PRIORITY_MEDIUM,
             assigned_to_id=getattr(assignee, "id", None), assigned_team_id=team_id,
             created_by_id=getattr(creator, "id", None), due_date=due, **extra)
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def _titles(cards) -> set[str]:
    return {c["title"] for c in cards}


# --- scoping: whose board is this? -------------------------------------------------------------
def test_employee_sees_own_work_and_the_team_queue_but_not_a_colleagues_card(db, make_user, make_team):
    """`can_view`'s three states, in the payload the coach reads. The third one is the point."""
    team = make_team()
    me = make_user(team_id=team.id)
    mate = make_user(team_id=team.id)
    _task(db, title="Mine", assignee=me)
    _task(db, title="Team queue", team_id=team.id)                  # routed, owned by nobody
    _task(db, title="Colleague's", assignee=mate, team_id=team.id)  # owned — not my business
    _task(db, title="Another team's", team_id=make_team(name="Acquisition").id)

    d = work_digest.work_digest(db, me)
    seen = _titles(d["mine"]["open"]) | _titles(d["board"]["others"])
    assert seen == {"Mine", "Team queue"}
    assert _titles(d["mine"]["open"]) == {"Mine"}


def test_a_card_led_by_someone_else_with_a_step_on_me_is_MINE(db, make_user):
    """`mine` is `task_perms.is_assigned` — the card's lead OR any breakdown slot. A coach that used
    the narrower rule would tell a delegate their plate is empty with the work one click away."""
    me = make_user()
    lead = make_user()
    t = _task(db, title="Shared build", assignee=lead)
    t.maintasks_json = MT.dumps([{"id": "m1", "title": "QA", "assignee_id": me.id, "subs": [
        {"id": "s1", "text": "regression pass", "done": False, "assignee_id": me.id},
    ]}])
    db.commit()

    d = work_digest.work_digest(db, me)
    card = next(c for c in d["mine"]["open"] if c["title"] == "Shared build")
    assert card["mine"] is True
    assert card["my_steps"] == 2          # the phase and its step
    assert card["lead"] == lead.name      # ...and it says whose card it is


def test_team_lead_is_scoped_to_their_team_and_an_am_sees_the_estate(db, make_user, make_team):
    mine = make_team(name="Creative")
    other = make_team(name="Acquisition")
    lead = make_user(role=C.ROLE_TEAM_LEAD, team_id=mine.id)
    _task(db, title="Ours", team_id=mine.id)
    _task(db, title="Theirs", team_id=other.id)

    lead_view = work_digest.work_digest(db, lead)
    assert _titles(lead_view["board"]["others"]) | _titles(lead_view["mine"]["open"]) == {"Ours"}

    am = make_user(role=C.ROLE_ACCOUNT_MANAGER)
    am_view = work_digest.work_digest(db, am)
    assert _titles(am_view["board"]["others"]) == {"Ours", "Theirs"}


def test_the_scope_note_tells_the_coach_it_is_not_the_company_board(db, make_user):
    """Without this sentence the model reads a four-card board as "the company has four tasks" and
    says so — turning a correct permission boundary into a false claim about the business."""
    assert "NOT the whole company" in work_digest.work_digest(db, make_user())["viewer"]["sees"]
    assert "whole" in work_digest.work_digest(
        db, make_user(role=C.ROLE_ACCOUNT_MANAGER))["viewer"]["sees"]


# --- the rollup is a manager surface -----------------------------------------------------------
def test_employees_get_no_per_person_rollup(db, make_user):
    make_user(role=C.ROLE_ACCOUNT_MANAGER)
    assert work_digest.work_digest(db, make_user())["people"] == []
    assert work_digest.work_digest(db, make_user(role=C.ROLE_INTERN))["people"] == []


def test_a_team_lead_rollup_covers_only_their_team(db, make_user, make_team):
    mine = make_team(name="Creative")
    lead = make_user(role=C.ROLE_TEAM_LEAD, team_id=mine.id, name="Lead One")
    member = make_user(team_id=mine.id, name="Member One")
    make_user(team_id=make_team(name="Acquisition").id, name="Outsider")

    rows = work_digest.work_digest(db, lead)["people"]
    assert {r["name"] for r in rows} == {"Lead One", "Member One"}


def test_the_viewer_seat_monitors_but_writes_nothing_it_can_see_everything(db, make_user):
    """D8: `viewer` is the read-only monitoring seat, so the rollup must name it EXPLICITLY — its
    ROLE_RANK is the floor, so nothing role-ranked would ever include it."""
    make_user(name="Worker")
    viewer = make_user(role=C.ROLE_VIEWER, name="Watcher")
    _task(db, title="Anything")
    d = work_digest.work_digest(db, viewer)
    assert _titles(d["board"]["others"]) == {"Anything"}
    assert {r["name"] for r in d["people"]} == {"Worker", "Watcher"}


def test_rollup_counts_stepped_work_and_bands_the_load(db, make_user):
    """Bucketed by `assigned_user_ids`, so somebody whose work arrives as steps of colleagues' cards
    is not idle — the blind spot every Monitor KPI inherited until 2026-08-05."""
    am = make_user(role=C.ROLE_ACCOUNT_MANAGER, name="Manager")
    worker = make_user(name="Stepper")
    t = _task(db, title="Big build", assignee=am)
    t.maintasks_json = MT.dumps([{"id": "m1", "title": "Build", "assignee_id": worker.id, "subs": []}])
    db.commit()

    row = next(r for r in work_digest.work_digest(db, am)["people"] if r["name"] == "Stepper")
    assert row["open_total"] == 1
    assert row["stepped"] == 1
    assert "load_band" in row       # apply_load_bands bands on `open_total` — the key it reads


# --- the two contract rules --------------------------------------------------------------------
def test_the_viewers_own_index_is_never_capped(db, make_user):
    """🔴 Same rule as the growth journal: the coach concludes "you have nothing about X" from X's
    absence here, so a cap turns that inference into a confident lie."""
    me = make_user()
    for i in range(work_digest.MAX_BOARD_CARDS + 25):
        _task(db, title=f"Card {i}", assignee=me)
    d = work_digest.work_digest(db, me)
    assert len(d["mine"]["open"]) == work_digest.MAX_BOARD_CARDS + 25
    assert d["mine"]["open_total"] == work_digest.MAX_BOARD_CARDS + 25


def test_a_truncated_wider_board_is_declared_not_silent(db, make_user):
    am = make_user(role=C.ROLE_ACCOUNT_MANAGER)
    for i in range(work_digest.MAX_BOARD_CARDS + 7):
        _task(db, title=f"Card {i}")
    d = work_digest.work_digest(db, am)
    assert len(d["board"]["others"]) == work_digest.MAX_BOARD_CARDS
    assert d["board"]["truncated"] == 7


# --- derived fields ----------------------------------------------------------------------------
def test_overdue_and_idle_are_derived_and_completed_work_is_neither(db, make_user):
    me = make_user()
    today = today_ph()
    late = _task(db, title="Late", assignee=me, due=today - timedelta(days=3))
    done = _task(db, title="Shipped", assignee=me, due=today - timedelta(days=9),
                 status=C.TASK_COMPLETED, completed_at=utcnow())

    d = work_digest.work_digest(db, me)
    by_title = {c["title"]: c for c in d["mine"]["open"]}
    assert by_title["Late"]["overdue_days"] == 3
    assert "idle_days" in by_title["Late"]
    # A completed card is not open, is not overdue, and shows up in the finished list instead.
    assert "Shipped" not in by_title
    assert d["mine"]["overdue_total"] == 1
    assert [s["title"] for s in d["mine"]["done"]] == ["Shipped"]
    assert late.id and done.id


def test_every_card_work_detail_will_hydrate_appears_in_the_digest(db, make_user):
    """🔴 The two endpoints must agree about what exists — found by probing them against each other on
    a seeded board (2026-08-05). `mine.open` drops completed cards and the board query drops FILED
    ones, so a card delivered last month was in NO list while `work_detail` would happily return its
    text: the coach would answer "you have nothing about the Acme June report" about work the person
    did and can still see on their own Past-work list. That is the growth-journal failure again — an
    incomplete index turns a gap into a confident denial — so the finished history is sent in full."""
    me = make_user()
    old = _task(db, title="Acme June report", assignee=me, status=C.TASK_COMPLETED,
                completed_at=utcnow() - timedelta(days=40))
    filed = _task(db, title="Filed long ago", assignee=me, status=C.TASK_COMPLETED,
                  completed_at=utcnow() - timedelta(days=90), archived=True)
    live = _task(db, title="Still going", assignee=me)

    d = work_digest.work_digest(db, me)
    listed = ({c["id"] for c in d["mine"]["open"]}
              | {c["id"] for c in d["mine"]["done"]}
              | {c["id"] for c in d["board"]["others"]})
    hydratable = {c["id"] for c in work_digest.work_detail(db, me, [old.id, filed.id, live.id])}
    assert hydratable <= listed, "work_detail can open a card the digest never mentions"
    assert {old.id, filed.id, live.id} == listed
    assert next(c for c in d["mine"]["done"] if c["id"] == filed.id)["filed"] is True
    # Newest first, so the engine can slice "this week" off the front.
    assert [c["id"] for c in d["mine"]["done"]] == [old.id, filed.id]


def test_stage_not_the_label_decides_what_is_done(db, make_user, client, auth):
    """D13: rename the column and the digest must stay correct. `Completed` -> `Delivered` here."""
    from app.models import TaskVocabItem

    admin = make_user(role=C.ROLE_SUPER_ADMIN)
    me = make_user()
    row = db.query(TaskVocabItem).filter_by(kind="status", name=C.TASK_COMPLETED).one()
    row.name = "Delivered"
    db.query(Task).update({Task.status: "Delivered"}, synchronize_session=False)
    _task(db, title="Was completed", assignee=me, status="Delivered", completed_at=utcnow())
    db.commit()

    d = work_digest.work_digest(db, me)
    assert d["mine"]["open"] == []                                   # not open — by STAGE
    assert [s["title"] for s in d["mine"]["done"]] == ["Was completed"]
    assert admin.id


def test_service_charge_never_crosses(db, make_user):
    """The one field on this table whose leak into a chat transcript is a commercial problem."""
    am = make_user(role=C.ROLE_ACCOUNT_MANAGER)
    _task(db, title="Billable", assignee=am, service_charge="45000")
    d = work_digest.work_digest(db, am)
    assert "45000" not in str(d)


# --- work_detail -------------------------------------------------------------------------------
def test_detail_returns_the_body_whole_with_owners_and_the_thread(db, make_user):
    me = make_user()
    mate = make_user(name="Mate")
    body = "x" * 5000
    t = _task(db, title="Deep card", assignee=me, description=body,
              internal_notes="internal only", on_hold=True, hold_reason="waiting on assets")
    t.maintasks_json = MT.dumps([{"id": "m1", "title": "Phase", "assignee_id": mate.id, "subs": [
        {"id": "s1", "text": "step one", "done": True, "assignee_id": me.id},
    ]}])
    db.add(TaskComment(task_id=t.id, author_id=mate.id, body="looks good"))
    db.add(TaskComment(task_id=t.id, client_author="Jane", body="can we change the headline?"))
    db.commit()

    card = work_digest.work_detail(db, me, [t.id])[0]
    assert card["description"] == body                  # WHOLE, never excerpted
    assert card["internal_notes"] == "internal only"
    assert card["parked_because"] == "waiting on assets"
    assert card["breakdown"][0]["owner"] == "Mate"
    assert card["breakdown"][0]["steps"][0]["owner"] == me.name
    assert {c["by"] for c in card["comments"]} == {"Mate", "Jane (client)"}


def test_detail_refuses_a_card_the_viewer_cannot_see(db, make_user):
    """🔴 An id is just an integer. The caller reads ids out of an index we scoped, but a coach — or a
    prompt injection reaching one — can name any number, so every id is re-checked."""
    me = make_user()
    other = make_user()
    hidden = _task(db, title="Not yours", assignee=other, description="secret")
    mine = _task(db, title="Yours", assignee=me, description="fine")

    got = work_digest.work_detail(db, me, [hidden.id, mine.id, 999999])
    assert [c["title"] for c in got] == ["Yours"]        # unseen and unknown are both just absent


def test_detail_caps_the_request_not_the_text(db, make_user):
    me = make_user()
    ids = [_task(db, title=f"C{i}", assignee=me, description="y" * 3000).id
           for i in range(work_digest.MAX_WORK_DETAIL_IDS + 5)]
    got = work_digest.work_detail(db, me, ids)
    assert len(got) == work_digest.MAX_WORK_DETAIL_IDS
    assert all(len(c["description"]) == 3000 for c in got)


# --- the HMAC endpoints ------------------------------------------------------------------------
def test_endpoints_need_a_valid_signature(client, db, make_user):
    make_user(email="worker@agora.ph")
    assert client.get("/api/internal/work-digest", params={"email": "worker@agora.ph"}).status_code == 401
    assert client.get("/api/internal/work-digest", params={"email": "worker@agora.ph"},
                      headers=_sig("holistic-profile")).status_code == 401   # wrong purpose
    ok = client.get("/api/internal/work-digest", params={"email": "worker@agora.ph"},
                    headers=_sig("work-digest"))
    assert ok.status_code == 200
    assert ok.json()["found"] is True


def test_an_unknown_or_inactive_email_degrades_to_nothing(client, db, make_user):
    make_user(email="gone@agora.ph", active=False)
    for email in ("nobody@agora.ph", "gone@agora.ph"):
        body = client.get("/api/internal/work-digest", params={"email": email},
                          headers=_sig("work-digest")).json()
        assert body == {"found": False, "digest": None}


def test_the_detail_endpoint_skips_malformed_and_atrium_ids(client, db, make_user):
    me = make_user(email="worker@agora.ph")
    t = _task(db, title="Real", assignee=me, description="body")
    body = client.get("/api/internal/work-detail",
                      params={"email": "worker@agora.ph", "ids": f"atrium:tcs:9,,oops,{t.id}"},
                      headers=_sig("work-detail")).json()
    assert [c["title"] for c in body["cards"]] == ["Real"]

"""Throughput history for Monitor (WP 6.2, §2.4i).

Monitor computed everything from the live table: a snapshot with no trend, no history and no
per-client view — so "are we getting faster?" and "which client is eating the team?" were questions
the board simply could not answer.

What must stay true:

* counted off `completed_at`, NEVER `updated_at` (§2.4h) — otherwise editing an old task re-dates
  its completion into this week;
* a task finished before the stamp existed is not counted at all, rather than attributed to
  whenever somebody last touched it;
* 🔴 the CURRENT week is flagged incomplete, and the average skips it — a 2-day week against a
  7-day mean reads as a collapse that never happened;
* archived work still counts: filing a shipped task must not erase that it shipped;
* a team lead sees their own team only; monitoring is a management surface, plus the read-only seat.
"""
from __future__ import annotations

from datetime import timedelta

from app import constants as C
from app.models import Client, Task
from app.utils.time import today_ph, utcnow


def _done(db, user, *, days_ago: int, **kw):
    """A completed task, stamped `days_ago` days back in Manila terms."""
    body = {"title": "shipped", "status": "Completed", "priority": "Medium",
            "created_by_id": user.id, "assigned_to_id": user.id,
            "completed_at": utcnow() - timedelta(days=days_ago)}
    body.update(kw)
    t = Task(**body)
    db.add(t)
    db.commit()
    return t


def _get(client, **q):
    qs = "&".join(f"{k}={v}" for k, v in q.items())
    return client.get("/api/tasks/throughput" + (f"?{qs}" if qs else ""))


# --- the series ---------------------------------------------------------------------------------

def test_it_returns_one_bucket_per_week(client, auth, make_user, db):
    auth(make_user(C.ROLE_ADMIN))
    body = _get(client, weeks=4).json()
    assert len(body["weeks"]) == 4
    assert all({"week_start", "week_end", "completed", "complete"} <= set(w) for w in body["weeks"])


def test_completed_work_lands_in_its_own_week(client, auth, make_user, db):
    u = auth(make_user(C.ROLE_ADMIN))
    _done(db, u, days_ago=0)
    _done(db, u, days_ago=0)
    body = _get(client, weeks=4).json()
    assert body["weeks"][-1]["completed"] == 2      # the current week is last


def test_the_current_week_is_flagged_incomplete(client, auth, make_user, db):
    """🔴 A partial week charted next to full ones reads as a collapse in throughput."""
    auth(make_user(C.ROLE_ADMIN))
    body = _get(client, weeks=4).json()
    assert body["weeks"][-1]["complete"] is False
    assert all(w["complete"] for w in body["weeks"][:-1])


def test_the_average_ignores_the_partial_week(client, auth, make_user, db):
    u = auth(make_user(C.ROLE_ADMIN))
    today = today_ph()
    # 4 shipped in a fully-elapsed week, 1 so far this week.
    monday = today - timedelta(days=today.weekday())
    for _ in range(4):
        _done(db, u, days_ago=(today - (monday - timedelta(days=3))).days)
    _done(db, u, days_ago=0)
    body = _get(client, weeks=4).json()
    # The 1-so-far must not drag the mean down; only complete weeks count.
    assert body["weekly_average"] == round(4 / 3, 1)


def test_work_outside_the_window_is_excluded(client, auth, make_user, db):
    u = auth(make_user(C.ROLE_ADMIN))
    _done(db, u, days_ago=200)
    body = _get(client, weeks=4).json()
    assert sum(w["completed"] for w in body["weeks"]) == 0


# --- the honesty rules ----------------------------------------------------------------------------

def test_a_task_with_no_completion_stamp_is_not_counted(client, auth, make_user, db):
    """Rows finished before the column existed have no honest date, so they get none."""
    u = auth(make_user(C.ROLE_ADMIN))
    db.add(Task(title="legacy", status="Completed", priority="Medium",
                created_by_id=u.id, assigned_to_id=u.id, completed_at=None))
    db.commit()
    body = _get(client, weeks=4).json()
    assert sum(w["completed"] for w in body["weeks"]) == 0


def test_archived_work_still_counts(client, auth, make_user, db):
    """Filing a shipped task must not erase the fact that it shipped."""
    u = auth(make_user(C.ROLE_ADMIN))
    _done(db, u, days_ago=0, archived=True)
    assert sum(w["completed"] for w in _get(client, weeks=4).json()["weeks"]) == 1


def test_a_reopened_task_is_not_counted_as_finished(client, auth, make_user, db):
    """It carries an old completed_at but is back in play — counting it would overstate delivery."""
    u = auth(make_user(C.ROLE_ADMIN))
    _done(db, u, days_ago=0, status="In Progress")
    assert sum(w["completed"] for w in _get(client, weeks=4).json()["weeks"]) == 0


# --- the rollups ---------------------------------------------------------------------------------

def test_per_client_rollup_answers_who_is_eating_the_team(client, auth, make_user, db):
    u = auth(make_user(C.ROLE_ADMIN))
    acme = Client(name="Acme", atrium_client_id="acme")
    db.add(acme)
    db.commit()
    _done(db, u, days_ago=0, client_id=acme.id)
    _done(db, u, days_ago=1, client_id=acme.id)
    _done(db, u, days_ago=1)                       # no client
    body = _get(client, weeks=4).json()
    top = body["by_client"][0]
    assert top["client_name"] == "Acme" and top["completed"] == 2
    assert any(r["client_name"] == "No client" for r in body["by_client"])


def test_per_person_rollup_is_ranked(client, auth, make_user, db, make_team):
    team = make_team("Acquisition")
    u = auth(make_user(C.ROLE_ADMIN, team_id=team.id))
    other = make_user(C.ROLE_EMPLOYEE, team_id=team.id)
    _done(db, u, days_ago=0)
    _done(db, u, days_ago=1)
    _done(db, u, days_ago=1, assigned_to_id=other.id)
    body = _get(client, weeks=4).json()
    assert body["by_person"][0]["completed"] == 2


# --- scope ----------------------------------------------------------------------------------------

def test_an_employee_cannot_monitor(client, auth, make_user, make_team):
    team = make_team("Acquisition")
    auth(make_user(C.ROLE_EMPLOYEE, team_id=team.id))
    assert _get(client).status_code == 403


def test_the_read_only_seat_can_monitor(client, auth, make_user):
    """Monitoring is the viewer's entire purpose (D8)."""
    auth(make_user("viewer"))
    assert _get(client).status_code == 200


def test_a_team_lead_sees_only_their_own_team(client, auth, make_user, make_team, db):
    mine, theirs = make_team("Acquisition"), make_team("Lifecycle")
    lead = make_user(C.ROLE_TEAM_LEAD, team_id=mine.id)
    mate = make_user(C.ROLE_EMPLOYEE, team_id=mine.id)
    stranger = make_user(C.ROLE_EMPLOYEE, team_id=theirs.id)
    _done(db, lead, days_ago=0, assigned_to_id=mate.id)
    _done(db, lead, days_ago=0, assigned_to_id=stranger.id)

    auth(lead)
    body = _get(client, weeks=4).json()
    assert sum(w["completed"] for w in body["weeks"]) == 1, "another team's delivery leaked in"
    assert [r["user"]["id"] for r in body["by_person"]] == [mate.id]


def test_an_admin_sees_every_team(client, auth, make_user, make_team, db):
    mine, theirs = make_team("Acquisition"), make_team("Lifecycle")
    admin = make_user(C.ROLE_ADMIN)
    mate = make_user(C.ROLE_EMPLOYEE, team_id=mine.id)
    stranger = make_user(C.ROLE_EMPLOYEE, team_id=theirs.id)
    _done(db, admin, days_ago=0, assigned_to_id=mate.id)
    _done(db, admin, days_ago=0, assigned_to_id=stranger.id)

    auth(admin)
    assert sum(w["completed"] for w in _get(client, weeks=4).json()["weeks"]) == 2


def test_the_window_is_bounded(client, auth, make_user):
    auth(make_user(C.ROLE_ADMIN))
    assert _get(client, weeks=1).status_code == 422        # too narrow to show a trend
    assert _get(client, weeks=99).status_code == 422       # not an unbounded table scan

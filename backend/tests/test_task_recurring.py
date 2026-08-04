"""Recurring / retainer services (WP 6.1, M10).

Monthly deliverables were re-created by hand, so they got forgotten in exactly the months somebody
was too busy to remember — which is when the client notices.

🔴 The invariants under test are all consequences of ONE design choice: a recurrence records the
last PERIOD KEY it generated for ("2026-08"), not a timestamp.

* generating twice in a period is impossible, however often the tick runs;
* a tick that has been down for three months generates ONE task on its return, not three;
* a recurrence created today never retro-generates the periods before it existed;
* editing a recurrence does not re-open a period it has already produced.

Duplicated retainer work is worse than late retainer work: somebody does it twice and bills once.
"""
from __future__ import annotations

from datetime import date

from app import constants as C
from app.models import RecurringService, Task
from app.services import task_recurring as R


def _rec(db, **kw):
    body = {"title": "Monthly SEO report", "cadence": "monthly", "day_of_period": 1,
            "priority": "Medium", "is_active": True}
    body.update(kw)
    r = RecurringService(**body)
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


# --- the period key ------------------------------------------------------------------------------

def test_the_monthly_key_is_the_month():
    assert R.period_key("monthly", date(2026, 8, 4)) == "2026-08"
    assert R.period_key("monthly", date(2026, 8, 31)) == "2026-08"
    assert R.period_key("monthly", date(2026, 9, 1)) == "2026-09"


def test_the_weekly_key_is_the_iso_week():
    mon = date(2026, 8, 3)
    assert R.period_key("weekly", mon) == R.period_key("weekly", mon.replace(day=9))
    assert R.period_key("weekly", mon) != R.period_key("weekly", date(2026, 8, 10))


def test_a_monthly_trigger_day_is_clamped_to_short_months(db):
    """A retainer set to "the 31st" must still fire in February — a recurrence that silently skips
    short months is a support ticket, not a feature."""
    rec = _rec(db, day_of_period=31)
    assert R.trigger_day(rec, date(2026, 2, 15)) == date(2026, 2, 28)
    assert R.trigger_day(rec, date(2026, 1, 15)) == date(2026, 1, 31)


# --- due-ness --------------------------------------------------------------------------------------

def test_it_is_due_on_and_after_its_day(db):
    rec = _rec(db, day_of_period=10, last_period=None)
    assert not R.is_due(rec, date(2026, 8, 9))
    assert R.is_due(rec, date(2026, 8, 10))
    assert R.is_due(rec, date(2026, 8, 20))     # late is still due — better late than never


def test_it_is_not_due_twice_in_a_period(db):
    rec = _rec(db, day_of_period=1, last_period="2026-08")
    assert not R.is_due(rec, date(2026, 8, 1))
    assert not R.is_due(rec, date(2026, 8, 28))
    assert R.is_due(rec, date(2026, 9, 1))      # the next period is a different question


def test_an_inactive_recurrence_never_fires(db):
    rec = _rec(db, is_active=False, last_period=None)
    assert not R.is_due(rec, date(2026, 8, 20))


# --- generation ---------------------------------------------------------------------------------

def test_running_creates_the_task_and_claims_the_period(db, make_user):
    make_user(C.ROLE_ADMIN)
    _rec(db, day_of_period=1, last_period=None)
    out = R.run(db, date(2026, 8, 4))
    assert out["count"] == 1
    task = db.query(Task).one()
    # The period is in the title: three "Monthly SEO report" cards are indistinguishable otherwise,
    # and knowing WHICH month is outstanding is the entire point.
    assert task.title == "Monthly SEO report — 2026-08"
    assert db.query(RecurringService).one().last_period == "2026-08"


def test_running_twice_in_a_day_creates_one_task(db, make_user):
    make_user(C.ROLE_ADMIN)
    _rec(db, day_of_period=1, last_period=None)
    R.run(db, date(2026, 8, 4))
    assert R.run(db, date(2026, 8, 4))["count"] == 0
    assert db.query(Task).count() == 1


def test_a_tick_down_for_three_months_generates_one_task(db, make_user):
    """🔴 Not three. Catching up on missed periods would dump invented work on somebody's Monday."""
    make_user(C.ROLE_ADMIN)
    _rec(db, day_of_period=1, last_period="2026-05")
    out = R.run(db, date(2026, 8, 4))
    assert out["count"] == 1
    assert db.query(Task).one().title.endswith("2026-08")


def test_successive_periods_each_generate_once(db, make_user):
    make_user(C.ROLE_ADMIN)
    _rec(db, day_of_period=1, last_period=None)
    for day in (date(2026, 8, 1), date(2026, 8, 15), date(2026, 9, 1), date(2026, 9, 20)):
        R.run(db, day)
    titles = sorted(t.title for t in db.query(Task).all())
    assert titles == ["Monthly SEO report — 2026-08", "Monthly SEO report — 2026-09"]


def test_the_generated_task_carries_the_routing_and_dates(db, make_user, make_team):
    team = make_team("Acquisition")
    who = make_user(C.ROLE_EMPLOYEE, team_id=team.id)
    _rec(db, day_of_period=1, last_period=None, assigned_team_id=team.id,
         assigned_to_id=who.id, due_in_days=7, priority="Urgent")
    R.run(db, date(2026, 8, 4))
    t = db.query(Task).one()
    assert t.assigned_team_id == team.id and t.assigned_to_id == who.id
    assert t.priority == "Urgent"
    assert t.start_date == date(2026, 8, 4) and t.due_date == date(2026, 8, 11)


# --- no backfill ------------------------------------------------------------------------------------

# NB: `is_active=True` is set explicitly here. It is a COLUMN default, applied on INSERT, so a
# model object that has never been committed reads None — these two tests exercise `seed_period`
# on a detached object, before it is added.

def test_a_recurrence_created_after_its_day_starts_next_period(db):
    """Set up on the 20th with "the 1st": this month is NOT invented retroactively."""
    rec = RecurringService(title="x", cadence="monthly", day_of_period=1, is_active=True)
    R.seed_period(rec, date(2026, 8, 20))
    assert rec.last_period == "2026-08"
    assert not R.is_due(rec, date(2026, 8, 21))
    assert R.is_due(rec, date(2026, 9, 1))


def test_a_recurrence_created_before_its_day_fires_this_period(db):
    """Set up on the 5th with "the 10th": firing this month is what the person expects."""
    rec = RecurringService(title="x", cadence="monthly", day_of_period=10, is_active=True)
    R.seed_period(rec, date(2026, 8, 5))
    assert rec.last_period is None
    assert R.is_due(rec, date(2026, 8, 10))


# --- the endpoints ------------------------------------------------------------------------------

def test_crud_round_trip(client, auth, make_user, db):
    auth(make_user(C.ROLE_ADMIN))
    made = client.post("/api/tasks/recurring",
                       json={"title": "Monthly report", "cadence": "monthly",
                             "day_of_period": 1, "due_in_days": 3})
    assert made.status_code == 200, made.text
    rid = made.json()["id"]
    assert made.json()["next_due"]

    assert any(r["id"] == rid for r in client.get("/api/tasks/recurring").json())

    upd = client.patch(f"/api/tasks/recurring/{rid}",
                       json={"title": "Monthly report v2", "cadence": "monthly",
                             "day_of_period": 1, "due_in_days": 3})
    assert upd.json()["title"] == "Monthly report v2"

    assert client.delete(f"/api/tasks/recurring/{rid}").json()["ok"] is True
    assert client.get("/api/tasks/recurring").json() == []


def test_editing_does_not_reopen_a_generated_period(client, auth, make_user, db):
    """🔴 Renaming a recurrence must never cause this period's task to be made a second time."""
    auth(make_user(C.ROLE_ADMIN))
    rec = _rec(db, day_of_period=1, last_period="2026-08")
    client.patch(f"/api/tasks/recurring/{rec.id}",
                 json={"title": "renamed", "cadence": "monthly", "day_of_period": 1})
    db.refresh(rec)
    assert rec.last_period == "2026-08"


def test_deleting_leaves_already_generated_tasks_alone(client, auth, make_user, db):
    auth(make_user(C.ROLE_ADMIN))
    _rec(db, day_of_period=1, last_period=None)
    R.run(db, date(2026, 8, 4))
    rid = db.query(RecurringService).one().id
    client.delete(f"/api/tasks/recurring/{rid}")
    assert db.query(Task).count() == 1, "generated work is ordinary work and stays"


def test_run_now_is_manager_only(client, auth, make_user, make_team):
    team = make_team("Acquisition")
    auth(make_user(C.ROLE_EMPLOYEE, team_id=team.id))
    assert client.post("/api/tasks/recurring/run").status_code == 403
    assert client.get("/api/tasks/recurring").status_code == 403


def test_recurring_is_not_swallowed_as_a_task_id(client, auth, make_user):
    """Declared before GET /{task_id} or FastAPI matches "recurring" as an id (AGENTS.md §5)."""
    auth(make_user(C.ROLE_ADMIN))
    assert client.get("/api/tasks/recurring").status_code == 200

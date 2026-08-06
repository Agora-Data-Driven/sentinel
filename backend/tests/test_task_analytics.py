"""The Monitor's derived workload metrics (`services/task_analytics.py` + `/api/tasks/summary`).

Two things are being pinned, and the first one matters more than all the numbers:

**1. The rollup counts STEP owners.** It bucketed by `assigned_to_id` alone, so anyone whose work
arrives as phases/steps of colleagues' cards read as **idle** on the Monitor — the same blind spot
the Overview's "my work" strip had (`test_task_mine.py`). Every metric below is computed over that
bucket, so getting it wrong would have quietly poisoned the lot.

**2. Nothing here invents a number it cannot support.** A task on this board carries no size, so:
`on_time_rate` is `None` — never `0` — when nothing datable was completed; `median_cycle_days` is
`None` when nothing has a start and an end; and `load_band` is a comparison against the cohort's own
median, suppressed entirely when the cohort has almost no work. Those None-vs-zero cases are the
tests most likely to be "simplified" away by someone tidying up, and each one is a lie if you do.
"""
from __future__ import annotations

from datetime import date, timedelta

from app import constants as C
from app.models import LeaveRequest, Task
from app.services import task_analytics
from app.utils.time import utcnow


def _row(client, uid, days=None):
    url = "/api/tasks/summary" + (f"?days={days}" if days else "")
    return next(r for r in client.get(url).json() if r["user"]["id"] == uid)


def _breakdown(step_owner=None, phase_owner=None):
    import json
    return json.dumps([{"id": "m1", "title": "Phase", "assignee_id": phase_owner,
                        "subs": [{"id": "s1", "text": "Step", "done": False,
                                  "assignee_id": step_owner}]}])


# --- 1. the bucketing fix ------------------------------------------------------------------------

def test_a_step_owner_is_not_invisible_on_the_monitor(client, db, make_user, auth):
    """🔴 THE REGRESSION. Led by a colleague, one step named to Ana — the Monitor read her as idle,
    and every KPI built on that would have said she had capacity to spare."""
    boss = make_user(C.ROLE_ADMIN)
    lead_user = make_user(C.ROLE_EMPLOYEE, name="Jerome")
    ana = make_user(C.ROLE_EMPLOYEE, name="Ana")
    db.add(Task(title="Led by Jerome", assigned_to_id=lead_user.id, status=C.TASK_IN_PROGRESS,
                maintasks_json=_breakdown(step_owner=ana.id)))
    db.commit()

    auth(boss)
    assert _row(client, ana.id)["open_total"] == 1
    assert _row(client, ana.id)["stepped"] == 1, "flagged as somebody else's card"
    # And it still counts for the person who LEADS it — a shared card is on both plates.
    assert _row(client, lead_user.id)["open_total"] == 1
    assert _row(client, lead_user.id)["stepped"] == 0


def test_a_card_you_lead_is_not_counted_as_stepped(client, db, make_user, auth):
    boss = make_user(C.ROLE_ADMIN)
    ana = make_user(C.ROLE_EMPLOYEE)
    db.add(Task(title="Hers outright", assigned_to_id=ana.id, status=C.TASK_TODO))
    db.commit()
    auth(boss)
    row = _row(client, ana.id)
    assert row["open_total"] == 1
    assert row["stepped"] == 0


def test_assigned_user_ids_is_the_set_form_of_is_assigned(db, make_user):
    """The two must never drift — `is_assigned` is defined in terms of this set for that reason."""
    from app.services import task_perms
    a = make_user(C.ROLE_EMPLOYEE)
    b = make_user(C.ROLE_EMPLOYEE)
    c = make_user(C.ROLE_EMPLOYEE)
    t = Task(title="Shared", assigned_to_id=a.id,
             maintasks_json=_breakdown(step_owner=b.id, phase_owner=c.id))
    db.add(t)
    db.commit()
    assert task_perms.assigned_user_ids(t) == {a.id, b.id, c.id}
    for u in (a, b, c):
        assert task_perms.is_assigned(u, t) is True


# --- 2. delivery metrics -------------------------------------------------------------------------

def test_cycle_time_and_on_time_rate(client, db, make_user, auth):
    boss = make_user(C.ROLE_ADMIN)
    ana = make_user(C.ROLE_EMPLOYEE)
    today = date.today()
    db.add_all([
        # Started 10 days ago, finished today, due yesterday -> 10-day cycle, LATE.
        Task(title="Late", assigned_to_id=ana.id, status=C.TASK_COMPLETED,
             start_date=today - timedelta(days=10), due_date=today - timedelta(days=1),
             completed_at=utcnow()),
        # Started 2 days ago, finished today, due tomorrow -> 2-day cycle, ON TIME.
        Task(title="On time", assigned_to_id=ana.id, status=C.TASK_COMPLETED,
             start_date=today - timedelta(days=2), due_date=today + timedelta(days=1),
             completed_at=utcnow()),
    ])
    db.commit()
    auth(boss)
    row = _row(client, ana.id)
    assert row["median_cycle_days"] == 6.0        # median of [10, 2]
    assert row["on_time_rate"] == 50              # 1 of 2 dated completions
    assert row["on_time_of"] == 2
    assert row["completed_window"] == 2


def test_on_time_rate_is_none_not_zero_when_nothing_dated_shipped(client, db, make_user, auth):
    """🔴 The one that must not be 'simplified'. Zero means "everything was late"; this person simply
    finished nothing with a deadline, and rendering both in the same red is a slander."""
    boss = make_user(C.ROLE_ADMIN)
    ana = make_user(C.ROLE_EMPLOYEE)
    db.add(Task(title="Undated done", assigned_to_id=ana.id, status=C.TASK_COMPLETED,
                completed_at=utcnow()))
    db.commit()
    auth(boss)
    row = _row(client, ana.id)
    assert row["on_time_rate"] is None
    assert row["on_time_of"] == 0
    assert row["completed_window"] == 1, "it still counts as work shipped"


def test_an_undated_completion_is_excluded_rather_than_counted_on_time(client, db, make_user, auth):
    """A card with no due date made no promise, so it may neither help nor hurt the rate."""
    boss = make_user(C.ROLE_ADMIN)
    ana = make_user(C.ROLE_EMPLOYEE)
    today = date.today()
    db.add_all([
        Task(title="Undated", assigned_to_id=ana.id, status=C.TASK_COMPLETED, completed_at=utcnow()),
        Task(title="Late", assigned_to_id=ana.id, status=C.TASK_COMPLETED,
             due_date=today - timedelta(days=2), completed_at=utcnow()),
    ])
    db.commit()
    auth(boss)
    row = _row(client, ana.id)
    assert row["on_time_of"] == 1        # only the dated one is judged
    assert row["on_time_rate"] == 0      # and it was late


def test_work_completed_before_the_window_is_out_of_the_rate(client, db, make_user, auth):
    boss = make_user(C.ROLE_ADMIN)
    ana = make_user(C.ROLE_EMPLOYEE)
    old = utcnow() - timedelta(days=60)
    db.add(Task(title="Ancient", assigned_to_id=ana.id, status=C.TASK_COMPLETED,
                due_date=date.today() - timedelta(days=61), completed_at=old))
    db.commit()
    auth(boss)
    assert _row(client, ana.id, days=30)["completed_window"] == 0
    assert _row(client, ana.id, days=90)["completed_window"] == 1


def test_a_completion_with_no_stamp_is_counted_in_no_window(client, db, make_user, auth):
    """Rows finished before `completed_at` existed. Counting them off `updated_at` is the bug §2.4h
    was about, so they are honestly counted nowhere."""
    boss = make_user(C.ROLE_ADMIN)
    ana = make_user(C.ROLE_EMPLOYEE)
    db.add(Task(title="Unstamped", assigned_to_id=ana.id, status=C.TASK_COMPLETED))
    db.commit()
    auth(boss)
    assert _row(client, ana.id)["completed_window"] == 0


# --- 3. aging ------------------------------------------------------------------------------------

def test_sitting_counts_untouched_open_work(client, db, make_user, auth):
    boss = make_user(C.ROLE_ADMIN)
    ana = make_user(C.ROLE_EMPLOYEE)
    long_ago = utcnow() - timedelta(days=task_analytics.STALE_DAYS + 5)
    t = Task(title="Forgotten", assigned_to_id=ana.id, status=C.TASK_TODO)
    db.add(t)
    db.commit()
    # created_at/updated_at have server defaults, so age them explicitly.
    t.created_at = long_ago
    t.updated_at = long_ago
    db.commit()
    auth(boss)
    row = _row(client, ana.id)
    assert row["stale_open"] == 1
    assert row["oldest_open_days"] >= task_analytics.STALE_DAYS
    assert row["stale_days"] == task_analytics.STALE_DAYS, "the UI labels the column from this"


def test_a_completed_card_is_never_sitting(client, db, make_user, auth):
    """`aging` is fed only the OPEN pile — finished work cannot be stale."""
    boss = make_user(C.ROLE_ADMIN)
    ana = make_user(C.ROLE_EMPLOYEE)
    t = Task(title="Old but done", assigned_to_id=ana.id, status=C.TASK_COMPLETED,
             completed_at=utcnow())
    db.add(t)
    db.commit()
    t.updated_at = utcnow() - timedelta(days=90)
    db.commit()
    auth(boss)
    assert _row(client, ana.id)["stale_open"] == 0


# --- 4. capacity ---------------------------------------------------------------------------------

def test_approved_leave_shows_as_capacity(client, db, make_user, make_leave_type, auth):
    boss = make_user(C.ROLE_ADMIN)
    ana = make_user(C.ROLE_EMPLOYEE)
    lt = make_leave_type()
    today = date.today()
    db.add(LeaveRequest(user_id=ana.id, leave_type_id=lt.id, start_date=today,
                        end_date=today + timedelta(days=2), total_days=3, reason="Trip",
                        status=C.LEAVE_APPROVED))
    db.commit()
    auth(boss)
    row = _row(client, ana.id)
    assert row["on_leave_today"] is True
    assert row["leave_days_ahead"] == 3


def test_pending_leave_is_not_capacity(client, db, make_user, make_leave_type, auth):
    """A request is a question, not a fact about who is at their desk."""
    boss = make_user(C.ROLE_ADMIN)
    ana = make_user(C.ROLE_EMPLOYEE)
    lt = make_leave_type()
    today = date.today()
    db.add(LeaveRequest(user_id=ana.id, leave_type_id=lt.id, start_date=today,
                        end_date=today, total_days=1, reason="Maybe",
                        status=C.LEAVE_PENDING))
    db.commit()
    auth(boss)
    row = _row(client, ana.id)
    assert row["on_leave_today"] is False
    assert row["leave_days_ahead"] == 0


# --- 5. the load band ----------------------------------------------------------------------------

def test_load_band_is_relative_and_suppressed_on_a_quiet_board():
    """No band at all when the cohort's median is under 2 — "double the median" is one card there,
    and a confident verdict off one card is worse than silence."""
    rows = [{"open_total": 2, "overdue": 0}, {"open_total": 0, "overdue": 0},
            {"open_total": 1, "overdue": 0}]
    task_analytics.apply_load_bands(rows)
    assert all(r["load_band"] is None for r in rows)


def test_load_band_ranks_against_the_cohort_median():
    rows = [{"open_total": 12, "overdue": 0}, {"open_total": 6, "overdue": 0},
            {"open_total": 5, "overdue": 0}, {"open_total": 1, "overdue": 0}]
    task_analytics.apply_load_bands(rows)
    bands = [r["load_band"] for r in rows]
    assert bands[0] == "heavy"      # 12 vs a median of 5.5
    assert bands[1] == "steady"
    assert bands[3] == "light"


def test_overdue_makes_a_small_pile_heavy():
    """Three late cards is a person in trouble; a purely volumetric band calls them 'light'."""
    rows = [{"open_total": 10, "overdue": 0}, {"open_total": 8, "overdue": 0},
            {"open_total": 2, "overdue": 3}]
    task_analytics.apply_load_bands(rows)
    assert rows[2]["load_band"] == "heavy"


# --- 6. the metrics agree with the rest of the board ---------------------------------------------

# --- 7. Atrium client work counts toward its LEAD ------------------------------------------------
#
# The rollup queried Sentinel's `tasks` table only, so every card Atrium owns counted toward NOBODY:
# a person holding fifteen client cards read as idle on the table a manager staffs from. Joined on
# the lead's EMAIL (an Atrium owner is a roster email, not a Sentinel id).

def _atrium_card(**over):
    c = {"atrium_id": "rooming-house:tk_1", "task_id": "tk_1", "client_key": "rooming-house",
         "title": "ActiveCampaign fix", "stage": "in_progress", "status": "In Progress",
         "priority": "Medium", "atrium_lead_id": "ana@agora.ph", "due_date": "", "start_date": "",
         "created_at": "", "updated_at": ""}
    c.update(over)
    return c


def _with_atrium(monkeypatch, cards):
    from app.services import atrium_tasks
    monkeypatch.setattr(atrium_tasks, "enabled", lambda: True)
    monkeypatch.setattr(atrium_tasks, "fetch_tasks", lambda *a, **k: cards)


def test_a_client_card_counts_toward_the_lead_it_resolves_to(client, db, make_user, auth, monkeypatch):
    boss = make_user(C.ROLE_ADMIN)
    ana = make_user(C.ROLE_EMPLOYEE, name="Ana", email="ana@agora.ph")
    _with_atrium(monkeypatch, [_atrium_card()])
    auth(boss)
    row = _row(client, ana.id)
    assert row["open_total"] == 1
    assert row["client_cards"] == 1
    assert row["stepped"] == 0, "the Atrium lead IS the owner, not a step-holder"


def test_a_client_card_is_overdue_like_any_other(client, db, make_user, auth, monkeypatch):
    boss = make_user(C.ROLE_ADMIN)
    ana = make_user(C.ROLE_EMPLOYEE, email="ana@agora.ph")
    past = (date.today() - timedelta(days=4)).isoformat()
    _with_atrium(monkeypatch, [_atrium_card(due_date=past)])
    auth(boss)
    assert _row(client, ana.id)["overdue"] == 1


def test_a_client_card_never_reaches_cycle_or_on_time(client, db, make_user, auth, monkeypatch):
    """🔴 Atrium sends NO completion stamp. Counting these off `updated_at` is the §2.4h bug, so they
    are excluded — and `client_cards` is what lets the UI admit it instead of implying the person
    never ships."""
    boss = make_user(C.ROLE_ADMIN)
    ana = make_user(C.ROLE_EMPLOYEE, email="ana@agora.ph")
    _with_atrium(monkeypatch, [_atrium_card(stage="completed", status="Completed",
                                            due_date=date.today().isoformat(),
                                            updated_at="2026-08-01T10:00:00")])
    auth(boss)
    row = _row(client, ana.id)
    assert row["completed_window"] == 0
    assert row["median_cycle_days"] is None
    assert row["on_time_rate"] is None
    # 🔴 0, not 1 (2026-08-06): `client_cards` is OPEN client work, and this card is Completed. It
    # asserted 1 here while the value was `len(rows)` — a total. The Monitor renders it as a
    # sub-line UNDER the Open count, so a total could exceed the number it broke down ("8 open · 19
    # client"). What tells a reader these cards can't reach Cycle/On-time is the LEGEND, which says
    # so for the whole table; it is not this per-row number's job.
    assert row["client_cards"] == 0
    assert row["open_total"] == 0


def test_client_cards_counts_only_the_OPEN_ones(client, db, make_user, auth, monkeypatch):
    """🔴 It sits under Open, beside `stepped` and `supporting` — both open-scoped. A total made the
    row say "1 open · 2 client", which is not a fact about anything."""
    boss = make_user(C.ROLE_ADMIN)
    ana = make_user(C.ROLE_EMPLOYEE, name="Ana", email="ana@agora.ph")
    _with_atrium(monkeypatch, [
        _atrium_card(task_id="tk_open"),
        _atrium_card(task_id="tk_done", stage="completed", status="Completed"),
    ])
    auth(boss)
    row = _row(client, ana.id)
    assert row["open_total"] == 1
    assert row["client_cards"] == 1, "the completed one is not open client work"
    assert row["client_cards"] <= row["open_total"], "it can never exceed the count it breaks down"


def test_a_lead_with_no_sentinel_account_is_counted_for_nobody(client, db, make_user, auth, monkeypatch):
    """Inventing an owner is worse than a gap."""
    boss = make_user(C.ROLE_ADMIN)
    ana = make_user(C.ROLE_EMPLOYEE, email="ana@agora.ph")
    _with_atrium(monkeypatch, [_atrium_card(atrium_lead_id="contractor@elsewhere.com")])
    auth(boss)
    assert _row(client, ana.id)["client_cards"] == 0
    assert _row(client, boss.id)["client_cards"] == 0


def test_the_email_match_is_case_insensitive(client, db, make_user, auth, monkeypatch):
    boss = make_user(C.ROLE_ADMIN)
    ana = make_user(C.ROLE_EMPLOYEE, email="ana@agora.ph")
    _with_atrium(monkeypatch, [_atrium_card(atrium_lead_id="  Ana@Agora.PH ")])
    auth(boss)
    assert _row(client, ana.id)["client_cards"] == 1


def test_a_card_already_claimed_by_a_sentinel_row_is_not_double_counted(client, db, make_user,
                                                                       auth, monkeypatch):
    """WP 4.3: a linked row IS that card. Counting both inflates the same work twice."""
    from app.models import Client as ClientModel
    boss = make_user(C.ROLE_ADMIN)
    ana = make_user(C.ROLE_EMPLOYEE, email="ana@agora.ph")
    cl = ClientModel(name="Rooming House", atrium_client_id="rooming-house")
    db.add(cl)
    db.commit()
    db.add(Task(title="The linked row", assigned_to_id=ana.id, status=C.TASK_IN_PROGRESS,
                client_id=cl.id, atrium_task_id="tk_1"))
    db.commit()
    _with_atrium(monkeypatch, [_atrium_card()])
    auth(boss)
    row = _row(client, ana.id)
    assert row["open_total"] == 1, "the Sentinel row only — not it plus the bridge's copy"
    assert row["client_cards"] == 0


def test_an_atrium_outage_costs_the_client_half_not_the_page(client, db, make_user, auth, monkeypatch):
    """Fail-soft, like every read of this bridge. `fetch_tasks` answers [] on any failure."""
    from app.services import atrium_tasks
    boss = make_user(C.ROLE_ADMIN)
    ana = make_user(C.ROLE_EMPLOYEE, email="ana@agora.ph")
    db.add(Task(title="Sentinel's own", assigned_to_id=ana.id, status=C.TASK_TODO))
    db.commit()
    monkeypatch.setattr(atrium_tasks, "enabled", lambda: True)
    monkeypatch.setattr(atrium_tasks, "fetch_tasks", lambda *a, **k: [])
    auth(boss)
    row = _row(client, ana.id)
    assert row["open_total"] == 1
    assert row["client_cards"] == 0


def test_a_malformed_atrium_date_does_not_break_the_monitor(client, db, make_user, auth, monkeypatch):
    """🔴 Atrium sends dates as STRINGS; the rollups compare them with `date`. Left unparsed, one bad
    field on one client card takes the whole manager surface down with a TypeError."""
    boss = make_user(C.ROLE_ADMIN)
    ana = make_user(C.ROLE_EMPLOYEE, email="ana@agora.ph")
    _with_atrium(monkeypatch, [_atrium_card(due_date="not-a-date", created_at="???")])
    auth(boss)
    row = _row(client, ana.id)
    assert row["open_total"] == 1
    assert row["overdue"] == 0


def test_filed_work_leaves_the_plate_but_still_counts_as_shipped(client, db, make_user, auth):
    """Same rule `_aggregate` already followed — the new columns must not contradict it."""
    boss = make_user(C.ROLE_ADMIN)
    ana = make_user(C.ROLE_EMPLOYEE)
    db.add(Task(title="Delivered and filed", assigned_to_id=ana.id, status=C.TASK_COMPLETED,
                archived=True, completed_at=utcnow(), due_date=date.today()))
    db.commit()
    auth(boss)
    row = _row(client, ana.id)
    assert row["open_total"] == 0
    assert row["completed_week"] == 1
    assert row["completed_window"] == 1
    assert row["on_time_rate"] == 100

"""The Physical tab's coach-visibility toggle.

Someone can train six days a week and log none of it. The coach was reading a low
`sessions_last_14d` as a fact about their TRAINING and telling them they had been inconsistent.
Turning the toggle off withholds the log — and, crucially, SAYS SO in the digest, so the coach
cannot reach the same wrong conclusion from the gap instead.

Weighted toward that second half: every test below that matters is about what the digest still
says once the numbers are gone.
"""
from __future__ import annotations

from datetime import timedelta

from app.constants import GYM_COMPLETED
from app.models import GymLog
from app.services import development as dev_svc
from app.utils.time import today_ph


def _log_sessions(db, user, n, status=GYM_COMPLETED):
    today = today_ph()
    for i in range(n):
        db.add(GymLog(user_id=user.id, date=today - timedelta(days=i), day_type="Push", status=status))
    db.commit()


# --- the setting itself ------------------------------------------------------

def test_defaults_to_on_for_a_user_who_has_never_touched_it(client, make_user, auth):
    auth(make_user())
    assert client.get("/api/gym/coach-visibility").json() == {"reads_logs": True}


def test_default_holds_with_no_profile_row_at_all(db, make_user):
    """The 1:1 profile row is created lazily, so the common case is no row. That must read as
    ON — a missing row is not a person who opted out."""
    user = make_user()
    assert dev_svc.coach_reads_gym_logs(db, user.id) is True


def test_toggle_off_then_on_round_trips(client, make_user, auth):
    auth(make_user())
    assert client.put("/api/gym/coach-visibility", json={"reads_logs": False}).json() == {"reads_logs": False}
    assert client.get("/api/gym/coach-visibility").json() == {"reads_logs": False}
    assert client.put("/api/gym/coach-visibility", json={"reads_logs": True}).json() == {"reads_logs": True}
    assert client.get("/api/gym/coach-visibility").json() == {"reads_logs": True}


def test_the_route_is_not_swallowed_by_the_log_id_route(client, make_user, auth):
    """`GET /{log_id}` sits at the bottom of routers/gym.py and parses an int. A
    `/coach-visibility` registered after it answers 422 instead of the setting — the same trap
    the routines routes carry a comment about."""
    auth(make_user())
    r = client.get("/api/gym/coach-visibility")
    assert r.status_code == 200, r.text
    assert "reads_logs" in r.json()


def test_it_is_the_callers_own_setting_only(client, make_user, auth, db):
    """No `?user=`, no manager override: one person's answer never moves another's."""
    a, b = make_user(), make_user()
    auth(a)
    client.put("/api/gym/coach-visibility", json={"reads_logs": False})
    assert dev_svc.coach_reads_gym_logs(db, b.id) is True


# --- what the coach actually receives ----------------------------------------

def test_digest_carries_the_counts_while_the_toggle_is_on(db, make_user):
    user = make_user()
    _log_sessions(db, user, 3)
    gym = dev_svc.holistic_digest(db, user)["gym"]
    assert gym["logs_shared"] is True
    assert gym["sessions_last_14d"] == 3
    assert gym["completed_last_14d"] == 3


def test_digest_DECLARES_the_withholding_rather_than_going_quiet(db, make_user):
    """🔴 The point of the whole feature. `logs_shared: False` is what the engine renders as
    "draw no conclusion". A digest that merely dropped the key would leave the coach to read
    absence as zero — which is what it did before, via `?? 0`."""
    user = make_user()
    _log_sessions(db, user, 3)
    dev_svc.set_coach_reads_gym_logs(db, user.id, False)
    gym = dev_svc.holistic_digest(db, user)["gym"]
    assert gym["logs_shared"] is False
    assert "logs_shared" in gym          # declared, never merely absent
    assert gym["sessions_last_14d"] is None
    assert gym["completed_last_14d"] is None


def test_withheld_counts_are_None_and_never_zero(db, make_user):
    """A zero is a claim ("they trained zero times"); None is the absence of one. The engine
    branches on `logs_shared`, but anything reading these must not find a number to believe."""
    user = make_user()
    _log_sessions(db, user, 5)
    dev_svc.set_coach_reads_gym_logs(db, user.id, False)
    gym = dev_svc.holistic_digest(db, user)["gym"]
    assert gym["sessions_last_14d"] is None
    assert gym["completed_last_14d"] is None
    # Identity, not equality: `0 == False == None`-adjacent bugs are exactly how an absence
    # turns back into a claim on the way through a template.
    assert not isinstance(gym["sessions_last_14d"], int)


def test_the_plan_prs_and_targets_still_reach_the_coach(db, make_user):
    """Off hides the LOG, not the person. The weekly split drives the coach's training-load
    advice about studying, and losing it would be a bigger regression than the bug."""
    user = make_user()
    from app.services import gym as gym_svc
    gym_svc.set_week(db, user.id, {"Mon": "Push", "Tue": "Pull", "Wed": "Legs",
                                   "Thu": "Push", "Fri": "Legs", "Sat": "Rest", "Sun": "Rest"}, None)
    dev_svc.set_coach_reads_gym_logs(db, user.id, False)
    digest = dev_svc.holistic_digest(db, user)
    assert digest["gym"]["weekly_split"]["Mon"] == "Push"
    assert "physical" in digest and "targets" in digest["physical"]


def test_the_personal_report_honours_it_too(db, make_user):
    """The daily context report is read the same way the digest is; a setting honoured in one
    place and not the other is not a setting."""
    from app.services import personal_report
    user = make_user()
    _log_sessions(db, user, 4)

    on = personal_report.build(db, user)["markdown"]
    assert "Sessions logged" in on

    dev_svc.set_coach_reads_gym_logs(db, user.id, False)
    off = personal_report.build(db, user)["markdown"]
    assert "Sessions logged" not in off
    assert "Not shared" in off           # the gap is named, exactly as in the digest

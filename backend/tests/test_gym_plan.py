"""The weekly plan, calendar, and always-editable (no-lock) session flow."""
from __future__ import annotations


def test_default_plan_is_ppl(client, make_user, auth):
    auth(make_user())
    r = client.get("/api/gym/plan")
    assert r.status_code == 200
    data = r.json()
    assert data["week"]["Mon"] == "Push"
    assert data["week"]["Sun"] == "Rest"
    assert set(data["weekdays"]) == {"Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"}
    assert "Rest" in data["day_types"]
    assert data["today"]["date"] and data["today"]["day_type"]


def test_set_weekly_split_and_override(client, make_user, auth):
    auth(make_user())
    week = {"Mon": "Pull", "Tue": "Rest", "Wed": "Push", "Thu": "Legs",
            "Fri": "Push", "Sat": "Pull", "Sun": "Rest"}
    assert client.post("/api/gym/plan/week", json={"week": week}).status_code == 200
    assert client.get("/api/gym/plan").json()["week"] == week

    # Override a single date, then confirm the calendar reflects it, then clear it.
    day = "2099-01-07"  # a Wednesday -> weekly says Push
    assert client.post("/api/gym/plan/day", json={"date": day, "day_type": "Rest"}).status_code == 200
    cal = client.get("/api/gym/calendar?month=2099-01").json()
    cell = next(d for d in cal["days"] if d["date"] == day)
    assert cell["planned"] == "Rest"
    assert cell["weekday"] == "Wed"

    assert client.delete(f"/api/gym/plan/day/{day}").status_code == 204
    cal = client.get("/api/gym/calendar?month=2099-01").json()
    cell = next(d for d in cal["days"] if d["date"] == day)
    assert cell["planned"] == "Push"  # reverted to the weekly split


def test_bad_plan_day_type_rejected(client, make_user, auth):
    auth(make_user())
    r = client.post("/api/gym/plan/day", json={"date": "2099-01-07", "day_type": "Bogus"})
    assert r.status_code == 400


def test_open_day_is_editable_with_no_lock(client, make_user, auth):
    # gym_required_hours defaults to 1h when unset.
    auth(make_user())
    today = client.get("/api/gym/plan").json()["today"]["date"]

    # Open today's session (no start/finish gate).
    log = client.post("/api/gym/day", json={"date": today}).json()
    log_id = log["id"]
    assert log["day_type"] in {"Push", "Pull", "Legs", "Custom"}

    # Log exercises (autosave).
    ex = [{"exercise_name": "Bench Press", "muscle_group": "Chest",
           "sets_detail": [{"set": 1, "kg": 100, "reps": 5, "type": "Normal", "done": True}]}]
    r = client.post(f"/api/gym/{log_id}/exercises", json=ex)
    assert r.status_code == 200 and r.json()["exercise_count"] == 1

    # Set a compliant duration + mark done -> Completed. No lock: still editable afterwards.
    r = client.patch(f"/api/gym/{log_id}/session", json={"duration_minutes": 65, "done": True})
    assert r.status_code == 200
    assert r.json()["log"]["status"] == "Completed"

    # Editing again after "done" still works (nothing is locked).
    ex2 = ex + [{"exercise_name": "Squat", "muscle_group": "Quads",
                 "sets_detail": [{"set": 1, "kg": 140, "reps": 5, "type": "Normal", "done": True}]}]
    r = client.post(f"/api/gym/{log_id}/exercises", json=ex2)
    assert r.status_code == 200 and r.json()["exercise_count"] == 2

    # Re-opening the same date returns the SAME session (idempotent, not a duplicate).
    again = client.post("/api/gym/day", json={"date": today}).json()
    assert again["id"] == log_id
    assert len(client.get("/api/gym/my").json()) == 1


def test_user_can_delete_own_session(client, make_user, auth):
    me = make_user()
    auth(me)
    today = client.get("/api/gym/plan").json()["today"]["date"]
    log = client.post("/api/gym/day", json={"date": today}).json()
    assert client.delete(f"/api/gym/{log['id']}").status_code == 204
    assert client.get("/api/gym/my").json() == []


def test_cannot_delete_someone_elses_session(client, make_user, auth):
    owner = make_user()
    auth(owner)
    today = client.get("/api/gym/plan").json()["today"]["date"]
    log = client.post("/api/gym/day", json={"date": today}).json()

    other = make_user()          # a plain employee, not the owner and not Super Admin
    auth(other)
    assert client.delete(f"/api/gym/{log['id']}").status_code == 403


def test_super_admin_can_delete_any_session(client, make_user, auth):
    import app.constants as C
    owner = make_user()
    auth(owner)
    today = client.get("/api/gym/plan").json()["today"]["date"]
    log = client.post("/api/gym/day", json={"date": today}).json()

    auth(make_user(role=C.ROLE_SUPER_ADMIN))
    assert client.delete(f"/api/gym/{log['id']}").status_code == 204


def test_planned_rest_day_can_still_be_trained(client, make_user, auth):
    auth(make_user())
    # Force today to be a planned Rest day, then open it — it should fall back to Custom, not error.
    today = client.get("/api/gym/plan").json()["today"]["date"]
    client.post("/api/gym/plan/day", json={"date": today, "day_type": "Rest"})
    log = client.post("/api/gym/day", json={"date": today}).json()
    assert log["day_type"] == "Custom"

"""Saved workout templates: create (by hand and from a logged session), apply to a day, weekday
defaults, and the ownership boundary."""
from __future__ import annotations


def _routine_body(**over):
    body = {
        "name": "Push A",
        "day_type": "Push",
        "exercises": [
            {"exercise_name": "Bench Press", "muscle_group": "Chest",
             "sets": [{"kg": 60, "reps": 8}, {"kg": 60, "reps": 8}, {"kg": 65, "reps": 6}]},
            {"exercise_name": "Overhead Press", "muscle_group": "Shoulders",
             "sets": [{"kg": 35, "reps": 10}]},
        ],
    }
    body.update(over)
    return body


def test_create_and_list_routine(client, make_user, auth):
    auth(make_user())
    r = client.post("/api/gym/routines", json=_routine_body())
    assert r.status_code == 201
    routine = r.json()
    assert routine["name"] == "Push A"
    assert routine["exercise_count"] == 2
    assert routine["total_sets"] == 4

    listing = client.get("/api/gym/routines").json()
    assert [x["name"] for x in listing["routines"]] == ["Push A"]
    assert listing["by_weekday"] == {}


def test_blank_name_falls_back_to_split_letters(client, make_user, auth):
    auth(make_user())
    first = client.post("/api/gym/routines", json=_routine_body(name="")).json()
    second = client.post("/api/gym/routines", json=_routine_body(name="")).json()
    assert first["name"] == "Push A"
    assert second["name"] == "Push B"


def test_apply_routine_fills_the_day(client, make_user, auth):
    auth(make_user())
    routine = client.post("/api/gym/routines", json=_routine_body()).json()
    today = client.get("/api/gym/plan").json()["today"]["date"]
    log = client.post("/api/gym/day", json={"date": today, "day_type": "Legs"}).json()

    r = client.post(f"/api/gym/{log['id']}/apply-routine", json={"routine_id": routine["id"]})
    assert r.status_code == 200
    session = r.json()
    assert [e["exercise_name"] for e in session["exercises"]] == ["Bench Press", "Overhead Press"]
    # A replace adopts the routine's split — the day IS a push day now.
    assert session["day_type"] == "Push"

    bench = session["exercises"][0]
    assert [(s["kg"], s["reps"]) for s in bench["sets_detail"]] == [(60, 8), (60, 8), (65, 6)]
    # Sets arrive UNticked: these are sets to do, not sets done.
    assert all(s["done"] is False for s in bench["sets_detail"])
    assert bench["sets"] == 3 and bench["weight_value"] == 65  # top-set summary columns


def test_apply_replaces_or_appends(client, make_user, auth):
    auth(make_user())
    routine = client.post("/api/gym/routines", json=_routine_body()).json()
    today = client.get("/api/gym/plan").json()["today"]["date"]
    log = client.post("/api/gym/day", json={"date": today}).json()
    client.post(f"/api/gym/{log['id']}/exercises", json=[
        {"exercise_name": "Dips", "sets_detail": [{"set": 1, "kg": 0, "reps": 12}]},
    ])

    appended = client.post(f"/api/gym/{log['id']}/apply-routine",
                           json={"routine_id": routine["id"], "mode": "append"}).json()
    assert [e["exercise_name"] for e in appended["exercises"]] == ["Dips", "Bench Press", "Overhead Press"]

    replaced = client.post(f"/api/gym/{log['id']}/apply-routine",
                           json={"routine_id": routine["id"], "mode": "replace"}).json()
    assert [e["exercise_name"] for e in replaced["exercises"]] == ["Bench Press", "Overhead Press"]

    assert client.post(f"/api/gym/{log['id']}/apply-routine",
                       json={"routine_id": routine["id"], "mode": "bogus"}).status_code == 400


def test_save_a_logged_session_as_a_routine(client, make_user, auth):
    """The zero-typing path: log it once, then keep it."""
    auth(make_user())
    today = client.get("/api/gym/plan").json()["today"]["date"]
    log = client.post("/api/gym/day", json={"date": today, "day_type": "Legs"}).json()
    client.post(f"/api/gym/{log['id']}/exercises", json=[
        {"exercise_name": "Back Squat", "muscle_group": "Quads", "sets_detail": [
            {"set": 1, "kg": 60, "reps": 5, "type": "Warm-up", "done": True},
            {"set": 2, "kg": 100, "reps": 5, "type": "Normal", "done": True},
        ]},
    ])

    routine = client.post("/api/gym/routines", json={"from_log_id": log["id"]}).json()
    assert routine["day_type"] == "Legs"        # inherited from the session
    assert routine["name"] == "Legs A"
    assert routine["exercises"][0]["exercise_name"] == "Back Squat"
    assert [s["kg"] for s in routine["exercises"][0]["sets"]] == [60, 100]

    # …and the maintenance case: the squat crept up, so refresh the template from today's numbers.
    client.post(f"/api/gym/{log['id']}/exercises", json=[
        {"exercise_name": "Back Squat", "muscle_group": "Quads", "sets_detail": [
            {"set": 1, "kg": 60, "reps": 5, "type": "Warm-up", "done": True},
            {"set": 2, "kg": 105, "reps": 5, "type": "Normal", "done": True},
        ]},
    ])
    updated = client.patch(f"/api/gym/routines/{routine['id']}", json={"from_log_id": log["id"]}).json()
    assert [s["kg"] for s in updated["exercises"][0]["sets"]] == [60, 105]
    assert updated["name"] == "Legs A"          # a partial PATCH leaves everything else alone


def test_weekday_default_belongs_to_one_routine(client, make_user, auth):
    auth(make_user())
    a = client.post("/api/gym/routines", json=_routine_body(name="Push A", weekdays=["Mon", "Thu"])).json()
    assert a["weekdays"] == ["Mon", "Thu"]
    assert client.get("/api/gym/routines").json()["by_weekday"] == {"Mon": a["id"], "Thu": a["id"]}

    # Claiming Thu for another routine takes it OFF the first — a weekday has exactly one answer.
    b = client.post("/api/gym/routines", json=_routine_body(name="Push B", weekdays=["Thu"])).json()
    listing = client.get("/api/gym/routines").json()
    assert listing["by_weekday"] == {"Mon": a["id"], "Thu": b["id"]}
    assert next(x for x in listing["routines"] if x["id"] == a["id"])["weekdays"] == ["Mon"]


def test_bad_day_type_and_blank_rename_rejected(client, make_user, auth):
    auth(make_user())
    assert client.post("/api/gym/routines", json=_routine_body(day_type="Bogus")).status_code == 400
    rid = client.post("/api/gym/routines", json=_routine_body()).json()["id"]
    assert client.patch(f"/api/gym/routines/{rid}", json={"name": "   "}).status_code == 400


def test_routines_are_private_to_their_owner(client, make_user, auth):
    owner = make_user()
    auth(owner)
    routine = client.post("/api/gym/routines", json=_routine_body()).json()
    today = client.get("/api/gym/plan").json()["today"]["date"]
    log = client.post("/api/gym/day", json={"date": today}).json()

    other = make_user()
    auth(other)
    assert client.get("/api/gym/routines").json()["routines"] == []
    assert client.patch(f"/api/gym/routines/{routine['id']}", json={"name": "Mine now"}).status_code == 404
    assert client.delete(f"/api/gym/routines/{routine['id']}").status_code == 404
    # Someone else's session can't be filled from — or copied into — a routine either.
    own = client.post("/api/gym/day", json={"date": today}).json()
    assert client.post(f"/api/gym/{log['id']}/apply-routine", json={"routine_id": routine["id"]}).status_code == 404
    assert client.post(f"/api/gym/{own['id']}/apply-routine", json={"routine_id": routine["id"]}).status_code == 404
    assert client.post("/api/gym/routines", json={"from_log_id": log["id"]}).status_code == 404


def test_delete_routine_leaves_logged_sessions_alone(client, make_user, auth):
    auth(make_user())
    routine = client.post("/api/gym/routines", json=_routine_body()).json()
    today = client.get("/api/gym/plan").json()["today"]["date"]
    log = client.post("/api/gym/day", json={"date": today}).json()
    client.post(f"/api/gym/{log['id']}/apply-routine", json={"routine_id": routine["id"]})

    assert client.delete(f"/api/gym/routines/{routine['id']}").status_code == 204
    assert client.get(f"/api/gym/{log['id']}").json()["log"]["exercise_count"] == 2


def test_routines_path_is_not_swallowed_by_the_log_id_route(client, make_user, auth):
    """`GET /api/gym/{log_id}` is declared later in the module; if it ever moved above these,
    /api/gym/routines would 422 on int parsing instead of listing."""
    auth(make_user())
    assert client.get("/api/gym/routines").status_code == 200

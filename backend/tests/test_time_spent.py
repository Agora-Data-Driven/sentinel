"""Time in the Mastery Engine — /api/development/time, /time/detail and /team-time.

Pins the four things that would be silently wrong rather than loudly broken:

1. The windows are PH dates sent to the engine as DATES, so "today" means the same thing on both
   sides (the engine stamps minutes in Asia/Manila).
2. Programmes map onto dimensions the way the compass does: career -> professional, the pinned
   growth programmes -> their tab, NO programme -> coach.
3. Team time is a MANAGEMENT surface (403 below admin); somebody else's strip needs can_view.
4. 🔴 An unreachable engine is None, never 0 — but, unlike progress, NO minutes is a real 0.
"""
from __future__ import annotations

from datetime import date

import pytest

from app import constants as C
from app.config import settings
from app.services import engine_bridge, time_spent


@pytest.fixture(autouse=True)
def _clear_cache():
    time_spent._cache.clear()
    yield
    time_spent._cache.clear()


PROGRAMS = [
    {"id": "data-science", "name": "Data Science", "category": "career"},
    {"id": "philosophy", "name": "Philosophy", "category": "growth"},
    {"id": "spiritual", "name": "Spiritual", "category": "growth"},
    {"id": "poetry", "name": "Poetry", "category": "growth"},
]


def _person(email, by_program):
    return {
        "email": email, "found": True,
        "minutes": sum(by_program.values()),
        "byProgram": dict(by_program),
        "byView": {"quiz": sum(by_program.values())},
        "byDay": {"2026-09-01": sum(by_program.values())},
        "firstAt": "2026-09-01 09:00", "lastAt": "2026-09-01 10:30",
    }


@pytest.fixture
def engine(monkeypatch):
    class _Fake:
        people: dict = {}
        sessions: list = []
        fail = ""
        calls = 0
        last_params: dict = {}

    fake = _Fake()
    monkeypatch.setattr(settings, "platform_sso_secret", "test-shared-key")
    monkeypatch.setattr(settings, "skill_mastery_url", "https://engine.example")

    def _call(purpose, path, params=None, timeout=None):
        fake.calls += 1
        fake.last_params = dict(params or {})
        if fake.fail:
            return 0, {}, fake.fail
        base = {"from": params["from"], "to": params["to"], "tz": "Asia/Manila", "programs": PROGRAMS}
        if purpose == "time-spent":
            wanted = (params or {}).get("emails", "").split(",")
            return 200, {**base, "people": [fake.people[e] for e in wanted if e in fake.people]}, ""
        if purpose == "time-detail":
            person = fake.people.get(params["email"])
            if not person:
                return 200, {**base, "email": params["email"], "minutes": 0, "byProgram": {}, "sessions": []}, ""
            return 200, {**base, **person, "sessions": fake.sessions}, ""
        raise AssertionError(purpose)

    monkeypatch.setattr(engine_bridge, "call", _call)
    return fake


# --- windows -----------------------------------------------------------------


def test_windows_are_ph_dates():
    wed = date(2026, 9, 2)  # a Wednesday
    assert time_spent.window_range("today", wed) == (wed, wed)
    assert time_spent.window_range("week", wed) == (date(2026, 8, 31), wed)   # Monday .. today
    assert time_spent.window_range("30d", wed) == (date(2026, 8, 4), wed)
    assert time_spent.window_range("nonsense", wed) == (wed, wed)             # falls back to today


def test_window_dates_are_sent_to_the_engine(client, make_user, auth, engine):
    me = make_user(C.ROLE_EMPLOYEE, email="me@test.ph")
    auth(me)
    body = client.get("/api/development/time?win=30d").json()
    assert engine.last_params["from"] == body["from"] and engine.last_params["to"] == body["to"]
    assert body["window"] == "30d"


# --- buckets -----------------------------------------------------------------


def test_programmes_map_onto_dimensions():
    programs = {p["id"]: p for p in PROGRAMS}
    assert time_spent.bucket_of("data-science", programs) == C.DIM_PROFESSIONAL
    assert time_spent.bucket_of("philosophy", programs) == C.DIM_PHILOSOPHICAL
    assert time_spent.bucket_of("spiritual", programs) == C.DIM_SPIRITUAL
    assert time_spent.bucket_of("", programs) == time_spent.BUCKET_COACH
    assert time_spent.bucket_of("poetry", programs) == time_spent.BUCKET_OTHER
    # An unknown programme id is assumed career — the engine's own default category.
    assert time_spent.bucket_of("brand-new", programs) == C.DIM_PROFESSIONAL


def test_my_strip_splits_minutes_by_bucket(client, make_user, auth, engine):
    me = make_user(C.ROLE_EMPLOYEE, email="me@test.ph")
    engine.people["me@test.ph"] = _person("me@test.ph", {"data-science": 30, "philosophy": 10, "": 5})
    auth(me)
    body = client.get("/api/development/time").json()
    assert body["found"] is True and body["window"] == "today"
    assert body["buckets"] == {"professional": 30, "philosophical": 10, "spiritual": 0, "coach": 5, "other": 0}
    assert body["total"] == 45


def test_no_minutes_is_a_real_zero(client, make_user, auth, engine):
    me = make_user(C.ROLE_EMPLOYEE, email="me@test.ph")
    engine.people["me@test.ph"] = _person("me@test.ph", {})
    auth(me)
    body = client.get("/api/development/time").json()
    assert body["found"] is True and body["total"] == 0
    assert all(v == 0 for v in body["buckets"].values())


def test_engine_down_is_unknown_not_zero(client, make_user, auth, engine):
    me = make_user(C.ROLE_EMPLOYEE, email="me@test.ph")
    engine.fail = "couldn't reach the Mastery Engine"
    auth(me)
    body = client.get("/api/development/time").json()
    assert body["found"] is False and body["total"] is None
    assert all(v is None for v in body["buckets"].values())
    assert "reach" in body["engine_error"]


def test_detail_tags_each_session_with_its_bucket(client, make_user, auth, engine):
    me = make_user(C.ROLE_EMPLOYEE, email="me@test.ph")
    engine.people["me@test.ph"] = _person("me@test.ph", {"data-science": 19, "": 4})
    engine.sessions = [
        {"day": "2026-09-01", "start": "09:32", "end": "09:51", "minutes": 19, "program": "data-science",
         "view": "quiz", "track": "Mathematics", "course": "Linear Algebra", "lesson": "Eigen", "topics": ["Eigenvalues"]},
        {"day": "2026-09-01", "start": "10:00", "end": "10:04", "minutes": 4, "program": "",
         "view": "assistant", "track": "", "course": "", "lesson": "", "topics": []},
    ]
    auth(me)
    body = client.get("/api/development/time/detail").json()
    assert body["found"] is True
    assert [s["bucket"] for s in body["sessions"]] == [C.DIM_PROFESSIONAL, time_spent.BUCKET_COACH]
    assert body["sessions"][0]["program_name"] == "Data Science"
    assert body["sessions"][0]["topics"] == ["Eigenvalues"]


# --- RBAC --------------------------------------------------------------------


@pytest.mark.parametrize("role", [C.ROLE_INTERN, C.ROLE_EMPLOYEE, C.ROLE_TEAM_LEAD,
                                  C.ROLE_ACCOUNT_MANAGER])
def test_team_time_forbidden_below_admin(client, make_user, auth, role):
    auth(make_user(role))
    assert client.get("/api/development/team-time").status_code == 403


@pytest.mark.parametrize("role", [C.ROLE_ADMIN, C.ROLE_SUPER_ADMIN])
def test_team_time_allowed_for_admin(client, make_user, auth, role, engine):
    auth(make_user(role))
    assert client.get("/api/development/team-time").status_code == 200


def test_someone_elses_strip_needs_can_view(client, make_user, auth, engine):
    other = make_user(C.ROLE_EMPLOYEE, email="other@test.ph")
    engine.people["other@test.ph"] = _person("other@test.ph", {"data-science": 12})
    auth(make_user(C.ROLE_EMPLOYEE, email="peer@test.ph"))
    assert client.get(f"/api/development/time?user_id={other.id}").status_code == 403
    assert client.get(f"/api/development/time/detail?user_id={other.id}").status_code == 403
    auth(make_user(C.ROLE_ADMIN, email="boss@test.ph"))
    body = client.get(f"/api/development/time?user_id={other.id}").json()
    assert body["user"]["email"] == "other@test.ph" and body["total"] == 12
    assert client.get("/api/development/time?user_id=999999").status_code == 404


# --- the team table ------------------------------------------------------------


def test_team_rows_sort_most_time_first_and_unknowns_last(client, make_user, auth, engine):
    admin = make_user(C.ROLE_ADMIN, email="boss@test.ph")
    make_user(C.ROLE_EMPLOYEE, email="a@test.ph", name="Ada")
    make_user(C.ROLE_EMPLOYEE, email="b@test.ph", name="Bo")
    make_user(C.ROLE_EMPLOYEE, email="gone@test.ph", name="Gone", active=False)
    engine.people["a@test.ph"] = _person("a@test.ph", {"data-science": 5})
    engine.people["b@test.ph"] = _person("b@test.ph", {"spiritual": 40})
    engine.people["boss@test.ph"] = {"email": "boss@test.ph", "found": False, "minutes": None, "error": "read failed"}
    auth(admin)
    body = client.get("/api/development/team-time").json()
    emails = [r["user"]["email"] for r in body["rows"]]
    assert emails == ["b@test.ph", "a@test.ph", "boss@test.ph"]      # 40, 5, unknown
    assert "gone@test.ph" not in emails
    assert body["rows"][0]["buckets"]["spiritual"] == 40
    assert body["rows"][2]["total"] is None and body["rows"][2]["engine_error"] == "read failed"


def test_team_rollup_is_cached_and_refresh_bypasses_it(client, make_user, auth, engine):
    auth(make_user(C.ROLE_ADMIN))
    assert client.get("/api/development/team-time").json()["cached"] is False
    assert client.get("/api/development/team-time").json()["cached"] is True
    assert engine.calls == 1
    assert client.get("/api/development/team-time?refresh=1").json()["cached"] is False
    assert engine.calls == 2
    # A different window is a different cache key.
    client.get("/api/development/team-time?win=week")
    assert engine.calls == 3

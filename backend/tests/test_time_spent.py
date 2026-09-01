"""Time on growth — /api/development/time, /time/detail, /team-time, /time/entries, /time/engine-edit.

Pins the things that would be silently wrong rather than loudly broken:

1. The windows are PH dates sent to the engine as DATES, so "today" means the same thing on both
   sides (the engine stamps minutes in Asia/Manila).
2. Programmes map onto dimensions the way the compass does: career -> professional, the pinned
   growth programmes -> their tab, NO programme -> coach.
3. Team time is a MANAGEMENT surface (403 below admin); somebody else's strip needs can_view; and
   WRITING somebody else's time needs admin.
4. 🔴 An unreachable engine is None, never 0 — but, unlike progress, NO minutes is a real 0.
5. Manual entries merge with engine minutes at read time and are tagged `source: manual`.
6. An engine session can be deleted or TRIMMED, never extended — and never while it may still be
   running (the engine would re-stamp it).
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from app import constants as C
from app.config import settings
from app.services import engine_bridge, time_spent
from app.utils.time import today_ph


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
        posts: list = []
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
            # The real engine answers EVERY email asked — a person with no activity docs is a real
            # zero (found, 0 minutes), not a missing row. Explicit entries in `people` still win.
            zero = lambda e: {"email": e, "found": True, "minutes": 0, "byProgram": {}, "byView": {},
                              "byDay": {}, "firstAt": None, "lastAt": None}
            return 200, {**base, "people": [fake.people.get(e) or zero(e) for e in wanted if e]}, ""
        if purpose == "time-detail":
            person = fake.people.get(params["email"])
            if not person:
                return 200, {**base, "email": params["email"], "minutes": 0, "byProgram": {}, "sessions": []}, ""
            return 200, {**base, **person, "sessions": fake.sessions}, ""
        raise AssertionError(purpose)

    def _post(purpose, path, body, timeout=None):
        fake.posts.append((purpose, path, body))
        if fake.fail:
            return 0, {}, fake.fail
        assert purpose == "time-edit"
        removed = sum(_span(r) for r in body["remove"])
        return 200, {"ok": True, "day": body["day"], "removed": removed}, ""

    monkeypatch.setattr(engine_bridge, "call", _call)
    monkeypatch.setattr(engine_bridge, "post", _post)
    return fake


def _span(r):
    a = int(r["start"][:2]) * 60 + int(r["start"][3:])
    z = int(r["end"][:2]) * 60 + int(r["end"][3:])
    return z - a


YESTERDAY = (today_ph() - timedelta(days=1)).isoformat()


# --- windows -----------------------------------------------------------------


def test_windows_are_ph_dates():
    wed = date(2026, 9, 2)  # a Wednesday
    assert time_spent.window_range("today", wed) == (wed, wed)
    assert time_spent.window_range("week", wed) == (date(2026, 8, 31), wed)   # Monday .. today
    assert time_spent.window_range("30d", wed) == (date(2026, 8, 4), wed)
    assert time_spent.window_range("nonsense", wed) == (wed, wed)             # falls back to today


def test_window_dates_are_sent_to_the_engine(client, make_user, auth, engine):
    auth(make_user(C.ROLE_EMPLOYEE, email="me@test.ph"))
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
    assert body["buckets"] == {"professional": 30, "philosophical": 10, "spiritual": 0, "physical": 0,
                               "coach": 5, "other": 0}
    assert body["total"] == 45 and body["engine_minutes"] == 45 and body["manual_minutes"] == 0


def test_no_minutes_is_a_real_zero(client, make_user, auth, engine):
    me = make_user(C.ROLE_EMPLOYEE, email="me@test.ph")
    engine.people["me@test.ph"] = _person("me@test.ph", {})
    auth(me)
    body = client.get("/api/development/time").json()
    assert body["found"] is True and body["total"] == 0
    assert all(v == 0 for v in body["buckets"].values())


def test_engine_down_is_unknown_not_zero_but_manual_minutes_survive(client, make_user, auth, engine):
    me = make_user(C.ROLE_EMPLOYEE, email="me@test.ph")
    auth(me)
    client.post("/api/development/time/entries", json={
        "date": today_ph().isoformat(), "start": "07:00", "minutes": 40, "dimension": "physical"})
    engine.fail = "couldn't reach the Mastery Engine"
    body = client.get("/api/development/time").json()
    assert body["found"] is False and body["total"] is None
    assert all(v is None for v in body["buckets"].values())
    assert body["manual_minutes"] == 40 and body["manual_buckets"]["physical"] == 40
    assert "reach" in body["engine_error"]


def test_detail_tags_each_session_with_its_bucket(client, make_user, auth, engine):
    me = make_user(C.ROLE_EMPLOYEE, email="me@test.ph")
    engine.people["me@test.ph"] = _person("me@test.ph", {"data-science": 19, "": 4})
    engine.sessions = [
        {"day": YESTERDAY, "start": "09:32", "end": "09:51", "minutes": 19, "program": "data-science",
         "view": "quiz", "track": "Mathematics", "course": "Linear Algebra", "lesson": "Eigen", "topics": ["Eigenvalues"]},
        {"day": YESTERDAY, "start": "10:00", "end": "10:04", "minutes": 4, "program": "",
         "view": "assistant", "track": "", "course": "", "lesson": "", "topics": []},
    ]
    auth(me)
    body = client.get("/api/development/time/detail?win=30d").json()
    assert body["found"] is True
    assert [s["bucket"] for s in body["sessions"]] == [C.DIM_PROFESSIONAL, time_spent.BUCKET_COACH]
    assert all(s["source"] == "engine" and s["editable"] is True for s in body["sessions"])
    assert body["sessions"][0]["program_name"] == "Data Science"
    assert body["sessions"][0]["topics"] == ["Eigenvalues"]


# --- manual entries ------------------------------------------------------------


def test_manual_entry_adds_to_buckets_and_shows_as_a_tagged_session(client, make_user, auth, engine):
    me = make_user(C.ROLE_EMPLOYEE, email="me@test.ph")
    engine.people["me@test.ph"] = _person("me@test.ph", {"data-science": 30})
    auth(me)
    r = client.post("/api/development/time/entries", json={
        "date": today_ph().isoformat(), "start": "06:30", "minutes": 45, "dimension": "physical", "note": "gym"})
    assert r.status_code == 200, r.text
    entry = r.json()
    assert entry["source"] == "manual" and entry["end"] == "07:15" and entry["self_reported"] is True

    body = client.get("/api/development/time").json()
    assert body["buckets"]["physical"] == 45 and body["buckets"]["professional"] == 30
    assert body["total"] == 75 and body["manual_minutes"] == 45 and body["engine_minutes"] == 30

    detail = client.get("/api/development/time/detail").json()
    manual = [s for s in detail["sessions"] if s["source"] == "manual"]
    assert len(manual) == 1 and manual[0]["note"] == "gym" and manual[0]["bucket"] == "physical"
    assert manual[0]["editable"] is True and manual[0]["id"] == entry["id"]
    assert "physical" in detail["dimensions"] and "coach" in detail["dimensions"]


def test_manual_entry_is_validated(client, make_user, auth, engine):
    auth(make_user(C.ROLE_EMPLOYEE, email="me@test.ph"))
    today = today_ph().isoformat()
    ok = {"date": today, "start": "06:30", "minutes": 45, "dimension": "spiritual"}
    assert client.post("/api/development/time/entries", json={**ok, "dimension": "vibes"}).status_code == 400
    assert client.post("/api/development/time/entries", json={**ok, "start": "6:30"}).status_code == 400
    assert client.post("/api/development/time/entries", json={**ok, "minutes": 0}).status_code == 400
    assert client.post("/api/development/time/entries", json={**ok, "minutes": 100000}).status_code == 400
    tomorrow = (today_ph() + timedelta(days=1)).isoformat()
    assert client.post("/api/development/time/entries", json={**ok, "date": tomorrow}).status_code == 400
    assert client.post("/api/development/time/entries", json=ok).status_code == 200


def test_manual_entry_can_be_edited_and_deleted(client, make_user, auth, engine):
    auth(make_user(C.ROLE_EMPLOYEE, email="me@test.ph"))
    eid = client.post("/api/development/time/entries", json={
        "date": today_ph().isoformat(), "start": "20:00", "minutes": 30, "dimension": "philosophical"}).json()["id"]
    r = client.patch(f"/api/development/time/entries/{eid}", json={"minutes": 50, "note": "Meditations"})
    assert r.status_code == 200 and r.json()["minutes"] == 50 and r.json()["note"] == "Meditations"
    assert client.get("/api/development/time").json()["buckets"]["philosophical"] == 50
    assert client.delete(f"/api/development/time/entries/{eid}").status_code == 200
    assert client.get("/api/development/time").json()["buckets"]["philosophical"] == 0
    assert client.delete(f"/api/development/time/entries/{eid}").status_code == 404


def test_writing_somebody_elses_time_needs_admin(client, make_user, auth, engine):
    other = make_user(C.ROLE_EMPLOYEE, email="other@test.ph")
    body = {"date": today_ph().isoformat(), "start": "09:00", "minutes": 20, "dimension": "professional",
            "user_id": other.id}
    # A peer may not; a lead in the same department may READ (can_view) but still may not write.
    auth(make_user(C.ROLE_EMPLOYEE, email="peer@test.ph"))
    assert client.post("/api/development/time/entries", json=body).status_code == 403
    auth(make_user(C.ROLE_ADMIN, email="boss@test.ph"))
    r = client.post("/api/development/time/entries", json=body)
    assert r.status_code == 200 and r.json()["self_reported"] is False
    eid = r.json()["id"]
    # The owner may edit what the admin logged for them; a peer still may not.
    auth(other)
    assert client.patch(f"/api/development/time/entries/{eid}", json={"minutes": 25}).status_code == 200
    auth(make_user(C.ROLE_EMPLOYEE, email="peer2@test.ph"))
    assert client.delete(f"/api/development/time/entries/{eid}").status_code == 403


# --- editing the engine's minutes ----------------------------------------------


def test_deleting_an_engine_session_removes_exactly_its_range(client, make_user, auth, engine):
    auth(make_user(C.ROLE_EMPLOYEE, email="me@test.ph"))
    r = client.post("/api/development/time/engine-edit", json={"day": YESTERDAY, "start": "09:32", "end": "09:51"})
    assert r.status_code == 200, r.text
    assert r.json()["removed"] == 19
    purpose, path, body = engine.posts[-1]
    assert (purpose, path) == ("time-edit", "/api/internal/time-edit")
    assert body == {"email": "me@test.ph", "day": YESTERDAY, "remove": [{"start": "09:32", "end": "09:51"}]}


def test_trimming_removes_only_the_ends(client, make_user, auth, engine):
    auth(make_user(C.ROLE_EMPLOYEE, email="me@test.ph"))
    r = client.post("/api/development/time/engine-edit", json={
        "day": YESTERDAY, "start": "09:00", "end": "10:00", "new_start": "09:10", "new_end": "09:40"})
    assert r.status_code == 200, r.text
    assert engine.posts[-1][2]["remove"] == [{"start": "09:00", "end": "09:10"}, {"start": "09:40", "end": "10:00"}]
    assert r.json()["removed"] == 30
    # Nothing to trim is a no-op, not an engine call.
    n = len(engine.posts)
    r = client.post("/api/development/time/engine-edit", json={
        "day": YESTERDAY, "start": "09:00", "end": "10:00", "new_start": "09:00", "new_end": "10:00"})
    assert r.status_code == 200 and r.json()["removed"] == 0 and len(engine.posts) == n


def test_an_engine_session_can_never_be_extended_or_inverted(client, make_user, auth, engine):
    auth(make_user(C.ROLE_EMPLOYEE, email="me@test.ph"))
    base = {"day": YESTERDAY, "start": "09:00", "end": "10:00"}
    r = client.post("/api/development/time/engine-edit", json={**base, "new_end": "10:30"})
    assert r.status_code == 400 and "manual entry" in r.json()["detail"]
    r = client.post("/api/development/time/engine-edit", json={**base, "new_start": "08:30"})
    assert r.status_code == 400
    r = client.post("/api/development/time/engine-edit", json={**base, "new_start": "09:40", "new_end": "09:20"})
    assert r.status_code == 400
    assert engine.posts == []


def test_a_session_that_may_still_be_running_is_refused(client, make_user, auth, engine):
    auth(make_user(C.ROLE_EMPLOYEE, email="me@test.ph"))
    r = client.post("/api/development/time/engine-edit", json={
        "day": today_ph().isoformat(), "start": "00:00", "end": "23:59"})
    assert r.status_code == 409 and "still be running" in r.json()["detail"]
    assert engine.posts == []


def test_live_sessions_are_marked_not_editable_in_the_detail(client, make_user, auth, engine):
    me = make_user(C.ROLE_EMPLOYEE, email="me@test.ph")
    engine.people["me@test.ph"] = _person("me@test.ph", {"data-science": 5})
    engine.sessions = [{"day": today_ph().isoformat(), "start": "23:50", "end": "23:59", "minutes": 9,
                        "program": "data-science", "view": "quiz", "track": "", "course": "", "lesson": "", "topics": []}]
    auth(me)
    s = client.get("/api/development/time/detail").json()["sessions"][0]
    assert s["live"] is True and s["editable"] is False


def test_engine_edit_of_somebody_elses_time_needs_admin(client, make_user, auth, engine):
    other = make_user(C.ROLE_EMPLOYEE, email="other@test.ph")
    body = {"day": YESTERDAY, "start": "09:00", "end": "09:30", "user_id": other.id}
    auth(make_user(C.ROLE_TEAM_LEAD, email="lead@test.ph"))
    assert client.post("/api/development/time/engine-edit", json=body).status_code == 403
    auth(make_user(C.ROLE_ADMIN, email="boss@test.ph"))
    assert client.post("/api/development/time/engine-edit", json=body).status_code == 200
    assert engine.posts[-1][2]["email"] == "other@test.ph"


def test_engine_edit_reports_a_bridge_failure_instead_of_pretending(client, make_user, auth, engine):
    auth(make_user(C.ROLE_EMPLOYEE, email="me@test.ph"))
    engine.fail = "couldn't reach the Mastery Engine"
    r = client.post("/api/development/time/engine-edit", json={"day": YESTERDAY, "start": "09:00", "end": "09:30"})
    assert r.status_code == 502 and "reach" in r.json()["detail"]


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
    a = make_user(C.ROLE_EMPLOYEE, email="a@test.ph", name="Ada")
    make_user(C.ROLE_EMPLOYEE, email="b@test.ph", name="Bo")
    make_user(C.ROLE_EMPLOYEE, email="gone@test.ph", name="Gone", active=False)
    engine.people["a@test.ph"] = _person("a@test.ph", {"data-science": 5})
    engine.people["b@test.ph"] = _person("b@test.ph", {"spiritual": 40})
    engine.people["boss@test.ph"] = {"email": "boss@test.ph", "found": False, "minutes": None, "error": "read failed"}
    auth(admin)
    # Ada's hand-logged gym hour lifts her above Bo: manual minutes count toward the total.
    client.post("/api/development/time/entries", json={
        "date": today_ph().isoformat(), "start": "06:00", "minutes": 60, "dimension": "physical", "user_id": a.id})
    body = client.get("/api/development/team-time").json()
    emails = [r["user"]["email"] for r in body["rows"]]
    assert emails == ["a@test.ph", "b@test.ph", "boss@test.ph"]      # 65, 40, unknown
    assert "gone@test.ph" not in emails
    assert body["rows"][0]["buckets"]["physical"] == 60 and body["rows"][0]["manual_minutes"] == 60
    assert body["rows"][1]["buckets"]["spiritual"] == 40
    assert body["rows"][2]["total"] is None and body["rows"][2]["engine_error"] == "read failed"


def test_team_rollup_is_cached_and_writes_invalidate_it(client, make_user, auth, engine):
    admin = make_user(C.ROLE_ADMIN)
    auth(admin)
    assert client.get("/api/development/team-time").json()["cached"] is False
    assert client.get("/api/development/team-time").json()["cached"] is True
    assert engine.calls == 1
    assert client.get("/api/development/team-time?refresh=1").json()["cached"] is False
    assert engine.calls == 2
    # A different window is a different cache key.
    client.get("/api/development/team-time?win=week")
    assert engine.calls == 3
    # A logged entry changes the totals, so the next read must not come from the cache.
    client.post("/api/development/time/entries", json={
        "date": today_ph().isoformat(), "start": "06:00", "minutes": 10, "dimension": "physical"})
    assert client.get("/api/development/team-time?win=week").json()["cached"] is False

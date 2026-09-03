"""GET /api/development/team — the collective growth rollup behind the Overview's admin panel.

Pins the three things that would be silently wrong rather than loudly broken:

1. It is a MANAGEMENT surface (403 below admin) — it shows one person's numbers to another.
2. Velocity is measured, not guessed: (now − then) over the window, topic-weighted exactly the way
   a worker's own ring is, so the two can't disagree.
3. 🔴 An unreachable engine yields None, never 0.0. A table of zeroes reads as "nobody is doing
   anything", which is a confident lie — and it is the failure mode this repo has shipped twice.
"""
from __future__ import annotations

import pytest

from app import constants as C
from app.config import settings
from app.models import PhysicalGoal
from app.services import engine_bridge, team_growth


@pytest.fixture(autouse=True)
def _clear_cache():
    """The rollup cache is module-level and keyed by user ids, which restart at 1 for every test."""
    team_growth._cache.clear()
    yield
    team_growth._cache.clear()


def _person(email, *, career=(100, 5000, 4000), philosophy=(50, 1000, 1000)):
    """One engine payload. Each program is (topicsTotal, progressSum, progressSumThen)."""
    programs = []
    if career:
        total, now, then = career
        programs.append({"id": "data-science", "name": "Data Science", "category": "career",
                         "courseCount": 4, "topicsTotal": total, "topicsPracticed": total // 2,
                         "progressSum": now, "progressSumThen": then,
                         "pct": round(now / total) if total else 0})
    if philosophy:
        total, now, then = philosophy
        programs.append({"id": "philosophy", "name": "Philosophy", "category": "growth",
                         "courseCount": 2, "topicsTotal": total, "topicsPracticed": total // 2,
                         "progressSum": now, "progressSumThen": then,
                         "pct": round(now / total) if total else 0})
    return {
        "email": email, "found": True, "programs": programs,
        "activity": {"days": 30, "attempts": 120, "correct": 90, "activeDays": 12,
                     "streak": 3, "lastActive": "2026-08-02T04:00:00.000Z", "unmatched": 0},
    }


@pytest.fixture
def engine(monkeypatch):
    """Stand in for the Mastery Engine. `engine.people` maps email -> payload; `engine.fail`
    makes the bridge answer the way an outage does."""

    class _Fake:
        people: dict = {}
        fail = ""
        calls = 0

    fake = _Fake()
    monkeypatch.setattr(settings, "platform_sso_secret", "test-shared-key")
    monkeypatch.setattr(settings, "skill_mastery_url", "https://engine.example")

    def _call(purpose, path, params=None, timeout=None):
        fake.calls += 1
        assert purpose == "team-progress"
        if fake.fail:
            return 0, {}, fake.fail
        wanted = (params or {}).get("emails", "").split(",")
        return 200, {"days": (params or {}).get("days", 30),
                     "people": [fake.people[e] for e in wanted if e in fake.people]}, ""

    monkeypatch.setattr(engine_bridge, "call", _call)
    return fake


# --- RBAC --------------------------------------------------------------------


@pytest.mark.parametrize("role", [C.ROLE_INTERN, C.ROLE_EMPLOYEE, C.ROLE_TEAM_LEAD,
                                  C.ROLE_ACCOUNT_MANAGER])
def test_team_forbidden_below_admin(client, make_user, auth, role):
    auth(make_user(role))
    assert client.get("/api/development/team").status_code == 403


@pytest.mark.parametrize("role", [C.ROLE_ADMIN, C.ROLE_SUPER_ADMIN])
def test_team_allowed_for_admin(client, make_user, auth, role, engine):
    auth(make_user(role))
    assert client.get("/api/development/team").status_code == 200


def test_inactive_staff_are_not_listed(client, make_user, auth, engine):
    admin = make_user(C.ROLE_ADMIN)
    make_user(C.ROLE_EMPLOYEE, email="gone@test.ph", active=False)
    auth(admin)
    emails = {r["user"]["email"] for r in client.get("/api/development/team").json()["rows"]}
    assert "gone@test.ph" not in emails


def test_the_super_admin_is_never_a_row(client, make_user, auth, engine):
    """The super admin has no growth profile (AGENTS.md §5, 2026-09-03): the operator seat is left
    out of Team progress and the team time table, whoever is looking."""
    boss = make_user(C.ROLE_SUPER_ADMIN, email="boss@test.ph")
    make_user(C.ROLE_EMPLOYEE, email="ana@test.ph")
    auth(boss)
    emails = {r["user"]["email"] for r in client.get("/api/development/team").json()["rows"]}
    assert "ana@test.ph" in emails
    assert "boss@test.ph" not in emails


# --- the numbers -------------------------------------------------------------


def test_velocity_is_measured_and_dimensions_split_by_program(client, make_user, auth, engine):
    admin = make_user(C.ROLE_ADMIN, email="admin@test.ph")
    worker = make_user(C.ROLE_EMPLOYEE, email="ana@test.ph", name="Ana Reyes")
    engine.people = {"ana@test.ph": _person("ana@test.ph"), "admin@test.ph": _person("admin@test.ph")}

    auth(admin)
    body = client.get("/api/development/team?days=30").json()
    row = next(r for r in body["rows"] if r["user"]["id"] == worker.id)

    # Professional rolls up the CAREER programs only: 5000/100.
    assert row["dimensions"]["professional"]["actual"] == 50.0
    # Philosophical is its one pinned growth program: 1000/50.
    assert row["dimensions"]["philosophical"]["actual"] == 20.0
    # Spiritual has no enrolled program — unknown, not zero.
    assert row["dimensions"]["spiritual"]["actual"] is None
    # Overall is topic-weighted across everything: 6000/150.
    assert row["overall"] == 40.0

    # Velocity: overall was 5000/150 = 33.33 thirty days ago, so (40 − 33.33)/30 * 7.
    assert row["velocity"] == pytest.approx(1.56, abs=0.01)
    # And per dimension: professional moved 50 − 40 over the window, philosophy didn't move.
    assert row["dimensions"]["professional"]["velocity"] == pytest.approx(2.33, abs=0.01)
    assert row["dimensions"]["philosophical"]["velocity"] == 0.0
    assert row["streak"] == 3


def test_physical_scores_from_target_prs_but_reports_no_speed(client, db, make_user, auth, engine):
    admin = make_user(C.ROLE_ADMIN)
    worker = make_user(C.ROLE_EMPLOYEE, email="leo@test.ph")
    db.add_all([
        PhysicalGoal(user_id=worker.id, name="Bench", target_value=100, current_value=50),
        PhysicalGoal(user_id=worker.id, name="Squat", target_value=100, current_value=100),
        # Paused targets are excluded, exactly as the worker's own Physical ring excludes them.
        PhysicalGoal(user_id=worker.id, name="10k", target_value=100, current_value=0,
                     status="paused"),
    ])
    db.commit()

    auth(admin)
    row = next(r for r in client.get("/api/development/team").json()["rows"]
               if r["user"]["id"] == worker.id)
    phys = row["dimensions"]["physical"]
    assert phys["actual"] == 75.0        # mean of 50% and 100%
    assert phys["targets"] == 2
    # Nothing timestamps a PR, so there is no honest rate — and "no rate" must not become 0.0.
    assert phys["velocity"] is None
    assert phys["measurable"] is False


def test_unknown_is_none_not_zero_when_the_engine_is_down(client, db, make_user, auth, engine):
    admin = make_user(C.ROLE_ADMIN)
    worker = make_user(C.ROLE_EMPLOYEE, email="ana@test.ph")
    db.add(PhysicalGoal(user_id=worker.id, name="Bench", target_value=100, current_value=40))
    db.commit()
    engine.fail = "couldn't reach the Mastery Engine"

    auth(admin)
    body = client.get("/api/development/team").json()
    row = next(r for r in body["rows"] if r["user"]["id"] == worker.id)

    assert body["engine_error"]                       # the reason reaches the UI
    assert row["engine"]["found"] is False
    assert row["overall"] is None                     # 🔴 never 0.0
    assert row["velocity"] is None
    assert row["dimensions"]["professional"]["actual"] is None
    # Physical is read from OUR database, so an engine outage must not blank it too.
    assert row["dimensions"]["physical"]["actual"] == 40.0


def test_missing_person_is_unknown_rather_than_zero(client, make_user, auth, engine):
    """The engine answered, but had nothing for this person (never enrolled). Still not a zero."""
    admin = make_user(C.ROLE_ADMIN)
    worker = make_user(C.ROLE_EMPLOYEE, email="new@test.ph")
    engine.people = {}

    auth(admin)
    row = next(r for r in client.get("/api/development/team").json()["rows"]
               if r["user"]["id"] == worker.id)
    assert row["engine"]["found"] is False
    assert row["overall"] is None
    assert row["velocity"] is None


def test_velocity_is_none_when_the_window_has_no_baseline(client, make_user, auth, engine):
    """An engine too old to report `progressSumThen` gives a score but no rate — never a fake 0."""
    admin = make_user(C.ROLE_ADMIN, email="admin@test.ph")
    payload = _person("admin@test.ph")
    for program in payload["programs"]:
        program.pop("progressSumThen")
    engine.people = {"admin@test.ph": payload}

    auth(admin)
    row = next(r for r in client.get("/api/development/team").json()["rows"]
               if r["user"]["email"] == "admin@test.ph")
    assert row["overall"] == 40.0
    assert row["velocity"] is None


# --- caching -----------------------------------------------------------------


def test_rollup_is_cached_and_refresh_bypasses_it(client, make_user, auth, engine):
    admin = make_user(C.ROLE_ADMIN, email="admin@test.ph")
    engine.people = {"admin@test.ph": _person("admin@test.ph")}
    auth(admin)

    assert client.get("/api/development/team").json()["cached"] is False
    assert engine.calls == 1
    assert client.get("/api/development/team").json()["cached"] is True
    assert engine.calls == 1                       # served from cache, engine untouched
    assert client.get("/api/development/team?refresh=1").json()["cached"] is False
    assert engine.calls == 2
    # A different window is a different question, so it is a different cache entry.
    assert client.get("/api/development/team?days=7").json()["cached"] is False
    assert engine.calls == 3


def test_unconfigured_bridge_is_reported_not_silently_zeroed(client, make_user, auth, monkeypatch):
    monkeypatch.setattr(settings, "platform_sso_secret", "")
    admin = make_user(C.ROLE_ADMIN)
    auth(admin)
    body = client.get("/api/development/team").json()
    assert body["engine_error"]
    assert all(r["overall"] is None for r in body["rows"])

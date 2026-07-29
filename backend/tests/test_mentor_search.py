"""Retrieval over the Mentor Library — what lets the AI coach answer "what would Nick say about my
plan?" and mentor in Nick's voice (app/services/mentor_search.py + /api/internal/mentor-search).

The library is far too big to hand to a model (one creator ~1M words), so the coach retrieves. The
contract these lock down is mostly about HONESTY: the coach must be able to tell "that mentor isn't
in your library" from "that mentor never covered this", because blurring the two is what would make
it confabulate a real person's opinion.
"""
from __future__ import annotations

import hashlib
import hmac
import time

import pytest

from app.config import settings
from app.models import MentorTranscript
from app.services import mentor_search

SECRET = "shared-platform-sso-key-for-tests"


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    monkeypatch.setattr(settings, "platform_sso_secret", SECRET)


@pytest.fixture(autouse=True)
def _clear_index_cache():
    """The index is cached per user across requests; tests reuse user ids, so start clean."""
    mentor_search._CACHE.clear()
    yield
    mentor_search._CACHE.clear()


def _sig(purpose: str) -> dict:
    ts = str(int(time.time()))
    mac = hmac.new(SECRET.encode(), f"{purpose}:{ts}".encode(), hashlib.sha256).hexdigest()
    return {"X-Academy-Ts": ts, "X-Academy-Sig": mac}


def _add(db, user, mentor, title, text, url="https://youtu.be/x"):
    t = MentorTranscript(user_id=user.id, mentor_name=mentor, title=title,
                         source_url=url, transcript_text=text)
    db.add(t)
    db.commit()
    return t


# Two mentors with clearly separable subject matter, so a wrong retrieval is obvious.
COLD_EMAIL = ("the whole cold email system starts with a narrow offer. you pick one painful "
              "problem and one industry, then you write a short plain email that names the "
              "problem. volume without a narrow offer is how people burn their domain. " * 12)
PRICING = ("pricing is positioning. when you charge more you attract clients who take the work "
           "seriously, and retainers beat one off projects because the revenue compounds. " * 12)
FITNESS = ("progressive overload is the whole game. add a little weight each week and sleep "
           "eight hours or the training does nothing for you at all. " * 12)


def test_roster_groups_by_mentor_biggest_first(db, make_user):
    user = make_user()
    _add(db, user, "Nick Saraev", "Cold email", COLD_EMAIL)
    _add(db, user, "Nick Saraev", "Pricing", PRICING)
    _add(db, user, "Carson Reed", "Lifting", FITNESS)
    assert mentor_search.roster(db, user.id) == [
        {"name": "Nick Saraev", "transcripts": 2},
        {"name": "Carson Reed", "transcripts": 1},
    ]


@pytest.mark.parametrize("typed", ["nick", "Nick", "saraev", "nick saraev", "NICK SARAEV"])
def test_mentor_name_is_matched_loosely(db, make_user, typed):
    """People type "what would Nick say", not the full stored name. An exact-match-only filter
    would silently retrieve nothing and the coach would answer ungrounded."""
    user = make_user()
    _add(db, user, "Nick Saraev", "Cold email", COLD_EMAIL)
    assert mentor_search.resolve_mentor(db, user.id, typed) == "Nick Saraev"


def test_unknown_mentor_is_reported_as_unmatched(db, make_user):
    """"Not in your library" must be distinguishable from "they never covered it"."""
    user = make_user()
    _add(db, user, "Nick Saraev", "Cold email", COLD_EMAIL)
    out = mentor_search.search(db, user.id, "cold email", mentor="Marcus Aurelius")
    assert out["matched_mentor"] is False and out["excerpts"] == []


def test_known_mentor_with_nothing_on_the_topic(db, make_user):
    """The honest-silence path: the mentor IS theirs, but said nothing about this."""
    user = make_user()
    _add(db, user, "Nick Saraev", "Cold email", COLD_EMAIL)
    out = mentor_search.search(db, user.id, "kettlebell swings and hypertrophy", mentor="nick")
    assert out["matched_mentor"] is True and out["mentor"] == "Nick Saraev"
    assert out["excerpts"] == []


def test_search_retrieves_the_relevant_passage(db, make_user):
    user = make_user()
    _add(db, user, "Nick Saraev", "Cold email", COLD_EMAIL)
    _add(db, user, "Nick Saraev", "Pricing", PRICING)
    out = mentor_search.search(db, user.id, "should I raise my prices and use retainers?")
    assert out["excerpts"]
    assert out["excerpts"][0]["title"] == "Pricing"
    assert "retainer" in out["excerpts"][0]["text"]


def test_mentor_filter_scopes_the_results(db, make_user):
    user = make_user()
    _add(db, user, "Nick Saraev", "Pricing", PRICING)
    _add(db, user, "Carson Reed", "Lifting", FITNESS)
    out = mentor_search.search(db, user.id, "how should I think about progressive overload",
                               mentor="nick")
    # Nick has nothing on lifting — Carson's material must NOT leak in under Nick's name.
    assert all(e["mentor"] == "Nick Saraev" for e in out["excerpts"])


def test_chunks_are_indexed_by_mentor_and_title_not_just_body(db, make_user):
    """A transcript body almost never says its own mentor's name, so without indexing the title +
    mentor, "what does Nick say about offers" retrieves nothing from Nick."""
    user = make_user()
    _add(db, user, "Nick Saraev", "Cold email", COLD_EMAIL)
    out = mentor_search.search(db, user.id, "Saraev")
    assert out["excerpts"], "mentor name alone should retrieve their material"


def test_results_spread_across_transcripts(db, make_user):
    """One long transcript must not fill every slot — that would present a single video's take as
    if it were the mentor's whole position."""
    user = make_user()
    for i in range(4):
        _add(db, user, "Nick Saraev", f"Cold email {i}", COLD_EMAIL)
    out = mentor_search.search(db, user.id, "cold email offer", limit=8)
    titles = [e["title"] for e in out["excerpts"]]
    assert len(set(titles)) > 1
    assert all(titles.count(t) <= 2 for t in titles)


def test_index_refreshes_when_the_library_changes(db, make_user):
    """The index is cached for speed; a newly imported transcript must still be findable."""
    user = make_user()
    _add(db, user, "Nick Saraev", "Cold email", COLD_EMAIL)
    assert mentor_search.search(db, user.id, "retainers compound")["excerpts"] == []
    _add(db, user, "Nick Saraev", "Pricing", PRICING)
    assert mentor_search.search(db, user.id, "retainers compound")["excerpts"]


def test_empty_library_is_quietly_empty(db, make_user):
    user = make_user()
    out = mentor_search.search(db, user.id, "anything at all")
    assert out["excerpts"] == [] and mentor_search.roster(db, user.id) == []


# --- the internal endpoint the coach actually calls ---------------------------------------------
def test_endpoint_returns_excerpts_and_roster(client, db, make_user):
    user = make_user(email="worker@agora.ph", active=True)
    _add(db, user, "Nick Saraev", "Pricing", PRICING)
    r = client.get("/api/internal/mentor-search",
                   params={"email": "worker@agora.ph", "q": "should I move to retainers?"},
                   headers=_sig("mentor-search"))
    assert r.status_code == 200
    body = r.json()
    assert body["found"] is True
    assert body["mentors"] == [{"name": "Nick Saraev", "transcripts": 1}]
    assert body["excerpts"] and body["excerpts"][0]["mentor"] == "Nick Saraev"


def test_endpoint_requires_a_valid_signature(client, make_user):
    make_user(email="worker@agora.ph", active=True)
    assert client.get("/api/internal/mentor-search",
                      params={"email": "worker@agora.ph", "q": "x"}).status_code == 401
    bad = {"X-Academy-Ts": str(int(time.time())), "X-Academy-Sig": "0" * 64}
    assert client.get("/api/internal/mentor-search",
                      params={"email": "worker@agora.ph", "q": "x"},
                      headers=bad).status_code == 401


def test_endpoint_is_empty_for_an_inactive_or_unknown_user(client, db, make_user):
    user = make_user(email="gone@agora.ph", active=False)
    _add(db, user, "Nick Saraev", "Pricing", PRICING)
    for email in ("gone@agora.ph", "nobody@agora.ph"):
        body = client.get("/api/internal/mentor-search",
                          params={"email": email, "q": "retainers"},
                          headers=_sig("mentor-search")).json()
        assert body["found"] is False and body["excerpts"] == []


def test_holistic_digest_carries_the_mentor_roster(client, db, make_user):
    """The coach reads the roster from the profile to know who it may speak as. The title list is
    capped at 40, so with a big library it stops naming some mentors entirely."""
    user = make_user(email="worker@agora.ph", active=True)
    for i in range(45):
        _add(db, user, "Nick Saraev", f"Video {i}", COLD_EMAIL)
    _add(db, user, "Carson Reed", "Lifting", FITNESS)
    body = client.get("/api/internal/holistic-profile", params={"email": "worker@agora.ph"},
                      headers=_sig("holistic-profile")).json()
    mentors = body["profile"]["mentors"]
    assert mentors == [{"name": "Nick Saraev", "transcripts": 45},
                       {"name": "Carson Reed", "transcripts": 1}]
    # The reason the roster exists: the title list is capped, so with 46 transcripts it can no
    # longer be relied on to name every mentor — the roster is complete and counted regardless.
    assert len(body["profile"]["mentor_library"]) == 40
    assert sum(m["transcripts"] for m in mentors) == 46

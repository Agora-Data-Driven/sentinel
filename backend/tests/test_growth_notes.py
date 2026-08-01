"""Per-dimension growth entries + the small-to-big retrieval contract they exist to support.

The AI coach is handed a COMPLETE index of a worker's journal (every entry's title, uncapped) on
every turn, and fetches the `detail` bodies separately for the handful a conversation needs. These
tests pin the two halves of that contract, because breaking either one is silent and looks to the
worker exactly like the coach lying about what they've written:

  * the index must never be capped or filtered — the coach concludes "you have no note about X"
    from X's absence there, so a dropped entry becomes a confident false denial;
  * bodies must come back WHOLE — a truncated body reads to the model just like a complete one and
    gets summarised as if it were the whole thing.

Both failures are exactly how a 600-char cap on the old free-form `other_info` field made the coach
deny a list the worker could see on their own screen (2026-08-01), which is what this replaced.
"""
from __future__ import annotations

import hashlib
import hmac
import time

import pytest

from app.config import settings
from app.models import DevelopmentArea, GrowthItem
from app.services import development as dev_svc

SECRET = "shared-platform-sso-key-for-tests"


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    monkeypatch.setattr(settings, "platform_sso_secret", SECRET)


def _sig(purpose: str, ts: str | None = None) -> dict:
    ts = ts or str(int(time.time()))
    mac = hmac.new(SECRET.encode(), f"{purpose}:{ts}".encode(), hashlib.sha256).hexdigest()
    return {"X-Academy-Ts": ts, "X-Academy-Sig": mac}


def _add(db, user, title, *, dimension="professional", detail=None, status="open", kind="note"):
    g = GrowthItem(user_id=user.id, dimension=dimension, kind=kind,
                   title=title, detail=detail, status=status)
    db.add(g)
    db.commit()
    db.refresh(g)
    return g


# --- the index -------------------------------------------------------------------------------
def test_index_lists_every_entry_uncapped(db, make_user):
    """No cap. The old digest sent 6 titles; the coach must see all of them or it will deny the rest."""
    user = make_user()
    for i in range(40):
        _add(db, user, f"Entry {i}", detail="x" * 50)
    index = dev_svc.holistic_digest(db, user)["growth"]["index"]
    assert len(index) == 40
    assert {e["title"] for e in index} == {f"Entry {i}" for i in range(40)}


def test_index_includes_archived_and_resolved(db, make_user):
    """An entry they put away is still an entry. Hiding it makes "do I have anything on X?" wrong."""
    user = make_user()
    _add(db, user, "Open thing", status="open")
    _add(db, user, "Resolved thing", status="resolved")
    _add(db, user, "Archived thing", status="archived")
    index = dev_svc.holistic_digest(db, user)["growth"]["index"]
    assert {e["title"] for e in index} == {"Open thing", "Resolved thing", "Archived thing"}


def test_index_carries_size_but_never_the_body(db, make_user):
    """`chars` is what lets the caller budget BEFORE fetching, so no body ever needs truncating."""
    user = make_user()
    _add(db, user, "Sized", detail="y" * 1234)
    entry = dev_svc.holistic_digest(db, user)["growth"]["index"][0]
    assert entry["chars"] == 1234
    assert "detail" not in entry


def test_index_reports_the_entrys_dimension(db, make_user):
    user = make_user()
    _add(db, user, "Filed", dimension="physical")
    by_title = {e["title"]: e for e in dev_svc.holistic_digest(db, user)["growth"]["index"]}
    assert by_title["Filed"]["dimension"] == "physical"


def test_legacy_rows_without_a_dimension_read_as_spiritual():
    """Pre-split rows read as spiritual, where the whole journal used to render.

    Exercised against the serializer rather than the DB on purpose: a fresh create_all schema has
    the column NOT NULL, so it cannot hold the value this guards against. The NULL only exists on an
    UPGRADED database, where the column arrives via `ALTER TABLE ... ADD COLUMN` (nullable) — see
    main._ensure_columns, which also backfills it.
    """
    from app.serializers import growth_item_dict
    assert growth_item_dict(GrowthItem(id=1, dimension=None, kind="note", title="Legacy",
                                       detail=None, status="open"))["dimension"] == "spiritual"


def test_other_info_is_no_longer_truncated(db, make_user):
    """The original bug: 600 chars, cut mid-word, and the coach denied what came after."""
    user = make_user()
    long_text = "A" * 5000
    db.add(DevelopmentArea(user_id=user.id, dimension="professional", other_info=long_text))
    db.commit()
    areas = dev_svc.holistic_digest(db, user)["areas"]
    assert areas["professional"]["other_info"] == long_text


# --- the bodies ------------------------------------------------------------------------------
def test_growth_details_returns_whole_bodies(db, make_user):
    user = make_user()
    body = "Z" * 9000
    g = _add(db, user, "Big one", detail=body)
    out = dev_svc.growth_details(db, user.id, [g.id])
    assert len(out) == 1 and out[0]["detail"] == body


def test_growth_details_preserves_requested_order(db, make_user):
    """The caller asks most-relevant-first, and that ordering carries into the prompt."""
    user = make_user()
    a = _add(db, user, "A", detail="a")
    b = _add(db, user, "B", detail="b")
    c = _add(db, user, "C", detail="c")
    out = dev_svc.growth_details(db, user.id, [c.id, a.id, b.id])
    assert [e["title"] for e in out] == ["C", "A", "B"]


def test_growth_details_is_scoped_to_the_owner(db, make_user):
    """Someone else's id must not be readable by guessing integers."""
    mine = make_user(email="mine@test.ph")
    theirs = make_user(email="theirs@test.ph")
    ours = _add(db, mine, "Mine", detail="secret-mine")
    hers = _add(db, theirs, "Theirs", detail="secret-theirs")
    out = dev_svc.growth_details(db, mine.id, [ours.id, hers.id])
    assert [e["title"] for e in out] == ["Mine"]


def test_growth_details_caps_the_request_not_the_text(db, make_user):
    user = make_user()
    ids = [_add(db, user, f"E{i}", detail="d").id for i in range(dev_svc.MAX_GROWTH_DETAIL_IDS + 10)]
    out = dev_svc.growth_details(db, user.id, ids)
    assert len(out) == dev_svc.MAX_GROWTH_DETAIL_IDS


def test_growth_details_ignores_unknown_ids(db, make_user):
    user = make_user()
    g = _add(db, user, "Real", detail="d")
    assert [e["title"] for e in dev_svc.growth_details(db, user.id, [g.id, 999999])] == ["Real"]
    assert dev_svc.growth_details(db, user.id, []) == []


# --- the internal endpoint -------------------------------------------------------------------
def test_internal_growth_detail_round_trip(client, db, make_user):
    user = make_user(email="worker@agora.ph", active=True)
    g = _add(db, user, "Pareto problem set", detail="P" * 2000)
    r = client.get("/api/internal/growth-detail",
                   params={"email": "worker@agora.ph", "ids": str(g.id)},
                   headers=_sig("growth-detail"))
    assert r.status_code == 200
    body = r.json()
    assert body["found"] is True
    assert body["entries"][0]["title"] == "Pareto problem set"
    assert body["entries"][0]["detail"] == "P" * 2000


def test_internal_growth_detail_skips_malformed_ids(client, db, make_user):
    """One bad id is the caller's bug — it must not cost the worker their whole turn."""
    user = make_user(email="worker@agora.ph", active=True)
    g = _add(db, user, "Fine", detail="d")
    r = client.get("/api/internal/growth-detail",
                   params={"email": "worker@agora.ph", "ids": f"abc,{g.id},,x"},
                   headers=_sig("growth-detail"))
    assert r.status_code == 200
    assert [e["title"] for e in r.json()["entries"]] == ["Fine"]


def test_internal_growth_detail_wrong_purpose_rejected(client, db, make_user):
    user = make_user(email="worker@agora.ph", active=True)
    g = _add(db, user, "Fine", detail="d")
    r = client.get("/api/internal/growth-detail",
                   params={"email": "worker@agora.ph", "ids": str(g.id)},
                   headers=_sig("holistic-profile"))
    assert r.status_code == 401


def test_internal_growth_detail_unknown_user(client):
    r = client.get("/api/internal/growth-detail",
                   params={"email": "nobody@agora.ph", "ids": "1"},
                   headers=_sig("growth-detail"))
    assert r.status_code == 200
    assert r.json() == {"found": False, "entries": []}


# --- the write path --------------------------------------------------------------------------
def test_create_entry_files_it_under_its_dimension(client, db, make_user, auth):
    user = auth(make_user())
    r = client.post("/api/development/growth",
                    json={"dimension": "philosophical", "kind": "reflection",
                          "title": "On practice", "detail": "long text"})
    assert r.status_code == 200
    assert r.json()["dimension"] == "philosophical"


def test_create_entry_rejects_an_unknown_dimension(client, make_user, auth):
    """An unknown dimension renders in no tab at all — invisible, and indistinguishable from lost."""
    auth(make_user())
    r = client.post("/api/development/growth",
                    json={"dimension": "spirtiual", "kind": "note", "title": "Typo"})
    assert r.status_code == 400


def test_entry_can_be_moved_between_dimensions(client, db, make_user, auth):
    user = auth(make_user())
    g = _add(db, user, "Wrong tab", dimension="spiritual")
    r = client.patch(f"/api/development/growth/{g.id}", json={"dimension": "physical"})
    assert r.status_code == 200 and r.json()["dimension"] == "physical"


def test_entry_detail_survives_a_round_trip_uncut(client, db, make_user, auth):
    user = auth(make_user())
    long_detail = "L" * 20000
    created = client.post("/api/development/growth",
                          json={"dimension": "professional", "kind": "note",
                                "title": "Roadmap", "detail": long_detail}).json()
    assert created["detail"] == long_detail
    assert dev_svc.growth_details(db, user.id, [created["id"]])[0]["detail"] == long_detail

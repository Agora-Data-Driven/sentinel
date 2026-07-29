"""Bulk import: pull a whole Atrium Watcher creator into the Mentor Library in one call.

Importing a 200-video creator one click at a time was the original complaint. These cover the
contract that makes the bulk path safe to press twice: it is IDEMPOTENT (re-running only adds
what's new, so it doubles as "catch me up"), it never stores an empty transcript, and an
unreachable Atrium degrades to a 404 rather than a 500.
"""
from __future__ import annotations

from app.models import MentorTranscript
from app.services import atrium_watcher


def _items(n, start=1):
    return [{"id": "vid%d" % i, "title": "Lesson %d" % i, "url": "https://youtu.be/v%d" % i,
             "transcript": "body of lesson %d" % i, "words": 4}
            for i in range(start, start + n)]


def _rows(db, user):
    return db.query(MentorTranscript).filter(MentorTranscript.user_id == user.id).all()


def test_imports_every_transcript_in_one_call(client, db, make_user, auth, monkeypatch):
    user = auth(make_user())
    monkeypatch.setattr(atrium_watcher, "list_transcripts", lambda cid: _items(5))
    r = client.post("/api/development/atrium/import-all",
                    json={"channel_id": "ian-fernandez:wch_1", "mentor_name": "Nick Saraev"})
    assert r.status_code == 200
    assert r.json() == {"imported": 5, "skipped": 0, "available": 5}
    rows = _rows(db, user)
    assert len(rows) == 5
    assert {t.mentor_name for t in rows} == {"Nick Saraev"}
    assert all(t.transcript_text for t in rows)


def test_rerunning_is_idempotent_and_only_adds_the_new_ones(client, db, make_user, auth, monkeypatch):
    """Pressing it twice must not duplicate; a creator that gained videos imports only those."""
    user = auth(make_user())
    monkeypatch.setattr(atrium_watcher, "list_transcripts", lambda cid: _items(3))
    client.post("/api/development/atrium/import-all",
                json={"channel_id": "c:1", "mentor_name": "Nick Saraev"})

    r = client.post("/api/development/atrium/import-all",
                    json={"channel_id": "c:1", "mentor_name": "Nick Saraev"})
    assert r.json() == {"imported": 0, "skipped": 3, "available": 3}
    assert len(_rows(db, user)) == 3

    # Atrium fetched two more since last time -> only those land.
    monkeypatch.setattr(atrium_watcher, "list_transcripts", lambda cid: _items(5))
    r = client.post("/api/development/atrium/import-all",
                    json={"channel_id": "c:1", "mentor_name": "Nick Saraev"})
    assert r.json() == {"imported": 2, "skipped": 3, "available": 5}
    assert len(_rows(db, user)) == 5


def test_duplicate_urls_within_one_payload_are_collapsed(client, db, make_user, auth, monkeypatch):
    """A channel listing the same video twice must not double-add inside a single run."""
    user = auth(make_user())
    dupes = _items(2) + _items(1)
    monkeypatch.setattr(atrium_watcher, "list_transcripts", lambda cid: dupes)
    r = client.post("/api/development/atrium/import-all",
                    json={"channel_id": "c:1", "mentor_name": "Carson Reed"})
    assert r.json()["imported"] == 2
    assert len(_rows(db, user)) == 2


def test_items_without_text_are_never_stored(client, db, make_user, auth, monkeypatch):
    """transcript_text is NOT NULL and an empty row is useless to the coach — skip, don't store."""
    user = auth(make_user())
    mixed = _items(2) + [{"id": "v9", "title": "Pending", "url": "https://youtu.be/v9",
                          "transcript": "", "words": 0}]
    monkeypatch.setattr(atrium_watcher, "list_transcripts", lambda cid: mixed)
    r = client.post("/api/development/atrium/import-all",
                    json={"channel_id": "c:1", "mentor_name": "Ben Heath"})
    assert r.json()["imported"] == 2
    assert len(_rows(db, user)) == 2
    assert all(t.transcript_text for t in _rows(db, user))


def test_unreachable_atrium_is_a_404_not_a_500(client, make_user, auth, monkeypatch):
    """The bridge degrades to [] on any failure; the route must turn that into a real message."""
    auth(make_user())
    monkeypatch.setattr(atrium_watcher, "list_transcripts", lambda cid: [])
    r = client.post("/api/development/atrium/import-all",
                    json={"channel_id": "c:1", "mentor_name": "Nick Saraev"})
    assert r.status_code == 404
    assert "Fetch missing" in r.json()["detail"]


def test_import_is_per_user(client, db, make_user, auth, monkeypatch):
    """One worker's library is their own — another user's rows must not count as already-imported."""
    monkeypatch.setattr(atrium_watcher, "list_transcripts", lambda cid: _items(3))
    first = auth(make_user(email="a@test.ph"))
    client.post("/api/development/atrium/import-all",
                json={"channel_id": "c:1", "mentor_name": "Nick Saraev"})
    second = auth(make_user(email="b@test.ph"))
    r = client.post("/api/development/atrium/import-all",
                    json={"channel_id": "c:1", "mentor_name": "Nick Saraev"})
    assert r.json()["imported"] == 3
    assert len(_rows(db, first)) == 3 and len(_rows(db, second)) == 3


def test_anonymous_cannot_bulk_import(client, monkeypatch):
    monkeypatch.setattr(atrium_watcher, "list_transcripts", lambda cid: _items(3))
    client.cookies.clear()
    r = client.post("/api/development/atrium/import-all",
                    json={"channel_id": "c:1", "mentor_name": "Nick Saraev"})
    assert r.status_code in (401, 403)

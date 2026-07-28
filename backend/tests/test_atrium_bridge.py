"""The Atrium task bridge: Atrium owns client-facing tasks, this board is the team's window.

These pin the contract that took a full day to get right (2026-07-27):
  * Atrium and Sentinel agree on the SAME status set, so a card can cross unambiguously.
  * An Atrium card is identifiable and routes its edits back to Atrium, never to Postgres.
  * The bridge is fail-SOFT -- unconfigured or unreachable Atrium must never blank the board or
    500 the endpoint, because the team's internal rows still have to render.
"""

from __future__ import annotations

from app.constants import TASK_STATUSES
from app.services import atrium_bridge, atrium_tasks


def test_status_map_covers_every_sentinel_status():
    """Every Sentinel status must map to an Atrium stage, or a drag would silently 400."""
    for status in TASK_STATUSES:
        assert status in atrium_tasks.STAGE_BY_STATUS, f"no Atrium stage for {status!r}"


def test_split_id_recognises_atrium_cards_only():
    assert atrium_tasks.split_id("atrium:riverdance-rv:tk_123") == ("riverdance-rv", "tk_123")
    # A plain Sentinel row id must NOT be mistaken for an Atrium card.
    assert atrium_tasks.split_id("42") == ("", "")
    assert atrium_tasks.split_id("") == ("", "")
    assert atrium_tasks.split_id(None) == ("", "")


def test_board_card_shape_and_client_resolution():
    payload = {
        "atrium_id": "riverdance-rv:tk_9", "task_id": "tk_9", "client_key": "riverdance-rv",
        "client_name": "Riverdance RV", "title": "audit ads", "status": "To Do",
        "priority": "Medium", "client_facing": True, "checklist_total": 3, "checklist_done": 1,
    }
    card = atrium_tasks.as_board_card(payload)
    assert card["id"] == "atrium:riverdance-rv:tk_9"
    assert card["source"] == "atrium"
    assert card["title"] == "audit ads"
    assert card["status"] == "To Do"
    assert card["checklist_total"] == 3 and card["checklist_done"] == 1
    # client_facing is what "visible in Atrium" means from this side.
    assert card["atrium_visible"] is True
    # With no matching Sentinel client row, the card still names the client from Atrium.
    assert card["client_id"] is None and card["client_name"] == "Riverdance RV"

    class _C:
        id, name = 7, "Riverdance RV Resort"

    linked = atrium_tasks.as_board_card(payload, _C())
    # Resolved through Client.atrium_client_id, so the board's client filter works on it.
    assert linked["client_id"] == 7 and linked["client_name"] == "Riverdance RV Resort"


def test_bridge_is_off_and_silent_without_config(monkeypatch):
    """No secret / no URL => disabled, and every call degrades instead of raising."""
    monkeypatch.setattr(atrium_bridge.settings, "platform_sso_secret", "", raising=False)
    monkeypatch.setattr(atrium_bridge.settings, "atrium_api_url", "", raising=False)
    monkeypatch.setattr(atrium_bridge.settings, "portal_login_url", "", raising=False)
    assert atrium_tasks.enabled() is False
    assert atrium_tasks.fetch_tasks() == []
    ok, err = atrium_tasks.move_task("c", "tk_1", "todo")
    assert ok is False and err


class _Client:
    def __init__(self, cid, name, atrium_client_id=None):
        self.id, self.name, self.atrium_client_id = cid, name, atrium_client_id


def test_resolve_client_prefers_the_explicit_link():
    """atrium_client_id always wins, even when another client's NAME looks like a better match."""
    rows = [_Client(1, "Riverdance RV"), _Client(2, "Something Else", "riverdance-rv")]
    assert atrium_tasks.resolve_client(rows, "riverdance-rv", "Riverdance RV").id == 2


def test_resolve_client_matches_on_normalised_name():
    rows = [_Client(1, "Honey Tribe"), _Client(3, "Riverdance")]
    # 'Honey Tribe' == 'honey-tribe' once normalised.
    assert atrium_tasks.resolve_client(rows, "honey-tribe", "Honey Tribe").id == 1
    # Sentinel's 'Riverdance' should still pick up Atrium's 'Riverdance RV' (unambiguous prefix).
    assert atrium_tasks.resolve_client(rows, "riverdance-rv", "Riverdance RV").id == 3


def test_resolve_client_refuses_to_guess_when_ambiguous():
    """Mislinking one client's work to another is worse than leaving it unlinked."""
    rows = [_Client(1, "Riverdance North"), _Client(2, "Riverdance South")]
    assert atrium_tasks.resolve_client(rows, "riverdance-rv", "Riverdance RV") is None
    # Duplicated names are equally unsafe.
    assert atrium_tasks.resolve_client([_Client(1, "Acme"), _Client(2, "Acme")], "acme", "Acme") is None
    # Nothing remotely similar, and an empty roster.
    assert atrium_tasks.resolve_client([_Client(1, "Totally Other")], "riverdance-rv", "Riverdance RV") is None
    assert atrium_tasks.resolve_client([], "riverdance-rv", "Riverdance RV") is None
    # A very short name must not prefix-match half the roster.
    assert atrium_tasks.resolve_client([_Client(1, "RV")], "riverdance-rv", "Riverdance RV") is None


def test_writes_get_a_longer_timeout_than_reads():
    """A move is a read-modify-write of a whole workspace JSON in GCS. The original 6s gave up
    while the write LANDED, so the card moved and the user was told it failed."""
    assert atrium_tasks._WRITE_TIMEOUT >= 30
    assert atrium_tasks._READ_TIMEOUT < atrium_tasks._WRITE_TIMEOUT


def test_unconfirmed_write_is_not_reported_as_a_failure(monkeypatch):
    """No answer != it didn't happen. Claiming failure on a write that landed invites a
    double-move, so the wording must send the user to refresh instead."""
    monkeypatch.setattr(atrium_bridge.settings, "platform_sso_secret", "s3cret", raising=False)
    monkeypatch.setattr(atrium_bridge.settings, "atrium_api_url", "https://portal.example",
                        raising=False)

    def _timeout(*a, **k):
        raise TimeoutError("slow")

    monkeypatch.setattr(atrium_bridge.urllib.request, "urlopen", _timeout)
    ok, err = atrium_tasks.move_task("riverdance-rv", "tk_1", "todo")
    assert ok is False
    low = err.lower()
    assert "refresh" in low
    assert "couldn't reach" not in low and "failed" not in low


def test_bridge_imports_without_third_party_deps():
    """STDLIB ONLY. `import requests` here crashed every container on boot -- it is not in the
    image, and an optional bridge must never be able to take the app down at import time. Checks
    every module in the bridge: the shared transport (atrium_bridge) and both its callers."""
    import pathlib

    from app.services import atrium_watcher

    for mod in (atrium_bridge, atrium_tasks, atrium_watcher):
        src = pathlib.Path(mod.__file__).read_text(encoding="utf-8")
        for line in src.splitlines():
            stripped = line.strip()
            assert not stripped.startswith("import requests"), f"requests is NOT in requirements.txt ({mod.__name__})"
            assert not stripped.startswith("from requests"), f"requests is NOT in requirements.txt ({mod.__name__})"


def test_fetch_degrades_when_atrium_is_unreachable(monkeypatch):
    """An Atrium outage returns [] -- the board still renders Sentinel's own rows."""
    monkeypatch.setattr(atrium_bridge.settings, "platform_sso_secret", "s3cret", raising=False)
    monkeypatch.setattr(atrium_bridge.settings, "atrium_api_url", "https://portal.example",
                        raising=False)

    def _boom(*a, **k):
        raise atrium_bridge.urllib.error.URLError("down")

    monkeypatch.setattr(atrium_bridge.urllib.request, "urlopen", _boom)
    assert atrium_tasks.fetch_tasks() == []
    ok, err = atrium_tasks.move_task("c", "tk_1", "todo")
    assert ok is False and err


def test_signed_request_carries_the_platform_hmac_headers(monkeypatch):
    """The bridge uses the SAME scheme as the other internal endpoints -- no new secret."""
    import hashlib
    import hmac as _hmac

    monkeypatch.setattr(atrium_bridge.settings, "platform_sso_secret", "s3cret", raising=False)
    monkeypatch.setattr(atrium_bridge.settings, "atrium_api_url", "https://portal.example",
                        raising=False)
    seen = {}

    class _Resp:
        status = 200

        def read(self):
            return b'{"ok": true, "tasks": []}'

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def _urlopen(req, timeout=None):
        seen["url"] = req.full_url
        seen["headers"] = dict(req.headers)
        return _Resp()

    monkeypatch.setattr(atrium_bridge.urllib.request, "urlopen", _urlopen)
    atrium_tasks.fetch_tasks()
    assert seen["url"].endswith("/api/internal/tasks")
    # urllib title-cases header names.
    ts = seen["headers"]["X-academy-ts"]
    expected = _hmac.new(b"s3cret", f"tasks:{ts}".encode(), hashlib.sha256).hexdigest()
    assert seen["headers"]["X-academy-sig"] == expected

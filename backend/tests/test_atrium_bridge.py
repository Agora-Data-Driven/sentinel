"""The Atrium task bridge: Atrium owns client-facing tasks, this board is the team's window.

These pin the contract that took a full day to get right (2026-07-27):
  * Atrium and Sentinel agree on the SAME status set, so a card can cross unambiguously.
  * An Atrium card is identifiable and routes its edits back to Atrium, never to Postgres.
  * The bridge is fail-SOFT -- unconfigured or unreachable Atrium must never blank the board or
    500 the endpoint, because the team's internal rows still have to render.
"""

from __future__ import annotations

from app.constants import TASK_STATUSES
from app.services import atrium_tasks


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
    monkeypatch.setattr(atrium_tasks.settings, "platform_sso_secret", "", raising=False)
    monkeypatch.setattr(atrium_tasks.settings, "atrium_api_url", "", raising=False)
    monkeypatch.setattr(atrium_tasks.settings, "portal_login_url", "", raising=False)
    assert atrium_tasks.enabled() is False
    assert atrium_tasks.fetch_tasks() == []
    ok, err = atrium_tasks.move_task("c", "tk_1", "todo")
    assert ok is False and err


def test_fetch_degrades_when_atrium_is_unreachable(monkeypatch):
    """An Atrium outage returns [] -- the board still renders Sentinel's own rows."""
    monkeypatch.setattr(atrium_tasks.settings, "platform_sso_secret", "s3cret", raising=False)
    monkeypatch.setattr(atrium_tasks.settings, "atrium_api_url", "https://portal.example",
                        raising=False)

    def _boom(*a, **k):
        raise atrium_tasks.requests.RequestException("down")

    monkeypatch.setattr(atrium_tasks.requests, "get", _boom)
    assert atrium_tasks.fetch_tasks() == []


def test_signed_request_carries_the_platform_hmac_headers(monkeypatch):
    """The bridge uses the SAME scheme as the other internal endpoints -- no new secret."""
    import hashlib
    import hmac as _hmac

    monkeypatch.setattr(atrium_tasks.settings, "platform_sso_secret", "s3cret", raising=False)
    monkeypatch.setattr(atrium_tasks.settings, "atrium_api_url", "https://portal.example",
                        raising=False)
    seen = {}

    class _Resp:
        status_code = 200

        @staticmethod
        def json():
            return {"ok": True, "tasks": []}

    def _get(url, params=None, headers=None, timeout=None):
        seen.update({"url": url, "headers": headers})
        return _Resp()

    monkeypatch.setattr(atrium_tasks.requests, "get", _get)
    atrium_tasks.fetch_tasks()
    assert seen["url"].endswith("/api/internal/tasks")
    ts = seen["headers"]["X-Academy-Ts"]
    expected = _hmac.new(b"s3cret", f"tasks:{ts}".encode(), hashlib.sha256).hexdigest()
    assert seen["headers"]["X-Academy-Sig"] == expected

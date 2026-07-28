"""The Atrium Watcher bridge: the Growth hub's Mentor Library imports a transcript Atrium's Watcher
tab already archived, instead of hand-pasting one. Same fail-soft contract as the task bridge
(test_atrium_bridge.py) -- an unconfigured or unreachable Atrium must degrade to empty/None, never
raise, so the Growth page still renders and manual paste still works.
"""

from __future__ import annotations

from app.services import atrium_bridge, atrium_watcher


def _configure(monkeypatch, client_key="agora"):
    monkeypatch.setattr(atrium_bridge.settings, "platform_sso_secret", "s3cret", raising=False)
    monkeypatch.setattr(atrium_bridge.settings, "atrium_api_url", "https://portal.example",
                        raising=False)
    monkeypatch.setattr(atrium_bridge.settings, "atrium_watcher_client_key", client_key, raising=False)


def test_not_ready_without_client_key(monkeypatch):
    """No client_key configured => the picker stays off, even with the bridge otherwise wired."""
    monkeypatch.setattr(atrium_bridge.settings, "platform_sso_secret", "s3cret", raising=False)
    monkeypatch.setattr(atrium_bridge.settings, "atrium_api_url", "https://portal.example",
                        raising=False)
    monkeypatch.setattr(atrium_bridge.settings, "atrium_watcher_client_key", "", raising=False)
    assert atrium_watcher.ready() is False
    assert atrium_watcher.list_channels() == []
    assert atrium_watcher.list_videos("wch_1") == []
    assert atrium_watcher.get_transcript("wch_1", "vid_1") is None


def test_ready_when_bridge_and_client_key_are_both_set(monkeypatch):
    _configure(monkeypatch)
    assert atrium_watcher.ready() is True


def test_channels_degrade_to_empty_on_unreachable_atrium(monkeypatch):
    _configure(monkeypatch)

    def _boom(*a, **k):
        raise atrium_bridge.urllib.error.URLError("down")

    monkeypatch.setattr(atrium_bridge.urllib.request, "urlopen", _boom)
    assert atrium_watcher.list_channels() == []
    assert atrium_watcher.list_videos("wch_1") == []
    assert atrium_watcher.get_transcript("wch_1", "vid_1") is None


def test_get_transcript_returns_none_when_not_yet_fetched(monkeypatch):
    """Atrium's endpoint 404s (no_transcript) when the video is archived but not yet fetched."""
    _configure(monkeypatch)

    class _Resp:
        status = 404

        def read(self):
            return b'{"error": "no_transcript"}'

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    import urllib.error

    def _urlopen(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 404, "not found", {}, None)

    monkeypatch.setattr(atrium_bridge.urllib.request, "urlopen", _urlopen)
    assert atrium_watcher.get_transcript("wch_1", "vid_1") is None


def test_get_transcript_returns_the_transcript_on_success(monkeypatch):
    _configure(monkeypatch)

    class _Resp:
        status = 200

        def read(self):
            return b'{"ok": true, "title": "Cold email systemization", "url": "https://youtu.be/abc", "transcript": "full text here"}'

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def _urlopen(req, timeout=None):
        return _Resp()

    monkeypatch.setattr(atrium_bridge.urllib.request, "urlopen", _urlopen)
    out = atrium_watcher.get_transcript("wch_1", "vid_1")
    assert out == {"title": "Cold email systemization", "url": "https://youtu.be/abc",
                   "transcript": "full text here"}


def test_signed_requests_carry_the_configured_client_key(monkeypatch):
    """channels/videos/transcript all scope to the configured workspace, signed the same way."""
    _configure(monkeypatch, client_key="agora")
    seen = {}

    class _Resp:
        status = 200

        def read(self):
            return b'{"ok": true, "channels": []}'

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def _urlopen(req, timeout=None):
        seen["url"] = req.full_url
        return _Resp()

    monkeypatch.setattr(atrium_bridge.urllib.request, "urlopen", _urlopen)
    atrium_watcher.list_channels()
    assert seen["url"].startswith("https://portal.example/api/internal/watcher/channels")
    assert "client=agora" in seen["url"]

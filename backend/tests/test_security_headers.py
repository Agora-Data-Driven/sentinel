"""Security response headers, focused on the frame-ancestors / X-Frame-Options pairing."""
from __future__ import annotations

from app.config import settings


def test_frame_ancestors_allows_the_agora_ecosystem_by_default(client):
    # Default must NOT be 'none' — Sentinel frames its own same-origin who-we-are.html (North Star)
    # and is meant to live inside the Agora portal.
    r = client.get("/api/health")
    csp = r.headers["content-security-policy"]
    assert "frame-ancestors 'self' https://*.agoradatadriven.com https://agoradatadriven.com" in csp
    # With framing allowed, the legacy XFO header must not hard-DENY and contradict the CSP.
    assert r.headers["x-frame-options"] == "SAMEORIGIN"


def test_frame_ancestors_none_still_hard_denies(client, monkeypatch):
    monkeypatch.setattr(settings, "csp_frame_ancestors", "'none'")
    r = client.get("/api/health")
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert r.headers["x-frame-options"] == "DENY"

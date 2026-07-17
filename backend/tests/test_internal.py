"""Tests for the HMAC-gated internal service-to-service endpoints (app/routers/internal.py).

The portal calls /api/internal/user-lookup on a verified Google email it doesn't know locally to
decide whether to sign the user in — this is what makes Sentinel the source of truth for "who may
sign in with Google". The gate is an HMAC over "purpose:ts" with the shared `platform-sso-key`.
"""
from __future__ import annotations

import hashlib
import hmac
import time

import pytest

from app.config import settings

SECRET = "shared-platform-sso-key-for-tests"


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    """Configure the shared secret so the internal endpoints are enabled (unset = 503)."""
    monkeypatch.setattr(settings, "platform_sso_secret", SECRET)


def _sig(purpose: str, ts: str, secret: str = SECRET) -> dict:
    mac = hmac.new(secret.encode(), f"{purpose}:{ts}".encode(), hashlib.sha256).hexdigest()
    return {"X-Academy-Ts": ts, "X-Academy-Sig": mac}


def _now() -> str:
    return str(int(time.time()))


def test_user_lookup_active_user(client, make_user):
    make_user(email="Staff@Agora.ph", active=True, name="Staff Member")
    r = client.get("/api/internal/user-lookup", params={"email": "staff@agora.ph"},
                   headers=_sig("user-lookup", _now()))
    assert r.status_code == 200
    body = r.json()
    assert body["found"] is True
    assert body["active"] is True
    assert body["name"] == "Staff Member"


def test_user_lookup_is_case_insensitive(client, make_user):
    make_user(email="mixed@agora.ph", active=True)
    r = client.get("/api/internal/user-lookup", params={"email": "MIXED@AGORA.PH"},
                   headers=_sig("user-lookup", _now()))
    assert r.status_code == 200 and r.json()["found"] is True


def test_user_lookup_inactive_user(client, make_user):
    make_user(email="left@agora.ph", active=False)
    r = client.get("/api/internal/user-lookup", params={"email": "left@agora.ph"},
                   headers=_sig("user-lookup", _now()))
    assert r.status_code == 200
    body = r.json()
    assert body["found"] is True and body["active"] is False


def test_user_lookup_unknown_email(client):
    r = client.get("/api/internal/user-lookup", params={"email": "nobody@agora.ph"},
                   headers=_sig("user-lookup", _now()))
    assert r.status_code == 200
    body = r.json()
    assert body["found"] is False and body["active"] is False


def test_user_lookup_bad_signature(client, make_user):
    make_user(email="staff@agora.ph", active=True)
    r = client.get("/api/internal/user-lookup", params={"email": "staff@agora.ph"},
                   headers={"X-Academy-Ts": _now(), "X-Academy-Sig": "deadbeef"})
    assert r.status_code == 401


def test_user_lookup_wrong_purpose_rejected(client, make_user):
    # A signature minted for a DIFFERENT purpose must not authorize this endpoint.
    make_user(email="staff@agora.ph", active=True)
    ts = _now()
    r = client.get("/api/internal/user-lookup", params={"email": "staff@agora.ph"},
                   headers=_sig("academy-people", ts))
    assert r.status_code == 401


def test_user_lookup_stale_timestamp_rejected(client, make_user):
    make_user(email="staff@agora.ph", active=True)
    old = str(int(time.time()) - 3600)  # an hour old, well past the 5-min window
    r = client.get("/api/internal/user-lookup", params={"email": "staff@agora.ph"},
                   headers=_sig("user-lookup", old))
    assert r.status_code == 401


def test_user_lookup_disabled_without_secret(client, make_user, monkeypatch):
    monkeypatch.setattr(settings, "platform_sso_secret", "")
    make_user(email="staff@agora.ph", active=True)
    r = client.get("/api/internal/user-lookup", params={"email": "staff@agora.ph"},
                   headers=_sig("user-lookup", _now(), secret=""))
    assert r.status_code == 503

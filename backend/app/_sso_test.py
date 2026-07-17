"""Off-cloud test for portal SSO verification (no DB, no network).

Verifies the wire format matches the portal's platform_sso.py byte for byte, and that every
malformed / forged / expired / wrong-secret cookie is rejected (fail-closed).

Run:  python backend/app/_sso_test.py   (exit 0 = pass)
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import sys
import time

# Put `backend/` on the path so this runs from anywhere, with no venv or pytest needed.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import sso  # noqa: E402

fails = []


def check(label, cond):
    print(("  [OK] " if cond else "  [FAIL] ") + label)
    if not cond:
        fails.append(label)


SECRET = "test-sso-secret"
NOW = 1_700_000_000


def portal_mint(secret, clients, subject, exp):
    """Mint EXACTLY the way the portal's platform_sso.mint_sso_cookie does — independent
    reimplementation, so this test fails if our verifier drifts from the signer of record."""
    payload = {"sub": subject, "clients": list(clients), "iat": 1, "exp": exp}
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    p = base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
    mac = hmac.new(secret.encode("utf-8"), p.encode("ascii"), hashlib.sha256).digest()
    return "%s.%s" % (p, base64.urlsafe_b64encode(mac).rstrip(b"=").decode("ascii"))


# --- wire-format compatibility with the portal ------------------------------
good = portal_mint(SECRET, ["*"], "info@agoradatadriven.com", NOW + 3600)
check("a portal-minted cookie verifies", sso.verify(SECRET, good, now=NOW) is not None)
check("sub is extracted", sso.email_from_cookie(SECRET, good, now=NOW) == "info@agoradatadriven.com")
check("our mint() matches the portal's byte for byte",
      sso.mint(SECRET, "info@agoradatadriven.com", ["*"], 3600, now=1) ==
      portal_mint(SECRET, ["*"], "info@agoradatadriven.com", 1 + 3600))

# --- normalisation ----------------------------------------------------------
check("email is lower-cased + trimmed",
      sso.email_from_cookie(SECRET, portal_mint(SECRET, ["*"], "  Ian@Agora.PH ", NOW + 60), now=NOW)
      == "ian@agora.ph")

# --- fail-closed ------------------------------------------------------------
check("expired cookie rejected", sso.verify(SECRET, portal_mint(SECRET, ["*"], "x@y.com", NOW - 1), now=NOW) is None)
check("wrong secret rejected", sso.verify("other-secret", good, now=NOW) is None)
check("empty secret rejected (SSO not configured)", sso.verify("", good, now=NOW) is None)
check("no cookie rejected", sso.verify(SECRET, None, now=NOW) is None)
check("garbage rejected", sso.verify(SECRET, "not-a-cookie", now=NOW) is None)
check("no-dot rejected", sso.verify(SECRET, "abcdef", now=NOW) is None)
check("bad base64 rejected", sso.verify(SECRET, "!!!.???", now=NOW) is None)
check("email_from_cookie on a forged cookie is empty",
      sso.email_from_cookie(SECRET, "abc.def", now=NOW) == "")

# Tamper: flip the payload but keep the old signature.
p, s = good.split(".", 1)
forged_payload = base64.urlsafe_b64encode(
    json.dumps({"sub": "attacker@evil.com", "clients": ["*"], "iat": 1, "exp": NOW + 3600},
               separators=(",", ":"), sort_keys=True).encode()).rstrip(b"=").decode()
check("tampered payload with a stale signature rejected",
      sso.verify(SECRET, forged_payload + "." + s, now=NOW) is None)
check("signature swapped for another valid one rejected",
      sso.verify(SECRET, p + "." + portal_mint(SECRET, ["*"], "other@x.com", NOW + 3600).split(".", 1)[1],
                 now=NOW) is None)

# A cookie with NO client grant still identifies its subject: Sentinel authorizes from the users
# table, not the client list (unlike a client dashboard).
check("a client-scoped cookie still yields its subject (authz is the users table)",
      sso.email_from_cookie(SECRET, portal_mint(SECRET, ["riverdance"], "staff@agora.ph", NOW + 60), now=NOW)
      == "staff@agora.ph")

# Real clock path (no `now` injected) — guards against an inverted expiry comparison.
check("live-clock cookie verifies", sso.verify(SECRET, sso.mint(SECRET, "a@b.com", ["*"], 600)) is not None)
check("live-clock expired cookie rejected",
      sso.verify(SECRET, sso.mint(SECRET, "a@b.com", ["*"], -10)) is None)

if fails:
    print("\n[sso-test] FAIL (%d): %s" % (len(fails), ", ".join(fails)))
    sys.exit(1)
print("\n[sso-test] PASS")

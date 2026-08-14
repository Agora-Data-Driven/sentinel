# DRAFT — Kiosk attendance security

**Status: DRAFT. Nothing here is built.** Raised 2026-08-14, deferred by owner decision to a later
session. This is the written-up plan so the analysis is not re-done from scratch; it is deliberately
not a change.

Related: `backend/app/utils/qr.py` (carries the short version of this in its module docstring),
`backend/app/routers/attendance.py` (`kiosk_guard`, `_resolve_token`).

---

## 1. What is actually wrong

### 1.1 The badge token is a static, non-expiring bearer secret

```python
# utils/qr.py
def new_token() -> str:
    return secrets.token_urlsafe(18)
```

Minted once per employee. `attendance._resolve_token` accepts it forever — it checks only that the
`qr_tokens` row is `is_active` and the user is active. There is no rotation, no expiry, no
device binding, no geofence, no rate limit.

**Consequence, stated plainly: a photograph of a colleague's badge is a permanent ability to clock
that colleague in and out, from any device, anywhere.** The QR is printed on a badge people wear
visibly; it is captured by any camera pointed at them, and by any group photo they appear in.

The token itself is fine cryptographically (18 random bytes). The problem is its *lifetime* and the
fact that possession alone is sufficient.

### 1.2 The kiosk key is accepted as a query parameter

```python
supplied = request.headers.get("X-Kiosk-Key") or request.query_params.get("kiosk_key")
```

A URL-borne secret lands in access logs, browser history, the Referer header, and any screenshot of
the address bar. The header form is already supported and is the only one that should be.

### 1.3 Dev mode is open by default

`kiosk_guard` returns successfully when `settings.kiosk_key` is unset and `is_production` is False.
Convenient locally; it also means any non-production deployment (a staging host, a demo, a laptop on
the office network) has fully open punch endpoints.

### 1.4 What is NOT wrong

Worth recording so it is not "fixed" later by mistake:

- The **super-admin session** path in `kiosk_guard` is fine. `/scanner` is super-admin-only and a
  signed-in super admin is already trusted.
- The **production fail-closed** behaviour (503 when no key is configured) is correct.
- `_resolve_token` correctly refuses an inactive user, not just an inactive token.

---

## 2. Options, ranked by effort

Each is independently deployable. They layer — 1 and 2 together already remove the realistic attack.

### Option 1 — Rotate / reissue a badge  ·  *cheapest real improvement*

A "reissue badge" action in People that mints a new token and deactivates the old row.

- **Fixes:** today a leaked badge has **no remedy at all** short of deactivating the employee.
- **Cost:** one endpoint, one button, one `qr_tokens` row swap. Reprint that one badge.
- **Does not fix:** the leak itself, only the recovery from it.
- **Note:** `qr_tokens` already has `is_active`, so the schema likely needs nothing.

### Option 2 — Bind the punch to the kiosk device  ·  *best value*

Require the kiosk key **and** the badge together on `/scan` and `/event`, instead of either-or.

- **Fixes:** the actual attack. A photographed badge becomes inert anywhere except the kiosk tablet.
- **Cost:** the tablet already sends the key; the change is to stop treating the key as *sufficient*
  and start treating it as *required alongside* a badge. Nothing is reprinted.
- **Watch out:** the super-admin `/scanner` phone tool relies on the session instead of the key —
  decide explicitly whether that path also requires the badge (it should; it already scans one).
- **Combine with:** moving the key to header-only (§1.2) in the same change; they touch one function.

### Option 3 — Time-based codes (TOTP-style)  ·  *strongest, real rollout cost*

The badge carries a seed; the scanned code derives from seed + current time, so a photo expires
within seconds.

- 🔴 **This changes what is PRINTED.** A static PNG can no longer *be* the credential, so every
  person needs a screen (phone app) or a reissued badge on a different medium. **Do not start here
  by accident** — it is the only option on this list with a per-person rollout.
- Clock skew on the kiosk tablet becomes a correctness concern.
- Offline kiosk boot (a defining requirement — the kiosk must work with no network) still works,
  since verification is local arithmetic, but the tablet's clock must be right.

### Not recommended

- **Geofencing by IP** — Cloud Run sees the egress IP, and the kiosk is on office wifi with the rest
  of the estate. It would reject nothing an attacker on the same wifi would do.
- **Photo capture on punch** — an after-the-fact deterrent that adds a camera-permission dependency
  and a storage/PII question, without preventing the punch.

---

## 3. Constraints anything here must respect

1. 🔴 **The kiosk must boot offline from its service-worker cache.** This is its defining
   requirement (see `sentinel/AGENTS.md` §5 — `/kiosk` deliberately opts out of dev-reload for
   exactly this reason). Any scheme requiring a network round trip *to render the scanner* is out.
2. **A service-worker cache is per ORIGIN.** After the `CANONICAL_HOST` redirect landed
   (2026-08-11), a kiosk bookmarked on the `run.app` host is on a different origin and must be
   opened once while online to re-prime. Re-check which origin the tablet actually uses before
   changing anything here.
3. **Offline punches queue in IndexedDB** and sync later via `/offline-sync`. Any new
   per-punch check must be verifiable at sync time, not only at punch time — a time-based code
   (Option 3) needs the punch's own timestamp carried and validated against *that*, not against
   arrival time.
4. **Deploy via `deploy/deploy.ps1` only.** A raw `gcloud run deploy` wipes the SSO env.

---

## 4. Suggested order, when this is picked up

1. §1.2 + §1.3 (header-only key, close the dev-open default) — small, independent, no badge changes.
2. Option 1 (rotation) — gives every later step a recovery path.
3. Option 2 (device binding) — closes the real attack.
4. Option 3 only if 1–3 prove insufficient, and only with the reprint budget agreed up front.

---

## 5. Open questions for the owner

- How many kiosk devices are there, and is the key shared across them? (A per-device key makes
  Option 2 revocable per device.)
- Is the `/scanner` phone tool used in practice, or is the tablet the only path?
- Has a badge ever actually been misused, or is this purely preventative? That changes the urgency
  ordering above, not the analysis.

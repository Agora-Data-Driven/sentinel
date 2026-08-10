"""Publish the personal report into a Google Doc.

    publish(markdown, doc_id) -> {"ok": bool, "error": str, "bytes": int}

WHY DRIVE AND NOT THE DOCS API. The Docs API edits a document through `batchUpdate` with explicit
character index ranges, so "replace everything" means deleting a computed range and re-inserting —
arithmetic that goes wrong quietly and produces no headings without a second pass of styling
requests. Drive's media upload converts an uploaded `text/markdown` body into real Doc structure
(headings, lists, tables) in ONE request, and `drive.googleapis.com` is already enabled on the
project where `docs.googleapis.com` is not. Fewer moving parts, one less API to turn on.

WHY A SERVICE ACCOUNT AND NOT OAUTH. The target document lives in a personal @gmail.com Drive, and
domain-wide delegation only works inside a Workspace domain — it cannot impersonate a consumer
account. So the document is created by hand and SHARED with this service account as an editor, and
Sentinel writes to it with its own runtime credentials. Nothing to consent to, no refresh token to
store or rotate, and the blast radius is exactly the files that were deliberately shared: a service
account's Drive contains nothing else.

🔴 **THIS REPLACES THE ENTIRE DOCUMENT.** The report is regenerated in full on every run, so the
target must be a document dedicated to it. Anything typed into that file by hand is destroyed on
the next pass, without a prompt, at whatever hour the job fires. Do not point this at a document
anyone edits.

🔴 **UTF-8 BYTES, EXPLICITLY.** The report carries em-dashes, arrows and the 🔴 marker. Python on
Windows encodes text to cp1252 by default and raises `UnicodeEncodeError` on all of them (observed
while building this, 2026-08-09) — and the estate has already been bitten by a Windows text-mode
write producing cp1252 where a reader expected UTF-8. The body is encoded once, here, and the
charset is declared on the Content-Type.

STDLIB TRANSPORT, matching `atrium_bridge.py` / `engine_bridge.py`: `google.auth` mints the token,
`urllib` makes the call. That keeps the runtime image free of `google-api-python-client`.

🔴 **THIS ONE IS NOT FAIL-SOFT.** Every other bridge in this service degrades silently because it
sits behind a page that must still render. This is a scheduled job whose ONLY output is the
document; a silent failure here is indistinguishable from a successful run that wrote yesterday's
content, and the reader has no way to tell the report is stale. It returns an explicit verdict and
the caller records it.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request

from ..config import settings

log = logging.getLogger(__name__)

# A service account only ever sees what has been shared with it, so the broad scope is bounded by
# sharing rather than by the scope string. `drive.file` is deliberately NOT used: it covers files
# the app itself created, and this document is created by a human and shared in.
SCOPES = ("https://www.googleapis.com/auth/drive",)

UPLOAD_URL = "https://www.googleapis.com/upload/drive/v3/files/{file_id}"
META_URL = "https://www.googleapis.com/drive/v3/files/{file_id}"

WRITE_TIMEOUT = 60


class _UrllibResponse:
    """The three attributes `google.auth` reads off a transport response."""

    def __init__(self, status: int, headers, data: bytes):
        self.status = status
        self.headers = headers
        self.data = data


class _UrllibRequest:
    """A `google.auth.transport.Request` implemented on urllib.

    🔴 THIS EXISTS TO AVOID ADDING `requests` TO SENTINEL. The obvious import —
    `google.auth.transport.requests` — raises ImportError unless the `requests` package is present,
    and this service deliberately has no HTTP client library at all: `atrium_bridge.py` and
    `engine_bridge.py` both say so, on the grounds that a bridge must never be the reason a page
    fails. Pulling in `requests` + `urllib3` for the sake of one scheduled job would spend that
    principle on the least important feature in the codebase.

    The interface google-auth actually requires is this small: a callable taking
    (url, method, body, headers, timeout) and returning something with `.status`, `.headers` and
    `.data`. google-auth still owns credential discovery, scope handling and token refresh — only
    the socket is ours.
    """

    def __call__(self, url, method="GET", body=None, headers=None, timeout=None, **kwargs):
        req = urllib.request.Request(url, data=body, method=method, headers=dict(headers or {}))
        try:
            with urllib.request.urlopen(req, timeout=timeout or WRITE_TIMEOUT) as resp:
                return _UrllibResponse(resp.status, dict(resp.headers), resp.read())
        except urllib.error.HTTPError as exc:
            # google-auth inspects the status and body to build its own error message, so a failed
            # token exchange must come back as a RESPONSE, not as a raised exception.
            return _UrllibResponse(exc.code, dict(exc.headers or {}), exc.read())


METADATA_TOKEN_URL = ("http://metadata.google.internal/computeMetadata/v1/"
                      "instance/service-accounts/default/token")
IAM_TOKEN_URL = ("https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/"
                 "{sa}:generateAccessToken")


def _metadata_token() -> tuple[str, str]:
    """The runtime service account's `cloud-platform` token, straight from the metadata server.

    🔴 DELIBERATELY NOT VIA `google.auth.default()`. On Cloud Run that returns a
    `compute_engine.Credentials`, whose refresh path does
    `from google.auth.transport import requests` (google/auth/compute_engine/credentials.py) — so
    it raises ImportError in an image without the `requests` package, which this service does not
    ship. Measured in production 2026-08-10: the report built fine at 234k characters and the
    publish died there. The metadata server is a plain HTTP endpoint, so urllib reaches it with no
    library at all.
    """
    req = urllib.request.Request(METADATA_TOKEN_URL, headers={"Metadata-Flavor": "Google"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            token = (json.loads(resp.read().decode("utf-8", "replace")) or {}).get("access_token")
            return (token or ""), ("" if token else "the metadata server returned no token")
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError, TimeoutError, OSError):
        # Off-cloud (a laptop) there is no metadata server. Not an error — just a different path.
        return "", "no metadata server (not running on Cloud Run)"


def _drive_token(source_token: str, service_account: str) -> tuple[str, str]:
    """Exchange a `cloud-platform` token for a DRIVE-scoped one via the IAM Credentials API.

    🔴 THIS EXCHANGE IS WHY THE FEATURE WORKS AT ALL, AND ITS ABSENCE LOOKS LIKE A SHARING BUG.
    The metadata server only ever issues `cloud-platform`, and the Drive API does not accept that
    scope — it wants the Drive scope specifically, and a metadata token cannot be widened to it.
    Without this step Drive answers 403, or 404 on a file that genuinely IS shared, which reads
    exactly like "you forgot to share the document" and sends the next person to re-check sharing
    that was never the problem.

    The account impersonates ITSELF, so the only requirement is that it hold
    `roles/iam.serviceAccountTokenCreator` on itself (granted 2026-08-09).
    """
    body = json.dumps({"scope": list(SCOPES), "lifetime": "600s"}).encode("utf-8")
    req = urllib.request.Request(
        IAM_TOKEN_URL.format(sa=urllib.parse.quote(service_account)),
        data=body,
        method="POST",
        headers={"Authorization": f"Bearer {source_token}",
                 "Content-Type": "application/json; charset=UTF-8"},
    )
    try:
        with urllib.request.urlopen(req, timeout=WRITE_TIMEOUT) as resp:
            token = (json.loads(resp.read().decode("utf-8", "replace")) or {}).get("accessToken")
            return (token or ""), ("" if token else "the IAM Credentials API returned no token")
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = ((json.loads(exc.read().decode("utf-8", "replace")) or {})
                      .get("error", {}).get("message") or "")[:160]
        except Exception:                          # noqa: BLE001
            detail = ""
        if exc.code in (403, 404):
            detail = detail or (f"{service_account} may not impersonate itself — it needs "
                                f"roles/iam.serviceAccountTokenCreator on itself")
        return "", f"minting a Drive-scoped token failed ({exc.code}: {detail})"
    except (urllib.error.URLError, ValueError, TimeoutError, OSError) as exc:
        return "", f"minting a Drive-scoped token failed ({str(exc)[:80]})"


def _access_token() -> tuple[str, str]:
    """A Drive-scoped bearer token, or ("", reason).

    Two paths, and the Cloud Run one is deliberately library-free (see `_metadata_token`):

      1. **On Cloud Run** — metadata token, exchanged for the Drive scope.
      2. **Locally** — `google.auth.default()` over our urllib transport, then the same exchange
         when a service account is named. A developer's own ADC cannot be widened to Drive either,
         so without impersonation this reports the reason rather than failing opaquely.
    """
    target = (settings.report_impersonate_sa or "").strip()
    source, why = _metadata_token()
    if not source:
        try:
            import google.auth
        except ImportError:
            return "", f"{why}, and google-auth is not installed for the local fallback"
        try:
            creds, _project = google.auth.default()
            creds.refresh(_UrllibRequest())
            source = creds.token or ""
        except Exception as exc:                   # noqa: BLE001 — reported, never raised
            return "", f"could not obtain credentials ({type(exc).__name__}: {str(exc)[:120]})"
        if not source:
            return "", "the local credential yielded no token"
    if not target:
        return "", ("no service account configured to impersonate — set REPORT_IMPERSONATE_SA, or "
                    "Drive will refuse the cloud-platform token")
    return _drive_token(source, target)


def enabled() -> bool:
    """True when a Drive-scoped token can be minted."""
    token, _ = _access_token()
    return bool(token)


def describe(doc_id: str) -> tuple[dict, str]:
    """Read the target's metadata — the pre-flight that proves sharing actually happened.

    Returns ({...}, "") or ({}, reason). A 404 here almost always means the document was never
    shared with this service account, which is the single most likely setup mistake and is
    indistinguishable from "deleted" unless it is said out loud.
    """
    token, err = _access_token()
    if not token:
        return {}, err
    url = META_URL.format(file_id=urllib.parse.quote(doc_id)) + "?" + urllib.parse.urlencode({
        "fields": "id,name,mimeType,capabilities(canEdit),owners(emailAddress)",
        "supportsAllDrives": "true",
    })
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=WRITE_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8", "replace")), ""
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return {}, ("the document was not found — most likely it has not been shared with this "
                        "service account (share it as an Editor), or the id is wrong")
        return {}, f"Drive answered {exc.code} reading the document"
    except (urllib.error.URLError, ValueError, TimeoutError, OSError) as exc:
        return {}, f"couldn't reach Drive ({str(exc)[:80]})"


def publish(markdown: str, doc_id: str) -> dict:
    """Replace `doc_id`'s entire contents with `markdown`, converted to Doc structure.

    Returns {"ok", "error", "bytes"}. Never raises — the caller (a scheduled job) records the
    verdict rather than dying, but a False `ok` is a real failure and must be surfaced, not
    swallowed.
    """
    if not doc_id:
        return {"ok": False, "error": "no document id configured", "bytes": 0}
    token, err = _access_token()
    if not token:
        return {"ok": False, "error": err, "bytes": 0}

    # 🔴 Encoded once, here. See the module docstring.
    body = markdown.encode("utf-8")

    # `uploadType=media` replaces the file's content; naming the Google Doc mimeType as the TARGET
    # is what makes Drive convert the markdown into headings and tables rather than storing it as a
    # plain-text blob. The source type travels on Content-Type.
    url = UPLOAD_URL.format(file_id=urllib.parse.quote(doc_id)) + "?" + urllib.parse.urlencode({
        "uploadType": "media",
        "supportsAllDrives": "true",
    })
    req = urllib.request.Request(
        url,
        data=body,
        method="PATCH",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "text/markdown; charset=UTF-8",
            "Content-Length": str(len(body)),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=WRITE_TIMEOUT) as resp:
            ok = 200 <= resp.status < 300
            return {"ok": ok, "error": "" if ok else f"Drive answered {resp.status}",
                    "bytes": len(body)}
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            payload = json.loads(exc.read().decode("utf-8", "replace"))
            detail = ((payload.get("error") or {}).get("message") or "")[:160]
        except Exception:                          # noqa: BLE001
            detail = ""
        if exc.code == 404:
            detail = detail or ("not found — has the document been shared with this service "
                                "account as an Editor?")
        log.warning("report doc publish failed: HTTP %s %s", exc.code, detail)
        return {"ok": False, "error": f"Drive answered {exc.code}"
                                      + (f" ({detail})" if detail else ""), "bytes": len(body)}
    except (urllib.error.URLError, ValueError, TimeoutError, OSError) as exc:
        log.warning("report doc publish failed: %s", exc)
        return {"ok": False, "error": f"couldn't reach Drive ({str(exc)[:80]})", "bytes": len(body)}

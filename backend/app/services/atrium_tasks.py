"""Atrium task bridge -- Sentinel's window onto the tasks Atrium owns.

Atrium (the `platform-dash` portal) is the SOURCE OF TRUTH for client-facing tasks: each client's
work lives in that client's own workspace JSON, which is why a task typed into a client's Atrium
Progress board belongs to that client by construction. Sentinel's board is the team's cross-client
view over the same work, PLUS its own internal-only rows that clients never see.

Transport is the platform's existing server-to-server HMAC (no cookie, no new secret): HMAC-SHA256
over `"{purpose}:{ts}"` with the shared `platform-sso-key`, sent as X-Academy-Ts / X-Academy-Sig --
the same scheme `sentinel_directory.py` uses in the other direction and mastery-engine uses against
`/api/internal/people`.

EVERYTHING here is best-effort and fail-SOFT: an unset secret, a missing URL, a timeout, a non-200
or a malformed body all degrade to "no Atrium tasks" so the internal board still renders Sentinel's
own rows. An Atrium outage must never blank the team's board.

STDLIB ONLY (urllib, not requests): this service's requirements.txt is deliberately tight, and an
optional bridge must never be able to take the app down at import time -- adding `import requests`
here crashed every container on boot (2026-07-27) because it isn't in the image.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request

from ..config import settings

log = logging.getLogger(__name__)

# Atrium-owned cards carry this prefix in their board id so the frontend and the mutation routes can
# tell them from Sentinel's own integer-keyed rows and send edits back to Atrium.
ATRIUM_ID_PREFIX = "atrium:"
_TIMEOUT = 6

# Sentinel status label -> Atrium stage key. Atrium deliberately adopted Sentinel's status set
# (constants.TASK_STATUSES) so the two boards speak the same language; this is the key mapping.
STAGE_BY_STATUS = {
    "To Do": "todo",
    "In Progress": "in_progress",
    "For Review": "for_review",
    "Waiting for Client": "waiting_client",
    "Revision Needed": "revision",
    "Completed": "completed",
    "Blocked": "blocked",
}


def _base_url() -> str:
    """The portal's origin, or "" when unconfigured (bridge stays off)."""
    url = (getattr(settings, "atrium_api_url", "") or "").strip()
    if not url:
        # Fall back to the portal login URL's origin, so a deploy that already knows where the
        # portal lives needs no extra setting.
        login = (getattr(settings, "portal_login_url", "") or "").strip()
        if login:
            url = login.split("/auth/")[0].split("/login")[0]
    return url.rstrip("/")


def _headers(purpose: str) -> dict | None:
    secret = (settings.platform_sso_secret or "").strip()
    if not secret:
        return None
    ts = str(int(time.time()))
    sig = hmac.new(secret.encode(), f"{purpose}:{ts}".encode(), hashlib.sha256).hexdigest()
    return {"X-Academy-Ts": ts, "X-Academy-Sig": sig}


def enabled() -> bool:
    """True when both the shared secret and the portal URL are configured."""
    return bool((settings.platform_sso_secret or "").strip() and _base_url())


def _call(purpose: str, path: str, params: dict | None = None,
          body: dict | None = None) -> tuple[int, dict]:
    """One signed request. Returns (status_code, parsed_json); (0, {}) if it never left the ground.

    Never raises -- every caller degrades instead, because an Atrium outage must not break the
    internal board."""
    headers = _headers(purpose)
    base = _base_url()
    if not headers or not base:
        return 0, {}
    url = base + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers,
                                 method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            raw = resp.read().decode("utf-8", "replace")
            return resp.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as exc:
        # A non-2xx still carries a body worth surfacing (e.g. Atrium's completion guard).
        try:
            return exc.code, json.loads(exc.read().decode("utf-8", "replace"))
        except Exception:
            return exc.code, {}
    except (urllib.error.URLError, ValueError, TimeoutError, OSError) as exc:
        log.warning("atrium %s call failed: %s", purpose, exc)
        return 0, {}


def fetch_tasks(client_key: str = "") -> list[dict]:
    """Every Atrium task (optionally one client's). [] on any failure -- never raises."""
    code, body = _call("tasks", "/api/internal/tasks",
                       params={"client": client_key} if client_key else None)
    if code != 200:
        if code:
            log.warning("atrium task fetch returned %s", code)
        return []
    tasks = body.get("tasks")
    return tasks if isinstance(tasks, list) else []


def move_task(client_key: str, task_id: str, stage: str, actor: str = "") -> tuple[bool, str]:
    """Move an Atrium task. Returns (ok, error_message) -- the error is safe to show the user."""
    if not enabled():
        return False, "The Atrium bridge is not configured."
    code, body = _call("task-move", "/api/internal/task-move",
                       body={"client_key": client_key, "task_id": task_id,
                             "stage": stage, "actor": actor})
    if code == 200:
        return True, ""
    if not code:
        return False, "Couldn't reach Atrium to move that card."
    # Atrium's completion guard (open sub-tasks / unresolved change requests) explains itself.
    return False, (body.get("error") or "Atrium rejected that move.")


def add_task(client_key: str, title: str, stage: str = "todo", client_facing: bool = False,
             priority: str = "Medium", department: str = "", due_date: str = "",
             actor: str = "", actor_name: str = "") -> tuple[bool, str]:
    """Create a task in Atrium. `client_facing=False` files internal work clients never see."""
    if not enabled():
        return False, "The Atrium bridge is not configured."
    code, _body = _call("task-add", "/api/internal/task-add",
                        body={"client_key": client_key, "title": title, "stage": stage,
                              "client_facing": client_facing, "priority": priority,
                              "department": department, "due_date": due_date,
                              "actor": actor, "actor_name": actor_name})
    if code == 200:
        return True, ""
    if not code:
        return False, "Couldn't reach Atrium to add that card."
    return False, "Atrium rejected that card."


def as_board_card(t: dict, client: object = None) -> dict:
    """Map an Atrium task onto the shape the Kanban board already renders (serializers.task_card).

    `client` is the matching Sentinel Client row (resolved via Client.atrium_client_id) when there
    is one, so the board's client filter and client name work on Atrium cards exactly as they do on
    Sentinel's own. Internal-only Sentinel concepts it has no equivalent for (assignee objects,
    team ids) come back empty rather than faked, and `source` marks the card so the UI can badge it
    and route edits back to Atrium."""
    return {
        "id": ATRIUM_ID_PREFIX + (t.get("atrium_id") or ""),
        "title": t.get("title") or "",
        "status": t.get("status") or "To Do",
        "priority": t.get("priority") or "Medium",
        "due_date": t.get("due_date") or None,
        "labels": t.get("labels") or [],
        "client_id": getattr(client, "id", None),
        "client_name": (getattr(client, "name", None)
                        or t.get("client_name") or t.get("client_key") or ""),
        "assigned_to_id": None,
        "assignee": None,
        "assigned_team_id": None,
        "created_by_id": None,
        "created_by": None,
        "comment_count": t.get("comment_count") or 0,
        "attachment_count": 0,
        "checklist_total": t.get("checklist_total") or 0,
        "checklist_done": t.get("checklist_done") or 0,
        # Atrium's client_facing IS the Atrium-visibility flag from Sentinel's point of view.
        "atrium_visible": bool(t.get("client_facing")),
        "source": "atrium",
        "atrium_client_key": t.get("client_key") or "",
        "atrium_task_id": t.get("task_id") or "",
    }


def split_id(board_id: str) -> tuple[str, str]:
    """('client_key', 'task_id') for an Atrium board id, or ('', '') if it isn't one."""
    if not isinstance(board_id, str) or not board_id.startswith(ATRIUM_ID_PREFIX):
        return "", ""
    rest = board_id[len(ATRIUM_ID_PREFIX):]
    key, _, task_id = rest.partition(":")
    return key, task_id

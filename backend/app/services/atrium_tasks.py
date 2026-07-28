"""Atrium task bridge -- Sentinel's window onto the tasks Atrium owns.

Atrium (the `platform-dash` portal) is the SOURCE OF TRUTH for client-facing tasks: each client's
work lives in that client's own workspace JSON, which is why a task typed into a client's Atrium
Progress board belongs to that client by construction. Sentinel's board is the team's cross-client
view over the same work, PLUS its own internal-only rows that clients never see.

Transport is the platform's existing server-to-server HMAC (no cookie, no new secret) --
see `atrium_bridge.py` (shared with `atrium_watcher.py`), which also uses this signing.

EVERYTHING here is best-effort and fail-SOFT: an unset secret, a missing URL, a timeout, a non-200
or a malformed body all degrade to "no Atrium tasks" so the internal board still renders Sentinel's
own rows. An Atrium outage must never blank the team's board.
"""

from __future__ import annotations

import logging

from . import atrium_bridge
from .atrium_bridge import enabled

log = logging.getLogger(__name__)

_READ_TIMEOUT = atrium_bridge.READ_TIMEOUT
_WRITE_TIMEOUT = atrium_bridge.WRITE_TIMEOUT
_call = atrium_bridge.call

# Atrium-owned cards carry this prefix in their board id so the frontend and the mutation routes can
# tell them from Sentinel's own integer-keyed rows and send edits back to Atrium.
ATRIUM_ID_PREFIX = "atrium:"

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
                             "stage": stage, "actor": actor},
                       timeout=_WRITE_TIMEOUT)
    if code == 200:
        return True, ""
    if not code:
        # We never got an answer -- but the write may well have landed anyway, so do NOT claim it
        # failed. Telling someone it failed when it succeeded is how you get a double-move.
        return False, "Atrium didn't confirm that move in time - refresh to see where the card is."
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
                              "actor": actor, "actor_name": actor_name},
                        timeout=_WRITE_TIMEOUT)
    if code == 200:
        return True, ""
    if not code:
        return False, "Atrium didn't confirm that card in time - refresh before adding it again."
    return False, "Atrium rejected that card."


def _norm(text: str) -> str:
    """Lowercase alphanumerics only -- 'Riverdance RV' and 'riverdance-rv' both -> 'riverdancerv'."""
    return "".join(ch for ch in (text or "").lower() if ch.isalnum())


def resolve_client(clients: list, client_key: str, client_name: str = ""):
    """Find the Sentinel Client an Atrium workspace belongs to, or None.

    Order matters, and so does refusing to guess:
      1. `Client.atrium_client_id` -- the EXPLICIT link, always wins.
      2. an exact normalised-name match ('Honey Tribe' == 'honey-tribe').
      3. an UNAMBIGUOUS prefix match, so Sentinel's 'Riverdance' still picks up Atrium's
         'Riverdance RV' -- but only when exactly ONE client could be meant, and only for names
         long enough (>=5 chars) that the prefix is meaningful.
    Anything ambiguous returns None: the card still renders with Atrium's own client name, which is
    far better than silently filing one client's work under another."""
    if not clients:
        return None
    for c in clients:
        if getattr(c, "atrium_client_id", None) and c.atrium_client_id == client_key:
            return c
    targets = {_norm(client_key), _norm(client_name)} - {""}
    if not targets:
        return None
    exact = [c for c in clients if _norm(getattr(c, "name", "")) in targets]
    if len(exact) == 1:
        return exact[0]
    if exact:
        return None  # two clients with the same name -- refuse to guess
    partial = []
    for c in clients:
        cn = _norm(getattr(c, "name", ""))
        if len(cn) < 5:
            continue
        if any(t.startswith(cn) or cn.startswith(t) for t in targets if len(t) >= 5):
            partial.append(c)
    return partial[0] if len(partial) == 1 else None


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

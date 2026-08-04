"""Atrium task bridge -- Sentinel's window onto the tasks Atrium owns.

Atrium (the `platform-dash` portal) is the SOURCE OF TRUTH for client-facing tasks: each client's
work lives in that client's own workspace JSON, which is why a task typed into a client's Atrium
Progress board belongs to that client by construction. Sentinel's board is the team's cross-client
view over the same work, PLUS its own internal-only rows that clients never see.

Transport is the platform's existing server-to-server HMAC (no cookie, no new secret) --
see `atrium_bridge.py` (shared with `atrium_watcher.py`), which also uses this signing.

The BOARD LIST is best-effort and fail-SOFT: an unset secret, a missing URL, a timeout, a non-200
or a malformed body all degrade to "no Atrium tasks" so the internal board still renders Sentinel's
own rows. An Atrium outage must never blank the team's board.

Everything else -- opening a card, editing it, deleting it, commenting on it (2026-07-29, when the
board stopped saying "open it in Atrium to edit") -- reports its failure instead, because those are
EXPLICIT acts: an empty drawer or a silently-dropped edit is indistinguishable from a card that was
deleted, and that ambiguity is exactly what hid two real bugs behind the Watcher bridge's empty
state (sentinel/CLAUDE.md §5). Nothing raises; every call returns a message fit to show the user.
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

# The one message every call returns when ATRIUM says the card is gone. Constants, not prose typed
# twice, because the router turns exactly these into a 404 -- every other failure is a transport
# problem and must NOT be reported to the user as "deleted".
GONE = "That card no longer exists in Atrium."
GONE_COMMENT = "That card or comment no longer exists in Atrium."
# ...and the OTHER thing a 404 can mean. See _gone_or_missing_route.
NOT_DEPLOYED = ("Atrium doesn't have this endpoint yet - the portal (platform-dash) needs "
                "redeploying for editing to work from here.")


def _gone_or_missing_route(body: dict, message: str = GONE) -> str:
    """Read a 404 correctly. It means one of two very different things, and getting it wrong is
    exactly how the Watcher bridge burned a day (sentinel/CLAUDE.md §5):

      * Atrium answers a genuinely missing card with a JSON body `{"error": "not_found"}`.
      * Flask answers an UNKNOWN ROUTE with an HTML page, which parses to nothing.

    So a Sentinel deployed ahead of the portal must say "that endpoint isn't deployed", never
    "the client deleted that card" -- one is a deploy step, the other sends someone hunting.
    """
    return message if body.get("error") else NOT_DEPLOYED


# Sentinel status label -> Atrium stage key. Atrium deliberately adopted Sentinel's status set
# (constants.TASK_STATUSES) so the two boards speak the same language; this is the key mapping.
# For Review / Waiting for Client are gone from BOTH sides now (Atrium 2026-07-29, here 2026-07-30
# — see task_config.RETIRED_STATUSES). Keeping them here after Atrium retired them was a quiet
# lie: `for_review` still POSTed fine, but Atrium's _STAGE_ALIASES landed the card on Blocked, so
# the two boards disagreed about where the client's card was.
# 🔴 BOTH labels of the blocked column are listed, and that is not redundancy. This map is the
# fallback for a DB with no stage information at all, so it is consulted on precisely the boards
# that have not been through `rename_statuses` yet (WP 1.2) as well as the ones that have. Listing
# only the new label would strand every card on an un-migrated board; listing only the old one
# would strand every card on a fresh install.
STAGE_BY_STATUS = {
    "To Do": "todo",
    "In Progress": "in_progress",
    "Revision Needed": "revision",
    "Completed": "completed",
    "Parked": "blocked",
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
             actor: str = "", actor_name: str = "") -> tuple[str, str]:
    """Create a task in Atrium. Returns (atrium_task_id, error) -- exactly one is truthy.

    `client_facing=False` files internal work clients never see.

    🔴 Returning the ID is the whole point, and it is why this returns (str, str) rather than the
    (bool, str) every other write here uses. Atrium answers `{"ok":true,"task_id":…,"stage":…}`
    and the caller MUST store that id: without it "shared with the client" is a boolean that
    refers to nothing, which is precisely the bug this fixes (docs/TASKBOARD_REBUILD.md §1.2).
    An `ok` with no usable id is therefore a FAILURE, not a success -- publishing a card we can
    never address again would recreate the same lie one row at a time.
    """
    if not enabled():
        return "", "The Atrium bridge is not configured."
    code, body = _call("task-add", "/api/internal/task-add",
                       body={"client_key": client_key, "title": title, "stage": stage,
                             "client_facing": client_facing, "priority": priority,
                             "department": department, "due_date": due_date,
                             "actor": actor, "actor_name": actor_name},
                       timeout=_WRITE_TIMEOUT)
    if code == 200:
        task_id = str((body or {}).get("task_id") or "").strip()
        if task_id:
            return task_id, ""
        log.warning("atrium task-add returned 200 without a task_id: %r", body)
        return "", "Atrium created that card but didn't return its id - check the client's board."
    if not code:
        # No answer is not the same as "it didn't happen": the card may exist. Say so, so nobody
        # publishes twice (same rule as move_task / edit_task).
        return "", "Atrium didn't confirm that card in time - check the client's board before retrying."
    return "", (body or {}).get("error") or "Atrium rejected that card."


def fetch_task(client_key: str, task_id: str) -> tuple[dict, str]:
    """One Atrium task in FULL for the detail drawer: ({task, roster, departments, stages}, error).

    Deliberately NOT fail-soft like `fetch_tasks`. Opening a card is an explicit act: degrading to
    "nothing here" would be indistinguishable from a deleted card -- the exact ambiguity that hid
    two real bugs behind the Watcher bridge's empty state (sentinel/CLAUDE.md §5). The caller gets
    a reason it can put on screen.
    """
    if not enabled():
        return {}, "The Atrium bridge is not configured."
    code, body = _call("task-detail", "/api/internal/task",
                       params={"client": client_key, "task": task_id})
    if code == 200 and isinstance(body.get("task"), dict):
        return body, ""
    if code == 404:
        return {}, _gone_or_missing_route(body)
    if not code:
        return {}, "Couldn't reach Atrium to open that card - try again in a moment."
    log.warning("atrium task detail returned %s", code)
    return {}, "Atrium couldn't open that card (%s)." % code


def edit_task(client_key: str, task_id: str, fields: dict, actor: str = "") -> tuple[dict, str]:
    """Patch an Atrium task. Returns (envelope, error) -- the envelope is fetch_task's shape, so the
    caller can answer with the refreshed task instead of re-reading it."""
    if not enabled():
        return {}, "The Atrium bridge is not configured."
    code, body = _call("task-update", "/api/internal/task-update",
                       body={"client_key": client_key, "task_id": task_id,
                             "fields": fields, "actor": actor},
                       timeout=_WRITE_TIMEOUT)
    if code == 200 and isinstance(body.get("task"), dict):
        return body, ""
    if code == 404:
        return {}, _gone_or_missing_route(body)
    if not code:
        # Same rule as move_task: no answer is not the same as "it didn't happen".
        return {}, "Atrium didn't confirm that edit in time - refresh to see what saved."
    return {}, (body.get("error") or "Atrium rejected that edit.")


def remove_task(client_key: str, task_id: str, actor: str = "") -> tuple[bool, str]:
    """Delete an Atrium task (it soft-deletes into Atrium's Bin). Returns (ok, error_message)."""
    if not enabled():
        return False, "The Atrium bridge is not configured."
    code, body = _call("task-delete", "/api/internal/task-delete",
                       body={"client_key": client_key, "task_id": task_id, "actor": actor},
                       timeout=_WRITE_TIMEOUT)
    if code == 200:
        return True, ""
    if code == 404:
        return False, _gone_or_missing_route(body)
    if not code:
        return False, "Atrium didn't confirm that delete in time - refresh before trying again."
    return False, (body.get("error") or "Atrium rejected that delete.")


def comment_task(client_key: str, task_id: str, body_text: str, actor: str = "",
                 actor_name: str = "") -> tuple[dict, str]:
    """Post a TEAM comment on an Atrium task. Returns (comment, error).

    On a client-facing card this lands in the client's Progress thread and notifies them -- exactly
    as it would from Atrium's own console, because it is the same route underneath."""
    if not enabled():
        return {}, "The Atrium bridge is not configured."
    code, body = _call("task-comment", "/api/internal/task-comment",
                       body={"client_key": client_key, "task_id": task_id, "op": "add",
                             "body": body_text, "actor": actor, "actor_name": actor_name},
                       timeout=_WRITE_TIMEOUT)
    if code == 200 and isinstance(body.get("comment"), dict):
        return body["comment"], ""
    if code == 404:
        return {}, _gone_or_missing_route(body)
    if not code:
        return {}, "Atrium didn't confirm that comment in time - refresh before posting it again."
    return {}, (body.get("error") or "Atrium rejected that comment.")


def resolve_change_request(client_key: str, task_id: str, comment_id: str,
                           actor: str = "") -> tuple[bool, str]:
    """Mark a client's "Request changes" comment resolved (a TEAM action on both boards)."""
    if not enabled():
        return False, "The Atrium bridge is not configured."
    code, body = _call("task-comment", "/api/internal/task-comment",
                       body={"client_key": client_key, "task_id": task_id, "op": "resolve",
                             "comment_id": comment_id, "actor": actor},
                       timeout=_WRITE_TIMEOUT)
    if code == 200:
        return True, ""
    if code == 404:
        return False, _gone_or_missing_route(body, GONE_COMMENT)
    if not code:
        return False, "Atrium didn't confirm that in time - refresh to see the current state."
    return False, (body.get("error") or "Atrium rejected that.")


# Sentinel's TaskUpdateIn field -> the Atrium field it means. Only fields that mean the SAME thing
# on both boards are here; anything Sentinel has and Atrium doesn't (assignee/team ids, description)
# is simply absent, never faked into a field that looks similar.
#   * client_facing_notes IS Atrium's client_note -- both are "the note the client reads".
#   * atrium_visible IS Atrium's client_facing -- "shared with the client" from either side.
#   * the atrium_* fields exist for values only an Atrium card has (its own department vocabulary,
#     and owners stored as roster EMAILS rather than Sentinel user ids).
#
# Keys TaskUpdateIn accepts that the SENTINEL branch of the update route must DROP rather than
# setattr onto the model.
#
# 🔴 `start_date` came OFF this list on 2026-08-03: it is a real `tasks.start_date` column now (M5),
# so dropping it would silently discard the field on every Sentinel edit. `on_hold` / `hold_reason`
# stayed ON it even though Sentinel gained both columns — a hold is three coupled fields and only
# `POST /{id}/park` may set it (see schemas.TaskUpdateIn). The atrium_* keys have no Sentinel
# equivalent at all (Atrium's own department vocabulary; owners as roster emails).
ONLY_ATRIUM = ("on_hold", "hold_reason",
               "atrium_department", "atrium_lead_id", "atrium_support_ids")

FIELD_MAP = {
    "title": "title",
    "campaign": "campaign",
    "content_type": "content_type",
    "priority": "priority",
    "due_date": "due_date",
    "start_date": "start_date",
    "service_charge": "service_charge",
    "deliverable_url": "deliverable_url",
    "internal_notes": "internal_notes",
    "client_facing_notes": "client_note",
    "atrium_visible": "client_facing",
    "atrium_department": "department",
    "atrium_lead_id": "lead_id",
    "atrium_support_ids": "support_ids",
    "on_hold": "on_hold",
    "hold_reason": "hold_reason",
}


def to_atrium_fields(data: dict) -> dict:
    """Translate a validated TaskUpdateIn dict into Atrium's own field names.

    Unmappable keys are DROPPED (Atrium has no assignee/team/description), dates become plain ISO
    strings (json can't serialize `date`), and the work breakdown swaps Sentinel's `title` for
    Atrium's `text` -- the wire format is Atrium's, so the far side stores what its own console
    stores."""
    out: dict = {}
    for key, value in data.items():
        target = FIELD_MAP.get(key)
        if not target:
            continue
        if hasattr(value, "isoformat"):        # date -> "YYYY-MM-DD"
            value = value.isoformat()
        if value is None:
            value = "" if target not in ("client_facing", "on_hold") else False
        out[target] = value
    if isinstance(data.get("maintasks"), list):
        out["maintasks"] = [{
            "id": m.get("id") or "",
            "text": (m.get("title") or m.get("text") or "").strip(),
            "assignee_id": m.get("assignee_id") or "",
            "subs": [{
                "id": s.get("id") or "",
                "text": (s.get("text") or "").strip(),
                "done": bool(s.get("done")),
                "assignee_id": s.get("assignee_id") or "",
            } for s in (m.get("subs") or []) if isinstance(s, dict)],
        } for m in data["maintasks"] if isinstance(m, dict)]
    return out


def _person(name: str) -> dict | None:
    """An Atrium owner/author as the {name} object the board's avatar + labels expect."""
    name = (name or "").strip()
    return {"id": None, "name": name, "profile_pic_url": None} if name else None


def as_task_detail(envelope: dict, client: object = None) -> dict:
    """Map Atrium's full task onto the shape the detail drawer already renders (task_detail).

    Same contract as `as_board_card`: fields Sentinel has no Atrium equivalent for come back empty
    rather than faked, `source` marks where edits must be routed, and the Atrium-only values keep
    an `atrium_` prefix so nothing here is mistaken for a Sentinel column. The pickers' vocabularies
    ride along so the drawer can offer Atrium's OWN roster and departments instead of Sentinel's."""
    t = envelope.get("task") or {}
    card = as_board_card(t, client)
    card.update({
        # Atrium has no `description`; its client-facing prose is client_note (mapped below) and its
        # internal prose is internal_notes -- both already have a home on the drawer.
        "description": "",
        "campaign": t.get("campaign") or "",
        "content_type": t.get("content_type") or "",
        "service_charge": t.get("service_charge") or "",
        "service_charge_label": t.get("service_charge_label") or "",
        "account_manager_id": None,
        "account_manager": None,
        "assigned_team_name": t.get("department_label") or "",
        "checklist": [],
        "deliverable_url": t.get("deliverable_url") or "",
        "internal_notes": t.get("internal_notes") or "",
        "client_facing_notes": t.get("client_note") or "",
        "created_at": t.get("created_at") or "",
        "updated_at": t.get("updated_at") or "",
        "maintasks": [{
            "id": m.get("id") or "",
            "title": m.get("text") or "",
            "assignee_id": m.get("assignee_id") or "",
            "assignee": _person(m.get("assignee_name") or m.get("assignee_id")),
            "subs": [{
                "id": s.get("id") or "",
                "text": s.get("text") or "",
                "done": bool(s.get("done")),
                "assignee_id": s.get("assignee_id") or "",
                "assignee": _person(s.get("assignee_name") or s.get("assignee_id")),
            } for s in (m.get("subs") or [])],
        } for m in (t.get("maintasks") or [])],
        "comments": [{
            "id": c.get("id") or "",
            "author": _person(c.get("sender_name")
                              or ("Client" if c.get("sender") == "client" else "AGORA")),
            "body": c.get("body") or "",
            "attachments": [],
            "created_at": c.get("created_at") or "",
            "kind": c.get("kind") or "comment",
            "resolved": bool(c.get("resolved")),
        } for c in (t.get("comments") or [])],
        # Atrium stamps the actor as a bare email and keeps its history oldest-first; the drawer
        # shows newest-first, like Sentinel's own activity list.
        "history": [{
            "id": i,
            "actor": _person((h.get("actor") or "").split("@")[0].replace(".", " ").title()),
            "field": h.get("field") or "",
            "old_value": h.get("old") or "",
            "new_value": h.get("new") or "",
            "changed_at": h.get("at") or "",
        } for i, h in enumerate(reversed(t.get("history") or []))],
        # --- Atrium-only: the values and vocabularies a Sentinel row has no column for ----------
        "atrium_department": t.get("department") or "",
        "atrium_lead_id": t.get("lead_id") or "",
        "atrium_lead_name": t.get("lead_name") or "",
        "atrium_support_ids": list(t.get("support_ids") or []),
        "atrium_support_names": list(t.get("support_names") or []),
        "atrium_roster": envelope.get("roster") or [],
        "atrium_departments": envelope.get("departments") or [],
        "start_date": t.get("start_date") or "",
        "on_hold": bool(t.get("on_hold")),
        "hold_reason": t.get("hold_reason") or "",
        "open_changes": t.get("open_changes") or 0,
        "reporter": t.get("reporter") or "agora",
        "reporter_name": t.get("reporter_name") or "",
    })
    return card


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

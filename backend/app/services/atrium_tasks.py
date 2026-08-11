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
import threading
import time

from ..config import settings
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


# --- The board-list cache -------------------------------------------------------------------
# 🔴 `fetch_tasks` sat on the CRITICAL PATH of every board load, every Monitor load and every Coach
# digest — a blocking cross-service HTTP call, with a 10s timeout, over a connection that is built
# from scratch each time (`atrium_bridge` is stdlib urllib and pools nothing). Fail-soft protected us
# from an Atrium OUTAGE; it did nothing about a merely SLOW Atrium, whose latency was added directly
# to Sentinel's own. A board 15 seconds stale is not a new compromise — the SSE reload already
# debounces bursts by 400ms and nobody was watching Atrium in real time through this window anyway.
#
# THREE rules hold this cache honest:
#   1. **Only a SUCCESS is cached.** Caching the fail-soft `[]` would blank every client card on the
#      board for the whole TTL because of one blip — turning a momentary glitch into a visible outage.
#   2. **Every WRITE through this module invalidates it** (`_invalidate`). Otherwise editing a client
#      card and landing back on the board would show the pre-edit copy, which reads as a lost save.
#   3. **Keyed by `client_key`**, since the one-client call returns a subset.
_cache_lock = threading.Lock()
_cache: dict[str, tuple[float, list[dict]]] = {}


def _invalidate() -> None:
    """Drop the board-list cache. Called after every write, so our own edits are never hidden."""
    with _cache_lock:
        _cache.clear()


def fetch_tasks(client_key: str = "") -> list[dict]:
    """Every Atrium task (optionally one client's). [] on any failure -- never raises.

    Cached for `settings.atrium_cache_seconds` (0 disables). See the block comment above.
    """
    ttl = max(0, settings.atrium_cache_seconds)
    if ttl:
        with _cache_lock:
            hit = _cache.get(client_key)
            if hit and (time.monotonic() - hit[0]) < ttl:
                return hit[1]

    code, body = _call("tasks", "/api/internal/tasks",
                       params={"client": client_key} if client_key else None)
    if code != 200:
        if code:
            log.warning("atrium task fetch returned %s", code)
        return []                                   # NOT cached — see rule 1 above
    tasks = body.get("tasks")
    if not isinstance(tasks, list):
        return []                                   # NOT cached either: a shape we don't understand
    if ttl:
        with _cache_lock:
            _cache[client_key] = (time.monotonic(), tasks)
    return tasks


def fetch_clients() -> tuple[list[dict], str]:
    """Atrium's client registry: `([{key, name, contact_email}], error)`.

    🔴 Returns an ERROR rather than degrading to `[]`, unlike every other read in this module — and
    that asymmetry is the whole point. The board list is fail-soft because an Atrium outage must not
    blank it; but the client MIRROR deactivates any Sentinel client missing from this list, so an
    empty answer is indistinguishable from "Atrium has no clients" and would deactivate **every
    client in the estate**. The caller must be able to tell "nothing came back" from "nothing exists"
    and refuse to sync. Exactly one of the two values is ever truthy.
    """
    if not enabled():
        return [], "The Atrium bridge is not configured."
    code, body = _call("clients", "/api/internal/clients")
    if code != 200:
        if code:
            log.warning("atrium client fetch returned %s", code)
        return [], (_gone_or_missing_route(body, "Atrium did not return its client list.")
                    if code == 404 else
                    "Atrium didn't answer the client list — nothing was changed.")
    rows = body.get("clients")
    if not isinstance(rows, list):
        return [], "Atrium's client list came back in a shape we don't understand."
    return rows, ""


def move_task(client_key: str, task_id: str, stage: str, actor: str = "") -> tuple[bool, str]:
    """Move an Atrium task. Returns (ok, error_message) -- the error is safe to show the user."""
    if not enabled():
        return False, "The Atrium bridge is not configured."
    code, body = _call("task-move", "/api/internal/task-move",
                       body={"client_key": client_key, "task_id": task_id,
                             "stage": stage, "actor": actor},
                       timeout=_WRITE_TIMEOUT)
    # Any write may have landed, even one Atrium never confirmed — so the board-list cache
    # goes regardless of the outcome. Hiding our own edit behind a stale read reads as a lost save.
    _invalidate()
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
    # Any write may have landed, even one Atrium never confirmed — so the board-list cache
    # goes regardless of the outcome. Hiding our own edit behind a stale read reads as a lost save.
    _invalidate()
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
    # Any write may have landed, even one Atrium never confirmed — so the board-list cache
    # goes regardless of the outcome. Hiding our own edit behind a stale read reads as a lost save.
    _invalidate()
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
    # Any write may have landed, even one Atrium never confirmed — so the board-list cache
    # goes regardless of the outcome. Hiding our own edit behind a stale read reads as a lost save.
    _invalidate()
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
    # Any write may have landed, even one Atrium never confirmed — so the board-list cache
    # goes regardless of the outcome. Hiding our own edit behind a stale read reads as a lost save.
    _invalidate()
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
    # Any write may have landed, even one Atrium never confirmed — so the board-list cache
    # goes regardless of the outcome. Hiding our own edit behind a stale read reads as a lost save.
    _invalidate()
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
    """An Atrium owner/author as the {name} object the board's avatar + labels expect.

    🔴 `id` is always None, and that is load-bearing: an Atrium owner is a roster EMAIL, not a
    Sentinel user, so nothing may join on it or treat this as an assignment Sentinel can act on.
    `S.avatar` needs only `name` (it falls back to initials), which is why a name with no id renders
    perfectly well.
    """
    name = (name or "").strip()
    return {"id": None, "name": name, "profile_pic_url": None} if name else None


def support_pairs(t: dict) -> list[tuple[str, str]]:
    """A client card's support as `(roster_id, display_name)`, in Atrium's own order.

    🔴 ONE derivation, called by BOTH `as_board_card` and the router that resolves these people to
    Sentinel users. Two copies of this list would drift the moment Atrium sent `support_ids` and
    `support_names` of different lengths — and a drifted list does not fail loudly, it pairs one
    person's name with another person's face.

    Atrium sends the two fields in parallel, but neither is guaranteed: an older payload carries ids
    only (hence the `owner_label` fallback, which turns an email into something printable), and a
    newer one can carry a name for somebody whose id it dropped. Index alignment is the only
    relationship the payload actually asserts, so that is the one used, and an entry survives if
    EITHER half is present.
    """
    ids = [str(s).strip() for s in (t.get("support_ids") or [])]
    names = [str(n).strip() for n in (t.get("support_names") or [])]
    pairs: list[tuple[str, str]] = []
    for i in range(max(len(ids), len(names))):
        sid = ids[i] if i < len(ids) else ""
        name = (names[i] if i < len(names) else "") or owner_label(sid)
        if sid or name:
            pairs.append((sid, name))
    return pairs


def owner_label(person_id: str) -> str:
    """A roster EMAIL rendered as a display name — the fallback when Atrium sent no resolved name.

    Atrium's LIST payload (`_internal_task_view`) carries `lead_id`/`support_ids` but no names; only
    its DETAIL payload resolves them against the roster. That asymmetry is why a client card whose
    Lead was set in Atrium rendered **"Unassigned"** on the board while the drawer for the same card
    said "Lead: Charles" — the board simply had no name to show and printed the empty state.

    So: prefer whatever name Atrium resolved, and derive one from the email's local part when it
    didn't. `charles.reyes@agora.ph` → "Charles Reyes". Same derivation the history mapper already
    uses for `actor`. It is a DISPLAY fallback, never an identity — see `_person`.
    """
    local = (person_id or "").split("@")[0].strip()
    if not local:
        return ""
    return local.replace(".", " ").replace("_", " ").replace("-", " ").title()


def as_task_detail(envelope: dict, client: object = None, owner: dict | None = None,
                   support: list[dict | None] | None = None) -> dict:
    """Map Atrium's full task onto the shape the detail drawer already renders (task_detail).

    Same contract as `as_board_card`: fields Sentinel has no Atrium equivalent for come back empty
    rather than faked, `source` marks where edits must be routed, and the Atrium-only values keep
    an `atrium_` prefix so nothing here is mistaken for a Sentinel column. The pickers' vocabularies
    ride along so the drawer can offer Atrium's OWN roster and departments instead of Sentinel's."""
    t = envelope.get("task") or {}
    card = as_board_card(t, client, owner, support=support)
    card.update({
        # Atrium has no `description`; its client-facing prose is client_note (mapped below) and its
        # internal prose is internal_notes -- both already have a home on the drawer.
        "description": "",
        # 🔴 `campaign` is NOT re-mapped here — `as_board_card` above already carries it (2026-08-11).
        # Re-deriving a field this function's own base already sets is how the card and the drawer
        # ended up disagreeing about an Atrium card's owner; the same rule now covers this field.
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
        # 🔴 `atrium_department` / `atrium_lead_*` / `atrium_support_*` are NOT re-mapped here — they
        # come from `as_board_card` above, which is now the single place they are derived. They used
        # to be set in both, and the two disagreed: the card hardcoded no owner while this branch
        # read the resolved name, which is exactly how a card with a Lead showed "Unassigned" on the
        # board and "Lead: Charles" in its own drawer. One derivation, both surfaces.
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


def as_board_card(t: dict, client: object = None, owner: dict | None = None,
                  viewer_id: int | None = None,
                  support: list[dict | None] | None = None) -> dict:
    """Map an Atrium task onto the shape the Kanban board already renders (serializers.task_card).

    `client` is the matching Sentinel Client row (resolved via Client.atrium_client_id) when there
    is one, so the board's client filter and client name work on Atrium cards exactly as they do on
    Sentinel's own. Internal-only Sentinel concepts it has no equivalent for (team ids, the creator
    tag) come back empty rather than faked, and `source` marks the card so the UI can badge it
    and route edits back to Atrium.

    🔴 **The owner reaches the card, and is the real Sentinel person whenever we can prove it
    (2026-08-05).** `assigned_to_id` and `assignee` were both hardcoded `None`, so a client card with
    a Lead set in Atrium rendered **"Unassigned"** on the board while its own drawer said
    "Lead: Charles". Two separate causes: Atrium's list payload sends `lead_id` — a roster *email* —
    and only its DETAIL payload resolved names, so the board had nothing to print; and "absent, never
    faked" was applied to the wrong field. Not inventing a Sentinel **identity** is right; hiding the
    **name** just made the board lie about who holds client work.

    Three outcomes, in falling order of confidence. `owner` is a `user_public` dict resolved by the
    CALLER through `services/atrium_identity` — this module never touches the DB:

    | `owner` | `assigned_to_id` | `assignee` | What the user sees |
    |---|---|---|---|
    | resolved | that user's id | the Sentinel user | Their **By Employee** lane, their PHOTO, counted on the Monitor |
    | unresolved lead | `None` | id-less `{name}` | Named on the card, initials avatar, no lane |
    | no lead at all | `None` | `None` | Honestly "Unassigned" |

    `owner_label` supplies the middle row's name from the email, which is what made the board stop
    saying "Unassigned" even before Atrium's side shipped resolved names.

    🔴 **`mine` and `on_hold` reach the card too (2026-08-06)** — both were simply missing, and a
    missing key is falsy, so both read on the board as a confident "no":

    * **`mine`** is the ONE definition of "is this work on me" (AGENTS.md §5,
      `task_perms.is_assigned` shipped as `mine`). Client cards had no such key, so the board's
      **My work** button dropped every one of them. That was correct while an Atrium owner was only
      ever a roster email — and wrong from the day `services/atrium_identity` began resolving that
      email to a Sentinel user, because from then on the SAME resolved owner put the card in that
      person's **By Employee** lane, counted it toward them on the **Monitor**, and printed their
      photo on it. Three surfaces said "yours", one said "not yours". It derives from `owner` for
      exactly that reason: one resolution, four answers. `viewer_id=None` omits the key entirely
      (absent, never a hardcoded ``False``) — the same contract `serializers.task_card` follows when
      no viewer is passed.
      There is deliberately no `my_slots`: an Atrium card's breakdown has no Sentinel step owners to
      count, and faking a 0 would make the "N steps on you" pill lie.
    * **`on_hold`** is what the board renders the "⏸ parked" pill from. `as_task_detail` has always
      mapped it, so a client card paused in Atrium said "On hold" in its own drawer while the card
      on the board looked perfectly live.
    """
    lead_name = (t.get("lead_name") or "").strip() or owner_label(t.get("lead_id") or "")
    # 🔴 `owner` is the SENTINEL user this card's Atrium lead resolves to (`services/atrium_identity`),
    # already serialized by `user_public` — so it carries the real id AND `profile_pic_url`. When it is
    # present the card is owned by an actual staff member and says so with their photo; when it is not
    # (a lead with no Sentinel account, or an ambiguous match we refuse to guess at) we fall back to
    # the id-less name below. That fallback is why the board still names somebody even before this
    # resolution exists — see `owner_label`.
    owner_name = (owner or {}).get("name")
    if owner_name:
        lead_name = owner_name
    # 🔴 SUPPORT IS RESOLVED THE SAME WAY THE LEAD IS (2026-08-06). Only the lead went through
    # `services/atrium_identity`, so on the SAME card the lead wore their photo and every supporter
    # rendered grey initials — Paulo has a photo in Sentinel, and a client card he supports showed
    # him as "P". That is the 2026-08-05 lead bug surviving in the half nobody re-read: an Atrium
    # supporter is a roster email, we already know how to turn one of those into the Sentinel user
    # who is that person, and we simply weren't doing it here.
    # `support` is that resolution, done by the ROUTER (this module never touches the DB) and
    # positionally aligned to `support_pairs`. An entry that did not resolve falls back to the
    # id-less `_person`, exactly like an unresolved lead: named, never faked.
    pairs = support_pairs(t)
    support_names = [name for _, name in pairs]
    resolved = list(support or [])
    support_people = [p for p in (
        (resolved[i] if i < len(resolved) else None) or _person(name)
        for i, name in enumerate(support_names)) if p]
    # "Is this work on me?" — from the RESOLVED owner, so this card agrees with its own By Employee
    # lane and its own Monitor row. Omitted (not False) when the caller passed no viewer.
    mine: dict = {}
    if viewer_id is not None:
        mine = {"mine": bool(owner and owner.get("id") == viewer_id)}
    return {
        **mine,
        "id": ATRIUM_ID_PREFIX + (t.get("atrium_id") or ""),
        "title": t.get("title") or "",
        "status": t.get("status") or "To Do",
        "priority": t.get("priority") or "Medium",
        "due_date": t.get("due_date") or None,
        "labels": t.get("labels") or [],
        "client_id": getattr(client, "id", None),
        "client_name": (getattr(client, "name", None)
                        or t.get("client_name") or t.get("client_key") or ""),
        # 🔴 The grouping field, on BOTH kinds of card (2026-08-11). `serializers.task_card` publishes
        # it for a Sentinel row, so a client card has to publish it here or the board's campaign filter
        # and its search would silently answer for only half the work on screen — the same
        # one-surface-disagrees split `mine` was missing until 2026-08-06 (AGENTS.md §5). Mapped here
        # and NOT in `as_task_detail`, which builds on this function.
        "campaign": t.get("campaign") or "",
        # 🔴 Set ONLY when the lead resolved to a real Sentinel user. That is what puts the card in
        # that person's **By Employee** lane and stops the board calling owned client work
        # "Unassigned" — grouping there is keyed on this field. It stays None for an unresolved lead,
        # so nothing is ever joined to an owner we had to guess at.
        "assigned_to_id": (owner or {}).get("id"),
        # The resolved Sentinel user (id + name + `profile_pic_url` — this is what makes the PHOTO
        # appear) or, failing that, an id-less name the avatar renders as initials.
        "assignee": owner or _person(lead_name),
        "assigned_team_id": None,
        "created_by_id": None,
        "created_by": None,
        # 🔴 An Atrium card can NEVER be classified planned/added: that answer is derived from the
        # SENTINEL creator's authority to plan (services/task_origin), and this card was raised in
        # another system by somebody who is a roster email here. `None` is the same "unknown" a
        # pre-column Sentinel row reports, so one renderer prints "—" for both.
        # Present-and-None rather than absent on purpose: a MISSING key is falsy, which is exactly how
        # `mine` silently answered "not yours" for every client card until 2026-08-06 (AGENTS.md §5).
        "origin": None,
        # Atrium's own ownership vocabulary, `atrium_`-prefixed so nothing mistakes it for a Sentinel
        # column. On the CARD as well as the drawer now: the drawer's "Lead" field reads these, and
        # the board needs the same values to stop rendering owned client work as "Unassigned".
        "atrium_lead_id": t.get("lead_id") or "",
        "atrium_lead_name": lead_name,
        "atrium_support_ids": list(t.get("support_ids") or []),
        "atrium_support_names": support_names,
        # The same field a Sentinel row publishes (`serializers.task_card`), so ONE renderer draws
        # the faces on both kinds of card. Entries carry a real Sentinel id + `profile_pic_url` when
        # the person resolved and are id-less names when they did not.
        # 🔴 `support_ids` is deliberately NOT set from these. That field is Sentinel's own
        # supporter list: By Employee groups lanes by it, and `mine`/"My work" is derived from the
        # resolved LEAD alone. Filling it here would silently move client cards into supporters'
        # lanes and onto their My work, while the Monitor (`task_analytics.atrium_workload`, which
        # counts a client card toward its lead) went on disagreeing — the exact three-surfaces-say-
        # yours-and-one-says-no split this resolver was written to end. Widening support to those
        # surfaces is a real decision; make it deliberately, everywhere at once, not as a side
        # effect of showing a photo.
        "support": support_people,
        "atrium_department": t.get("department") or "",
        "comment_count": t.get("comment_count") or 0,
        "attachment_count": 0,
        "checklist_total": t.get("checklist_total") or 0,
        "checklist_done": t.get("checklist_done") or 0,
        # Atrium's client_facing IS the Atrium-visibility flag from Sentinel's point of view.
        "atrium_visible": bool(t.get("client_facing")),
        # The board's "⏸ parked" pill reads this. Absent until 2026-08-06, so a client card paused in
        # Atrium looked live on the board and said "On hold" the moment you opened it.
        "on_hold": bool(t.get("on_hold")),
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

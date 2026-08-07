"""Two-level work breakdown helpers: a task holds main tasks, each with its own sub-tasks.

Shape (stored in Task.maintasks_json):
    [{"id","title","assignee_id",
      "subs":[{"id","text","done","assignee_id"}, ...]}, ...]

`normalize` is the single sanitizer used on both read (serializer) and write (update_task): it fills
missing ids, coerces types, and — for a task created before this feature — migrates a legacy flat
`checklist_json` into one "Checklist" main task so nothing is lost.
"""
from __future__ import annotations

import json
import uuid


def new_id(prefix: str = "mt") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _loads(raw, default):
    try:
        v = json.loads(raw) if isinstance(raw, str) else raw
        return v if isinstance(v, list) else default
    except (TypeError, ValueError):
        return default


def _as_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def normalize(maintasks_raw, checklist_raw=None) -> list[dict]:
    """Clean, id-complete main tasks. Falls back to migrating a legacy flat checklist."""
    mts = _loads(maintasks_raw, [])
    if not mts:
        cl = _loads(checklist_raw, [])
        if cl:
            mts = [{"title": "Checklist", "subs": [
                {"text": c.get("text", ""), "done": bool(c.get("done"))}
                for c in cl if isinstance(c, dict)]}]

    clean = []
    for m in mts:
        if not isinstance(m, dict):
            continue
        subs = []
        for s in (m.get("subs") or []):
            if not isinstance(s, dict):
                continue
            text = str(s.get("text", "")).strip()
            if not text:
                continue
            subs.append({
                "id": s.get("id") or new_id("st"),
                "text": text,
                "done": bool(s.get("done")),
                "assignee_id": _as_int(s.get("assignee_id")),
            })
        clean.append({
            "id": m.get("id") or new_id("mt"),
            "title": (str(m.get("title", "")).strip() or "Untitled"),
            "assignee_id": _as_int(m.get("assignee_id")),
            "subs": subs,
        })
    return clean


_MEMO_ATTR = "_mt_normalized"


def normalized(task) -> list[dict]:
    """`normalize` for a Task ROW, memoized on the instance. Use this whenever the input is a task.

    🔴 PERFORMANCE, and it is not a micro-optimisation. Answering "is this work on me?" and "how far
    along is it?" both go through `normalize`, so ONE board card parses this JSON three times —
    `task_perms.is_assigned` (which is also what filtered the list), then `my_slot_count` and
    `sub_stats` inside `serializers.task_card`. Measured 2026-08-07: **2,400 `normalize()` calls to
    render 801 cards**, each one re-parsing the JSON and rebuilding every dict in it.

    The memo is keyed on the IDENTITY of the two raw strings, not their value. Writing
    `maintasks_json` always rebinds the attribute to a fresh `str`, so an edited row misses the memo
    and re-normalizes — which is what makes this safe to hold across a whole request. Value equality
    would be wrong the other way round: it would be slower (comparing long JSON) for no extra safety.

    It also makes the result STABLER than calling `normalize` three times did: `normalize` mints a
    fresh `uuid4` id for any step that arrives without one, so the three calls behind a single card
    each invented different ids. Nothing read them across calls, so nothing was broken — but one
    answer per row is the shape everything here assumes.
    """
    raw = getattr(task, "maintasks_json", "[]")
    legacy = getattr(task, "checklist_json", None)
    memo = getattr(task, _MEMO_ATTR, None)
    if memo is not None and memo[0] is raw and memo[1] is legacy:
        return memo[2]
    out = normalize(raw, legacy)
    try:
        object.__setattr__(task, _MEMO_ATTR, (raw, legacy, out))
    except (AttributeError, TypeError):      # a mapped stub / slotted object — just don't cache
        pass
    return out


def sub_stats(maintasks: list[dict]) -> tuple[int, int]:
    """(done, total) counted across every sub-task of every main task."""
    total = done = 0
    for m in maintasks:
        for s in m.get("subs", []):
            total += 1
            if s.get("done"):
                done += 1
    return done, total


def _slot_key(out: dict, key: str) -> str:
    """`key`, suffixed if that slot is already taken.

    Ids are supposed to be unique, but they arrive from a client and nothing stops a caller sending
    the same step id twice. Two slots must never collapse into one: last-write-wins would let a
    duplicated step hide an ownership change from the diff below (send the victim's step twice, one
    copy unowned, and the map still reads "victim" — while the victim now holds two steps).
    """
    if key not in out:
        return key
    i = 2
    while f"{key}#{i}" in out:
        i += 1
    return f"{key}#{i}"


def slots(maintasks: list[dict]) -> dict[str, dict]:
    """Every phase and step as an addressable SLOT: `{key: {"kind","owner","done","text"}}`.

    🔴 This is a SECURITY input, not a convenience. Naming somebody on a step puts the card on their
    board — `task_perms.is_assigned` counts step owners for visibility — so writing this field IS
    delegation, and `update_task` has to hold it to the same `can_reassign` rule as
    `assigned_to_id`. Before 2026-08-03 it did not: `maintasks` went through its own branch with no
    assignee check at all, so an employee who could not reassign a task could still drop any card
    onto any colleague's board by naming them on a sub-task (docs/TASKBOARD_REBUILD.md §2.4e).

    🔴 And a per-person SET was not enough either — that was the SECOND version of the same hole,
    live until 2026-08-05. The guard compared `{owner ids} before` with `{owner ids} after`, so any
    edit that left the set intact passed: an employee could move a colleague's ownership from one
    step to another, pile them onto five more steps, or swap two colleagues' steps, all answering
    200. A set answers "who is on this card"; delegation is a question about **which work each
    person holds**, so the diff has to be per slot. Steps are keyed by their OWN id (not nested
    under the phase) so re-titling or re-nesting a phase is not mistaken for a handover.
    """
    out: dict[str, dict] = {}
    for m in maintasks:
        mid = str(m.get("id") or "")
        out[_slot_key(out, f"m:{mid}")] = {
            "kind": "phase", "owner": _as_int(m.get("assignee_id")) or None,
            "done": None, "text": str(m.get("title") or ""),
        }
        for s in (m.get("subs") or []):
            out[_slot_key(out, f"s:{s.get('id') or ''}")] = {
                "kind": "step", "owner": _as_int(s.get("assignee_id")) or None,
                "done": bool(s.get("done")), "text": str(s.get("text") or ""),
            }
    return out


def foreign_owner_changes(before: dict[str, dict], after: dict[str, dict],
                          actor_id: int) -> set[int]:
    """Ids of OTHER people whose hold on a slot moved between two breakdowns — the delegation test.

    Empty means every ownership change in this edit involved nobody but `actor_id`, i.e. it was
    self-assignment (picking up an unowned step, dropping your own), which every role may do.
    Anything else — giving work away, taking it off someone, or rearranging what somebody else
    holds — puts an id in here and needs `can_reassign`.
    """
    others: set[int] = set()
    for key in set(before) | set(after):
        b = (before.get(key) or {}).get("owner")
        a = (after.get(key) or {}).get("owner")
        if b == a:
            continue
        others |= {v for v in (b, a) if v and v != actor_id}
    return others


def tick_changes(before: dict[str, dict], after: dict[str, dict]) -> list[dict]:
    """Steps whose `done` flag moved: `[{"owner","text","done"}]`, owner read from the BEFORE state.

    The owner comes from before-the-edit on purpose. Otherwise ticking a colleague's step and
    clearing its owner in the same PATCH would present itself as "an unowned step was ticked" — the
    owner change is refused separately, but the two guards must not be able to launder each other.
    """
    out: list[dict] = []
    for key in set(before) | set(after):
        b, a = before.get(key) or {}, after.get(key) or {}
        if b.get("kind") != "step" and a.get("kind") != "step":
            continue
        if b.get("done") is None or a.get("done") is None:
            continue                       # a step that was added or deleted, not ticked
        if b["done"] == a["done"]:
            continue
        out.append({"owner": b.get("owner"), "text": a.get("text") or b.get("text") or "",
                    "done": a["done"]})
    return out


def dumps(maintasks: list[dict]) -> str:
    return json.dumps(maintasks)

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


def sub_stats(maintasks: list[dict]) -> tuple[int, int]:
    """(done, total) counted across every sub-task of every main task."""
    total = done = 0
    for m in maintasks:
        for s in m.get("subs", []):
            total += 1
            if s.get("done"):
                done += 1
    return done, total


def dumps(maintasks: list[dict]) -> str:
    return json.dumps(maintasks)

"""DB-backed board vocabulary — statuses, labels, priorities — with colours.

The single place the router, serializers, and /api/vocab consult for the configurable task
vocabulary. Reads `TaskVocabItem`; if the table is empty (before the one-time seed) it falls back
to the `constants.py` defaults, so nothing ever breaks. `SEED` + the DEFAULT_* maps are also what
`main._seed_config` writes into the DB on first boot.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..constants import PRIORITIES, TASK_LABELS, TASK_STATUSES
from ..models import TaskVocabItem

DEFAULT_STATUS_COLORS = {
    "To Do": "#6B7280", "In Progress": "#3B82F6", "For Review": "#9484FB",
    "Waiting for Client": "#F59E0B", "Revision Needed": "#F97316",
    "Completed": "#54B948", "Blocked": "#EF4444",
}
DEFAULT_LABEL_COLORS = {"Design": "#EC4899", "Copy": "#8B5CF6", "Ads": "#F97316", "SEO": "#06B6D4", "Dev": "#3B82F6"}
DEFAULT_PRIORITY_COLORS = {"Urgent": "#EF4444", "Medium": "#F59E0B", "Low": "#54B948"}

_DEFAULT_COLORS = {"status": DEFAULT_STATUS_COLORS, "label": DEFAULT_LABEL_COLORS, "priority": DEFAULT_PRIORITY_COLORS}
_FALLBACK_NAMES = {"status": TASK_STATUSES, "label": TASK_LABELS, "priority": PRIORITIES}
KINDS = ("status", "label", "priority")

# What main._seed_config writes on first boot: (name, color) per kind, in the constants' order.
SEED = {kind: [(n, _DEFAULT_COLORS[kind].get(n)) for n in _FALLBACK_NAMES[kind]] for kind in KINDS}


def _rows(db: Session, kind: str) -> list[TaskVocabItem]:
    return db.execute(
        select(TaskVocabItem)
        .where(TaskVocabItem.kind == kind, TaskVocabItem.is_active.is_(True))
        .order_by(TaskVocabItem.sort_order, TaskVocabItem.id)
    ).scalars().all()


def names(db: Session, kind: str) -> list[str]:
    rows = _rows(db, kind)
    return [r.name for r in rows] if rows else list(_FALLBACK_NAMES[kind])


def colors(db: Session, kind: str) -> dict[str, str]:
    rows = _rows(db, kind)
    if rows:
        return {r.name: r.color for r in rows if r.color}
    return dict(_DEFAULT_COLORS[kind])


def statuses(db: Session) -> list[str]:
    return names(db, "status")


def labels(db: Session) -> list[str]:
    return names(db, "label")


def priorities(db: Session) -> list[str]:
    return names(db, "priority")

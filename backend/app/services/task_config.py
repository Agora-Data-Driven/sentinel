"""DB-backed board vocabulary — statuses, labels, priorities — with colours.

The single place the router, serializers, and /api/vocab consult for the configurable task
vocabulary. Reads `TaskVocabItem`; if the table is empty (before the one-time seed) it falls back
to the `constants.py` defaults, so nothing ever breaks. `SEED` + the DEFAULT_* maps are also what
`main._seed_config` writes into the DB on first boot.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..constants import PRIORITIES, TASK_BLOCKED, TASK_LABELS, TASK_STATUSES
from ..models import Task, TaskVocabItem

# --- The status key/stage table (decision D13) -------------------------------------------------
# A status has THREE facets and only one of them is safe to key anything off:
#   name  — the LABEL. Renameable in Manage, cascaded onto every task row. Never key off it.
#   key   — the stable slug. Minted once, never changed.
#   stage — the Atrium stage the status projects onto. The bridge speaks stages, not labels.
# `atrium_tasks.STAGE_BY_STATUS` is a label-keyed literal and stays only as the legacy fallback for
# a DB seeded before `task_vocab.stage` existed.
ATRIUM_STAGES = ("todo", "in_progress", "revision", "blocked", "completed")

# (name, key, stage) for the shipped five — what `main._seed_config` writes on a fresh DB and what
# `_backfill_status_meta` heals an older one with.
STATUS_SEED = (
    ("To Do", "todo", "todo"),
    ("In Progress", "in_progress", "in_progress"),
    ("Revision Needed", "revision", "revision"),
    ("Completed", "completed", "completed"),
    ("Blocked", "blocked", "blocked"),
)

DEFAULT_STATUS_COLORS = {
    "To Do": "#6B7280", "In Progress": "#3B82F6", "Revision Needed": "#F97316",
    "Completed": "#54B948", "Blocked": "#EF4444",
}
# One colour per DERIVED label (decision D14). The old hand-picked set
# (Design/Copy/Ads/SEO/Dev) went with the vocabulary it coloured — see constants.TASK_DEPT_LABEL.
# Keys must stay in step with `constants.TASK_LABELS`, which is derived from that same mapping.
DEFAULT_LABEL_COLORS = {"Paid Media": "#F97316", "Organic": "#54B948", "Website": "#3B82F6"}
DEFAULT_PRIORITY_COLORS = {"Urgent": "#EF4444", "Medium": "#F59E0B", "Low": "#54B948"}

_DEFAULT_COLORS = {"status": DEFAULT_STATUS_COLORS, "label": DEFAULT_LABEL_COLORS, "priority": DEFAULT_PRIORITY_COLORS}
_FALLBACK_NAMES = {"status": TASK_STATUSES, "label": TASK_LABELS, "priority": PRIORITIES}
KINDS = ("status", "label", "priority")

# What main._seed_config writes on first boot: (name, color) per kind, in the constants' order.
SEED = {kind: [(n, _DEFAULT_COLORS[kind].get(n)) for n in _FALLBACK_NAMES[kind]] for kind in KINDS}


def reconcile_labels(db: Session) -> dict:
    """Bring the label vocabulary AND every task's label in line with the department (D14).

    Runs on every boot, not only on a fresh DB, because `_seed_config` seeds an EMPTY table and the
    boards that matter are the ones already carrying the retired vocabulary. Idempotent: on a
    reconciled board it reads and writes nothing.

    Three parts:
      1. Retire any active label row the mapping no longer produces (Design/Copy/Ads/SEO/Dev).
         Deactivated, never deleted — the rows are referenced by old history entries.
      2. Add any derived label that is missing, with its colour.
      3. Recompute `labels_json` on every task from its team. A label is DERIVED, so a stored one
         that disagrees is simply stale; leaving it would keep a retired vocabulary on the board
         forever, and the two boards would go on disagreeing — the exact drift D14 exists to end.

    🔴 Part 3 is a WRITE over the tasks table. It is safe precisely because the value is a pure
    function of `assigned_team_id`: re-running it can only ever produce the same answer, and no
    human input is being discarded (nobody can pick a label any more).
    """
    import json as _json

    from ..constants import label_for_department
    from ..models import Task, Team

    wanted = list(_FALLBACK_NAMES["label"])
    out = {"retired": 0, "added": 0, "relabelled": 0}

    existing = db.execute(select(TaskVocabItem).where(TaskVocabItem.kind == "label")).scalars().all()
    by_name = {r.name: r for r in existing}
    for row in existing:
        if row.name not in wanted and row.is_active:
            row.is_active = False
            out["retired"] += 1
    for i, name in enumerate(wanted):
        row = by_name.get(name)
        if row is None:
            db.add(TaskVocabItem(kind="label", name=name,
                                 color=_DEFAULT_COLORS["label"].get(name), sort_order=i))
            out["added"] += 1
        elif not row.is_active:
            row.is_active = True          # heals a board where someone deactivated a derived label

    team_name = {t.id: t.name for t in db.execute(select(Team)).scalars().all()}
    for task in db.execute(select(Task)).scalars().all():
        lbl = label_for_department(team_name.get(task.assigned_team_id))
        want = [lbl] if lbl else []
        try:
            have = _json.loads(task.labels_json or "[]")
        except (ValueError, TypeError):
            have = []
        if have != want:
            task.labels_json = _json.dumps(want)
            out["relabelled"] += 1

    if any(out.values()):
        db.commit()
    return out


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


def slugify(name: str) -> str:
    """A stable key from a label. Only ever called when MINTING a key, never to look one up —
    re-deriving a key from a renamed label is exactly the bug this column exists to prevent."""
    import re

    return re.sub(r"[^a-z0-9]+", "_", (name or "").strip().lower()).strip("_") or "status"


def _status_rows(db: Session) -> list[TaskVocabItem]:
    """Every status row, in BOARD ORDER.

    🔴 The ordering is load-bearing, not cosmetic. Several Sentinel statuses may legitimately share
    one Atrium stage (Atrium has exactly five; this board can have any number of columns folding
    onto them), and `status_for_stage` answers "which column IS the blocked one?" — the target Park
    moves work into, and the target the boot-time retirement sweep files stranded cards under.
    Unordered, that answer was whatever the DB happened to return first, so it could differ between
    two deploys of the same data. Left-most column wins now, which is the one a human would point at.
    """
    return db.execute(
        select(TaskVocabItem)
        .where(TaskVocabItem.kind == "status")
        .order_by(TaskVocabItem.sort_order, TaskVocabItem.id)
    ).scalars().all()


def stage_for(db: Session, status_name: str) -> str:
    """The Atrium stage a status projects onto. '' when it has none (so the caller can refuse).

    Resolution order — DB first, so a RENAMED status keeps working:
      1. the vocab row's own `stage`;
      2. the legacy label-keyed literal, for a DB seeded before the column existed.
    """
    for r in _status_rows(db):
        if r.name == status_name:
            if r.stage:
                return r.stage
            break
    from .atrium_tasks import STAGE_BY_STATUS      # legacy fallback only

    return STAGE_BY_STATUS.get(status_name, "")


def status_for_stage(db: Session, stage: str) -> str:
    """The CURRENT label of the status carrying this stage — the inverse of `stage_for`.

    This is what lets code refer to "the blocked column" without naming it. Renaming Blocked to
    Parked then changes one label and nothing else; hardcoding `constants.TASK_BLOCKED` instead is
    how a boot-time sweep moves live cards onto a status that has no column (AGENTS.md §5).
    """
    rows = _status_rows(db)
    active = [r for r in rows if r.is_active and r.stage == stage]
    if active:
        return active[0].name
    # 🔴 The legacy literal map is ONLY for a DB that has no stage information at all. Once any
    # status carries a stage, "no status carries THIS one" is the true answer and must be returned
    # as such: naming a label the board no longer has a column for is how cards vanish off it with
    # no error (AGENTS.md §5). `park` refuses on '' rather than filing work into a phantom column.
    if any(r.stage for r in rows):
        return ""
    from .atrium_tasks import STAGE_BY_STATUS

    live = {r.name for r in rows if r.is_active} or set(_FALLBACK_NAMES["status"])
    for label, st in STAGE_BY_STATUS.items():
        if st == stage and label in live:
            return label
    return ""


def is_completed(db: Session, status_name: str) -> bool:
    """Does this status mean the work is DONE? Answered by its stage, never by its label.

    Everything that used to compare against `constants.TASK_COMPLETED` goes through here: the
    Monitor rollup, the completion stamp, and the review gate. Renaming Completed to "Shipped" then
    changes one label in Manage and nothing else — and a SECOND done-column (say "Delivered", also
    stage `completed`) is counted correctly the day someone adds it.
    """
    return stage_for(db, status_name) == "completed"


def status_meta(db: Session) -> list[dict]:
    """name / key / stage / colour per status — what /api/vocab hands the frontend."""
    rows = [r for r in _status_rows(db) if r.is_active]
    rows.sort(key=lambda r: (r.sort_order, r.id))
    if not rows:
        return [{"name": n, "key": k, "stage": st, "color": DEFAULT_STATUS_COLORS.get(n)}
                for n, k, st in STATUS_SEED]
    return [{"name": r.name, "key": r.key or slugify(r.name),
             "stage": r.stage or stage_for(db, r.name), "color": r.color} for r in rows]


def backfill_status_meta(db: Session) -> int:
    """Give every shipped status its key + stage. Idempotent; runs on boot beside the seed.

    🔴 This is the path the two columns take to PRODUCTION for rows that already exist — the same
    reason `retire_statuses` runs every boot. Without it, an existing board would have statuses
    with no stage, and `stage_for` would be leaning on the legacy literal map for every card.
    """
    fixed = 0
    by_name = {r.name: r for r in _status_rows(db)}
    for name, key, stage in STATUS_SEED:
        row = by_name.get(name)
        if row is None:
            continue
        if not row.key:
            row.key = key
            fixed += 1
        if not row.stage:
            row.stage = stage
            fixed += 1
    # Any status the seed does not know (a custom one added before `stage` existed) at least gets a
    # key, so its identity is stable from now on. Its stage stays empty ON PURPOSE: guessing one
    # would silently file a client's card in the wrong column.
    for row in by_name.values():
        if not row.key:
            row.key = slugify(row.name)
            fixed += 1
    if fixed:
        db.commit()
    return fixed


def labels(db: Session) -> list[str]:
    return names(db, "label")


def priorities(db: Session) -> list[str]:
    return names(db, "priority")


# --- Retired statuses -------------------------------------------------------------------------
# Dropping a name from `constants.TASK_STATUSES` is NOT enough to remove a board column: the DB row
# in `task_vocab` was seeded on first boot and overrides the code defaults from then on, so the
# column keeps rendering. Worse, a task still holding a retired status disappears from the board
# entirely — `renderBoard` groups by the CURRENT status list and drops anything outside it.
# So a retirement is two moves, and this map drives both: move the tasks, then delete the row.
# 🔴 The VALUE is a STAGE, not a label. It used to be `TASK_BLOCKED` ("Blocked"), which meant this
# boot-time sweep moved live cards onto a hardcoded label — and the moment that label is renamed
# (Blocked -> Parked) it would move them onto a status with no column, i.e. off the board with no
# error. Resolved through `status_for_stage` at run time instead.
RETIRED_STATUSES = {
    # Removed 2026-07-30. Both only meant "blocked on someone", the same call Atrium made a day
    # earlier for its matching stages (workspace._STAGE_ALIASES -> "blocked").
    "For Review": "blocked",
    "Waiting for Client": "blocked",
}


def retire_statuses(db: Session) -> list[str]:
    """Move every task off a retired status, then delete its vocab row. Returns what it retired.

    Idempotent and safe to run on every boot — this is how the change reaches PRODUCTION, where
    deploys don't run Alembic (same reason `main._ensure_columns` carries the 'mental' data fix).
    Order matters: the tasks move FIRST, so the delete can never strand a card off the board.
    """
    retired: list[str] = []
    for old, stage in RETIRED_STATUSES.items():
        # Whatever the surviving column is CALLED today. Never a literal — and if NOTHING carries
        # that stage any more (someone deleted the column), the first real column beats the
        # hardcoded name: this sweep's whole job is to leave no task in a column that isn't there.
        new = status_for_stage(db, stage) or next(iter(statuses(db)), TASK_BLOCKED)
        moved = db.query(Task).filter(Task.status == old).update(
            {Task.status: new}, synchronize_session=False)
        row = db.execute(
            select(TaskVocabItem).where(TaskVocabItem.kind == "status", TaskVocabItem.name == old)
        ).scalar_one_or_none()
        if row is not None:
            db.delete(row)
        if moved or row is not None:
            retired.append(f"{old} -> {new} ({moved} task(s))")
    if retired:
        db.commit()
    return retired

"""Was this task PLANNED ahead, or ADDED during the day? (2026-08-11)

The Sentinel task-placement guidelines split the board's work in two and the split is the point of
the doc:

* **§1 — planned.** "The Team Lead is responsible for placing all planned tasks into Sentinel before
  or at the start of the workday… creating and assigning these planned tasks to the correct worker."
* **§3 — added.** "If a new task comes up during the day and it was not already added by the Team
  Lead, the worker responsible for doing that task must add it to Sentinel… so Sentinel accurately
  reflects the actual work completed during the day."

That last clause is the requirement. Until this field existed every task looked equally planned, so
the reactive load a team actually absorbs — the unexpected revisions, the budget changes, the
suddenly-needed report — was invisible on every surface, and a person buried in it read as simply
having a lot of cards.

🔴 THE RULE IS THE ONE THE GUIDELINES THEMSELVES ASSIGN: WHO RAISED IT.

Those guidelines allocate the *planning duty* by role — the Team Lead plans, the worker adds — so
that is what this classifies on, and nothing else:

| Creator | For whom | Answer |
|---|---|---|
| may delegate (team lead / AM / admin / super) | somebody else, or a department queue | `planned` |
| may delegate | **themselves** | `added` — they raised their own work, which is §3, not §1 |
| may NOT delegate (employee / intern) | anyone, including a department queue | `added` |

The employee row is the one worth stating out loud. An employee CAN route a card to a department
without owning it (decision D10 — "an Acquisition employee who spots a website bug should not have to
own the fix"), and that act looks like delegation. It is not planning: it is §3's "a new task came up",
filed by the person it came up in front of. Keying off "did they delegate" instead of "may they plan"
would file every one of those as planned.

🔴 IT IS A DERIVED DEFAULT, AND IT CAN BE WRONG — WHICH IS WHY IT IS CORRECTABLE.

The honest limit, stated here so nobody has to rediscover it: an account manager who logs a client's
urgent 4pm request and assigns it to somebody is doing §3's job through §1's motion, and this rule
answers `planned` for it. The only signals that would catch that case are clock-based (was it filed
after the workday began?), and each of them is wrong in the opposite direction — a lead planning
tomorrow's campaign build at 4pm today would be filed as `added`. Two fuzzy signals do not make one
sharp one, so this takes the rule the doc actually states and lets a human fix the exceptions
(`routers/tasks.py`, gated on `task_perms.can_reassign` — reclassifying somebody's work is a
manager's call, exactly like moving it).

🔴 It is also **stored, never re-derived**. The creator's role changes when somebody is promoted, and
`assigned_to_id` changes the first time a card is reassigned — so a rule evaluated at read time would
silently re-answer for tasks that have not changed. Classified once, at create, like the label.
"""
from __future__ import annotations

from ..constants import ORIGIN_ADDED, ORIGIN_PLANNED, TASK_ORIGINS
from ..models import User


def classify(user: User, assigned_to_id: int | None, *, may_delegate: bool) -> str:
    """`planned` | `added` for a task being created.

    `may_delegate` is passed in rather than recomputed: `create_task` has already worked out whether
    this caller may name somebody (a team lead is scoped to their OWN department there), and a second
    derivation of that rule is how the delegation guard has been walked past twice on this board.
    """
    if not may_delegate:
        # An employee or intern raising anything — including filing into a department's queue, which
        # is D10's "I spotted it, somebody else owns it", not a planning act.
        return ORIGIN_ADDED
    if assigned_to_id is not None and assigned_to_id == user.id:
        # A planner raising their OWN work. §1 is about placing work FOR a worker; this is §3.
        return ORIGIN_ADDED
    return ORIGIN_PLANNED


def normalize(value: str | None) -> str | None:
    """A caller-supplied origin, or None for "unknown / leave it alone".

    Anything that is not one of the two keys is rejected as None rather than stored: a third value
    would sit in the column looking like an answer while every count silently excluded it.
    """
    v = (value or "").strip().lower()
    return v if v in TASK_ORIGINS else None


def label(value: str | None) -> str:
    """How a surface prints it. 🔴 An unknown origin says so — it must never render as "Planned".

    The rows that predate this column are genuinely unclassified (see `Task.origin`), and printing a
    guess on them is exactly the failure `on_time_rate` avoids by returning None instead of 0.
    """
    return {ORIGIN_PLANNED: "Planned", ORIGIN_ADDED: "Added during the day"}.get(value or "", "—")

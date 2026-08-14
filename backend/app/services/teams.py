"""Departments — the ONE definition of "which departments is this person part of".

Added 2026-08-14, with `models.UserTeam`. Before it, every scope rule in the estate was written as
`something.team_id == user.team_id`: a single integer compared to a single integer, in nine
different files. That was fine while a person belonged to exactly one department and wrong the
moment anybody belonged to two — which people genuinely do here (a designer who also sits with
Acquisition, a lead covering a second team while it has no lead of its own).

🔴 **`users.team_id` IS STILL THE PRIMARY DEPARTMENT and is not going away.** See `models.UserTeam`
for why: shift/lateness, payroll and the directory's Department column all need exactly one answer,
and a set cannot give them one. What this module answers is the other question — *participation* —
and the two must not be confused:

| question | ask |
|---|---|
| "which department is this person OF?" (shift, payroll, the People column, a card's routing) | `user.team_id` |
| "whose work may this person take part in / see / lead?" | `team_ids(user)` |

Everything that scopes a BOARD, a ROLLUP or a NOTIFICATION asks this module. Nothing else should
read `UserTeam` directly — a second derivation of the union is exactly how `is_assigned` and the
Overview's "my work" strip came to disagree in July 2026.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import User, UserTeam


def team_ids(user: User | None) -> set[int]:
    """Every department this person takes part in: their primary one plus any additional ones.

    Empty for somebody with no department at all — which is a real state here (it is the default for
    a new account) and is why every caller has to treat "no departments" as "matches nothing" rather
    than as "matches everything". A card with `assigned_team_id = None` is not in anybody's
    department; an employee with no department sees only what is actually on them.
    """
    if user is None:
        return set()
    ids = {t.team_id for t in (getattr(user, "extra_teams", None) or []) if t.team_id is not None}
    if user.team_id is not None:
        ids.add(user.team_id)
    return ids


def in_team(user: User | None, team_id: int | None) -> bool:
    """Is `team_id` one of this person's departments? The set form of the old `u.team_id == x`."""
    return team_id is not None and team_id in team_ids(user)


def shares_department(a: User | None, b: User | None) -> bool:
    """Do these two people share ANY department? "Somebody I work alongside", for the rollups."""
    return bool(team_ids(a) & team_ids(b))


def member_ids(db: Session, ids: set[int] | None) -> set[int]:
    """Every user id in ANY of `ids` — primary members and additional members alike.

    Two queries, never one per person. `ids` empty returns an empty set, deliberately: a lead with
    no department leads nobody, and answering "everyone" there would silently hand them the estate.
    """
    if not ids:
        return set()
    primary = db.execute(select(User.id).where(User.team_id.in_(ids))).scalars().all()
    extra = db.execute(select(UserTeam.user_id).where(UserTeam.team_id.in_(ids))).scalars().all()
    return set(primary) | set(extra)


def members(db: Session, ids: set[int] | None) -> list[User]:
    """`member_ids` as rows, ordered by name — for the surfaces that render people rather than
    filter by them."""
    keep = member_ids(db, ids)
    if not keep:
        return []
    rows = db.execute(select(User).where(User.id.in_(keep))).scalars().all()
    return sorted(rows, key=lambda u: (u.name or "").lower())


def set_extra_teams(db: Session, user: User, ids: list[int] | None) -> list[int]:
    """Replace a person's ADDITIONAL departments with `ids`. Returns what was stored.

    Three rules, each of which is a bug that would otherwise be filed later:

    * **the primary department is dropped from the list.** It is already a department of theirs, and
      storing it twice would make `Manage → Employees` show it in two places and make removing it
      from one of them do nothing;
    * **unknown team ids are ignored, not 400'd.** This arrives from a checkbox list built from the
      live `/api/teams`; a department deleted between opening the form and saving it is not the
      admin's mistake to be shouted at for;
    * **`None` means "not sent" and leaves the memberships alone** — the same contract
      `support_ids` follows (AGENTS.md §5). An unrelated PATCH from another screen must not silently
      empty somebody's departments. `[]` really does mean "remove them all".
    """
    if ids is None:
        return sorted(t.team_id for t in (user.extra_teams or []))
    from ..models import Team

    known = set(db.execute(select(Team.id)).scalars().all())
    want = {int(i) for i in ids if int(i) in known and int(i) != (user.team_id or -1)}
    user.extra_teams[:] = [t for t in user.extra_teams if t.team_id in want]
    have = {t.team_id for t in user.extra_teams}
    for tid in sorted(want - have):
        user.extra_teams.append(UserTeam(user_id=user.id, team_id=tid))
    return sorted(want)


def names(db: Session, ids: set[int] | None) -> list[str]:
    """Department names for a set of ids, alphabetically — for display only."""
    if not ids:
        return []
    from ..models import Team

    rows = db.execute(select(Team.name).where(Team.id.in_(ids))).scalars().all()
    return sorted(rows, key=lambda n: (n or "").lower())

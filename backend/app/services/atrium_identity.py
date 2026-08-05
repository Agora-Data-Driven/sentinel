"""Resolve an ATRIUM roster owner to the SENTINEL user who is that person.

🔴 **Why an exact email match is not enough — the reason client cards read "Unassigned".**
Sentinel's `users` table is the source of truth for staff, but Atrium's roster is a *separate* list
keyed by email, and in this estate the two do not agree on the domain. Atrium's canonical
`ATRIUM_TEAM` alone spans three:

    @agoradatadriven.com   Christian, Ehjay, Jerome, Justine, Lance, Nico, Paulo, Samuel
    @100.digital           Charles, Ian, Zhen
    @bidbrain.com          John

…and `_team_roster()` also merges every LIVE portal account, whose email can be anything at all
(a personal Gmail, which is how a lead ends up displayed as "Agustinnico228"). So the same human is
`justine@agoradatadriven.com` in Atrium and `justine@agora.ph` in Sentinel, and an `email ==` join
finds nobody. Every client card then resolves to no Sentinel user: it lands in the **Unassigned**
swimlane, counts toward nobody's workload on the Monitor, and renders initials because there is no
Sentinel row to take a `profile_pic_url` from.

So resolution is a LADDER, tried in falling order of confidence:

    1. exact email                      justine@agora.ph == justine@agora.ph
    2. email local part                 justine@agoradatadriven.com -> "justine"
    3. full display name                "Justine Roa" == "Justine Roa"
    4. first name                       "Justine" -> the one Sentinel user called Justine

🔴 **Every rung refuses to guess when it is ambiguous.** Two people whose local part is "ian", or two
Justines, resolve to NOBODY rather than to the first match — mis-attributing a person's workload is
worse than a gap, and a gap is visible (`client_cards` on the row, "Unassigned" on the card) while a
wrong attribution silently reads as truth on the table a manager staffs from.

The index is built per request from the users the caller may already see. It is a READ of Sentinel
only — nothing is written, to either system, and no column is added anywhere.
"""
from __future__ import annotations

from ..models import User


def _norm(value: str | None) -> str:
    return (value or "").strip().lower()


def _local_part(email: str | None) -> str:
    return _norm(email).split("@")[0]


def _first_name(name: str | None) -> str:
    parts = _norm(name).split()
    return parts[0] if parts else ""


def _unique(index: dict[str, User | None], key: str) -> User | None:
    """A key maps to a user only while exactly ONE user claims it.

    `None` is stored as the value for a collided key (rather than dropping the key) so a later
    identical key cannot silently re-add the first winner.
    """
    return index.get(key) if key else None


def _add(index: dict[str, User | None], key: str, user: User) -> None:
    if not key:
        return
    if key in index and (index[key] is None or index[key].id != user.id):
        index[key] = None          # collision -> this key can never resolve
    else:
        index.setdefault(key, user)


class Resolver:
    """Atrium roster identity -> Sentinel `User`, or None. Built once, called per card."""

    def __init__(self, users: list[User]):
        self._by_email: dict[str, User | None] = {}
        self._by_local: dict[str, User | None] = {}
        self._by_name: dict[str, User | None] = {}
        self._by_first: dict[str, User | None] = {}
        for u in users:
            _add(self._by_email, _norm(u.email), u)
            _add(self._by_local, _local_part(u.email), u)
            _add(self._by_name, _norm(u.name), u)
            _add(self._by_first, _first_name(u.name), u)

    def resolve(self, email: str | None, display_name: str | None = None) -> User | None:
        """The ladder. Returns the Sentinel user, or None when nothing resolves unambiguously."""
        email_n = _norm(email)
        found = _unique(self._by_email, email_n)
        if found:
            return found
        found = _unique(self._by_local, _local_part(email_n))
        if found:
            return found
        # The name Atrium shows. Its roster carries one, and for a Gmail-based portal account it is
        # the ONLY usable signal — the local part is "agustinnico228", which matches nothing.
        name_n = _norm(display_name)
        found = _unique(self._by_name, name_n)
        if found:
            return found
        return _unique(self._by_first, _first_name(name_n))


def build(users: list[User]) -> Resolver:
    return Resolver(users)

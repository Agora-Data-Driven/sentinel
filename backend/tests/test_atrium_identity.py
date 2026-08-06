"""Resolving an ATRIUM roster owner to the SENTINEL user who is that person (2026-08-05).

🔴 **The root cause this fixes.** Sentinel's `users` table is the source of truth for staff, but
Atrium keeps its OWN roster keyed by email — and the two disagree on the domain for the same human.
Atrium's canonical `ATRIUM_TEAM` alone spans `@agoradatadriven.com`, `@100.digital` and
`@bidbrain.com`, and `_team_roster()` also merges live portal accounts whose email may be a personal
Gmail (which is how a lead renders as "Agustinnico228"). Sentinel's own users are on yet another
domain. So the first attempt — an exact `email ==` join — resolved almost nobody, and every client
card kept behaving as ownerless: **Unassigned** lane on By Employee, counted toward nobody on the
Monitor, and initials instead of a photo because there was no Sentinel row to read
`profile_pic_url` from.

The ladder, in falling confidence: exact email → email local part → full display name → first name.
Every rung **refuses to guess when ambiguous**, which is the property most likely to be "simplified"
away by someone tidying up — and each of those simplifications silently mis-attributes a real
person's workload on the table a manager staffs from.
"""
from __future__ import annotations

from app import constants as C
from app.services import atrium_identity, atrium_tasks


def _resolve(users, email, name=None):
    return atrium_identity.build(users).resolve(email, name)


# --- the ladder ----------------------------------------------------------------------------------

def test_exact_email_wins(make_user):
    u = make_user(C.ROLE_EMPLOYEE, name="Justine Roa", email="justine@agora.ph")
    assert _resolve([u], "justine@agora.ph") is u
    assert _resolve([u], "  JUSTINE@AGORA.PH ") is u, "case and whitespace are not identity"


def test_a_different_DOMAIN_still_resolves_by_local_part(make_user):
    """🔴 THE ACTUAL BUG. Atrium says justine@agoradatadriven.com; Sentinel says justine@agora.ph."""
    u = make_user(C.ROLE_EMPLOYEE, name="Justine Roa", email="justine@agora.ph")
    assert _resolve([u], "justine@agoradatadriven.com") is u
    assert _resolve([u], "justine@100.digital") is u


def test_a_gmail_lead_resolves_by_NAME_because_its_local_part_matches_nothing(make_user):
    """The "Agustinnico228" case: the email carries no usable name, but Atrium's roster ships one."""
    u = make_user(C.ROLE_EMPLOYEE, name="Nico Agustin", email="nico@agora.ph")
    assert _resolve([u], "agustinnico228@gmail.com", "Nico Agustin") is u


def test_a_first_name_resolves_when_it_is_unique(make_user):
    """Atrium's roster stores bare first names ("Justine", "Ehjay") — the last rung exists for them."""
    u = make_user(C.ROLE_EMPLOYEE, name="Ehjay Bautista", email="ehjay@agora.ph")
    assert _resolve([u], "someone.else@gmail.com", "Ehjay") is u


# --- 🔴 refuse to guess --------------------------------------------------------------------------

def test_two_people_with_the_same_LOCAL_PART_resolve_to_nobody(make_user):
    """`ian@100.digital` and `ian@agora.ph` are two different humans as far as we can prove."""
    a = make_user(C.ROLE_EMPLOYEE, name="Ian Fernandez", email="ian@agora.ph")
    b = make_user(C.ROLE_EMPLOYEE, name="Ian Cruz", email="ian@bidbrain.com")
    assert _resolve([a, b], "ian@100.digital") is None


def test_two_people_with_the_same_FIRST_NAME_resolve_to_nobody(make_user):
    a = make_user(C.ROLE_EMPLOYEE, name="Justine Roa", email="jroa@agora.ph")
    b = make_user(C.ROLE_EMPLOYEE, name="Justine Lim", email="jlim@agora.ph")
    assert _resolve([a, b], "justine@agoradatadriven.com", "Justine") is None


def test_a_specific_rung_disambiguates_what_a_vaguer_one_could_not(make_user):
    """Ambiguity lower down the ladder must never spoil a definite match higher up.

    Two Justines exist, so the FIRST-NAME rung is ambiguous — but only one of them owns the local
    part `justine`, so the rung above it still answers. Resolution stops at the first rung that is
    unambiguous; it does not fall through and then give up.
    """
    a = make_user(C.ROLE_EMPLOYEE, name="Justine Roa", email="justine@agora.ph")
    b = make_user(C.ROLE_EMPLOYEE, name="Justine Lim", email="jlim@agora.ph")
    assert _resolve([a, b], "justine@agora.ph", "Justine") is a          # rung 1
    assert _resolve([a, b], "justine@agoradatadriven.com", "Justine") is a   # rung 2 saves it
    # Take the distinguishing local part away and it is genuinely ambiguous again.
    c = make_user(C.ROLE_EMPLOYEE, name="Justine Cruz", email="jcruz@agora.ph")
    assert _resolve([b, c], "justine@agoradatadriven.com", "Justine") is None


def test_a_lead_who_is_nobody_here_resolves_to_nobody(make_user):
    u = make_user(C.ROLE_EMPLOYEE, name="Justine Roa", email="justine@agora.ph")
    assert _resolve([u], "contractor@elsewhere.com", "Some Contractor") is None
    assert _resolve([u], "", "") is None
    assert _resolve([u], None, None) is None


# --- what the resolved owner does to the CARD ----------------------------------------------------

def _card(owner=None, viewer_id=None, **over):
    payload = {"atrium_id": "rooming-house:tk_4", "task_id": "tk_4",
               "client_key": "rooming-house", "title": "ActiveCampaign manual list fix",
               "status": "In Progress", "lead_id": "justine@agoradatadriven.com",
               "lead_name": "Justine"}
    payload.update(over)
    return atrium_tasks.as_board_card(payload, None, owner, viewer_id=viewer_id)


_JUSTINE = {"id": 12, "name": "Justine Roa", "email": "justine@agora.ph",
            "profile_pic_url": "https://x/justine.jpg", "initials": "JR",
            "role": "employee", "role_label": "Employee", "team_id": 3}


def test_a_resolved_owner_gives_the_card_a_LANE_and_a_PHOTO():
    """🔴 Both halves of the user's report. `assigned_to_id` is what `renderByEmployee` groups on, so
    without it an owned client card sits in the Unassigned swimlane; `profile_pic_url` is why the
    avatar showed initials."""
    owner = {"id": 12, "name": "Justine Roa", "email": "justine@agora.ph",
             "profile_pic_url": "https://x/justine.jpg", "initials": "JR",
             "role": "employee", "role_label": "Employee", "team_id": 3}
    card = _card(owner)
    assert card["assigned_to_id"] == 12, "this is what puts it in Justine's lane"
    assert card["assignee"]["profile_pic_url"] == "https://x/justine.jpg"
    assert card["assignee"]["name"] == "Justine Roa", "the Sentinel name, not Atrium's short one"


def test_an_unresolved_lead_still_shows_a_NAME_but_claims_no_identity():
    """The middle rung: named on the card (so the board doesn't lie), but no lane and no fake id."""
    card = _card(None)
    assert card["assigned_to_id"] is None
    assert card["assignee"]["id"] is None
    assert card["assignee"]["name"] == "Justine"


def test_a_card_with_no_lead_at_all_is_honestly_unassigned():
    card = _card(None, lead_id="", lead_name="")
    assert card["assigned_to_id"] is None
    assert card["assignee"] is None


# --- "My work" has to agree with the lane and the Monitor (2026-08-06) ---------------------------
# 🔴 `mine` was simply absent from this payload, and a missing key is falsy — so the board's My work
# button dropped every client card. That was right while an Atrium owner was only ever a roster
# email, and wrong from the moment this module started resolving that email to a Sentinel user:
# the SAME resolved owner put the card in that person's By Employee lane, counted it toward them on
# the Monitor and printed their photo on it, while one button insisted the work was not theirs.

def test_the_resolved_owner_is_the_one_the_card_says_is_MINE():
    card = _card(_JUSTINE, viewer_id=12)
    assert card["mine"] is True
    assert card["assigned_to_id"] == 12, "and it is the same owner the lane groups on"


def test_a_colleagues_client_card_is_not_mine():
    assert _card(_JUSTINE, viewer_id=99)["mine"] is False


def test_an_unresolved_lead_makes_the_card_nobodys():
    """No proven Sentinel identity, so it is not on anyone's My work — the same refusal to guess
    that leaves it out of every lane."""
    assert _card(None, viewer_id=12)["mine"] is False


def test_mine_is_ABSENT_when_no_viewer_was_passed():
    """`serializers.task_card`'s contract: a payload built without a viewer omits the field rather
    than hardcoding False, because False is a claim and absence is not. `people.py`'s profile card
    relies on exactly this for Sentinel rows."""
    assert "mine" not in _card(_JUSTINE)
    assert "my_slots" not in _card(_JUSTINE, viewer_id=12), \
        "an Atrium breakdown has no Sentinel step owners to count, so a 0 would be a lie"


def test_the_board_pill_can_see_an_atrium_hold():
    """`on_hold` was missing too, so a client card paused in Atrium looked live on the board and
    said "On hold" the moment you opened it (as_task_detail always mapped it)."""
    assert _card(None, on_hold=True)["on_hold"] is True
    assert _card(None)["on_hold"] is False

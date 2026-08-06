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

def _card(owner=None, viewer_id=None, support=None, **over):
    payload = {"atrium_id": "rooming-house:tk_4", "task_id": "tk_4",
               "client_key": "rooming-house", "title": "ActiveCampaign manual list fix",
               "status": "In Progress", "lead_id": "justine@agoradatadriven.com",
               "lead_name": "Justine"}
    payload.update(over)
    return atrium_tasks.as_board_card(payload, None, owner, viewer_id=viewer_id, support=support)


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


# --- SUPPORT is resolved by the same ladder (2026-08-06) -----------------------------------------
# 🔴 The lead had been resolved since 2026-08-05 and support had not, so on ONE card the lead wore
# their photo while every supporter rendered grey initials — including people who do have a photo in
# Sentinel. Confirmed on the live board: "Weekly blog + Newsletter posting (Thursday)" (Rooming House
# Expert) carries lead `agustinnico228@gmail.com` (resolves by NAME → photo) and support
# `paulo@agoradatadriven.com` (never resolved → "P"). Same roster, same ladder; the resolver was
# never lead-specific.

_PAULO = {"id": 7, "name": "Paulo Reyes", "email": "paulo@agora.ph",
          "profile_pic_url": "https://x/paulo.jpg", "initials": "PR",
          "role": "employee", "role_label": "Employee", "team_id": 2}


def _sup_card(support=None, viewer_id=None, **over):
    over.setdefault("support_ids", ["paulo@agoradatadriven.com"])
    over.setdefault("support_names", ["Paulo"])
    return _card(None, viewer_id=viewer_id, support=support, **over)


def test_a_resolved_SUPPORTER_gets_a_photo_like_the_lead_does():
    card = _sup_card([_PAULO])
    assert card["support"][0]["profile_pic_url"] == "https://x/paulo.jpg", "the reported bug"
    assert card["support"][0]["id"] == 7
    assert card["support"][0]["name"] == "Paulo Reyes", "the Sentinel name, not Atrium's short one"


def test_an_unresolved_supporter_is_still_NAMED_and_claims_no_identity():
    """Same contract as an unresolved lead: initials are honest, a fabricated id is not."""
    card = _sup_card([None])
    assert card["support"][0]["id"] is None
    assert card["support"][0]["name"] == "Paulo"


def test_support_falls_back_to_names_when_the_router_resolved_nothing():
    """`support=None` is the no-resolver path (anything calling this module without a DB)."""
    card = _sup_card(None)
    assert [p["name"] for p in card["support"]] == ["Paulo"]
    assert card["support"][0]["id"] is None


def test_resolved_support_does_NOT_become_a_sentinel_support_id():
    """🔴 By Employee groups lanes on `support_ids` and `mine` comes from the LEAD. Filling it here
    would move client cards onto supporters' lanes and My work while the Monitor still counted them
    toward the lead — the same three-surfaces-disagree split this resolver exists to end. Widening
    support to those surfaces is a separate, deliberate decision."""
    card = _sup_card([_PAULO], viewer_id=7)
    assert card.get("support_ids") in (None, []), "not a Sentinel supporter list"
    assert card["atrium_support_ids"] == ["paulo@agoradatadriven.com"], "Atrium's own, unchanged"
    assert card["mine"] is False, \
        "Paulo supports this card and sees his face on it, but 'My work' still means the LEAD — " \
        "today's boundary, pinned so widening it is a decision somebody makes on purpose"


def test_a_card_with_no_support_says_so_with_an_empty_list():
    card = _card(None)
    assert card["support"] == []
    assert card["atrium_support_names"] == []


# --- pairing: the half that fails SILENTLY -------------------------------------------------------
# A mis-paired list does not raise — it puts one person's name under another person's face, which is
# worse than the bug being fixed. `support_pairs` is the single derivation both sides read.

def test_ids_without_names_are_labelled_from_the_email():
    pairs = atrium_tasks.support_pairs({"support_ids": ["paulo@agoradatadriven.com"]})
    assert pairs == [("paulo@agoradatadriven.com", "Paulo")]


def test_a_shorter_name_list_does_not_shift_everyone_up():
    """Atrium sending two ids and one name must not label the SECOND person "Paulo"."""
    pairs = atrium_tasks.support_pairs(
        {"support_ids": ["paulo@agoradatadriven.com", "justine@agoradatadriven.com"],
         "support_names": ["Paulo"]})
    assert pairs == [("paulo@agoradatadriven.com", "Paulo"),
                     ("justine@agoradatadriven.com", "Justine")]


def test_a_name_with_no_id_still_survives():
    assert atrium_tasks.support_pairs({"support_names": ["", "Zhen"]}) == [("", "Zhen")]


def test_the_resolution_is_aligned_to_that_same_order():
    """The router hands back one entry per pair, positionally. This pins the contract between the
    two halves — swap either side's order and this fails instead of mislabelling a face."""
    card = _card(None, support=[None, _PAULO],
                 support_ids=["zhen@agoradatadriven.com", "paulo@agoradatadriven.com"],
                 support_names=["Zhen", "Paulo"])
    assert [p["name"] for p in card["support"]] == ["Zhen", "Paulo Reyes"]
    assert card["support"][0]["id"] is None and card["support"][1]["id"] == 7


def test_the_detail_drawer_shows_the_same_faces_as_the_card():
    """Two surfaces, one resolution — the lead bug started as the card and the drawer disagreeing."""
    detail = atrium_tasks.as_task_detail(
        {"task": {"atrium_id": "rooming-house:tk_4", "task_id": "tk_4",
                  "client_key": "rooming-house", "title": "x",
                  "support_ids": ["paulo@agoradatadriven.com"], "support_names": ["Paulo"]}},
        None, None, support=[_PAULO])
    assert detail["support"][0]["profile_pic_url"] == "https://x/paulo.jpg"
    assert detail["atrium_support_names"] == ["Paulo"], "Atrium's own vocabulary is untouched"


def test_the_board_pill_can_see_an_atrium_hold():
    """`on_hold` was missing too, so a client card paused in Atrium looked live on the board and
    said "On hold" the moment you opened it (as_task_detail always mapped it)."""
    assert _card(None, on_hold=True)["on_hold"] is True
    assert _card(None)["on_hold"] is False

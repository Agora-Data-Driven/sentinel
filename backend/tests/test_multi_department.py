"""A person may belong to MORE THAN ONE department (`models.UserTeam`, 2026-08-14).

`users.team_id` asserted that everybody belongs to exactly one, and nine files were written as
`something.team_id == user.team_id`. People here do not work that way: a designer also sits with
Acquisition, a lead covers a second team while it has no lead of its own. Those people saw one
department's board, were absent from the other's rollups, and were never notified about its work —
all silently, because a card that is not on your board and a notification that was never sent look
exactly like a quiet day.

What is pinned here, in the order it matters:

1. **the union is the rule** — every task-permission branch reads `services/teams.team_ids`, so an
   extra department behaves EXACTLY like a primary one for reading, queueing and leading;
2. **it only ever widens what somebody SEES.** An extra department is not a promotion: an employee
   still cannot edit a colleague's card there, and `can_delete` still refuses another department's
   work. If a future change makes membership grant a write, these are the tests that fail;
3. **`users.team_id` still means something** — it is the PRIMARY department, and the surfaces that
   need exactly one answer (shift, payroll, the directory's Department column) still get one;
4. **the write path's contract**: `None` leaves memberships alone, `[]` clears them, the primary is
   never stored twice, and an unknown id is ignored rather than 400'd.
"""
from __future__ import annotations

import pytest

from app import constants as C
from app.models import Notification, Task, User, UserTeam
from app.services import task_perms, teams as teams_svc


@pytest.fixture
def design(make_team):
    return make_team(name="Design")


@pytest.fixture
def acquisition(make_team):
    return make_team(name="Acquisition")


@pytest.fixture
def finance(make_team):
    return make_team(name="Finance")


def _join(db, user, team):
    """Give `user` an ADDITIONAL department, the way the People form does."""
    db.add(UserTeam(user_id=user.id, team_id=team.id))
    db.commit()
    db.refresh(user)
    return user


# --- 1. The union is the rule --------------------------------------------------------------------

def test_the_second_department_reads_exactly_like_the_first(client, auth, db, make_user,
                                                            design, acquisition, finance):
    """The whole feature in one assertion: work routed to EITHER department is on their board, and a
    third department they are not in is not."""
    ana = make_user(C.ROLE_EMPLOYEE, team_id=design.id, name="Ana")
    _join(db, ana, acquisition)
    mine_a = Task(title="Design a landing page", assigned_team_id=design.id)
    mine_b = Task(title="Chase the Q3 leads", assigned_team_id=acquisition.id)
    theirs = Task(title="Reconcile the ledger", assigned_team_id=finance.id)
    db.add_all([mine_a, mine_b, theirs])
    db.commit()

    auth(ana)
    seen = {c["id"] for c in client.get("/api/tasks").json()}
    assert mine_a.id in seen
    assert mine_b.id in seen, "the extra department's work is the entire point of the feature"
    assert theirs.id not in seen, "a department they are NOT in stays invisible"


def test_the_triage_queue_follows_every_department(client, auth, db, make_user, design, acquisition):
    """`_team_queue` is `_dept` + unowned, so somebody in two departments is in both queues — that is
    what being in both departments means."""
    ana = make_user(C.ROLE_EMPLOYEE, team_id=design.id)
    _join(db, ana, acquisition)
    queued = Task(title="Unclaimed acquisition work", assigned_team_id=acquisition.id,
                  assigned_to_id=None)
    db.add(queued)
    db.commit()

    auth(ana)
    assert task_perms.can_view(ana, queued)
    # Unowned team work is a shared queue: claimable, not merely readable.
    assert task_perms.can_edit(ana, queued)


def test_a_lead_leads_every_department_they_are_in(client, auth, db, make_user, design, acquisition):
    """A lead covering a second department can staff and approve its work. Before this, the card was
    visible to them (`_dept`) and every control on it was dead — the same shape as the "Team Lead
    can't assign" bug, one layer down."""
    lead = make_user(C.ROLE_TEAM_LEAD, team_id=design.id, name="Bong")
    _join(db, lead, acquisition)
    worker = make_user(C.ROLE_EMPLOYEE, team_id=acquisition.id, name="Zhen")
    card = Task(title="Acquisition campaign build", assigned_team_id=acquisition.id)
    db.add(card)
    db.commit()

    auth(lead)
    r = client.patch(f"/api/tasks/{card.id}", json={"assigned_to_id": worker.id})
    assert r.status_code == 200, r.text
    assert client.patch(f"/api/tasks/{card.id}", json={"priority": "Urgent"}).status_code == 200


def test_a_lead_is_notified_about_their_second_department(client, auth, db, make_user,
                                                          design, acquisition):
    """`notify_managers` queried `User.team_id == team_id`, so the lead of a covered department was
    never told anything about it. Nothing surfaces that failure — a notification that was not sent
    leaves no trace anywhere."""
    lead = make_user(C.ROLE_TEAM_LEAD, team_id=design.id)
    _join(db, lead, acquisition)
    filer = make_user(C.ROLE_ACCOUNT_MANAGER, name="Leo")

    auth(filer)
    r = client.post("/api/tasks", json={"title": "Route this to Acquisition",
                                        "assigned_team_id": acquisition.id})
    assert r.status_code == 200, r.text
    notes = db.query(Notification).filter(Notification.user_id == lead.id).all()
    assert notes, "the lead of the department the card was routed to hears about it"


def test_the_monitor_cohort_includes_the_other_department(client, auth, db, make_user,
                                                          design, acquisition):
    """Two directions at once, and both were broken: a lead covering a second department must see
    its people, AND somebody whose SECOND department is this lead's belongs in the cohort."""
    lead = make_user(C.ROLE_TEAM_LEAD, team_id=design.id, name="Bong")
    _join(db, lead, acquisition)
    make_user(C.ROLE_EMPLOYEE, team_id=acquisition.id, name="Zhen")
    # Kai has NO primary department and Design as an additional one — the pure form of the second
    # direction, and the one a `p.team_id == lead.team_id` filter can never find.
    kai = make_user(C.ROLE_EMPLOYEE, team_id=None, name="Kai")
    _join(db, kai, design)

    auth(lead)
    rows = client.get("/api/tasks/summary").json()
    names = {r["user"]["name"] for r in rows}
    assert "Zhen" in names, "a member of the department this lead covers"
    assert "Kai" in names, "somebody whose ADDITIONAL department is this lead's"


# --- 2. It widens sight, never authority ---------------------------------------------------------

def test_an_extra_department_is_not_a_promotion(client, auth, db, make_user, design, acquisition):
    """🔴 The load-bearing refusal. Membership grants the department READ (`can_view`) and nothing
    else — an employee still cannot touch a colleague's card there, exactly as in their primary
    department. If this ever passes as 200, `can_edit` has been re-aliased to `can_view`."""
    ana = make_user(C.ROLE_EMPLOYEE, team_id=design.id)
    _join(db, ana, acquisition)
    colleague = make_user(C.ROLE_EMPLOYEE, team_id=acquisition.id, name="Zhen")
    theirs = Task(title="Zhen's card", assigned_team_id=acquisition.id, assigned_to_id=colleague.id)
    db.add(theirs)
    db.commit()

    auth(ana)
    card = next(c for c in client.get("/api/tasks").json() if c["id"] == theirs.id)
    assert card["mine"] is False
    assert card["can_edit"] is False
    assert client.patch(f"/api/tasks/{theirs.id}", json={"title": "mine now"}).status_code == 403
    assert client.delete(f"/api/tasks/{theirs.id}").status_code == 403


def test_delete_stays_scoped_to_the_departments_they_actually_lead(db, make_user,
                                                                   design, acquisition, finance):
    """`can_delete` is the one power still keyed on `_leads_team`. Widening membership widens it to
    the covered department — that IS a department they lead — and to no further."""
    lead = make_user(C.ROLE_TEAM_LEAD, team_id=design.id)
    _join(db, lead, acquisition)
    covered = Task(title="Acquisition card", assigned_team_id=acquisition.id)
    elsewhere = Task(title="Finance card", assigned_team_id=finance.id)
    db.add_all([covered, elsewhere])
    db.commit()

    assert task_perms.can_delete(lead, covered) is True
    assert task_perms.can_delete(lead, elsewhere) is False


def test_a_viewer_with_two_departments_still_writes_nothing(db, make_user, design, acquisition):
    """The read-only seat is orthogonal to the ladder (D8), so no amount of membership reaches a
    write. Cheap to assert, and the exact thing a future `_dept`-based shortcut would break."""
    seat = make_user(C.ROLE_VIEWER, team_id=design.id)
    _join(db, seat, acquisition)
    card = Task(title="Anything", assigned_team_id=acquisition.id)
    db.add(card)
    db.commit()

    assert task_perms.can_view(seat, card) is True
    assert task_perms.can_edit(seat, card) is False
    assert task_perms.can_reassign(seat, card) is False
    assert task_perms.can_delete(seat, card) is False


# --- 3. The primary department still means something ---------------------------------------------

def test_the_primary_department_is_still_one_answer(client, auth, db, make_user,
                                                    design, acquisition):
    """Shift, payroll and the directory column need exactly one department, and they still get it.
    `team_ids` publishes the set with the primary FIRST so a surface with room for one name prints
    the right one."""
    ana = make_user(C.ROLE_EMPLOYEE, team_id=design.id, name="Ana")
    _join(db, ana, acquisition)

    auth(ana)
    me = client.get("/api/auth/me").json()
    assert me["team_id"] == design.id, "the primary department did not move"
    assert me["team_name"] == "Design"
    assert me["team_ids"] == [design.id, acquisition.id], "primary first, then the extras"


def test_the_directory_finds_somebody_by_their_second_department(client, auth, db, make_user,
                                                                 design, acquisition):
    """Filtering People by Acquisition has to list everybody who works in Acquisition. Matching
    `team_id` alone hid exactly the people this feature exists for."""
    ana = make_user(C.ROLE_EMPLOYEE, team_id=design.id, name="Ana")
    _join(db, ana, acquisition)
    admin = make_user(C.ROLE_ADMIN)

    auth(admin)
    rows = client.get(f"/api/people?team={acquisition.id}").json()
    assert "Ana" in {r["name"] for r in rows}
    # ...and by the department's NAME, which is the other half of that filter.
    hits = client.get("/api/people?search=acquisition").json()
    assert "Ana" in {r["name"] for r in hits}


# --- 4. The write path's contract ----------------------------------------------------------------

def test_not_sending_the_field_leaves_the_departments_alone(client, auth, db, make_user,
                                                            design, acquisition):
    """🔴 `None` means NOT SENT. Same contract as `support_ids`, and for the same reason: a PATCH
    from any other screen — a phone number, a shift, a password reset — must not quietly empty
    somebody's departments and shrink their board."""
    ana = make_user(C.ROLE_EMPLOYEE, team_id=design.id)
    _join(db, ana, acquisition)
    admin = make_user(C.ROLE_ADMIN)

    auth(admin)
    r = client.patch(f"/api/people/{ana.id}", json={"phone": "0917"})
    assert r.status_code == 200, r.text
    assert r.json()["team_ids"] == [design.id, acquisition.id]


def test_an_empty_list_really_does_clear_them(client, auth, db, make_user, design, acquisition):
    ana = make_user(C.ROLE_EMPLOYEE, team_id=design.id)
    _join(db, ana, acquisition)
    admin = make_user(C.ROLE_ADMIN)

    auth(admin)
    r = client.patch(f"/api/people/{ana.id}", json={"team_ids": []})
    assert r.status_code == 200, r.text
    assert r.json()["team_ids"] == [design.id], "only their primary department is left"


def test_the_primary_is_never_stored_twice(client, auth, db, make_user, design, acquisition):
    """Ticking their own department in the extras list would otherwise put one department in two
    places, and un-ticking it in one of them would do nothing."""
    ana = make_user(C.ROLE_EMPLOYEE, team_id=design.id)
    admin = make_user(C.ROLE_ADMIN)

    auth(admin)
    r = client.patch(f"/api/people/{ana.id}",
                     json={"team_ids": [design.id, acquisition.id]})
    assert r.status_code == 200, r.text
    assert r.json()["team_ids"] == [design.id, acquisition.id]
    assert db.query(UserTeam).filter(UserTeam.user_id == ana.id).count() == 1


def test_an_unknown_department_is_ignored_not_rejected(client, auth, db, make_user,
                                                       design, acquisition):
    """This list comes from a checkbox row built from the live `/api/teams`. A department deleted
    between opening the form and saving it is not the admin's mistake to be 400'd for."""
    ana = make_user(C.ROLE_EMPLOYEE, team_id=design.id)
    admin = make_user(C.ROLE_ADMIN)

    auth(admin)
    r = client.patch(f"/api/people/{ana.id}", json={"team_ids": [acquisition.id, 999999]})
    assert r.status_code == 200, r.text
    assert r.json()["team_ids"] == [design.id, acquisition.id]


def test_deleting_a_department_takes_its_memberships_with_it(client, auth, db, make_user,
                                                             design, acquisition):
    """These rows carry an FK to `teams`. Left behind they orphan — and on SQLite, which does not
    enforce FKs, they survive and `team_ids` keeps handing out a department that no longer exists."""
    ana = make_user(C.ROLE_EMPLOYEE, team_id=design.id)
    _join(db, ana, acquisition)
    root = make_user(C.ROLE_SUPER_ADMIN)

    auth(root)
    assert client.delete(f"/api/manage/teams/{acquisition.id}").status_code == 200
    db.refresh(ana)
    assert db.query(UserTeam).filter(UserTeam.team_id == acquisition.id).count() == 0
    assert teams_svc.team_ids(ana) == {design.id}


def test_a_person_with_no_department_matches_nothing(db, make_user, design):
    """🔴 Empty means EMPTY, never "everything". The comparison this replaced was `None == None`,
    which quietly grouped every department-less person into one pseudo-team — a lead with no
    department could see all of them."""
    nobody = make_user(C.ROLE_EMPLOYEE, team_id=None)
    other = make_user(C.ROLE_EMPLOYEE, team_id=None)
    card = Task(title="Unrouted", assigned_team_id=None)

    assert teams_svc.team_ids(nobody) == set()
    assert teams_svc.shares_department(nobody, other) is False
    assert task_perms.can_view(nobody, card) is False

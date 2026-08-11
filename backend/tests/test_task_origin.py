"""PLANNED ahead vs ADDED during the day (2026-08-11) — `Task.origin`, `services/task_origin`.

The requirement is one sentence of the Sentinel task-placement guidelines: §1 gives the Team Lead the
duty of placing planned work before the workday starts, §3 makes the worker add whatever comes up
afterwards, "so Sentinel accurately reflects the actual work completed during the day". Every task
looked equally planned, so a team's reactive load was invisible on every surface.

What is pinned here, in the order it matters:

* the classification rule the guidelines themselves state — **who may plan**, not "who delegated";
* 🔴 the **employee-routes-to-a-department** case, which looks like delegation and is not (D10);
* NULL stays NULL — a task raised before the column existed is unclassified, never "planned";
* it is **stored, not re-derived**, so a promotion or a reassignment cannot re-answer it;
* correcting it is `can_reassign`, because it feeds the Monitor's reactive-load number;
* an Atrium card can never be classified, and its key is **present-and-None** rather than absent.
"""
from __future__ import annotations

from app.constants import ORIGIN_ADDED, ORIGIN_PLANNED
from app.models import Task
from app.services import atrium_tasks, task_origin


# --- the rule -------------------------------------------------------------------------------------

def test_a_planner_filing_for_somebody_else_is_planned(make_user):
    lead = make_user(role="team_lead")
    worker = make_user(role="employee")
    assert task_origin.classify(lead, worker.id, may_delegate=True) == ORIGIN_PLANNED


def test_a_planner_filing_into_a_department_queue_is_planned(make_user):
    """§1's "creating and assigning these planned tasks" covers routing to the team that will do it —
    nobody owns it yet, but a planner planned it."""
    lead = make_user(role="team_lead")
    assert task_origin.classify(lead, None, may_delegate=True) == ORIGIN_PLANNED


def test_a_planner_raising_their_OWN_work_is_added(make_user):
    """§1 is about placing work FOR a worker. Somebody raising a job they will do themselves is §3,
    whatever their role — otherwise every task an AM does personally reads as planned."""
    am = make_user(role="account_manager")
    assert task_origin.classify(am, am.id, may_delegate=True) == ORIGIN_ADDED


def test_an_employee_raising_anything_is_added(make_user):
    emp = make_user(role="employee")
    assert task_origin.classify(emp, emp.id, may_delegate=False) == ORIGIN_ADDED


def test_an_employee_routing_to_a_DEPARTMENT_is_still_added(make_user):
    """🔴 The case that breaks the obvious rule. An employee may route a card to a department without
    owning it (D10 — "an Acquisition employee who spots a website bug should not have to own the
    fix"), and that ACT looks exactly like delegation. It is not planning: it is §3's "a new task came
    up", filed by whoever it came up in front of. Keying off "did they delegate" would file every one
    of these as planned."""
    emp = make_user(role="employee")
    assert task_origin.classify(emp, None, may_delegate=False) == ORIGIN_ADDED


# --- normalize / label ----------------------------------------------------------------------------

def test_an_unknown_value_is_refused_rather_than_stored():
    """A third value would sit in the column looking like an answer while every count excluded it."""
    assert task_origin.normalize("urgent") is None
    assert task_origin.normalize("") is None
    assert task_origin.normalize(None) is None
    assert task_origin.normalize("  Planned  ") == ORIGIN_PLANNED   # trimmed + lowercased


def test_an_unclassified_task_never_prints_as_planned():
    """The on-time-rate rule in another field: unknown says so, it does not pick a side."""
    assert task_origin.label(None) == "—"
    assert task_origin.label("nonsense") == "—"
    assert task_origin.label(ORIGIN_PLANNED) == "Planned"


# --- through the API ------------------------------------------------------------------------------

def test_create_stores_the_classification(client, auth, make_user, make_team):
    team = make_team(name="Acquisition")
    lead = make_user(role="team_lead", team_id=team.id)
    worker = make_user(role="employee", team_id=team.id)
    auth(lead)

    planned = client.post("/api/tasks", json={
        "title": "Campaign build", "assigned_team_id": team.id, "assigned_to_id": worker.id})
    assert planned.status_code == 200, planned.text
    assert planned.json()["origin"] == ORIGIN_PLANNED

    own = client.post("/api/tasks", json={
        "title": "Fix tracking", "assigned_team_id": team.id, "assigned_to_id": lead.id})
    assert own.json()["origin"] == ORIGIN_ADDED


def test_an_employees_own_task_is_added_through_the_API(client, auth, make_user, make_team):
    team = make_team(name="Acquisition")
    emp = make_user(role="employee", team_id=team.id)
    auth(emp)
    r = client.post("/api/tasks", json={"title": "Client asked for a revision"})
    assert r.status_code == 200, r.text
    assert r.json()["origin"] == ORIGIN_ADDED


def test_origin_is_NOT_settable_on_create(client, auth, make_user, make_team):
    """The classification is the server's, like the creator tag and the label. `TaskCreateIn` has no
    such field, so a caller claiming one is ignored rather than believed."""
    team = make_team(name="Acquisition")
    emp = make_user(role="employee", team_id=team.id)
    auth(emp)
    r = client.post("/api/tasks", json={"title": "Mine", "origin": ORIGIN_PLANNED})
    assert r.json()["origin"] == ORIGIN_ADDED


def test_it_is_stored_not_re_derived(client, auth, db, make_user, make_team):
    """🔴 A rule evaluated at READ time would re-answer for tasks that never changed: the creator's
    role moves when somebody is promoted, and `assigned_to_id` moves the first time a card is
    reassigned. Reassigning an `added` card must not turn it into `planned`."""
    team = make_team(name="Acquisition")
    lead = make_user(role="team_lead", team_id=team.id)
    worker = make_user(role="employee", team_id=team.id)
    auth(lead)
    made = client.post("/api/tasks", json={"title": "Mine", "assigned_team_id": team.id,
                                          "assigned_to_id": lead.id})
    tid = made.json()["id"]
    assert made.json()["origin"] == ORIGIN_ADDED

    moved = client.patch(f"/api/tasks/{tid}", json={"assigned_to_id": worker.id})
    assert moved.status_code == 200, moved.text
    assert moved.json()["origin"] == ORIGIN_ADDED
    assert db.get(Task, tid).origin == ORIGIN_ADDED


# --- correcting it --------------------------------------------------------------------------------

def test_a_manager_may_correct_it(client, auth, make_user, make_team):
    team = make_team(name="Acquisition")
    am = make_user(role="account_manager")
    worker = make_user(role="employee", team_id=team.id)
    auth(am)
    tid = client.post("/api/tasks", json={"title": "Urgent client ask", "assigned_team_id": team.id,
                                         "assigned_to_id": worker.id}).json()["id"]

    r = client.patch(f"/api/tasks/{tid}", json={"origin": ORIGIN_ADDED})
    assert r.status_code == 200, r.text
    assert r.json()["origin"] == ORIGIN_ADDED


def test_a_manager_may_clear_it_back_to_unclassified(client, auth, make_user, make_team):
    """"Not set" is a real answer — it is what every pre-column task holds, and a manager must be able
    to say "I don't know" rather than being forced to pick a side."""
    team = make_team(name="Acquisition")
    am = make_user(role="account_manager")
    worker = make_user(role="employee", team_id=team.id)
    auth(am)
    tid = client.post("/api/tasks", json={"title": "Something", "assigned_team_id": team.id,
                                         "assigned_to_id": worker.id}).json()["id"]

    r = client.patch(f"/api/tasks/{tid}", json={"origin": None})
    assert r.status_code == 200, r.text
    assert r.json()["origin"] is None


def test_an_employee_cannot_rewrite_it(client, auth, make_user, make_team):
    """🔴 It feeds the Monitor's reactive-load number, so leaving it open to whoever can EDIT would let
    anyone rewrite the one figure that says how much unplanned work their team absorbed. Dropped
    rather than 403'd — nothing in the UI offers the field to them, so a request carrying it is a
    script, not somebody's lost edit (and failing the whole PATCH over it is the complaint the
    assignee guard exists to avoid)."""
    team = make_team(name="Acquisition")
    emp = make_user(role="employee", team_id=team.id)
    auth(emp)
    tid = client.post("/api/tasks", json={"title": "Mine"}).json()["id"]

    r = client.patch(f"/api/tasks/{tid}", json={"title": "Mine, renamed",
                                               "origin": ORIGIN_PLANNED})
    assert r.status_code == 200, r.text
    assert r.json()["title"] == "Mine, renamed", "the rest of the edit must still land"
    assert r.json()["origin"] == ORIGIN_ADDED, "their own classification must be untouched"


def test_a_bogus_value_from_a_manager_clears_rather_than_stores(client, auth, make_user, make_team):
    team = make_team(name="Acquisition")
    am = make_user(role="account_manager")
    worker = make_user(role="employee", team_id=team.id)
    auth(am)
    tid = client.post("/api/tasks", json={"title": "Something", "assigned_team_id": team.id,
                                         "assigned_to_id": worker.id}).json()["id"]

    r = client.patch(f"/api/tasks/{tid}", json={"origin": "whenever"})
    assert r.status_code == 200, r.text
    assert r.json()["origin"] is None


# --- an Atrium client card ------------------------------------------------------------------------

def test_an_atrium_card_is_present_and_None():
    """🔴 It can never be classified: the answer comes from the SENTINEL creator's authority to plan,
    and this card was raised in another system by a roster email. Present-and-None rather than absent,
    because a MISSING key is falsy — which is exactly how `mine` answered "not yours" for every client
    card until 2026-08-06 (AGENTS.md §5)."""
    card = atrium_tasks.as_board_card({
        "atrium_id": "stratos:tk_1", "task_id": "tk_1", "client_key": "stratos", "title": "Report"})
    assert "origin" in card
    assert card["origin"] is None


def test_origin_never_crosses_to_atrium():
    """It says how the AGENCY works, not what the client asked for. `FIELD_MAP` has no entry, and
    `to_atrium_fields` drops what it cannot map."""
    assert "origin" not in atrium_tasks.FIELD_MAP
    # `title` rides along to prove the call worked at all — an empty dict would pass this test even if
    # the mapper were broken. (The title -> text swap is inside `maintasks` only, not at this level.)
    assert atrium_tasks.to_atrium_fields({"origin": ORIGIN_ADDED, "title": "x"}) == {"title": "x"}

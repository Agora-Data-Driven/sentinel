"""GET /api/tasks/summary — the per-employee rollup behind the Monitor view.

Asserts (1) it's a management-only surface (403 below team lead), (2) the aggregates are right,
and (3) a team lead only sees their own team.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from app import constants as C
from app.models import Task


@pytest.mark.parametrize("role", [C.ROLE_INTERN, C.ROLE_EMPLOYEE])
def test_summary_forbidden_below_team_lead(client, make_user, auth, role):
    auth(make_user(role))
    assert client.get("/api/tasks/summary").status_code == 403


@pytest.mark.parametrize("role", [C.ROLE_TEAM_LEAD, C.ROLE_ACCOUNT_MANAGER, C.ROLE_ADMIN, C.ROLE_SUPER_ADMIN])
def test_summary_allowed_for_manager(client, make_user, auth, role):
    auth(make_user(role))
    assert client.get("/api/tasks/summary").status_code == 200


def test_summary_aggregates(client, db, make_user, auth):
    manager = make_user(C.ROLE_ADMIN)
    emp = make_user(C.ROLE_EMPLOYEE, name="Ana Reyes")
    overdue_day = date.today() - timedelta(days=3)   # comfortably before "today" in any tz
    db.add_all([
        Task(title="Overdue open", assigned_to_id=emp.id, status=C.TASK_IN_PROGRESS, due_date=overdue_day),
        Task(title="Open no due", assigned_to_id=emp.id, status=C.TASK_TODO),
        Task(title="Done recently", assigned_to_id=emp.id, status=C.TASK_COMPLETED),
    ])
    db.commit()

    auth(manager)
    rows = client.get("/api/tasks/summary").json()
    row = next(r for r in rows if r["user"]["id"] == emp.id)
    assert row["total"] == 3
    assert row["open_total"] == 2          # the two non-completed tasks
    assert row["overdue"] == 1             # only the past-due, non-completed one
    assert row["completed_week"] == 1      # completed with a fresh updated_at
    assert row["counts"][C.TASK_IN_PROGRESS] == 1
    assert row["counts"][C.TASK_COMPLETED] == 1


def test_summary_team_lead_scoped_to_team(client, db, make_user, make_team, auth):
    team_a = make_team(name="Creative")
    team_b = make_team(name="Growth")
    lead = make_user(C.ROLE_TEAM_LEAD, team_id=team_a.id, name="Bong Cruz")
    mine = make_user(C.ROLE_EMPLOYEE, team_id=team_a.id, name="Teammate")
    other = make_user(C.ROLE_EMPLOYEE, team_id=team_b.id, name="Outsider")

    auth(lead)
    rows = client.get("/api/tasks/summary").json()
    ids = {r["user"]["id"] for r in rows}
    assert mine.id in ids
    assert other.id not in ids

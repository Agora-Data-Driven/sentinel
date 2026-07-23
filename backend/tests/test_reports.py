"""GET /api/reports/{report} — the Reports page tabs (Admin).

Every report type must build without error and return the {columns, rows, count} shape. This would
have caught the `tasks` report importing a name (`tasks._can_view`) that no longer exists after
authorization moved into `task_perms` — it 500'd with "Internal server error".
"""
from __future__ import annotations

import pytest

from app import constants as C
from app.models import Client, Task


@pytest.mark.parametrize("report", ["attendance", "gym", "tasks", "team", "leave", "overdue"])
def test_every_report_builds_for_admin(client, make_user, auth, report):
    auth(make_user(C.ROLE_ADMIN))
    r = client.get(f"/api/reports/{report}?from=2026-01-01&to=2026-12-31")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["report"] == report
    assert isinstance(body["columns"], list) and body["columns"]
    assert body["count"] == len(body["rows"])


def test_tasks_report_returns_the_task(client, db, make_user, auth):
    """The specific regression: the Task Summary report lists tasks the viewer can see."""
    auth(make_user(C.ROLE_ADMIN))
    c = Client(name="Acme")
    db.add(c)
    db.flush()
    db.add(Task(title="Ship it", client_id=c.id, priority=C.PRIORITY_MEDIUM, status=C.TASK_TODO))
    db.commit()
    r = client.get("/api/reports/tasks?from=2026-01-01&to=2026-12-31")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["columns"][0] == "Task"
    assert any(row[0] == "Ship it" for row in body["rows"])


def test_tasks_report_csv_export(client, make_user, auth):
    auth(make_user(C.ROLE_ADMIN))
    r = client.get("/api/reports/tasks?from=2026-01-01&to=2026-12-31&export=csv")
    assert r.status_code == 200, r.text
    assert "text/csv" in r.headers.get("content-type", "")

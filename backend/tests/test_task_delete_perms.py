"""Delete a task (AM+ only) and the update-permission fix (non-managers = checklist-only)."""
from __future__ import annotations

import pytest

from app import constants as C
from app.models import Task, TaskComment


def _make_task(db, **kw):
    t = Task(title=kw.pop("title", "T"), **kw)
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


# --- Delete ---------------------------------------------------------------
@pytest.mark.parametrize("role", [C.ROLE_INTERN, C.ROLE_EMPLOYEE, C.ROLE_TEAM_LEAD])
def test_delete_forbidden_below_account_manager(client, db, make_user, auth, role):
    tid = _make_task(db, title="Keep me").id
    auth(make_user(role))
    assert client.delete(f"/api/tasks/{tid}").status_code == 403
    assert db.get(Task, tid) is not None


@pytest.mark.parametrize("role", [C.ROLE_ACCOUNT_MANAGER, C.ROLE_ADMIN, C.ROLE_SUPER_ADMIN])
def test_delete_allowed_for_managers(client, db, make_user, auth, role):
    tid = _make_task(db, title="Bye").id
    db.add(TaskComment(task_id=tid, author_id=make_user(C.ROLE_EMPLOYEE).id, body="hi"))
    db.commit()
    auth(make_user(role))
    assert client.delete(f"/api/tasks/{tid}").status_code == 200
    db.expire_all()
    assert db.get(Task, tid) is None
    # comments cascade with the task
    assert db.query(TaskComment).filter(TaskComment.task_id == tid).count() == 0


def test_delete_missing_task_404(client, make_user, auth):
    auth(make_user(C.ROLE_ADMIN))
    assert client.delete("/api/tasks/999999").status_code == 404


# --- Update permission fix ------------------------------------------------
def test_employee_can_only_toggle_own_checklist(client, db, make_user, auth):
    emp = make_user(C.ROLE_EMPLOYEE)
    t = _make_task(db, title="Mine", assigned_to_id=emp.id)
    auth(emp)
    # checklist-only patch is allowed
    ok = client.patch(f"/api/tasks/{t.id}", json={"checklist": [{"text": "step", "done": True}]})
    assert ok.status_code == 200
    # editing any other field is rejected
    denied = client.patch(f"/api/tasks/{t.id}", json={"title": "Hijacked"})
    assert denied.status_code == 403
    denied2 = client.patch(f"/api/tasks/{t.id}", json={"assigned_to_id": make_user(C.ROLE_EMPLOYEE).id})
    assert denied2.status_code == 403


def test_manager_can_edit_all_fields(client, db, make_user, auth):
    t = _make_task(db, title="Old")
    auth(make_user(C.ROLE_ACCOUNT_MANAGER))
    r = client.patch(f"/api/tasks/{t.id}", json={"title": "New"})
    assert r.status_code == 200
    assert r.json()["title"] == "New"

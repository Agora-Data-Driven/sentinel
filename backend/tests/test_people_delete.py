"""DELETE /api/people/{id} — the sweep must cover EVERY table that points at `users`.

Until 2026-09-03 the route named each dependent table by hand, so every table added after it was
written (body metrics, task sessions, time entries, certifications, growth records …) was missed and
Postgres refused the final delete with a ForeignKeyViolation — "Internal server error" in the
console, and nobody could be deleted at all. The route now reads the FKs off the model metadata.
These tests plant a row in several of the once-missing tables and prove the delete goes through,
that OWNED rows are gone, and that OTHER people's records survive with the reference nulled.
"""
from __future__ import annotations

from datetime import date

from app import constants as C
from app.models import BodyMetric, Certification, Task, TaskSession, User
from app.utils.time import utcnow


def _plant(db, worker, other):
    task = Task(title="Christian's card", status=C.TASK_TODO, created_by_id=worker.id,
                assigned_to_id=worker.id)
    db.add(task)
    db.flush()
    db.add(BodyMetric(user_id=worker.id, date=date(2026, 9, 1)))
    db.add(TaskSession(task_id=task.id, user_id=worker.id, started_at=utcnow()))
    cert = Certification(user_id=other.id, key="meta_campaign_deployment", label="Meta deploy",
                         granted_by_id=worker.id, granted_at=date(2026, 9, 1))
    db.add(cert)
    db.commit()
    return task.id, cert.id


def test_delete_sweeps_tables_the_old_list_missed(client, db, auth, make_user):
    boss = make_user(C.ROLE_SUPER_ADMIN)
    worker = make_user(C.ROLE_EMPLOYEE, email="christian@test.ph")
    other = make_user(C.ROLE_EMPLOYEE, email="other@test.ph")
    task_id, cert_id = _plant(db, worker, other)
    wid = worker.id

    auth(boss)
    r = client.delete(f"/api/people/{wid}")
    assert r.status_code == 200, r.text

    db.expire_all()
    assert db.get(User, wid) is None
    # Owned rows are gone.
    assert db.query(BodyMetric).filter_by(user_id=wid).count() == 0
    assert db.query(TaskSession).filter_by(user_id=wid).count() == 0
    # Other people's records survive, with the reference nulled — never deleted.
    task = db.get(Task, task_id)
    assert task is not None
    assert task.created_by_id is None and task.assigned_to_id is None
    cert = db.get(Certification, cert_id)
    assert cert is not None and cert.user_id == other.id and cert.granted_by_id is None


def test_cannot_delete_yourself(client, auth, make_user):
    boss = make_user(C.ROLE_SUPER_ADMIN)
    auth(boss)
    assert client.delete(f"/api/people/{boss.id}").status_code == 400


def test_delete_is_super_admin_only(client, auth, make_user):
    admin = make_user(C.ROLE_ADMIN)
    worker = make_user(C.ROLE_EMPLOYEE)
    auth(admin)
    assert client.delete(f"/api/people/{worker.id}").status_code == 403

"""Unified shift model: one company-default Shift Template is the base every shift resolves from,
and there is always exactly one default. Covers the Manage-router invariants + the resolution chain.
"""
from __future__ import annotations

import pytest

from app import constants as C
from app.models import ShiftTemplate
from app.routers import manage
from app.services.attendance import effective_shift


def _mk(db, actor, name, start, end, *, is_default=False, brk=60):
    return manage.create_shift_template(
        {"name": name, "start": start, "end": end, "break_min": brk, "is_default": is_default},
        actor, db,
    )


def test_only_one_default_after_creates(db, make_user):
    sa = make_user(role=C.ROLE_SUPER_ADMIN)
    _mk(db, sa, "Day", "08:00", "17:00", is_default=True)
    _mk(db, sa, "PM", "13:00", "22:00", is_default=True)  # this becomes the sole default
    defaults = db.query(ShiftTemplate).filter(ShiftTemplate.is_default.is_(True)).all()
    assert len(defaults) == 1
    assert defaults[0].name == "PM"


def test_update_can_switch_the_default(db, make_user):
    sa = make_user(role=C.ROLE_SUPER_ADMIN)
    a = _mk(db, sa, "Day", "08:00", "17:00", is_default=True)
    b = _mk(db, sa, "PM", "13:00", "22:00")
    manage.update_shift_template(b["id"], {"is_default": True}, sa, db)
    assert db.get(ShiftTemplate, a["id"]).is_default is False
    assert db.get(ShiftTemplate, b["id"]).is_default is True


def test_cannot_delete_the_default_template(db, make_user):
    sa = make_user(role=C.ROLE_SUPER_ADMIN)
    a = _mk(db, sa, "Day", "08:00", "17:00", is_default=True)
    with pytest.raises(Exception) as exc:
        manage.delete_shift_template(a["id"], sa, db)
    assert getattr(exc.value, "status_code", None) == 409


def test_default_template_is_the_resolution_base(db, make_user):
    sa = make_user(role=C.ROLE_SUPER_ADMIN)
    _mk(db, sa, "PM Default", "13:00", "22:00", is_default=True, brk=0)
    emp = make_user(role=C.ROLE_EMPLOYEE)  # no team, no personal template
    sh = effective_shift(db, emp)
    assert (sh.start, sh.end, sh.break_min) == ("13:00", "22:00", 0)
    assert sh.name == "PM Default"

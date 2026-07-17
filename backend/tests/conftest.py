"""Shared pytest fixtures.

Configures a throwaway SQLite database and safe test settings *before* the app is imported
(the engine binds to DATABASE_URL at import time), then rebuilds the schema fresh for every test
so cases are fully isolated. Auth is done by minting the session cookie directly — no dev-login
round-trip needed.
"""
from __future__ import annotations

import os
import pathlib
import tempfile

# --- Must run before importing the app -------------------------------------
_TEST_DB = pathlib.Path(tempfile.gettempdir()) / "sentinel_pytest.db"
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB.as_posix()}"
os.environ["JWT_SECRET"] = "test-secret-not-for-prod"
os.environ["ENVIRONMENT"] = "test"
os.environ["DEV_LOGIN_ENABLED"] = "true"
os.environ["RATE_LIMIT_ENABLED"] = "false"  # never 429 mid-test

import pytest  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

from app import constants as C  # noqa: E402
from app.config import settings  # noqa: E402
from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import LeaveType, Team, User  # noqa: E402
from app.security import create_access_token  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_schema():
    """Rebuild all tables before each test for total isolation."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client():
    # Not used as a context manager: we manage the schema ourselves, so lifespan/startup is skipped.
    return TestClient(app)


@pytest.fixture
def make_team(db):
    def _make(name="Creative", shift_start="08:00", shift_end="17:00", break_min=60):
        team = Team(name=name, shift_start=shift_start, shift_end=shift_end, break_duration_min=break_min)
        db.add(team)
        db.commit()
        db.refresh(team)
        return team
    return _make


@pytest.fixture
def make_user(db):
    _n = {"i": 0}

    def _make(role=C.ROLE_EMPLOYEE, *, email=None, team_id=None, active=True, name=None, **extra):
        _n["i"] += 1
        user = User(
            email=email or f"{role}{_n['i']}@test.ph",
            name=name or role.replace("_", " ").title(),
            role=role, is_active=active, team_id=team_id, **extra,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user
    return _make


@pytest.fixture
def auth(client):
    """Authenticate the client as a given user by setting the session cookie directly."""
    def _auth(user):
        client.cookies.set(settings.cookie_name, create_access_token(user.id))
        return user
    return _auth


@pytest.fixture
def make_leave_type(db):
    def _make(name="Vacation", annual_balance=10.0):
        lt = LeaveType(name=name, annual_balance=annual_balance)
        db.add(lt)
        db.commit()
        db.refresh(lt)
        return lt
    return _make

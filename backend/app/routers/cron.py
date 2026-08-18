"""Scheduled-job endpoints. Called by Cloud Scheduler (shared-secret header) or a Super Admin (session).

Auth: authorized if the ``X-Cron-Key`` header matches ``settings.cron_key`` (when set), OR the caller
is a logged-in Super Admin (so it can be triggered manually from the app for testing).
"""
from __future__ import annotations

import secrets
from datetime import date

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.orm import Session

from ..capabilities import CAP_SYSTEM_RUN_DAILY
from ..config import settings
from ..database import get_db
from ..models import User
from ..security import get_current_user_optional
from ..services import daily
from ..services import permissions as perms_svc

router = APIRouter(prefix="/api/cron", tags=["cron"])


def _authorize(x_cron_key: str | None, user: User | None) -> None:
    """Two independent doors: the Scheduler's shared secret, or a session holding `system.run_daily`.

    The key branch stays a constant-time compare and stays FIRST — an unattended job carries no
    session, and it must not depend on the capability table being readable.
    """
    if settings.cron_key and x_cron_key and secrets.compare_digest(x_cron_key, settings.cron_key):
        return
    if perms_svc.has_cap(user, CAP_SYSTEM_RUN_DAILY):
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to run jobs")


@router.post("/report")
def run_report(
    x_cron_key: str | None = Header(None, alias="X-Cron-Key"),
    user: User | None = Depends(get_current_user_optional),
    db: Session = Depends(get_db),
):
    """Regenerate and republish the personal context report, without the rest of the daily pass.

    Same authorization as `/daily` (cron key or a Super Admin session). It exists because the daily
    pass also rebuilds attendance and mints recurring tasks — real writes nobody wants repeated
    just to refresh a document. Safe to call repeatedly: the report is derived state and the Doc is
    replaced wholesale each time.
    """
    _authorize(x_cron_key, user)
    return daily.publish_report(db)


@router.post("/daily")
def run_daily(
    day: date | None = Query(None, description="Target day (YYYY-MM-DD); defaults to yesterday PH"),
    x_cron_key: str | None = Header(None, alias="X-Cron-Key"),
    user: User | None = Depends(get_current_user_optional),
    db: Session = Depends(get_db),
):
    _authorize(x_cron_key, user)
    return daily.run(db, day)

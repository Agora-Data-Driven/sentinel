"""Reference data for the frontend: teams, clients, and the enum vocabularies used in dropdowns."""
from __future__ import annotations

import hashlib
import hmac
import json
import time
import urllib.error
import urllib.parse
import urllib.request

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..constants import (
    ALL_ROLES,
    GYM_DAY_TYPES,
    ROLE_LABELS,
    SET_TYPES,
)
from ..database import get_db
from ..models import Client, Team, User
from ..security import get_current_user, require_roles
from ..serializers import client_dict, team_dict

router = APIRouter(prefix="/api", tags=["meta"])


@router.get("/academy/config")
def academy_config(user: User = Depends(get_current_user)):
    """Where the Academy tab points its iframe (the mastery engine).

    Signed-in only: the URL is not a secret, but there's no reason to publish our internal
    topology. `embed=1` asks the engine to drop its own header/nav since Sentinel supplies the
    shell. The engine authenticates the viewer itself from the shared portal cookie, which reaches
    it because both hosts sit under agoradatadriven.com.
    """
    base = (settings.skill_mastery_url or "").rstrip("/")
    return {
        "url": (base + "/?embed=1") if base else "",
        # The engine's assistant-only view — Sentinel iframes this as the global floating coach.
        "assistant_url": (base + "/?embed=assistant") if base else "",
        "configured": bool(base),
        # A same-site host is what makes the shared cookie (and so the seamless embed) work.
        "same_site": base.endswith(".agoradatadriven.com") or ".agoradatadriven.com/" in base + "/",
    }


@router.get("/academy/courses")
def academy_courses(user: User = Depends(get_current_user)):
    """The signed-in worker's enrolled courses + progress, for the native Academy dashboard.

    Fetched server-to-server from the mastery engine's HMAC-gated internal endpoint (shared
    platform-sso-key both apps mount). No CORS, no browser credentials. Degrades to an empty
    list (the dashboard then shows an empty state) if the engine is unreachable or unconfigured.
    """
    base = (settings.skill_mastery_url or "").rstrip("/")
    secret = (settings.platform_sso_secret or "").strip()
    embed = (base + "/?embed=1") if base else ""
    if not base or not secret:
        return {"courses": [], "program": "", "engineUrl": embed, "error": "not configured"}
    ts = str(int(time.time()))
    sig = hmac.new(secret.encode(), f"enrollment-progress:{ts}".encode(), hashlib.sha256).hexdigest()
    qs = urllib.parse.urlencode({"email": user.email})
    req = urllib.request.Request(
        f"{base}/api/internal/enrollment-progress?{qs}",
        headers={"x-academy-ts": ts, "x-academy-sig": sig},
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read().decode())
    except (urllib.error.URLError, ValueError, TimeoutError) as e:
        return {"programs": [], "engineUrl": embed, "error": str(e)[:120]}
    return {
        "programs": data.get("programs", []),
        "engineUrl": embed,
        # The mastery engine's own verdict on whether this user is an Academy admin (by email).
        # The Academy tab uses it to default admins straight to the admin view.
        "admin": bool(data.get("admin")),
        "adminUrl": (base + "/academy-admin.html?embed=1") if base else "",
    }


@router.get("/teams")
def teams(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return [team_dict(t) for t in db.execute(select(Team).order_by(Team.name)).scalars().all()]


@router.get("/clients")
def clients(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """The client picker. ACTIVE clients only — a client Atrium no longer lists is deactivated by
    `client_sync`, and offering it on the New Task form would let somebody file fresh work against a
    client that has left. Its existing tasks keep their attribution (see `Client.is_active`)."""
    rows = db.execute(select(Client).where(Client.is_active.is_(True))
                      .order_by(Client.name)).scalars().all()
    return [client_dict(c) for c in rows]


# 🔴 `POST /api/meta/clients` was REMOVED on 2026-08-05, with the Manage → Clients write routes, by
# owner decision: **Atrium owns the client list; Sentinel owns staff.** This one was the quieter of
# the two problems — it let any AM mint a client row with `atrium_client_id` left unset, which is the
# exact state that makes `task_adoption` refuse to run ("its adopted cards will appear twice on the
# board") and makes Send to Atrium unable to address a workspace. `services/client_sync` fills the
# table from Atrium's registry now. A client is created in ATRIUM.


@router.get("/vocab")
def vocab(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """All enum vocabularies in one shot. Task statuses/priorities/labels are DB-backed (editable in
    Manage) — returned as name lists (unchanged shape) plus a `colors` map for inline rendering."""
    from ..services import task_config
    return {
        "roles": [{"value": r, "label": ROLE_LABELS[r]} for r in ALL_ROLES],
        "task_statuses": task_config.statuses(db),
        # The same statuses with their stable key + Atrium stage. `task_statuses` stays a plain
        # name list because that is the shape the board's column loop already consumes; this is
        # the addition, so the UI can say which client stage a column maps to without keying
        # anything off the label (decision D13).
        "task_status_meta": task_config.status_meta(db),
        "priorities": task_config.priorities(db),
        "task_labels": task_config.labels(db),
        "colors": {
            "statuses": task_config.colors(db, "status"),
            "priorities": task_config.colors(db, "priority"),
            "labels": task_config.colors(db, "label"),
        },
        "gym_day_types": GYM_DAY_TYPES,
        "set_types": SET_TYPES,
    }

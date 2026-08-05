"""Internal service-to-service endpoints (no user session).

These are called by sister apps in the Agora ecosystem (e.g. the mastery engine's
Academy admin, which needs the Sentinel people list to offer a name dropdown).
They are gated by an HMAC signature over a timestamp, using the SAME shared secret
the portal signs `ag_sso` with (Secret Manager `platform-sso-key`), which both
services already mount. No new secret, no CORS, no browser credentials: only a
caller holding the shared secret can read these, and the timestamp window blocks
replay. If the secret isn't configured (local dev), the endpoint is disabled.
"""
from __future__ import annotations

import hashlib
import hmac
import time

from fastapi import APIRouter, Header, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from fastapi import Depends

from ..config import settings
from ..constants import NOTIF_TASK_ASSIGNED
from ..database import get_db
from ..models import Client, Task, TaskComment, TaskRequest, User
from ..services import board_mirror
from ..services import development as dev_svc
from ..services import mentor_search as mentor_svc
from ..services import notifications as notif

router = APIRouter(prefix="/api/internal", tags=["internal"])

# How far apart the caller's clock and ours may be (replay window).
_MAX_SKEW_SECONDS = 300


def _verify(ts: str | None, sig: str | None, purpose: str) -> None:
    secret = (settings.platform_sso_secret or "").strip()
    if not secret:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="internal auth not configured")
    if not ts or not sig:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing signature")
    try:
        skew = abs(time.time() - int(ts))
    except (TypeError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="bad timestamp")
    if skew > _MAX_SKEW_SECONDS:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="stale request")
    expected = hmac.new(secret.encode(), f"{purpose}:{ts}".encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="bad signature")


@router.get("/people")
def internal_people(
    x_academy_ts: str | None = Header(default=None),
    x_academy_sig: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """Active users as {email, name, role} — for a sister app's person picker."""
    _verify(x_academy_ts, x_academy_sig, "academy-people")
    rows = db.execute(
        select(User).where(User.is_active.is_(True)).order_by(User.name)
    ).scalars().all()
    return {
        "people": [
            {"email": u.email, "name": u.name or u.email, "role": u.role}
            for u in rows
        ]
    }


@router.get("/user-lookup")
def internal_user_lookup(
    email: str,
    x_academy_ts: str | None = Header(default=None),
    x_academy_sig: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """Is `email` a Sentinel user, and is the account active?

    This is what makes Sentinel the source of truth for "who may sign in with Google": the portal
    (the one app that runs the OAuth flow) calls this on a verified email it doesn't already know,
    and signs the caller in when we say the user is active. Adding someone via People → Add Employee
    is therefore all it takes to enable their Google login; deactivating them blocks it immediately.

    Returns identity only ({found, active, name, role}) — never anything else. HMAC-gated exactly
    like /people (shared `platform-sso-key`, timestamp replay window), so only a caller holding the
    secret can probe the directory.
    """
    _verify(x_academy_ts, x_academy_sig, "user-lookup")
    norm = (email or "").strip().lower()
    user = db.execute(
        select(User).where(func.lower(User.email) == norm)
    ).scalars().first() if norm else None
    if user is None:
        return {"found": False, "active": False, "name": "", "role": ""}
    return {
        "found": True,
        "active": bool(user.is_active),
        "name": user.name or user.email,
        "role": user.role,
    }


@router.post("/task-request")
def internal_task_request(
    payload: dict,
    x_academy_ts: str | None = Header(default=None),
    x_academy_sig: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """Atrium files a CLIENT'S ASK here (decision D3, WP 3.3).

    🔴 This is the inbound half of making Atrium read-only. Its quick-add composer used to write
    straight into `ws["tasks"]`, so anything a client typed during a call became a live card on the
    delivery board — unowned, unestimated, and indistinguishable from work the agency had actually
    committed to. Now the composer posts here and the ask waits for triage; a human turns it into a
    task by accepting it. The client keeps the one thing they genuinely use (capturing an ask
    mid-call) without being able to write onto the delivery board.

    IDEMPOTENT on `source_ref`: Atrium retries, and a client tapping Send twice must not file the
    same ask twice. A repeat returns the EXISTING request with `duplicate: true` rather than an
    error — the caller's job succeeded, and a 4xx would make Atrium show the client a failure for
    something that worked.

    Resolving `client_key` to a Sentinel `Client` is best-effort: an unlinked workspace is a
    configuration gap, not a reason to drop what the client said. The key is always kept.
    """
    _verify(x_academy_ts, x_academy_sig, "task-request")

    client_key = str(payload.get("client") or payload.get("client_key") or "").strip()
    title = str(payload.get("title") or "").strip()
    if not client_key:
        raise HTTPException(status_code=400, detail="client is required")
    if not title:
        raise HTTPException(status_code=400, detail="title is required")

    source_ref = str(payload.get("source_ref") or "").strip() or None
    if source_ref:
        existing = db.execute(
            select(TaskRequest).where(TaskRequest.source_ref == source_ref,
                                      TaskRequest.client_key == client_key)
        ).scalars().first()
        if existing:
            return {"ok": True, "duplicate": True, "id": existing.id, "status": existing.status}

    client = db.execute(
        select(Client).where(Client.atrium_client_id == client_key)
    ).scalars().first()

    req = TaskRequest(
        client_key=client_key,
        client_id=client.id if client else None,
        title=title[:200],
        details=(str(payload.get("details") or "").strip() or None),
        requester_name=(str(payload.get("requester_name") or "").strip()[:160] or None),
        requester_email=(str(payload.get("requester_email") or "").strip()[:200] or None),
        source_ref=source_ref,
    )
    db.add(req)
    db.commit()
    db.refresh(req)

    # Tell the people who trIage. An ask nobody sees is the same as no ask at all, and the client
    # has already been told it was sent.
    notif.notify_managers(db, type=NOTIF_TASK_ASSIGNED,
                          title=f"New client request: {title[:80]}",
                          link="/tasks?requests=1")
    return {"ok": True, "duplicate": False, "id": req.id, "status": req.status,
            "client_linked": client is not None}


@router.post("/task-feedback")
def internal_task_feedback(
    payload: dict,
    x_academy_ts: str | None = Header(default=None),
    x_academy_sig: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """The REVERSE CHANNEL: a client's comment or change request reaches the Sentinel row (D4).

    🔴 This is the half that makes the projection a conversation rather than a broadcast. Sentinel
    has pushed cards TO the client since 0.1/0.2, but anything the client said back lived only in
    Atrium's workspace JSON — so the team found out by re-reading a client's board, which nobody
    does. Now the words land on the task where the work is managed.

    `kind`:
      * "comment" — appended to the task's thread, attributed to the client by NAME
        (a client has no `users` row and must never need one).
      * "changes" — the same, plus `client_changes_open` +1, which is what puts the red pill on
        the card. Deliberately NOT `review_state`: that is the internal approval gate (D5), and a
        client must not be able to satisfy or block a team lead's sign-off.

    The task is found by `atrium_task_id` — the link 0.1 established — so this works only for a
    card Sentinel actually published. A stray id is a 404 and never creates anything.

    Idempotent on `source_ref` (Atrium's comment id): a retry must not double-count a change
    request, or the pill would keep climbing and never clear.
    """
    _verify(x_academy_ts, x_academy_sig, "task-feedback")

    atrium_id = str(payload.get("atrium_task_id") or "").strip()
    body = str(payload.get("body") or "").strip()
    kind = str(payload.get("kind") or "comment").strip().lower()
    if not atrium_id or not body:
        raise HTTPException(status_code=400, detail="atrium_task_id and body are required")
    if kind not in ("comment", "changes"):
        raise HTTPException(status_code=400, detail="kind must be comment or changes")

    # 🔴 `atrium_task_id` holds Atrium's RAW task id (see task_bridge.publish), not the composite
    # "atrium:<key>:<id>" the deep links use — and that id is only unique WITHIN a workspace. So
    # the client key narrows it whenever the caller sends one and it resolves to a linked client;
    # without that, two clients whose workspaces happen to mint the same id would cross-post each
    # other's feedback. A tolerated fallback (no key, or an unlinked workspace) still matches on
    # the id alone, which is what old callers and unlinked workspaces need.
    q = select(Task).where(Task.atrium_task_id == atrium_id)
    client_key = str(payload.get("client") or "").strip()
    if client_key:
        owner = db.execute(
            select(Client).where(Client.atrium_client_id == client_key)
        ).scalars().first()
        if owner:
            q = q.where(Task.client_id == owner.id)
    task = db.execute(q).scalars().first()
    if not task:
        raise HTTPException(status_code=404, detail="No Sentinel task is linked to that card")

    source_ref = str(payload.get("source_ref") or "").strip()
    marker = f"[atrium:{source_ref}]" if source_ref else ""
    if marker:
        seen = db.execute(
            select(TaskComment).where(TaskComment.task_id == task.id,
                                      TaskComment.body.like(f"%{marker}%"))
        ).scalars().first()
        if seen:
            return {"ok": True, "duplicate": True, "comment_id": seen.id,
                    "open_changes": task.client_changes_open or 0}

    author = str(payload.get("author_name") or "").strip()[:160] or "The client"
    comment = TaskComment(
        task_id=task.id,
        author_id=None,            # a client is not a user — see the model's note
        client_author=author,
        # The de-dupe marker rides in the body so no extra column is needed for a value only this
        # endpoint ever reads. It is stripped for display by the frontend.
        body=(body + (f"\n{marker}" if marker else "")),
    )
    db.add(comment)
    if kind == "changes":
        task.client_changes_open = (task.client_changes_open or 0) + 1
    db.commit()
    db.refresh(comment)

    # Tell whoever owns the work. A client's words nobody sees are the status quo this replaces.
    target = task.assigned_to_id or task.account_manager_id
    if target:
        notif.notify(db, user_id=target, type=NOTIF_TASK_ASSIGNED,
                     title=("Client requested changes: " if kind == "changes" else "Client commented: ")
                           + task.title[:70],
                     link=f"/tasks?open={task.id}")
    elif task.assigned_team_id:
        notif.notify_managers(db, type=NOTIF_TASK_ASSIGNED,
                              title=f"Client feedback on {task.title[:70]}",
                              link=f"/tasks?open={task.id}", team_id=task.assigned_team_id)
    return {"ok": True, "duplicate": False, "comment_id": comment.id,
            "open_changes": task.client_changes_open or 0}


@router.get("/board")
def internal_board(
    x_academy_ts: str | None = Header(default=None),
    x_academy_sig: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """This board's LIVE tasks in Atrium's task-dict shape — for Atrium's operator console.

    🔴 STAFF-ONLY, and the caller is what makes that true. There is no user session here, so this
    endpoint cannot check a role: it trusts the HMAC, and the one caller is Atrium's
    `/admin/atrium` console, which is itself behind `is_superadmin()`. Anything mounted on this
    payload therefore has to be safe for the delivery team and NOT for a client — which is exactly
    who reads that console. The CLIENT-facing path is the other direction entirely
    (`services/task_bridge.py`, six fields, pushed by us), and the two must never be merged.

    Why Atrium needs it: its console used to assemble the board from each client's workspace JSON,
    i.e. from the client-safe projections, so it could only show work somebody had already shared
    with a client. See `services/board_mirror.py` for the whole argument and the field mapping.
    """
    _verify(x_academy_ts, x_academy_sig, "board")
    return {"ok": True, "tasks": board_mirror.board(db)}


@router.get("/holistic-profile")
def internal_holistic_profile(
    email: str,
    x_academy_ts: str | None = Header(default=None),
    x_academy_sig: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """A compact digest of `email`'s whole-person development, for the Mastery Engine AI coach.

    The coach calls this server-to-server (HMAC-gated, shared platform-sso-key) so the SAME assistant
    that knows the worker's learning can also speak to their body-fat/PRs, career goals, required
    reading, and personal obstacles. It's always the user's OWN data (the coach acts on their behalf),
    so no manager check applies here. Unknown/inactive email → an empty profile (the coach then simply
    has no holistic context and behaves as before).
    """
    _verify(x_academy_ts, x_academy_sig, "holistic-profile")
    norm = (email or "").strip().lower()
    user = db.execute(
        select(User).where(func.lower(User.email) == norm)
    ).scalars().first() if norm else None
    if user is None or not user.is_active:
        return {"found": False, "profile": None}
    return {"found": True, "profile": dev_svc.holistic_digest(db, user)}


@router.get("/growth-detail")
def internal_growth_detail(
    email: str,
    ids: str = "",
    x_academy_ts: str | None = Header(default=None),
    x_academy_sig: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """Full bodies for specific growth-journal entries — the "big" half of small-to-big retrieval.

    `holistic-profile` hands the coach a COMPLETE index of the worker's journal (every entry's title,
    uncapped) but no bodies, because the journal grows without bound and most turns need none of it.
    When a turn does bear on an entry, the coach names its ids here and gets the text back WHOLE.

    Why the index is complete and only the bodies are lazy: the coach decides "you have no note about
    X" by not seeing X in the index. If the index were sampled, that inference would be a confident
    lie — the failure that made a 600-char cap on `other_info` deny a list the worker was looking at
    on their own screen. A retrieval MISS here is recoverable (the title is still listed, so the
    coach can say "you have a note called X I haven't opened"); a missing title is not.

    `ids` is a comma-separated list, capped at `MAX_GROWTH_DETAIL_IDS` entries per call — a limit on
    the request, never on any entry's text. Entries are scoped to the owner, so unknown or
    other-people's ids are simply absent from the response rather than an error.

    Always the user's OWN journal (the coach acts on their behalf), so no manager check applies.
    Unknown/inactive email → an empty result and the coach stays ungrounded, exactly as before.
    """
    _verify(x_academy_ts, x_academy_sig, "growth-detail")
    norm = (email or "").strip().lower()
    user = db.execute(
        select(User).where(func.lower(User.email) == norm)
    ).scalars().first() if norm else None
    if user is None or not user.is_active:
        return {"found": False, "entries": []}
    wanted: list[int] = []
    for part in (ids or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            wanted.append(int(part))
        except ValueError:
            # A malformed id is the caller's bug, not a reason to fail the worker's whole turn —
            # skip it and serve whatever else was asked for.
            continue
    return {"found": True, "entries": dev_svc.growth_details(db, user.id, wanted)}


@router.get("/mentor-search")
def internal_mentor_search(
    email: str,
    q: str = "",
    mentor: str = "",
    limit: int = mentor_svc.DEFAULT_LIMIT,
    x_academy_ts: str | None = Header(default=None),
    x_academy_sig: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """The passages from `email`'s Mentor Library that bear on `q` — retrieval for the AI coach.

    This is what makes "what would Nick say about my plan?" and "act as Nick and mentor me"
    answerable. The library is far too large to hand over (one creator can be ~1M words), and the
    holistic digest could only ever list titles — so the coach asks this instead and gets back the
    handful of relevant passages to reason from.

    `mentor` narrows to one person and is matched loosely ("nick" → "Nick Saraev"), because that is
    how people actually ask. `matched_mentor` lets the caller distinguish "that mentor isn't in
    their library" from "that mentor never covered this" — two answers the coach must never blur.

    Always the user's OWN library (the coach acts on their behalf), so no manager check applies.
    Unknown/inactive email → an empty result and the coach simply stays ungrounded, as before.
    """
    _verify(x_academy_ts, x_academy_sig, "mentor-search")
    norm = (email or "").strip().lower()
    user = db.execute(
        select(User).where(func.lower(User.email) == norm)
    ).scalars().first() if norm else None
    if user is None or not user.is_active:
        return {"found": False, "mentors": [], "mentor": "", "matched_mentor": False,
                "excerpts": []}
    out = mentor_svc.search(db, user.id, q, mentor=mentor, limit=limit)
    out["found"] = True
    out["mentors"] = mentor_svc.roster(db, user.id)
    return out

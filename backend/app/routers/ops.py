"""The operating-system surfaces (2026-09-02): Today, the calendar projection, Clients, Operations,
AI task drafting and certifications. Thin — every rule lives in `services/`.

    GET  /api/ops/today                       the specialist's landing payload (time + training)
    GET  /api/ops/calendar?from&to&mine       dated records, projected (no table)
    GET  /api/ops/clients                     health per account            [clients.view]
    GET  /api/ops/clients/{id}                one account in depth           [clients.view]
    PATCH /api/ops/clients/{id}/account-manager                             [clients.assign_am]
    GET  /api/ops/exceptions                  the COO's list + capacity     [ops.view]
    POST /api/ops/ai/draft-tasks              plain words → proposals       [ai.draft]
    GET  /api/ops/certifications?user_id=     a person's credentials
    POST /api/ops/certifications/{user_id}    grant / update                [certifications.manage]
    DELETE /api/ops/certifications/{id}       revoke                        [certifications.manage]
    GET  /api/ops/meta                        hold kinds, stages, health rule (for the UI)
"""
from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..capabilities import (CAP_AI_DRAFT, CAP_CERTIFICATIONS_MANAGE, CAP_CLIENTS_ASSIGN_AM,
                            CAP_CLIENTS_VIEW, CAP_OPS_VIEW)
from ..constants import HOLD_KINDS, ROLE_ACCOUNT_MANAGER, STAGE_LABELS, WORKER_STAGES
from ..database import get_db
from ..models import Certification, Client, User
from ..schemas import AccountManagerIn, AiDraftIn, CertificationIn
from ..security import get_current_user, require_cap
from ..serializers import user_public
from ..services import ai_draft, audit, calendar_view, client_health, operations, today
from ..services import development as dev_svc
from ..utils.time import today_ph

router = APIRouter(prefix="/api/ops", tags=["ops"])


@router.get("/meta")
def meta(user: User = Depends(get_current_user)):
    """Vocabulary for the UI. Session-gated like every other endpoint — it leaks nothing sensitive,
    but an unauthenticated read here would be the one exception on the whole API."""
    return {
        "hold_kinds": HOLD_KINDS,
        "stages": [{"key": k, "label": STAGE_LABELS[k]} for k in WORKER_STAGES],
        "health_rule": client_health.HEALTH_RULE,
        "ai_enabled": ai_draft.enabled(),
    }


@router.get("/today")
def today_payload(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return today.payload(db, user)


@router.get("/calendar")
def calendar(frm: date | None = Query(None, alias="from"), to: date | None = None,
             mine: bool = False, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    t = today_ph()
    frm = frm or (t - timedelta(days=t.weekday()))
    to = to or (frm + timedelta(days=6))
    return calendar_view.events(db, user, frm, to, mine=mine)


# --- Clients ------------------------------------------------------------------------------------------

@router.get("/clients", dependencies=[Depends(require_cap(CAP_CLIENTS_VIEW))])
def clients(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return {"clients": client_health.rollup(db, user), "rule": client_health.HEALTH_RULE}


@router.get("/clients/{client_id}", dependencies=[Depends(require_cap(CAP_CLIENTS_VIEW))])
def client_overview(client_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    c = db.get(Client, client_id)
    if not c:
        raise HTTPException(status_code=404, detail="Client not found")
    return client_health.overview(db, c, user)


@router.patch("/clients/{client_id}/account-manager", dependencies=[Depends(require_cap(CAP_CLIENTS_ASSIGN_AM))])
def set_account_manager(client_id: int, payload: AccountManagerIn,
                        user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    c = db.get(Client, client_id)
    if not c:
        raise HTTPException(status_code=404, detail="Client not found")
    am = None
    if payload.account_manager_id is not None:
        am = db.get(User, payload.account_manager_id)
        if not am or not am.is_active:
            raise HTTPException(status_code=400, detail="That person isn't an active staff member.")
    old = c.account_manager_id
    c.account_manager_id = am.id if am else None
    db.commit()
    audit.record(db, actor_id=user.id, table_name="clients", record_id=c.id, action="assign_am",
                 old={"account_manager_id": old}, new={"account_manager_id": c.account_manager_id})
    return {"ok": True, "client_id": c.id, "account_manager": user_public(am)}


# --- Operations ---------------------------------------------------------------------------------------

@router.get("/exceptions", dependencies=[Depends(require_cap(CAP_OPS_VIEW))])
def exceptions(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return operations.exceptions(db, user)


# --- AI drafting --------------------------------------------------------------------------------------

@router.post("/ai/draft-tasks", dependencies=[Depends(require_cap(CAP_AI_DRAFT))])
def draft_tasks(payload: AiDraftIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Propose tasks from plain words. NOTHING is created here — the UI posts each accepted proposal
    to `POST /api/tasks`, where every permission, label and origin rule applies as usual."""
    client = db.get(Client, payload.client_id) if payload.client_id else None
    if payload.client_id and not client:
        raise HTTPException(status_code=404, detail="Client not found")
    proposals, err = ai_draft.draft(db, user, payload.text, client)
    if proposals is None:
        # 503, not 500: the feature is unavailable, the fallback (New Task) is not.
        raise HTTPException(status_code=503, detail=err or "AI drafting is unavailable right now.")
    return {"proposals": proposals, "client_id": client.id if client else None}


# --- Certifications ------------------------------------------------------------------------------------

def _cert_dict(c: Certification, db: Session) -> dict:
    by = db.get(User, c.granted_by_id) if c.granted_by_id else None
    return {
        "id": c.id, "user_id": c.user_id, "key": c.key, "label": c.label,
        "granted_at": c.granted_at.isoformat(), "expires_at": c.expires_at.isoformat() if c.expires_at else None,
        "valid": c.is_valid(today_ph()), "evidence_url": c.evidence_url, "note": c.note,
        "granted_by": user_public(by),
    }


@router.get("/certifications")
def list_certifications(user_id: int | None = None, user: User = Depends(get_current_user),
                        db: Session = Depends(get_db)):
    """Somebody's credentials — your own, or anyone's if you may see their development record."""
    target = db.get(User, user_id) if user_id else user
    if not target:
        raise HTTPException(status_code=404, detail="Person not found")
    if target.id != user.id and not dev_svc.can_view(user, target) and user.role != ROLE_ACCOUNT_MANAGER:
        raise HTTPException(status_code=403, detail="Not permitted")
    rows = db.execute(select(Certification).where(Certification.user_id == target.id)
                      .order_by(Certification.label)).scalars().all()
    return {"user": user_public(target), "certifications": [_cert_dict(c, db) for c in rows]}


@router.post("/certifications/{user_id}", dependencies=[Depends(require_cap(CAP_CERTIFICATIONS_MANAGE))])
def grant_certification(user_id: int, payload: CertificationIn,
                        user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(status_code=404, detail="Person not found")
    key = payload.key.strip().lower().replace(" ", "_")
    row = db.execute(select(Certification).where(Certification.user_id == user_id,
                                                 Certification.key == key)).scalar_one_or_none()
    if row is None:
        row = Certification(user_id=user_id, key=key, label=payload.label.strip(),
                            granted_at=payload.granted_at or today_ph(), granted_by_id=user.id)
        db.add(row)
    else:
        row.label = payload.label.strip()
        row.granted_at = payload.granted_at or row.granted_at
        row.granted_by_id = user.id
    row.expires_at = payload.expires_at
    row.evidence_url = payload.evidence_url
    row.note = payload.note
    db.commit()
    audit.record(db, actor_id=user.id, table_name="certifications", record_id=row.id, action="grant",
                 new={"user_id": user_id, "key": key, "expires_at": str(payload.expires_at) if payload.expires_at else None})
    return _cert_dict(row, db)


@router.delete("/certifications/{cert_id}", dependencies=[Depends(require_cap(CAP_CERTIFICATIONS_MANAGE))])
def revoke_certification(cert_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = db.get(Certification, cert_id)
    if not row:
        raise HTTPException(status_code=404, detail="Certification not found")
    old = {"user_id": row.user_id, "key": row.key}
    db.delete(row)
    db.commit()
    audit.record(db, actor_id=user.id, table_name="certifications", record_id=cert_id, action="revoke", old=old)
    return {"ok": True}

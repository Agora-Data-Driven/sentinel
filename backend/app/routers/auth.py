"""Auth: email+password login, Google OAuth (Sign in with Google), change-password.

DEV_LOGIN (pick a seeded user, no password) stays available ONLY when DEV_LOGIN_ENABLED=true —
it is turned OFF in production so the open dropdown can never be used there.
"""
from __future__ import annotations

import json
import secrets as _secrets
import urllib.parse
import urllib.request

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..models import Team, User
from ..schemas import ChangePasswordIn, DevLoginIn, LoginIn
from ..security import create_access_token, get_current_user
from ..serializers import user_full
from ..utils.passwords import hash_password, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _set_cookie(response: Response, user_id: int) -> None:
    token = create_access_token(user_id)
    response.set_cookie(
        key=settings.cookie_name, value=token, httponly=True, secure=settings.secure_cookies,
        samesite="lax", max_age=settings.jwt_expire_minutes * 60, path="/",
    )


def _user_by_email(db: Session, email: str) -> User | None:
    return db.execute(select(User).where(User.email == email.strip().lower())).scalar_one_or_none()


@router.get("/config")
def auth_config():
    """Tells the login page which sign-in methods are available."""
    return {
        "dev_login_enabled": settings.dev_login_active,
        "google_enabled": bool(settings.google_client_id),
        "app_name": settings.app_name,
    }


# --- Password login --------------------------------------------------------
@router.post("/login")
def login(payload: LoginIn, response: Response, db: Session = Depends(get_db)):
    user = _user_by_email(db, payload.email)
    if not user or not user.is_active or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
    _set_cookie(response, user.id)
    team = db.get(Team, user.team_id) if user.team_id else None
    return {"ok": True, "user": user_full(user, team)}


@router.post("/change-password")
def change_password(payload: ChangePasswordIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if len(payload.new_password or "") < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    # If the user already has a password, require the current one; first-time set is allowed.
    if user.password_hash and not verify_password(payload.current_password or "", user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    user.password_hash = hash_password(payload.new_password)
    db.commit()
    return {"ok": True}


# --- Dev login (only when explicitly enabled) ------------------------------
@router.get("/dev-users")
def dev_users(db: Session = Depends(get_db)):
    if not settings.dev_login_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dev login disabled")
    users = db.execute(select(User).where(User.is_active.is_(True)).order_by(User.role)).scalars().all()
    return [{"id": u.id, "name": u.name, "email": u.email, "role": u.role} for u in users]


@router.post("/dev-login")
def dev_login(payload: DevLoginIn, response: Response, db: Session = Depends(get_db)):
    if not settings.dev_login_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dev login disabled")
    user = db.get(User, payload.user_id) if payload.user_id else _user_by_email(db, payload.email or "")
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    _set_cookie(response, user.id)
    team = db.get(Team, user.team_id) if user.team_id else None
    return {"ok": True, "user": user_full(user, team)}


@router.get("/me")
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    team = db.get(Team, user.team_id) if user.team_id else None
    return user_full(user, team)


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(settings.cookie_name, path="/")
    return {"ok": True}


# --- Google OAuth 2.0 ------------------------------------------------------
_STATE_COOKIE = "g_oauth_state"


@router.get("/google/login")
def google_login(response: Response):
    if not settings.google_client_id:
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Google sign-in not configured")
    state = _secrets.token_urlsafe(24)
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
    }
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(params)
    resp = RedirectResponse(url=url, status_code=302)
    resp.set_cookie(_STATE_COOKIE, state, max_age=600, httponly=True,
                    secure=settings.secure_cookies, samesite="lax", path="/")
    return resp


@router.get("/google/callback")
def google_callback(request: Request, code: str = Query(None), state: str = Query(None), db: Session = Depends(get_db)):
    if not settings.google_client_id:
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Google sign-in not configured")
    if not code or not state or state != request.cookies.get(_STATE_COOKIE):
        return RedirectResponse(url="/login?error=google", status_code=302)

    # Exchange the auth code for tokens (stdlib urllib — no extra deps).
    try:
        token_data = urllib.parse.urlencode({
            "code": code,
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "redirect_uri": settings.google_redirect_uri,
            "grant_type": "authorization_code",
        }).encode()
        with urllib.request.urlopen("https://oauth2.googleapis.com/token", data=token_data, timeout=10) as r:
            tokens = json.loads(r.read().decode())
        access_token = tokens.get("access_token")
        req = urllib.request.Request(
            "https://openidconnect.googleapis.com/v1/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            info = json.loads(r.read().decode())
    except Exception:
        return RedirectResponse(url="/login?error=google", status_code=302)

    email = (info.get("email") or "").strip().lower()
    user = _user_by_email(db, email) if email else None
    if not user or not user.is_active:
        # Only people who've been added (by email) may enter.
        return RedirectResponse(url="/login?error=noaccount", status_code=302)

    resp = RedirectResponse(url="/dashboard", status_code=302)
    _set_cookie(resp, user.id)
    resp.delete_cookie(_STATE_COOKIE, path="/")
    return resp

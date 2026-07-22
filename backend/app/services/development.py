"""Assembly for the holistic development profile.

Two shapes are built here and shared by both the worker-facing router and the internal HMAC endpoint
the Mastery Engine coach calls:

    full_profile(db, user)   -> the complete profile for the Development hub / manager view
    holistic_digest(db, user) -> a compact, top-N digest tuned for LLM context

Plus can_view(viewer, target): owner, admins, and the target's team lead may read a profile.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..constants import ADMIN_ROLES, ROLE_TEAM_LEAD
from ..models import (
    BodyMetric,
    CareerAchievement,
    DevelopmentProfile,
    GrowthItem,
    PersonalRecord,
    ProfessionalGoal,
    ReadingItem,
    ReadingProgress,
    User,
)
from ..serializers import (
    achievement_dict,
    body_metric_dict,
    development_profile_dict,
    goal_dict,
    growth_item_dict,
    personal_record_dict,
    reading_item_dict,
    user_public,
)


def can_view(viewer: User, target: User) -> bool:
    """Who may read a worker's Development profile: themselves, admins, or their team lead."""
    if viewer.id == target.id:
        return True
    if viewer.role in ADMIN_ROLES:
        return True
    if viewer.role == ROLE_TEAM_LEAD and viewer.team_id and viewer.team_id == target.team_id:
        return True
    return False


def _metrics(db: Session, user_id: int) -> list[BodyMetric]:
    return list(
        db.execute(
            select(BodyMetric)
            .where(BodyMetric.user_id == user_id)
            .order_by(BodyMetric.date.desc(), BodyMetric.id.desc())
        ).scalars()
    )


def _prs(db: Session, user_id: int) -> list[PersonalRecord]:
    return list(
        db.execute(
            select(PersonalRecord)
            .where(PersonalRecord.user_id == user_id)
            .order_by(PersonalRecord.exercise_name)
        ).scalars()
    )


def _achievements(db: Session, user_id: int) -> list[CareerAchievement]:
    return list(
        db.execute(
            select(CareerAchievement)
            .where(CareerAchievement.user_id == user_id)
            .order_by(CareerAchievement.achieved_on.desc().nullslast(), CareerAchievement.id.desc())
        ).scalars()
    )


def _goals(db: Session, user_id: int) -> list[ProfessionalGoal]:
    return list(
        db.execute(
            select(ProfessionalGoal)
            .where(ProfessionalGoal.user_id == user_id)
            .order_by(ProfessionalGoal.created_at.desc())
        ).scalars()
    )


def _growth(db: Session, user_id: int) -> list[GrowthItem]:
    return list(
        db.execute(
            select(GrowthItem)
            .where(GrowthItem.user_id == user_id)
            .order_by(GrowthItem.created_at.desc())
        ).scalars()
    )


def _profile(db: Session, user_id: int) -> DevelopmentProfile | None:
    return db.execute(
        select(DevelopmentProfile).where(DevelopmentProfile.user_id == user_id)
    ).scalar_one_or_none()


def reading_with_progress(db: Session, user_id: int) -> list[dict]:
    """The whole canon, each item merged with this worker's progress on it."""
    items = list(
        db.execute(select(ReadingItem).order_by(ReadingItem.sort_order, ReadingItem.title)).scalars()
    )
    prog = {
        p.reading_item_id: p
        for p in db.execute(
            select(ReadingProgress).where(ReadingProgress.user_id == user_id)
        ).scalars()
    }
    return [reading_item_dict(it, prog.get(it.id)) for it in items]


def full_profile(db: Session, user: User) -> dict:
    """The complete Development profile — used by the hub and the manager read view."""
    metrics = _metrics(db, user.id)
    return {
        "user": user_public(user),
        "physical": {
            "metrics": [body_metric_dict(m) for m in metrics],
            "latest": body_metric_dict(metrics[0]) if metrics else None,
            "prs": [personal_record_dict(p) for p in _prs(db, user.id)],
        },
        "career": {
            "profile": development_profile_dict(_profile(db, user.id)),
            "achievements": [achievement_dict(a) for a in _achievements(db, user.id)],
            "goals": [goal_dict(g) for g in _goals(db, user.id)],
        },
        "growth": [growth_item_dict(g) for g in _growth(db, user.id)],
        "reading": reading_with_progress(db, user.id),
    }


def _pr_line(p: PersonalRecord) -> str:
    unit = p.weight_unit or "kg"
    return f"{p.exercise_name}: {p.weight_value:g}{unit} x{p.reps}"


def holistic_digest(db: Session, user: User) -> dict:
    """A compact, token-frugal digest for the AI coach (top-N of each pillar)."""
    metrics = _metrics(db, user.id)
    latest = metrics[0] if metrics else None
    prs = _prs(db, user.id)
    profile = _profile(db, user.id)
    achievements = _achievements(db, user.id)
    goals = _goals(db, user.id)
    growth = _growth(db, user.id)
    reading = reading_with_progress(db, user.id)

    reading_now = [r["title"] for r in reading if r["progress"]["status"] == "reading"][:8]
    reading_done = [r["title"] for r in reading if r["progress"]["status"] == "done"][:12]
    obstacles = [g.title for g in growth if g.kind == "obstacle" and g.status != "archived"][:6]
    reflections = [g.title for g in growth if g.kind in ("reflection", "note")][:6]

    return {
        "name": user.name,
        "physical": {
            "body_fat_pct": latest.body_fat_pct if latest else None,
            "weight_kg": latest.weight_kg if latest else None,
            "as_of": latest.date.isoformat() if latest else None,
            "recent_prs": [_pr_line(p) for p in prs[:10]],
        },
        "career": {
            "headline": profile.headline if profile else None,
            "has_resume": bool(profile and profile.resume_text),
            "achievements": [a.title for a in achievements[:10]],
            "goals": [
                {
                    "title": g.title,
                    "status": g.status,
                    "progress": g.progress_pct,
                    "target": g.target_date.isoformat() if g.target_date else None,
                }
                for g in goals[:10]
            ],
        },
        "reading": {"reading_now": reading_now, "done": reading_done},
        "growth": {"obstacles": obstacles, "reflections": reflections},
    }

"""Holistic Development: the worker's physical + career + reading + growth data.

Owner-only writes; reads allowed for the owner, admins, and the owner's team lead (see
``services.development.can_view``). The AI coach reads a compact digest of the SAME data over the
internal HMAC endpoint (see routers/internal.py).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..constants import ROLE_ADMIN
from ..database import get_db
from ..models import (
    BodyMetric,
    CareerAchievement,
    DevelopmentProfile,
    GrowthItem,
    PersonalRecord,
    ProfessionalGoal,
    ReadingItem,
    ReadingProgress,
    Skill,
    User,
)
from ..schemas import (
    AchievementIn,
    AchievementUpdateIn,
    BodyMetricIn,
    GoalIn,
    GoalUpdateIn,
    GrowthItemIn,
    GrowthItemUpdateIn,
    PersonalRecordIn,
    PersonalRecordUpdateIn,
    ReadingItemIn,
    ReadingItemUpdateIn,
    ReadingProgressIn,
    ResumeIn,
    SkillIn,
    SkillUpdateIn,
)
from ..security import get_current_user, require_min_role
from ..serializers import (
    achievement_dict,
    body_metric_dict,
    development_profile_dict,
    goal_dict,
    growth_item_dict,
    personal_record_dict,
    reading_item_dict,
    skill_dict,
)
from ..services import development as dev_svc
from ..utils.time import today_ph, utcnow

router = APIRouter(prefix="/api/development", tags=["development"])


def _apply(obj, payload, fields: list[str]) -> None:
    """Copy any non-None fields from a Pydantic update payload onto a model row."""
    data = payload.model_dump(exclude_unset=True)
    for f in fields:
        if f in data and data[f] is not None:
            setattr(obj, f, data[f])


def _own(db: Session, model, row_id: int, user: User):
    """Fetch a row and 404 unless it belongs to the current user (no data leak by id)."""
    obj = db.get(model, row_id)
    if not obj or obj.user_id != user.id:
        raise HTTPException(status_code=404, detail="Not found")
    return obj


# --- Read (owner + manager) -------------------------------------------------
@router.get("/me")
def my_development(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return dev_svc.full_profile(db, user)


@router.get("/user/{user_id}")
def user_development(user_id: int, viewer: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Manager read: a report's full profile (read-only). 403 unless owner/admin/their team lead."""
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if not dev_svc.can_view(viewer, target):
        raise HTTPException(status_code=403, detail="Not allowed to view this profile")
    return dev_svc.full_profile(db, target)


# --- Body metrics -----------------------------------------------------------
@router.post("/body-metrics")
def add_body_metric(payload: BodyMetricIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    m = BodyMetric(
        user_id=user.id,
        date=payload.date or today_ph(),
        weight_kg=payload.weight_kg,
        body_fat_pct=payload.body_fat_pct,
        notes=payload.notes,
    )
    db.add(m)
    db.commit()
    return body_metric_dict(m)


@router.delete("/body-metrics/{metric_id}", status_code=204)
def delete_body_metric(metric_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.delete(_own(db, BodyMetric, metric_id, user))
    db.commit()


# --- Personal records -------------------------------------------------------
@router.post("/prs")
def add_pr(payload: PersonalRecordIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    p = PersonalRecord(
        user_id=user.id,
        exercise_name=payload.exercise_name,
        weight_value=payload.weight_value,
        weight_unit=payload.weight_unit,
        reps=payload.reps,
        detail=payload.detail,
        achieved_on=payload.achieved_on,
        notes=payload.notes,
    )
    db.add(p)
    db.commit()
    return personal_record_dict(p)


@router.patch("/prs/{pr_id}")
def update_pr(pr_id: int, payload: PersonalRecordUpdateIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    p = _own(db, PersonalRecord, pr_id, user)
    _apply(p, payload, ["exercise_name", "weight_value", "weight_unit", "reps", "detail", "achieved_on", "notes"])
    db.commit()
    return personal_record_dict(p)


@router.delete("/prs/{pr_id}", status_code=204)
def delete_pr(pr_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.delete(_own(db, PersonalRecord, pr_id, user))
    db.commit()


# --- Resume / career profile ------------------------------------------------
@router.patch("/resume")
def update_resume(payload: ResumeIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    prof = db.execute(
        select(DevelopmentProfile).where(DevelopmentProfile.user_id == user.id)
    ).scalar_one_or_none()
    if not prof:
        prof = DevelopmentProfile(user_id=user.id)
        db.add(prof)
    data = payload.model_dump(exclude_unset=True)
    for f in ("headline", "resume_text", "resume_file_url"):
        if f in data:
            setattr(prof, f, data[f])
    prof.updated_at = utcnow()
    db.commit()
    return development_profile_dict(prof)


# --- Career achievements ----------------------------------------------------
@router.post("/achievements")
def add_achievement(payload: AchievementIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    a = CareerAchievement(user_id=user.id, title=payload.title, description=payload.description, achieved_on=payload.achieved_on)
    db.add(a)
    db.commit()
    return achievement_dict(a)


@router.patch("/achievements/{achievement_id}")
def update_achievement(achievement_id: int, payload: AchievementUpdateIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    a = _own(db, CareerAchievement, achievement_id, user)
    _apply(a, payload, ["title", "description", "achieved_on"])
    db.commit()
    return achievement_dict(a)


@router.delete("/achievements/{achievement_id}", status_code=204)
def delete_achievement(achievement_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.delete(_own(db, CareerAchievement, achievement_id, user))
    db.commit()


# --- Professional goals -----------------------------------------------------
@router.post("/goals")
def add_goal(payload: GoalIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    g = ProfessionalGoal(
        user_id=user.id,
        title=payload.title,
        description=payload.description,
        target_date=payload.target_date,
        status=payload.status,
        progress_pct=payload.progress_pct,
    )
    db.add(g)
    db.commit()
    return goal_dict(g)


@router.patch("/goals/{goal_id}")
def update_goal(goal_id: int, payload: GoalUpdateIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    g = _own(db, ProfessionalGoal, goal_id, user)
    _apply(g, payload, ["title", "description", "target_date", "status", "progress_pct"])
    db.commit()
    return goal_dict(g)


@router.delete("/goals/{goal_id}", status_code=204)
def delete_goal(goal_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.delete(_own(db, ProfessionalGoal, goal_id, user))
    db.commit()


# --- Growth journal ---------------------------------------------------------
@router.post("/growth")
def add_growth(payload: GrowthItemIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    g = GrowthItem(user_id=user.id, kind=payload.kind, title=payload.title, detail=payload.detail, status=payload.status)
    db.add(g)
    db.commit()
    return growth_item_dict(g)


@router.patch("/growth/{item_id}")
def update_growth(item_id: int, payload: GrowthItemUpdateIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    g = _own(db, GrowthItem, item_id, user)
    _apply(g, payload, ["kind", "title", "detail", "status"])
    db.commit()
    return growth_item_dict(g)


@router.delete("/growth/{item_id}", status_code=204)
def delete_growth(item_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.delete(_own(db, GrowthItem, item_id, user))
    db.commit()


# --- Skills -----------------------------------------------------------------
@router.post("/skills")
def add_skill(payload: SkillIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    s = Skill(user_id=user.id, name=payload.name, level=payload.level, source=payload.source, note=payload.note)
    db.add(s)
    db.commit()
    return skill_dict(s)


@router.patch("/skills/{skill_id}")
def update_skill(skill_id: int, payload: SkillUpdateIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    s = _own(db, Skill, skill_id, user)
    _apply(s, payload, ["name", "level", "source", "note"])
    db.commit()
    return skill_dict(s)


@router.delete("/skills/{skill_id}", status_code=204)
def delete_skill(skill_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.delete(_own(db, Skill, skill_id, user))
    db.commit()


# --- Reading & philosophy ---------------------------------------------------
@router.get("/reading")
def my_reading(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """The canon, each item merged with my status + reflection."""
    return {"items": dev_svc.reading_with_progress(db, user.id)}


@router.put("/reading/{item_id}/progress")
def set_reading_progress(item_id: int, payload: ReadingProgressIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Upsert my progress on a canon item."""
    item = db.get(ReadingItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Reading item not found")
    prog = db.execute(
        select(ReadingProgress).where(
            ReadingProgress.user_id == user.id, ReadingProgress.reading_item_id == item_id
        )
    ).scalar_one_or_none()
    if not prog:
        prog = ReadingProgress(user_id=user.id, reading_item_id=item_id)
        db.add(prog)
    data = payload.model_dump(exclude_unset=True)
    for f in ("status", "reflection", "rating"):
        if f in data:
            setattr(prog, f, data[f])
    prog.updated_at = utcnow()
    db.commit()
    return reading_item_dict(item, prog)


# --- Reading canon (admin curation) -----------------------------------------
@router.post("/reading/canon")
def add_canon(payload: ReadingItemIn, admin: User = Depends(require_min_role(ROLE_ADMIN)), db: Session = Depends(get_db)):
    it = ReadingItem(
        title=payload.title,
        author=payload.author,
        kind=payload.kind,
        url=payload.url,
        summary=payload.summary,
        required=payload.required,
        sort_order=payload.sort_order,
        created_by=admin.id,
    )
    db.add(it)
    db.commit()
    return reading_item_dict(it)


@router.patch("/reading/canon/{item_id}")
def update_canon(item_id: int, payload: ReadingItemUpdateIn, admin: User = Depends(require_min_role(ROLE_ADMIN)), db: Session = Depends(get_db)):
    it = db.get(ReadingItem, item_id)
    if not it:
        raise HTTPException(status_code=404, detail="Reading item not found")
    _apply(it, payload, ["title", "author", "kind", "url", "summary", "required", "sort_order"])
    db.commit()
    return reading_item_dict(it)


@router.delete("/reading/canon/{item_id}", status_code=204)
def delete_canon(item_id: int, admin: User = Depends(require_min_role(ROLE_ADMIN)), db: Session = Depends(get_db)):
    it = db.get(ReadingItem, item_id)
    if not it:
        raise HTTPException(status_code=404, detail="Reading item not found")
    # Drop dependent progress rows first (SQLite has no cascade here).
    for p in db.execute(select(ReadingProgress).where(ReadingProgress.reading_item_id == item_id)).scalars():
        db.delete(p)
    db.delete(it)
    db.commit()

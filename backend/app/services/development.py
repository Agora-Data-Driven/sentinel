"""Assembly for the holistic development profile.

Two shapes are built here and shared by both the worker-facing router and the internal HMAC endpoint
the Mastery Engine coach calls:

    full_profile(db, user)   -> the complete profile for the Development hub / manager view
    holistic_digest(db, user) -> a compact, top-N digest tuned for LLM context

Plus can_view(viewer, target): owner, admins, and the target's team lead may read a profile.
"""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..constants import ADMIN_ROLES, GYM_COMPLETED, ROLE_TEAM_LEAD
from ..models import (
    BodyMetric,
    CareerAchievement,
    DevelopmentArea,
    DevelopmentProfile,
    GrowthItem,
    GymLog,
    MentorTranscript,
    PersonalRecord,
    PhysicalGoal,
    ProfessionalGoal,
    ReadingItem,
    ReadingProgress,
    Skill,
    User,
)
from ..utils.time import today_ph
from . import gym as gym_svc
from ..serializers import (
    achievement_dict,
    body_metric_dict,
    development_area_dict,
    development_profile_dict,
    goal_dict,
    growth_item_dict,
    mentor_transcript_dict,
    personal_record_dict,
    physical_goal_dict,
    pr_display,
    reading_item_dict,
    skill_dict,
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


def _skills(db: Session, user_id: int) -> list[Skill]:
    return list(
        db.execute(
            select(Skill).where(Skill.user_id == user_id).order_by(Skill.source, Skill.name)
        ).scalars()
    )


def _profile(db: Session, user_id: int) -> DevelopmentProfile | None:
    return db.execute(
        select(DevelopmentProfile).where(DevelopmentProfile.user_id == user_id)
    ).scalar_one_or_none()


def _physical_goals(db: Session, user_id: int) -> list[PhysicalGoal]:
    return list(
        db.execute(
            select(PhysicalGoal).where(PhysicalGoal.user_id == user_id).order_by(PhysicalGoal.created_at)
        ).scalars()
    )


def _areas(db: Session, user_id: int) -> dict[str, DevelopmentArea]:
    """This user's per-dimension settings rows, keyed by dimension. Rows are lazy —
    a dimension with no row simply uses the frontend defaults."""
    return {
        a.dimension: a
        for a in db.execute(
            select(DevelopmentArea).where(DevelopmentArea.user_id == user_id)
        ).scalars()
    }


def _transcripts(db: Session, user_id: int) -> list[MentorTranscript]:
    return list(
        db.execute(
            select(MentorTranscript)
            .where(MentorTranscript.user_id == user_id)
            .order_by(MentorTranscript.created_at.desc())
        ).scalars()
    )


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
            # Target PRs being chased — mean progress across non-paused ones IS the
            # Physical ring on the Growth Overview.
            "targets": [physical_goal_dict(g) for g in _physical_goals(db, user.id)],
        },
        "career": {
            "profile": development_profile_dict(_profile(db, user.id)),
            "achievements": [achievement_dict(a) for a in _achievements(db, user.id)],
            "goals": [goal_dict(g) for g in _goals(db, user.id)],
        },
        "skills": [skill_dict(s) for s in _skills(db, user.id)],
        "growth": [growth_item_dict(g) for g in _growth(db, user.id)],
        "reading": reading_with_progress(db, user.id),
        # Per-dimension settings (pace deadline / other info), keyed by dimension.
        # Missing keys = the frontend's defaults; ring % comes from the Mastery Engine.
        "areas": {dim: development_area_dict(a) for dim, a in _areas(db, user.id).items()},
        # Mentor library — compact (no transcript_text; that's fetched per-item on demand).
        "transcripts": [mentor_transcript_dict(t) for t in _transcripts(db, user.id)],
    }


def _pr_line(p: PersonalRecord) -> str:
    return f"{p.exercise_name}: {pr_display(p)}"


def holistic_digest(db: Session, user: User) -> dict:
    """A compact, token-frugal digest for the AI coach (top-N of each pillar)."""
    metrics = _metrics(db, user.id)
    latest = metrics[0] if metrics else None
    prs = _prs(db, user.id)
    profile = _profile(db, user.id)
    achievements = _achievements(db, user.id)
    goals = _goals(db, user.id)
    skills = _skills(db, user.id)
    growth = _growth(db, user.id)
    reading = reading_with_progress(db, user.id)
    transcripts = _transcripts(db, user.id)

    resume = (profile.resume_text or "").strip() if profile else ""
    resume_excerpt = (resume[:700] + ("…" if len(resume) > 700 else "")) if resume else None

    # Target PRs (lifts/runs/skills). One compact line each; the coach both reads these and
    # edits them (update_physical_goal — e.g. "I benched 85 today" bumps current_value).
    physical_goals = _physical_goals(db, user.id)
    def _pg_line(g: PhysicalGoal) -> str:
        d = physical_goal_dict(g)
        return (f"({g.kind}) {g.name}: {g.current_value:g}/{g.target_value:g}{(' ' + g.unit) if g.unit else ''}"
                f" = {d['progress_pct']}% ({g.status}{', lower is better' if g.direction == 'lower' else ''})")

    # Gym: the recurring weekly split + how consistent they've been lately, so the coach can speak
    # to (and edit) the schedule.
    today = today_ph()
    weekly_split = gym_svc.get_week(db, user.id)
    weekly_cardio = gym_svc.get_cardio(db, user.id)
    since = today - timedelta(days=14)
    sessions_14d = db.execute(
        select(func.count(GymLog.id)).where(GymLog.user_id == user.id, GymLog.date >= since)
    ).scalar() or 0
    completed_14d = db.execute(
        select(func.count(GymLog.id)).where(
            GymLog.user_id == user.id, GymLog.date >= since, GymLog.status == GYM_COMPLETED
        )
    ).scalar() or 0

    reading_now = [r["title"] for r in reading if r["progress"]["status"] == "reading"][:8]
    reading_done = [r["title"] for r in reading if r["progress"]["status"] == "done"][:12]
    obstacles = [g.title for g in growth if g.kind == "obstacle" and g.status != "archived"][:6]
    reflections = [g.title for g in growth if g.kind in ("reflection", "note")][:6]

    # Per-dimension area settings (pace deadline + the free-form "other info" dump). The coach
    # can both read these and edit them via the update_area action, so include current values.
    areas = _areas(db, user.id)
    area_summaries = {
        dim: {
            "deadline": a.deadline.isoformat() if a.deadline else None,
            "other_info": (a.other_info or "")[:600] or None,
        }
        for dim, a in areas.items()
    }

    # Items with their ids, for the assistant's edit actions (update/delete need the id).
    editable = {
        "prs": [{"id": p.id, "label": _pr_line(p)} for p in prs],
        "physical_goals": [{"id": g.id, "label": _pg_line(g)} for g in physical_goals],
        "goals": [{"id": g.id, "label": f"[{g.dimension or 'professional'}] {g.title} ({g.status}, {g.progress_pct}%)"} for g in goals],
        "achievements": [{"id": a.id, "label": a.title} for a in achievements],
        "skills": [{"id": s.id, "label": f"{s.name} ({s.level}, {s.source})"} for s in skills],
        "growth": [{"id": g.id, "label": f"({g.kind}) {g.title}"} for g in growth[:15]],
        "reading": [{"id": r["id"], "label": r["title"]} for r in reading],
        # Areas are keyed by dimension NAME, not id — update_area takes the dimension directly.
        "areas": ["spiritual", "professional", "philosophical", "physical"],
    }

    return {
        "name": user.name,
        "physical": {
            "body_fat_pct": latest.body_fat_pct if latest else None,
            "weight_kg": latest.weight_kg if latest else None,
            "as_of": latest.date.isoformat() if latest else None,
            "recent_prs": [_pr_line(p) for p in prs[:10]],
            # Targets being chased — their mean progress is the Physical ring.
            "targets": [_pg_line(g) for g in physical_goals[:15]],
        },
        "gym": {
            "weekly_split": weekly_split,
            "weekly_cardio": weekly_cardio,
            "sessions_last_14d": sessions_14d,
            "completed_last_14d": completed_14d,
        },
        "career": {
            "headline": profile.headline if profile else None,
            "resume_excerpt": resume_excerpt,
            "achievements": [a.title for a in achievements[:10]],
            "goals": [
                {
                    "title": g.title,
                    "dimension": g.dimension or "professional",
                    "status": g.status,
                    "progress": g.progress_pct,
                    "target": g.target_date.isoformat() if g.target_date else None,
                }
                for g in goals[:10]
            ],
        },
        "skills": [
            {"name": s.name, "level": s.level, "source": s.source} for s in skills[:40]
        ],
        "reading": {"reading_now": reading_now, "done": reading_done},
        "growth": {"obstacles": obstacles, "reflections": reflections},
        "areas": area_summaries,
        # Titles only — a mentor transcript can be a whole video's worth of text, so the
        # digest lists what's available rather than dumping it into every prompt.
        "mentor_library": [f"{t.mentor_name} — {t.title}" for t in transcripts[:40]],
        "editable": editable,
    }

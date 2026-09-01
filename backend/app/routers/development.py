"""Holistic Development: the worker's physical + career + reading + growth data.

Owner-only writes; reads allowed for the owner, admins, and the owner's team lead (see
``services.development.can_view``). The AI coach reads a compact digest of the SAME data over the
internal HMAC endpoint (see routers/internal.py).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..constants import GROWTH_DIMENSIONS
from ..models import TimeEntry
from ..database import get_db
from ..models import (
    BodyMetric,
    CareerAchievement,
    DevelopmentArea,
    DevelopmentProfile,
    GrowthItem,
    MentorTranscript,
    PersonalRecord,
    PhysicalGoal,
    ProfessionalGoal,
    ReadingItem,
    ReadingProgress,
    Skill,
    User,
)
from ..schemas import (
    AchievementIn,
    AchievementUpdateIn,
    AreaUpdateIn,
    AtriumImportAllIn,
    AtriumImportIn,
    BodyMetricIn,
    EngineSessionEditIn,
    TimeEntryIn,
    TimeEntryUpdateIn,
    GoalIn,
    GoalUpdateIn,
    GrowthItemIn,
    GrowthItemUpdateIn,
    MentorTranscriptIn,
    PersonalRecordIn,
    PersonalRecordUpdateIn,
    PhysicalGoalIn,
    PhysicalGoalUpdateIn,
    ReadingItemIn,
    ReadingItemUpdateIn,
    ReadingProgressIn,
    ResumeIn,
    SkillIn,
    SkillUpdateIn,
)
from ..capabilities import CAP_GROWTH_TEAM, CAP_READING_CANON
from ..security import get_current_user, require_cap
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
    reading_item_dict,
    skill_dict,
)
from ..services import atrium_watcher, development as dev_svc, team_growth as team_growth_svc
from ..services import time_spent as time_spent_svc
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


@router.get("/team")
def team_growth(
    days: int = Query(team_growth_svc.DEFAULT_WINDOW_DAYS, ge=1, le=180,
                      description="Velocity measurement window, in days."),
    refresh: bool = Query(False, description="Bypass the rollup cache and re-read the engine."),
    viewer: User = Depends(require_cap(CAP_GROWTH_TEAM)),
    db: Session = Depends(get_db),
):
    """Everyone's growth in one payload, for the Overview's admin Team-progress panel.

    Ranked on measured VELOCITY (points of engine mastery per week), not on the ahead/behind pace
    chip — see `services/team_growth.py` for why those are different questions.

    Admin+ at the dependency layer, and scoped again inside `visible_users` (a team lead reaching
    this in future sees only their team). The panel is a management surface: it shows one person's
    numbers to another, which no worker-facing route here does.
    """
    return team_growth_svc.team_rows(db, viewer, days=days, refresh=refresh)


# --- Time in the engine -------------------------------------------------------
# Minutes ACTIVELY spent in the Mastery Engine, per dimension, over Today / This week / 30 days.
# The engine records the minutes (its /api/activity/beat); services/time_spent.py reads them back
# and maps programmes onto dimensions. Only the totals are shown by default — the sessions behind
# them are the /detail click-through.


def _time_target(db: Session, viewer: User, user_id: int | None) -> User:
    """Whose clock: your own, or — with the same rule as the Development profile — a report's."""
    if not user_id or user_id == viewer.id:
        return viewer
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if not dev_svc.can_view(viewer, target):
        raise HTTPException(status_code=403, detail="Not allowed to view this profile")
    return target


@router.get("/time")
def my_time(
    win: str = Query(time_spent_svc.DEFAULT_WINDOW, description="today | week | 30d"),
    user_id: int | None = Query(None, description="Somebody else's clock (owner / admin / their lead)."),
    viewer: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """One person's minutes per dimension over the window — the Overview's time strip."""
    return time_spent_svc.summary(db, _time_target(db, viewer, user_id), win)


@router.get("/time/detail")
def my_time_detail(
    win: str = Query(time_spent_svc.DEFAULT_WINDOW, description="today | week | 30d"),
    user_id: int | None = Query(None),
    viewer: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """The sessions behind the strip: start–end, section, view, per day."""
    return time_spent_svc.detail(db, _time_target(db, viewer, user_id), win)


@router.get("/team-time")
def team_time(
    win: str = Query(time_spent_svc.DEFAULT_WINDOW, description="today | week | 30d"),
    refresh: bool = Query(False, description="Bypass the rollup cache and re-read the engine."),
    viewer: User = Depends(require_cap(CAP_GROWTH_TEAM)),
    db: Session = Depends(get_db),
):
    """Everyone's minutes in one payload, for the Overview's admin block. Same gate and the same
    visibility scope as /team — a management surface that shows one person's time to another."""
    return time_spent_svc.team(db, viewer, win, refresh=refresh)


def _time_writer(db: Session, viewer: User, user_id: int | None) -> User:
    """Whose time may be changed: your own, or — as an admin — somebody's on their behalf. A team lead
    may READ a report's time (can_view) but not rewrite it: honesty edits are the person's own."""
    target = _time_target(db, viewer, user_id)
    if not time_spent_svc.may_write(viewer, target):
        raise HTTPException(status_code=403, detail="Only the person or an admin can change their time")
    return target


@router.post("/time/entries")
def add_time_entry(payload: TimeEntryIn, viewer: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Log time the engine could not see — any dimension, Physical included."""
    target = _time_writer(db, viewer, payload.user_id)
    return time_spent_svc.add_entry(db, target, viewer, day=payload.date, start=payload.start,
                                    minutes=payload.minutes, dimension=payload.dimension, note=payload.note)


def _entry_or_404(db: Session, viewer: User, entry_id: int) -> TimeEntry:
    entry = db.get(TimeEntry, entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Not found")
    _time_writer(db, viewer, entry.user_id)
    return entry


@router.patch("/time/entries/{entry_id}")
def update_time_entry(entry_id: int, payload: TimeEntryUpdateIn,
                      viewer: User = Depends(get_current_user), db: Session = Depends(get_db)):
    entry = _entry_or_404(db, viewer, entry_id)
    return time_spent_svc.update_entry(db, entry, day=payload.date, start=payload.start, minutes=payload.minutes,
                                       dimension=payload.dimension, note=payload.note)


@router.delete("/time/entries/{entry_id}")
def delete_time_entry(entry_id: int, viewer: User = Depends(get_current_user), db: Session = Depends(get_db)):
    time_spent_svc.delete_entry(db, _entry_or_404(db, viewer, entry_id))
    return {"ok": True}


@router.post("/time/engine-edit")
def edit_engine_time(payload: EngineSessionEditIn, viewer: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    """Delete or trim one RECORDED engine session — the honesty edit ("I was only moving the mouse").
    Removal only: the engine's minutes can be shortened, never extended or moved (add a manual entry)."""
    target = _time_writer(db, viewer, payload.user_id)
    return time_spent_svc.edit_engine_session(target, day=payload.day, start=payload.start, end=payload.end,
                                              new_start=payload.new_start, new_end=payload.new_end)


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
        dimension=payload.dimension,
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
    _apply(g, payload, ["title", "dimension", "description", "target_date", "status", "progress_pct"])
    db.commit()
    return goal_dict(g)


@router.delete("/goals/{goal_id}", status_code=204)
def delete_goal(goal_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.delete(_own(db, ProfessionalGoal, goal_id, user))
    db.commit()


# --- Physical goals (target PRs: lifts / runs / skills) ----------------------
@router.get("/physical-goals")
def list_physical_goals(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """The owner's target PRs — the Physical tab's goals card fetches just this
    (the full /me payload would be overkill on the gym page)."""
    rows = db.execute(
        select(PhysicalGoal).where(PhysicalGoal.user_id == user.id).order_by(PhysicalGoal.created_at)
    ).scalars()
    return {"goals": [physical_goal_dict(g) for g in rows]}


@router.post("/physical-goals")
def add_physical_goal(payload: PhysicalGoalIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    g = PhysicalGoal(
        user_id=user.id,
        name=payload.name,
        kind=payload.kind,
        target_value=payload.target_value,
        current_value=payload.current_value,
        unit=payload.unit,
        direction=payload.direction,
        notes=payload.notes,
        status=payload.status,
    )
    db.add(g)
    db.commit()
    return physical_goal_dict(g)


@router.patch("/physical-goals/{goal_id}")
def update_physical_goal(goal_id: int, payload: PhysicalGoalUpdateIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    g = _own(db, PhysicalGoal, goal_id, user)
    _apply(g, payload, ["name", "kind", "target_value", "current_value", "unit", "direction", "notes", "status"])
    db.commit()
    return physical_goal_dict(g)


@router.delete("/physical-goals/{goal_id}", status_code=204)
def delete_physical_goal(goal_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.delete(_own(db, PhysicalGoal, goal_id, user))
    db.commit()


# --- Growth areas (per-dimension settings) -----------------------------------
@router.patch("/areas/{dimension}")
def update_area(
    dimension: str,
    payload: AreaUpdateIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Upsert this user's settings for one growth dimension (pace deadline / other info).

    Owner-only, lazily created. Uses exclude_unset (not _apply) so an explicit null CLEARS a
    field — needed to reset a deadline back to the UI default, which _apply cannot express.
    """
    if dimension not in GROWTH_DIMENSIONS:
        raise HTTPException(status_code=400, detail=f"Unknown dimension '{dimension}'")
    area = db.execute(
        select(DevelopmentArea).where(
            DevelopmentArea.user_id == user.id, DevelopmentArea.dimension == dimension
        )
    ).scalar_one_or_none()
    if not area:
        area = DevelopmentArea(user_id=user.id, dimension=dimension)
        db.add(area)
    data = payload.model_dump(exclude_unset=True)
    for f in ("deadline", "other_info"):
        if f in data:
            setattr(area, f, data[f])
    area.updated_at = utcnow()
    db.commit()
    return development_area_dict(area)


# --- Growth journal ---------------------------------------------------------
# One titled idea per entry, filed under a growth dimension. The title is what the AI coach sees on
# every turn (complete index); the detail is fetched on demand. See models/development.GrowthItem.
def _dimension_or_400(value: str | None, fallback: str = "spiritual") -> str:
    """Validate a dimension, or 400. An unknown one would file the entry into a tab that renders
    nowhere — invisible in the UI, and mis-grouped in the coach's index."""
    dim = (value or fallback).strip().lower()
    if dim not in GROWTH_DIMENSIONS:
        raise HTTPException(status_code=400, detail=f"Unknown dimension '{value}'")
    return dim


@router.post("/growth")
def add_growth(payload: GrowthItemIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    g = GrowthItem(
        user_id=user.id,
        dimension=_dimension_or_400(payload.dimension),
        kind=payload.kind,
        title=payload.title,
        detail=payload.detail,
        status=payload.status,
    )
    db.add(g)
    db.commit()
    return growth_item_dict(g)


# "Upload a PDF" = make an entry whose detail is the PDF's text. Nothing else is stored — no bucket,
# no blob column, no migration — because the entry is the ONLY thing the coach can read: its title
# joins the complete index on every turn and its body is fetched whole when a conversation bears on
# it. A stored file the coach cannot see would be a filing cabinet with the coach locked out.
# Text extraction + the declared-truncation rule live in services/pdf_text.py.
@router.post("/growth/upload")
async def upload_growth_pdf(
    file: UploadFile = File(...),
    dimension: str = Form("professional"),
    kind: str = Form("note"),
    title: str | None = Form(None),
    status: str = Form("open"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from ..services import pdf_text

    name = (file.filename or "").strip()
    ctype = (file.content_type or "").lower()
    if ctype != "application/pdf" and not name.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Please upload a PDF")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="The file was empty")
    if len(data) > pdf_text.MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="PDF is too large (max 15 MB)")
    try:
        got = pdf_text.extract_pdf_text(data)
    except pdf_text.PdfUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))
    except pdf_text.PdfError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # The title is the load-bearing field (it is all the coach sees until it opens the body), so it
    # is taken from, in order: what the worker typed, the PDF's own metadata title, the file name.
    stem = name[:-4] if name.lower().endswith(".pdf") else name
    final_title = ((title or "").strip() or got.title or stem.replace("_", " ").replace("-", " ").strip()
                   or "Uploaded PDF")[:200]
    if kind not in ("note", "reflection", "obstacle"):
        kind = "note"
    if status not in ("open", "resolved", "archived"):
        status = "open"
    header = (f"[Imported from PDF \"{name or 'upload.pdf'}\" — {got.pages} page{'s' if got.pages != 1 else ''}, "
              f"{got.pages_imported} imported, {today_ph().isoformat()}]\n\n")
    g = GrowthItem(
        user_id=user.id,
        dimension=_dimension_or_400(dimension),
        kind=kind,
        title=final_title,
        detail=header + got.text,
        status=status,
    )
    db.add(g)
    db.commit()
    out = growth_item_dict(g)
    out["import"] = {"pages": got.pages, "pages_imported": got.pages_imported,
                     "chars": len(g.detail or ""), "truncated": got.truncated}
    return out


@router.patch("/growth/{item_id}")
def update_growth(item_id: int, payload: GrowthItemUpdateIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    g = _own(db, GrowthItem, item_id, user)
    if payload.dimension is not None:
        g.dimension = _dimension_or_400(payload.dimension)
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


# --- Mentor library (imported transcripts) ----------------------------------
@router.post("/transcripts")
def add_transcript(payload: MentorTranscriptIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    t = MentorTranscript(
        user_id=user.id,
        mentor_name=payload.mentor_name,
        title=payload.title,
        source_url=payload.source_url,
        transcript_text=payload.transcript_text,
    )
    db.add(t)
    db.commit()
    return mentor_transcript_dict(t)


@router.get("/transcripts/{transcript_id}")
def get_transcript(transcript_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """The full row, including transcript_text — fetched on demand when a library entry is opened."""
    return mentor_transcript_dict(_own(db, MentorTranscript, transcript_id, user), full=True)


@router.delete("/transcripts/{transcript_id}", status_code=204)
def delete_transcript(transcript_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.delete(_own(db, MentorTranscript, transcript_id, user))
    db.commit()


# --- Mentor library: import from Atrium's Watcher (creators already archived there) ---------------
# Watcher (Atrium's team-only tab) already auto-fetches full transcripts for watched YouTube
# creators -- this lets the Growth hub import one of those instead of hand-pasting text. Read-only
# browsing, then a one-time COPY into `mentor_transcripts` (not a live link): the coach's digest and
# this page both read Sentinel's own table, so an Atrium outage never breaks an already-imported
# transcript. See services/atrium_watcher.py -- everything here degrades to empty/404 when the
# bridge isn't configured, never a 500.
@router.get("/atrium/channels")
def atrium_channels(user: User = Depends(get_current_user)):
    return {"ready": atrium_watcher.ready(), "channels": atrium_watcher.list_channels()}


@router.get("/atrium/channels/{channel_id}/videos")
def atrium_videos(channel_id: str, user: User = Depends(get_current_user)):
    return {"videos": atrium_watcher.list_videos(channel_id)}


@router.post("/atrium/import")
def atrium_import(payload: AtriumImportIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    v = atrium_watcher.get_transcript(payload.channel_id, payload.video_id)
    if not v:
        raise HTTPException(status_code=404, detail="That transcript isn't available from Atrium yet.")
    t = MentorTranscript(
        user_id=user.id,
        mentor_name=payload.mentor_name,
        title=v["title"] or "Untitled",
        source_url=v["url"] or None,
        transcript_text=v["transcript"],
    )
    db.add(t)
    db.commit()
    return mentor_transcript_dict(t)


@router.post("/atrium/import-all")
def atrium_import_all(payload: AtriumImportAllIn, user: User = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    """Import EVERY fetched transcript on one creator in a single call.

    Pulling a 200-video creator one click at a time was the whole complaint. Atrium hands the
    channel over in one (byte-budgeted) transfer, so this is a handful of round trips rather than
    one per video.

    IDEMPOTENT: re-running only adds what's missing, so it doubles as "catch me up since Atrium
    fetched more". A transcript is considered already-mine by source_url (stable per video), falling
    back to its title for the rare archived item that has no URL."""
    items = atrium_watcher.list_transcripts(payload.channel_id)
    if not items:
        raise HTTPException(status_code=404,
                            detail="No fetched transcripts on that creator yet — run \"Fetch "
                                   "missing\" on it in Atrium first.")
    mentor = (payload.mentor_name or "").strip() or "Unknown mentor"
    existing = db.execute(
        select(MentorTranscript.source_url, MentorTranscript.title)
        .where(MentorTranscript.user_id == user.id)
    ).all()
    seen_urls = {u for (u, _t) in existing if u}
    seen_titles = {t for (u, t) in existing if not u}
    imported = 0
    for it in items:
        url = (it.get("url") or "").strip()
        title = (it.get("title") or "").strip() or "Untitled"
        text = it.get("transcript") or ""
        if not text:
            continue
        if (url and url in seen_urls) or (not url and title in seen_titles):
            continue
        db.add(MentorTranscript(user_id=user.id, mentor_name=mentor, title=title[:300],
                                source_url=url[:500] or None, transcript_text=text))
        # Track within this run too, so a channel that lists the same video twice can't double-add.
        (seen_urls.add(url) if url else seen_titles.add(title))
        imported += 1
    db.commit()
    return {"imported": imported, "skipped": len(items) - imported, "available": len(items)}


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
def add_canon(payload: ReadingItemIn, admin: User = Depends(require_cap(CAP_READING_CANON)), db: Session = Depends(get_db)):
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
def update_canon(item_id: int, payload: ReadingItemUpdateIn, admin: User = Depends(require_cap(CAP_READING_CANON)), db: Session = Depends(get_db)):
    it = db.get(ReadingItem, item_id)
    if not it:
        raise HTTPException(status_code=404, detail="Reading item not found")
    _apply(it, payload, ["title", "author", "kind", "url", "summary", "required", "sort_order"])
    db.commit()
    return reading_item_dict(it)


@router.delete("/reading/canon/{item_id}", status_code=204)
def delete_canon(item_id: int, admin: User = Depends(require_cap(CAP_READING_CANON)), db: Session = Depends(get_db)):
    it = db.get(ReadingItem, item_id)
    if not it:
        raise HTTPException(status_code=404, detail="Reading item not found")
    # Drop dependent progress rows first (SQLite has no cascade here).
    for p in db.execute(select(ReadingProgress).where(ReadingProgress.reading_item_id == item_id)).scalars():
        db.delete(p)
    db.delete(it)
    db.commit()

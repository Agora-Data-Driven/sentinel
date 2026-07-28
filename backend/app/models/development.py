"""Holistic development: body metrics, personal records, career profile, goals, growth journal,
and the reading & philosophy canon.

Sentinel is the system of record for a worker's *whole* development — physical, career, learning,
and personal growth. The worker-facing "Development" tab reads/writes these, and the Mastery Engine's
AI coach pulls a compact digest of them over the internal HMAC channel so it can coach across all of
a person's life, not just their learning.

Tables:
    body_metrics          -> time-series body-fat % / weight snapshots (latest = current)
    personal_records      -> all-time best per lift (one row per user+exercise)
    development_profiles   -> 1:1 with a user; resume + headline
    career_achievements    -> list of wins
    professional_goals     -> list of goals with status + progress
    physical_goals         -> TARGET PRs being chased (lift/run/skill; drives the Physical ring)
    development_areas      -> per-user settings for one growth dimension (pace deadline, other info)
    growth_items           -> personal journal: obstacles / reflections / notes (bottom-up)
    reading_items          -> admin-curated canon of required books/philosophies (top-down)
    reading_progress       -> per-worker status + reflection on a canon item
    mentor_transcripts     -> full transcripts imported from outside mentors (e.g. Atrium creators)
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base
from ..utils.time import utcnow


class BodyMetric(Base):
    """A dated body-composition snapshot. The most recent row is the worker's current stats."""

    __tablename__ = "body_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    body_fat_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class PersonalRecord(Base):
    """An all-time personal best. Covers BOTH weight lifts (weight_value + reps, e.g. Bench 80kg x5)
    AND non-weight records — runs, times, distances, holds — via the free-form `detail` (e.g. a
    "10 km run" with detail "~59 min"). For a cardio PR, leave weight_value 0 and fill `detail`."""

    __tablename__ = "personal_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    exercise_name: Mapped[str] = mapped_column(String(120), nullable=False)
    weight_value: Mapped[float] = mapped_column(Float, default=0.0)
    weight_unit: Mapped[str] = mapped_column(String(8), default="kg")
    reps: Mapped[int] = mapped_column(Integer, default=1)
    detail: Mapped[str | None] = mapped_column(String(160), nullable=True)  # non-weight result, e.g. "10 km in ~59 min"
    achieved_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class DevelopmentProfile(Base):
    """1:1 with a user — the career narrative (headline + resume)."""

    __tablename__ = "development_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, unique=True, index=True)
    headline: Mapped[str | None] = mapped_column(String(200), nullable=True)
    resume_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    resume_file_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class CareerAchievement(Base):
    __tablename__ = "career_achievements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    achieved_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ProfessionalGoal(Base):
    """A goal in one of the four growth dimensions. Historically career-only (hence the table
    name); `dimension` widens it to the whole person, and old rows default to 'professional'."""

    __tablename__ = "professional_goals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    dimension: Mapped[str] = mapped_column(String(16), default="professional")  # spiritual|professional|philosophical|physical
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="active")  # active|done|paused
    progress_pct: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class PhysicalGoal(Base):
    """A TARGET PR the worker is chasing — a lift, a run, or a skill (calisthenics, boxing).

    The physical analogue of an engine program: each goal is a number to reach
    (`target_value`) and where they are now (`current_value`, hand- or coach-updated;
    `personal_records` stays the log of achieved bests). Progress is the ratio —
    `direction` 'lower' inverts it for time-based goals (a 55-min 10k). The Physical
    ring on the Growth Overview is the mean progress across non-paused goals.
    """

    __tablename__ = "physical_goals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)  # "Bench Press", "10k run", "Muscle-up"
    kind: Mapped[str] = mapped_column(String(16), default="lift")  # lift|run|skill
    target_value: Mapped[float] = mapped_column(Float, nullable=False)
    current_value: Mapped[float] = mapped_column(Float, default=0)
    unit: Mapped[str] = mapped_column(String(24), default="")  # kg, lb, min, sec, reps, km…
    direction: Mapped[str] = mapped_column(String(8), default="higher")  # higher|lower (times: lower wins)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="active")  # active|achieved|paused
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class DevelopmentArea(Base):
    """Per-user settings for ONE growth dimension (spiritual|professional|philosophical|physical).

    The Overview's ring percentages come from the Mastery Engine (never typed by hand), so what a
    dimension needs of its own is only: the pace `deadline` the whole area is racing toward
    (defaulted in the UI, editable there and by the coach), and `other_info` — a free-form dump the
    worker or the coach can keep per area. Rows are created lazily on first write; a missing row
    just means "all defaults".
    """

    __tablename__ = "development_areas"
    __table_args__ = (UniqueConstraint("user_id", "dimension", name="uq_dev_area_user_dim"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    dimension: Mapped[str] = mapped_column(String(16), nullable=False)
    deadline: Mapped[date | None] = mapped_column(Date, nullable=True)
    other_info: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class GrowthItem(Base):
    """The worker's personal, bottom-up journal — obstacles they're facing, reflections, notes."""

    __tablename__ = "growth_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(16), default="reflection")  # obstacle|reflection|note
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="open")  # open|resolved|archived
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Skill(Base):
    """A skill the worker HAS — often from real project experience, not (only) the Mastery Engine.

    The whole point: the AI coach should know you can do SQL / pandas / GitHub even though you chose to
    prove those on the job rather than drill them in the engine. `source` records how it was gained so
    the coach can distinguish "proven on real projects" from "practised in the engine".
    """

    __tablename__ = "skills"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    level: Mapped[str] = mapped_column(String(16), default="Intermediate")  # Beginner|Intermediate|Advanced
    source: Mapped[str] = mapped_column(String(24), default="project")  # project|mastery_engine|course|certification|other
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class ReadingItem(Base):
    """A book/philosophy in the company canon (top-down, admin-curated required reading)."""

    __tablename__ = "reading_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    author: Mapped[str | None] = mapped_column(String(160), nullable=True)
    kind: Mapped[str] = mapped_column(String(16), default="book")  # book|philosophy|essay
    url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    required: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ReadingProgress(Base):
    """A worker's status + reflection on a canon item. One row per (user, item)."""

    __tablename__ = "reading_progress"
    __table_args__ = (
        UniqueConstraint("user_id", "reading_item_id", name="uq_reading_progress_user_item"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    reading_item_id: Mapped[int] = mapped_column(ForeignKey("reading_items.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), default="not_started")  # not_started|reading|done
    reflection: Mapped[str | None] = mapped_column(Text, nullable=True)
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class MentorTranscript(Base):
    """A full transcript imported from an outside mentor's video/lesson (e.g. an Atrium
    creator like Nic Saraev or Carson Reed) — a personal, bottom-up knowledge base the
    worker builds so the AI coach can draw on someone else's playbook, not just the
    Mastery Engine's own curriculum. `transcript_text` can be long (a whole video), so
    list views should read the compact digest and fetch the full row only on demand."""

    __tablename__ = "mentor_transcripts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    mentor_name: Mapped[str] = mapped_column(String(120), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    transcript_text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

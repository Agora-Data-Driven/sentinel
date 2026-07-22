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
    growth_items           -> personal journal: obstacles / reflections / notes (bottom-up)
    reading_items          -> admin-curated canon of required books/philosophies (top-down)
    reading_progress       -> per-worker status + reflection on a canon item
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
    """All-time best for a lift — the worker maintains it manually (e.g. Bench 80kg x5)."""

    __tablename__ = "personal_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    exercise_name: Mapped[str] = mapped_column(String(120), nullable=False)
    weight_value: Mapped[float] = mapped_column(Float, default=0.0)
    weight_unit: Mapped[str] = mapped_column(String(8), default="kg")
    reps: Mapped[int] = mapped_column(Integer, default=1)
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
    __tablename__ = "professional_goals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="active")  # active|done|paused
    progress_pct: Mapped[int] = mapped_column(Integer, default=0)
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

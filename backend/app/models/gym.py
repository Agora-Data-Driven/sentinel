"""gym_logs, gym_exercises, exercise_library."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base
from ..utils.time import utcnow


class GymLog(Base):
    __tablename__ = "gym_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    day_type: Mapped[str] = mapped_column(String(16), default="Custom")  # Push|Pull|Legs|Custom
    start_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    end_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_minutes: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="Incomplete")  # Completed|Incomplete|Missing
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    exercises: Mapped[list["GymExercise"]] = relationship(
        back_populates="log", cascade="all, delete-orphan"
    )


class GymExercise(Base):
    __tablename__ = "gym_exercises"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    gym_log_id: Mapped[int] = mapped_column(ForeignKey("gym_logs.id"), nullable=False, index=True)
    exercise_name: Mapped[str] = mapped_column(String(120), nullable=False)
    muscle_group: Mapped[str | None] = mapped_column(String(60), nullable=True)
    weight_value: Mapped[float] = mapped_column(Float, default=0.0)
    weight_unit: Mapped[str] = mapped_column(String(8), default="kg")
    sets: Mapped[int] = mapped_column(Integer, default=0)
    reps: Mapped[int] = mapped_column(Integer, default=0)
    set_type: Mapped[str] = mapped_column(String(16), default="Normal")
    # Per-set detail for Hevy-style logging: [{set,kg,reps,type,done}]
    sets_json: Mapped[str] = mapped_column(Text, default="[]")
    duration_minutes: Mapped[int] = mapped_column(Integer, default=0)  # for cardio
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    log: Mapped[GymLog] = relationship(back_populates="exercises")


class GymSchedule(Base):
    """One row per user — the recurring weekly split (which day-type each weekday is)."""

    __tablename__ = "gym_schedules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, unique=True, index=True)
    # {"Mon":"Push","Tue":"Pull",...,"Sun":"Rest"} — see constants.GYM_WEEKDAYS / GYM_DEFAULT_WEEK.
    week_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class GymPlanOverride(Base):
    """A per-date override of the weekly split (e.g. "make the 25th Pull", "Rest today")."""

    __tablename__ = "gym_plan_overrides"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    day_type: Mapped[str] = mapped_column(String(16), nullable=False)  # Push|Pull|Legs|Custom|Rest
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    __table_args__ = (UniqueConstraint("user_id", "date", name="uq_gym_override_user_date"),)


class ExerciseLibrary(Base):
    __tablename__ = "exercise_library"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    muscle_group: Mapped[str | None] = mapped_column(String(60), nullable=True)
    day_types_json: Mapped[str] = mapped_column(Text, default="[]")  # ["Push"], ["Custom"]...
    equipment: Mapped[str | None] = mapped_column(String(60), nullable=True)
    instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

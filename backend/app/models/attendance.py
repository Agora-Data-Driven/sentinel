"""attendance_events, daily_attendance_summary, attendance_requests."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..constants import REQ_PENDING
from ..database import Base
from ..utils.time import utcnow


class AttendanceEvent(Base):
    """A single raw punch (clock in/out, break start/end). Immutable log; the summary is derived."""

    __tablename__ = "attendance_events"
    # DB-level guard against a duplicate-punch race: at most one clock-in and one clock-out per
    # person per day (breaks are exempt). Partial unique indexes — Postgres + SQLite (>=3.8).
    __table_args__ = (
        Index("uq_att_one_clockin_per_day", "user_id", "date", unique=True,
              sqlite_where=text("action = 'clock_in'"), postgresql_where=text("action = 'clock_in'")),
        Index("uq_att_one_clockout_per_day", "user_id", "date", unique=True,
              sqlite_where=text("action = 'clock_out'"), postgresql_where=text("action = 'clock_out'")),
        # Idempotency: an offline punch carries a stable client_uid so re-syncing the same punch
        # (e.g. after a lost response) can't record it twice. NULLs are distinct, so online punches
        # without a uid are unaffected.
        Index("uq_att_client_uid", "client_uid", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)  # PH date of the punch
    time: Mapped[datetime] = mapped_column(DateTime, nullable=False)  # UTC instant of the punch
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    device: Mapped[str] = mapped_column(String(40), default="kiosk")  # kiosk | admin-phone | offline
    client_uid: Mapped[str | None] = mapped_column(String(64), nullable=True)  # offline dedupe key
    late_status: Mapped[str | None] = mapped_column(String(16), nullable=True)  # OnTime|Late
    late_minutes: Mapped[int] = mapped_column(Integer, default=0)
    late_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    handover_note: Mapped[str | None] = mapped_column(Text, nullable=True)  # captured on clock-out
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class DailyAttendanceSummary(Base):
    __tablename__ = "daily_attendance_summary"
    __table_args__ = (UniqueConstraint("user_id", "date", name="uq_summary_user_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    clock_in: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    clock_out: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    break_start: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    break_end: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    break_duration_min: Mapped[int] = mapped_column(Integer, default=0)
    total_work_hours: Mapped[float] = mapped_column(Float, default=0.0)
    overtime_minutes: Mapped[int] = mapped_column(Integer, default=0)
    overtime_approved: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default="")
    handover_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class AttendanceRequest(Base):
    """Regularization (fix a punch) OR overtime approval request. Manager/Admin reviews."""

    __tablename__ = "attendance_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    request_type: Mapped[str] = mapped_column(String(20), nullable=False)  # regularization|overtime
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    old_value: Mapped[str | None] = mapped_column(String(120), nullable=True)
    new_value: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default=REQ_PENDING, index=True)
    reviewed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

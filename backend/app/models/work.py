"""task_sessions, certifications — the two tables the operating-system release added (2026-09-02).

Both are NEW TABLES rather than columns on `tasks` / `users`, for the reason AGENTS.md §4 gives:
prod deploys don't run Alembic, `create_all` lands a new table by itself, and a new column only
arrives via `main._ensure_columns`. (The handful of columns this release did add are listed there.)

TaskSession — one block of time one person spent working a task. Written by Start Work / Pause /
Submit / clock-out, never typed. This is the FIRST per-task time Sentinel has ever recorded: until
now the only time it knew was attendance (clock in → out) and the Mastery Engine's learning
minutes. See `services/task_sessions.py` for the rules (one open session per person; clock-out
closes it; a runaway session is capped and flagged, never silently trusted).

Certification — a credential a person holds ("Meta Campaign Deployment"), granted by somebody,
optionally expiring. `service_templates.required_certification` names one of these keys; the board
SURFACES the gap at assignment ("Earl is not certified for this — a reviewer is required") and does
not enforce it. Enforcement is a later decision once the table is populated.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base
from ..utils.time import utcnow

# How a session ENDED. `start_work` = the person pressed Pause / Submit / started another task;
# `auto_clockout` = clocking out closed it; `auto_cap` = it ran past SESSION_CAP_MINUTES and was
# clamped (the row is kept, flagged, so the person can trim it honestly rather than lose it);
# `manual` = an admin correction row.
SESSION_SOURCES = ("start_work", "auto_clockout", "auto_cap", "manual")


class TaskSession(Base):
    __tablename__ = "task_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow, index=True)
    # NULL = still running. Exactly one open row per user at any time (services/task_sessions).
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="start_work")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    @property
    def minutes(self) -> int:
        end = self.ended_at or utcnow()
        return max(0, int((end - self.started_at).total_seconds() // 60))


class Certification(Base):
    __tablename__ = "certifications"
    # One row per (person, credential): re-granting updates the row rather than stacking a second.
    __table_args__ = (UniqueConstraint("user_id", "key", name="uq_certification_user_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    # A stable slug ("meta_campaign_deployment") — what `service_templates.required_certification`
    # names — and the label a human reads.
    key: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    granted_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    granted_at: Mapped[date] = mapped_column(Date, nullable=False)
    expires_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    evidence_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    def is_valid(self, today: date) -> bool:
        return self.expires_at is None or self.expires_at >= today

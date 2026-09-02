"""projects, project_milestones — the thin project layer (2026-09-02).

Why it exists: the company runs on NAMED OUTCOMES with dates ("Phase One — a replicable pod by
October 1"), and until now Sentinel could only express the day-sized work underneath them. The owner
could see every card and no initiative. A project here is deliberately small: a name, a goal, an
owner, a target date, a handful of MILESTONES (checkable statements of done, not tasks), and the
tasks that claim membership via `tasks.project_id`. Everything else — assignment, review, time,
health inputs — already lives on the task and is ROLLED UP, never duplicated.

🔴 Do not grow this into a PM suite. No per-project statuses, no Gantt, no project-level assignees
beyond the one owner — the handoff brief (docs/SENTINEL_OPERATING_SYSTEM.md) and the owner's own
instruction ("I do not want to overcomplicate it") both say the value is a page that answers
"is Phase One on track, and why not?", not a second board.

Two TABLES (create_all lands new tables on prod by itself — the same reasoning as TaskSupporter);
the one new COLUMN (`tasks.project_id`) rides `main._ensure_columns` + migration d4c7e9a2f5b8.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base
from ..utils.time import utcnow


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    # WHY this project exists, in the owner's words — printed at the top of the page so every
    # milestone and task is read against the outcome, not as a list.
    goal: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # active | done | archived. A tiny fixed enum, deliberately NOT a task_vocab-style table:
    # projects are few and these three states are the whole lifecycle.
    status: Mapped[str] = mapped_column(String(16), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    milestones: Mapped[list["ProjectMilestone"]] = relationship(
        back_populates="project", cascade="all, delete-orphan",
        order_by="ProjectMilestone.position")


class ProjectMilestone(Base):
    """A checkable statement of done ("Report Standard v1 used in a live client meeting").

    NOT a task: it has no assignee, no status ladder and no board card, because a milestone is a
    CLAIM about the world that somebody senior ticks, while a task is work somebody does. The page
    links the two by proximity, not by schema — forcing milestones to be tasks is how project tools
    end up with two boards showing the same work.
    """

    __tablename__ = "project_milestones"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    done: Mapped[bool] = mapped_column(Boolean, default=False)
    # Stamped by the TOGGLE (routers/projects.py), never typed — the same rule as the board's
    # completed_at: "when did we reach this" must be a fact about the transition.
    done_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    done_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    project: Mapped[Project] = relationship(back_populates="milestones")

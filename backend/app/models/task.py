"""tasks, task_comments, task_history, atrium_approvals."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..constants import PRIORITY_MEDIUM, TASK_TODO
from ..database import Base
from ..utils.time import utcnow


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id"), nullable=True, index=True)
    campaign: Mapped[str | None] = mapped_column(String(160), nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(80), nullable=True)

    # Internal-only ownership fields (NEVER exposed to clients / Atrium).
    account_manager_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    assigned_team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"), nullable=True, index=True)
    assigned_to_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    priority: Mapped[str] = mapped_column(String(16), default=PRIORITY_MEDIUM)  # AM-only to change
    status: Mapped[str] = mapped_column(String(32), default=TASK_TODO, index=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    labels_json: Mapped[str] = mapped_column(Text, default="[]")  # ["Design","Ads",...]
    checklist_json: Mapped[str] = mapped_column(Text, default="[]")  # [{text,done}]

    # Visibility bridge: whether this task's client-facing fields are shared to Atrium.
    atrium_visible: Mapped[bool] = mapped_column(Boolean, default=False)
    deliverable_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    internal_notes: Mapped[str | None] = mapped_column(Text, nullable=True)  # 🔒 internal
    client_facing_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    comments: Mapped[list["TaskComment"]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )
    history: Mapped[list["TaskHistory"]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )


class TaskComment(Base):
    __tablename__ = "task_comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), nullable=False, index=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    attachments_json: Mapped[str] = mapped_column(Text, default="[]")  # [{name,url}]
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    task: Mapped[Task] = relationship(back_populates="comments")


class TaskHistory(Base):
    __tablename__ = "task_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), nullable=False, index=True)
    changed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    field_changed: Mapped[str] = mapped_column(String(60), nullable=False)
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    changed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    task: Mapped[Task] = relationship(back_populates="history")


class AtriumApproval(Base):
    __tablename__ = "atrium_approvals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), nullable=False, index=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    client_response: Mapped[str | None] = mapped_column(String(40), nullable=True)  # approved/changes
    responded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revision_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

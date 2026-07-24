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
    # Internal-only money field (never crosses to Atrium). Optional; stored bare — digits with an
    # optional decimal, no "$" or thousands commas. Empty/blank = no charge set.
    service_charge: Mapped[str | None] = mapped_column(String(32), nullable=True)
    labels_json: Mapped[str] = mapped_column(Text, default="[]")  # ["Design","Ads",...]
    checklist_json: Mapped[str] = mapped_column(Text, default="[]")  # [{text,done}] — legacy flat list
    # Two-level work breakdown: [{id,title,assignee_id,subs:[{id,text,done,assignee_id}]}].
    # Supersedes checklist_json (a legacy flat list is migrated into one main task on read).
    maintasks_json: Mapped[str] = mapped_column(Text, default="[]")

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


class ServiceTemplate(Base):
    """A super-admin-editable service recipe (was hardcoded in task_templates.py).

    `maintasks_json` holds the grouped breakdown [{"title","subs":[{"text"}]}] the New Task form
    seeds into a task's two-level work breakdown. `dept` matches a Team name.
    """
    __tablename__ = "service_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    dept: Mapped[str | None] = mapped_column(String(80), nullable=True)  # Team name
    content_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    maintasks_json: Mapped[str] = mapped_column(Text, default="[]")
    # Defaults auto-filled onto a new task when this service is picked (a seed, not a lock —
    # each is still editable on the task afterwards; the form pre-fills them client-side too).
    default_priority: Mapped[str | None] = mapped_column(String(16), nullable=True)
    default_labels_json: Mapped[str] = mapped_column(Text, default="[]")  # ["Design","Ads",...]
    default_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class TaskVocabItem(Base):
    """Super-admin-editable board vocabulary: statuses, labels, and priorities (was constants).

    One row per value; `kind` partitions the three vocabularies. `color` is a hex used for inline
    rendering so custom names still get a colour.
    """
    __tablename__ = "task_vocab"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, index=True)  # status|label|priority
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    color: Mapped[str | None] = mapped_column(String(16), nullable=True)  # #RRGGBB
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class AtriumApproval(Base):
    __tablename__ = "atrium_approvals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), nullable=False, index=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    client_response: Mapped[str | None] = mapped_column(String(40), nullable=True)  # approved/changes
    responded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revision_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

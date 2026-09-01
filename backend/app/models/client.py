"""clients — the agency's clients (bridged to Atrium via atrium_client_id)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base
from ..utils.time import utcnow


class Client(Base):
    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    contact_email: Mapped[str | None] = mapped_column(String(160), nullable=True)
    # Links a Sentinel client to its Atrium workspace key. 🔴 THE bridge key: `resolve_client`,
    # `task_bridge`, `board_mirror` and `task_adoption` all address a workspace through it. Filled by
    # `services/client_sync` from Atrium's registry since 2026-08-05 — Atrium owns clients, Sentinel
    # owns staff — not typed into a form.
    atrium_client_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # 🔴 Deactivated instead of DELETED when Atrium stops listing a client (client_sync). Deleting
    # nulls `Task.client_id` on every past task, so historical reports for that client go blank; an
    # inactive client keeps its whole history and simply leaves the pickers.
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False,
                                            server_default="1")
    # WHO OWNS THE ACCOUNT (2026-09-02). Atrium owns the client's identity; who at Agora is
    # accountable for it is a STAFFING fact, so it lives here beside the staff table. Drives the AM's
    # "My accounts" view and the AI drafter's default assignee. NULL = nobody named yet — the
    # Clients page says so rather than guessing from who filed the most cards.
    account_manager_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

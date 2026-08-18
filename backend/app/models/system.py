"""audit_logs, system_settings, role_capabilities."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base
from ..utils.time import utcnow


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    table_name: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    record_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    action: Mapped[str] = mapped_column(String(40), nullable=False)  # create|update|delete|approve...
    old_value_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class SystemSetting(Base):
    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class RoleCapability(Base):
    """A Super Admin's DEVIATION from a capability's coded default — never the full answer.

    🔴 **This table stores DELTAS, and that is the whole safety model.** `app/capabilities.py`
    owns what each role can do by default; a row here says only "for this one role, this one
    capability is now on/off, whatever the code says". Three things follow, and all three are the
    reason it is not a full role × capability snapshot:

    - **An empty table means "exactly what the code ships with"** — which is also what makes
      `POST /api/permissions/reset` a single `DELETE`, so a Super Admin who has made a mess of the
      grid is always one click from a known-good state.
    - **A capability added in a later deploy arrives with its coded default already applied** to
      every role. A snapshot table would freeze the roster as it stood the day somebody last
      touched the console, so every new capability would land silently denied to everybody.
    - **A row is deleted, not flipped, when it matches the default again** (`services/permissions`
      does this), so the table stays a short, readable list of *decisions somebody made*.

    🔴 A row here is a REQUEST, not an authority: `capabilities.effective_caps` re-checks every one
    against `is_grantable` when it resolves, so a row that would hand a viewer a write or revoke a
    Super Admin's console is inert however it got here (a hand-run INSERT, a restored backup).
    """

    __tablename__ = "role_capabilities"

    # Composite PK: one row per (role, capability) is exactly the constraint we want, enforced by
    # the DB rather than by remembering to check before every insert.
    role: Mapped[str] = mapped_column(String(32), primary_key=True)
    capability: Mapped[str] = mapped_column(String(60), primary_key=True)
    allowed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    # 🔴 NO ForeignKey, unlike `SystemSetting.updated_by_id` above — deliberately. `people.delete_person`
    # hand-nulls every reference to a departing user and knows nothing about this table, so an FK here
    # would make deleting the Super Admin who last edited permissions fail on Postgres with an
    # integrity error (SQLite would let it through, so it would pass locally and break in prod). An
    # override must outlive whoever set it: losing the attribution is a nuisance, a delete that
    # cascades away a live permission decision is an outage.
    updated_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class UserCapability(Base):
    """A per-PERSON deviation, layered on top of their role's (`RoleCapability` above).

    The case this exists for: "Maria specifically may run payroll." Without it the only way to say
    that is to invent a role for one person, and a role per exception is how a permission model
    becomes unreadable.

    🔴 **Resolution order is role defaults -> role overrides -> USER overrides**, and the user layer
    is applied last so it always wins. It is deliberately NOT a way around the invariants: every row
    is re-checked by `capabilities.is_grantable` against **that person's role** when it resolves, so
    a user override cannot hand a `viewer` a write, cannot touch a `locked` capability, and cannot
    change anything for a Super Admin. Same deltas-not-snapshots contract as the role table, and the
    same reason: a capability added in a later deploy must arrive with its default, not denied.

    🔴 The row is keyed by user id and **survives a role change**. That is the honest behaviour — the
    grant was made about the person, not the seat — but it means promoting somebody does not clear
    their exceptions. The console shows every person holding one, so they can be seen and removed;
    `services/permissions.user_overrides` is what it reads.
    """

    __tablename__ = "user_capabilities"

    user_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    capability: Mapped[str] = mapped_column(String(60), primary_key=True)
    allowed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    # No FK, for the reason RoleCapability documents: `people.delete_person` hand-nulls references
    # and knows nothing about this table. Rows for a deleted user are pruned by `prune_orphans`.
    updated_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

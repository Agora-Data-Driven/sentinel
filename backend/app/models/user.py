"""users, teams, qr_tokens."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base
from ..utils.time import utcnow


class ShiftTemplate(Base):
    """A named, reusable schedule (start/end/break/grace) assignable to a team or an employee.

    This is what makes shifts data-driven: new shift types (part-time, night, split) are created and
    edited in the Manage UI — no code changes. ``break_min`` is per-shift, so a 4-hour part-time
    shift can carry a 0-minute break instead of the standard unpaid lunch. ``grace_min`` NULL falls
    back to the system-wide grace. Times are "HH:MM" 24h, applied in PH time; an ``end`` <= ``start``
    is treated as crossing midnight (overnight shift).
    """

    __tablename__ = "shift_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(60), unique=True, nullable=False)
    start: Mapped[str] = mapped_column("start_time", String(5), nullable=False, default="08:00")
    end: Mapped[str] = mapped_column("end_time", String(5), nullable=False, default="17:00")
    break_min: Mapped[int] = mapped_column(Integer, default=60)
    grace_min: Mapped[int | None] = mapped_column(Integer, nullable=True)  # NULL => system default grace
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Exactly one template is the company default — it's the base every shift resolves from when a
    # team/employee has no template of their own. Setting one default clears any previous default.
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    # A team's hours come entirely from its Shift Template. Blank = the company-default template.
    shift_template_id: Mapped[int | None] = mapped_column(ForeignKey("shift_templates.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    members: Mapped[list["User"]] = relationship(back_populates="team")


class UserTeam(Base):
    """ONE ADDITIONAL department for a user — the join row behind multi-department membership.

    Added 2026-08-14. `users.team_id` stays the **primary/home** department and is deliberately not
    replaced by this table, because several rules genuinely need ONE answer and would become
    ambiguous the moment a person had two:

    * **shift + attendance** — `Team.shift_template_id` decides when somebody is late. Two teams
      means two shifts, and "which one is this punch against?" has no honest answer;
    * **payroll + the People directory's Department column** — one row, one department;
    * **`Task.assigned_team_id` defaults and `_derived_labels`** — a card is routed to one team.

    So this table answers the OTHER question — "which departments' work does this person take part
    in?" — and `services/teams.team_ids` is the one place the two are unioned. Every scope rule asks
    that function; nothing outside it should read this relationship directly.

    🔴 The row is a MEMBERSHIP, not a role grant. A team lead in two departments leads both (their
    role is a property of the person, and `task_perms._leads_team` tests the union); an employee in
    two departments reads both and — exactly as with their primary one — writes to neither
    colleague's card. Adding a department can therefore only ever widen what somebody SEES.
    """

    __tablename__ = "user_teams"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(160), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"), nullable=True)
    google_sub: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    profile_pic_url: Mapped[str | None] = mapped_column(String(400), nullable=True)
    # Uploaded profile photo stored in-DB (small, client-resized ~256px JPEG). Cloud Run's disk is
    # ephemeral and there's no object store wired, so the bytes live here and are served by
    # GET /api/people/{id}/avatar. profile_pic_url points at that endpoint (with a ?v= cache-buster).
    profile_pic_data: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    profile_pic_type: Mapped[str | None] = mapped_column(String(60), nullable=True)
    # Password login (PBKDF2). Null = no password set yet (must use Google, or admin sets one).
    password_hash: Mapped[str | None] = mapped_column(String(200), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Per-employee shift override (a Shift Template). Blank = use the department's shift.
    shift_template_id: Mapped[int | None] = mapped_column(ForeignKey("shift_templates.id"), nullable=True)
    hired_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Monthly base salary (Super Admin only — never exposed via public serializers).
    monthly_salary: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    team: Mapped[Team | None] = relationship(back_populates="members")
    qr_tokens: Mapped[list["QRToken"]] = relationship(back_populates="user")
    # 🔴 `selectin`, NOT the default lazy load. `task_perms._dept` asks for this set once per CARD
    # while filtering the board, so a lazy relationship here would be a SELECT per card the first
    # time each user object was touched — the exact shape of the 2,946-query board `CardPrefetch`
    # was written to end (AGENTS.md §5, "the board has a QUERY BUDGET"). `selectin` loads it in one
    # extra query alongside whoever was fetched, and the signed-in user is fetched once per request.
    # `delete-orphan` so removing a department from the form really deletes the row, and deleting a
    # person takes their memberships with them.
    extra_teams: Mapped[list["UserTeam"]] = relationship(
        lazy="selectin", cascade="all, delete-orphan",
        primaryjoin="User.id == UserTeam.user_id",
    )

    @property
    def initials(self) -> str:
        parts = [p for p in (self.name or "").split() if p]
        return ("".join(p[0] for p in parts[:2]) or "?").upper()


class QRToken(Base):
    __tablename__ = "qr_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    user: Mapped[User] = relationship(back_populates="qr_tokens")

"""time_entries — minutes a person logs BY HAND against a growth dimension.

The Mastery Engine records its own minutes (minute buckets in its Firestore — see
services/time_spent.py); this table is everything the engine cannot see: a book read on paper, a
gym session, a course somewhere else, a mentoring call. One row is one block of time on one day,
filed under one dimension, with an optional note.

Kept deliberately separate from the engine's minutes rather than written into them: an engine minute
means "the app saw you active", and a hand-typed row must never be able to impersonate that. The two
are merged only at read time (`time_spent.summary` / `detail`), and every session row says which it is
(`source: engine | manual`).

NEW TABLE, no column changes — the one schema shape `create_all` lands by itself on prod, where
deploys don't run Alembic. `b7e2f4a9c1d6_time_entries.py` is the migrated path, existence-guarded.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base
from ..utils.time import utcnow


class TimeEntry(Base):
    __tablename__ = "time_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    # The PH calendar day the time belongs to, and where in it (HH:MM). `minutes` is the length —
    # stored as a number, not an end time, so a block can't be written inside-out.
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    start_hhmm: Mapped[str] = mapped_column(String(5), nullable=False)
    minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    # A growth dimension (spiritual | professional | philosophical | physical), or `coach` / `other` —
    # the same buckets the engine's minutes are read into, so the two add up on one strip.
    dimension: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Who typed it. Normally the person themselves; an admin may log time on somebody's behalf and
    # the row remembers that it was not self-reported.
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

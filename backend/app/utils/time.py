"""Timezone helpers. Rule: store UTC, display + apply business rules in Asia/Manila (UTC+8).

PH has no DST, so a fixed +8 offset is exact and dependency-free.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

PH_TZ = timezone(timedelta(hours=8), name="Asia/Manila")


def utcnow() -> datetime:
    """Naive UTC timestamp for DB columns (consistent, tz-agnostic storage)."""
    return datetime.utcnow()


def now_ph() -> datetime:
    """Current wall-clock time in Manila (tz-aware)."""
    return datetime.now(PH_TZ)


def to_ph(dt: datetime) -> datetime:
    """Interpret a naive-UTC (or aware) datetime in Manila local time."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(PH_TZ)


def today_ph() -> date:
    return now_ph().date()


def parse_hhmm(value: str) -> time:
    """'08:15' -> time(8, 15). Tolerates missing/blank input by defaulting to 00:00."""
    if not value:
        return time(0, 0)
    hh, _, mm = value.partition(":")
    return time(int(hh), int(mm or 0))


def normalize_hhmm(value: str) -> str:
    """Validate + normalize a shift time to 'HH:MM' 24-hour ('9:0' -> '09:00').

    Raises ValueError on anything that isn't a real 24-hour time (e.g. '1pm', '25:00', blank), so a
    typo can never silently break the attendance engine's late/hours math.
    """
    s = (value or "").strip()
    if not s or ":" not in s:
        raise ValueError("Time must be HH:MM in 24-hour format, e.g. 13:00")
    hh, _, mm = s.partition(":")
    try:
        h, m = int(hh), int(mm)
    except ValueError as exc:
        raise ValueError("Time must be HH:MM in 24-hour format, e.g. 13:00") from exc
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError("Time out of range (00:00–23:59)")
    return f"{h:02d}:{m:02d}"


def minutes_between(start: datetime, end: datetime) -> int:
    return int((end - start).total_seconds() // 60)

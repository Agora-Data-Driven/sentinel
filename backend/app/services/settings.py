"""System settings access. Falls back to sane defaults so the app runs before seeding."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import SystemSetting

DEFAULTS: dict[str, str] = {
    "work_start": "08:00",
    "work_end": "17:00",
    "late_grace": "15",
    "break_duration": "60",
    "work_days": "Mon,Tue,Wed,Thu,Fri",
    "timezone": "Asia/Manila",
    "gym_required_hours": "1",
}

DESCRIPTIONS: dict[str, str] = {
    "work_start": "Default shift start time (HH:MM, PH time)",
    "work_end": "Default shift end time (HH:MM, PH time)",
    "late_grace": "Grace period in minutes before a clock-in counts as late",
    "break_duration": "Standard break allowance in minutes",
    "work_days": "Working days of the week",
    "timezone": "Display + rules timezone",
    "gym_required_hours": "Minimum gym session hours to count as compliant",
}


def get_map(db: Session) -> dict[str, str]:
    stored = {s.key: s.value for s in db.execute(select(SystemSetting)).scalars()}
    return {**DEFAULTS, **stored}


def get(db: Session, key: str) -> str:
    row = db.get(SystemSetting, key)
    return row.value if row else DEFAULTS.get(key, "")


def set_value(db: Session, key: str, value: str, actor_id: int | None) -> tuple[str | None, str]:
    """Upsert a setting. Returns (old_value, new_value) for audit logging."""
    row = db.get(SystemSetting, key)
    old = row.value if row else None
    if row:
        row.value = value
        row.updated_by_id = actor_id
    else:
        db.add(
            SystemSetting(
                key=key,
                value=value,
                description=DESCRIPTIONS.get(key),
                updated_by_id=actor_id,
            )
        )
    return old, value

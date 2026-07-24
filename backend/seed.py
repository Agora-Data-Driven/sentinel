"""Seed Sentinel with realistic sample data across all 19 tables.

Run from the backend/ directory:  python seed.py
Re-running WIPES and rebuilds the database (dev convenience). Pass nothing else — it is idempotent
in the sense that the end state is always the same fresh dataset.
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta

# Allow "python seed.py" from backend/ (so "app" is importable).
sys.path.insert(0, ".")

# Windows consoles default to cp1252; force UTF-8 so status glyphs (→ ✓) print cleanly.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

from app.constants import (  # noqa: E402
    ACTION_BREAK_END,
    ACTION_BREAK_START,
    ACTION_CLOCK_IN,
    ACTION_CLOCK_OUT,
    DAY_LEGS,
    DAY_PULL,
    DAY_PUSH,
    LEAVE_APPROVED,
    LEAVE_PENDING,
    LEAVE_REJECTED,
    NOTIF_ANNOUNCEMENT,
    NOTIF_APPROVAL,
    NOTIF_GYM_MISSING,
    NOTIF_TASK_ASSIGNED,
    PRIORITY_LOW,
    PRIORITY_MEDIUM,
    PRIORITY_URGENT,
    REQ_OVERTIME,
    REQ_PENDING,
    REQ_REGULARIZATION,
    ROLE_ACCOUNT_MANAGER,
    ROLE_ADMIN,
    ROLE_EMPLOYEE,
    ROLE_INTERN,
    ROLE_SUPER_ADMIN,
    ROLE_TEAM_LEAD,
    TASK_BLOCKED,
    TASK_COMPLETED,
    TASK_FOR_REVIEW,
    TASK_IN_PROGRESS,
    TASK_REVISION,
    TASK_TODO,
    TASK_WAITING_CLIENT,
)
from app.database import Base, SessionLocal, engine  # noqa: E402
from app import models  # noqa: E402  (registers mappers)
from app.models import (  # noqa: E402
    AttendanceEvent,
    Client,
    ExerciseLibrary,
    GymExercise,
    GymLog,
    LeaveBalance,
    LeaveRequest,
    LeaveType,
    Notification,
    ShiftTemplate,
    Task,
    TaskComment,
    TaskHistory,
    Team,
    User,
)
from app.services import attendance as att  # noqa: E402
from app.services import gym as gym_svc  # noqa: E402
from app.services import leave as leave_svc  # noqa: E402
from app.services import settings as settings_svc  # noqa: E402
from app.utils.qr import new_token  # noqa: E402
from app.utils.passwords import hash_password  # noqa: E402
from app.utils.time import today_ph  # noqa: E402

# Default password for every seeded account (change it in Manage after first login).
DEFAULT_PASSWORD = "Agora2026!"


def ph_to_utc(d: date, hh: int, mm: int) -> datetime:
    """A PH wall-clock time on date d -> naive UTC instant (what the DB stores)."""
    return datetime(d.year, d.month, d.day, hh, mm) - timedelta(hours=8)


def recent_weekdays(n: int, include_today: bool) -> list[date]:
    days: list[date] = []
    d = today_ph()
    if not include_today:
        d -= timedelta(days=1)
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d -= timedelta(days=1)
    return list(reversed(days))


# --------------------------------------------------------------------------
# Reference data
# --------------------------------------------------------------------------
TEAMS = [
    ("Acquisition", "08:00", "17:00", 60),
    ("Development", "09:00", "18:00", 60),
    ("Data Analyst", "08:00", "17:00", 60),
    ("Lifecycle", "08:00", "17:00", 60),
]

USERS = [
    ("Melo Yelo", "melo@agora.ph", ROLE_SUPER_ADMIN, None, "0917-100-0001"),
    ("Maria Santos", "maria@agora.ph", ROLE_ADMIN, None, "0917-100-0002"),
    ("Leo Vasquez", "leo@agora.ph", ROLE_ACCOUNT_MANAGER, None, "0917-100-0003"),
    ("Bong Cruz", "bong@agora.ph", ROLE_TEAM_LEAD, "Acquisition", "0917-100-0004"),
    ("Ana Reyes", "ana@agora.ph", ROLE_EMPLOYEE, "Data Analyst", "0917-100-0005"),
    ("Carlo Dizon", "carlo@agora.ph", ROLE_EMPLOYEE, "Development", "0917-100-0006"),
    ("Dana Lim", "dana@agora.ph", ROLE_EMPLOYEE, "Lifecycle", "0917-100-0007"),
    ("Earl Santos", "earl@agora.ph", ROLE_EMPLOYEE, "Acquisition", "0917-100-0008"),
    ("Faye Torres", "faye@agora.ph", ROLE_EMPLOYEE, "Data Analyst", "0917-100-0009"),
    ("Grace Navarro", "grace@agora.ph", ROLE_INTERN, "Development", "0917-100-0010"),
]

CLIENTS = [
    ("Acme Corp", "ops@acme.example", "acme"),
    ("BrandCo", "hello@brandco.example", "brandco"),
    ("NovaCorp", "team@novacorp.example", "novacorp"),
    ("Riverdance RV", "info@riverdance.example", "riverdance"),
]

LEAVE_TYPES = [
    ("Sick Leave", 10, "Monthly", "Auto ≤2 days, manager >2", 0),
    ("Vacation Leave", 15, "Monthly", "Manager approval", 5),
    ("Personal Leave", 5, "Yearly", "Manager approval", 0),
    ("Emergency Leave", 3, "Yearly", "Auto-approved", 0),
    ("Unpaid Leave", -1, "—", "Admin approval", 0),
]

# Exercise library: 50+ across Push / Pull / Legs / Custom(Cardio).
LIBRARY: list[tuple[str, str, list[str], str]] = [
    # Push
    ("Bench Press", "Chest", [DAY_PUSH], "Barbell"),
    ("Incline Bench Press", "Chest", [DAY_PUSH], "Barbell"),
    ("Incline DB Press", "Chest", [DAY_PUSH], "Dumbbell"),
    ("Overhead Press", "Shoulders", [DAY_PUSH], "Barbell"),
    ("Seated DB Shoulder Press", "Shoulders", [DAY_PUSH], "Dumbbell"),
    ("Lateral Raises", "Shoulders", [DAY_PUSH], "Dumbbell"),
    ("Front Raises", "Shoulders", [DAY_PUSH], "Dumbbell"),
    ("Cable Fly", "Chest", [DAY_PUSH], "Cable"),
    ("Pec Deck", "Chest", [DAY_PUSH], "Machine"),
    ("Tricep Pushdown", "Triceps", [DAY_PUSH], "Cable"),
    ("OH Tricep Extension", "Triceps", [DAY_PUSH], "Dumbbell"),
    ("Skullcrushers", "Triceps", [DAY_PUSH], "Barbell"),
    ("Dips", "Triceps", [DAY_PUSH], "Bodyweight"),
    ("Close-Grip Bench Press", "Triceps", [DAY_PUSH], "Barbell"),
    # Pull
    ("Barbell Row", "Back", [DAY_PULL], "Barbell"),
    ("Pull-ups", "Back", [DAY_PULL], "Bodyweight"),
    ("Chin-ups", "Back", [DAY_PULL], "Bodyweight"),
    ("Lat Pulldown", "Back", [DAY_PULL], "Cable"),
    ("Seated Cable Row", "Back", [DAY_PULL], "Cable"),
    ("T-Bar Row", "Back", [DAY_PULL], "Machine"),
    ("Face Pulls", "Rear Delts", [DAY_PULL], "Cable"),
    ("Reverse Fly", "Rear Delts", [DAY_PULL], "Dumbbell"),
    ("Shrugs", "Traps", [DAY_PULL], "Dumbbell"),
    ("Barbell Curl", "Biceps", [DAY_PULL], "Barbell"),
    ("Hammer Curl", "Biceps", [DAY_PULL], "Dumbbell"),
    ("Preacher Curl", "Biceps", [DAY_PULL], "Machine"),
    ("Cable Curl", "Biceps", [DAY_PULL], "Cable"),
    ("Concentration Curl", "Biceps", [DAY_PULL], "Dumbbell"),
    # Legs
    ("Squats", "Quads", [DAY_LEGS], "Barbell"),
    ("Front Squat", "Quads", [DAY_LEGS], "Barbell"),
    ("Romanian Deadlift", "Hamstrings", [DAY_LEGS], "Barbell"),
    ("Deadlift", "Hamstrings", [DAY_LEGS, DAY_PULL], "Barbell"),
    ("Leg Press", "Quads", [DAY_LEGS], "Machine"),
    ("Leg Curl", "Hamstrings", [DAY_LEGS], "Machine"),
    ("Leg Extension", "Quads", [DAY_LEGS], "Machine"),
    ("Bulgarian Split Squat", "Quads", [DAY_LEGS], "Dumbbell"),
    ("Calf Raises", "Calves", [DAY_LEGS], "Machine"),
    ("Seated Calf Raise", "Calves", [DAY_LEGS], "Machine"),
    ("Hip Thrust", "Glutes", [DAY_LEGS], "Barbell"),
    ("Lunges", "Quads", [DAY_LEGS], "Dumbbell"),
    ("Goblet Squat", "Quads", [DAY_LEGS], "Dumbbell"),
    # Custom / Cardio / Core
    ("Treadmill", "Cardio", ["Custom"], "Machine"),
    ("Cycling", "Cardio", ["Custom"], "Machine"),
    ("Rowing", "Cardio", ["Custom"], "Machine"),
    ("Jump Rope", "Cardio", ["Custom"], "Bodyweight"),
    ("Stair Climber", "Cardio", ["Custom"], "Machine"),
    ("Plank", "Core", ["Custom"], "Bodyweight"),
    ("Hanging Leg Raise", "Core", ["Custom"], "Bodyweight"),
    ("Cable Crunch", "Core", ["Custom"], "Cable"),
    ("Russian Twist", "Core", ["Custom"], "Bodyweight"),
    ("Clean & Press", "Full Body", ["Custom"], "Barbell"),
    ("Kettlebell Swing", "Full Body", ["Custom"], "Kettlebell"),
    ("Battle Ropes", "Cardio", ["Custom"], "Rope"),
]


def wipe_and_create() -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def run(minimal: bool = False) -> None:
    mode = "MINIMAL (reference data + 1 admin only)" if minimal else "FULL demo dataset"
    print(f"→ Rebuilding schema (all 19 tables) — {mode}…")
    wipe_and_create()
    db = SessionLocal()
    try:
        # --- System settings -------------------------------------------------
        for k, v in settings_svc.DEFAULTS.items():
            settings_svc.set_value(db, k, v, None)
        db.commit()

        # --- Shift templates (the single source of truth for schedules) ------
        # One template per distinct window in TEAMS; the standard 8–5 is the company default.
        DEFAULT_WINDOW = ("08:00", "17:00", 60)
        WINDOW_NAMES = {("08:00", "17:00", 60): "Day (8AM–5PM)", ("09:00", "18:00", 60): "Day (9AM–6PM)"}
        tpl_by_window: dict[tuple, ShiftTemplate] = {}
        for _name, s, e, brk in TEAMS:
            key = (s, e, brk)
            if key not in tpl_by_window:
                tpl = ShiftTemplate(name=WINDOW_NAMES.get(key, f"{s}–{e}"), start=s, end=e,
                                    break_min=brk, is_default=(key == DEFAULT_WINDOW))
                db.add(tpl)
                tpl_by_window[key] = tpl
        db.commit()
        if not any(t.is_default for t in tpl_by_window.values()):
            next(iter(tpl_by_window.values())).is_default = True
            db.commit()

        # --- Teams (each points at a template; blank would inherit the default) ----
        teams: dict[str, Team] = {}
        for name, s, e, brk in TEAMS:
            t = Team(name=name, shift_template_id=tpl_by_window[(s, e, brk)].id)
            db.add(t)
            teams[name] = t
        db.commit()

        # --- Users + QR tokens ----------------------------------------------
        # Minimal keeps ONLY the first user (Super Admin) so someone can log in and add the real
        # team via People > Add Employee. Full seeds all 10 demo users.
        users_to_seed = USERS[:1] if minimal else USERS
        users: dict[str, User] = {}
        for i, (name, email, role, team_name, phone) in enumerate(users_to_seed):
            u = User(
                name=name, email=email, role=role, phone=phone, is_active=True,
                team_id=teams[team_name].id if team_name else None,
                hired_date=date(2023, 1, 1) + timedelta(days=i * 47),
                password_hash=hash_password(DEFAULT_PASSWORD),
            )
            db.add(u)
            db.flush()
            db.add(models.QRToken(user_id=u.id, token=new_token()))
            users[name] = u
        db.commit()

        # --- Clients (skipped in minimal — add real clients later) -----------
        clients: dict[str, Client] = {}
        if not minimal:
            for name, contact, atrium in CLIENTS:
                c = Client(name=name, contact_email=contact, atrium_client_id=atrium)
                db.add(c)
                clients[name] = c
            db.commit()

        # --- Leave types + balances -----------------------------------------
        for name, bal, accrual, approval, carry in LEAVE_TYPES:
            db.add(LeaveType(name=name, annual_balance=bal, accrual_type=accrual,
                             requires_approval=approval, carry_over_days=carry))
        db.commit()
        year = today_ph().year
        for u in users.values():
            leave_svc.ensure_balances(db, u.id, year, commit=False)
        db.commit()

        # --- Exercise library ------------------------------------------------
        for name, muscle, days, equip in LIBRARY:
            db.add(ExerciseLibrary(
                name=name, muscle_group=muscle, day_types_json=json.dumps(days),
                equipment=equip, instructions=f"Perform {name} with controlled form.",
            ))
        db.commit()
        print(f"  seeded {len(LIBRARY)} exercises, {len(users)} user(s), {len(clients)} client(s)")

        if minimal:
            print("✓ Minimal seed complete — reference data + Super Admin only.")
            print(f"  Log in: melo@agora.ph  /  {DEFAULT_PASSWORD}  (Super Admin — change it in Manage).")
            print("  Then add your real team in Manage > Employees.")
            return

        _seed_attendance(db, users)
        _seed_gym(db, users)
        _seed_tasks(db, users, teams, clients)
        _seed_leave(db, users)
        _seed_notifications(db, users)

        print("✓ Seed complete.")
        print(f"  Log in at /login with any seeded email + password '{DEFAULT_PASSWORD}'"
              " (e.g. melo@agora.ph = Super Admin).")
    finally:
        db.close()


def _tracked_users(users: dict[str, User]) -> list[User]:
    # Everyone punches except the Super Admin (kiosk operator) — gives ~9 tracked staff.
    return [u for name, u in users.items() if name != "Melo Yelo"]


def _seed_attendance(db, users) -> None:
    staff = _tracked_users(users)
    days = recent_weekdays(5, include_today=False)
    handover_pool = [
        "Handed off the Acme creatives to review; awaiting client font files.",
        "NovaCorp report is 80% done — pick up the paid-social section tomorrow.",
        "Left BrandCo ad copy in For Review. Blocker: legal sign-off pending.",
        "Data pull for Riverdance finished; dashboards refreshed.",
    ]
    for di, day in enumerate(days):
        absent = staff[di % len(staff)]
        late_a = staff[(di + 2) % len(staff)]
        late_b = staff[(di + 4) % len(staff)]
        for si, u in enumerate(staff):
            if u.id == absent.id:
                continue  # one absentee per day
            if u.id in (late_a.id, late_b.id):
                in_h, in_m = 8, 35 + (si % 3) * 5  # late
            else:
                in_h, in_m = (7, 55) if si % 2 else (8, 8)  # on time (within grace)
            # Development team shifts start 09:00 — nudge them an hour later.
            if u.team_id == users["Carlo Dizon"].team_id:
                in_h += 1
            db.add(AttendanceEvent(user_id=u.id, date=day, action=ACTION_CLOCK_IN,
                                   time=ph_to_utc(day, in_h, in_m), device="kiosk"))
            db.add(AttendanceEvent(user_id=u.id, date=day, action=ACTION_BREAK_START,
                                   time=ph_to_utc(day, 12, 0), device="kiosk"))
            db.add(AttendanceEvent(user_id=u.id, date=day, action=ACTION_BREAK_END,
                                   time=ph_to_utc(day, 13, 0), device="kiosk"))
            out_h, out_m = (17, 0) if si % 2 else (17, 40)  # some overtime
            note = handover_pool[si % len(handover_pool)] if si % 3 == 0 else None
            db.add(AttendanceEvent(user_id=u.id, date=day, action=ACTION_CLOCK_OUT,
                                   time=ph_to_utc(day, out_h + (1 if u.team_id == users["Carlo Dizon"].team_id else 0), out_m),
                                   device="kiosk", handover_note=note))
    db.commit()

    # Today: most staff clocked in (no clock-out yet) so "present today" is live.
    today = today_ph()
    if today.weekday() < 5:
        for si, u in enumerate(staff):
            if si % 5 == 0:
                continue  # a few not in yet — kiosk stays usable for a live demo
            db.add(AttendanceEvent(user_id=u.id, date=today, action=ACTION_CLOCK_IN,
                                   time=ph_to_utc(today, 8, 3 + si % 10), device="kiosk"))
        db.commit()

    # Build every daily summary from the raw events.
    all_days = days + ([today] if today.weekday() < 5 else [])
    for u in staff:
        for day in all_days:
            att.recompute_summary(db, u, day, commit=False)
    db.commit()

    # A regularization + an overtime request (pending) to populate the approvals queue.
    db.add(models.AttendanceRequest(
        user_id=users["Ana Reyes"].id, date=days[-1], request_type=REQ_REGULARIZATION,
        reason="Forgot to clock out — left at 5:10pm.", old_value="—", new_value="17:10",
        status=REQ_PENDING,
    ))
    db.add(models.AttendanceRequest(
        user_id=users["Earl Santos"].id, date=days[-2], request_type=REQ_OVERTIME,
        reason="Stayed late to finish the Acme launch checklist.", old_value="8h", new_value="9h40m",
        status=REQ_PENDING,
    ))
    db.commit()
    print("  seeded attendance events + daily summaries + 2 pending requests")


def _seed_gym(db, users) -> None:
    rotation = [DAY_PUSH, DAY_PULL, DAY_LEGS]
    exercises_by_day = {
        DAY_PUSH: [("Bench Press", "Chest", 60), ("Overhead Press", "Shoulders", 40),
                   ("Incline DB Press", "Chest", 28), ("Lateral Raises", "Shoulders", 12),
                   ("Tricep Pushdown", "Triceps", 25)],
        DAY_PULL: [("Barbell Row", "Back", 70), ("Lat Pulldown", "Back", 55),
                   ("Seated Cable Row", "Back", 60), ("Barbell Curl", "Biceps", 30),
                   ("Face Pulls", "Rear Delts", 20)],
        DAY_LEGS: [("Squats", "Quads", 90), ("Romanian Deadlift", "Hamstrings", 80),
                   ("Leg Press", "Quads", 160), ("Leg Curl", "Hamstrings", 40),
                   ("Calf Raises", "Calves", 50)],
    }
    gym_staff = [users[n] for n in ("Bong Cruz", "Ana Reyes", "Carlo Dizon", "Dana Lim", "Earl Santos", "Grace Navarro")]
    days = recent_weekdays(5, include_today=True)
    for di, day in enumerate(days):
        day_type = rotation[di % 3]
        for ui, u in enumerate(gym_staff):
            roll = (di + ui) % 4
            if roll == 3:
                continue  # missing session -> shows as a gap in compliance
            duration = 72 if roll != 2 else 41  # roll==2 => incomplete (<60m)
            start = ph_to_utc(day, 18, 30)
            log = GymLog(
                user_id=u.id, date=day, day_type=day_type, start_time=start,
                end_time=start + timedelta(minutes=duration), duration_minutes=duration,
            )
            db.add(log)
            db.flush()
            for ei, (name, muscle, base) in enumerate(exercises_by_day[day_type]):
                sets = []
                for s in range(1, 4):
                    kg = base + di * 2.5 + (s - 1) * 2.5
                    sets.append({"set": s, "kg": kg, "reps": 10 - (s - 1),
                                 "type": "Warm-up" if s == 1 else "Normal",
                                 "done": True, "pr": bool(di == len(days) - 1 and ei == 0 and s == 3)})
                db.add(GymExercise(
                    gym_log_id=log.id, exercise_name=name, muscle_group=muscle,
                    weight_value=max(s["kg"] for s in sets), weight_unit="kg",
                    sets=len(sets), reps=10, set_type="Normal", sets_json=json.dumps(sets),
                ))
            log.status = gym_svc.compute_status(duration, len(exercises_by_day[day_type]), 1.0)
    db.commit()
    print("  seeded gym logs (PPL rotation, completed/incomplete/missing mix)")


def _seed_tasks(db, users, teams, clients) -> None:
    leo = users["Leo Vasquez"]
    T = today_ph()

    def mk(title, client, team, assignee, priority, status, labels, due_offset, desc,
           checklist=None, campaign=None, ctype=None, deliverable=None, atrium=False,
           client_notes=None, internal=None):
        t = Task(
            title=title,
            description=desc,
            client_id=clients[client].id if client else None,
            campaign=campaign,
            content_type=ctype,
            account_manager_id=leo.id,
            assigned_team_id=teams[team].id if team else None,
            assigned_to_id=users[assignee].id if assignee else None,
            priority=priority, status=status, due_date=T + timedelta(days=due_offset),
            labels_json=json.dumps(labels),
            checklist_json=json.dumps(checklist or []),
            deliverable_url=deliverable, atrium_visible=atrium,
            client_facing_notes=client_notes, internal_notes=internal,
        )
        db.add(t)
        db.flush()
        db.add(TaskHistory(task_id=t.id, changed_by_id=leo.id, field_changed="created",
                           old_value=None, new_value=status))
        return t

    specs = [
        ("Q3 Paid Social Launch — Acme", "Acme Corp", "Acquisition", "Earl Santos", PRIORITY_URGENT,
         TASK_IN_PROGRESS, ["Ads"], 2, "Launch the Q3 paid-social campaign across Meta + TikTok.",
         [{"text": "Audience research", "done": True}, {"text": "Creative brief", "done": True},
          {"text": "Build campaigns", "done": False}, {"text": "QA pixels", "done": False}],
         "Q3 Growth", "Paid Social", None, False, "Targeting PH metros, 25-45.", "Budget cap ₱180k/mo."),
        ("Homepage Hero Redesign", "BrandCo", "Development", "Carlo Dizon", PRIORITY_MEDIUM,
         TASK_IN_PROGRESS, ["Dev", "Design"], 5, "Rebuild the hero section, mobile-first.",
         [{"text": "Wireframe", "done": True}, {"text": "Build component", "done": False}],
         "Site Refresh", "Web", None, False, None, "Use the new design tokens."),
        ("Blog: 'Attribution 101'", "NovaCorp", "Data Analyst", "Ana Reyes", PRIORITY_MEDIUM,
         TASK_FOR_REVIEW, ["Copy", "SEO"], 1, "1,500-word explainer on marketing attribution.",
         [{"text": "Outline", "done": True}, {"text": "Draft", "done": True}, {"text": "Edit", "done": False}],
         "Content Engine", "Blog", "https://docs.example/nova-attribution", False, "Keep it beginner-friendly."),
        ("Lifecycle Email Flow — Welcome", "BrandCo", "Lifecycle", "Dana Lim", PRIORITY_LOW,
         TASK_TODO, ["Copy"], 7, "5-email welcome automation.",
         [{"text": "Map the flow", "done": False}], "Retention", "Email", None, False, None, None),
        ("SEO Audit", "NovaCorp", "Data Analyst", "Faye Torres", PRIORITY_MEDIUM, TASK_TODO,
         ["SEO"], 9, "Technical + on-page SEO audit.", [], "Organic", "Report", None, False, None, None),
        ("Google Ads Restructure", "Acme Corp", "Acquisition", "Bong Cruz", PRIORITY_URGENT,
         TASK_REVISION, ["Ads"], 0, "Restructure into SKAG → SPAG.", [{"text": "Export current", "done": True}],
         "Q3 Growth", "Paid Search", None, False, "Client wants ROAS focus.", "Prev agency left a mess."),
        ("Landing Page Copy — RV Summer", "Riverdance RV", "Lifecycle", "Dana Lim", PRIORITY_MEDIUM,
         TASK_WAITING_CLIENT, ["Copy"], 3, "Summer promo landing page copy.", [],
         "Summer Sale", "Landing", "https://docs.example/rv-summer", True, "Awaiting client's promo dates.", None),
        ("Monthly Report — Acme (June)", "Acme Corp", "Data Analyst", "Ana Reyes", PRIORITY_LOW,
         TASK_COMPLETED, ["SEO", "Ads"], -2, "June performance report.",
         [{"text": "Pull data", "done": True}, {"text": "Write insights", "done": True}],
         "Reporting", "Report", "https://docs.example/acme-june", True, "Shared to Atrium.", None),
        ("TikTok Creative Batch #4", "BrandCo", "Acquisition", "Earl Santos", PRIORITY_MEDIUM,
         TASK_IN_PROGRESS, ["Design", "Ads"], 4, "6 short-form video ads.", [{"text": "Scripts", "done": True}],
         "Q3 Growth", "Video", None, False, None, None),
        ("Fix Checkout Bug", "Riverdance RV", "Development", "Carlo Dizon", PRIORITY_URGENT,
         TASK_BLOCKED, ["Dev"], -1, "Cart total miscalculates with promo codes.", [],
         "Site Refresh", "Bugfix", None, False, None, "Blocked on Stripe API keys from client."),
        ("Persona Refresh Workshop", "NovaCorp", "Lifecycle", "Dana Lim", PRIORITY_LOW, TASK_TODO,
         ["Copy"], 12, "Facilitate persona workshop.", [], "Strategy", "Workshop", None, False, None, None),
        ("Meta Pixel + CAPI Setup", "Acme Corp", "Development", "Grace Navarro", PRIORITY_MEDIUM,
         TASK_IN_PROGRESS, ["Dev"], 6, "Server-side conversions via CAPI.",
         [{"text": "Pixel base", "done": True}, {"text": "CAPI gateway", "done": False}],
         "Q3 Growth", "Tech", None, False, None, None),
        ("Keyword Map — RV", "Riverdance RV", "Data Analyst", "Faye Torres", PRIORITY_MEDIUM,
         TASK_FOR_REVIEW, ["SEO"], 1, "Keyword map for the RV rental category.", [],
         "Organic", "Report", None, False, None, None),
        ("Newsletter — July", "BrandCo", "Lifecycle", "Dana Lim", PRIORITY_LOW, TASK_TODO,
         ["Copy", "Design"], 8, "July newsletter.", [], "Retention", "Email", None, False, None, None),
        ("Brand Guidelines v2", "NovaCorp", "Development", "Carlo Dizon", PRIORITY_LOW, TASK_COMPLETED,
         ["Design"], -5, "Refresh brand guidelines PDF.", [{"text": "Design", "done": True}],
         "Brand", "Doc", "https://docs.example/nova-brand", True, "Delivered.", None),
        ("Competitor Teardown — Acme", "Acme Corp", "Acquisition", "Bong Cruz", PRIORITY_MEDIUM,
         TASK_TODO, ["Ads", "SEO"], 10, "Teardown of 3 competitors.", [], "Strategy", "Report", None, False, None, None),
    ]
    made = []
    for s in specs:
        made.append(mk(*s))
    db.commit()

    # A few comment threads.
    comment_seed = [
        (made[0].id, "Bong Cruz", "Creatives are in — @Earl can you QA the pixel events?"),
        (made[0].id, "Earl Santos", "On it. Will confirm by EOD."),
        (made[2].id, "Leo Vasquez", "Great draft. Tighten the intro and it's ready for the client."),
        (made[5].id, "Leo Vasquez", "Client requested a ROAS-first structure — please revise."),
        (made[9].id, "Carlo Dizon", "Blocked: still waiting on Stripe keys. Flagged to the client."),
    ]
    for task_id, author, body in comment_seed:
        db.add(TaskComment(task_id=task_id, author_id=users[author].id, body=body))
    db.commit()
    print(f"  seeded {len(specs)} tasks across all columns + comments + history")


def _seed_leave(db, users) -> None:
    types = {lt.name: lt for lt in db.query(LeaveType).all()}
    T = today_ph()
    reqs = [
        ("Ana Reyes", "Vacation Leave", 5, 9, "Family trip to Palawan.", LEAVE_PENDING),
        ("Carlo Dizon", "Sick Leave", -1, -1, "Flu — doctor's advice to rest.", LEAVE_PENDING),
        ("Dana Lim", "Personal Leave", 14, 14, "Errand at city hall.", LEAVE_PENDING),
        ("Earl Santos", "Vacation Leave", -20, -18, "Long weekend in Baguio.", LEAVE_APPROVED),
        ("Faye Torres", "Emergency Leave", -8, -8, "Family emergency.", LEAVE_APPROVED),
        ("Grace Navarro", "Vacation Leave", 2, 6, "Semester break.", LEAVE_REJECTED),
    ]
    maria = users["Maria Santos"]
    for name, ltype, start_off, end_off, reason, status in reqs:
        u = users[name]
        lt = types[ltype]
        start = T + timedelta(days=start_off)
        end = T + timedelta(days=end_off)
        days = leave_svc.count_days(start, end)
        r = LeaveRequest(user_id=u.id, leave_type_id=lt.id, start_date=start, end_date=end,
                         total_days=days, reason=reason, status=status)
        if status in (LEAVE_APPROVED, LEAVE_REJECTED):
            r.reviewed_by_id = maria.id
        db.add(r)
        db.flush()
        if status == LEAVE_APPROVED:
            leave_svc.apply_approval(db, u.id, lt.id, days, start.year)
    db.commit()
    print("  seeded leave requests (3 pending, 2 approved, 1 rejected)")


def _seed_notifications(db, users) -> None:
    T = today_ph()
    notes = [
        ("Maria Santos", NOTIF_APPROVAL, "Vacation request from Ana Reyes (5d)", "Family trip to Palawan.", "/leave", False),
        ("Maria Santos", NOTIF_APPROVAL, "Regularization request from Ana Reyes", "Forgot to clock out.", "/attendance", False),
        ("Leo Vasquez", NOTIF_TASK_ASSIGNED, "Task ready for review: Blog 'Attribution 101'", None, "/tasks", False),
        ("Earl Santos", NOTIF_TASK_ASSIGNED, "New task assigned: TikTok Creative Batch #4", None, "/tasks", True),
        ("Carlo Dizon", NOTIF_GYM_MISSING, "No gym session logged today", "Log your session before EOD.", "/gym", False),
        ("Bong Cruz", NOTIF_APPROVAL, "Google Ads Restructure moved to Revision Needed", None, "/tasks", True),
        ("Grace Navarro", NOTIF_ANNOUNCEMENT, "Welcome to Sentinel 🎉", "Your ops hub is live.", "/dashboard", False),
        ("Dana Lim", NOTIF_TASK_ASSIGNED, "New task assigned: Landing Page Copy — RV Summer", None, "/tasks", False),
    ]
    for name, ntype, title, body, link, read in notes:
        db.add(Notification(user_id=users[name].id, type=ntype, title=title, body=body,
                            link=link, is_read=read))
    db.commit()
    print("  seeded notifications (unread mix)")


if __name__ == "__main__":
    run(minimal="--minimal" in sys.argv)

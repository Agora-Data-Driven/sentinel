"""SQLAlchemy models for all 19 Sentinel tables, grouped by domain.

Importing this package registers every mapper on ``Base.metadata`` so ``create_all`` builds the
full schema. The tables:

    users, teams, qr_tokens                          -> user.py
    clients                                          -> client.py
    tasks, task_comments, task_history,
    atrium_approvals                                 -> task.py
    attendance_events, daily_attendance_summary,
    attendance_requests                              -> attendance.py
    leave_types, leave_balances, leave_requests      -> leave.py
    gym_logs, gym_exercises, exercise_library        -> gym.py
    body_metrics, personal_records,
    development_profiles, career_achievements,
    professional_goals, growth_items,
    reading_items, reading_progress                  -> development.py
    notifications                                    -> notification.py
    audit_logs, system_settings                      -> system.py
"""
from .attendance import AttendanceEvent, AttendanceRequest, DailyAttendanceSummary
from .client import Client
from .development import (
    BodyMetric,
    CareerAchievement,
    DevelopmentProfile,
    GrowthItem,
    PersonalRecord,
    ProfessionalGoal,
    ReadingItem,
    ReadingProgress,
    Skill,
)
from .gym import ExerciseLibrary, GymExercise, GymLog, GymPlanOverride, GymSchedule
from .leave import LeaveBalance, LeaveRequest, LeaveType
from .notification import Notification
from .payroll import PayrollEntry
from .system import AuditLog, SystemSetting
from .task import AtriumApproval, Task, TaskComment, TaskHistory
from .user import QRToken, Team, User

__all__ = [
    "Team",
    "User",
    "QRToken",
    "Client",
    "Task",
    "TaskComment",
    "TaskHistory",
    "AtriumApproval",
    "AttendanceEvent",
    "DailyAttendanceSummary",
    "AttendanceRequest",
    "LeaveType",
    "LeaveBalance",
    "LeaveRequest",
    "GymLog",
    "GymExercise",
    "GymSchedule",
    "GymPlanOverride",
    "ExerciseLibrary",
    "BodyMetric",
    "PersonalRecord",
    "DevelopmentProfile",
    "CareerAchievement",
    "ProfessionalGoal",
    "GrowthItem",
    "Skill",
    "ReadingItem",
    "ReadingProgress",
    "Notification",
    "PayrollEntry",
    "AuditLog",
    "SystemSetting",
]

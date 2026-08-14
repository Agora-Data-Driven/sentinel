"""SQLAlchemy models for every Sentinel table, grouped by domain.

Importing this package registers every mapper on ``Base.metadata`` so ``create_all`` builds the
full schema. The tables:

    users, teams, user_teams, qr_tokens              -> user.py
    clients                                          -> client.py
    tasks, task_comments, task_history,
    atrium_approvals                                 -> task.py
    attendance_events, daily_attendance_summary,
    attendance_requests                              -> attendance.py
    leave_types, leave_balances, leave_requests      -> leave.py
    gym_logs, gym_exercises, gym_routines,
    exercise_library                                 -> gym.py
    body_metrics, personal_records,
    development_profiles, career_achievements,
    professional_goals, growth_items,
    reading_items, reading_progress,
    mentor_transcripts                               -> development.py
    notifications                                    -> notification.py
    audit_logs, system_settings                      -> system.py
"""
from .attendance import AttendanceEvent, AttendanceRequest, DailyAttendanceSummary
from .client import Client
from .development import (
    BodyMetric,
    CareerAchievement,
    DevelopmentArea,
    DevelopmentProfile,
    GrowthItem,
    MentorTranscript,
    PersonalRecord,
    PhysicalGoal,
    ProfessionalGoal,
    ReadingItem,
    ReadingProgress,
    Skill,
)
from .gym import ExerciseLibrary, GymExercise, GymLog, GymPlanOverride, GymRoutine, GymSchedule
from .leave import LeaveBalance, LeaveRequest, LeaveType
from .notification import Notification
from .payroll import PayrollEntry
from .system import AuditLog, SystemSetting
from .task import (AtriumApproval, RecurringService, ServiceTemplate, Task, TaskComment,
                   TaskHistory, TaskRequest, TaskSupporter, TaskVocabItem)
from .user import QRToken, ShiftTemplate, Team, User, UserTeam

__all__ = [
    "Team",
    "User",
    "UserTeam",
    "QRToken",
    "ShiftTemplate",
    "Client",
    "Task",
    "TaskComment",
    "TaskHistory",
    "TaskSupporter",
    "AtriumApproval",
    "TaskRequest",
    "RecurringService",
    "ServiceTemplate",
    "TaskVocabItem",
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
    "GymRoutine",
    "ExerciseLibrary",
    "BodyMetric",
    "PersonalRecord",
    "DevelopmentProfile",
    "CareerAchievement",
    "ProfessionalGoal",
    "PhysicalGoal",
    "DevelopmentArea",
    "GrowthItem",
    "Skill",
    "ReadingItem",
    "ReadingProgress",
    "MentorTranscript",
    "Notification",
    "PayrollEntry",
    "AuditLog",
    "SystemSetting",
]

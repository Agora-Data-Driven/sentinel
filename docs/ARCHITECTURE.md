# Sentinel — Architecture & API reference

Deep reference. Read [../CLAUDE.md](../CLAUDE.md) first for the operating rules and gotchas.

---

## Request lifecycle

```
Browser (frontend/static/js/*.js — vanilla, no build)
   │  api(path, opts)  →  fetch with credentials
   ▼
FastAPI (backend/app/main.py)
   │  SecurityHeadersMiddleware   CSP · Permissions-Policy · HSTS   (middleware.py)
   │  observability               request logging                    (observability.py)
   │  Depends(get_current_user)   JWT cookie → else portal ag_sso    (security.py)
   │  Depends(require_min_role)   RBAC → real 403                    (security.py)
   ▼
routers/<domain>.py        thin — parse, guard, delegate
   ▼
services/<domain>.py       business logic
   ▼
models/<domain>.py         SQLAlchemy → Postgres (prod) / SQLite (local)
   ▼
serializers.py             model → dict   ← FIELD EXPOSURE BOUNDARY
```

**`serializers.py` is a security boundary, not a formatting convenience.** The
internal-vs-client-safe split (what may cross into Atrium) is enforced there.

---

## Database schema — 33 tables

### Identity & org
| Table | Notes |
|---|---|
| `users` | **Source of truth for who may sign in.** SSO/Google authenticate; this table authorizes. |
| `teams` | Org units |
| `clients` | Client accounts (task//report scoping) |
| `qr_tokens` | Rotating badge tokens for the kiosk |

### Attendance
| Table | Notes |
|---|---|
| `attendance_events` | Raw punches (in/out/break). UTC. |
| `daily_attendance_summary` | Rolled-up day view; late detection, overtime |
| `attendance_requests` | Regularization / overtime approval workflow |

### Gym
| Table | Notes |
|---|---|
| `gym_logs` | A workout session |
| `gym_exercises` | Per-set rows (KG × REPS × type) inside a session |
| `exercise_library` | 50+ catalogued exercises (Push/Pull/Legs/Custom) |
| `gym_schedules` | Weekly split **+ `cardio_json`** |
| `gym_plan_overrides` | Per-date overrides **+ `cardio`** |
| `body_metrics` | Weight/measurements over time |
| `personal_records` | PRs |

### Development (holistic hub)
| Table | Notes |
|---|---|
| `development_profiles` | Per-user development record |
| `career_achievements`, `professional_goals` | Career track |
| `growth_items`, `skills` | Growth track |
| `reading_items`, `reading_progress` | Reading canon + per-user progress |

### Tasks
| Table | Notes |
|---|---|
| `tasks` | Kanban card. **`priority` is Account-Manager-only** (403 otherwise). |
| `task_comments`, `task_history` | Detail panel + activity log |
| `atrium_approvals` | The Send-to-Atrium bridge record |

### Leave / payroll / system
| Table | Notes |
|---|---|
| `leave_types`, `leave_balances`, `leave_requests` | Request → approval → balance update |
| `payroll_entries` | Payroll runs |
| `notifications` | In-app bell |
| `system_settings` | Editable rules (shift, grace, break, gym hours, overtime) |
| `audit_logs` | Every settings change |

### Migrations

`backend/alembic/versions/` — production truth. The app also calls `create_all` for local
convenience, which is why a missing migration passes locally and fails in prod.

| Revision | Adds |
|---|---|
| `2ea39b27b42d` | Initial schema |
| `c3a8e5f1b920` | Skills |
| `d4b1f6a2c8e1` | PR detail |
| `b7f2a1c9d4e0` | Holistic development (8 tables) |
| `f6d2b8a4c1e2` | Gym schedule + plan overrides |
| `a1c7e93f5b60` | Gym cardio (`cardio_json`, `cardio`) |

---

## API reference

All paths are prefixed `/api`. Every endpoint enforces RBAC.

### `auth`
`GET /auth/config` · `POST /auth/sso` · `POST /auth/login` · `POST /auth/change-password` ·
`GET /auth/dev-users` · `POST /auth/dev-login` · `GET /auth/me` · `POST /auth/logout` ·
`GET /auth/google/login` · `GET /auth/google/callback`

### `attendance`
`POST /attendance/scan` `/event` — kiosk punches ·
`POST /attendance/offline-sync` — bulk IndexedDB upload ·
`POST /attendance/request` · `GET /attendance/requests` · `PATCH /attendance/request/{id}` ·
`GET /attendance/summary` · `PATCH /attendance/summary/{id}` · `GET /attendance/my`

### `gym`
`POST /gym/day` — **no-lock autosave day editor** · `PATCH /gym/{log_id}/session` ·
`POST /gym/{log_id}/exercises` · `GET /gym/library` · `GET /gym/my` `/today` ·
`GET /gym/plan` · `POST /gym/plan/week` `/plan/day` · `DELETE /gym/plan/day/{on}` ·
`GET /gym/calendar` `/summary` · `PATCH|DELETE|GET /gym/{log_id}`

### `tasks`
`GET /tasks` — role-filtered board · `GET|POST /tasks[/{id}]` · `PATCH /tasks/{id}` `/status` ·
`PATCH /tasks/{id}/priority` — **Account Manager only** ·
`POST /tasks/{id}/comments` `/attachments` ·
`POST /tasks/{id}/send-to-atrium` — client-safe fields only

### `development`
`GET /development/me` `/user/{id}` ·
`POST|DELETE /development/body-metrics[/{id}]` ·
`POST|PATCH|DELETE /development/prs[/{id}]` · `PATCH /development/resume` ·
`…/achievements`, `…/goals`, `…/growth`, `…/skills` (POST/PATCH/DELETE each) ·
`GET /development/reading` · `PUT /development/reading/{id}/progress` ·
`POST|PATCH|DELETE /development/reading/canon[/{id}]`

### `people`
`GET /people` `/{id}` · `POST /people` · `PATCH /people/{id}` · `DELETE /people/{id}` ·
`GET /people/{id}/qr` `/badge` · `POST /people/{id}/qr/regenerate`

### `leave`
`GET /leave/types` `/balance` `/my` `/requests` · `POST /leave/request` ·
`PATCH /leave/request/{id}`

### `manage` (admin CRUD)
`exercises` · `clients` · `teams` · `leave-types` — GET/POST/PATCH/DELETE each

### `admin`
`GET|PATCH /admin/settings` · `GET /audit-logs` · `POST /admin/announce` ·
`GET /insights` `/dashboard`

### `payroll`
`GET /payroll` · `PUT /payroll/salary/{user_id}` · `POST /payroll/adjust/{user_id}` ·
`POST /payroll/finalize/{user_id}`

### `reports`
`GET /reports/{report}?export=csv` — attendance · gym · tasks · team · leave · overdue

### `notifications`
`GET /notifications` · `PATCH /notifications/{id}/read` · `PATCH /notifications/read-all`

### `meta`
`GET /academy/config` `/academy/courses` · `GET /teams` `/clients` · `POST /clients` · `GET /vocab`

### `stream`
`GET /stream` — Server-Sent Events push (backed by `events.py`)

### `internal` — service-to-service, **HMAC-signed, not cookie-auth**
`GET /internal/people` · `GET /internal/user-lookup` · `GET /internal/holistic-profile`

> `/internal/holistic-profile` is what feeds the Mastery Engine's **Coach** with training load,
> so a hard gym day produces a lighter study plan. Covered by `tests/test_internal.py`.

### `cron`
`POST /cron/daily` — scheduled rollups

---

## Frontend

No framework, no bundler. `pages/*.html` are ~0.7 kb shells; JS renders the markup.

| File | Owns |
|---|---|
| `app.js` (44 kb) | Shell: nav, `api()`, `toast()`, `modal()`, `skeleton()`, icons, command palette, Coach FAB |
| `gym.js` (36 kb) | Calendar, day editor, history |
| `growth.js` (23 kb) | Development hub |
| `tasks.js` (19 kb) | Kanban + drag/drop |
| `kiosk.js` (17 kb) | QR scanning + **IndexedDB offline punch queue** (syncs every 30s) |
| `manage.js`, `reading.js`, `charts.js`, `people.js`, … | One per page |
| `academy.js` | Hosts the Mastery Engine iframe |

`app.js` exports a shared toolkit — always use `api()` so FastAPI's two error shapes are
normalised (see CLAUDE.md §5).

### Worker-facing IA

Three tabs: **My Day** · **Development** · **HR + Admin**. The Development hub (`/growth`) plus
Reading (`/reading`) and the gym card make up the holistic system; the Mastery Engine's assistant
is reused as a global **Coach** FAB fed by the Mastery Engine's `lib/sentinel.js` and Sentinel's
`/internal/holistic-profile`.

---

## Cross-app integration

| Direction | Mechanism |
|---|---|
| Portal → Sentinel | `ag_sso` cookie, HMAC via `PLATFORM_SSO_SECRET` (Secret Manager: `platform-sso-key`) |
| Sentinel → Mastery Engine (UI) | iframe, `SKILL_MASTERY_URL`; needs CSP `frame-src` **and** Permissions-Policy mic delegation |
| Mastery Engine → Sentinel (data) | `GET /api/internal/*`, HMAC-signed |
| Sentinel → Atrium | `POST /tasks/{id}/send-to-atrium` — client-safe fields only |

All four are configured by `deploy/deploy.ps1`. That is why hand-rolled deploys break them.

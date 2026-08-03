# Sentinel — Architecture & API reference

Deep reference. Read [../AGENTS.md](../AGENTS.md) first for the operating rules and gotchas.

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

## Database schema — 38 tables

### Identity & org
| Table | Notes |
|---|---|
| `users` | **Source of truth for who may sign in.** SSO/Google authenticate; this table authorizes. |
| `teams` | Org units |
| `shift_templates` | Reusable shift schedules, assignable to a team or an employee |
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
| `physical_goals` | Physical targets (drives the Physical ring — mean progress) |
| `development_areas` | The four growth dimensions' area records |
| `growth_items`, `skills` | Growth track |
| `reading_items`, `reading_progress` | Reading canon + per-user progress |
| `mentor_transcripts` | Imported Watcher transcripts — the Mentor Library (feeds `/internal/mentor-search`) |

### Tasks
| Table | Notes |
|---|---|
| `tasks` | Kanban card. **`priority` is Account-Manager-only** (403 otherwise). |
| `task_comments`, `task_history` | Detail panel + activity log |
| `service_templates` | Editable service recipes — default maintasks/priority/labels for new cards |
| `task_vocab` | Board vocabulary — statuses, labels, priorities (`kind` partitions), super-admin-editable |
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

**The revision list lives in `backend/alembic/versions/` itself** — read the files (each names
what it adds), don't trust any hardcoded list here; every copy of one went stale. Two rules from
AGENTS.md §4–5: migrations for tables `create_all` already built in prod must be
existence-guarded (`a9c4e7f2d5b8_service_templates_task_vocab.py` is the pattern), and the full
chain does not replay onto a fresh SQLite DB — validate new revisions in isolation.

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
`GET /internal/people` · `GET /internal/user-lookup` · `GET /internal/holistic-profile` ·
`GET /internal/mentor-search`

> `/internal/holistic-profile` is what feeds the Mastery Engine's **Coach** with training load,
> so a hard gym day produces a lighter study plan. Covered by `tests/test_internal.py`.
> `/internal/mentor-search` ([internal.py:128](../backend/app/routers/internal.py#L128), signing
> purpose `mentor-search`) retrieves the Mentor Library passages that bear on a question — how
> the Coach answers "what would Nick say?" (AGENTS.md §5). Covered by `tests/test_mentor_search.py`.

### `cron`
`POST /cron/daily` — scheduled rollups

---

## Frontend

No framework, no bundler. `pages/*.html` are ~0.7 kb shells; JS renders the markup.

| File | Owns |
|---|---|
| `app.js` (44 kb) | Shell: nav, `api()`, `toast()`, `modal()`, `skeleton()`, icons, command palette, Coach FAB |
| `gym.js` (36 kb) | Calendar, day editor, history |
| `growth.js` (24 kb) | `window.GrowthPanel` — a mountable component (compass + ledger), hosted by the Overview and by `/growth`'s read-only manager view |
| `dashboard.js` (10 kb) | **The Overview**: day strip, then GrowthPanel's rings, TaskBoard, GrowthPanel's ledger, and the admin block |
| `taskboard.js` (19 kb) | Kanban + drag/drop — a mountable component embedded in the Overview (no /tasks page; the URL **307-redirects** to /dashboard, query string intact) |
| `kiosk.js` (17 kb) | QR scanning + **IndexedDB offline punch queue** (syncs every 30s) |
| `manage.js`, `reading.js`, `charts.js`, `people.js`, … | One per page |
| `academy.js` | Hosts the Mastery Engine iframe |

`app.js` exports a shared toolkit — always use `api()` so FastAPI's two error shapes are
normalised (see AGENTS.md §5).

### Navigation (the `NAV` array, `app.js:78`)

Two sidebar sections. **Workspace**: **Overview** (`/dashboard` — the task board AND the growth
compass/ledger, merged 2026-08-03; the URL kept its name because notifications, the palette and
bookmarks all point at it) · a **Growth** group of exactly the four engine tabs, which the
Overview's four rings link into one-to-one — Professional (`/academy`, the engine's career
programs), Philosophical + Spiritual (each a Mastery Engine pinned to its reading program),
Physical (`/gym`); `/growth` is no longer in the nav — it serves only a manager's read-only view
of one person (`?user=<id>`) · a **Time & Leave** group —
Time (`/attendance`), Leave, Approvals (team_lead+, one inbox for attendance + leave),
Clock in (`/scanner`, super_admin only) · Our North Star (`/north-star`). **Admin**: People,
Reports (team_lead+), Payroll, Manage (super_admin), Settings (admin+). There is no Reading tab —
`/reading` stays reachable from the Overview's links.

The Mastery Engine's assistant is reused as a global **Coach** FAB fed by the Mastery Engine's
`lib/sentinel.js` and Sentinel's `/internal/holistic-profile` + `/internal/mentor-search`.

---

## Cross-app integration

| Direction | Mechanism |
|---|---|
| Portal → Sentinel | `ag_sso` cookie, HMAC via `PLATFORM_SSO_SECRET` (Secret Manager: `platform-sso-key`) |
| Sentinel → Mastery Engine (UI) | iframe, `SKILL_MASTERY_URL`; needs CSP `frame-src` **and** Permissions-Policy mic delegation |
| Mastery Engine → Sentinel (data) | `GET /api/internal/*`, HMAC-signed |
| Sentinel → Atrium | `POST /tasks/{id}/send-to-atrium` — client-safe fields only |

All four are configured by `deploy/deploy.ps1`. That is why hand-rolled deploys break them.

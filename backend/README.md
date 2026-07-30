# backend/ — the Sentinel API

FastAPI + SQLAlchemy 2.0 app that serves both the JSON API (`/api/*`) and the frontend shells.
SQLite locally (zero setup), Cloud SQL Postgres in prod, Alembic migrations run at boot.
Operating rules, auth model, and gotchas live in [../AGENTS.md](../AGENTS.md) — this file is the
unit map + cookbook.

## File map

| Entry | What it is |
|---|---|
| `app/main.py` | App assembly: middleware stack, startup safeguards (bootstrap admin + platform owners), **router tuple `main.py:322`**, `_PAGES` dict `:381`, `/login` SSO short-circuit `:358`, `/tasks` 307 redirect `:413` |
| `app/config.py` | `Settings` (pydantic-settings) — every env var the app reads |
| `app/database.py` | Engine / `SessionLocal` / `Base` / `get_db` |
| `app/constants.py` | Roles, statuses, `ROLE_RANK` |
| `app/security.py` | `get_current_user`, `require_min_role`, `require_roles` factories; `user_from_sso` `:50` |
| `app/sso.py` | Portal `ag_sso` cookie parsing (`email_from_cookie`, `COOKIE_NAME`) |
| `app/middleware.py` | `_csp()` `:37`, `_permissions_policy()` `:61`, `SecurityHeadersMiddleware` `:68` (also sets `Cache-Control: no-cache` on non-API responses `:94`), `RateLimitMiddleware` `:111` (hand-rolled on purpose), `CSRFMiddleware` `:167` |
| `app/serializers.py` | **The field-exposure boundary.** `user_public`/`user_full`, `task_card`/`task_detail`/`atrium_payload`, `summary_dict`/`attendance_request_dict`, `gym_log_dict`, `leave_*_dict`, `*_goal_dict`, `mentor_transcript_dict`, `notification_dict`, … |
| `app/events.py` | In-process SSE event broker (consumed by `routers/stream.py`) |
| `app/observability.py` | JSON logs in prod, `ExceptionLoggingMiddleware`, optional Sentry |
| `app/models/` | 38 tables: `user.py` (shift_templates, teams, users, qr_tokens) · `attendance.py` (3) · `gym.py` (5) · `task.py` (tasks, task_comments, task_history, service_templates, task_vocab, atrium_approvals) · `development.py` (12 incl. physical_goals, development_areas, mentor_transcripts) · `leave.py` (3) · `client.py`, `system.py` (2), `notification.py`, `payroll.py` |
| `app/schemas/__init__.py` | All Pydantic request bodies (single file) |
| `app/routers/` | 16 modules — prefixes: `/api/auth`, `/api/attendance`, `/api/gym`, `/api/tasks`, `/api/people`, `/api/leave`, `/api/development`, `/api/payroll`, `/api/reports`, `/api/notifications`, `/api/cron`, `/api/internal`, `/api/manage` (whole router super_admin-gated), and bare `/api` for `admin`, `meta`, `stream` |
| `app/services/attendance.py` | The attendance engine (punch state machine, late/grace in Manila) |
| `app/services/atrium_bridge.py` · `atrium_watcher.py` | HMAC signer + Watcher-archive client (Mentor Library import; fail-soft by design) |
| `app/services/atrium_tasks.py` | Whole Atrium task-bridge translation layer: `FIELD_MAP`, `to_atrium_fields`, `as_board_card`, `as_task_detail`, `split_id`, `GONE`/`GONE_COMMENT` |
| `app/services/task_perms.py` | The whole task RBAC table. `can_view` (employee/intern = **assigned to them**, nothing else) · `can_view_atrium` / `can_edit_atrium` (team lead+) / `can_manage_atrium` (AM+) |
| `app/services/task_config.py` · `task_templates.py` · `maintasks.py` | Board vocab (task_vocab), service templates, two-level work breakdown |
| `app/services/mentor_search.py` | Per-user BM25-ish retrieval over `mentor_transcripts` (`resolve_mentor`, `DEFAULT_LIMIT`; no table of its own — deliberate) |
| `app/services/development.py` | Holistic hub incl. `holistic_digest` (feeds the Coach) |
| `app/services/` (rest) | `gym.py`, `leave.py`, `payroll.py`, `notifications.py`, `settings.py`, `audit.py`, `daily.py` — one domain each |
| `app/utils/` | `time.py` (**`utcnow()` — the only clock**), `qr.py`, `csv_export.py`, `passwords.py` |
| `alembic/versions/` | 17 revisions; head `a9c4e7f2d5b8_service_templates_task_vocab` |
| `entrypoint.sh` → `migrate.py` | Boot: `alembic upgrade head` (or `stamp head` to adopt a create_all schema), then uvicorn |
| `seed.py` · `make_badges.py` | Demo data · printable QR badges |
| `tests/` (23 files) | pytest suite — `conftest.py` builds a throwaway SQLite per test |
| `sentinel.db` | Local dev database (throwaway) |

## Data contract (router → serializer → page consumer)

| Domain | Router | `serializers.py` | Consumer (`frontend/static/js/`) |
|---|---|---|---|
| Tasks | `routers/tasks.py` | `task_card`, `task_detail`, `comment_dict`, `history_dict`, `atrium_payload` | `taskboard.js` (embedded in dashboard) |
| Attendance | `routers/attendance.py` | `summary_dict`, `attendance_request_dict` | `attendance.js`, `dashboard.js`, `approvals.js`, `kiosk.js` |
| Gym | `routers/gym.py` | `gym_log_dict`, `body_metric_dict`, `personal_record_dict` | `gym.js` |
| Leave | `routers/leave.py` | `leave_type_dict`, `leave_balance_dict`, `leave_request_dict` | `leave.js`, `approvals.js` |
| Development | `routers/development.py` | `development_profile_dict`, `goal_dict`, `physical_goal_dict`, `development_area_dict`, `growth_item_dict`, `skill_dict`, `reading_item_dict`, `mentor_transcript_dict` | `growth.js`, `reading.js` |

## Cookbook

1. **Add an endpoint** — `routers/<domain>.py` (guard per AGENTS.md §3) + logic in
   `services/<domain>.py` + body model in `schemas/__init__.py` + response fn in
   `serializers.py`. New router → add to the tuple at `main.py:322`.
   Verify: `python -c "import app.main"` then `pytest`. Deploy: `..\deploy\deploy.ps1` (asia-southeast1).
2. **Add a DB column (with migration)** — edit `models/<domain>.py`; `alembic revision -m "..."`,
   hand-write the upgrade copying a neighbour in `alembic/versions/`. If prod's `create_all`
   already built the table, existence-guard it (copy `a9c4e7f2d5b8_*.py`). Validate in isolation:
   `alembic stamp <parent>` on a seeded DB, then `alembic upgrade head` — the full chain will NOT
   replay onto a fresh SQLite DB (AGENTS.md §5). Verify: `pytest`. Deploy: `..\deploy\deploy.ps1`.
3. **Change RBAC on an endpoint** — swap the `Depends(require_min_role(...))` /
   `require_roles(...)` guard (factories in `security.py`); update `tests/test_security_rbac.py`
   to pin it. Verify: `python -m pytest tests/test_security_rbac.py -v`. Deploy: `..\deploy\deploy.ps1`.
4. **Add an internal HMAC endpoint** — copy `/mentor-search` in `routers/internal.py:128`:
   `_verify(x_academy_ts, x_academy_sig, "<purpose>")`; the purpose string must match the caller's
   signer exactly (Mastery Engine `lib/sentinel.js` / Atrium bridge). Add a case to
   `tests/test_internal.py`. Deploy BOTH sides; the caller 401s until purposes agree.
5. **Expose a new field to the frontend** — `serializers.py` only; check `atrium_payload` before
   adding anything client-visible (internal fields must never cross to Atrium).
6. **Add a vocab/enum the frontend needs** — `routers/meta.py` (`GET /api/vocab`) or, for the
   board, a `task_vocab` row via `services/task_config.py`.
7. **RETIRE a board status** — a `task_config.RETIRED_STATUSES` entry (`{"Old": SURVIVING}`), not
   just a `constants.TASK_STATUSES` edit. The seeded DB row outranks the code defaults, and
   deleting it while a task still holds the name drops that card off the board. See AGENTS.md §5.

Verify commands (from `backend/`): `.\.venv\Scripts\Activate.ps1; pytest` — or, when
`backend/.venv` doesn't exist on this machine, `..\..\.venv\Scripts\python.exe -m pytest`
(the shared workspace venv).

## Gotchas / DO NOT TOUCH

- **`serializers.py` is a security boundary** — every response goes through it; never return an
  ORM object.
- **The no-cache middleware is pinned by `tests/test_security_headers.py`** — `Cache-Control:
  no-cache` on non-API responses fixed the 2026-07-27 stale-asset incident; don't "optimize" it.
- **Alembic history is append-only** — never edit a shipped revision; `d8f4b2c6a9e3` failing in
  batch mode on a fresh SQLite DB is a known, accepted limitation (fine on Postgres).
- **No `requests`** — it is not in the production image (imported it once → boot crash). Use
  stdlib `urllib` like `routers/auth.py` does.
- `utcnow()` from `utils/time.py`, never `datetime.now()`.
- The rate limiter in `middleware.py` is hand-rolled deliberately (AGENTS.md §9).

## Status (volatile)

- Live: `https://sentinel-585951669065.asia-southeast1.run.app` — serving revision
  **`sentinel-00112-mpl`** (verified 2026-07-29).
- Test suite: **213 passed** (2026-07-29, shared workspace venv).
- Migrations: 17 revisions, head `a9c4e7f2d5b8` (2026-07-29).
- Prod DB: Cloud SQL `agora-data-driven:asia-southeast1:sentinel-db` (Postgres 16).

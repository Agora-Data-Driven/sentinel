# CLAUDE.md — Sentinel

> **Read this before touching any file.** It is the operating manual for this repo.
> Product/feature overview: [README.md](README.md). Deploy detail: [deploy/DEPLOY.md](deploy/DEPLOY.md).
> Deep map: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

---

## 0. What this is, in 30 seconds

Agora's **internal operations command center** — the staff-facing counterpart to the
client-facing Atrium portal. Attendance (QR kiosk), gym tracking, tasks, people directory,
leave, payroll, reporting, and a "holistic development" hub (learning + reading + gym).

| | |
|---|---|
| **Stack** | Python 3.11, **FastAPI**, SQLAlchemy 2.0, Alembic, **vanilla JS frontend** (no build step) |
| **DB** | Cloud SQL **Postgres** in prod · SQLite locally (zero setup) |
| **Runs on** | Cloud Run service `sentinel`, project `agora-data-driven`, region **`asia-southeast1`** |
| **Live URL** | `https://sentinel-585951669065.asia-southeast1.run.app` |
| **Timezone** | Stored **UTC**, displayed/ruled in **Asia/Manila (UTC+8)** |
| **Embeds** | The Mastery Engine, via iframe — Academy tab + global Coach FAB |

> ⚠️ **Region is `asia-southeast1`, not `us-central1`.** Every other Agora service is
> `us-central1`. Getting this wrong makes `gcloud` commands silently target nothing.

**Hard product rule:** clients never see internal fields (assignee, team, priority, internal
notes, attendance, gym). The Account Manager bridges Sentinel → Atrium via **Send to Atrium**,
which shares only client-safe fields.

---

## 1. Run it / deploy it

```bash
# Local — SQLite, no database to install
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1          # PowerShell
pip install -r requirements-dev.txt   # includes runtime deps + pytest
python seed.py                        # builds all tables + realistic sample data
uvicorn app.main:app --reload         # http://localhost:8000
```

Log in from the **Dev login** dropdown, no password. Seeded users:

| Login | Role | Sees |
|---|---|---|
| `melo@agora.ph` | Super Admin | Everything + Scanner |
| `maria@agora.ph` | Admin | Records, reports, approvals, settings |
| `leo@agora.ph` | Account Manager | Tasks + **priority control** |
| `bong@agora.ph` | Team Lead | Team tasks, approvals |
| `ana@agora.ph` | Employee | Own data only |

```powershell
# Deploy to production — from the sentinel/ root, ALWAYS via the script
.\deploy\deploy.ps1
```

> 🔴 **Never deploy Sentinel with a raw `gcloud run deploy`.**
> `--set-env-vars` / `--set-secrets` replace their whole category. `deploy.ps1` bakes in
> `PLATFORM_SSO_SECRET`, `PORTAL_LOGIN_URL`, `SKILL_MASTERY_URL`, and `GOOGLE_REDIRECT_URI`.
> A hand-rolled deploy silently wipes them and breaks portal sign-in **and** the Academy
> microphone. This has already happened once.

Interactive API docs while running: **http://localhost:8000/docs**.

---

## 2. Map — where everything lives

```
backend/app/
  main.py          FastAPI app, router registration (:205), page routes, static mount
  config.py        env-driven settings (pydantic-settings)
  database.py      engine / session / Base
  constants.py     roles, statuses, ROLE_RANK
  security.py      JWT cookie auth + RBAC dependency guards      ← auth lives HERE
  sso.py           portal ag_sso cookie verification
  middleware.py    CSP, Permissions-Policy, security headers      ← see §5 gotchas
  serializers.py   model → dict. Controls what leaves the API.
  events.py        SSE event bus (see routers/stream.py)
  observability.py request logging / metrics
  models/          SQLAlchemy tables, grouped by domain
  schemas/         Pydantic request bodies (single __init__.py)
  routers/         one module per domain — see table below
  services/        business logic, called by routers
  utils/           time (Manila), qr, csv_export, passwords
  alembic/         migrations
  seed.py          populates every table with sample data
frontend/
  pages/*.html     thin shells — real markup is rendered by JS
  static/js/       app.js (shell + api() + toast) + one file per page
  static/css/      styles.css — the whole design system
  sw.js            service worker — BUMP `CACHE` ON EVERY ASSET CHANGE (§5)
deploy/            deploy.ps1, seed-job.ps1, DEPLOY.md
```

### Routers (`backend/app/routers/`)

| Module | Owns |
|---|---|
| `auth.py` | Login (dev/password/Google/SSO), session, `/api/auth/me` |
| `attendance.py` | Kiosk scan, punches, offline sync, approvals |
| `gym.py` | Workouts, exercise library, schedule/overrides, cardio |
| `tasks.py` | Kanban board, priority (AM-only), Send to Atrium |
| `people.py` | Directory, profiles, QR badges |
| `leave.py` | Requests, approvals, balances |
| `development.py` | Holistic development hub — learning, reading, growth |
| `payroll.py` | Payroll runs |
| `reports.py` | 6 reports + CSV export |
| `admin.py` | System settings, announcements, audit log |
| `manage.py` | Admin management screens |
| `notifications.py` | Bell, unread counts |
| `meta.py` | Enums/constants for the frontend |
| `cron.py` | Scheduled job endpoints |
| `stream.py` | SSE push to the browser |
| `internal.py` | **HMAC-signed** service-to-service (Mastery Engine ↔ Sentinel) |

Adding a router? Register it in the tuple at [main.py:205](backend/app/main.py#L205).

---

## 3. Auth & RBAC — the core pattern

Roles, ranked (`ROLE_RANK` in `constants.py`):

```
super_admin › admin › account_manager › team_lead › employee / intern
```

**RBAC is enforced at the dependency layer**, so every protected endpoint returns a real
401/403 — never just hidden UI. Two factories in [security.py](backend/app/security.py):

```python
from ..security import require_min_role, require_roles, get_current_user

# Whole router
router = APIRouter(prefix="/api/thing", dependencies=[Depends(require_min_role(ROLE_ADMIN))])

# Single endpoint, when you also need the user object
@router.patch("/{id}/priority")
def set_priority(id: int, user: User = Depends(require_roles(ROLE_ACCOUNT_MANAGER)),
                 db: Session = Depends(get_db)):
    ...
```

**Never gate access in the frontend only.** The UI hides things for tidiness; the server is
what enforces it.

### Two ways in

1. **Sentinel JWT** — httpOnly cookie, or `Authorization: Bearer` for curl.
2. **Portal `ag_sso` cookie** — HMAC-signed with `PLATFORM_SSO_SECRET`, shared with the portal
   and the Mastery Engine.

> **SSO never creates a user and never grants a role.** An email with no *active* row in `users`
> gets nothing. Sentinel's `users` table is the **source of truth** for who may sign in
> ([security.py:50](backend/app/security.py#L50)). Google sign-in follows the same contract.

`/login` short-circuits: arriving with a valid `ag_sso` cookie *and* an active user lands you
straight on the dashboard, minting a normal session on the way ([main.py:241](backend/app/main.py#L241)).

---

## 4. Recipes

### Add an endpoint

1. Route in `routers/<domain>.py`, business logic in `services/<domain>.py`.
2. Request body → a Pydantic model in `schemas/__init__.py`.
3. Response → a function in `serializers.py`. **This is the field-exposure boundary** — the
   client-safe/internal split is enforced here.
4. Pick a guard (§3).

```python
@router.post("/thing")
def create_thing(body: ThingIn,
                 user: User = Depends(require_min_role(ROLE_TEAM_LEAD)),
                 db: Session = Depends(get_db)):
    obj = services.thing.create(db, user, body)
    return serialize_thing(obj)
```

### Add a database column

The app calls `create_all` for MVP convenience, **but production runs Alembic.** A new column
without a migration works locally and breaks prod.

```bash
cd backend
alembic revision -m "add cardio to gym schedule"   # then hand-write the upgrade
alembic upgrade head
```

Existing migrations are in `backend/alembic/versions/` (e.g. `a1c7e93f5b60_gym_cardio.py`) —
copy their style.

### Add a frontend page

1. `frontend/pages/<name>.html` — a thin shell (~0.7 kb; the JS renders everything).
2. `frontend/static/js/<name>.js` — the page controller.
3. Register the page route in `main.py` beside the others.
4. Add nav in `app.js`.
5. **Bump `CACHE` in [frontend/sw.js](frontend/sw.js#L6)** — see §5.

`app.js` exports the shared toolkit: `api`, `toast`, `skeleton`, `modal`, `esc`, `qs`, `qsa`,
`ICON`, `avatar`. Use `api()` for every request — it already normalises FastAPI errors.

---

## 5. Gotchas — read before debugging

### 🔴 Deploying with raw `gcloud run deploy` wipes the SSO env

Covered in §1. **Always `.\deploy\deploy.ps1`.** Symptom: portal → Sentinel sign-in breaks, and
the Academy mic dies, immediately after a deploy.

### 🔴 Frontend change deployed but the browser shows the old version

The service worker caches static assets. **Bump `CACHE` in [sw.js](frontend/sw.js#L6)**
(`sentinel-v22` → `v23`) whenever you change CSS/JS. The `activate` handler purges every cache
whose key isn't the current one.

### 🔴 Login page flashes for ~2s before redirecting

Caused by the service worker serving a **cached** `/login` over the server's 302. Fixed by not
intercepting navigations ([sw.js:41](frontend/sw.js#L41)). Don't reintroduce navigation caching —
the `/kiosk` exception is deliberate (it must boot offline).

### 🔴 Microphone dead in the embedded Academy iframe

A cross-origin iframe gets the mic only if **both** hold:
1. the `<iframe>` carries `allow="microphone"`, **and**
2. this top-level document *delegates* the feature to that exact origin.

`microphone=()` (empty allowlist) blocks it for everyone, silently, with no prompt.
`_permissions_policy()` ([middleware.py:61](backend/app/middleware.py#L61)) derives the origin
from `SKILL_MASTERY_URL`. Permissions-Policy origins must be **exact** — no wildcards.

### 🔴 Toast shows `[object Object]`

FastAPI returns `detail` as a *string* for `HTTPException` but a *list of `{loc, msg}`* for 422
validation errors. `api()` in [app.js:110](frontend/static/js/app.js#L110) flattens both. Use
`api()` rather than bare `fetch`.

### 🔴 An `onclick` handler receives a click Event as its first argument

`#add.onclick = addForm` passes the **Event** as `addForm`'s first parameter, so an "Add" button
opened in edit mode and PATCHed `/api/people/undefined`. Always wrap:

```js
addBtn.onclick = () => addForm();     // ✅
addBtn.onclick = addForm;             // ❌
```

### 🟡 CSP blocks a new asset

`_csp()` ([middleware.py:37](backend/app/middleware.py#L37)) is tight on purpose: **no inline
`<script>` anywhere**, so `script-src` stays `'self'`. Put JS in a file under `static/js/`.
`frame-src` allows `*.agoradatadriven.com` (the Mastery Engine embed); `frame-ancestors` is
driven by `CSP_FRAME_ANCESTORS`.

### 🟡 Timezone drift

Store UTC, always. Use `app/utils/time.py` (`utcnow()`) — never `datetime.now()`. Business rules
(late/grace, "today") apply in Asia/Manila.

### 🟡 A `/go` from another machine can clobber this repo

Sentinel is swept by the polyrepo `/go`. A stale tree elsewhere can overwrite main and deploy.
Check `git log --oneline -5` and the serving revision before assuming your change is live.

---

## 6. Verify your change

**This repo has a real test suite. Use it.**

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
pytest                                    # runs backend/tests/
python -m pytest tests/test_security_rbac.py -v   # RBAC specifically
python app\_sso_test.py                   # standalone SSO test
python -c "import app.main"               # import check — catches syntax/wiring errors
```

Existing coverage: attendance engine, CSRF, events, gym plan, internal HMAC endpoints, leave,
observability, security headers, RBAC.

**If you touch auth, RBAC, or headers, run the suite before deploying.** Those tests exist
because those areas broke in production before.

After deploying:
```powershell
gcloud run services describe sentinel --project agora-data-driven --region asia-southeast1 `
  --format="value(status.url,status.traffic[0].revisionName)"
curl.exe -s https://sentinel-585951669065.asia-southeast1.run.app/api/health
```

---

## 7. Never do this

| ❌ | Why |
|---|---|
| `gcloud run deploy sentinel …` by hand | Wipes `PLATFORM_SSO_SECRET` + portal/mastery URLs. Use `deploy/deploy.ps1`. |
| Forget to bump `CACHE` in `sw.js` | Users keep getting stale CSS/JS after a deploy. |
| Use `us-central1` | Sentinel is **`asia-southeast1`**. |
| Enforce a permission only in the UI | RBAC belongs in a dependency guard. |
| Add a column without an Alembic migration | Works locally (`create_all`), breaks prod. |
| `datetime.now()` | Use `utils/time.utcnow()`. Everything is stored UTC. |
| Inline `<script>` in a page | CSP forbids it — `script-src 'self'`. |
| `element.onclick = handler` | Passes the Event as arg 1. Use `() => handler()`. |
| Expose internal fields to Atrium | Client-safe split is enforced in `serializers.py`. |
| Create users via SSO | SSO authenticates; the `users` table authorizes. |

---

## 8. Conventions

- **Python**: type hints, `from __future__ import annotations`, 4-space indent. Routers stay
  thin — logic goes in `services/`.
- **Frontend**: vanilla JS, no framework, no bundler, no build step. One file per page.
  **Do not introduce React or a bundler.**
- Every response passes through `serializers.py`. Never return an ORM object directly.
- Docstrings explain *why* a rule exists. The codebase is well-commented — match that density,
  and don't delete a comment that documents a workaround.
- Secrets come from Secret Manager. Never commit real values; `.env.example` is the template.

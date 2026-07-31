# AGENTS.md — Sentinel

> **Read this before touching any file.** It is the operating manual for this repo.
> Product/feature overview: [README.md](README.md). Deploy detail: [deploy/DEPLOY.md](deploy/DEPLOY.md).
> Deep map: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Unit file maps + cookbooks:
> [backend/README.md](backend/README.md) · [frontend/README.md](frontend/README.md) ·
> [deploy/README.md](deploy/README.md).

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
| **Embeds** | The Mastery Engine, via iframe — Professional (formerly Academy) tab, Philosophical + Spiritual tabs (each pinned to one engine program via `?program=`), and the global Coach FAB |

> ⚠️ **Region is `asia-southeast1`, not `us-central1`.** Every other Agora service is
> `us-central1`. Getting this wrong makes `gcloud` commands silently target nothing.

**Hard product rule:** clients never see internal fields (assignee, team, priority, internal
notes, attendance, gym). The Account Manager bridges Sentinel → Atrium via **Send to Atrium**,
which shares only client-safe fields. The reverse — a card Atrium owns, shown on this board — is
**fully editable here**, writing straight back to Atrium (§2, "The task board holds TWO kinds of
card"). Nothing internal crosses in that direction either: Atrium's own internal fields stay in
Atrium's team surfaces.

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
  main.py          FastAPI app, router registration (:322), page routes, static mount
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
| `gym.py` | Workouts, exercise library, schedule/overrides, cardio, **saved routines** |
| `tasks.py` | Kanban board, priority (AM-only), Send to Atrium, **editing Atrium's own cards** |
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

Adding a router? Register it in the tuple at [main.py:322](backend/app/main.py#L322).

### The task board holds TWO kinds of card

| | Sentinel row | Atrium-owned card |
|---|---|---|
| id | an integer PK | the string `atrium:<client_key>:<task_id>` |
| stored in | Postgres `tasks` | that client's Atrium workspace JSON — **Atrium is the source of truth** |
| reaches the board via | `task_card` | `atrium_tasks.fetch_tasks()` → `as_board_card` (fail-soft: an Atrium outage just hides them) |
| who sees it | `task_perms.can_view` (employee/intern: **only what's assigned to them**) | `task_perms.can_view_atrium` — **team lead and up** |

**Both are fully editable here** (since 2026-07-29 — before that, opening an Atrium card said "open
it in Atrium to view or edit", which is a dead end, not an answer). Every route in `tasks.py` looks
for the prefix first (`atrium_tasks.split_id`) and, when it matches, writes across the bridge
instead of to Postgres: `GET /{id}`, `PATCH /{id}`, `DELETE /{id}`, `PATCH /{id}/status`,
`PATCH /{id}/priority`, `POST /{id}/comments`, `POST /{id}/comments/{cid}/resolve`.

- **`services/atrium_tasks.py` is the whole translation layer.** `FIELD_MAP` + `to_atrium_fields`
  turn Sentinel's field names into Atrium's on the way out (`client_facing_notes` → `client_note`,
  `atrium_visible` → `client_facing`, main-task `title` → `text`, `date` → ISO string);
  `as_task_detail` maps the answer back into the shape the drawer already renders. Anything the
  other side has no equivalent for is **absent, never faked** — an Atrium card has no Sentinel
  assignee, team or description, and its owners are roster **emails**, not user ids.
- **Signing purposes** (HMAC, shared `platform-sso-key`, same scheme as everything else):
  `tasks`, `task-detail`, `task-update`, `task-delete`, `task-move`, `task-add`, `task-comment`.
- **Permissions** live in `task_perms.can_view_atrium` / `can_edit_atrium` / `can_manage_atrium`:
  a client card is a **manager surface** (team lead and up) because it belongs to no Sentinel user;
  whoever sees it may edit its content; priority, client visibility and deletion stay AM+ — the same
  three decisions Sentinel reserves for managers. Every Atrium branch in `tasks.py` calls
  `_require_atrium` (or the stricter `can_manage_atrium`) — scoping only the board LIST would be
  theatre while the id still opened and edited the card.
- 🔴 **Only Atrium's own 404 may surface as "that card is gone."** The board LIST is fail-soft, but
  every explicit act (open / edit / delete / comment) reports its failure — the router keys its 404
  off `atrium_tasks.GONE`/`GONE_COMMENT` and answers **502** for anything else, so a timeout is
  never shown as a deletion. (The Watcher bridge's empty state hid two real bugs exactly this way;
  see §5.)

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
straight on the dashboard, minting a normal session on the way ([main.py:358](backend/app/main.py#L358)).

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

Existing migrations are in `backend/alembic/versions/` — **18 revisions** as of 2026-07-31
(e.g. `a1c7e93f5b60_gym_cardio.py`) — copy their style. If prod's `create_all` safety net
already built your table, the migration must be **existence-guarded** — copy
`a9c4e7f2d5b8_service_templates_task_vocab.py` (added 2026-07-29 for exactly that case).
Validate a new revision in isolation, not by replaying the whole chain (§5).

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

Two layers can serve stale JS/CSS; both are handled, don't undo either:
1. **Service-worker cache** — **bump `CACHE` in [sw.js](frontend/sw.js#L6)** (`sentinel-vN` →
   `vN+1`) whenever you change CSS/JS. The `activate` handler purges every cache whose key isn't
   the current one.
2. **Browser HTTP cache (heuristic freshness)** — static responses carry `Last-Modified`, so
   without an explicit `Cache-Control` browsers may treat a pre-deploy copy as "fresh" and never
   revalidate; the SW's network-first `fetch()` is satisfied by that same HTTP cache, so it can't
   help. Live incident 2026-07-27: day-old `dashboard.js` ran against the new `/api/dashboard`
   and rendered "undefined" KPIs. Fixed by `Cache-Control: no-cache` on all non-API responses
   ([middleware.py](backend/app/middleware.py), pinned by `test_security_headers.py`) plus
   `cache: "no-cache"` on the SW's fetches. ETag revalidation keeps it a cheap 304.

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
validation errors. `api()` in [app.js:130](frontend/static/js/app.js#L130) flattens both. Use
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

### 🟡 The full Alembic chain cannot replay onto a FRESH SQLite DB

`alembic upgrade head` on an empty SQLite database dies at `d8f4b2c6a9e3_task_created_by` in
batch mode ("Constraint must have a name"); the same chain runs fine on prod Postgres. So never
validate a new migration by replaying history from scratch — test the single revision in
isolation: `alembic stamp <parent>` on an existing (seeded) DB, then `alembic upgrade head`.
That is how `a9c4e7f2d5b8` was verified.

### 🔴 Removing a board column is TWO moves — deleting the status name alone hides work

Statuses are DB-backed (`task_vocab`, seeded on first boot from `constants.TASK_STATUSES`), and
`renderBoard` builds the columns from `/api/vocab` and groups tasks by that exact list. So:

1. Dropping the name from `constants.py` changes **nothing** on any existing deploy — the seeded
   row still wins, and the column keeps rendering.
2. Deleting the row while a task still holds that status makes the task **vanish** — it groups
   under a key no column exists for. No error, no empty state; the card is just gone.

`task_config.RETIRED_STATUSES` + `retire_statuses(db)` do both halves in the right order (move the
tasks, then delete the row) and run from `main._seed_config` on every boot — which is how the
change reaches **prod, where deploys don't run Alembic**. Retire a status by adding a
`{"Old Name": SURVIVING_STATUS}` entry there, never by editing the list alone. The manual path
(Manage → Task Fields → Statuses) is guarded for the same reason: a delete 409s while in use.

**For Review + Waiting for Client were removed this way on 2026-07-30** (both folded into Blocked),
a day after Atrium retired the matching stages — so `atrium_tasks.STAGE_BY_STATUS` is 5 entries now.
Leaving them mapped after Atrium dropped them was a quiet lie: `for_review` still POSTed 200 while
Atrium's `_STAGE_ALIASES` filed the card under Blocked, so the two boards disagreed about where the
client's card actually was.

### 🟡 A board scoped by role still showed other people's work

An intern's Task Board showed seven cards, none of them theirs (2026-07-30). Two independent
reasons, and the second is the one to remember:

1. The creator tag (`created_by_id`) granted visibility on its own, so a card they raised and a
   manager then delegated stayed on their board. `can_view` now means **assigned** for
   employee/intern (the creator branch survives for team leads only, and `can_delete`'s creator
   branch is gated on `can_view`).
2. **`list_tasks` appended every Atrium card to every board**, bypassing `can_view` entirely —
   those cards have no assignee, team or creator to test, so no ownership rule *could* apply to
   them. They are scoped by role instead (`can_view_atrium`, team lead and up).

The lesson generalises: a bridged/aggregated row that joins a list *after* the permission filter is
invisible to that filter. Scope it where it is appended, and give it its own predicate.

### 🔴 "Import from Atrium" says there are no creators when there obviously are

The Growth hub's Mentor Library imports transcripts from Atrium's Watcher archive over the HMAC
bridge (`services/atrium_bridge.py` → `services/atrium_watcher.py`). **Every leg of that bridge is
fail-SOFT by design** — an unset secret, a 404, a timeout and a malformed body all degrade to `[]`.
That is correct (an Atrium outage must not break the page) but it means *a broken bridge and an
empty archive look identical in the UI*. Two real failures hid behind that one empty state:

1. **Atrium never exposed `/api/internal/watcher/*` at all** — the Sentinel half shipped complete
   and tested against endpoints that did not exist. Every call 404'd into the empty list.
2. **`atrium_watcher_client_key` defaulted to `"agora"`**, a workspace that has never existed, so
   even a working bridge would have scoped every query to nothing.

It now reads **every** workspace (the key is an optional filter, `""` = all — don't re-pin it to a
guessed key), and channel ids arrive namespaced `"<client_key>:<channel_id>"`. **When this picker
is empty, curl the bridge before believing the UI** — the fail-soft path never surfaces the reason:

```powershell
# See the real status code instead of the swallowed one.
# 🔴 Use a UTC epoch. PowerShell 5.1's `Get-Date -UFormat %s` returns a LOCAL-time epoch, which is
# 8h off in Manila -- past the gate's 300s skew window, so you get a 401 and misread it as a bad
# secret. (This cost a debugging round.)
$ts  = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
$key = (gcloud secrets versions access latest --secret=platform-sso-key --project agora-data-driven | Out-String).Trim()
$h = New-Object System.Security.Cryptography.HMACSHA256
$h.Key = [Text.Encoding]::UTF8.GetBytes($key)
$sig = ($h.ComputeHash([Text.Encoding]::UTF8.GetBytes("watcher-channels:$ts")) |
        ForEach-Object { $_.ToString("x2") }) -join ""
curl.exe -s -o NUL -w "%{http_code}`n" -H "X-Academy-Ts: $ts" -H "X-Academy-Sig: $sig" `
  https://portal.agoradatadriven.com/api/internal/watcher/channels
```

**Reading the result:** `200` = bridge healthy (an empty `channels` list then really means an empty
archive). `404` = the route doesn't exist in the deployed Atrium — what caused this bug. `401` =
signature/skew (check the UTC epoch above first). Signing purposes are `watcher-channels`,
`watcher-videos`, `watcher-transcript`, `watcher-transcripts`. Swap in `/api/internal/tasks` (purpose
`tasks`) as a control: if tasks answers `200` and watcher `404`, the transport is fine and Atrium is
missing the endpoint.

**Bulk import** (`POST /api/development/atrium/import-all` → `atrium_watcher.list_transcripts`):
pulls a whole creator in one go, because doing it one video at a time was unusable at 200 videos.
Atrium hands over the entire archive in a byte-budgeted response, so this is a couple of round trips
(measured: 104 transcripts / 6.3 MB → 2.1 MB gzipped, ~4 s), not one per video — hence the separate
`BULK_TIMEOUT` (180 s) instead of the 10 s used for the light listings. It is **idempotent** — rows
are matched on `source_url` (falling back to title), per user — so the button doubles as "catch me
up since Atrium fetched more", and a mid-way failure returns what was already collected rather than
discarding megabytes. Covered by `tests/test_atrium_import_all.py`.

### 🟡 The coach answers "what would Nick say?" by RETRIEVAL, not a bigger prompt

`services/mentor_search.py` + `GET /api/internal/mentor-search` (purpose `mentor-search`) are what
let the Mastery Engine coach speak from an imported mentor's material — and act as them when asked.
Design constraints worth knowing before changing it:

- **The library cannot be prompted.** One creator is ~104 transcripts / ~1M words, which is why
  `holistic_digest` could only ever send TITLES (`mentor_library`). The coach retrieves the handful
  of passages that bear on the question instead.
- **No new table, no migration** — deliberately. Prod has a history of not running Alembic, so a
  schema change here would be a silent no-op. Everything derives from `mentor_transcripts` rows and
  a per-user in-process index, invalidated by a `(count, max id, total length)` signature.
- **Chunks are indexed by mentor + title + body.** A transcript body almost never says its own
  mentor's name, so without this "what does Nick say about offers" retrieves nothing from Nick.
  (Atrium's assistant learned this the hard way — see its `assistant_ai.py`.)
- **`matched_mentor` is load-bearing.** It separates "that mentor isn't in your library" from "that
  mentor never covered this". Blur the two and the coach invents a real person's opinion — the one
  failure that makes the feature worse than not having it. The prompt in `mastery-engine`'s
  `lib/gemini.js` (`mentorGroundBlock`) depends on this distinction.
- Mentor names are matched loosely (`resolve_mentor`): people type "Nick", not "Nick Saraev".
- `holistic_digest.mentors` is the authoritative roster — `mentor_library` is capped at 40 titles
  and stops naming some mentors entirely once a library is large.

Covered by `tests/test_mentor_search.py`.

### 🟡 Gym routines: two constraints that shaped the design

Saved routines (`gym_routines`, added 2026-07-31) are named workout templates — "Push A", "Push B" —
that `services/gym.apply_routine` stamps onto a day's session in one call. Two things to know before
extending them:

1. 🔴 **Every `/api/gym/routines*` route must stay ABOVE the `/{log_id}` routes** at the bottom of
   `routers/gym.py`. FastAPI matches in registration order, so a `/routines` declared later is
   swallowed by `GET /{log_id}` and answers **422** (int parse) rather than listing anything.
   `tests/test_gym_routines.py` pins this.
2. **The weekday→routine binding lives on `gym_routines.weekdays_json`, not on `gym_schedules`.**
   That keeps the whole feature to ONE new table, and a new table is the only schema change
   `create_all` lands by itself. A new *column* on an existing table reaches an un-migrated DB only
   via `main._ensure_columns`. Given the split between "which kind of day" (the weekly plan) and
   "which routine", hanging it off the routine was also the better model — and
   `set_routine_weekdays` moves a weekday rather than duplicating it, so "what am I doing today?"
   always has exactly one answer.

Applying with `mode="replace"` also sets the session's `day_type` from the routine (loading a Push
template over a whole day means the day IS a push day); `append` leaves the split alone. Sets arrive
with `done: false` — a template holds sets to *do*, and pre-ticking them would log work never done.

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

`backend/.venv` does **not** exist on every machine. Fallback: the shared workspace venv runs the
suite too — from `backend/`:

```powershell
..\..\.venv\Scripts\python.exe -m pytest      # Agora/.venv — verified 213 passed
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

---

## 9. Standing debt & deliberate choices

Migrated from the retired `MODERNIZATION.md` (2026-07-29). The first two are **still-open HUMAN
actions**; the last two are decisions — don't "fix" them.

- **Leaked session-token files remain in git history.** `live.txt` and
  `backend/{cg,cm,em,live,pw,sa}.txt` were removed from disk and gitignored (2026-07-17), but the
  tokens live on in past commits. Still open: rotate the prod `JWT_SECRET`
  (Secret Manager `sentinel-jwt-secret`) and scrub history with `git filter-repo`.
- **Cloud SQL automated backups + a restore test were never set up.** Attendance/payroll data
  cannot be regenerated from `seed.py` — until backups exist, that data is unrecoverable.
  (See [deploy/DEPLOY.md](deploy/DEPLOY.md).)
- The rate limiter in `middleware.py` is **hand-rolled on purpose** — slowapi was rejected to
  avoid a new dependency and router churn.
- The task board keeps **native HTML5 drag-and-drop** — SortableJS was rejected because the CSP
  blocks CDNs, and the built-in works.

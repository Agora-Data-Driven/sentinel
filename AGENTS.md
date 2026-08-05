# AGENTS.md — Sentinel

> **Read this before touching any file.** It is the operating manual for this repo.
> Product/feature overview: [README.md](README.md). Deploy detail: [deploy/DEPLOY.md](deploy/DEPLOY.md).
> Deep map: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Task-board rebuild plan (analysis +
> decisions D1–D15 + build order; **every work package is built as of 2026-08-04** — what is left is
> three operator passes over live client data, and the runbook for them is §5.4 there):
> [docs/TASKBOARD_REBUILD.md](docs/TASKBOARD_REBUILD.md).
> Unit file maps + cookbooks:
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
| **Embeds** | The Mastery Engine, via iframe — Professional (formerly Academy) tab, Philosophical + Spiritual tabs (each pinned to one engine program via `?program=`), and the global Coach FAB. Every src is built through `S.engineUrl()`, which appends `&theme=` so the engine wears our light/dark; `setTheme` messages the running frames (§5) |

> ⚠️ **Region is `asia-southeast1`, not `us-central1`.** Every other Agora service is
> `us-central1`. Getting this wrong makes `gcloud` commands silently target nothing.

**Hard product rule:** clients never see internal fields (assignee, team, priority, internal
notes, attendance, gym). The Account Manager bridges Sentinel → Atrium via **Send to Atrium**,
which shares only client-safe fields. The reverse — a card Atrium owns, shown on this board — is
**fully editable here**, writing straight back to Atrium (§2, "The task board holds TWO kinds of
card"). Nothing internal crosses in that direction either: Atrium's own internal fields stay in
Atrium's team surfaces.

> **Send to Atrium really publishes now (2026-08-03).** It mints the client's card via
> `/api/internal/task-add`, stores the returned id in `tasks.atrium_task_id`, and thereafter every
> change to a client-visible field re-projects. Until this date it set `atrium_visible = True` and
> **created nothing** — see §5 and [docs/TASKBOARD_REBUILD.md](docs/TASKBOARD_REBUILD.md).

> 🔴 **TWO payloads cross to Atrium, and they are opposites. Never merge them (2026-08-05).**
>
> | | Who reads it | What crosses | Built by |
> |---|---|---|---|
> | **Client projection** | a CLIENT, in their own workspace tab | six fields (`task_bridge.SAFE`) | `services/task_bridge.py` — we PUSH |
> | **Staff mirror** | a SUPER-ADMIN, in Atrium's operator console | everything: assignee, priority, service charge, internal notes, hold reason | `services/board_mirror.py` — Atrium PULLS `GET /api/internal/board` |
>
> The mirror exists because Atrium's `/admin/atrium` Task Board used to be assembled from each
> client's workspace JSON — i.e. from the projections — so it could only show work somebody had
> already **shared with a client**. Every unpublished row was structurally invisible on a board
> whose subtitle claims "every client deliverable across every workspace", and the two systems
> disagreed about how much work the agency had. If a change ever makes these two payloads look
> alike, **the client one is the one that is wrong.** Pinned by `tests/test_board_mirror.py`.

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
  services/        business logic, called by routers (task_bridge.py = the Atrium projection;
                   task_workflow.py = the task lifecycle: completion, park, filing, review)
  utils/           time (Manila), qr, csv_export, passwords
  alembic/         migrations
  seed.py          populates every table with sample data
frontend/
  pages/*.html     thin shells — real markup is rendered by JS
  static/js/       app.js (shell + api() + toast) + one file per page, PLUS two mountable
                   components: taskboard.js and growth.js (`window.GrowthPanel`), which the
                   Overview (dashboard.js) hosts together — see §5
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
| `tasks.py` | Kanban board (page `/tasks`), priority (AM-only), Send to Atrium, the lifecycle actions (park/resume/archive/review), **editing Atrium's own cards** |
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
| `internal.py` | **HMAC-signed** service-to-service (Mastery Engine ↔ Sentinel, Atrium → Sentinel). Purposes: `user-lookup`, `academy-people`, `holistic-profile`, `growth-detail`, `mentor-search`, `task-request`, `task-feedback`, **`board`**, **`work-digest`**, **`work-detail`** |

Adding a router? Register it in the tuple at [main.py:322](backend/app/main.py#L322).

### The task board holds TWO kinds of card

| | Sentinel row | Atrium-owned card |
|---|---|---|
| id | an integer PK | the string `atrium:<client_key>:<task_id>` |
| stored in | Postgres `tasks` | that client's Atrium workspace JSON — **Atrium is the source of truth** |
| reaches the board via | `task_card` | `atrium_tasks.fetch_tasks()` → `as_board_card` (fail-soft: an Atrium outage just hides them) |
| who sees it | `task_perms.can_view` (employee/intern: **only what's assigned to them**) | `task_perms.can_view_atrium` — **team lead and up** |

🔴 **A card is one kind or the other, never both (WP 4.3, 2026-08-04).** The moment a Sentinel row
carries `atrium_task_id` — whether Send to Atrium put it there or adoption did — that row **is** the
client's card, and `list_tasks` drops the bridge's copy of it
(`task_adoption.claimed_atrium_ids(db)`). Without that the board rendered the same work twice: the
row (assignable, parkable, reviewable, counted) plus a read-only ghost that diverges from it the
instant either one moves. That was live from 2026-08-03, when Send to Atrium began really
publishing. Two rules if you touch it:

- **The claim set is keyed by `(client_key, atrium_task_id)`, never the id alone** — that id is
  unique only *within* a workspace. Matching globally would HIDE another client's card, and a card
  silently missing from a board is far worse than a visible duplicate.
- **A linked row with `client_id = NULL` is unattributable**, so it claims nothing and its card
  shows twice on purpose. `task_adoption.apply()` refuses to create such rows — link the workspace
  (`Client.atrium_client_id`) first.

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
- 🔴 **An Atrium card's OWNER shows on the board; its owner is still not a Sentinel user
  (2026-08-05).** `as_board_card` hardcoded `assignee: None`, so a client card whose **Lead** was set
  in Atrium rendered **"Unassigned"** on this board while its own drawer said "Lead: Charles". Two
  causes, and both are worth remembering: Atrium's LIST payload (`_internal_task_view`) carried
  `lead_id` — an *email* — while only its DETAIL payload resolved names, so the board genuinely had
  nothing to print; and "absent, never faked" was being applied to the wrong field. Not inventing a
  Sentinel **user id** is right; hiding the **name** just made the board lie about who holds client
  work. Now: `assigned_to_id` stays `None` (nothing joins on an Atrium owner, and every
  assignee-keyed filter still excludes these cards — that is what keeps them off employees' boards),
  `assignee` is an **id-less** `_person`, and `owner_label()` derives a display name from the email
  when Atrium sent none, so Sentinel works whether or not Atrium has redeployed. Both payloads now
  derive it in ONE place (`as_board_card`); `as_task_detail` no longer re-maps those fields, because
  two derivations is exactly how the card and the drawer disagreed. Atrium's half
  (`lead_name`/`support_names` in the list payload) is pinned by its `_atrium_smoketest.py`; this
  half by `tests/test_atrium_card_owner.py`.
### 🔴 Sentinel owns EMPLOYEES. Atrium owns CLIENTS. Manage → Clients is read-only.

Owner decision, 2026-08-05. Sentinel's `users` table is the source of truth for staff (§3 — SSO only
authenticates, this table authorizes). **Atrium's registry is the source of truth for clients**, and
Sentinel now MIRRORS it (`services/client_sync`) instead of keeping its own hand-maintained list.

Why it mattered enough to remove a form: `Client.atrium_client_id` is the **bridge key**.
`atrium_tasks.resolve_client` matches a client card with it, `task_bridge` needs it to know which
workspace to publish into, `board_mirror` puts it in the payload Atrium pulls, and `task_adoption`
**refuses to run** without it ("its adopted cards will appear twice on the board"). Every one of those
failures began as somebody not typing a workspace key into Manage. Two write paths existed and BOTH
are gone — `POST/PATCH/DELETE /api/manage/clients` and the quieter `POST /api/clients` (the meta
router), which let any AM mint an unlinked client straight from the New Task picker.

🔴 **The `clients` TABLE stays.** It is the FK target for `Task.client_id` and the local cache the
board's client filter reads. Only the hand-maintenance went.

What the mirror does, and the rule behind each step:

| Step | Rule |
|---|---|
| Upsert by `atrium_client_id` | A linked client's name follows Atrium's — that is what the console's Rename button edits and what the client sees |
| Adopt an unlinked client by **unambiguous name** | Writes down the link `resolve_client` was already inferring at read time, so nobody hand-types a key. Ambiguous → left alone |
| **Deactivate** what Atrium no longer lists — **opt-in only** | 🔴 NEVER delete: that NULLs `Task.client_id` on every past task and blanks that client's reporting. `Client.is_active` keeps the history and drops it from the pickers. And `deactivate` defaults to **False** — see below |
| Reactivate anything that returns | — |

🔴 **The sync refuses to act on an empty or failed answer.** Deactivation is driven by *absence*, so
"Atrium didn't answer" and "Atrium has no clients" must never be confused — that would switch off
every client in the estate in one pass. This is why `atrium_tasks.fetch_clients` returns an explicit
error instead of degrading to `[]` like every other read in that module, and why a zero-length list
with no error is refused too (a real estate is never empty).

🔴 **The automatic sync is ADDITIVE-ONLY: `deactivate` defaults to False.** Creating and linking are
safe in every direction; switching a client off is driven by ABSENCE, and absence is a lie whenever the
two systems spell a client differently. Measured on the live estate 2026-08-05: Atrium had **"Rooming
House Expert"** where Sentinel had *"Rooming House Experts"*, **"Riverdance RV"** vs *"Riverdance"*, and
**"The Contract Shop"** vs *"TCS"* — a blind first pass would have created a duplicate for each **and
retired the original**, leaving the board's tasks hanging off deactivated clients while empty
look-alikes filled the pickers. Candidates are always reported in `would_deactivate` (and in the boot
log) so the gap is visible rather than silent.

Retiring a client is therefore a deliberate two-step: read
`GET /api/manage/clients/sync-preview` — which is literally `sync(dry_run=True)`, **not** a second
walk, because a preview that re-derives the plan is a second definition of it — then
`POST /api/manage/clients/sync?deactivate=1`.

It runs on boot (`main._mirror_clients`, last and fully swallowed — a client list one boot stale is a
nuisance, a Sentinel that won't start is an outage) and on `POST /api/manage/clients/sync`. The
read-only Manage pane surfaces `GET /api/manage/clients/sync-status`, whose `unlinked` list is the one
actionable thing there: those clients are invisible to the bridge, and the fix is in **Atrium**.
Covered by `tests/test_client_sync.py`; the Atrium half is `GET /api/internal/clients` (purpose
`clients`), pinned in its `_atrium_smoketest.py`.

### 🔴 An Atrium lead is resolved to a SENTINEL user — and an `email ==` join does not work here

`services/atrium_identity.py`, 2026-08-05. Showing the lead's *name* on the card was only half the
job: **By Employee** groups by `assigned_to_id` and the Monitor rolls up by Sentinel user, so owned
client work still sat in the *Unassigned* lane, counted toward nobody's workload, and rendered
initials instead of a photo (there was no Sentinel row to read `profile_pic_url` from).

The trap is that the obvious join is wrong. **Sentinel's `users` table is the source of truth for
staff, but Atrium keeps its own roster keyed by email, and the two disagree on the domain for the
same human.** Atrium's canonical `ATRIUM_TEAM` alone spans `@agoradatadriven.com`, `@100.digital`
and `@bidbrain.com`; `_team_roster()` also merges live portal accounts, whose address may be a
personal Gmail (which is how a lead displays as "Agustinnico228"); Sentinel's own users are on
another domain again. An exact email match therefore resolved almost nobody.

So resolution is a ladder, and **every rung refuses to guess when ambiguous**:

| # | Key | Example |
|---|---|---|
| 1 | exact email | `justine@agora.ph` = `justine@agora.ph` |
| 2 | email local part | `justine@agoradatadriven.com` → `justine` |
| 3 | full display name | `"Justine Roa"` |
| 4 | first name | `"Justine"` → the one Sentinel user called Justine |

Two Justines, or two locals called `ian`, resolve to **nobody** — a visible gap (`client_cards` on
the Monitor row, "Unassigned" on the card) beats a silent mis-attribution on the table a manager
staffs from. Resolution stops at the first *unambiguous* rung; it does not fall through and give up.

What the resolved owner changes, and why each one matters:

- `assigned_to_id` → the card lands in that person's **By Employee** lane instead of *Unassigned*;
- `assignee` → the full `user_public`, so the **photo** appears;
- the Monitor counts the card toward them (`task_analytics.atrium_workload` takes the Resolver, not
  an email map);
- the board's `?assignee_id=` filter now KEEPS a card whose lead resolved to that person — dropping
  it while the card visibly shows their name and face is the same contradiction as the original bug.

`atrium_tasks.py` still never touches the DB: the ROUTER resolves (`_owner_index` / `_atrium_owner`,
one index per request) and passes `owner` into `as_board_card` / `as_task_detail`. Covered by
`tests/test_atrium_identity.py`.
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
                                                    viewer  (OFF the ladder — see below)
```

🔴 **`viewer` is a read-only seat, not a rung** (added 2026-08-03, decision D8). It **sees everything
and writes nothing**, which no point on a linear ladder can express — so:

- its **`ROLE_RANK` is the floor (1)**, deliberately, so no `require_min_role` gate can ever hand it
  a write;
- every READ surface it needs names it **explicitly** — `constants.VIEW_ALL_ROLES`,
  `task_perms.can_view` / `can_view_atrium`, and the Monitor rollup's guard;
- it is **never** in `MANAGER_ROLES` or `ADMIN_ROLES`: those gate approvals, exports and record
  edits, which are writes.

Adding a task write? Add a case to the `test_viewer_is_refused_every_task_write` parametrisation in
`tests/test_security_rbac.py`. The audit is the feature; the role is three lines.

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

### 🔴 `can_edit` is NOT `can_view`, and `can_edit_atrium` is NOT `can_view_atrium`

Both were bare aliases until 2026-08-03, and both are why no read-only seat could exist (§2.4b):
anyone who could see a card could rewrite its title, dates, breakdown and notes, and anyone who could
see a CLIENT card could edit, move, comment on and resolve it. They are separate functions now — keep
them separate even though the bodies look near-identical, because the seam is where the next role
goes. `tests/test_security_rbac.py` fails if either is re-aliased.

Two consequences in `routers/tasks.py` worth knowing:

- **`_require_atrium` guards a READ; `_require_atrium_write` guards a WRITE.** Every Atrium branch
  used to call the first one. Four of the five were writes.
- **Posting a comment and adding an attachment are WRITES**, and both were gated on `can_view`. A
  thread you may read is not a thread you may write to.

### 🔴 Naming somebody on a SUB-TASK is delegation — it was ungated until 2026-08-03

`task_perms._assigned` counts **step owners** for visibility, so writing `maintasks[].assignee_id` or
`subs[].assignee_id` puts the card on that person's board. But `update_task`'s delegation guard
covered `assigned_to_id` / `assigned_team_id` only, and `maintasks` went through its own branch with
no assignee check at all — so **an employee who could not reassign a task could still drop any card
onto any colleague's board by naming them on a sub-task** (docs/TASKBOARD_REBUILD.md §2.4e).

Closed where the field is WRITTEN, not in the UI: `update_task` diffs the breakdown's owners and
refuses when the change involves anyone but the actor, unless `can_reassign`. What stays open on
purpose:

- renaming, adding and deleting steps — that is editing the work, not handing it out;
- **self-assignment** — picking up an unowned step or dropping your own. Every role may do that, or
  the board stops working for the people using it.

If you add another way to write the breakdown, it needs the same diff — the guard is on the field,
and a second writer would walk straight past it.

🔴 **The diff is per SLOT, and comparing owner SETS was the same hole a second time (2026-08-05).**
It compared `{owner ids} before` with `{owner ids} after`, so every edit that left the *set* intact
answered 200. An employee could therefore still rearrange a colleague's work: **move their step to a
different one, pile them onto five more, or swap two colleagues over.** Each of the six original
tests adds or removes a person, which is exactly why none of them saw it. `maintasks.slots` keys
every phase and step, `foreign_owner_changes` compares them slot by slot, and duplicate ids get
distinct slots (`_slot_key`) so a resent step cannot hide a handover. Removing a slot counts as an
ownership change, which is what keeps "delete the step somebody else owns" refused.

🔴 **Ticking a step is scoped too, and it is NOT `can_edit` (2026-08-05, `task_perms.can_tick_step`).**
"Done" is a claim about work another person performed, and it is what the progress bar and the D5
review gate read — yet any of a card's several owners could close each other's steps. Now: the
step's owner, the card's `assigned_to_id`, or `can_reassign`; an **unowned** step stays open to
anyone who can edit (that is how a team queue is worked through), and an Atrium card keeps the old
open behaviour because its owners are roster emails, not Sentinel users. The refusal names the owner.

Three more asymmetries closed the same day — all of them "the server was right, the UI lied":

| Was | Now |
|---|---|
| `create_task` let a team lead name anyone **company-wide**, while `can_reassign` scopes them to their own team on edit | `may_delegate` requires `payload.assigned_team_id == user.team_id` for a lead. **Priority deliberately keeps the old role-only rule** (`may_prioritize`) — it is not delegation, and tying it to the team test would silently downgrade a lead's cross-department card to Medium |
| Naming somebody you may not delegate to was **silently dropped** and answered 200 | **403** with the reason. Naming *yourself* still passes, even alongside a department |
| Bulk allowed any `value == user.id`, so an employee could **take** a card a colleague owned | `may_claim` also requires `assigned_to_id is None` — claiming from a queue, never lifting work off a person |

`frontend/static/js/taskboard.js` mirrors all of it (the `Lead (main)` picker was the only field in
that form with no gate; step pickers list only the actor for a non-delegator; a step you may not tick
renders `disabled` with the owner's name). **The mirror is courtesy — every one of these is enforced
in `routers/tasks.py`.** Pinned by ~20 cases in `tests/test_security_rbac.py`,
`tests/test_task_assignment.py`, `tests/test_task_bulk.py`.

Still open, deliberately not changed here: **bulk's assignee branch tests no `can_view`**, so an
employee can claim an unowned card they cannot see by id (the status branch does test it, via
`can_move`). Narrow it only together with `test_assigning_someone_else_still_needs_delegation_rights`,
which pins today's shape.

### 🔴 "Is this work on me?" has ONE definition — `task_perms.is_assigned`, shipped as `mine`

Added 2026-08-05, as the other half of the section above. If naming somebody on a sub-task puts the
card on their board, then **every surface that answers "what is on me" has to count step owners** —
and one didn't. The Overview's "my work" strip filtered in JS on `assigned_to_id === S.user.id`, the
narrower rule. So a card **led by a colleague with a step named to you** was on your Task Board
(`can_view` → `is_assigned`), openable, editable, tickable… and the Overview said **"0 open tasks ·
nothing on you right now"**. The page told a delegate their plate was empty with the work one click
away. The board's own "My work" button had the same hole, because it just set `?assignee_id=<me>`.

The fix is that there is no second copy of the rule, in any language:

| | |
|---|---|
| the definition | `task_perms.is_assigned(user, task)` — the card's lead **or** any phase/step of its breakdown. Public for this reason; it is what `can_view` already asked |
| how a surface gets it | `serializers.task_card(t, db, viewer=user)` → **`mine`** (bool) + **`my_slots`** (how many breakdown slots that viewer holds) |
| who passes a viewer | `list_tasks`. `people.py`'s profile card does not — it lists somebody *else's* work, so the two fields are **absent, never a hardcoded `false`** |

Three rules if you touch this:

- **`?assignee_id=` stays a FIELD filter** (`Task.assigned_to_id`, nothing else). "What is on Jerome?"
  is a real question a manager needs answered precisely. "My work" is a separate client-side flag
  over `mine`, so widening one can never silently widen the other.
- **"I can see it" is not "it is mine."** A team's unowned queue, a card you created, an AM's whole
  cross-client board — all visible, none of them `mine`. Blur that and the Overview's "Open tasks"
  tile becomes a company-wide total on one person's morning page.
- **If a card's lead is somebody else, the surface has to SAY so** — that is the "N steps on you"
  pill (`my_slots`). Otherwise the fix reads as the strip listing other people's work, i.e. as the
  July 2026 regression wearing the opposite face.

Pinned by `tests/test_task_mine.py`.

**The Monitor rollup had the same blind spot, and every KPI sits on top of it.**
`GET /api/tasks/summary` bucketed by `assigned_to_id` alone, so a person whose work arrives as steps
of colleagues' cards read as **idle** — with capacity to spare, according to the table a manager
staffs from. It buckets by `assigned_user_ids` now, which has one consequence to state out loud
wherever these numbers are shown:

> 🔴 **The rows do not sum to the number of tasks.** A card with a build phase on one person and a QA
> step on another is on two plates and is counted on both. `stepped` says how much of a row arrived
> that way. Do **not** "fix" the double count by attributing each card to one owner — picking a
> winner re-hides exactly the work this surfaced.

### 🟡 Monitor's workload metrics are DERIVED — a task on this board has no size

`services/task_analytics.py`, added 2026-08-05. The honest constraint first: **there is no effort,
estimate or points field on `tasks`**, so a card count cannot answer "who is overworked" — one card
is a ten-minute copy tweak or a three-week build. An estimate field was considered and rejected for
now: a half-populated one produces worse numbers than none. So every column is derived from data the
board already keeps honestly:

| Column | Derived from | The trap it avoids |
|---|---|---|
| median cycle days | `start_date`/`created_at` → `completed_at` | **Median, not mean** — one six-month epic makes a mean unreadable |
| on-time rate | `completed_at` vs `due_date` | **`None`, never `0`, when nothing dated shipped.** Zero means "everything was late"; undated completions are excluded, not counted as on time — a card with no due date made no promise |
| sitting | `updated_at` of OPEN cards (`STALE_DAYS`) | Two clocks on purpose: `oldest_open_days` is `created_at` (how long owed), `stale_open` is `updated_at` (untouched). Old ≠ stale |
| capacity | approved `LeaveRequest` | Only **approved** leave — a pending request is a question, not a fact about who is at their desk |
| `load_band` | open work **vs the cohort's own median** | Never absolute. Suppressed entirely when the median is < 2 (there, "double the median" is one card), and `overdue >= 3` forces `heavy` so a small-but-late pile isn't rendered `light` |

**Atrium's client cards count toward the lead they resolve to (2026-08-05).** The rollup queried
Sentinel's own `tasks` table only, so every card Atrium owns counted toward **nobody** — a person
holding fifteen client cards read as idle on the table a manager staffs from. The join is the Atrium
lead's **email**, matched case-insensitively against `users`, because an Atrium owner is a roster
email and never a Sentinel id. Four rules hold it together:

| Rule | Why |
|---|---|
| A lead with no Sentinel account is counted for **nobody** | Inventing an owner is worse than a gap |
| Cards already claimed by a Sentinel row are **skipped** (`claimed_atrium_ids`) | WP 4.3 — the linked row *is* that card; counting both inflates the same work twice, exactly as it would render twice on the board |
| The read is **fail-soft** (`fetch_tasks` → `[]`) | An Atrium outage costs a manager the client half of these numbers, never the whole page |
| Atrium's dates are **strings**; `task_analytics._as_date`/`_as_dt` parse them | The rollups compare against `date`. Unparsed, one malformed field on one client card takes the entire manager surface down with a `TypeError` |

🔴 **A client card carries no `completed_at`, so it reaches Open / Overdue / Sitting and NOTHING
else.** `task_analytics.AtriumWork` sets it to `None` and `delivery()` skips any row without a stamp,
so cycle time, the on-time rate and throughput are **Sentinel rows only** — substituting `updated_at`
here would be the §2.4h bug wearing a new hat. `client_cards` on the row exists to make the UI *say*
that; without it, somebody who delivers mostly client work looks like they never ship anything.

Two rules if you extend this:

- **The band is relative and the UI says so** (`.mon-legend`). Do not restate it anywhere as
  "overloaded" — the data cannot support that word, and the moment a surface implies hours, someone
  will staff against it.
- **A band is computed across the rows the CALLER can see**, so a team lead is compared against their
  own team. The cohort on screen must be the cohort the comparison claims to be about.

Covered by `tests/test_task_analytics.py`.

### 🔴 An employee's board = their own work **plus their team's unowned queue**

Changed 2026-08-03 (§2.4c). Read `task_perms._team_queue` before touching `can_view`: the condition
is narrow, and both halves are load-bearing.

| state | on a team member's board? | why |
|---|---|---|
| assigned to them | yes | it is their work |
| routed to their team, **owned by nobody** | **yes** | it is the team's triage queue |
| routed to their team, owned by a colleague | **no** | it is that colleague's job |
| another team's queue | no | not their business |

Widening this to "every card routed to my team" would re-create the July 2026 regression where an
intern's board showed seven cards, none of them theirs. Narrowing it back to assignment-only
re-creates the invisible middle step: AM files it → routes it to Acquisition → *nobody can see it*
until a lead happens to look. Both directions have already been wrong once.

Two consequences that look like bugs and are not:

- **A card routed away leaves the filer's board.** That is why `GET /api/tasks/filed-by-me` exists —
  it answers "where did my work go" without putting the card back (§2.4d, D10).
- **A lead who sends work back can no longer see it** (`POST /{id}/send-back`, D11). The team link is
  cleared and the filer owns it again. Refusing work stops it being yours.

**The third state, added with WP 4.3: `_unowned_client_work`.** A row linked to a client's Atrium
card with no assignee *and* no team is on every **manager's** board (team lead and up) until somebody
owns it. It exists because adoption creates exactly that shape — no assignee, no team, and a creator
tag naming whoever ran the import — so every other clause of `can_view` says no, and a team lead
would have silently stopped seeing client work they can see today. It is `_team_queue`'s twin for
work that has not been routed to a team yet, and it obeys the same rule: **the moment it is owned it
leaves the boards it is not on.** It never widens to employees/interns — the manager surface has to
survive the collapse of the two permission models without becoming a wider one.

### 🔴 The Task Board is a PAGE — and `/dashboard?open=<id>` must forward to it forever

The board has moved twice: its own `/tasks` page → embedded in the dashboard (2026-07-26) → its own
page again (**2026-08-03**, decision D7). Each move stranded a set of notification links, and those
rows are **permanent**:

| minted | link in `notifications` | what serves it now |
|---|---|---|
| before 2026-07-26 | `/tasks?open=<id>` | the real page — arrives home |
| 2026-07-26 → 08-03 | `/dashboard?open=<id>` | `main.dashboard_page` forwards to `/tasks?…` |
| since 2026-08-03 | `/tasks?open=<id>` | the real page |

🔴 **`dashboard_page` forwards ONLY when a board param is present** (`open` / `new` / `view`,
`main._BOARD_PARAMS`). `/dashboard` bare is the landing page for the whole company every morning —
redirecting it wholesale sends everyone to the task board. And `"/dashboard"` is deliberately NOT in
`_PAGES`: that loop would register a plain page route and shadow the forward.

The board itself is still the mountable component `TaskBoard.mount(S, root)` in `taskboard.js` —
`pages/tasks.html` + `tasks.js` are a ~20-line shell around it, and the dashboard keeps only a "my
work" strip that links in. Bump `sw.js` when you touch any of it.

### 🔴 Opening a task is a WIDE CENTRED MODAL — a docked panel does not fit this board

Two changes on 2026-08-03, in that order. The detail was `S.modal({drawer: true})`, a 560px overlay
with one long column of fields. It became a **sticky side panel** (split view) so the board stayed
visible… and that was **reverted the same day**, because the board's dimensions make it impossible:

| | width |
|---|---|
| sidebar (`--sidebar-w`) | 248px |
| 5 columns × 288px + gaps | **1496px** |
| a 340px panel + gap | 356px |
| page padding | ~56px |
| **needed before anything breathes** | **≈2156px** |

The board **already** scrolls horizontally at ~1800px with no panel at all, so the panel squeezed the
columns *and* cramped itself. Worse: at 340px the `.spread` field grid (`minmax(220px, 1fr)`)
collapses to **one** column, so eleven label/value pairs stacked up before the work breakdown came
into view. In `.modal.wide` (920px) that same grid gives four.

So: **`.modal.wide` + a two-column body** (`.tb-cols` — the record left, work + conversation right),
which is also what makes it shorter than the panel ever was. Do the arithmetic above before
re-proposing a docked panel.

What survived from the panel attempt, and is worth keeping:

- **The URL carries the open card** (`?open=<id>`, via `replaceState` — not `pushState`, or opening six
  cards buries the page under six back steps). Same param every notification uses, so a click, a
  shared link and a notification all land identically, and a refresh keeps the task open.
- 🔴 **`openTaskModal` re-points the modal's three closers.** `S.modal`'s ✕, overlay-click and Esc all
  call its *internal* close, so wrapping the returned `close` is not enough — the `?open=` param would
  survive those three paths and the URL would lie.
- `confirmDelete` stays its own modal: a destructive confirm SHOULD block.

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

### 🔴 A status has a LABEL, a KEY and a STAGE — never key anything off the label

Since 2026-08-03 (decision D13). `task_vocab.name` is a **label**: Manage renames it and
`_rename_in_tasks` cascades the new string onto every task row, so `tasks.status` always holds the
current label. Two more columns give a status an identity that survives that:

| facet | column | rule |
|---|---|---|
| label | `name` | renameable, cascaded onto every task |
| identity | `vocab_key` | minted once from the first name, **never** re-slugged on rename |
| client stage | `stage` | which of Atrium's five stages a published card sits in |

Before this, `atrium_tasks.STAGE_BY_STATUS` was a literal dict keyed by the **display string**, so
renaming a status silently broke the bridge for every client card — a move answered a bare
400 "Invalid status". Resolve through `task_config.stage_for(db, status)` /
`status_for_stage(db, stage)`; the literal map survives only as the fallback for a DB seeded before
the columns existed.

Consequences worth knowing:

- **A new status must declare its stage.** `POST /api/manage/task-vocab` 400s a stage-less status,
  because a column a client card can never enter is a trap that only surfaces weeks later.
- **`retire_statuses` targets a STAGE, not a label.** `RETIRED_STATUSES` values are stage keys and
  the surviving column is resolved at run time. It used to be `constants.TASK_BLOCKED`, so once
  Blocked was renamed that boot-time sweep would have filed live cards under a status with no
  column — off the board, no error.
- **`main._backfill_status_meta()` runs every boot**, which is how the two columns reach rows that
  already exist in **production** (same reason `retire_statuses` runs there). A *custom* status
  added before the columns existed gets a key but **no guessed stage** — guessing would file a
  client's card in the wrong column, so `publish` refuses instead.
- The DB column is `vocab_key`, not `key`: `_ensure_columns` builds raw `ALTER TABLE … ADD COLUMN`,
  and a bare `key` is a keyword in enough dialects to not be worth the risk.

Covered by `tests/test_task_status_stages.py`.

**A SHIPPED rename travels in the deploy — `task_config.RENAMED_STATUSES` (WP 1.2, 2026-08-04).**
Blocked → **Parked** (and Atrium's client column → **Paused**) went in this way rather than as the
one-field Manage edit this section used to recommend. Two reasons, and the second is the one people
miss: a hand-edit has a destructive ORDER constraint on whoever clicks it (rename before the code
ships and the boot-time retirement sweep files live cards under a column that isn't there), and it
reaches **one database** — every other environment then seeds the new label while the old board keeps
the old one, and the two boards disagree in wording forever. `rename_statuses(db)` is the twin of
`retire_statuses`, and needs all three of these to stay safe:

- **keyed by `key`, never the old label** — so it runs **strictly after `_backfill_status_meta()`** in
  `main._startup`, which is what fills `key` in on a pre-D13 board. Reversed, it silently matches
  nothing on exactly the oldest boards;
- **it rewrites one named old label, and only while that label is untouched** — a team that renamed
  their blocked column themselves keeps their name through every deploy. It corrects a default, it
  does not enforce a policy;
- **`tasks.status` is cascaded in the same commit** — the label is what task rows store.

🔴 **Anything that keys off a status LABEL breaks on the next rename, silently.** Shipping this found
one that had been there all along: the Monitor's workload bar built its segments from a hardcoded
`["To Do", …, "Blocked"]`, so on the live board it went from covering 18 of 18 open cards to **8** —
the ten parked ones just stopped appearing, and any status somebody *added* had never been counted at
all. It derives from `/api/vocab` and colours by STAGE now. Grep for status literals before renaming
anything. Both legacy spellings stay listed in `atrium_tasks.STAGE_BY_STATUS` and
`task_config.LEGACY_STATUS_NAMES` on purpose — those are the paths an un-migrated board takes.

### 🔴 A task's lifecycle is `services/task_workflow.py` — don't set those columns by hand

Added 2026-08-03 (Stage 2 / M2–M5). Eight columns on `tasks` that look like ordinary fields and are
not: each is written by a RULE, and setting one directly reproduces the bug it was added to fix.

| Column(s) | Owned by | The rule |
|---|---|---|
| `completed_at` | `on_status_change` | Stamped by the TRANSITION into a done column, cleared on the way out. **Never typed, never backfilled.** |
| `archived` | `archive` / `unarchive` | Only COMPLETED work may be filed. Reopening a filed task un-files it. |
| `on_hold` + `hold_reason` + `resume_to` | `park` / `resume` | Three coupled fields, one writer — which is why `on_hold`/`hold_reason` stay in `atrium_tasks.ONLY_ATRIUM` even though Sentinel has the columns. A PATCH could otherwise park a card with no memory of where it came from. |
| `review_state` + `reviewer_id` | `submit_review` / `approve` / `request_changes` | Approval gates entry into a done column and is **spent** by that completion. |
| `start_date` | ordinary field | The one plain one — and it had to be REMOVED from `ONLY_ATRIUM`, which was silently dropping it from every Sentinel PATCH. |

Four consequences worth knowing before changing anything here:

- **"Is this done?" is `task_config.is_completed(db, status)` — a STAGE test, never `== "Completed"`.**
  The rollup, the stamp, the review gate and the file button all ask it, which is what makes the
  Blocked → Parked rename (and a second done column) safe.
- **Throughput counts `completed_at`, not `updated_at`.** Off `updated_at`, fixing a typo on a task
  finished in March re-dated its completion to today (docs/TASKBOARD_REBUILD.md §2.4h). A completed
  row with no stamp is counted on NO day — deliberately. Nothing backfills the column from
  `updated_at`, because that value is precisely what stopped being trusted.
- **Filed work is off the board but still counts as shipped.** `_aggregate` drops archived rows from
  the column counts and the overdue tally, and keeps them in "Done · 7d". Excluding them outright
  would mean filing a delivered task erased the fact that it shipped.
- **Filing never touches the client's card.** Park does (the stage moves); `archive` does not. Atrium
  has no archive in this bridge, and quietly moving or hiding a delivered card rewrites what the
  client was told.

The review gate is the **only** enforced rule on this board — a card with six open steps still drops
into Completed (surface, never enforce; §2.2.2 of the plan). It answers **409** with
`task_workflow.NEEDS_REVIEW`. Covered by `tests/test_task_workflow.py`.

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

### 🔴 "Send to Atrium" used to publish NOTHING — and the drawer said it had

Fixed 2026-08-03. `POST /api/tasks/{id}/send-to-atrium` set `atrium_visible = True`, wrote an
`AtriumApproval` row, logged history — and never called `atrium_tasks.add_task`, the one function
that creates the card. So the AM got a success toast, the drawer showed "✓ In Atrium", and the
client's Tasks tab stayed empty **forever**. Every `atrium_visible=True` row predating the fix
points at a card that was never created.

`services/task_bridge.py` is the projection now, and three rules keep it honest:

1. **A share is only real when `tasks.atrium_task_id` is set.** `atrium_visible` alone is the old
   lie, so `task_bridge.published()` — and the API's `atrium_shared` field — test the id, never the
   boolean. `add_task` returns `(task_id, error)` for this reason; a 200 with no id is a FAILURE,
   because a card we cannot address again would recreate the same lie one row at a time.
2. **Only `client_safe_fields()` may build a bridge payload** — title, client note, launch date,
   deliverable URL, and the breakdown reduced to phase names + step text/done. Assignee, team,
   priority, `service_charge`, `internal_notes`, the creator tag and every step's `dod` never
   cross. That function is the bridge's field-exposure boundary, the way `serializers.py` is the
   API's.
3. **A push failure is LOUD.** It lands in `tasks.atrium_sync_error` (NULL = the client's card is
   current), the board renders it, and `POST /{id}/atrium-retry` clears it. An edit whose push
   failed still SAVES — the local write succeeded — but the row admits the client's copy is stale.

`GET /api/tasks/atrium/stale-shares` reports the pre-fix rows; there is deliberately **no bulk
publish**, because those are live client records and some are months old or already delivered
(decision D15). Resolve each with a real share or `POST /{id}/atrium-clear-share`.
Covered by `tests/test_task_publish.py`.

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

### 🔴 The AI coach can READ the task board — and the SCOPING is the security property

`services/work_digest.py` + `GET /api/internal/{work-digest,work-detail}` (purposes `work-digest`,
`work-detail`), added 2026-08-05. The Mastery Engine coach already knew a worker's development; now
the same chat box knows their actual plate, so "what should I do today?" is answered against real
cards, and a manager can ask "who is buried?". The engine half is `workDigest`/`workDetail` in its
`lib/sentinel.js` and `workBlock` in its `lib/gemini.js`.

**Why this endpoint is unlike every other one on that router.** `holistic-profile`, `growth-detail`
and `mentor-search` each say "always the user's OWN data, so no manager check applies". The board is
not that — it is other people's work — so every card goes through **`task_perms.can_view(user, task)`,
the same predicate `list_tasks` filters the real board with**, and the per-person rollup copies
`/api/tasks/summary`'s cohort rule (AM/admin/viewer see everyone, a team lead their own team,
employees/interns none). Widen either and the Coach FAB becomes an RBAC bypass with a chat box on it.

Four rules that hold it together:

| Rule | Why |
|---|---|
| **The viewer's OWN index is complete** — open cards AND their whole finished history | The coach concludes "you have nothing about X" from X's absence. Live probing the two endpoints against each other found a card completed last month that appeared in NO list yet `work-detail` would hydrate it — the coach would have denied work the person can see on their own Past-work list. Same failure as the 600-char `other_info` cap |
| **`work-detail` re-checks every id** | An id is just an integer, and the caller is an LLM. An id the viewer may not see is absent exactly as an unknown one is, so nobody can walk the table by guessing |
| **A truncation is DECLARED** (`board.truncated`, `mine.done_truncated`) | An AM sees the estate, so the wider board is capped — and the prompt says how much it could not see, so a miss reads as "there are 12 more" rather than "there are none" |
| **`service_charge` never crosses**; `internal_notes`/`hold_reason` only via `work-detail` | Not needed to coach anybody, and the one field whose leak into a chat transcript is a commercial problem. Pinned by a test |

🔴 **This is NOT the staff mirror.** `GET /api/internal/board` hands Atrium's superadmin console
everything on purpose (§2). This is scoped to ONE viewer. If a change makes the two converge, this
one is wrong. Nothing here keys off a status LABEL either (D13) — `stage_for`/`is_completed` only.

The coach is **read-only** on the board: `workBlock` states it cannot move, assign, reschedule or
close a card, and no `agora-action` op touches tasks. Adding writes means extending the action
protocol (§ the holistic profile's approval flow) — the digest alone must never become a write path.
Covered by `tests/test_work_digest.py` (20 cases, weighted toward the refusals).

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

### 🔴 The coach's growth-journal INDEX must never be capped

The Growth hub's four dimensions each hold **titled entries** (`growth_items`, one idea per row,
`dimension` added 2026-08-01). `holistic_digest` ships **every entry's title, uncapped**, on every
coach turn; the `detail` bodies are fetched separately via `GET /api/internal/growth-detail`
(purpose `growth-detail`, `services/development.growth_details`). Small-to-big retrieval — and the
split is only safe because of one rule:

> **The index is complete; only the bodies are lazy.**

The coach decides "you have no note about X" by not finding X in that index. Cap or filter the
index and that inference becomes a confident lie. A missing *body* is recoverable (the title is
still listed, so the coach can say "you have a note called X I haven't opened"); a missing *title*
is not. So: never add a `[:N]` to `growth_index`, never drop archived rows from it, and never
truncate a `detail` — bodies are budgeted from the index's `chars` **before** fetching precisely so
they never need cutting. The Mastery Engine end mirrors this (`growthGroundingFor` in `server.js`,
`growthNotesBlock` in `lib/gemini.js`), and declares whatever it didn't load.

**This replaced `development_areas.other_info`**, a per-dimension free-form blob with no titles and
therefore no index — so it could only ever be sent truncated. It was capped at 600 chars, and the
coach consequently denied the existence of a list the worker was looking at on their own screen.
The field still exists, is no longer truncated, and surfaces in the UI as "Unfiled" with a one-click
path into a real entry; `update_area` remains for editing/clearing it, but the coach is told to
prefer `add_growth`. The same cap-the-index bug is documented one section down for
`mentor_library` — it is the same mistake, and it has now been made twice.

Covered by `tests/test_growth_notes.py`. 🔴 The column reaches **prod** via
`main._ensure_columns` (deploys don't run alembic); `b6d2f8a4c7e9` is the local/migrated path and is
existence-guarded because `create_all` usually wins the race.

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

### 🟡 The Overview is ONE page assembled from components — `/growth` is not your growth hub

Merged 2026-08-03. `/dashboard` (labelled **"Overview"**; the URL is unchanged because
notifications, the command palette and everyone's bookmarks point at it) now hosts, in reading
order: greeting + the day strip → `GrowthPanel`'s four rings → `TaskBoard` → `GrowthPanel`'s
ledger → the admin block. Consequences worth knowing before you edit any of it:

- **`growth.js` exports `window.GrowthPanel`, not `window.pageInit`.** The Overview loads it
  *alongside* `dashboard.js`, and two files assigning `pageInit` is a silent last-one-wins bug.
  `mount(S, root, {userId, ringsHost, mast})`; `ringsHost` is what lets the task board sit
  between the compass and the ledger.
- **`/growth` survives only as a manager's read-only view of somebody else** (`?user=<id>`,
  `growth-page.js`). With no `?user` it redirects to the Overview — rendering a second copy of
  your own hub is how the two drift apart. It is no longer in the Growth hub's nav children,
  so that hub is now exactly the four engine tabs.
- **Each ring is the door into its Mastery Engine tab** (`/academy`, `/philosophical`,
  `/spiritual`, `/gym`); the quiet "Details" strip under it expands that dimension in the ledger.
  Two affordances, deliberately not one overloaded click.
- Both mounts are **fail-soft**: a broken `/api/development` must never cost anyone their board.

### 🟡 An embedded Mastery Engine stays light inside a dark Sentinel

The engine is cross-origin, so it cannot read our theme. We hand it over twice and BOTH halves are
required: `S.engineUrl()` appends `&theme=` to the iframe src (the initial paint), and `setTheme`
postMessages `{type:'agora-theme'}` to every iframe (the toggle moving while a frame is already
running). Build every engine src through `S.engineUrl()` — a hand-built src loses half of it.
Also give the iframe `background:var(--card)`, never `#fff`: a white slab flashes behind the
engine on every load in dark mode. The engine end is `public/theme.js` there.

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

🔴 **Never run two pytest processes at once — the suite is not concurrency-safe with itself.**
`tests/conftest.py` pins `DATABASE_URL` to ONE fixed path (`%TEMP%/sentinel_pytest.db`) and rebuilds
the schema for every test, so a second run drops the first run's tables mid-test. The damage looks
nothing like a race: you get `sqlite3.OperationalError: no such table: shift_templates`, fixture
ERRORs, and a scatter of 500s in unrelated files — i.e. it reads as "my change broke everything".
If you see that, check for another run (including a backgrounded one) before debugging your diff.
The same applies to a CI runner executing two jobs on one machine.

🟡 **A SECOND cause wears the same mask: something on the machine sweeping `%TEMP%`** (seen
2026-08-05 — `Get-Process python` empty, no second run, and the tables still vanished *between two
statements of one test*, mid-`_seed_config`). Same symptoms, plus `table X already exists` straight
after a `drop_all`, and it moves around between runs. The tell is that a file you never touched
(e.g. `tests/test_gym_routines.py`) fails the same way — **run one of those before you believe your
diff broke anything.** Fix: relocate the DB by pointing the temp dir somewhere stable for the run,
which `conftest`'s `tempfile.gettempdir()` obeys:

```powershell
$env:TMP = "C:\some\stable\dir"; $env:TEMP = $env:TMP
..\..\.venv\Scripts\python.exe -m pytest      # 548 passed, 2026-08-05
```

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

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
> **The operating-system release (2026-09-02) is BUILT — §5 "Sentinel as the operating system".**
> Proposal + rationale: [docs/SENTINEL_OPERATING_SYSTEM.md](docs/SENTINEL_OPERATING_SYSTEM.md); the
> team's SOP: [docs/SENTINEL_SOP.md](docs/SENTINEL_SOP.md); the mockup it was built from:
> `docs/sentinel_ops_mockup.html`.

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
| **Embeds** | The Mastery Engine, via iframe — Professional (formerly Academy) tab, Philosophical + Spiritual tabs (each pinned to one engine program via `?program=`), and the global Coach FAB. Every src is built through `S.engineUrl()`, which appends `&theme=` so the engine wears our light/dark; `setTheme` messages the running frames (§5). 🔴 **The Coach FAB is that same engine's study assistant in a frame — one assistant, and one door per page (§5)** |

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

**Live reload is on by default and needs no setup** (added 2026-08-06). `--reload` restarts Python;
the other half watches `frontend/` and pushes to the browser, because a vanilla-JS frontend with no
build step has nothing else watching it:

| You save | What happens |
|---|---|
| a `.css` file | the stylesheet is **swapped in place** — no reload, so the open task card, the board's filters and your scroll position all survive |
| a `.js` / `.html` file | the page reloads |
| a `.py` file | uvicorn restarts, and the browser reloads itself when it reconnects (it compares a per-process boot id) |

`routers/dev.py` + `static/js/devreload.js`. **It cannot run in production** — see §5 for the three
independent gates and the one page that opts out (`/kiosk`, which must still boot offline from its
service-worker cache). Switch it off locally with `DEV_RELOAD=false`.

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
  capabilities.py  the NAMED-CAPABILITY registry + its invariants ← "what may this role do", §3
  security.py      JWT cookie auth + RBAC dependency guards      ← auth lives HERE
  sso.py           portal ag_sso cookie verification
  middleware.py    CSP, Permissions-Policy, security headers, gzip ← see §5 gotchas
  assets.py        content-hashed CSS/JS URLs (the build id)      ← see §5 gotchas
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
| `gym.py` | Workouts, exercise library, schedule/overrides, cardio, **saved routines**, **coach log-visibility** (`/coach-visibility` — §5) |
| `tasks.py` | Kanban board (page `/tasks`), priority (AM-only), Send to Atrium, the lifecycle actions (park/resume/archive/review), **editing Atrium's own cards** |
| `people.py` | Directory, profiles, QR badges |
| `leave.py` | Requests, approvals, balances |
| `development.py` | Holistic development hub — learning, reading, growth, **`GET /team`** (admin+: everyone's growth ranked by measured speed — `services/team_growth.py`) |
| `payroll.py` | Payroll runs |
| `reports.py` | 6 reports + CSV export |
| `admin.py` | System settings, announcements, audit log |
| `manage.py` | Admin management screens |
| `permissions.py` | **The role × capability console** (page `/permissions`) — read/edit which capability each role holds. Deliberately NOT under `/api/manage`; see §3 |
| `notifications.py` | Bell, unread counts |
| `meta.py` | Enums/constants for the frontend |
| `cron.py` | Scheduled job endpoints — `POST /daily` (the full pass, **manual only**, see §2) and `POST /report` (regenerate the personal context Google Doc; what Cloud Scheduler actually calls) |
| `stream.py` | SSE push to the browser |
| `dev.py` | **Local-development live reload** (`GET /api/dev/reload`, SSE). 404s in production — §5 |
| `internal.py` | **HMAC-signed** service-to-service (Mastery Engine ↔ Sentinel, Atrium → Sentinel). Purposes: `user-lookup`, `academy-people`, `holistic-profile`, `growth-detail`, `mentor-search`, `task-request`, `task-feedback`, **`board`**, **`work-digest`**, **`work-detail`** |
| `ops.py` | **The operating-system surfaces (2026-09-02)** — `/api/ops/today` (time + training), `/calendar` (projection), `/clients` + `/clients/{id}` (health), `/clients/{id}/account-manager`, `/exceptions` (the COO's list), `/ai/draft-tasks`, `/certifications`, `/meta`. Thin; the rules are `services/{today,calendar_view,client_health,operations,ai_draft}.py`. See §5 |

Adding a router? Register it in the tuple at [main.py:513](backend/app/main.py#L513).

### The task board holds TWO kinds of card

| | Sentinel row | Atrium-owned card |
|---|---|---|
| staffing | ONE lead (`assigned_to_id`) + **many supporters** (`task_supporters`, since 2026-08-06) | ONE lead + many support, as roster **emails** |
| id | an integer PK | the string `atrium:<client_key>:<task_id>` |
| stored in | Postgres `tasks` | that client's Atrium workspace JSON — **Atrium is the source of truth** |
| reaches the board via | `task_card` | `atrium_tasks.fetch_tasks()` → `as_board_card` (fail-soft: an Atrium outage just hides them) |
| who sees it | `task_perms.can_view` (employee/intern: what is assigned to them, their team's unclaimed queue, and — since 2026-08-14 — **every department they are in, read-only**; a person may be in more than one — see §5) | `task_perms.can_view_atrium` — **team lead and up** |

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

🔴 **It has THREE triggers, and "on boot" alone was not enough (2026-08-07).**

| Trigger | Notes |
|---|---|
| boot — `main._mirror_clients` | on a daemon thread since 2026-08-07, and fully swallowed: a client list one boot stale is a nuisance, a Sentinel that won't start is an outage. **Off the startup path** because startup handlers complete before uvicorn accepts a connection, so its 10s Atrium call was billed to every cold start |
| the **daily pass** — `services/daily.mirror_clients` | added 2026-08-07; runs before `task_recurring` so a workspace created today can still receive its recurrence on the same pass. 🔴 **Dormant in production today — see below** |
| **Sync now** — `POST /api/manage/clients/sync` | the button in the Manage → Clients strip, plus the route for a script. **This is the only trigger you can rely on right now** |

> 🟡 **`CRON_KEY` IS NOW SET, BUT `POST /api/cron/daily` STILL DOES NOT RUN UNATTENDED (2026-08-10).**
> Half of the old blocker is gone and half is a deliberate choice — read both before wiring anything.
>
> **What changed:** `deploy.ps1` now passes `CRON_KEY=sentinel-cron-key:latest` (it never did before,
> though the secret has existed since 2026-07-04 with the runtime SA already granted accessor). So
> `cron._authorize`'s header branch works, and a Scheduler job can finally authenticate.
>
> **What did NOT change:** the one Scheduler job that exists — `sentinel-daily` in `asia-southeast1`,
> 23:30 Asia/Manila — deliberately targets **`POST /api/cron/report`**, NOT `/daily`. The name is a
> historical accident; the description on the job says so. `/api/cron/report` regenerates the personal
> context report and nothing else.
>
> 🔴 **Repointing that job at `/api/cron/daily` is an OPERATIONAL decision, not a config tweak.** The
> daily pass has never once run unattended, so switching it on turns four dormant behaviours live at
> once, estate-wide and unattended: attendance day-summaries (which write `Absent` rows), **approval
> and overdue reminders that notify every affected staff member**, recurring retainer deliverables
> (WP 6.1) that mint real cards, and the client mirror. Each hook is correct and tested in isolation;
> none has ever fired on a schedule against live data with nobody watching. Turn them on
> deliberately, in daylight, with someone reading the result — not as a side effect of wanting the
> report on a timer.
>
> So the daily pass remains manual: the Super Admin button in `dashboard.js`, or a direct POST with
> `X-Cron-Key`.

🔴 **Why the daily pass exists, because it looks redundant and is not.** A client created in Atrium
reaches the New Task picker only when this sync runs, and until 2026-08-07 boot was its only automatic
trigger. That was survivable *only* because Cloud Run scaled to **zero**: any quiet spell ended in a
fresh boot, so a new client appeared on its own within ~15 minutes. Adding `--min-instances 1` the
same day removed those restarts — so "boot-only" silently became "once", and a client could stay
invisible here indefinitely. Observed live that afternoon: a client added minutes after a deploy was
still unpickable hours later, with a healthy `client mirror: created: 0` in the boot log and **no
error anywhere**. If you ever make the service restart-free in some new way, check this trigger list
again. 🔴 Neither automatic trigger passes `deactivate` — see above; a scheduled job is the worst
place to act on absence, because nobody is watching when it runs.

The read-only Manage pane surfaces `GET /api/manage/clients/sync-status`, whose `unlinked` list is the
one actionable thing there: those clients are invisible to the bridge, and the fix is in **Atrium**.
**Sync now** is the pane's only write, and it only ever creates and links.
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

🔴 **SUPPORT is resolved by the same ladder — it wasn't until 2026-08-06.** Only the lead went
through the resolver, so on ONE card the lead wore their photo and every supporter rendered grey
initials, including people who do have a photo in Sentinel (confirmed on the live board: "Weekly
blog + Newsletter posting", Rooming House Expert — lead `agustinnico228@gmail.com` resolves by name,
support `paulo@agoradatadriven.com` resolved to nobody). The resolver was never lead-specific; the
second caller was just missing. Now `_atrium_support` resolves each roster entry and the card
publishes **`support`** — the same field a Sentinel row publishes — so one renderer draws the faces
on both kinds of card. Two rules:

- **`atrium_tasks.support_pairs` is the ONE derivation** of "who supports this card", read by
  `as_board_card` and by the router that resolves them. Atrium sends `support_ids` and
  `support_names` in parallel and neither is guaranteed; a second copy of this pairing does not fail
  loudly, it puts one person's name under another person's face.
- 🔴 **A resolved supporter does NOT become a Sentinel `support_ids` entry.** By Employee groups
  lanes on that field and `mine` / "My work" comes from the resolved **lead**, while the Monitor
  (`task_analytics.atrium_workload`) counts a client card toward its lead. Filling it here would
  move client cards onto supporters' lanes and My work while the Monitor disagreed — the same
  three-surfaces-say-yours-and-one-says-no split this resolver was written to end. Widening support
  to those surfaces is a real decision: make it everywhere at once, not as a side effect.
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

**`team_lead`'s user-facing LABEL is "Department Head"** (owner decision 2026-09-02 — one
term everywhere; the hub docs' org chart says Department Head, and Sentinel now agrees). The
KEY stays `team_lead` in code, tests and this file; only labels, refusal messages and the
living docs use the new term.

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

### 🔴 There are now TWO kinds of permission here, and only one of them is a matrix (2026-08-17)

`backend/app/capabilities.py` is the registry; `services/permissions.py` resolves it; the Super
Admin edits it at **`/permissions`** (Admin → Permissions). Before it, "what exactly can an Account
Manager do?" existed only as ~41 `require_min_role`/`require_roles` sites across nine routers.

| | Decided from | Example | Lives in | Editable in the console? |
|---|---|---|---|---|
| **Surface access** | the role ALONE | "may open Payroll", "may approve leave" | `capabilities.py` | **yes** |
| **Object-scoped rules** | the role **and the row** | "an employee may edit a task *if assigned to it or it's in their team queue*" | `services/task_perms.py` | **the ROLE half only — see below** |

🔴 **Do not migrate `task_perms` into the capability registry.** There is no cell in a role ×
capability grid for "assigned only" — forcing it in either drops that nuance (handing every employee
edit rights over every colleague's card, the regression §5 documents) or turns a console a human is
meant to reason about into a rules engine nobody can read. **A capability that cannot be decided from
the role alone does not belong there.**

#### The task board: the role half of a predicate CAN be a capability (2026-08-18)

Seven `task_perms` predicates now ask `permissions.has_cap` while keeping their object test in code.
The four Atrium ones were always pure role tests. The interesting three are `can_reassign` /
`can_prioritize` / `can_review`, which were `_is_full(user) or _lead_may_act(user, task)` and
**collapse exactly** to `has_cap(...) and can_view(user, task)`:

```
  _is_full(u) or _lead_may_act(u, t)
= (role in FULL) or (role == team_lead and can_view(u, t))
= (role in FULL and can_view(u, t)) or (role == team_lead and can_view(u, t))   [1]
= role in (FULL | {team_lead}) and can_view(u, t)          # i.e. MANAGER_ROLES
```

🔴 **Step [1] is only legal because `FULL ⊆ VIEW_ALL_ROLES`**, which makes `can_view` unconditionally
True for AM/admin/super_admin. Remove a FULL role from `VIEW_ALL_ROLES` and those three predicates
silently NARROW. `tests/test_task_capabilities.py::test_the_collapse_premise_still_holds` pins it,
and `test_predicate_is_unchanged_for_every_role` re-implements each original body and compares, for
every role × card shape × in/out of department.

What it buys: the scope rides along with the grant. Giving an employee `tasks.review` lets them
approve work **they can already see** — their own cards and their department's queue — not the
estate. That is why these are safe to expose as checkboxes at all.

🔴 **`can_delete` deliberately does NOT collapse.** Delete is the only irreversible act and
`can_view` reaches a lead through branches as thin as "somebody named you on one step", so its scope
stays `_is_full(user) or _dept(user, task)`. Two more rules there: the **creator branch is checked
BEFORE the capability** (anyone may quick-add a card, so anyone must be able to undo that — gating it
would strand every employee's own mistakes), and a granted employee may tidy their *department*,
never everything they can see.

🔴 **Still not capabilities, and should not become them:** `can_view`, `can_edit`, `can_move`,
`can_tick_step`, `is_assigned`. These are decided by the ROW alone (assigned to me / my team's
unclaimed queue / my department read-only) and have no role half to lift out.

#### Per-PERSON exceptions layer on top (2026-08-18)

`models.UserCapability` + the console's **People** tab. Resolution is
**role defaults → role overrides (`role_capabilities`) → person (`user_capabilities`)**, person last
so it always wins. It exists so "Maria specifically may run payroll" does not require inventing a
role for one person.

- 🔴 **It is not a way around the invariants.** Every row is re-checked by `is_grantable` against
  **that person's role** at resolution time, so it cannot give a `viewer` a write, cannot touch a
  `locked` capability, and is inert for a Super Admin.
- 🔴 **A row survives a role change**, because the grant was made about the person. Demote them and
  a write they could no longer hold goes **inert** — and the People tab still LISTS it, marked
  inactive, because a permission that silently does nothing is exactly what somebody needs to see in
  order to delete it.
- 🔴 **`people.delete_person` calls `permissions.prune_orphans`.** Neither capability table has an
  FK (both document why), so nothing cleans these up automatically — and a row keyed by a recycled
  user id would hand a future person somebody else's permissions.
- `/api/auth/me` ships **`caps_for_user`**, never `caps_for(role)`. Shipping the role's set would
  hide features from somebody the API allows — the dead-button failure pointed the other way.

#### Reports: one capability per report

`capabilities.REPORT_CAPS` maps the `report` path segment to a capability, and
`reports._require_access` is now a dict lookup. Six capabilities rather than one `reports.view`
because the six already had six different answers — collapsing them would either leak the
payroll-adjacent ones to a team lead or take the overdue list off them. 🔴 **An unknown report name
is now a 404.** It used to fall through the access check and be handled by `_build` returning
nothing, so any report added later without a rule was world-readable; the default is closed.

#### Two UI/API mismatches closed

- `dashboard.is_admin` is now `has_cap(insights.view)`, not `role in ADMIN_ROLES`. Granting
  `insights.view` used to open `GET /api/insights` while the Overview block that renders it stayed
  hidden. The payload key is unchanged — `dashboard.js` reads it.
- `attendance.kiosk_guard`'s session branch is now `has_cap(attendance.kiosk)`, so the scanner can go
  to an office manager without making them a Super Admin. 🔴 The **kiosk-key branch stays first and
  untouched**: an unattended kiosk carries no session and must not depend on the capability table.
  It is still deliberately OPEN in non-production when no `KIOSK_KEY` is set.

**Every default is a mechanical translation of the guard it replaced** — `_at_least(X)` where the
code said `require_min_role(X)`, an explicit set where it said `require_roles(...)`.
`tests/test_permissions.py::test_default_matches_the_guard_it_replaced` re-derives all 24 from
`ROLE_RANK`, so a typo fails the suite rather than silently opening or closing an endpoint. Adding a
capability? Add its row to `_ORIGINAL_GATES` too.

**Three invariants (`capabilities.is_grantable`), re-checked at RESOLUTION time and not only at write
time** — so a hand-run `INSERT`, a restored backup or a future bug in the write path is *inert*
rather than obeyed:

1. **`super_admin` holds every capability, always, and its column is not editable.** The console is
   itself reached through a capability; a grid that can revoke it locks the last Super Admin out of
   the only page that could give it back.
2. **`locked` capabilities are editable by nobody** — `people.set_role`, `people.create`,
   `people.delete` (privilege escalation) and `permissions.manage` (the console's own).
3. **`viewer` can never hold a `write` capability**, the same rule its floor rank enforces for
   `require_min_role`. One checkbox would otherwise undo decision D8 above.

Two more things that are load-bearing:

- 🔴 **`routers/permissions.py` is deliberately NOT under `/api/manage`.** That console is gated by
  ONE capability (`manage.console`) which is grantable — so behind that gate, giving somebody the
  departments-and-leave-types screen would silently also give them the power to grant themselves
  everything else.
- 🔴 **`role_capabilities` stores DELTAS, never a snapshot.** An empty table means "exactly what the
  code ships with", which is what makes Reset a single `DELETE` — and what makes a capability added
  in a later deploy arrive with its coded default already applied to every role. A snapshot would
  freeze the roster as it stood the day somebody last opened the console, so every new capability
  would land silently denied to everybody.
- 🔴 **`has_cap(user, cap)` and `caps_for(role)` take NO session** — `resolved()` opens its own on a
  cache miss. That is what makes `task_perms` able to ask at all: its predicates are `(user, task)`,
  called from ~67 sites and from `serializers.task_card` once per card, and threading a `Session`
  through all of them to read a seven-row table would be both a huge diff and the per-card read
  §5's query budget forbids. A failed read falls back to the **coded defaults** and is not cached —
  denying everything would take the app down over a blip; allowing everything is unthinkable.
- 🟡 **The resolved matrix is cached per process (`PERMISSIONS_CACHE_SECONDS`, default 15).** Sentinel
  runs up to three instances, so a **revoke** takes up to that long to reach the other two. The
  console says so on screen; set it to `0` to resolve per request. The console's own read bypasses the
  cache — a permissions page that lies about its own state is worse than a slow one. `conftest.py`
  clears it around every test, or a granted capability leaks into the next test's 403 assertions.

**Use `require_cap` for anything reassignable; `require_min_role`/`require_roles` remain correct** for
a gate that is genuinely "this rung and up" and that nobody should be able to move (the attendance
`kiosk_guard`, the internal HMAC endpoints). A capability key that does not exist in the registry
answers **False**, so a typo in a guard CLOSES the endpoint rather than opening it.

The frontend gates on `S.hasCap("…")` and a nav entry's `cap:`, fed by `caps` on `/api/auth/me` —
never by re-deriving from `role`, which goes stale the moment a Super Admin moves a capability. It
stays a convenience: every endpoint behind it enforces its own `require_cap`.

### 🔴 `PATCH /api/people/{id}` was a privilege-escalation path until 2026-08-17

It was guarded by `require_min_role("admin")` and applied every field through a generic `setattr`
loop — so `role` was written exactly like `phone`, and **any Admin could PATCH themselves to
`super_admin`**, taking payroll, the Manage console and the delete button with them. The Manage UI is
Super-Admin-only, but that is a frontend gate on an open API (§7: "Enforce a permission only in the
UI"). `people._guard_role_write` now imposes two separate refusals:

- **changing a role needs `people.set_role`** — locked, so the console cannot hand it out. Gated on
  the role actually *changing*, not on being present in the payload: the Manage form submits every
  field on every save, so gating on presence would 403 an Admin editing a phone number.
- **the LAST active Super Admin cannot be demoted or deactivated**, by anybody including themselves.
  `main.py`'s startup safeguard would recreate a platform owner eventually, but on `--min-instances 1`
  that next boot may be days away — "nobody can log in until someone redeploys" is not a recovery
  story.

Pinned by `tests/test_permissions.py` (§5 and §6 there, weighted toward the refusals).

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
straight on the dashboard, minting a normal session on the way ([main.py:582](backend/app/main.py#L582)).

### 🔴 Sentinel answers on TWO hosts and they behave differently — that is where lockouts come from

| Host | `sso_enabled` | The only way in |
|---|---|---|
| `sentinel.agoradatadriven.com` (canonical) | **true** | the portal. `/login` redirects there before showing a form |
| `sentinel-…run.app` | **false** | the password form — `ag_sso` is scoped to `.agoradatadriven.com`, so on `*.run.app` the cookie is never sent and SSO is silently inert (`auth._sso_reachable`, by design) |

So which URL somebody bookmarked decided whether single sign-on worked for them, and an **SSO-only
account** (`password_hash` NULL — what the platform-owner bootstrap and a blank password field both
create) reaching the run.app host had **no door at all**. `CANONICAL_HOST` was written for exactly
this and `deploy.ps1` never passed it; it does now (**2026-08-11**), so browsers on the run.app host
are forwarded to the canonical one. **Keep the two in step**: `GOOGLE_REDIRECT_URI` must name the
same host, or the `g_oauth_state` cookie is set on one host and checked on the other and every Google
sign-in fails its state test.

⚠️ **A service worker cache is per ORIGIN**, so anything bookmarked on the run.app host — the
attendance **kiosk** tablet above all — lands on a different origin after this and has to re-prime its
cache. Open the kiosk **once while online** after deploying, or its offline boot has nothing to boot
from. The run.app URL still answers everything else (the redirect is GET + `text/html` only), so it
remains a working fallback for curl, probes and the health check.

### 🔴 The portal ↔ Sentinel login LOOP, and the three things that now stop it (2026-08-11)

The report was "sometimes I'm stuck on the login page and can't get in". It was a real infinite loop,
and the reason it came and went is that it needs `ag_sso` to have expired while the portal still
thinks you are signed in:

```
/dashboard → /api/auth/me 401 → /login → POST /api/auth/sso 401 → portal/login?next=…
          → portal is authed, redirects back → 401 → /login → portal → … forever
```

`ag_sso` has a **12h** TTL and is minted **only** by a real portal login; the portal's own Flask
session is a browser-session cookie that Chrome's session-restore keeps alive for days. So the portal
kept answering "you're already signed in, off you go" with a redirect and **no cookie**, and Sentinel
kept bouncing back for one. `location.replace` meant the Back button could not escape either. Three
independent fixes, and **none of them is redundant**:

| # | Fix | Why it alone is not enough |
|---|---|---|
| 1 | **the portal re-mints `ag_sso`** on that already-authed redirect (atrium `main.login()`) | it is the actual bug, but it lives in the OTHER repo — Sentinel can ship without it |
| 2 | **`?next=` points at `/login`, not `/dashboard`** ([login.js](frontend/static/js/login.js)) | only `/login` mints a Sentinel session from the portal cookie; `/dashboard` merely authenticates per request, so the whole company rode the 12h cookie and came back every time it expired |
| 3 | **the one-bounce guard** — a bounce that follows a bounce within 20s is suppressed and the password form is shown with an explanation | turns any future variant (an unset `SSO_SECRET`, a portal outage, a third app in the chain) into one wasted round trip instead of a lockout |

The guard is a **timestamp, not a flag**, so a legitimate bounce hours later in the same tab still
works. The manual escape hatch **`/login?local=1`** still exists and still skips the SSO branch.

### 🔴 The login form works with NO JavaScript — `POST /login` is the floor

The form posts `/api/auth/login` from `login.js` normally. It also carries `method="post"
action="/login"` and `name=` on both inputs, because when that script does not run the button used to
be wired to nothing: the click silently re-GET'd `/login` with the fields cleared, so the page looked
perfect and could not admit anyone — no error on screen, no failed request in the logs. (The same
lesson Atrium learned when its quick-add composer died inside another block's guard.)

- **Don't remove the `name=` attributes or the `action`** — they ARE the fallback.
- Its CSRF defence is an **Origin/Referer check** (`main._is_same_origin`), not a token: the page is
  a static file and the CSP forbids inline script, so there is nowhere to render a token into. It
  **fails open when neither header is present**, deliberately — this route is for degraded
  conditions. `/login` is therefore in `_CSRF_EXEMPT_PREFIXES`, which is also what stops a **stale**
  session cookie from 403-ing the one path that recovers a broken session.
- It shares `auth.authenticate` with the API, so a second door can never accept what the first
  refuses. Pinned by `tests/test_login_fallback.py`.

### 🟡 "Invalid email or password" was a lie for accounts with no password

`password_hash` is nullable **on purpose** (SSO-only accounts; People → Add Employee leaves the
password optional). Those users have nothing to get wrong, so the generic message sent them round the
retry loop until the rate limiter stopped them. `auth.login_failure_detail` now names that one state
and tells them to use the portal. It stops there: a **wrong** password and a **deactivated** account
both stay generic. The enumeration trade-off is deliberate — every employee can already open the
staff directory.

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

Existing migrations are in `backend/alembic/versions/` — **29 revisions** as of 2026-08-06
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

### 🟡 Assets are CONTENT-VERSIONED and compressed — what that changes for you (2026-08-13)

The section above made staleness impossible by revalidating **every asset on every navigation**.
That is a conditional round trip per file, forever — `/tasks` alone is `app.js` + `taskboard.js` +
`styles.css` ≈ **356 kb**, and the frontend has no build step, so those are real source files.

| Layer | What it does |
|---|---|
| [`assets.py`](backend/app/assets.py) | hashes every `static/**/*.{js,css}` at import into one **build id**, and rewrites each page shell's `src=`/`href=` to `/static/js/app.js?v=<id>` |
| `_VersionedStaticFiles` ([main.py](backend/app/main.py)) | a URL carrying the **current** build id is answered `public, max-age=31536000, immutable` — so the browser serves it with **no request at all**, and the SW's network-first `fetch()` is satisfied from that same HTTP cache |
| `ConditionalGZipMiddleware` ([middleware.py](backend/app/middleware.py)) | gzip on everything else — `/tasks` drops **356 kb → 110 kb** (69%), and the board's JSON with it |

Four things that are load-bearing:

- 🔴 **The page shell itself stays `no-cache`.** It is the document that hands out the immutable
  URLs; cache it and a deploy's new URLs never reach anyone. `_page` returns a `Response` (rewritten
  in memory, memoized per file), not a `FileResponse`.
- 🔴 **Only the CURRENT build id earns `immutable`.** A stale `?v=` from a page held across a deploy
  gets ordinary `no-cache`, because the bytes on disk are no longer the ones that URL named.
- 🔴 **An UNVERSIONED request is completely unchanged** (`no-cache`). That is what keeps `sw.js`'s
  precache list, old bookmarks and anything not rewritten behaving exactly as before.
- 🔴 **The SSE streams are excluded from compression by PATH** (`_NO_COMPRESS_PREFIXES`). gzip's
  deflate stage buffers, so a 40-byte SSE frame emits **zero bytes** — the live board would silently
  stop being live, and no header fixes that. Adding a new streaming endpoint? Add its prefix.

`sw.js`'s offline fallback is `caches.match(req, { ignoreSearch: true })` **because** of this: shells
now ask for `kiosk.js?v=<id>` while `CORE` precaches the bare `kiosk.js`, and an exact match would
miss — the kiosk would fail to boot offline. Online behaviour is unchanged (still network-first).
The build id is derived from **content**, so a deploy that doesn't touch an asset keeps its URL and
everyone's cached copy. All of it is pinned by `tests/test_asset_delivery.py`.

### 🔴 A task has ONE lead and MANY supporters — support widens "assigned" and nothing else

`models.TaskSupporter`, 2026-08-06. The asymmetry it closes: an **Atrium client card has carried Lead
+ many Support since the bridge was built**, while a Sentinel row had exactly one ownership field
(`assigned_to_id`). Two kinds of card sit on the same board (§2) and only one of them could say who
was helping. So the only way to put a second name on a Sentinel task was to **invent a checklist step
for them** — and the progress bar is `done steps / total steps`, which means *staffing a card changed
how finished it looked*. Adding a helper made the work read as less complete.

🔴 **`assigned_user_ids` is the ONLY place support joins the model.** That one function already
answered "who is this work on?" for the board, `mine`, My work, By Employee and the Monitor, so all
five inherited support at once. Adding it to any of them individually would have been the second copy
of a rule whose first duplication caused the July 2026 "nothing on you right now" bug — see the
`is_assigned` section above. If you add a sixth surface, ask that function; do not re-derive.

| Support DOES get | Support does NOT get |
|---|---|
| the card on their board (`can_view` → `is_assigned`), and edit/move with it | accountability — `assigned_to_id` stays the one neck |
| counted in `mine`, "My work", their By Employee lane, their Monitor row | the lead's right to tick **somebody else's** step (`can_tick_step`) |
| a `supporting` flag on the card so a surface can say which hat they wear | claiming the card out of its team's triage queue |
| `support_ids` in the staff mirror Atrium's console pulls | anything in the CLIENT projection — `task_bridge.SAFE` is six fields and staffing is not one |

Five rules, each of which is a decision somebody will otherwise re-lit igate:

- 🔴 **Naming somebody is DELEGATION**, guarded where the field is WRITTEN
  (`tasks._support_delegates`), never in the UI. This board has shipped that exact hole twice —
  `maintasks[].assignee_id` (2026-08-03) and comparing owner SETS instead of slots (2026-08-05) — both
  times because a new way to put a name on a card walked past the check. The diff is the **symmetric
  difference minus the actor**, so "add me and drop a colleague" is still refused.
- **Adding or removing YOURSELF is always allowed**, mirroring self-assignment on a step — otherwise
  the field is unusable by the people who pick work up. It is **not a way in**: `update_task` checks
  `can_edit` before it reads any field, so you can only join a card already on your board. Without
  that, support would be a hole straight through `can_view`.
- 🔴 **The team triage queue still tests `assigned_to_id` alone.** A card with supporters and no lead
  stays in the queue — support is help, not ownership, and the alternative is work with helpers but no
  owner quietly leaving the one list the team watches. Same reasoning for send-back and bulk-claim.
- **`?assignee_id=` stays a lead-only FIELD filter.** "What is on Jerome?" is a precise question;
  "who is on this card" is a different one. Widening one must never silently widen the other.
- **`support_ids: None` means "not sent"; `[]` means "remove everyone".** A plain list default on the
  schema would make every unrelated PATCH silently clear the support list.

Two consequences that look like bugs and are not: **By Employee lane counts add up to more than the
number of cards** (a supported card appears in the lead's lane and each supporter's, marked
"supporting"), which is the same shared-work property the Monitor legend already explains; and the
Monitor counts `supporting` **separately from `stepped`**, because support used to fall into that
bucket and the UI renders it as "N as steps" — describing somebody as owning steps they may not own.

Covered by `tests/test_task_support.py` (22 cases, weighted toward the refusals).

### 🟡 Live reload is local-only, and the localhost test in `app.js` is one of the gates

Added 2026-08-06 (`routers/dev.py`, `frontend/static/js/devreload.js`, §1). It exists because the
frontend has **no build step** — a deliberate choice (§8) whose cost was that nothing watched
`frontend/`, so every CSS tweak needed a manual refresh that the service worker could then answer
from cache. It is not a bundler and does not introduce one: the server polls mtimes, the browser
listens on SSE, and a `.css` save is hot-swapped in place rather than reloaded.

🔴 **THREE INDEPENDENT GATES keep it out of production. Don't collapse them to one.**

| # | Gate | Where |
|---|---|---|
| 1 | `settings.dev_reload_active` is False whenever `environment == "production"`, and there is **no `allow_dev_reload_in_prod`** (deliberately unlike `dev_login_enabled`) | `config.py` |
| 2 | the client script is only ever loaded when `location.hostname` is localhost — **a Cloud Run host can never satisfy it**, so a misconfigured deploy still serves a page that never asks | `app.js` |
| 3 | the router is registered **unconditionally** and every handler re-checks gate 1 **per request** | `routers/dev.py` |

Gate 3 is the counter-intuitive one: a conditional `include_router` would make the route's existence
depend on a setting's value at import time, which is how an endpoint ends up "gone" in one worker and
live in another. It answers **404, not 403** — a 403 confirms the endpoint exists.

Do **not** widen gate 2 to a LAN IP or a hostname pattern. Its whole value is that it cannot be
satisfied from anywhere but the machine doing the editing.

Two more things worth knowing before changing it:

- **The service worker is NOT registered on localhost** (`app.js`), and `devreload.js` unregisters any
  worker left over from an earlier session. This is required, not tidiness: `sw.js` caches CSS/JS and
  falls back to that cache, so a reload could serve the file you just edited *from before you edited
  it* — the local face of the "deployed but the browser shows the old version" bug above, with no
  `CACHE` bump available to clear it because nobody edits `sw.js` on every save.
- 🔴 **`/kiosk` OPTS OUT and behaves exactly as it does in production**, service worker and all. The
  kiosk's defining requirement is that it **boots offline from cache**, so it is the one page whose
  caching has to be exercisable locally — unregistering its worker to make styling faster would mean
  that path is only ever tested in production, on a tablet, on the day it matters.
- The stream carries a **per-process boot id**, which is what makes a mixed Python+frontend save work.
  A reconnecting stream rebuilds its baseline from disk, so a frontend file saved while uvicorn was
  down is already in the new baseline and compares equal forever — its change event can never arrive.
  Keying the reload off the restart instead means it fires for a reason that is still observable.

Covered by `tests/test_dev_reload.py` (17 cases, weighted toward the gates). 🔴 Those tests drive the
SSE generator **directly**, not through `TestClient`: `request.is_disconnected()` never becomes True
under TestClient's portal, so `client.stream()` on the 200 path hangs the suite forever rather than
failing. The 404 paths are safe to test over HTTP because they raise before streaming starts.

### 🔴 A PERSON MAY BELONG TO SEVERAL DEPARTMENTS — `users.team_id` is only their PRIMARY one (2026-08-14)

`models.UserTeam` + **`services/teams.py`**, which is the one place the union is derived. Before it,
nine files compared one integer to another (`something.team_id == user.team_id`), which silently
asserted that everybody belongs to exactly one department. People here do not: a designer who also
sits with Acquisition, a lead covering a second team while it has no lead of its own. Those people
saw one department's board, were missing from the other's rollups, and were never notified about its
work — **all invisibly**, because a card that is not on your board and a notification that was never
sent both look exactly like a quiet day.

🔴 **`users.team_id` IS KEPT and still answers a different question.** Two questions were sharing one
column, and only one of them can take a set:

| question | ask | why it cannot be a set |
|---|---|---|
| "which department is this person **OF**?" | `user.team_id` | `Team.shift_template_id` decides whether a punch is late; payroll needs one row; the People column has room for one name |
| "whose work may they **take part in**?" | `services/teams.team_ids(user)` | — |

Everything that scopes a board, a rollup or a notification asks that helper: `task_perms._dept` /
`_team_queue` / `_leads_team`, `tasks.employee_summary` + `throughput`, `work_digest`,
`team_growth`, `development.can_view`, `notifications.notify_managers`, the People directory filter,
attendance summaries, the gym rollup and every `?team_id=` report filter. **Do not re-derive the
union** — a second copy of this rule is how `is_assigned` and the Overview's "my work" strip came to
disagree in July 2026.

- 🔴 **Membership widens what somebody SEES and nothing else.** An extra department is not a
  promotion: an employee still cannot edit a colleague's card in it (`can_edit` never reads `_dept`),
  and `can_delete` still refuses a department they are not in. A team lead *does* lead every
  department they are in — the role is a property of the person, and `_leads_team` is the set test.
- 🔴 **An empty set matches NOTHING, deliberately.** The comparison this replaced was `None == None`,
  which quietly grouped every department-less person into one pseudo-team — a lead with no department
  could see all of them. A lead with no department now monitors only themselves.
- 🔴 **`team_ids: None` means "not sent"; `[]` means "remove them all"** — the same contract as
  `support_ids`, for the same reason: a plain `[]` default would make every unrelated PATCH (a phone
  number, a shift, a password reset) quietly empty somebody's departments and shrink their board.
  `services/teams.set_extra_teams` also drops the primary from the extras (one department in two
  places makes un-ticking it in one of them do nothing) and ignores unknown ids rather than 400-ing
  a form built from a department list that has since changed.
- **Deleting a department deletes its memberships** (`manage.delete_team`). Those rows carry an FK;
  orphaned on SQLite they survive and `team_ids` keeps handing out a department that no longer exists.
- **The set ships as `team_ids` on `user_full` only** (`/api/auth/me`, `/api/people`) — never on
  `user_public`, which is serialized once per card for every assignee and supporter on the board.
  Primary first, so a surface with room for one name prints the right one.
- Set it in **Manage → Employees → "Also works with"**. `frontend/README.md` has the filter-bar half.

Pinned by `tests/test_multi_department.py`, weighted toward the refusals and the write contract.

### 🔴 A TEAM LEAD'S POWERS FOLLOW WHAT THEY CAN SEE — not the team field (2026-08-14)

Reported as two bugs ("Team Lead can't assign", "Team Lead can't approve"); it was **one predicate**.
`can_reassign` / `can_review` / `can_prioritize` all asked `_leads_team`
(`task.assigned_team_id == user.team_id`), while `can_view` grants a lead sight through **four**
branches — so the board routinely handed a lead a card with every control dead:

| Reached the lead via | Why `_leads_team` failed |
|---|---|
| `is_assigned` | work handed to them with **Department left blank** — `assigned_team_id is None` |
| `_unowned_client_work` | an **adopted Atrium card**, which that predicate shows leads *precisely because* it has no team |
| `_created` | a card the lead raised **for another department** |
| any of them | the lead's own **`users.team_id` was never set** — this killed the whole role, everywhere, at once |

🔴 **The failure was invisible.** `taskboard.js` mirrors these predicates, so the assignee picker
rendered `disabled` and Approve was **never drawn**. Nobody saw a 403; they saw a missing feature.
That is why the frontend mirror is now just `isLead` — the board only ever receives cards `can_view`
already passed, so there is no client-side re-derivation left to drift.

`task_perms._lead_may_act` is the one definition. Two things deliberately did **not** move:

- **`can_delete` still asks `_leads_team`.** Delete is the only irreversible act here, and `can_view`
  reaches a lead through branches as thin as "somebody named you on one step".
- **`create_task.may_delegate` was relaxed to match** (it had been narrowed to the lead's own
  department on 2026-08-05). It was the *second half of the same report*: a lead who filled in the
  form without touching Department got **403 "Only a team lead or manager can assign a task to
  somebody else"** — a sentence naming their own role as the reason. 🔴 **Keep the two doors in step**:
  whatever `_lead_may_act` allows on an existing card, create must allow on a new one.

Pinned by `tests/test_task_assignment.py` (one case per way in, each asserted **visible** before it
is asserted actionable — the obvious-looking "any card with no department" scenario is *not* one of
them, because such a card is invisible to everyone below AM and never had a dead button).

### 🔴 An employee SEES their whole department and may WRITE to almost none of it (2026-08-14)

`can_view` gained a `_dept` branch, so a team is no longer opaque to its own members. (`_dept` is a
SET test — a person may be in several departments; see the section above.) **This is the
one place `can_edit` and `can_view` genuinely diverge in shape, and it is load-bearing:**

| | employee / intern |
|---|---|
| `can_view` | `is_assigned` **or** `_team_queue` **or** `_dept` |
| `can_edit` | `is_assigned` **or** `_team_queue` — **never `_dept`** |

Had `can_edit` stayed an alias of `can_view`, that single read would have handed every employee edit
and move rights over every colleague's card — a far bigger change arriving as a side effect of a
smaller one. The July 2026 regression this seems to reverse was about **accountability** ("an intern's
board showed seven cards, none of them theirs"), not secrecy; that half is now answered by `mine` and
by the board defaulting to the narrow scope.

- **`serializers.task_card` publishes `can_edit`** (viewer-relative, in the `mine` dict, absent when
  no viewer). Required, not decorative: a visible-but-read-only card must not render draggable and
  then 403 on drop. `taskboard.js` marks it `.readonly`, `draggable="false"`, no move select, no bulk
  checkbox — it still opens, because reading a colleague's card is the point.
- **The board's scope switch (`#scope-seg`) is rendered for everyone below AM**, with per-role tabs
  and a per-role default that reproduces that role's old board exactly — an employee opens on **On
  me**, a team lead on **Everything**. A lead gets no "On me" tab, because the attention pills on the
  same bar already carry **on you**. The whole role-shaped filter bar (which pickers each role gets,
  and why they are grouped rather than trimmed) is in [frontend/README.md](frontend/README.md).
- 🔴 **THE AI COACH INHERITED THIS, AND THAT IS INTENDED.** `services/work_digest` filters on
  `can_view` *by design* — its stated failure mode is the coach denying work the person can see on
  their own screen — so an employee's coach can now discuss their department. It is what finally makes
  "who on my team is buried?", quoted in that module's own docstring, answerable. The card lands in
  `board.others` (the cappable, truncation-declaring bucket), **never in `mine`**, so the coach still
  never briefs somebody as if a colleague's card were theirs. Pinned by `tests/test_work_digest.py`.
  Anything else that filters on `can_view` inherits this too — check before assuming it is a leak.

### 🟡 A service template can be applied to an EXISTING task (2026-08-14)

`POST /api/tasks/{id}/apply-template` (`{service_key, mode: "append"|"replace"}`). Templates could
only be picked at **create** time, so the commonest card on this board — a quick-added title, which
§3 of the task-placement guidelines says is the *right* way to log work that comes up during the day —
could never be given a breakdown without retyping every phase.

- Guarded by **`can_edit`**, matching the existing rule that editing the breakdown is editing the work.
- 🔴 **`mode` has no default.** `replace` discards every tick and step owner; a wrong guess is
  unrecoverable, so the caller must say which they mean (the drawer skips the question only when the
  breakdown is empty and the two modes are identical).
- 🔴 **It is not a delegation hole only because recipes carry no owners.** If a template ever grows
  default assignees, this route needs `maintasks.foreign_owner_changes` before it ships —
  `tests/test_task_templates.py` fails loudly if that day comes.

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
| an **Atrium** card | `atrium_tasks.as_board_card(..., viewer_id=user.id)` → `mine` from the **resolved owner** (`services/atrium_identity`). No `my_slots`: an Atrium breakdown has no Sentinel step owners, so a `0` would make the "N steps on you" pill lie |

🔴 **The Atrium half was missing until 2026-08-06, and a missing key is falsy.** Client cards carried
no `mine`, so the board's **My work** button dropped every one of them. That was correct while an
Atrium owner was only ever a roster email — and wrong from the day `atrium_identity` began resolving
that email to a Sentinel user, because from then on the SAME resolved owner put the card in that
person's **By Employee** lane, counted it toward them on the **Monitor**, and printed their photo on
it. Three surfaces said "yours" and one button said "not yours". Whenever a new surface answers this
question, it has to answer it for **both kinds of card** (§2, "The task board holds TWO kinds of
card") or it will disagree with the three that already do. Pinned by `tests/test_atrium_identity.py`.

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

### 🔴 The board's column width is a VARIABLE, and the Monitor's `<td>`s are not flex containers

Two unrelated layout bugs found together on 2026-08-14, both of which had been there from the start
and both of which read to a user as "the UI is broken".

**1. `.col` is `flex: 0 0 var(--col-w)`, and `--col-w` is a `clamp()`.** The width was a hardcoded
`288px` with **no responsive rule for the kanban anywhere** — the `@media` blocks at 900/640/480px
touch `.app`, `.tabs`, `.kpis`, `.grid` and never `.board`. Do this arithmetic before changing either
number:

| | |
|---|---|
| needed | 5 statuses × 288px + 4 × 14px gap = **1496px** |
| given | `min(1400px, viewport − 248px sidebar) − 52px` of `.content` padding |
| at a **1280px** viewport (a 1920×1080 laptop at Windows' **150% display scaling** — the common case on this estate) | **≈980px = 3.2 columns** |

So two thirds of the work sat off-screen and every card looked oversized, with nothing having changed
in the CSS — which is exactly how it gets reported ("the columns suddenly got huge"). The clamp keeps
the roomy 288px wherever there is room and gives width up only as the viewport takes it. **232px is
not a guess** — it is the width the By Employee lanes have shipped at since they were written.

- 🔴 **The `0` in the middle of `flex: 0 0 var(--col-w)` is flex-SHRINK and stays `0`.** The column
  scrolls; cards never squash. Same rule as `.col-list > .tcard { flex: 0 0 auto }` — see the
  comment on it in `taskboard.js`, which explains what squashing does to a card's footer.
- **`.dense` is a per-person preference** (`localStorage`, `sentinel.tb.density`), toggled from the
  **More** menu because that toolbar was deliberately cut from fourteen controls to six. It narrows
  the column and tightens padding **only** — font sizes are untouched, so compact is denser, never
  harder to read.

**2. 🔴 `display: flex` was on a `<td>` — in TWO tables.** `.mon-tbl .who` and `.tg-tbl .who`. A
table cell whose `display` changes stops being a table-cell, so the browser wraps it in an
**anonymous** cell: the `td`'s own `padding` and `border-bottom` then paint on the flex box instead of
on the row. Visible result was a row divider that stopped dead at the Load column and a name block
sitting off the numbers' baseline — a table that looks broken with nothing wrong in the data. The flex
belongs on a `div.who-in` **inside** the cell; both markups (`taskboard.js`, `teamgrowth.js`) wrap.

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
| `load_band` | open work **vs the cohort's own median** | Never absolute. Suppressed entirely when the median is < 2 (there, "double the median" is one card), and `overdue >= 3` forces `heavy` so a small-but-late pile isn't rendered `light`. 🔴 **The median is taken over the people who HAVE open work** — see below |

🔴 **The Load column was blank for the whole company, permanently (fixed 2026-08-14).** The median
was taken over every row, idle ones included — so on the normal shape of this board (~40 open cards
concentrated on four names out of a roster of fifteen) it was dragged to 0 or 1, the `med < 2` guard
fired for **every** row, and the Monitor's one judgement column showed an em dash for everybody. The
relative principle is unchanged; the **cohort** was wrong. A person with nothing open is still banded
(`light`, which is simply true of them) — they just no longer get a vote on where the middle is. The
guard itself is kept and now means what it says. Two rules that came with it:

- **A withheld judgement has to say so.** `bandPill` renders a *titled* dash explaining that the
  median is under two cards. A bare `—` in a column that is never populated is indistinguishable from
  a broken column, which is how this survived so long.
- 🔴 **The workload bar's LENGTH is amount; its COLOURS are mix.** The segments carry `flex:<n>` —
  which is flex-*grow* — so inside a flex bar they only ever divide up whatever width the bar is
  given, and the bar filled its cell unconditionally: **one open card and twenty-five drew the same
  length**. Three teammates rendered as three identical full-width bars in a column headed
  "Workload". There is a `.wl-track` (the cell) and a `.wl-bar` (`width: var(--wl)`, this person's
  open work over the busiest plate in the cohort on screen) now, and the legend states both halves.
  Scaled against the **cohort on screen**, matching `load_band` — a comparison must be about the
  people it appears to be about.

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
here would be the §2.4h bug wearing a new hat. The Monitor's **legend** is what makes the UI *say*
that; without it, somebody who delivers mostly client work looks like they never ship anything.

🔴 **`client_cards` counts a person's OPEN client cards, not all of them (2026-08-06).** It was
`len(rows)` — every card the person leads, finished ones included — while the UI renders it as a
sub-line **under the Open count**, beside `stepped` and `supporting`, both of which are open-scoped.
So it could exceed the number it appears to break down: a live row read **"8 open · 19 client"**,
which is not a fact about anything, and it read as a count of *clients* (there are 8) rather than of
cards. An Atrium card genuinely does reach a done status — the rollup maps Atrium's `completed` stage
through `task_config.status_for_stage` — so this was not a theoretical case. Two rules:

- **Both call sites scope it the same way**, because two surfaces showing one number differently is
  the same class of bug: `routers/tasks.py` (the Monitor) and `services/work_digest.py` (the Coach,
  which prints it next to `open_total`).
- **Any new sub-line under Open must be open-scoped too.** The cell is a breakdown of one number;
  a total placed in it is wrong however it is labelled.

Pinned by `test_client_cards_counts_only_the_OPEN_ones`.

Two rules if you extend this:

- **The band is relative and the UI says so** (`.mon-legend`). Do not restate it anywhere as
  "overloaded" — the data cannot support that word, and the moment a surface implies hours, someone
  will staff against it.
- **A band is computed across the rows the CALLER can see**, so a team lead is compared against their
  own team. The cohort on screen must be the cohort the comparison claims to be about.

Covered by `tests/test_task_analytics.py`.

### 🔴 `campaign` is a grouping KEY, and `campaignOf` is the only thing allowed to read it

2026-08-11, driven by the **Sentinel task-placement guidelines** (the operator doc for who files what
and how a task is named). Full record + the table of what changed:
[docs/TASKBOARD_REBUILD.md](docs/TASKBOARD_REBUILD.md) §7a.

Two things about this field will otherwise be re-broken:

- 🔴 **Never read `t.campaign` in the frontend — ask `campaignOf(t)`.** Every task created before
  2026-08-04 really does have `campaign == title` (one input used to write both, §7), and those rows
  were **deliberately never backfilled**. `campaignOf` returns `""` for them, which is what stops a
  legacy card printing its own name twice and stops the filter offering one bogus campaign per legacy
  task.
- 🔴 **That duplicate test COMPARES normalised text and RETURNS the original (2026-08-14).** It was
  an exact string compare, and a near miss defeated it outright: the live board held the title
  *"RHE Rooming House Extension"* against the campaign *"RHE Rooming HouseExtension"* — **one absent
  space** — so the card printed its own name on both lines. That was not just ugly. `.t-client` and
  `.t-camp` are `white-space: nowrap`, so the doubled line became the widest unbreakable content in
  the column and **widened the whole column** (see the `.col` note above: a flex item's automatic
  minimum beats its basis). One stray keystroke in a campaign name reshaped the board.
  Whitespace is stripped **entirely**, not collapsed — the difference was a *missing* space, so
  `\s+ → " "` would not have caught it — and case is folded with it. 🔴 **That is the whole
  normalisation, deliberately**: anything fuzzier starts suppressing campaigns that legitimately
  resemble their title, and a grouping key you cannot see is a filter you cannot trust — strictly
  worse than the duplicate it hides. Four surfaces read it — the card, the search, the filter's option list, the drawer — through
  that one function, because this is precisely the shape of duplication that made the card and the
  drawer disagree about an Atrium owner (§2). **The API still reports the duplicate honestly**; the
  suppression is a display rule, so it stays reversible and no data is rewritten.
- 🔴 **The field is offered on EVERY task, and re-hiding it breaks §4 of those guidelines.** It used to
  appear only when `content_type == "Campaign"` — i.e. only for the one campaign-shaped service — which
  made it unreachable for exactly the cards that need it: work raised *after* a campaign launches is
  deliberately a separate one-line task with no template and no campaign content type. So grouping
  could only ever cover campaign-BUILD cards, of which there is one per campaign. `isCampaignType` and
  `syncCampaign` were deleted with the condition.

Two smaller rules that go with it: the filter (`#f-campaign`) is **client-side and deliberately not a
member of `filters`** — everything in that object is sent to the server by `load()`, and these values
are just whatever the fetched cards carry; and the form offers a **`<datalist>`** of existing campaign
names, because a grouping key compared with `===` drifts silently the first time somebody retypes it.

Both card mappers publish the field (`serializers.task_card`, `atrium_tasks.as_board_card`) and
**neither DETAIL mapper re-derives it** — the drawers build on the card mappers. Pinned by
`tests/test_task_campaign.py`.

### 🟡 `Task.origin` — planned ahead vs added during the day, and why it may be wrong

2026-08-11. `Task.origin` is `planned` | `added` | **NULL**, classified once at create by
`services/task_origin.classify` and never a form field on create. It exists because the
task-placement guidelines split the board's work in two (§1 the Team Lead plans ahead, §3 the worker
adds what comes up) and stake a claim on it — "so Sentinel accurately reflects the actual work
completed during the day" — which nothing here could answer: every task looked equally planned, so a
team's reactive load was invisible. Surfaced as the Monitor's **`added`** sub-line under Open, and as
the drawer's **Raised** row.

| Rule | Why |
|---|---|
| The rule is **"may they plan"**, not "did they delegate" | An employee may route a card to a department without owning it (D10) and that *looks* like delegation. It is §3's "a new task came up", filed by whoever it came up in front of — keying off delegation files every one of those as planned |
| A planner raising their **own** work is `added` | §1 is about placing work FOR a worker |
| 🔴 **NULL stays NULL** | Every task predating the column is genuinely unclassified. A `DEFAULT 'planned'` would assert that about thousands of rows, and the migration + `_ensure_columns` both deliberately omit one. Unknown counts toward **neither** side, so **Open − Added is not "planned"** — the Monitor legend says so |
| 🔴 **Stored, never re-derived** | The creator's role changes on promotion and `assigned_to_id` changes on the first reassignment, so a read-time rule would silently re-answer for tasks that never moved |
| Correcting it is **`can_reassign`** | It feeds the reactive-load number; leaving it to whoever can *edit* lets anyone rewrite how much unplanned work their team absorbed. **Dropped, not 403'd** — no UI offers it to them, so a request carrying it is a script, not a lost edit |
| An **Atrium card** is `origin: None`, present not absent | Its answer comes from a *Sentinel* creator's authority to plan, and it has none. Present-and-None because a missing key is falsy — that is how `mine` answered "not yours" for every client card until 2026-08-06 |

🔴 **The derivation is known to be wrong in one case, and that is why it is correctable.** An account
manager logging a client's urgent 4pm request and assigning it out is doing §3's job through §1's
motion, and this rule answers `planned`. The only signals that would catch it are clock-based, and each
is wrong in the opposite direction (a lead planning tomorrow's build at 4pm today would read as
`added`). Two fuzzy signals do not make a sharp one — so it takes the rule the doc states and lets a
manager fix the exceptions. **Do not "improve" this with a time heuristic** without deciding what
happens to the lead planning tomorrow's work this afternoon.

Pinned by `tests/test_task_origin.py`. Migration `a3f7c2e9d4b6` (existence-guarded) **and**
`main._ensure_columns` — the second is the path it takes to production.

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

**Its contents were redesigned on 2026-08-06** (with the card — see
[frontend/README.md](frontend/README.md), "the quiet card"): kicker + name → **ONE notice**, the
worst true thing, on the same ladder the card's flag uses → **who is on it** → **four facts** →
record left, **Work / Comments / Activity tabs** right. Three things not to undo: the panes are
toggled with `[hidden]` and **never re-rendered** (the breakdown re-wires itself after every save,
and the comment box may hold half a sentence); **nothing is printed twice** — the field list carries
only what the facts strip does not; and the footer's **Mark complete** resolves its target column by
STAGE (`isDoneStatus`), never by the renameable label.

🔴 **The footer is ONE row, and Park is no longer a button in it.** Parking a card IS putting it in
the parked column, and the record's `Move to` select already does that — choosing that stage asks
for the reason and calls the same `park` endpoint, so `task_workflow` still writes all three hold
columns (§ "A task's lifecycle is `services/task_workflow.py`"). Everything rare or destructive sits
behind **More**. Keep it one row: it wrapped once, and the primary action ended up stranded under a
red Delete.

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

### 🔴 The SW's asset miss FAILS — it must never fall back to `/kiosk` (fixed 2026-08-11)

The static-asset handler used to end `|| caches.match("/kiosk")`, so an offline request for an
**uncached asset** was answered with the kiosk's **HTML document**. A `<script>` then received
`text/html`, which `X-Content-Type-Options: nosniff` blocks outright — so on `/login`, `login.js`
never defined `pageInit` and the form was never wired: a page that rendered perfectly and could not
sign anyone in, with the "Continue with Google" button still visible because the config branch never
ran (that visible button is the **tell** — in production `google_enabled` is false, so a healthy page
hides it). It answers `Response.error()` now, so the fetch fails as what it is and the browser reports
it. Two rules: **never return a wrong-type body**, and **never an empty 200 either** — a blank script
is worse, it fails silently. `login.js` also joined `CORE` (nobody can sign in without it).

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
| `on_hold` + `hold_reason` + `resume_to` | `park` / `resume` / **`_sync_hold`** | Three coupled fields, and only ever written TOGETHER — which is why `on_hold`/`hold_reason` stay in `atrium_tasks.ONLY_ATRIUM` even though Sentinel has the columns. A PATCH could otherwise park a card with no memory of where it came from. `_sync_hold` (2026-08-06) is the second writer and obeys the same rule: it derives all three from the stage the card just moved into. |
| `review_state` + `reviewer_id` | `submit_review` / `approve` / `request_changes` | Approval gates entry into a done column and is **spent** by that completion. |
| `start_date` | ordinary field | The one plain one — and it had to be REMOVED from `ONLY_ATRIUM`, which was silently dropping it from every Sentinel PATCH. |

🔴 **A STAGE'S RULE HAS TO FIRE FROM EVERY DOOR INTO IT — two were missing (2026-08-06).**
The rules above were only ever run by `_apply_status`, so two ways of putting a card in a column
skipped them entirely and produced rows the rest of the board then read as facts:

| Door | What it produced | Fix |
|---|---|---|
| **Dragging INTO the blocked column** | a card in the parked column with `on_hold` **False** — no ⏸ pill, no remembered column, a drawer still offering "Park…". `push_stage` moved the CLIENT's card to the blocked stage anyway, so the client read "Paused" for work this row denied was paused | `task_workflow._sync_hold` — the entry half of a rule that only had an exit half |
| **"Add card" at the foot of a column** (`create_task`) | a task created in a done column with **no `completed_at`** → per §2.4h it is counted on NO day, so it sat in Completed while being invisible to Throughput, the on-time rate, cycle time, and showing "—" in Past work. Created in the blocked column: "parked" with `on_hold` False | `create_task` calls `on_status_change(db, task, "", status, user)`. `old=""` resolves to no stage, so no "was_done"/"was_blocked" branch fires — a new card is not leaving anywhere |

The review gate is deliberately NOT applied on create: `review_blocks` is about a claim that existing
work is finished, and refusing to let anyone file already-delivered work would just push them to
create it in To Do and drag it across, arriving at the same place with an extra step.

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

**Uploading a PDF IS adding an entry (2026-08-31).** `POST /api/development/growth/upload`
(multipart: `file`, `dimension`, `kind`, `title?`, `status`) runs `services/pdf_text.py` (pypdf, lazy
import → 503 when the image lacks it) and stores the text as the entry's `detail`, page-marked
(`[page N]`), with an import header line. **No bucket, no blob column, no migration** — the file is not
kept, because an entry is the only shape the coach can read (index + on-demand body, above). Rules
carried over: the text is capped at `pdf_text.MAX_CHARS` (200k) and a cut is **written into the text**
("N more pages were NOT imported") so the coach reports a gap, never an absence; a scanned PDF with no
text layer is a 400, not an empty entry. The "↑ upload PDF" link sits next to "+ add entry" in every
dimension's Notes section (`growth.js` `pdfForm`). Covered by `tests/test_growth_pdf_upload.py`.

Covered by `tests/test_growth_notes.py`. 🔴 The column reaches **prod** via
`main._ensure_columns` (deploys don't run alembic); `b6d2f8a4c7e9` is the local/migrated path and is
existence-guarded because `create_all` usually wins the race.

### 🔴 The gym LOG is opt-out for the coach — and withholding it must be SAID, not just done

`development_profiles.coach_reads_gym_logs` (2026-08-10), toggled on the **Physical tab**.

The bug it fixes: `holistic_digest` shipped `sessions_last_14d` / `completed_last_14d`, and the
engine rendered them with `?? 0`. Someone who trains six days a week and **logs none of it** was
therefore told by their own coach that they had been inconsistent. A low count there is a fact
about logging, not about training, and nothing in the prompt said so.

**The setting is the easy half. This is the half that matters:**

> Turning it off must make the digest say **`gym.logs_shared: false`** — never simply drop the
> keys. An absent count is read as zero; that is how the bug got worse, not better. The engine
> branches on the flag and prints an explicit "draw no conclusion about their training frequency"
> instruction. Same rule as the growth-journal index and the task-board digest one section up:
> **name the gap.**

Four things hold it together:

- **The counts become `None`, never `0`.** A zero is a claim. `test_withheld_counts_are_None_and_
  never_zero` pins it, because a `0` sailing through a template turns the absence back into one.
- **Off hides the LOG, not the person.** The weekly split, cardio, routines, PRs and target lifts
  still ship — the split is what drives the coach's training-load advice about *studying*, and
  losing that would be a worse regression than the bug.
- 🔴 **The coach cannot flip it.** It has its own endpoint (`GET`/`PUT /api/gym/coach-visibility`,
  own-caller only, no `?user=`) and is deliberately outside `ResumeIn` and the `update_resume`
  action op — a blindfold its wearer can remove is not a setting. Don't add it to that whitelist.
- **Every surface that reports training frequency asks first.** Today that is `holistic_digest`
  **and** `services/personal_report`. A setting honoured in one place and not the other is not a
  setting; add the check with any third reader.

🔴 The route sits **above** `/{log_id}` in `routers/gym.py` for the reason the routines block
documents — registered later, `GET /{log_id}` swallows it and answers 422. Pinned by
`test_the_route_is_not_swallowed_by_the_log_id_route`. Column reaches prod via
`main._ensure_columns` (deploys don't run alembic); `d4a9f1c8e35b` is the local/migrated path and
is existence-guarded. Covered by `tests/test_gym_coach_visibility.py`.

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
- **The pace arithmetic lives in `growthmath.js`, not in either component.** The admin table
  renders the same numbers about the same people as a worker's own rings; two copies of
  `expected()` would let one surface drift from the other with nothing to say which is right.
- 🔴 **The super admin has NO growth profile (owner decision, 2026-09-03).** The Agora super-admin
  seat is an operator account, not an employee, so the staff growth surfaces are not drawn for it:
  no rings, no "Time on growth", no pace band ("where you are vs where the calendar says"), no
  per-dimension ledger, no Mentor library — on its Overview or via `/growth?user=`. The rule is
  spelled ONCE, in `S.hasGrowthProfile` (app.js), and `dashboard.js` hangs sections 2 and 4 on it;
  the server half is `team_growth.visible_users`, which leaves the seat out of Team progress and the
  team time table (both rosters come from it). Branch on the predicate, never on
  `role === "super_admin"` inline. The admin block itself stays — it is about everyone else.

### 🟡 The Overview's admin block has a PAGE-WIDE people filter — added 2026-08-03

`TeamGrowth` (`teamgrowth.js` → `GET /api/development/team`) opens the "Across Agora" block with
everyone's four dimensions in one table, and it is also the Overview's **scope control**: pick
people, or a segment like "stalled", and `dashboard.js:applyScope` re-scopes the task board, the
KPI tiles, the clock-in chart and the late/handover lists. State is URL-backed
(`?people=&sort=&seg=&win=`). Three things to know before changing any of it:

- **Speed is not the pace chip.** The chip is `actual − expected`: a POSITION against a calendar,
  so somebody who banked progress in July and stopped still reads "▲ ahead". Speed is points of
  engine mastery gained per WEEK, measured — the engine reports `progressSumThen` (the same rollup
  recomputed against each topic's stats as they stood when the window opened) beside
  `progressSum`, and `team_growth._velocity` takes the difference. Both columns are on the table
  because they answer different questions; the default sort is speed.
- 🔴 **Unknown is `None`, never `0.0` — end to end.** An unreachable engine, or a person with no
  enrolled programme, renders "—", sorts LAST in both directions, is excluded from the named
  segments, and is counted out loud under the table; `engine_error` carries the reason up. A team
  of zeroes reads as "nobody is doing anything", which is the same confident-lie failure the
  Watcher bridge produced twice (see the fail-soft entry below). `tests/test_team_growth.py` pins
  it.
- **Physical has a score but no speed, deliberately.** Its ring is the mean progress across target
  PRs, and a PR row carries only a current value — nothing timestamps the climb. Reporting "no
  history" as "no movement" would libel whoever is training hardest, so `velocity` is `None` and
  the dimension sits outside the ranking.
- **The rollup is ONE batched engine call, not one per head** (`/api/internal/team-progress`,
  purpose `team-progress`), because the engine reads its shared ~540-doc catalogue once and
  overlays each person onto it. Cached 120 s in-process; `?refresh=1` bypasses. Never loop
  `enrollment-progress` per person to rebuild this — that is ~540 doc reads each.

### 🟡 Time in the engine — minutes per dimension, Today / This week / 30 days (2026-09-01)

The Overview shows, under the compass, how many minutes the person ACTIVELY spent in the Mastery
Engine per dimension (Professional · Philosophical · Spiritual · Coach), and the admin block shows
the same four numbers for everyone (`timespent.js` → `/api/development/time`, `/time/detail`,
`/team-time`; `services/time_spent.py`). Totals only — the sessions behind them (start–end ·
section · view) are a click away, deliberately not on the page. Four things to know:

- **The engine records the minutes, Sentinel only reads them.** A minute counts when the engine
  frame is on screen and something happened in the last three minutes — an answer, a card, a
  message, the learner speaking, the assistant speaking or writing back. Mouse movement is NOT a
  signal (a hands-free conversation has none). Several open frames (Professional tab + a growth
  tab + the Coach FAB) count a minute once. The rule lives in the engine's `activityTracker`
  (`public/app.js`) and `/api/activity/beat`; change it THERE, never by re-deriving here.
- **Windows are PH DATES sent to the engine** (`from`/`to`), which stamps minutes in Asia/Manila
  too — so "today" is the same day on both sides. `today` is the default; the choice is shared by
  both mounts and remembered in localStorage.
- **Programmes → dimensions the way the compass does:** career → Professional, the pinned growth
  programmes (`team_growth.DIM_PROGRAMS`) → their tab, NO programme → Coach, any other growth
  programme → "Other" (shown only when it has minutes).
- 🔴 **"—" is unknown, "0m" is zero — and here zero is a real answer.** Unlike the progress rollups,
  a person with no minutes has nothing recorded and shows 0m. The dash is reserved for the bridge
  failing, and `engine_error` is printed beside the table. `tests/test_time_spent.py` pins it.
- **Two sources, merged at READ time, never in storage (2026-09-01, same day).** Engine minutes stay
  in the engine's Firestore; hand-logged time is `models.TimeEntry` (`time_entries` — a NEW table, so
  `create_all` lands it on prod; `b7e2f4a9c1d6` is the guarded migration). Every session row says
  `source: engine | manual`. A manual entry may be filed under any dimension **including Physical**,
  which has no engine programme at all.
- 🔴 **An engine session can be DELETED or TRIMMED, never extended or moved** — the honesty edit ("I
  was just moving the mouse"). `POST /api/development/time/engine-edit` turns it into one signed
  `time-edit` POST that removes minute keys (`engine_bridge.post`). To ADD time you log a manual
  entry, so a typed minute can never impersonate engine activity. A session that ended inside the
  last `LIVE_GUARD_MINUTES` (5) today is refused with **409**: the engine keeps no tombstones, so the
  next beat would simply re-stamp it.
- **Writes are the person's own, or an admin's on their behalf** (`time_spent.may_write`). A team lead
  can read a report's time (`can_view`) but not rewrite it. Every write clears the team cache.

### 🔴 Sentinel as the operating system — Today · Clients · Operations · Calendar · Start Work (2026-09-02)

Built overnight from the owner-approved proposal in [docs/SENTINEL_OPERATING_SYSTEM.md](docs/SENTINEL_OPERATING_SYSTEM.md)
(read §E there for the reasoning; this section is the operating rules). The SOP the team follows is
[docs/SENTINEL_SOP.md](docs/SENTINEL_SOP.md).

**One landing page, three shapes.** `/dashboard` is still everyone's landing page; `dashboard.js`
mounts ONE role-shaped block under the greeting — `today.js` (employee / intern / team_lead:
work today, waiting, time today, training), `accounts.js` (account_manager: needs-your-action,
account health, commitments, people) or `ops.js` (admin / super_admin / viewer: the exception list,
stats, client health, capacity) — and the growth compass + ledger follow it, unchanged. Each is a
mountable object like `GrowthPanel` (never `window.pageInit`), fail-soft on its own. `opsui.js` is
their shared drawing: **one row shape per task everywhere** (`.os-row`), stage tested through
`S.vocab.task_status_meta`, never a status label.

**New pages:** `/clients` (`clients.js`; `?client=<id>` drills into one account, with "Draft with AI"
and the account-manager control) and `/calendar` (`calendar.js`). Nav follows capabilities:
Clients is `clients.view`, the Calendar is everyone's.

**The one new data primitive: `task_sessions`** (`models/work.py`, `services/task_sessions.py`).
Per-task work time, written ONLY by Start Work / Pause / Submit / Park / clock-out — never typed.
Rules: one open session per person (starting another card pauses the first); a session past
`SESSION_CAP_MINUTES` (240) is **clamped and flagged `auto_cap`**, never trusted; clock-out closes it
(`auto_clockout`, in `routers/attendance._record_event`); Start Work on a To Do / Revision card moves
it to In Progress **through `_apply_status`**, so history, projection and broadcast all happen. The
topbar's "Working on …" strip (`app.js refreshWorkStrip`, polled every 60s) and the record's footer
(taskboard.js `#d-start` / `#d-pause`) are its two doors. 🔴 `/sessions/active` and `/sessions/pause`
are declared **above** `GET /{task_id}` in `routers/tasks.py` or they 404 as "Task not found".
🔴 Session time is INTERNAL — not in `task_bridge.SAFE`, not in the staff mirror.

**Structured holds.** `tasks.hold_kind` (constants.HOLD_KINDS) + `tasks.blocked_by_task_id` ride with
`on_hold`/`hold_reason`/`resume_to` — written by `task_workflow.park`, cleared by `_sync_hold`, and
that is the only writer. It is what lets the AM's and COO's screens split "waiting on the client"
from "waiting on us" without reading prose. The park dialog (`askPark`) offers the kinds as chips.

**Client health is a PRINTED rule** (`services/client_health.py`): red = overdue ∨ blocked on us > 2d
∨ review waiting > 24h; amber = due today ∨ waiting on the client ∨ untouched 14d; else green. Both
screens print the rule and the reason in words. Only Sentinel rows count — an un-adopted Atrium card
has no hold kind or review state to test. `clients.account_manager_id` is a staffing fact and lives
here, not in Atrium (`PATCH /api/ops/clients/{id}/account-manager`, cap `clients.assign_am`).

**The calendar has NO table** (`services/calendar_view.py`): task due dates (through `can_view` /
`is_assigned`, the board's own predicates), recurring services' trigger days, approved leave. Change
the due date on the card and the calendar moves.

**Operations is exceptions only** (`services/operations.py`): red clients, heavy people (the
Monitor's relative band), absence without cover, client-blocked > 2d, reviews > 24h, changes requested
twice in 30d, stalled learners. 🔴 Stalled learners are skipped entirely while `engine_error` is set —
an unreachable engine makes every row read zero, and zero is UNKNOWN there.

**AI drafting proposes, never writes** (`services/ai_draft.py`, Vertex Gemini via the runtime SA —
`deploy.ps1` grants `roles/aiplatform.user` and sets `VERTEX_*`). It returns `TaskCreateIn`-shaped
proposals validated against Sentinel's roster (warnings computed HERE: leave, heavy, stage needs a
reviewer, not in the department, missing certification); the UI posts each kept one to `POST /api/tasks`.
Off (`VERTEX_GEMINI_ENABLED` unset) → 503 and the button says "unavailable — file it by hand".

**Stage and certifications are SURFACED, not enforced** (v1). `users.stage` (Shadow → Contributor →
Workstream Owner → Client Owner) is readiness, orthogonal to `role`; `certifications` +
`service_templates.required_certification` produce warnings at drafting. Enforcement is a later,
separate decision.

**"Act as user" (2026-09-02, same day).** A SUPER ADMIN can browse Sentinel as any active user —
the Mastery Engine's act-as, estate-wide. `security._apply_act_as` swaps the resolved user on EVERY
dependency (the session cookie stays the real person's; `sentinel_act_as` carries the target id and
is inert unless the real session is a super admin — re-checked per request, so forging it grants
nothing and acting is only ever a narrowing). Rules that hold it together: the `/api/auth/act-as`
gate reads **`get_real_user`** (an acted-as employee must not re-point the act); 🔴 **time is never
written while acting** (`forbid_while_acting` on punches, timer sessions, manual entries,
engine edits — the ME keys its minutes to the real identity for the same reason); start/stop are
audited to the REAL person while ordinary writes attribute to the target (that is what "as" means —
the audit bracket is why that's acceptable); a deactivated target silently dissolves the act;
logout clears it. UI: the loud orange `.actas-bar` with Stop, the topbar eye button + palette
entry (`openActAsPicker` in app.js), `/api/auth/me` ships `acting_as.real`. Pinned by
`tests/test_act_as.py`.

**Projects — the thin project layer (2026-09-02, the go-live reset day).** Named outcomes with
dates ("Phase One — a replicable pod by October 1"), because the owner could see every card and no
initiative. `models/project.py` (two tables — create_all lands them on prod; `tasks.project_id`
rides `_ensure_columns` + migration d4c7e9a2f5b8), `services/projects.py` (rollups DERIVED from
milestones + linked tasks; health is a printed rule like `client_health`), `routers/projects.py`
(🔴 milestone routes declared ABOVE `/{project_id}` — the gym `/routines` registration-order
lesson), page `/projects` (`projects.js`), caps `projects.view` (managers + viewer) /
`projects.manage` (AM+). Rules: a MILESTONE is a checkable claim, not a task (no assignee, no
board card — forcing that merge is how PM tools grow two boards); milestone done is a stamped
transition (done_at/done_by, audited); deleting a project UNLINKS its tasks, never deletes them;
`task_card` publishes `project_id` only (the name would be a per-card read — query budget),
`task_detail` resolves `{id,name}`. 🔴 Keep it thin: no per-project statuses, Gantt or staffing —
the owner's instruction was "do not overcomplicate it". The board takes `?project_id=` and the
form's Project row renders only for `projects.view` holders. Pinned by `tests/test_projects.py`.

**The AI planner is the SHARED create flow (`OpsUI.openAiPlanner`, 2026-09-02).** One modal —
Task Board header ("✦ Plan with AI"), a project page, and the client drill-down's older inline
box — for the owner's AI-first design: plain words → `/api/ops/ai/draft-tasks` proposals →
**title, assignee and due date editable per proposal** → each kept one POSTed to `/api/tasks`
(every rule intact; `depends_on` becomes a park on the created card). Proposing never writes.

**The go-live reset (owner decision, 2026-09-02).** Every Sentinel task row was deleted in prod
(a full JSON export was taken first) and the board restarted clean; Atrium's client cards and ALL
Mastery Engine progress were deliberately untouched. `operations.MEASUREMENT_BASELINE` starts the
measurement clock that day: the stalled-learner exception stays silent until its window fits
entirely after the baseline, so nobody is flagged for a fortnight that predates the system.

**The AI Assistant (renamed from "Coach", 2026-09-02) is SELF-AWARE and can ACT.** Three pieces:
(1) **Naming** — the FAB and panel header say "AI Assistant" everywhere Sentinel shows them
(`app.js mountAssistant`; the engine retitles its embedded header in `?embed=assistant` mode). The
ids stay `#coach-*` and the postMessage types stay `agora-coach-action*` — renaming wire formats
buys nothing and breaks both repos at once.
(2) **Self-knowledge** — 🔴 [docs/HOW-SENTINEL-WORKS.md](docs/HOW-SENTINEL-WORKS.md) is injected
into the assistant's prompt (served by `GET /api/internal/sentinel-guide`, purpose
`sentinel-guide`; the engine fetches + caches it 10 min in its `lib/sentinel.js`). **Any change to
a user-facing page, flow or rule MUST update that doc in the same change** — it ships in the
image (`Dockerfile` copies it to `/docs`; `.dockerignore` un-ignores it from the `*.md` rule), so
a deploy IS the knowledge update. Same pattern as the engine's own HOW-IT-WORKS.md.
(3) **Actions** — `app.js coachExecute` now carries SENTINEL OPS (create/update/move/park/resume/
delete/comment a task, reviews, start/pause work, clock, projects + milestones, set a client's
AM): the assistant proposes an `agora-action`, the person taps Approve in the chat, and the op
executes via the normal REST API **in the user's own session** — fixed endpoints, whitelisted
bodies, so every permission rule applies exactly as if they clicked the UI. The prompt half
(`assistantSentinelOps` + `sentinelGuideBlock`) lives in the engine's `lib/gemini.js`, wired in
BOTH assistant paths (blocking + streaming — the engine's three-places rule). Approved actions
call `window.SentinelReloadBoard` / `refreshWorkStrip` so the change appears at once.

**Go-live reset, phase 2 (2026-09-02, owner's instruction).** All 61 remaining ATRIUM client
cards were exported (`agora-devtools/backups/prod-atrium-card-backup-2026-09-02.json`) and deleted
— Atrium soft-deletes each into its console Bin (30 days). The board is now fully empty. Every
active non-super-admin was reset to `employee` (specialist) so AM/COO roles can be granted
deliberately; supers kept: Agora Admin, Ian, Charles.

**What did not change:** no new statuses (review and hold are flags on the five stages — D13); no pod
entity (client AM + card holders express it); estimates are optional and template-defaulted
(`estimate_minutes`), and the Monitor's relative band stays the truthful capacity default; the daily
cron is still NOT scheduled (see §2). New columns reach prod via `_ensure_columns`; the two tables via
`create_all`; migration `c9e4a7b2d6f1` is the guarded twin. Pinned by `tests/test_operating_system.py`.

### 🔴 The Coach FAB is not a second assistant — ONE DOOR PER PAGE

Added 2026-08-10. The FAB frames the Mastery Engine at `?embed=assistant`, which is that app's own
**study assistant** with its chrome hidden — same widget, same `/api/assistant/chat`, same thread
store, same persona. "Coach mode" is a toggle on that same panel. There is nothing here to keep
separate from the engine's assistant, because it *is* the engine's assistant.

Which meant that on `/academy`, `/philosophical` and `/spiritual` — pages that already iframe the
engine — **two buttons rendered in the same corner**: ours at `right:24px` and the engine's own
`#assistantDock` at `right:20px` inside the frame, both opening the same assistant. So
`mountAssistant` suppresses the FAB on `ENGINE_PAGES`. Three rules:

- **The engine's in-frame dock is the one that wins**, and it is a strict superset: it proposes the
  same profile edits (gated on being in a host frame — **not** on the `actions=1` the FAB's src used
  to carry, whose reader in the engine was dead code and is now gone), *and* it can see the
  learner's screen. Our FAB frames a blank engine and never can.
- 🔴 **Suppress the BUTTON, never skip `mountAssistant()`.** The `agora-coach-action` listener at
  the end of that function is what executes an Approve, and on those pages the in-frame panel is now
  the only thing sending one. Early-returning would break profile edits exactly where they are used.
- **It has its own class (`.on-engine-page`), not `.hidden`.** Modals toggle `.hidden` to keep the
  FAB off their footer, and restoring it must not resurrect a button the page suppressed for good.

Adding a page that embeds the engine? Add it to `ENGINE_PAGES`.

### 🟡 An embedded Mastery Engine stays light inside a dark Sentinel

The engine is cross-origin, so it cannot read our theme. We hand it over twice and BOTH halves are
required: `S.engineUrl()` appends `&theme=` to the iframe src (the initial paint), and `setTheme`
postMessages `{type:'agora-theme'}` to every iframe (the toggle moving while a frame is already
running). Build every engine src through `S.engineUrl()` — a hand-built src loses half of it.
Also give the iframe `background:var(--card)`, never `#fff`: a white slab flashes behind the
engine on every load in dark mode. The engine end is `public/theme.js` there.

### 🔴 The board has a QUERY BUDGET — `task_card` must never read per card

Fixed 2026-08-07, and the two costs behind it are both invisible in the source, which is why this
section exists. Measured on the board as it was: **801 cards → 2,946 SQL queries, 780 ms on SQLite**
— and on Cloud SQL every one of those is a socket round-trip, so the same board cost *seconds*.
After: **7 queries, 61 ms.**

| Where | What it really did |
|---|---|
| `len(t.comments)` | a LAZY LOAD — one SELECT per card, to count rows. `Task.supporters` is `lazy="selectin"` and cost 1 query for the whole board; nothing batched comments |
| `db.get(Client/User, …)` | 🔴 **SQLAlchemy's identity map holds WEAK references.** `task_card` returns a plain dict and keeps no reference to the row it read, so each one was garbage-collected before the next card asked for it and `db.get` went back to the DB. That is how the same **four** clients cost **703 SELECTs** |
| `MT.normalize(...)` | parsed and rebuilt the breakdown JSON **3× per card** — `can_view`→`is_assigned`, then `my_slot_count` and `sub_stats` (2,400 calls for 801 cards) |

Three rules, each of which is the fix:

- **`serializers.CardPrefetch.for_tasks(db, tasks)` is the ONE prefetch**, and every list caller
  passes it (`list_tasks`, `people.py`'s profile card). It is three queries whatever the board's
  size, and **holding the rows alive is what makes the identity map work** — do not "simplify" it
  into a lookup that drops its references.
- **It is an optimisation, never a source of truth.** Every accessor falls back to a direct read, so
  a card built without one (`task_detail`, one row) is still correct. `test_a_card_is_identical_with_
  and_without_a_prefetch` pins that they can never disagree.
- **Ask `maintasks.normalized(task)`, never `normalize(task.maintasks_json, …)`.** It memoizes on the
  row, keyed on the *identity* of the raw strings — so a write rebinds the attribute and correctly
  misses the memo.

Adding a field to a card that needs another row? Put it in the prefetch. A single `db.get` in that
function is a query per card again, and nothing will fail — pinned by
`tests/test_performance_guards.py::test_board_query_count_is_bounded_not_per_card`.

### 🔴 Atrium's board list is CACHED (15s), and share-on-create runs AFTER the response

Both landed 2026-08-07, and both are about the same thing: a blocking call to another service was
sitting inside a request somebody was waiting on. `atrium_bridge` is stdlib urllib and **pools no
connections**, so every one of these paid a fresh TCP + TLS handshake.

- **`atrium_tasks.fetch_tasks` caches successful reads** for `settings.atrium_cache_seconds`
  (`ATRIUM_CACHE_SECONDS`, default 15, `0` disables). It was on the critical path of every board
  load, every Monitor load and every Coach digest, with a 10s read timeout. Fail-soft covered an
  Atrium *outage*; it did nothing about a *slow* Atrium, whose latency was simply added to ours.
  🔴 **A failure is never cached** — caching the fail-soft `[]` would blank every client card for the
  whole TTL over one blip. 🔴 **Every write in that module invalidates it**, or your own edit comes
  back looking like it was dropped. A new write function must call `_invalidate()`;
  `test_every_write_invalidates_the_cache` is parametrised over all six so a seventh fails until it
  is added.
- **Share-on-create is a `BackgroundTask`** (`tasks._publish_after_response`). `task_bridge.publish`
  is TWO sequential blocking writes to Atrium (`add_task`, then `push`), each with a 30s timeout, and
  they sat between the AM pressing Create and the form closing. Nothing about the contract changed —
  the task was already committed first, the failure path was already `atrium_sync_error` + the
  drawer's stale pill + one-click Retry, and the response never reported the result.
  🔴 **It opens its OWN session**: FastAPI tears the request's session down *before* background tasks
  run, so reusing `db` would pass tests and fail in production. 🔴 **Its `_broadcast` is
  deliberately unattributed** (`actor_id=None`) — the frontend skips events it caused, and the board
  that most needs this refresh is the creator's, still rendering their new card as unshared.

### 🟡 The connection pool and `--max-instances` are ONE decision

Every endpoint here is a sync `def`, so FastAPI runs it in anyio's **40-thread** pool, while
SQLAlchemy's default pool is **5 + 10 = 15** connections. 25 threads could be queueing on
`pool_timeout` (30s by default) with nothing in the logs but a slow request — which is what turned
"slow" into "hung" whenever a query got expensive.

🔴 **The answer is not one connection per thread.** `db-f1-micro` allows about **25 connections in
total**, shared with the seed job, migrations and any psql — so a pool sized to the threadpool would
starve the estate from one instance, and multiplying by `--max-instances` would ask for hundreds. The
real fix was making the HOLD short (`CardPrefetch`: ~880ms → ~60ms per board request); the pool only
covers what is genuinely in flight.

| Knob | Value | Meaning |
|---|---|---|
| `db_pool_size` | 5 | what one warm instance **holds at rest** — this is the number that eats `max_connections` |
| `db_max_overflow` | 15 | burst, opened on demand and closed on return; free at idle |
| `db_pool_timeout` | 10s | fail fast; a caller that cannot get a connection is better served by a retryable error than a request that dies at the load balancer |
| `--max-instances` | 3 | **worst case is `(5 + 15) × 3 = 60`.** Change this and the pool together, or neither |

Set in `app/config.py`, applied in `database.py`; SQLite ignores all of it. If a genuinely slow
endpoint appears (a big CSV export, adoption over a large workspace), raise these — and
`max_connections` or the instance tier with them.

### 🟡 The tests cannot all be run in ONE pytest process on Windows

Pre-existing, confirmed against unmodified `main` on 2026-08-07. Every test file passes on its own,
and the suite passes some of the time, but a long single process reliably stalls partway (seen in
`test_task_adoption.py`, with no single predecessor able to reproduce it) — the profile of leaked
`TestClient` threads/handles accumulating, since `conftest.client` never closes one. If `pytest`
appears to hang, **it is not your diff**: fall back to per-file runs (below), and see §7 about the
shared `%TEMP%\sentinel_pytest.db` — two pytest processes at once clobber each other's schema and
produce "no such table" errors that look like a code bug.

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

🔴 **Two things about running it on Windows, both of which have cost a debugging session:**

```powershell
# 1. Give this run its OWN temp dir. conftest puts the test DB at %TEMP%\sentinel_pytest.db, so two
#    pytest processes (a second window, a background run) rebuild each other's schema mid-test and
#    the failures read as "no such table: users" — a machine problem wearing a code problem's face.
$env:TEMP = "$env:TEMP\sentinel-pytest-1"; $env:TMP = $env:TEMP
mkdir $env:TEMP -Force | Out-Null

# 2. If one long run stalls, run per file — see §5, "the tests cannot all be run in ONE pytest
#    process". That stall predates any current change and reproduces on unmodified main.
Get-ChildItem tests\test_*.py | ForEach-Object { python -m pytest -q $_.FullName }
```

Existing coverage: attendance engine, CSRF, events, gym plan, internal HMAC endpoints, leave,
observability, security headers, RBAC, **the capability layer + Permissions console
(`test_permissions.py`), the task-board predicate rewrite (`test_task_capabilities.py`, which re-derives every original body and compares), and the per-person layer + reports (`test_user_capabilities.py`)**.

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
| Put a `task_perms`-style rule in `capabilities.py` | A capability is decided from the ROLE alone. Anything that needs the row stays in `task_perms` — §3. |
| Unlock `permissions.manage` or `people.set_role` | Both are privilege escalation: the console could then grant away the power to grant everything. |
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

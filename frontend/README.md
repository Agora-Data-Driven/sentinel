# frontend/ — the Sentinel UI

Vanilla JS, no framework, no bundler, no build step: 19 thin HTML shells under `pages/`, one
controller file per page under `static/js/`, one stylesheet, a PWA service worker for the offline
kiosk. Operating rules (CSP, cache bumping, `api()`-only fetches) live in
[../AGENTS.md](../AGENTS.md) — this file is the unit map + cookbook.

## File map

| Entry | What it is |
|---|---|
| `pages/*.html` | 19 shells (~0.7 kb each; JS renders everything): dashboard, attendance, approvals, gym, growth, reading, academy, philosophical, spiritual, people, leave, north-star, reports, settings, manage, payroll, login, kiosk, scanner. Routes registered in `backend/app/main.py` (`_PAGES`; `/login` is its own route). 🔴 **Served rewritten, not as files** — `main._page` appends `?v=<build id>` to every `/static/**.{js,css}` reference so those assets can be cached `immutable` (`backend/app/assets.py`, AGENTS.md §5). Write plain `/static/...` paths here; the rewrite is automatic and skips any URL that already has a query string |
| `static/js/app.js` | The shell every page loads: `NAV` array `:78` (roles/`min`/`hideRoles` gate visibility; **Clients** follows `cap: "clients.view"`, **Calendar** is everyone's — 2026-09-02), `api()` (CSRF echo + FastAPI error flattening), `toast`, `skeleton`, **`loadErr`**, **`sortTable`**, `modal`, `esc`/`qs`/`qsa`, `ICON`, `avatar`, **the "Working on …" strip** (`refreshWorkStrip` — the one running task session from `/api/tasks/sessions/active`, with Pause; polled every 60s; exported as `S.refreshWorkStrip` so the board re-reads it after Start Work / Pause), command palette (`initCommandPalette`), Coach FAB (`mountAssistant` — an iframe of the Mastery Engine's own study assistant; **suppressed on `ENGINE_PAGES`**, which already show that panel inside their engine frame — see AGENTS.md §5), `setTheme`/`engineUrl`/`themeEmbeds` (hands our light/dark to every embedded Mastery Engine). 🔴 **`toast` writes into an `aria-live` region and `.x-close` is a real `<button>`** — see the a11y gotchas below |
| `static/js/taskboard.js` | Mountable Kanban (`TaskBoard.mount`). Optimistic DnD (native HTML5 — deliberate, see AGENTS.md §9), SSE reload, quick-add, Atrium-card editing, and the lifecycle controls: Park/Resume, Submit/Approve/Request changes, Past work. **"My work" is a client-side toggle over the card's `mine` flag, NOT the `?assignee_id=` filter** — see the gotcha below. **Support** (many people per card, since 2026-08-06): `supportOptions` builds the picker and mirrors the server's delegation rule (a non-delegator's list contains only THEM; a colleague already on the card renders `selected disabled` so the list round-trips instead of 403ing), `supportStack` draws the overlapped avatars from **`support`, now for BOTH kinds of card** — the server resolves a client card's Atrium roster emails to Sentinel users too (2026-08-06), so a supporter with a photo shows it instead of grey initials beside a lead who had one; `atrium_support_names` remains the fallback for a payload built without a resolver. **The card and the record were redesigned 2026-08-06** (`flagOf` + `card()` + `openDetail`) — see "The quiet card" below |
| `static/js/tasks.js` | **The Task Board page** (`/tasks`) — its own page again since 2026-08-03 (decision D7); a thin shell that mounts `taskboard.js` full-width. It was embedded in the dashboard from 2026-07-26 until then, so `/dashboard?open=<id>` forwards here forever (the notifications minted in that window are permanent rows) |
| `static/js/opsui.js` · `today.js` · `accounts.js` · `ops.js` | **The operating-system release (2026-09-02, AGENTS.md §5 "Sentinel as the operating system").** `opsui.js` = `window.OpsUI`, the shared drawing: ONE row shape per task (`.os-row` — priority dot + title, one grey meta line, a due chip), `clientsTable`, `healthPill`, `band`, `meta()` (caches `/api/ops/meta`). The other three each define ONE mountable object — `TodayPage` (employee / intern / team_lead: work today, waiting on others, time today, training today), `AccountsPage` (account_manager: needs-your-action, account health, commitments, people) and `OpsPage` (admin / super_admin / viewer: the exception list, stats strip, client health, capacity) — and `dashboard.js` mounts exactly one of them by role into `#dash-landing`, under the greeting and above the growth compass. 🔴 None of them may define `window.pageInit`. 🔴 Stage through `S.vocab.task_status_meta`, never a status label |
| `static/js/clients.js` · `pages/clients.html` | **Clients** (`/clients`, cap `clients.view`): the health table; `?client=<id>` drills into one account (work by specialist, blockers and on whom, reviews, commitments, completed) with **Draft with AI** (proposals → each kept one is `POST /api/tasks`, a dependent one then parked as "waiting on another task") and the account-manager control (`PATCH /api/ops/clients/{id}/account-manager`). Loads `opsui.js` |
| `static/js/calendar.js` · `pages/calendar.html` | **Calendar** (`/calendar`, everyone): Today / Week / Month over `/api/ops/calendar` — task due dates, recurring trigger days, approved leave. **No table behind it**; Mine / Everyone follows the board's own scope. Loads `opsui.js` |
| `static/js/dashboard.js` | **The Overview** (`/dashboard`, labelled "Overview" since 2026-08-03): greeting + the day strip (attendance/gym as two buttons), then **the role-shaped landing (`#dash-landing`, 2026-09-02 — see the row above; `renderMyWork` is skipped for the Today landing, which carries the whole work list)**, then `GrowthPanel`'s rings, the **"my work"** strip (`renderMyWork` — three `.mw-tile` doors into `/tasks` + the "Up next" shortlist, **soonest deadline first**, undated last; fails silently; "mine" = the card's `mine` flag, see the gotcha below), `GrowthPanel`'s ledger, and — admins only, last — `TeamGrowth` + the org KPIs/chart/late list/handovers. **Owns the page-wide people scope** (`applyScope`): TeamGrowth sets it, this re-scopes the KPIs, chart and lists from data already in hand. The board is no longer one of its consumers (it left for `/tasks` with D7), and "my work" is deliberately never scoped — it answers "what is on ME" |
| `static/js/teamgrowth.js` | **`window.TeamGrowth`** (admin only) — everyone's four dimensions in one table from `/api/development/team`, ranked by MEASURED speed (engine points/week), **and the control that scopes the whole Overview**. Selection/sort/segment/window live in the URL (`?people=&sort=&seg=&win=`) |
| `static/js/growthmath.js` | The dimension list + all pace/speed arithmetic (`expected`, `paceChip`, `paceNeeded`, `speedBand`). Shared by `growth.js` and `teamgrowth.js` so a worker's own ring and their row in the admin table can't drift. **Must load before both** |
| `static/js/growth-page.js` | `/growth` = a manager's read-only view of ONE person (`?user=<id>`); without a `?user` it redirects to the Overview |
| `static/js/attendance.js` · `approvals.js` | Time page · combined attendance+leave approvals inbox (team_lead+) |
| `static/js/gym.js` | Calendar, no-lock day editor, saved routines (one-tap workout templates), history, **coach log-visibility toggle** (`renderCoachVis` — withholds the workout log from the AI coach; see AGENTS.md §5) |
| `static/js/growth.js` | **`window.GrowthPanel`, a component — not a page controller.** `mount(S, root, {userId, ringsHost, mast})` renders the 4-dimension compass (each ring links into its engine tab) and the ledger (pace band, per-dimension details, Mentor Library import). `ringsHost` splits the two so the Overview can put the task board between them. Each dimension's Notes section has **"+ add entry"** and **"↑ upload PDF"** (`pdfForm` → multipart `POST /api/development/growth/upload`; the PDF's text becomes the entry, so the coach can read it) |
| `static/js/reading.js` | Reading canon |
| `static/js/academy.js` | Mastery Engine iframe (Professional tab) |
| `static/js/engine-tab.js` | ONE controller for the Philosophical + Spiritual tabs — each shell pins a program via `<body data-program>` → iframe `?program=` |
| `static/js/kiosk.js` | QR scanning + **IndexedDB offline punch queue** (syncs every 30 s) |
| `static/js/login.js` | Portal bounce + "not a Sentinel user" messaging |
| `static/js/northstar.js` · `who-we-are.js` | North Star page (iframes `static/who-we-are.html`) · that page's reveal/count-up interactions (extracted from an inline script — CSP) |
| `static/js/permissions.js` | **The role x capability grid** (page `/permissions`). Renders entirely from `GET /api/permissions` — every cell's `editable` flag AND the sentence explaining a disabled box come from the server, because a UI copy of those invariants is a second definition of them. Saves only the cells that moved and re-renders from the response, so a REFUSED change springs visibly back with its reason. 🔴 No backticks anywhere in it (string concatenation throughout) |
| `static/js/people.js` · `leave.js` · `reports.js` · `settings.js` · `manage.js` · `payroll.js` · `charts.js` | One per page + the shared canvas charts helper. `manage.js`'s Clients pane is read-only APART FROM **Sync now** (`POST /api/manage/clients/sync`) — the recovery affordance for a stale client list; it only creates and links, never retires |
| `static/js/devreload.js` | **Live reload — localhost only.** Loaded by `app.js` behind a hostname test; listens to `/api/dev/reload` (SSE). A **.css** save is hot-swapped in place (the `<link>` href is re-pointed — no reload, so the open task card, filters and scroll position survive); anything else reloads. Also **unregisters the service worker locally**, without which a reload can serve the pre-edit file from cache. Never loads in production — see the gotcha below |
| `static/css/styles.css` | The whole design system (token-driven, dark mode via overrides) |
| `static/vendor/html5-qrcode.min.js` | The only vendored lib — CSP blocks CDNs |
| `static/who-we-are.html` | North Star manifesto content (served statically, iframed) |
| `sw.js` | Service worker: **`CACHE` key line 6** (the value lives in the file — this doc does not carry a third copy of it; see Status), `CORE` precache list, network-first assets; navigations NOT intercepted except **`/kiosk`**. **Not registered on localhost** (except `/kiosk`) since 2026-08-06 — live reload needs it out of the way. 🔴 The offline fallback is `caches.match(req, { ignoreSearch: true })` **because shells now request content-versioned URLs** (`app.js?v=<hash>`) while `CORE` precaches the bare paths — an exact match would miss and the kiosk would not boot offline (AGENTS.md §5) |
| `manifest.json` · icons/favicons | PWA install metadata |
| `ui.test.js` | **The only real-DOM test in this repo.** Drives `app.js`'s shared helpers under jsdom — `modal()`'s dialog a11y contract (role/labelling, initial focus, the focus TRAP, stack-aware RESTORE, and the command palette outranking the modal stack) and `sortTable()`'s rules (**"—" is unknown and sinks in BOTH directions**, numeric-vs-text, the `data-sort` override) — **57 assertions**, exits non-zero on failure. `node --check` cannot see any of it: every bug it catches parses fine, and writing it found three (see the gotchas). Run instructions are in its header (jsdom is installed ad hoc; this repo has no `package.json` by design). **Run it after touching `modal()`, the focus helpers, `.x-close`, or `sortTable()`** |
| `modern_prototype.html` · `sidebar_prototype.html` | Design prototypes — not served, don't ship code in them |

## Data contract (page → API → serializer)

| Page script | Calls | Backend shape from `backend/app/serializers.py` |
|---|---|---|
| `taskboard.js` | `/api/tasks*` | `task_card` / `task_detail` (+ Atrium cards via `as_board_card` — string ids `atrium:<client>:<id>`) |
| `dashboard.js` | `/api/dashboard`, `/api/insights`, `/api/attendance/self-event` | `dashboard` payload (`me`, `kpis`, `late_today_list`, `handovers`) |
| `teamgrowth.js` | `/api/development/team` | `services/team_growth.py` rollup (`rows[].dimensions`, `overall`, `velocity`, `engine`) — **not a serializer**: it joins the Mastery Engine's batched per-person rollup to our own attendance/gym/PR rows |
| `attendance.js`, `approvals.js` | `/api/attendance/*` | `summary_dict`, `attendance_request_dict` |
| `gym.js` | `/api/gym/*` | `gym_log_dict`, `gym_routine_dict`, `body_metric_dict`, `personal_record_dict` |
| `leave.js`, `approvals.js` | `/api/leave/*` | `leave_type_dict`, `leave_balance_dict`, `leave_request_dict` |
| `growth.js`, `reading.js` | `/api/development/*` | `development_profile_dict`, `physical_goal_dict`, `growth_item_dict`, `reading_item_dict`, `mentor_transcript_dict` |

## Cookbook

1. **Add a page** — `pages/<name>.html` shell + `static/js/<name>.js` + register in
   `backend/app/main.py:381` (`_PAGES`) + nav entry in `app.js:78` + **bump `CACHE` in `sw.js:6`**.
   Verify: `node --check static/js/<name>.js`, load it locally. Deploy: `..\deploy\deploy.ps1`.
2. **Bump the SW cache** — `sw.js:6`, `sentinel-vN` → `vN+1`. Do this on EVERY CSS/JS change;
   the `activate` handler purges old caches.
3. **Add / gate a nav entry** — `NAV` in `app.js:78`; use `min: "<role>"`, `roles: [...]` or
   `hideRoles: [...]`. UI-only — the endpoint guard in the backend is what enforces access.
4. **Call a new API** — always `api(path, opts)` from `app.js:130`, never bare `fetch` (CSRF
   header + 422-detail flattening live there).
5. **Add an icon** — extend the `ICON` map in `app.js`; inline SVG strings, no icon fonts.
6. **Embed another Mastery Engine tab** — copy the `engine-tab.js` pattern: new shell with
   `data-program`/`data-title`, iframe needs `allow="microphone"`, build the src through
   **`S.engineUrl(base, extra)`** (it appends `&theme=` so the engine boots in our skin; `setTheme`
   then messages every iframe when the toggle moves), give the iframe `background:var(--card)`
   NOT `#fff`, and the server must delegate the mic (Permissions-Policy derives from
   `SKILL_MASTERY_URL` — AGENTS.md §5).
7. **Add something to the Overview** — it is `dashboard.js` end to end. Blocks are appended in
   reading order to one `html` string, then filled: `GrowthPanel` into `#dash-rings`/`#dash-growth`,
   `renderMyWork` into `#dash-mywork`. Both are fail-soft on purpose — a bad `/api/development` or
   `/api/tasks` must never cost anyone the rest of the page. The **board itself is not here**: it
   lives at `/tasks` (`tasks.js`) since decision D7, and the strip only links into it.
8. **Change styles** — `static/css/styles.css` only; keep it token-driven (`var(--*)`) so dark
   mode holds; then bump the SW cache. 🔴 **Check the token EXISTS** — see the undefined-token
   gotcha below; `var(--nope)` fails silently and invisibly.
9. **Render a load failure** — `S.loadErr(host, err, retry)`, never a hand-rolled `.empty`. It
   replaces the skeleton with the reason plus a **Try again**; pass `retry` whenever re-running is
   a pure function of on-screen state (a filter, a date range) and omit it when it would repeat a
   side effect. See the gotcha below for why every skeleton needs one.

Verify: `node --check` every edited JS file (CI does the same); full check = backend pytest suite.
🔴 **Touched `modal()`, the focus helpers, `.x-close`, or `sortTable()`? Run `node ui.test.js`** (file map
above) — `node --check` passes on every bug it catches.
Deploy: `..\deploy\deploy.ps1` (Cloud Run `sentinel`, asia-southeast1).

🔴 **`node --check` does NOT catch a backtick inside a comment inside a template literal.** The
board's injected `<style>` block is one big template literal, and a markdown-style code span in its
explanatory comment (`` `.spread` ``) CLOSES the string — the rest then parses as a tagged-template
call on a string property, which is *valid syntax* and only explodes at run time
(`TypeError: "…".spread is not a function`, i.e. the board dies with a bare "Couldn't load the task
board" toast and no clue). This cost a debugging round on 2026-08-04. **Quote CSS selectors with `'`
inside any comment that lives in a template literal**, never with a backtick.

## Gotchas / DO NOT TOUCH

- 🔴 **`/api/vocab` IS FETCHED ONCE PER PAGE LOAD — READ `S.vocab`, DO NOT REFETCH IT (2026-08-17).**
  It looks like a cheap GET and is not: `routers/meta.vocab()` is **4 SELECTs** (it was 7, and up to
  12 when statuses lacked a `stage` — see `task_config.vocab_bundle`). It is hit on **every**
  navigation, and `dashboard.js`, `manage.js`, `people.js` and `taskboard.js` each used to fetch it a
  **second** time on top of `boot()`'s copy — so one page load could run 14–24 queries for
  configuration that changes about once a month, on a shared-core `db-f1-micro`.
  - `boot()` now fetches it **in parallel with `/api/auth/me`** (they were two sequential `await`s,
    which cost two full round trips — measured 250–440ms each to `asia-southeast1` — before the shell
    was even built). vocab carries its own `.catch` so it can never reject the `Promise.all`; only
    `auth/me` decides whether you are signed in.
  - 🔴 **`S.vocab` is a SNAPSHOT, and Manage EDITS the vocabulary.** Statuses, priorities and labels
    are all renameable, so any surface that *writes* vocabulary must call **`S.refreshVocab()`** —
    `manage.js` does, from its generic save and delete paths, and it re-points its own local copy at
    the same time (or the app sees the new list while that page keeps rendering the old one). Reading
    `S.vocab` is only safe for a surface that does not change it.
  - **`taskboard.js` is the one consumer that falls back to a real fetch** (`S.vocab ? … : S.api(…)`),
    because `task_statuses` *are* its columns — a missing snapshot must not be the reason a board has
    no columns. The others tolerate `null` because a missing colour is cosmetic.
  - Pinned by `ui.test.js` §16–17 (one fetch, issued in parallel, and `refreshVocab` re-publishes).
    Without those the duplicate creeps back the next time a page wants `roles` or `priorities`.
- 🔴 **THE BELL BADGE COSTS A COUNT, NOT THE FEED (2026-08-17).** `wireBell()` ends with
  **`refreshBadge()`**, which calls `GET /api/notifications/unread-count` — a one-key response. It
  used to call `GET /api/notifications`: on **every navigation** that serialized up to 50
  notifications, and re-rendered the whole closed panel with them, to draw a one-character badge. The
  backend half was worse — the count was `len()` over every unread row hydrated as an ORM object, so
  a bell ignored for a month cost more than one read this morning. Measured on a 120-item backlog:
  **2 queries and 170 hydrated rows → 1 query and 0**.
  - **The feed is fetched when the panel OPENS**, and its response carries `unread_count`, so opening
    the bell never needs a second count request.
  - 🔴 **`setBadge(n)` is the ONE renderer.** Three things move that badge — the shell, the panel's
    "Mark all read", and the command palette's own action — and the last two used to poke
    `style.display` themselves. A second copy is how two of them end up disagreeing about whether a
    zero prints as `0` or hides.
  - `refreshBadge` swallows its error on purpose: the badge is decoration, and a failed count must
    never cost anybody the shell. (This is *not* the silent-degradation trap below — nothing here
    claims "you have no notifications"; the badge simply keeps its previous state.)
  - Pinned by `ui.test.js` §18, including the assertion that boot fetches **no** list at all.
- 🔴 **THE FONT LINKS ARE ON THE CRITICAL PATH, AND THE `preconnect` PAIR IS LOAD-BEARING.**
  `fonts.googleapis.com` serves the **render-blocking** stylesheet; the font FILES live on
  `fonts.gstatic.com` and their URLs are only discovered by parsing that stylesheet — a serialised
  second hop, measured at ~247ms. Both origins are now preconnected, and 🔴 **the gstatic one needs
  `crossorigin`**: fonts are fetched in CORS mode, so a non-CORS preconnect opens a connection the
  font request cannot reuse and the hint does nothing at all.
  - `Inter:wght@400..800` is the **variable-font range**, which cut that blocking stylesheet from
    **12,355 to 2,499 bytes** (35 `@font-face` rules to 7). ⚠️ It does *not* reduce the number of font
    files — Google already served Inter's variable file for the enumerated weights, so both spellings
    resolve to the same 7 subset files and a browser downloads only the subset it needs. The win is
    the blocking CSS, not the fonts.
  - All five weights (400/500/600/700/800) are genuinely used in `styles.css`, so trimming the list
    was never an option — collapsing it was. Space Mono stays enumerated (it is not variable) and is
    correctly requested by **only the four `.dev` shells** that use it.
  - 🔴 **The "make it non-blocking" trick does not work here.** `media="print" onload="this.media='all'"`
    needs an inline event handler, and CSP is `script-src 'self'` with no inline script anywhere — it
    would be silently blocked. The only way to remove that blocking request is to **self-host** the
    woff2 files (same-origin, immutable-cached, no third-party DNS/TLS); that is the remaining step.

- 🔴 **SORTING IS `S.sortTable`, AND `thead th.sortable` WAS DEAD CSS FOR A YEAR (2026-08-17).** That
  class has been styled in `styles.css` since the first version of this app — cursor, hover colour —
  and **nothing ever emitted it**: no table sorted except the growth table, which rolls its own via
  `?sort=`. The affordance was built, styled, and never connected. Now: mark a `<th class="sortable">`
  and call `S.sortTable(tableEl)` after each render. Five rules, each a bug already paid for:
  - 🔴 **"—" MEANS UNKNOWN AND SINKS IN BOTH DIRECTIONS** — never multiplied by the sort direction.
    This is the growth tables' rule (see further down) generalised: rendering an outage as a zero reads
    as "nobody is doing anything", and *reversing* the sort must not float the unknowns to the top.
    Empty cells count as unknown too — an absent handover note is not the earliest one.
  - 🔴 **The numeric test is ANCHORED (`$`), and an ISO DATE is why.** A permissive `parseFloat` returns
    **2026** for `"2026-08-02"`, so every date in a month compared EQUAL, ties held their original
    order, and sorting a date column did nothing while looking like it worked — on exactly the
    `data-sort` values Attendance and Leave pass. Anchored, it falls through to the text branch, which
    is *correct* for ISO because `YYYY-MM-DD` sorts chronologically as text. Caught by `ui.test.js`.
  - **`data-sort` carries the raw value wherever the display form does not sort** — Attendance prints
    "Aug 17" (alphabetical by month name) and "9:05 AM" (which puts 10:00 before 9:05); Leave prints a
    date *range*. Set it, or the column sorts by prose.
  - **The control is a real `<button>`** injected into the th, not a clickable th with `tabindex` —
    keyboard-operable and announced for free. `aria-sort` goes on the th and is **removed from the
    other columns**, because two columns claiming to be sorted is worse than none.
  - **Sorting reorders the DOM, so never key a row action to its POSITION.** Attendance's Edit button
    carries an index into the `rows` array and Payroll's carries `user_id`; both survive a sort. A row
    index would silently open the wrong person's record.
- 🔴 **`.table-wrap.tall` IS WHAT MAKES THE STICKY HEADER WORK, AND IT IS OPT-IN.** `position: sticky`
  resolves against the nearest scrollport. `.table-wrap`'s `overflow-x: auto` already makes it one on
  **both** axes (per spec, `visible` on one axis with a non-`visible` other computes to `auto`), but
  with an unconstrained height the header has nowhere to travel — so `thead { position: sticky }` is a
  harmless no-op until a height caps it. `.tall` (70vh) is a separate class **because several
  `.table-wrap`s live inside a modal**, whose `.modal-body` already scrolls, and capping them globally
  would put a second scrollbar inside the first. 🔴 And `border-collapse: collapse` **drops a sticky
  cell's borders** (they belong to the collapsed grid, which does not travel), so the hairline under the
  header is a `box-shadow` — don't "simplify" it back to `border-bottom`.
- **`.table-sticky-1` freezes the first column, for the two WIDE rollups only** (`.mon-tbl`,
  `.tg-tbl`). Both already scrolled horizontally, which meant scrolling the person's NAME out of view —
  so the numbers you were reading belonged to nobody, on the table a manager staffs from. Opt-in
  because each frozen cell costs a stacking context and a table that already fits gains nothing.
- 🔴 **REPORTS CAPS THE RENDER AT 500 ROWS — AND NEVER THE DATA.** This built *every* returned row into
  one string for `innerHTML`; an Attendance report is one row per person per day, so a six-month range
  is tens of thousands of `<tr>`s parsed and laid out synchronously, which visibly hangs the tab. Two
  properties are load-bearing: the count above the table stays the **server's** `d.count`, so the
  number is always true; and **the CSV export is untouched** (it goes straight to the API), so "I can
  only see 500 rows" and "I can only export 500 rows" are never the same sentence. The notice says so,
  because a capped table with a silent export is how somebody concludes the data is missing.
- **`dvh` with a `vh` fallback, in that order** (`.app`, `.side`, `.modal`, `.modal.as-drawer`, `.col`).
  On iOS/Android `100vh` is the viewport with the URL bar **retracted** — taller than what you can see —
  so a `height: 100vh` sidebar parked its own footer (user card, theme toggle, **Log out**) under the
  browser chrome, unreachable. 🔴 **Never delete the plain `vh` line** "because the `dvh` one supersedes
  it": a browser that does not know `dvh` discards that declaration and keeps the first, which is the
  entire mechanism.
- **`.col`'s height comes from `--board-top`, not a hardcoded 230px.** That constant encoded "topbar +
  page head + the toolbar's two rows" — and the toolbar *deliberately wraps* at narrow widths, so the
  moment it did, columns ran past the fold with their internal scroll misaligned. The token is
  overridden per breakpoint instead of guessed once.
- 🔴 **EVERY ICON IS `aria-hidden="true"`, SET ONCE IN `P()` (app.js).** All ~60 `ICON` entries are
  built there, which is the only reason it is worth doing centrally. Consequence to respect: **an icon
  can no longer be a control's accessible name**, so any control whose entire content is an icon MUST
  carry its own `aria-label` — the ✕, hamburger, bell, Coach FAB, Log out and both theme buttons all
  do. Adding an icon-only control? Label it, and check with the sweep in `ui.test.js`'s sibling audit.
  `focusable="false"` rides along because an inline `<svg>` is focusable by default in some engines,
  which would insert an unnamed Tab stop per icon — and a stop the modal focus trap would have to
  reason about.
- 🔴 **DEGRADING A READ TO AN EMPTY SHAPE IS ONLY SAFE WHERE ABSENCE AND FAILURE MEAN THE SAME THING.**
  Beyond `approvals.js` (below), four more sites did it and now name the failure instead:
  `manage.js` shift-templates (an empty Shift picker reads as "no templates exist", and the operator's
  next move is to duplicate one — while `Team.shift_template_id` decides whether a punch is late),
  `attendance.js` teams (a filter that cannot filter), `reading.js` (a canon somebody filled rendering
  as an empty state inviting their first book), and `dashboard.js`'s "my work" strip (a blank region
  where your work should be — better than the July 2026 false "nothing on you", still unreadable).
  🔴 **In every one, a 401/403 is EXEMPT**: it is the normal answer for a role that does not hold that
  data, and a warning that cries wolf on every load is one nobody reads on the day it is true.

- 🔴 **AN UNDEFINED CSS TOKEN FAILS SILENTLY AND INVISIBLY — `var(--accent)` cost this app five
  defects (fixed 2026-08-17).** `--accent` and `--fg` were used in 7 places and **defined nowhere**.
  A `var()` on an undefined property with no fallback makes the whole declaration *invalid at
  computed-value time*, which is **not** "ignore this line" — the property falls back to its
  **initial** value. So:
  | Site | Fell back to | What you saw |
  |---|---|---|
  | `.tp-bar{background:var(--accent)}` (`taskboard.js`) | `transparent` | **the Monitor's throughput chart drew eight correctly-sized INVISIBLE bars** over their labels |
  | `.tp-bar.tp-partial` gradient + dashed border | `transparent` / `currentColor` | the partial week was a thin grey outline |
  | `.tcard.picked{outline:2px solid var(--accent)}` | `currentColor` | bulk multi-select outlined a picked card in its own **text colour**, barely separable from its 1px border |
  | `.t-move:focus-visible{color:var(--fg);border-color:var(--accent)}` | inherited / `currentColor` | the only move affordance a **keyboard** user has ever had revealed itself with no focus edge |
  | `.filters .btn.on{border-color:var(--accent)}` (`styles.css`) | `currentColor` | a pressed filter toggle lost the green edge that made it look pressed |
  There is **no linter for this and no console warning** — the CSS parses, the element renders, the
  colour is just gone. **No global `--accent` was introduced**, deliberately: the four sites meant
  four different things (green for the green-on-green filter toggle, violet for interaction/focus
  and selection, green for chart data), and this design system already documents green vs violet
  roles. Inventing a fifth half-defined accent would have hidden the ambiguity instead of resolving
  it. **Before shipping a new token, grep that it is defined:**
  ```bash
  cd frontend
  cat static/js/*.js static/css/styles.css pages/*.html | grep -o "var(--[a-zA-Z0-9-]*" | sed 's/var(//' | sort -u > /tmp/u
  cat static/css/styles.css static/js/*.js | grep -o "\--[a-zA-Z0-9-]*[[:space:]]*:" | sed 's/[[:space:]]*:$//' | sort -u > /tmp/d
  comm -23 /tmp/u /tmp/d    # expect only: --dim- (built dynamically), --bg-subtle (has a fallback)
  ```
- 🔴 **EVERY `skeleton()` NEEDS AN OWNER FOR ITS FAILURE — use `S.loadErr` (2026-08-17).** There
  are 13 skeleton call sites and until this date **only `manage.js` ever replaced one on error**.
  Everywhere else a failed refetch left the skeleton on screen **forever**: `people.js`'s `load()`
  had no `try/catch` at all and is called straight from `oninput`, so a 500 was an unhandled
  rejection and the page simply read as *permanently loading*. `boot()` catches the **first**
  `pageInit` and toasts, but a toast is gone in 4.2 s and a skeleton is not — the honest signal (a
  stuck loader) and the informative one (the message) never coexisted, and **neither offered a way
  out**: a browser refresh was the only recovery and it discarded the filters that provoked the
  error. `S.loadErr(host, err, retry)` is the one definition. It reads `err.detail` **first**
  (`api()` has already flattened FastAPI's shape into it; `err.message` alone gives you "Failed to
  fetch" for a real 403 with a real explanation).
- 🔴 **DEGRADING A READ TO `[]` IS ONLY SAFE WHERE ABSENCE AND FAILURE MEAN THE SAME THING — and on
  an ACTION QUEUE they are opposites (2026-08-17).** `approvals.js` fetched its two halves with
  `.catch(() => [])` each, so a 500 on either endpoint rendered a **shorter pending list with no
  warning**: an approver read "Nothing to approve", believed they were caught up, and left real
  requests sitting. Same failure the Watcher bridge's empty state hid twice (AGENTS.md §5). It is
  still fail-soft — one broken endpoint must not cost you the other's requests — but the failure is
  now **reported** (`failed[]` → a `.notice warn` inside the card, above the count it qualifies) and
  the empty state says **"Nothing loaded."**, not "Nothing to approve", because that is a claim the
  page cannot make while a source is down.
- **`.notice` is the shared inline-explanation shape** (`styles.css`) — for text that *qualifies*
  the content beside it. 🔴 **Do not use `.pill` for a sentence**: it is 11 px, uppercase, with
  letter-spacing, so prose in it comes out as a wall of tiny capitals (which is what the approvals
  warning did on its first pass). `.notice` deliberately mirrors the task board's `.tb-note`
  drawing — but `.tb-note` lives inside `taskboard.js`'s own injected `<style>`, so no other page
  can reach it. **Shared shapes belong in `styles.css`.**
- 🔴 **`--muted` IS TEXT and must clear 4.5:1.** It was `#8A939F` = **3.1:1** on `--card` (dark:
  `#6D7A73` = 3.96:1) — both failing WCAG AA — while being used ~54 times, almost always at 10–12 px
  (`.navlabel`, `.empty`, the Monitor legend, `.tp-n`, `.tb-shown`). Now `#6B7480` (4.73:1) and
  `#859189` (5.4:1). This **narrows the gap to `--sub`** on purpose: three text tiers on a white
  card cannot all be both distinct and legible, and legible wins. If you want a lighter grey for
  something **decorative** (an icon, a gridline), add a token for it — don't lighten this one back.
- 🔴 **Keyboard focus: `:focus-visible`, and it lives in `styles.css` for everything non-input.**
  Inputs got a violet ring in 2026-07; **nothing else in the app had a `:focus` style at all** until
  2026-08-17 — no `.btn`, no `.iconbtn`, no `.tabs button`, no `.nav a`, across ~220 buttons. They
  fell through to the UA outline, which is invisible on a green-filled primary button and on every
  dark surface. Three properties of the rule: **`:focus-visible` not `:focus`** (a mouse click would
  otherwise leave a ring parked on the button, which is why authors delete these rules again); an
  **`outline` + `offset`, never a box-shadow** (several of these elements own their box-shadow and a
  focus style must not erase their depth); and **no `!important`**, so the growth table's own
  `.dc-main` / `.dc-more` / `.pace-row` focus rings — single-class selectors that come later in the
  file — still win.
- 🔴 **`toast()` writes into an `aria-live` region, and that is not decoration.** `api()` flattens
  every failure into a toast, so it is the app's **only** error channel — and until 2026-08-17 it
  was a plain div appended to `<body>`, which assistive tech never announces: a screen-reader user
  pressed Approve, the request 403'd, and **nothing whatsoever reported it**. Two details that are
  easy to undo: the region must **exist in the DOM before** the message goes into it (which is why
  the attributes are on the `#toasts` container, not on each toast), and it is **`polite` with
  `role="alert"` only on error toasts** — one assertive region for everything would interrupt
  whatever the user was reading to say "Photo updated".
- **`.x-close` is a real `<button type="button">` with an `aria-label`**, in both `modal()` and the
  Coach panel. It was a `<span>`, so the ✕ that closes every dialog in the app could not be reached
  by keyboard at all — Esc working (see `modal()` below) is the only reason that was survivable.
  Its CSS carries four resets (`background`/`border`/`padding`/`width`) to strip the UA chrome, and
  the Coach panel's own `#coach-head .x-close` rule **repeats them** because it sets `color` and
  would otherwise re-inherit them.

- 🔴 **"Is this work mine?" is `t.mine`, never `t.assigned_to_id === S.user.id`** (fixed
  2026-08-05). Naming somebody on a phase/sub-task is delegation and puts the card on their board
  (AGENTS.md §5) — the server's one definition is `task_perms.is_assigned`, published on every card
  by `serializers.task_card` as **`mine`** (+ `my_slots`, how many breakdown slots you hold). Both
  the Overview's strip and the board's "My work" button re-derived it as the narrower
  `assigned_to_id` test, so a card **led by a colleague with a step named to you** sat on your Task
  Board while the Overview said *"0 open tasks · nothing on you right now"* — the work was one click
  away and the page told the delegate their plate was empty. Two surfaces, two definitions of one
  rule. Don't add a third: filter on `mine`, and if a card's lead is somebody else say so (that is
  the "N steps on you" pill). An Atrium-owned card has no `mine` (its owners are roster emails) and
  correctly falls out of both.
- **Monitor's numbers are comparative signals, not an effort measure.** `renderMonitor` renders
  Load / Open (+"as steps") / Overdue / Sitting / Cycle / On time / Done·7d from
  `/api/tasks/summary?days=N`. Three things not to "tidy": a `null` metric renders an **em dash, not
  0** (`null` means "no basis to judge" — a person who shipped nothing datable must not look like one
  who missed every deadline); `MONITOR_WINDOW_DAYS` is **sent to the server**, never assumed, so the
  legend and the numbers can't disagree; and `.mon-legend` states that Load is relative to the team's
  median — it is load-bearing copy, because tasks carry no size estimate. See AGENTS.md §5.
- **`?assignee_id=` is a FIELD filter and must stay one** — it matches `Task.assigned_to_id` only,
  which is exactly what a manager asking "what is on Jerome?" needs. "My work" is a separate
  client-side flag (`mineOnly`, tested in `matches`) precisely so widening one never widens the
  other. It is a **toggle**, and `applyView` reflects it with `.on` on `#f-mine`: a board showing a
  subset while every control reads "no filter" is indistinguishable from a bug. Since 2026-08-06 the
  toggle **composes with the other filters** instead of routing through `applyView`, which reset
  them — so turning it on silently discarded the client and department you had picked, and turning it
  off discarded them again rather than restoring the board you came from.
- 🔴 **One field, ONE control (the board's rule since 2026-08-06).** A field settable from two places
  can display two different answers, and every instance of it here was already doing so:
  | Field | The one control | What was removed, and why |
  |---|---|---|
  | status | drag · the card's `.t-move` select · the bulk bar — all through `moveCard` (optimistic, undoable, rolls back) | **Status is no longer in either Edit form.** On a Sentinel row it was worse than redundant: `TaskUpdateIn` has no `status`, and Pydantic ignores extra fields, so picking a column and pressing Save changes **did nothing at all** and still toasted "Task updated". On an Atrium card it had to go as a SECOND request (a stage move has its own endpoint), so a failure there left every other field saved and the card in its old column. A new card's column still comes from the column's own "Add card" (`presetStatus`) |
  | client visibility | the footer toggle (`atriumControl`) | the `#a-visible` checkbox in "Edit client card" |
  | department | one label, "Department", in both the drawer and the form | the drawer said "Routed to" for the same `assigned_team_id` |
- **A control must never be able to only fail** — the rule the bulk bar already followed ("so the bar
  never promises a 403"), applied to the footer. `atriumControl` renders a **chip** for an
  already-shared Sentinel row (there is no un-share; re-pushing happens automatically on every edit,
  and a failed push has its own Retry), and a **disabled** button with the reason in its `title` when
  the task has no client (`publish()` can only answer "no Atrium client linked"). Park and Submit for
  review are hidden on a card in a done column for the same reason — nothing to pause, and the
  approval a review authorises is spent by the completion that already happened.
- 🔴 **The quiet card, and the record behind it (2026-08-06).** Ported from
  `frontend/taskboard_ux_prototype.html`, which is kept as the reference drawing. **A card says WHO
  is on it and WHETHER it is in trouble, and nothing else** — a signal every card carries is not a
  signal, so the priority word, the filled label pill, the creator tag, the attachment count and the
  `done/total` text all came off it. Five rules, each of which is a decision:
  - **ONE flag per card, at most** (`flagOf`, in `taskboard.js`): client-asked → not-synced →
    in-review → changes → approved → urgent → parked → filed → unclaimed. It replaced a row of five
    pills that could all be lit at once on a 288px card, at which point none of them was read.
  - 🔴 **"Parked" is derived from the COLUMN, not from `on_hold`** (`isParked`, 2026-08-14). Sitting
    in the parked column *is* the hold — the rule `task_workflow._sync_hold` enforces on every
    Sentinel move — and the flag plus the dashed `.quiet` card now both ask that. `on_hold` alone was
    false for two kinds of card that were nevertheless sitting in that column: an **Atrium** card
    (`PATCH /{id}/status` takes the bridge branch, which moves the client card's STAGE and nothing
    else; over there `on_hold` is a separate flag with its own checkbox on the Atrium edit form), and
    a Sentinel row dragged in before `_sync_hold` shipped. Both rendered as ordinary live work in the
    Parked column — reported live 2026-08-14, one client card with no flag and no dimming beside two
    that had both. The record's notice ladder and the Overview's "my work" strip (`dashboard.js`,
    `flags`) derive it the same way, or the three surfaces disagree about one card. By **stage**,
    never the label "Parked" — Manage renames that column.
  - 🔴 **Overdue is deliberately NOT in that ladder.** The DATE carries it, in red, at the other end
    of the card ("Jul 31 · 6d late"). Putting it in the ladder spends the one flag slot on something
    already said — which is exactly how the single card that was both late AND had an open client
    change request showed only "late", hiding the actionable half.
  - **The label is a 6px dot** in the label's own colour (`S.colors.labels`), named in its `title`
    and spelled out in the record. Within one client it never varies, so as a filled pill it was the
    loudest thing on the board while saying the least.
  - **Faces, not names**: the lead is ringed green, anything of yours is ringed violet, support is an
    overlapped stack that spreads on hover. 🔴 Initials chips are **neutral grey on this board only**
    — the house avatar is a green gradient, and a green chip inside the green lead ring read as one
    blob. The rest of the app keeps the green chip.
  - **Progress is a 2px hairline** on the card's bottom edge, present only when there is a
    breakdown — which is what made 🔴 **`.col-list > .tcard{flex:0 0 auto}`** load-bearing. `.col-list`
    is a flex **column**, so cards are flex items that the browser SHRINKS once a column holds more
    than fits, rather than scrolling. That was survivable while a card had no `overflow` (the text
    just spilled over the card below); with `overflow:hidden` it became silent truncation — clipped
    titles and no footer at all (reported 2026-08-06, on a short window). The column scrolls; cards
    do not shrink.
  The **record** (`openDetail`) reads in the order the questions get asked: kicker + name → **ONE
  notice** (the same worst-true-thing ladder, replacing up to ten chips and two stacked warning
  boxes) → **who is on it** (`.tb-crew`, lead + support + how many steps each holds) → **four facts**
  (stage · due/delivered · progress · priority) → the record on the left, **Work / Comments /
  Activity tabs** on the right. Two rules: **nothing is printed twice** (the `.tb-kv` list carries
  only what the facts strip does not — due date and priority used to appear twice, two inches
  apart), and 🔴 **the three panes stay in the DOM and are toggled with `[hidden]`, never
  re-rendered** — the breakdown wires eight handlers per row and re-wires itself after every save,
  and the comment box may hold half a sentence. The notice also reports **which rung it used**
  (`noticeKind`), because a card can be parked AND late: the internal field list prints the hold
  reason exactly when the notice didn't, so the one piece of prose no other surface carries can
  never vanish.
- 🔴 **The record's footer is ONE row, and that is a constraint** (2026-08-06 — it wrapped onto two,
  stranding the primary action under a red Delete). Left to right: the **Move to** select (you used
  to have to close the card to move the card), Edit, the two or three actions this STATE offers,
  **More** (a `<details>` menu — filing, Not ours…, the Atrium bridge, Retry, Delete), then Close +
  **Mark complete**. Three consequences:
  - **Park lost its button.** Parking a card *is* putting it in the parked column, and Move already
    does that — the same "one field, ONE control" rule as the row above. Choosing the parked stage
    asks for the reason and calls the same `park` endpoint, so `hold_reason`/`resume_to` are still
    written by `task_workflow` and never by a bare status PATCH. `askReason` grew an **`onCancel`**
    for it: abandoning the prompt has to put the select back, or the control claims a move that
    never happened.
  - **Mark complete resolves its target column by STAGE** (`isDoneStatus`), never by the label
    "Completed" — see AGENTS.md §5 (D13). The review gate can still refuse it with a 409, which the
    toast reports rather than the button pretending to be disabled.
  - **A shared Sentinel row's "✓ Shared with the client" chip is gone.** A state does not belong in
    an actions menu, and the record says it twice already (the kicker ends "· shared with the
    client"; the internal list carries "Client card · Published").
- 🔴 **The create/edit form is PROPERTY ROWS, and nothing routing-related is collapsed** (2026-08-11;
  prototype: `scratchpad/new-task-modal-prototype.html`, option 2 of three). It was a two-column grid
  of boxed fields with **every** routing field — client, department, lead, support, priority, campaign,
  service type — behind a collapsed "More options". "Simple by default" (2026-07-27) was right that
  filing must need a **name and nothing else**; the cost was that the eleven fields deciding where a
  card *goes* were both one click away **and, being collapsed, unread**, so work reached the board
  unrouted because the form never asked. Now: name and description lead as **plain text with no box**
  (the modal head already says this is a task), then one labelled **row per field**, then the
  client-safe note in its own block, then a `<details>` holding only the four genuinely rare fields.
  Filing still needs a name only — every row is optional and a labelled row reads as skippable in a
  way a boxed field does not. Five things not to undo:
  - **Controls sit flush** — transparent ground and border — **until hovered or focused**, written as
    `:not(:focus)` so the app's own focus ring (violet in light, green in dark) stays the one that
    paints. Nine boxed selects in a column read as a wall of chrome, and the row's label already says
    what the control is. A `select[multiple]` is the exception and stays boxed: it is a list, not a
    value.
  - 🔴 **`.tf-row[hidden]{display:none}` is load-bearing.** The UA's `[hidden]` rule loses to **any**
    author `display` declaration regardless of specificity, so `.tf-row{display:grid}` alone leaves a
    hidden row on screen — which is exactly how the prototype rendered "Client sees it" on a card with
    **no client**. Same trap as the collapsed hold form. Any new conditional row needs the same guard.
  - **The naming rule is now live feedback** — the three `Campaign | Action | Detail` chips fill in as
    their pipes are typed (`syncPattern`) — and is **still not a validator**. A blank name still saves
    as "Untitled task": §3 of the placement guidelines is entirely about capturing unplanned work the
    moment it appears, and a form that refuses a badly-shaped title loses it. `NAME_HINT` stays printed
    in full because the chips cannot carry the "anything else" and "leave the client out" halves of it.
  - **Priority stays a `<select>`,** deliberately, though the prototype drew a four-way segmented
    control. `vocab.priorities` is DB-driven and renameable, so a fixed four buttons with colour-coded
    dots would be both a status-label literal (AGENTS.md §5, D13) and a hardcoded count — and it would
    be the fourth priority control on this board rendered unlike the other three (drawer, bulk bar,
    Atrium form).
  - **`Ctrl`/`Cmd`+`Enter` submits, bound to `m.root` and not the document** — this form can sit under
    a confirm, and a document-level handler fires for whichever modal is on top. Plain Enter is
    deliberately not it (three of the fields are textareas). It is also why `save()` now has an
    **in-flight guard**: a shortcut is easy to fire twice, and on create a second POST is a duplicate
    card, not a repeated edit. The guard releases in the `catch`, because the modal stays open on
    failure so the typed work survives a 403.
  `extrasOpen` shrank with the block it opens — it tests only the five fields still inside it, so
  adding one that has moved out to a row does nothing at all. The five row-label icons (`building`,
  `eye`, `briefcase`, `user`, `list`) went into **`S.ICON` in `app.js`**, not inline here: this file
  deliberately holds no SVG of its own.
- 🔴 **The toolbar: three rows of chrome became two** (2026-08-06, reported as "too many filters and
  not all usable"). It was **fourteen controls** above a board whose whole job is to be scanned — and
  the three questions a Monday morning starts with (what is late · what has a client asked for · what
  is waiting on my approval) were not among them, because they were not askable at all. The rule
  applied: **a control earns its place by answering a question somebody actually asks**; everything
  else is a destination and goes behind **More** — reachable, not resident. Nothing was deleted.
  | Was | Now |
  |---|---|
  | `Overdue` checkbox · `My work` button · `All Priority` select | **attention pills** (`3 overdue · 1 client asked · 2 to approve · 4 urgent · 6 on you`) |
  | Requests · Filed by me · Past work · Select | the **More** menu in the header |
  | `Save view` button + a `Saved views…` select that was empty for anyone who had never saved one | "Save this view…" under More; the picker **appears only once you have one** |
  | nothing | a **Clear** that exists only while something is filtered, and `N of M` beside it |
  Four properties of the pills are load-bearing:
  - **Independent toggles, not one-of.** A single-choice row would undo the fix that made My work
    *compose* with the other filters — "mine + overdue, on this client" is a real question that was
    unaskable for months. They AND together.
  - **Counted over `inScope`** — the cards the selects and the search left on the board, *before* the
    pills apply — so pressing one never moves another's number. `render()` splits the two passes for
    exactly this; don't collapse them back into one `matches()`.
  - **A count is why a pill beats a select**: "3 overdue" is information whether or not you press it,
    and a dropdown reading "All Priority" is not. Zero is shown dimmed, not hidden — a pill that
    vanishes takes its question with it.
  - **`urgent` reads the card's own priority, client-side.** The old select sent `?priority=` and
    re-fetched; as a pill it must be counted from the same set as its neighbours, or the five numbers
    would describe five different boards. `list_tasks` has no cap, so nothing is lost.
  Two consequences worth knowing: **a saved view written before this** carries `overdueOnly` /
  `mineOnly` instead of `att`, and `applyView` reads both — those live in each person's localStorage,
  so dropping the old keys would quietly change what their view shows. And the **client request queue
  moved behind More**, so `refreshRequestCount` also lights a dot on the menu — a waiting request
  that is invisible until someone opens a menu is a request nobody answers.
- 🔴 **The filter bar is ROLE-SHAPED — one bar for everyone was two different bad bars** (2026-08-14,
  reported as "fix the filters of a team lead"). Every viewer got the same row of controls, so the
  two ends of the ladder both got a bar that could not be used to ask anything: an **employee** was
  offered a picker of every department in the company, all but one of which empty their board; a
  **team lead** got that same flat list with nothing marking the departments they actually lead, and
  no way at all to ask "what is on ME today" except by reading past everyone else's cards. Neither
  control was *wrong* — the server has always scoped the answer — they just answered no question.

  | | employee / intern | team lead | AM · admin · super · viewer |
  |---|---|---|---|
  | `#f-team` | only when they are in **2+** departments | grouped: **My departments** / Other | flat, all of them |
  | `#f-assignee` | — (they have no multi-person view) | grouped: **My departments** / Elsewhere | flat |
  | `#scope-seg` | **On me** (default) · My department | **Everything** (default) · My department(s) | — |

  Four rules behind that table, each of which the obvious alternative breaks:
  - 🔴 **Group, never truncate.** Every one of these filters can legitimately reach outside the
    viewer's own department — a card they raised for another team (`_created`), a person from
    another team holding their work (a lead may name anybody they can see). Cutting those options
    removes real queries; labelling them removes only the confusion.
  - 🔴 **Each role's DEFAULT scope reproduces the board that role already had.** An employee opens
    on `mine`, a lead on `all`. An upgrade that quietly narrows somebody's board is indistinguishable
    from cards going missing.
  - 🔴 **A lead gets no "On me" tab** — the attention pills two controls to the right already carry
    **on you**, and a tab that repeats a pill on the same bar is the duplication this toolbar was cut
    from fourteen controls to six to remove. The employee's `mine` is not that duplicate: it is their
    *default scope*, so it defines the board rather than filtering it.
  - **A control that cannot change the answer is not rendered** (`showTeamFilter`, `showScopeSeg`) —
    the same rule the saved-views picker, Clear and the campaign filter already follow.

  The scope switch only ever NARROWS: every card on the board already passed the server's `can_view`,
  so it can hide but never reveal. `dept` tests the card's `assigned_team_id` against the viewer's
  set and deliberately does **not** fall back to `mine` for a card with no department — "what is my
  team carrying" is a question about routed work.
- 🟡 **A `height` on a form control must reset its padding.** The base rule gives every `select` a
  `padding:10px 12px`; forcing `height:30px` on top of that leaves a **ten-pixel content box**, and a
  select clips its label to that box — the bulk bar's three dropdowns read as "Move to" with the
  bottom half sliced off (found 2026-08-06). Nothing overflows and nothing errors, which is why it
  survived: the element is exactly the height it was told to be. Every shrunken control in
  `taskboard.js` (`#tb-bulkbar select`, `.tb-facts select`, `.tb-move select`, `.tcard .t-move`)
  zeroes the vertical padding for this reason.
- **A card on a retired status gets its own column, marked, and takes no new cards.** `columnsFor`
  appends any status the vocabulary no longer lists. Before this, `renderBoard` bucketed by
  `t.status` and then rendered only `STATUSES`, so those cards **vanished** — no error, no empty
  state. That is the read-side of the failure AGENTS.md §5 documents for deleting a `task_vocab` row,
  and the board was the surface hiding it. `moveOptions` puts the orphan status in the card's own move
  select too, or it would read as the first column while sitting somewhere else.
- **`sw.js` must not intercept navigations** — the `/kiosk` exception (`sw.js:46-53`) is the ONLY
  one allowed (offline kiosk boot). Caching other navigations resurrects the 2 s stale-login flash.
- **No inline `<script>`** — CSP `script-src 'self'`; `who-we-are.js` exists precisely because an
  inline block was silently blocked and blanked the page.
- **`element.onclick = handler` passes the Event as arg 1** — always `() => handler()`.
- **`modal()` STACKS, since 2026-08-06** — each call creates and removes its own overlay. It used to
  reuse one `#modal-ov` node and overwrite its `innerHTML`, so opening a second dialog destroyed the
  first and closing the second left nothing behind. The task board nests five deep (Park / Request
  changes / Send back / Delete confirm / Past work over an open task), so **Cancel threw the user out
  of the card they were reading** — and the card's own close never ran, which is how `?open=<id>` was
  left in the URL pointing at a modal that wasn't on screen. Three things follow:
  - **`onClose` runs on every path** (button, ✕, backdrop, Esc). Anything that must be undone on
    close hooks there — `taskboard.js`'s `openTaskModal` clears `?open=` that way — rather than
    re-pointing the three closers by hand and hoping it found them all.
  - **Esc closes the TOP modal**, via one document listener held while the stack is non-empty. The
    old code added one per modal and removed it only if Escape was actually pressed, so every dialog
    closed by a button leaked a listener for the page's lifetime.
  - 🔴 **NOTHING INSIDE A STACKED DIALOG MAY BE FOUND BY `id`.** Ids are not unique while a stack is
    open, so scope every lookup to the `root` the call returns — `.modal-body` from `m.root`, never a
    document-wide query (which is what `showPastWork` used to guess at). **Scoping is necessary but
    not sufficient for an id:** the close button used to be `qs("#modal-x", ov)`, and a scoped
    `querySelector("#dup")` is entitled to consult the document's id map and answer **null** because
    the first match lives in another subtree. jsdom does exactly that, so opening a SECOND dialog
    threw `Cannot set properties of null` and left the ✕ wired to nothing (found 2026-08-17 by the
    harness below). **`id="modal-x"` is therefore gone**: the head's ✕ is located once via
    `.modal-head .x-close` — scoped that way because a caller may render its own `.x-close` controls
    in the body, as `gym.js`'s routine editor does — and held by reference. Prefer a class + a held
    reference over an id for anything a stack can duplicate. The one id that remains is the title's,
    and it carries a **per-overlay counter** (`modal-title-N`) precisely because `aria-labelledby`
    pointing at a duplicated id resolves to the BOTTOM dialog's title.
  - 🔴 **THE DIALOG A11Y CONTRACT (2026-08-17), and every clause is load-bearing.** `modal()` had
    none of this while `initCommandPalette` — 600 lines further down the same file — had all of it, so
    a keyboard user could open a task, press Tab, and walk out of the dialog into the page behind
    while the overlay still covered the screen, operating controls they could not see. Esc closing the
    top modal was the only reason it was survivable.
    | Clause | Why it is the way it is |
    |---|---|
    | `role="dialog"` + `aria-modal="true"` + `aria-labelledby` | announces itself as a dialog, and as **which** dialog |
    | `tabindex="-1"` on `.modal` | a focus target for a body with no control of its own (a plain message). Tab can never reach it, so `.modal:focus{outline:none}` in styles.css stops a UA ring round the whole dialog |
    | initial focus is **synchronous** | callers focus their OWN field right after `modal()` returns (`#t-name`, `#a-title`, manage.js's generated password, growth.js's entry box). Running first lets their explicit choice win; a `requestAnimationFrame` here would fire AFTER them and **steal focus back** |
    | initial focus **skips the ✕** by reference | it is first in DOM order (head precedes body), and opening a dialog with the keyboard on "discard this" is the one default worth avoiding. By reference, not by class — a caller's `.x-close` buttons in the body are ordinary controls |
    | the ✕ **stays in the Tab cycle** | `trapTab` reads `focusablesIn` unfiltered. Removing it from the cycle would make it keyboard-unreachable, which is the bug this change exists to fix |
    | `focusablesIn` filters on `offsetParent` | drops controls inside a `[hidden]` row or a shut `<details>` — the task form has both. A trap that counts invisible controls silently eats Tab presses |
    | `:not([disabled])` in `FOCUSABLE` | this board renders genuinely disabled controls (a non-delegator's support picker). A trap whose boundary is a dead control cannot be escaped forwards |
    | Tab handled in the **one shared** listener | same reason as Esc — a listener per layer is how the pre-2026-08-06 code leaked one per dialog |
    | focus restore is **per-entry**, not one shared slot | that is what makes it stack-aware: closing a nested confirm returns you to the control inside the task card underneath, not to whatever opened the bottom of the stack |
    | restore is **guarded three ways** | the element may have been REMOVED by the very save the dialog performed (a re-rendered board row); then it falls back to the dialog now on top, so focus never lands on `<body>` |
  Rendering an editor inline instead of in a dialog (`gym.js`'s routine editor in `#tabc`) is still
  fine — it just is no longer forced.
- 🔴 **`hidden` is honoured by ONE rule, `[hidden]{display:none !important}` at the top of
  styles.css** — and it is load-bearing. `[hidden]` normally lives only in the UA stylesheet, so ANY
  author rule that sets `display` silently disarms the attribute and every `el.hidden = …` becomes a
  no-op with no error. It bit three times before the global rule went in (2026-08-06): `#tb-bulkbar`
  (`.row`) showed an empty white strip under the board filters; `#t-campaign-wrap` (`label.field`)
  put the Campaign field on **every** task, defeating the "only offer it for campaign-shaped services"
  change of the day before; `#tb-req-n` (`.pill`) rendered a violet **0** on an empty Requests queue.
  Do not remove it, and do not use `hidden` for something that should stay laid out — use a class.
  (🔴 Historical example only: `#t-campaign-wrap` no longer exists. The Campaign field is now offered
  on **every** task deliberately — the reveal rule made it unreachable for exactly the post-launch
  one-line work that needs it, see [docs/TASKBOARD_REBUILD.md](../docs/TASKBOARD_REBUILD.md) §7. What
  the field looks like today is the same thing that 2026-08-06 bug looked like; the `[hidden]` rule
  it motivated is still load-bearing for `#tb-bulkbar`, `#tb-req-n` and `#f-campaign`.)
- **A KPI class only styles inside `.kpi`** — `.k-val`, `.k-label`, `.k-ic` and `.k-sub` are all
  written as `.kpi .k-val` descendants, so a `<div class="k-val">` in a plain `.card` is styled by
  **nothing** and looks "unfinished" for no visible reason. The Overview's "my work" strip did this
  until 2026-08-05 (three near-empty white slabs, each with one inline `font-size:30px`). Either put
  the value inside a `.kpi`, or give the block its own classes — `renderMyWork` took the second
  route (`.mw-*`) because its tiles are LINKS into `/tasks`, not read-only metrics, so they need
  affordances a kpi deliberately doesn't have.
- **Two renderers must never share a host element.** `renderGoals` and `renderBodyStats` both wrote
  `#gym-body` and each set `innerHTML`, so whichever fetch resolved last silently erased the other
  card. They own `#gym-goals` / `#gym-body` now — give every async renderer its own node.
- **`growth.js` must not define `window.pageInit`.** The Overview loads `growth.js` AND
  `dashboard.js`; whichever assigned `pageInit` last would win, silently. `growth.js` exports
  `window.GrowthPanel` only, and `/growth`'s controller is the separate `growth-page.js`.
- **A component that queries `S.qsa` document-wide must not collide with its host's markup.**
  `GrowthPanel` keys its collapsibles off `details[data-ui]`; the task board it now shares a page
  with uses `data-uid`. Check before adding an attribute selector. (`TeamGrowth` scopes every
  `S.qs`/`S.qsa` to its own `root` for the same reason — its rows carry `data-uid` too.)
- **Never build a list of task statuses from LABEL literals** — statuses are renameable in Manage,
  and a rename ships in the deploy now (`task_config.RENAMED_STATUSES`). The Monitor's workload bar
  did exactly this (`["To Do","In Progress","Revision Needed","Blocked"]`) and the 2026-08-04
  Blocked → Parked rename took it from covering **18 of 18** open cards to **8**, with no error and
  no empty state — the parked work just stopped being drawn. Any status somebody *added* had never
  been counted either. Derive from `/api/vocab` (`STATUSES`) and switch on **`STAGE_OF[status]`**,
  never the name; the same rule is why `isDone` asks the stage rather than comparing to "Completed".
- 🔴 **"—" in the growth tables means UNKNOWN, and must never be rendered or sorted as a zero.**
  A person the Mastery Engine couldn't answer for shows a dash, sorts LAST in both directions, and
  is excluded from the named segments. Rendering an outage as a team of 0%s reads as "nobody is
  doing anything" — see AGENTS.md §5 on fail-soft bridges.
- **Re-rendering a chart into the same host is fine, but `charts.js` keeps one registry seat per
  host** (`mountChart`). The Overview redraws the clock-in trend on every scope change; without the
  dedupe, a later theme flip would replay every stale scope into that element first.
- Forgetting the `CACHE` bump ships stale assets to everyone (AGENTS.md §5 has the full two-layer
  cache story; the server's `Cache-Control: no-cache` half is pinned by backend tests).
- No React, no bundler, no TypeScript — keep matching what's here.

## Status (volatile)

- Live: `https://sentinel-585951669065.asia-southeast1.run.app` — serving revision
  **`sentinel-00166-f8d`** (verified 2026-08-17: full `status.traffic` array read, 100% to latest).
- `ui.test.js`: **72 assertions** (2026-08-17). It needs `jsdom`, which this repo deliberately does not
  vendor (no `package.json` — AGENTS.md §8), so point `NODE_PATH` at any install that has it:
  `$env:NODE_PATH = "<dir>\node_modules"; node frontend\ui.test.js`.
- `sw.js` `CACHE` currently **`sentinel-v104`**. 🔴 This line and the `sw.js` entry in the file map
  above had drifted to **v74** and **v94** while the file said `v99` (caught 2026-08-17). Two stale
  copies of one number in one document: **the file is the source of truth** — `frontend/sw.js:6`.
- 26 JS files under `static/js/`; 20 page shells (the header above said "19 thin HTML shells" and the
  file map "19 shells" — both were stale too).

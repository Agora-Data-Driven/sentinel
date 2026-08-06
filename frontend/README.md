# frontend/ — the Sentinel UI

Vanilla JS, no framework, no bundler, no build step: 19 thin HTML shells under `pages/`, one
controller file per page under `static/js/`, one stylesheet, a PWA service worker for the offline
kiosk. Operating rules (CSP, cache bumping, `api()`-only fetches) live in
[../AGENTS.md](../AGENTS.md) — this file is the unit map + cookbook.

## File map

| Entry | What it is |
|---|---|
| `pages/*.html` | 19 shells (~0.7 kb each; JS renders everything): dashboard, attendance, approvals, gym, growth, reading, academy, philosophical, spiritual, people, leave, north-star, reports, settings, manage, payroll, login, kiosk, scanner. Routes registered in `backend/app/main.py:381` (`_PAGES`; `/login` is its own route) |
| `static/js/app.js` | The shell every page loads: `NAV` array `:78` (roles/`min`/`hideRoles` gate visibility), `api()` (CSRF echo + FastAPI error flattening), `toast`, `skeleton`, `modal`, `esc`/`qs`/`qsa`, `ICON`, `avatar`, command palette (`initCommandPalette`), Coach FAB, `setTheme`/`engineUrl`/`themeEmbeds` (hands our light/dark to every embedded Mastery Engine) |
| `static/js/taskboard.js` | Mountable Kanban (`TaskBoard.mount`). Optimistic DnD (native HTML5 — deliberate, see AGENTS.md §9), SSE reload, quick-add, Atrium-card editing, and the lifecycle controls: Park/Resume, Submit/Approve/Request changes, Past work. **"My work" is a client-side toggle over the card's `mine` flag, NOT the `?assignee_id=` filter** — see the gotcha below. **Support** (many people per card, since 2026-08-06): `supportOptions` builds the picker and mirrors the server's delegation rule (a non-delegator's list contains only THEM; a colleague already on the card renders `selected disabled` so the list round-trips instead of 403ing), `supportStack` draws the overlapped avatars — reading `support` for a Sentinel row **and** `atrium_support_names` for a client card, because both kinds have support and only one has Sentinel users |
| `static/js/tasks.js` | **The Task Board page** (`/tasks`) — its own page again since 2026-08-03 (decision D7); a thin shell that mounts `taskboard.js` full-width. It was embedded in the dashboard from 2026-07-26 until then, so `/dashboard?open=<id>` forwards here forever (the notifications minted in that window are permanent rows) |
| `static/js/dashboard.js` | **The Overview** (`/dashboard`, labelled "Overview" since 2026-08-03): greeting + the day strip (attendance/gym as two buttons), then `GrowthPanel`'s rings, the **"my work"** strip (`renderMyWork` — three `.mw-tile` doors into `/tasks` + the "Up next" shortlist, **soonest deadline first**, undated last; fails silently; "mine" = the card's `mine` flag, see the gotcha below), `GrowthPanel`'s ledger, and — admins only, last — the org KPIs/chart/late list/handovers |
| `static/js/growth-page.js` | `/growth` = a manager's read-only view of ONE person (`?user=<id>`); without a `?user` it redirects to the Overview |
| `static/js/attendance.js` · `approvals.js` | Time page · combined attendance+leave approvals inbox (team_lead+) |
| `static/js/gym.js` | Calendar, no-lock day editor, saved routines (one-tap workout templates), history |
| `static/js/growth.js` | **`window.GrowthPanel`, a component — not a page controller.** `mount(S, root, {userId, ringsHost, mast})` renders the 4-dimension compass (each ring links into its engine tab) and the ledger (pace band, per-dimension details, Mentor Library import). `ringsHost` splits the two so the Overview can put the task board between them |
| `static/js/reading.js` | Reading canon |
| `static/js/academy.js` | Mastery Engine iframe (Professional tab) |
| `static/js/engine-tab.js` | ONE controller for the Philosophical + Spiritual tabs — each shell pins a program via `<body data-program>` → iframe `?program=` |
| `static/js/kiosk.js` | QR scanning + **IndexedDB offline punch queue** (syncs every 30 s) |
| `static/js/login.js` | Portal bounce + "not a Sentinel user" messaging |
| `static/js/northstar.js` · `who-we-are.js` | North Star page (iframes `static/who-we-are.html`) · that page's reveal/count-up interactions (extracted from an inline script — CSP) |
| `static/js/people.js` · `leave.js` · `reports.js` · `settings.js` · `manage.js` · `payroll.js` · `charts.js` | One per page + the shared canvas charts helper |
| `static/js/devreload.js` | **Live reload — localhost only.** Loaded by `app.js` behind a hostname test; listens to `/api/dev/reload` (SSE). A **.css** save is hot-swapped in place (the `<link>` href is re-pointed — no reload, so the open task card, filters and scroll position survive); anything else reloads. Also **unregisters the service worker locally**, without which a reload can serve the pre-edit file from cache. Never loads in production — see the gotcha below |
| `static/css/styles.css` | The whole design system (token-driven, dark mode via overrides) |
| `static/vendor/html5-qrcode.min.js` | The only vendored lib — CSP blocks CDNs |
| `static/who-we-are.html` | North Star manifesto content (served statically, iframed) |
| `sw.js` | Service worker: **`CACHE` key line 6** (currently `sentinel-v83`), `CORE` precache list, network-first assets; navigations NOT intercepted except **`/kiosk`** (`:46-53`). **Not registered on localhost** (except `/kiosk`) since 2026-08-06 — live reload needs it out of the way |
| `manifest.json` · icons/favicons | PWA install metadata |
| `modern_prototype.html` · `sidebar_prototype.html` | Design prototypes — not served, don't ship code in them |

## Data contract (page → API → serializer)

| Page script | Calls | Backend shape from `backend/app/serializers.py` |
|---|---|---|
| `taskboard.js` | `/api/tasks*` | `task_card` / `task_detail` (+ Atrium cards via `as_board_card` — string ids `atrium:<client>:<id>`) |
| `dashboard.js` | `/api/dashboard`, `/api/insights`, `/api/attendance/self-event` | `dashboard` payload (`me`, `kpis`, `late_today_list`, `handovers`) |
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
   mode holds; then bump the SW cache.

Verify: `node --check` every edited JS file (CI does the same); full check = backend pytest suite.
Deploy: `..\deploy\deploy.ps1` (Cloud Run `sentinel`, asia-southeast1).

🔴 **`node --check` does NOT catch a backtick inside a comment inside a template literal.** The
board's injected `<style>` block is one big template literal, and a markdown-style code span in its
explanatory comment (`` `.spread` ``) CLOSES the string — the rest then parses as a tagged-template
call on a string property, which is *valid syntax* and only explodes at run time
(`TypeError: "…".spread is not a function`, i.e. the board dies with a bare "Couldn't load the task
board" toast and no clue). This cost a debugging round on 2026-08-04. **Quote CSS selectors with `'`
inside any comment that lives in a template literal**, never with a backtick.

## Gotchas / DO NOT TOUCH

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
  - **`id="modal-x"` is no longer unique while a stack is open.** Scope lookups to the `root` the
    call returns; a bare `qs("#modal-x")` finds the BOTTOM one. Same for `.modal-body` — take it from
    `m.root`, not from a document-wide query (which is what `showPastWork` used to guess at).
  Rendering an editor inline instead of in a dialog (`gym.js`'s routine editor in `#tabc`) is still
  fine — it just is no longer forced.
- 🔴 **`hidden` is honoured by ONE rule, `[hidden]{display:none !important}` at the top of
  styles.css** — and it is load-bearing. `[hidden]` normally lives only in the UA stylesheet, so ANY
  author rule that sets `display` silently disarms the attribute and every `el.hidden = …` becomes a
  no-op with no error. It bit three times before the global rule went in (2026-08-06): `#tb-bulkbar`
  (`.row`) showed an empty white strip under the board filters; `#t-campaign-wrap` (`label.field`)
  put the Campaign field on **every** task, defeating the whole "only offer it for campaign-shaped
  services" change; `#tb-req-n` (`.pill`) rendered a violet **0** on an empty Requests queue. Do not
  remove it, and do not use `hidden` for something that should stay laid out — use a class.
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
  with uses `data-uid`. Check before adding an attribute selector.
- **Never build a list of task statuses from LABEL literals** — statuses are renameable in Manage,
  and a rename ships in the deploy now (`task_config.RENAMED_STATUSES`). The Monitor's workload bar
  did exactly this (`["To Do","In Progress","Revision Needed","Blocked"]`) and the 2026-08-04
  Blocked → Parked rename took it from covering **18 of 18** open cards to **8**, with no error and
  no empty state — the parked work just stopped being drawn. Any status somebody *added* had never
  been counted either. Derive from `/api/vocab` (`STATUSES`) and switch on **`STAGE_OF[status]`**,
  never the name; the same rule is why `isDone` asks the stage rather than comparing to "Completed". (AGENTS.md §5 has the full two-layer
  cache story; the server's `Cache-Control: no-cache` half is pinned by backend tests).
- No React, no bundler, no TypeScript — keep matching what's here.

## Status (volatile)

- Live: `https://sentinel-585951669065.asia-southeast1.run.app` — serving revision
  **`sentinel-00112-mpl`** (verified 2026-07-29).
- `sw.js` `CACHE` currently **`sentinel-v74`**.
- 22 JS files under `static/js/`; 19 page shells.

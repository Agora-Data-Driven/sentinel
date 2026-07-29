# frontend/ — the Sentinel UI

Vanilla JS, no framework, no bundler, no build step: 19 thin HTML shells under `pages/`, one
controller file per page under `static/js/`, one stylesheet, a PWA service worker for the offline
kiosk. Operating rules (CSP, cache bumping, `api()`-only fetches) live in
[../AGENTS.md](../AGENTS.md) — this file is the unit map + cookbook.

## File map

| Entry | What it is |
|---|---|
| `pages/*.html` | 19 shells (~0.7 kb each; JS renders everything): dashboard, attendance, approvals, gym, growth, reading, academy, philosophical, spiritual, people, leave, north-star, reports, settings, manage, payroll, login, kiosk, scanner. Routes registered in `backend/app/main.py:381` (`_PAGES`; `/login` is its own route) |
| `static/js/app.js` | The shell every page loads: `NAV` array `:78` (roles/`min`/`hideRoles` gate visibility), `api()` `:130` (CSRF echo + FastAPI error flattening), `toast`, `skeleton`, `modal`, `esc`/`qs`/`qsa`, `ICON`, `avatar`, command palette (`initCommandPalette`), Coach FAB |
| `static/js/taskboard.js` | Mountable Kanban embedded in the dashboard (no /tasks page — the URL 307s to /dashboard). Optimistic DnD (native HTML5 — deliberate, see AGENTS.md §9), SSE reload, quick-add, Atrium-card editing |
| `static/js/dashboard.js` | KPIs, self clock-in card, hosts the task board |
| `static/js/attendance.js` · `approvals.js` | Time page · combined attendance+leave approvals inbox (team_lead+) |
| `static/js/gym.js` | Calendar, no-lock day editor, history |
| `static/js/growth.js` · `reading.js` | Development hub (4 dimensions, Mentor Library import) · reading canon |
| `static/js/academy.js` | Mastery Engine iframe (Professional tab) |
| `static/js/engine-tab.js` | ONE controller for the Philosophical + Spiritual tabs — each shell pins a program via `<body data-program>` → iframe `?program=` |
| `static/js/kiosk.js` | QR scanning + **IndexedDB offline punch queue** (syncs every 30 s) |
| `static/js/login.js` | Portal bounce + "not a Sentinel user" messaging |
| `static/js/northstar.js` · `who-we-are.js` | North Star page (iframes `static/who-we-are.html`) · that page's reveal/count-up interactions (extracted from an inline script — CSP) |
| `static/js/people.js` · `leave.js` · `reports.js` · `settings.js` · `manage.js` · `payroll.js` · `charts.js` | One per page + the shared canvas charts helper |
| `static/css/styles.css` | The whole design system (token-driven, dark mode via overrides) |
| `static/vendor/html5-qrcode.min.js` | The only vendored lib — CSP blocks CDNs |
| `static/who-we-are.html` | North Star manifesto content (served statically, iframed) |
| `sw.js` | Service worker: **`CACHE` key line 6** (currently `sentinel-v48`), `CORE` precache list, network-first assets; navigations NOT intercepted except **`/kiosk`** (`:46-53`) |
| `manifest.json` · icons/favicons | PWA install metadata |
| `modern_prototype.html` · `sidebar_prototype.html` | Design prototypes — not served, don't ship code in them |

## Data contract (page → API → serializer)

| Page script | Calls | Backend shape from `backend/app/serializers.py` |
|---|---|---|
| `taskboard.js` | `/api/tasks*` | `task_card` / `task_detail` (+ Atrium cards via `as_board_card` — string ids `atrium:<client>:<id>`) |
| `attendance.js`, `approvals.js` | `/api/attendance/*` | `summary_dict`, `attendance_request_dict` |
| `gym.js` | `/api/gym/*` | `gym_log_dict`, `body_metric_dict`, `personal_record_dict` |
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
   `data-program`/`data-title`, iframe needs `allow="microphone"`, and the server must delegate
   the mic (Permissions-Policy derives from `SKILL_MASTERY_URL` — AGENTS.md §5).
7. **Change styles** — `static/css/styles.css` only; keep it token-driven (`var(--*)`) so dark
   mode holds; then bump the SW cache.

Verify: `node --check` every edited JS file (CI does the same); full check = backend pytest suite.
Deploy: `..\deploy\deploy.ps1` (Cloud Run `sentinel`, asia-southeast1).

## Gotchas / DO NOT TOUCH

- **`sw.js` must not intercept navigations** — the `/kiosk` exception (`sw.js:46-53`) is the ONLY
  one allowed (offline kiosk boot). Caching other navigations resurrects the 2 s stale-login flash.
- **No inline `<script>`** — CSP `script-src 'self'`; `who-we-are.js` exists precisely because an
  inline block was silently blocked and blanked the page.
- **`element.onclick = handler` passes the Event as arg 1** — always `() => handler()`.
- Forgetting the `CACHE` bump ships stale assets to everyone (AGENTS.md §5 has the full two-layer
  cache story; the server's `Cache-Control: no-cache` half is pinned by backend tests).
- No React, no bundler, no TypeScript — keep matching what's here.

## Status (volatile)

- Live: `https://sentinel-585951669065.asia-southeast1.run.app` — serving revision
  **`sentinel-00112-mpl`** (verified 2026-07-29).
- `sw.js` `CACHE` currently **`sentinel-v48`**.
- 21 JS files under `static/js/`; 19 page shells.

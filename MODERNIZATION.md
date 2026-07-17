# Sentinel — Modernization & Hardening Plan

> Living checklist for turning Sentinel into a more **robust** and **modern** internal ops
> platform, without throwing away the FastAPI + vanilla-JS architecture that already works.
>
> **How to use this file:** each task has a checkbox. Check it off when merged. The
> "Session" grouping is how we'll batch the work so it fits inside usage-limit windows.
> Prototype of the target UX: an interactive HTML mockup was built (task board with
> optimistic drag-drop, Ctrl+K palette, live updates, dark mode).

**Started:** 2026-07-17
**Owner:** juan@100.digital
**Stack today:** FastAPI + SQLAlchemy (SQLite dev / Postgres prod) · vanilla-JS multi-page frontend · PWA · Cloud Run

---

## Progress at a glance

- [x] **Session 1 — Security & quick wins** (urgent) — DONE 2026-07-17
- [~] **Session 2 — UX modernization** — 3 of 4 done (2.3 drawer deferred), 2026-07-17
- [ ] **Session 3 — Robustness & testing**
- [ ] **Session 4 — Real-time & build tooling** (optional / biggest)

Rough total: **~4–7 hrs active work**, **~1.0–1.8M tokens**, across **3–4 sessions**.

---

## 🔴 Session 1 — Security & quick wins
*~1–1.5 hrs · ~200–280k tokens · high value, low risk. Contains the only truly urgent item.*

- [x] **1.1 — Remove leaked session tokens** ⚠️ *URGENT* — DONE
  - Removed `live.txt` + `backend/{cg,cm,em,live,pw,sa}.txt` from git and disk; extended `.gitignore`.
  - **Still TODO by a human:** rotate `JWT_SECRET` in prod; scrub git history (`git filter-repo`)
    if the repo was ever pushed/shared — the tokens remain in past commits.
- [x] **1.2 — Replace `python-jose` with `PyJWT`** — DONE
  - `requirements.txt` → `PyJWT==2.10.1`; `security.py` catches `jwt.PyJWTError`. Round-trip verified.
- [x] **1.3 — Security headers + rate limiting** — DONE
  - New `app/middleware.py`: `SecurityHeadersMiddleware` (CSP/XFO/nosniff/Referrer/Permissions/HSTS)
    + `RateLimitMiddleware` (per-IP: login 10/min, scan 120/min → 429). No new dependency (used a
    hand-rolled limiter instead of slowapi to avoid router churn). `kiosk_guard` was already wired.
- [x] **1.4 — Toasts + skeleton loaders** — DONE
  - Toasts + dark mode already existed. Added `S.skeleton()` helper + `.skel-*` CSS, `toast()` now
    supports an Undo-style action button, applied skeletons to dashboard + people.
- [x] **1.5 — Dark mode QA pass** — DONE (audit, no code change)
  - CSS is token-driven (188 `var()` uses, 13 dark overrides); no contrast breakage. login/kiosk/
    scanner are intentionally light-only (`data-shell="off"`). *Optional polish later:* the tint
    tokens (`--green-bg`, `--push-bg`, …) aren't dark-adjusted — legible but could feel more native.
- [x] **1.6 — Lock down prod config** — DONE
  - Dev-login is now forced OFF in production (secure-by-default) unless `ALLOW_DEV_LOGIN_IN_PROD=true`;
    loud startup SECURITY warnings for default JWT_SECRET / active dev-login / insecure cookies /
    default admin password; `deploy.ps1` now ships `DEV_LOGIN_ENABLED=false`; `.env.example` documents it.
  - **Still TODO by a human:** wire Google OAuth (`deploy/GOOGLE-SIGNIN-SETUP.md`) or set passwords,
    then next deploy uses the secure posture. Change the bootstrap admin password after first sign-in.

---

## 🟢 Session 2 — UX modernization
*Partially done 2026-07-17 (branch `hardening/session-1`). 2.1/2.2/2.4 shipped; 2.3 deferred.*

- [x] **2.1 — Command palette (Ctrl+K)** — DONE
  - `initCommandPalette()` in `app.js`: searches Pages / Actions / People / Tasks; subsequence
    scorer; keyboard nav; topbar "Search" trigger. Deep-links via `/tasks?open=`, `/people?open=`
    (added), `/tasks?new=1` (added). Verified with a jsdom harness (13/13 checks).
- [x] **2.2 — Optimistic drag-and-drop** (`tasks.js`) — DONE
  - Card moves instantly, syncs in background, rolls back + error toast on failure, Undo toast on
    success, live column counts. Kept the built-in HTML5 DnD (no SortableJS needed — CSP blocks
    CDNs and it works well). Verified with jsdom (move / counts / PATCH / Undo / rollback).
- [ ] **2.3 — Task detail drawer polish** — DEFERRED
  - The detail is a functional wide modal (checklist + comments + activity + AM priority lock).
    Converting to a right-side slide-in is a layout rewrite that really wants real-browser visual
    verification (jsdom can't validate layout), so deferring to a focused session. No functionality lost.
- [x] **2.4 — Board quick-add** — DONE (filters already existed)
  - Per-column inline "Add card" (AM+): Enter creates `{title, status}`, Esc/empty cancels.
    The Client/Department/Priority/Assignee filter selects were already present and working.
    Verified with jsdom (button present, input appears, POST with title+status).
  - Note: added a defensive `scrollIntoView` guard in `app.js` + `tasks.js` (harmless in browsers,
    keeps the palette/quick-add robust and headless-testable).

---

## 🔵 Session 3 — Robustness & testing
*~1.5 hrs · ~260–390k tokens · the highest value-per-token work.*

- [ ] **3.1 — Pytest skeleton + first tests** ⭐ *biggest bang for buck*
  - `pytest` + FastAPI `TestClient`. Start with highest-risk logic:
    - **RBAC guards** — assert real 403s per role per endpoint (`app/security.py`).
    - **Attendance engine** — late/grace boundaries around midnight Asia/Manila (timezone math).
    - **Leave balance** updates on request → approval.
- [ ] **3.2 — CSRF protection**
  - Cookie-based JWT is CSRF-vulnerable by default. Add `SameSite=Strict` + custom header check
    or a double-submit token. Frontend gets a shared `fetch` wrapper.
- [ ] **3.3 — Alembic migrations for real**
  - Stop relying on `create_all`. Run `alembic upgrade head` in the Dockerfile entrypoint.
  - Baseline migration from current models.
- [ ] **3.4 — CI pipeline** (`.github/workflows/ci.yml`)
  - `ruff` lint + `pytest` + docker build on every push/PR.
- [ ] **3.5 — Error tracking + structured logging**
  - Sentry free tier (or GCP Error Reporting since we're on Cloud Run).
- [ ] **3.6 — Cloud SQL automated backups + a restore test**
  - Attendance/payroll data can't be regenerated from `seed.py`.

---

## 🟣 Session 4 — Real-time & build tooling
*Biggest items — each may want its own session. Optional / defer if tokens are tight.*

- [ ] **4.1 — Real-time board via SSE (or WebSockets)**
  - FastAPI supports both natively. Push card moves + notifications instantly.
  - Makes the notification bell live and stops two-editor clobbering.
- [ ] **4.2 — Vite + TypeScript build step** ⚠️ *most expensive — defer unless needed*
  - Keep vanilla JS, but add TS types, ES modules, and bundling across all 15 JS files.
  - Catches a class of bugs in the 16KB page scripts. Highest token cost; lowest urgency.
- [ ] **4.3 — (Stretch) Object storage for task attachments**
  - Currently metadata-only. Wire GCS/S3 for the bytes.

---

## Reference — similar systems for design inspiration

| System | Link | For |
|---|---|---|
| Linear | linear.app | Interaction patterns, Ctrl+K, optimistic UI |
| Plane (OSS) | plane.so · github.com/makeplane/plane | Board/DnD code to read |
| Huly (OSS) | huly.io | Modern dark theme + density |
| Focalboard (OSS) | github.com/mattermost-community/focalboard | Simplest kanban codebase |
| Frappe HR (OSS) | frappe.io/hr | Attendance/leave/payroll depth |
| Jibble | jibble.io | QR kiosk attendance UX |

---

## Decisions & notes
*(Append as we go — this is the running log.)*

- 2026-07-17 — Plan created. Prototype built and reviewed. Agreed to batch into sessions;
  Session 1 first because of the live session token in `live.txt`.
- 2026-07-17 — **Session 1 completed** (branch `hardening/session-1`, 6 commits). Discovered
  toasts + dark mode already existed, so 1.4/1.5 were lighter than estimated. Chose a hand-rolled
  rate limiter over slowapi (no new dep, no router churn). Made dev-login secure-by-default in prod
  rather than only editing deploy config, so the footgun is closed in code too.
  **Human follow-ups outstanding:** rotate prod `JWT_SECRET`; scrub git history; wire OAuth / set
  passwords before next deploy (dev-login dropdown will be gone in prod); change bootstrap password.
  Branch not yet merged to `main` or pushed — awaiting review.
- 2026-07-17 — **Session 2 (UX): 2.1, 2.2, 2.4 shipped** on the same branch. Built a jsdom test
  harness (installed in scratchpad, not the repo) to functionally verify the palette (13 checks)
  and board DnD + quick-add (17 checks) headlessly. Kept HTML5 DnD instead of SortableJS (CSP blocks
  CDNs; the built-in works). 2.3 (modal→drawer) deferred as a layout rewrite needing browser visual
  QA. Two jsdom-surfaced robustness fixes shipped: guarded `scrollIntoView` in the palette + quick-add.

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

- [ ] **Session 1 — Security & quick wins** (urgent)
- [ ] **Session 2 — UX modernization**
- [ ] **Session 3 — Robustness & testing**
- [ ] **Session 4 — Real-time & build tooling** (optional / biggest)

Rough total: **~4–7 hrs active work**, **~1.0–1.8M tokens**, across **3–4 sessions**.

---

## 🔴 Session 1 — Security & quick wins
*~1–1.5 hrs · ~200–280k tokens · high value, low risk. Contains the only truly urgent item.*

- [ ] **1.1 — Remove leaked session tokens** ⚠️ *URGENT*
  - `git rm --cached live.txt backend/cg.txt backend/cm.txt backend/em.txt backend/pw.txt backend/sa.txt backend/sentinel.db`
  - These are curl cookie jars holding **live session JWTs** (including one for the Cloud Run deployment).
  - Add to `.gitignore`: `*.txt` cookie jars, `*.db`, `.venv/`, `__pycache__/`, `badges/`.
  - **Rotate `JWT_SECRET`** in production → invalidates all leaked tokens at once.
  - Consider `git filter-repo` to scrub history if the repo is pushed/shared.
- [ ] **1.2 — Replace `python-jose` with `PyJWT`**
  - `python-jose` is effectively unmaintained (CVE-2024-33663 / 33664). PyJWT is a drop-in.
  - Touches: `requirements.txt`, `app/security.py`.
- [ ] **1.3 — Security headers + rate limiting**
  - `slowapi` on `/api/auth/*` and `/api/attendance/scan` (brute-force / abuse protection).
  - Middleware for `Content-Security-Policy`, `X-Frame-Options`, `X-Content-Type-Options`, `HSTS`.
  - Enforce the `KIOSK_KEY` (`X-Kiosk-Key`) the README already documents.
- [ ] **1.4 — Toasts + skeleton loaders** (shared `frontend/static/js/app.js` + `styles.css`)
  - Replace blank-then-pop rendering; add success/error/undo toasts.
  - *(Prototype already shows the target look.)*
- [ ] **1.5 — Dark mode QA pass**
  - Dark mode already exists in `styles.css` (`:root[data-theme="dark"]`). Audit every page for
    contrast + missed hardcoded colors; confirm the toggle persists (localStorage).
- [ ] **1.6 — Lock down prod config**
  - `DEV_LOGIN_ENABLED=false`, `SECURE_COOKIES=true`, strong `JWT_SECRET`, `SameSite` cookies.
  - Wire the already-scaffolded Google OAuth (`deploy/GOOGLE-SIGNIN-SETUP.md`).

---

## 🟢 Session 2 — UX modernization
*~1.5 hrs · ~300–390k tokens · the "feels modern" batch.*

- [ ] **2.1 — Command palette (Ctrl+K)**
  - Jump to any person / task / page + run actions. ~200–300 lines, self-contained.
  - Highest-impact single feature. Lives in `app.js`, works on every page.
- [ ] **2.2 — Optimistic drag-and-drop with SortableJS** (`frontend/static/js/tasks.js`)
  - Move card instantly, sync in background, roll back + toast on failure.
  - Replace hand-rolled HTML5 DnD with SortableJS for smoother feel.
- [ ] **2.3 — Task detail drawer polish**
  - Slide-in drawer with checklist + comments + activity + labels; keep AM-only priority lock.
- [ ] **2.4 — Board filters + quick-add polish**
  - Client / Department / Priority / Assignee filter chips; inline "+ new task".

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

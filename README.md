# Sentinel — Agora Internal Operations

Sentinel is the **internal operations command center** for **Agora**, a digital-marketing agency in
the Philippines. It sits behind the client-facing **Atrium** portal and handles everything the
internal team needs: **attendance tracking, gym compliance, task management, an employee directory,
leave management, notifications, and reporting.**

It's built to look like Atrium's sibling — the same clean white UI, 248px sidebar, green-gradient
active nav, and brand-gradient hairline under the topbar — distinguished by an **amber-orange
`SENTINEL` badge** (Atrium's is green→violet).

> **Hard rule:** clients never see internal fields (assignee, team, priority, internal notes,
> attendance, gym). The Account Manager bridges Sentinel ↔ Atrium via **Send to Atrium**, which
> shares only client-safe fields.

---

## Quick start (local, zero-setup)

Requires **Python 3.11+**. SQLite is used by default — no database to install.

```bash
cd backend
python -m venv .venv
# Windows PowerShell:  .\.venv\Scripts\Activate.ps1
# macOS/Linux:         source .venv/bin/activate
pip install -r requirements.txt

python seed.py                        # builds all 19 tables + realistic sample data
uvicorn app.main:app --reload         # serves API + frontend on http://localhost:8000
```

Open **http://localhost:8000** → you'll land on the login page. Pick any seeded user from the
**Dev login** dropdown (no password). Try:

| User | Login | Role | Sees |
|------|-------|------|------|
| Melo Yelo | `melo@agora.ph` | Super Admin | Everything + Scanner |
| Maria Santos | `maria@agora.ph` | Admin | Records, reports, approvals, settings |
| Leo Vasquez | `leo@agora.ph` | Account Manager | Tasks + **priority control** |
| Bong Cruz | `bong@agora.ph` | Team Lead | Team tasks, approvals |
| Ana Reyes | `ana@agora.ph` | Employee | Own data only |

### The attendance kiosk

Open **http://localhost:8000/kiosk** on a tablet. It auto-scans employee QR badges via the camera
(or type a badge code for testing). Print a badge from **People → View → Download badge**.

The **Super Admin phone scanner** is at **/scanner** (same flow, behind auth, records
`device: admin-phone`).

---

## Docker (with Postgres)

```bash
docker compose up --build
docker compose exec app python seed.py     # first-run seed
# → http://localhost:8000
```

## Deploy to the web (Google Cloud Run)

Sentinel deploys the same way as Atrium — a container on Cloud Run built by Cloud Build. See
**[deploy/DEPLOY.md](deploy/DEPLOY.md)** for the full guide. Short version (from `sentinel/`):

```powershell
# One-time: enable APIs, create the Artifact Registry repo, JWT secret, and Cloud SQL (see DEPLOY.md)
.\deploy\deploy.ps1 -CloudSqlInstance "agora-data-driven:asia-southeast1:sentinel-db"
.\deploy\seed-job.ps1 -CloudSqlInstance "agora-data-driven:asia-southeast1:sentinel-db"   # optional demo data
```

> Cloud Run is stateless, so **production uses Cloud SQL (Postgres)** — SQLite data would reset on
> every restart. A single-instance `-DemoSqlite` mode exists for a quick look.

---

## What's inside

### Modules
- **Attendance** — QR kiosk (idle / after-scan / offline states), late detection with reason chips,
  handover notes on clock-out, break tracking, regularization & overtime approval workflows, daily
  summaries, and an **offline IndexedDB punch queue** that syncs every 30s.
- **Gym Tracker** — Hevy-style logging (per-set KG × REPS × type, a grayed-out **PREVIOUS** column,
  rest/notes), a 50+ exercise library filtered by Push/Pull/Legs/Custom, session summaries
  (duration, sets, volume, PRs, muscle activation), and team compliance.
- **Task Board** — Trello-style Kanban with drag-and-drop across 7 columns, filters (Client /
  Department / Priority / Assignee), colored label pills, a detail panel with checklist + comments +
  activity log, and **Send to Atrium**. Priority is **AM-only** (server returns 403 otherwise).
  Lives **embedded in the Dashboard** (no tab of its own; `/tasks` redirects to `/dashboard`).
- **People** — searchable directory with filters, rich profile cards (attendance, gym, tasks, leave),
  and downloadable QR badges.
- **Leave** — 5 leave types with balances, request → approval → balance-update flow.
- **Notifications** — in-app bell with unread count, deep links, mark-read / mark-all-read.
- **Reports** — 6 reports (attendance, gym, tasks, team, leave, overdue) with date/team filters and
  **CSV export**.
- **Settings** — editable system rules (shift, grace, break, gym hours, overtime), announcement
  broadcast, and the **audit log** viewer.

### Roles & access (enforced on every endpoint, not just the UI)
`super_admin` › `admin` › `account_manager` › `team_lead` › `employee` / `intern`.
RBAC lives in dependency guards (`app/security.py`); unauthorized calls get a real **403**.

### Timezone
All instants are stored **UTC**; display and business rules (late/grace, "today") apply in
**Asia/Manila (UTC+8)**.

---

## Project structure

```
sentinel/
├── backend/
│   ├── app/
│   │   ├── main.py            # FastAPI app: routers + serves the frontend
│   │   ├── config.py          # env-driven settings
│   │   ├── database.py        # SQLAlchemy engine/session/Base
│   │   ├── constants.py       # roles, statuses, enums
│   │   ├── security.py        # JWT cookie auth + RBAC guards
│   │   ├── serializers.py     # model → dict (controls field exposure)
│   │   ├── models/            # 19 tables, grouped by domain
│   │   ├── schemas/           # Pydantic request models
│   │   ├── routers/           # auth, attendance, gym, tasks, people, leave, notifications, reports, admin, meta
│   │   ├── services/          # attendance engine, leave, gym, notifications, settings, audit
│   │   └── utils/             # timezone, qr, csv
│   ├── alembic/               # migrations (optional; app auto-creates tables for MVP)
│   ├── seed.py                # populates all 19 tables
│   ├── make_badges.py         # writes printable QR badges to ../badges/
│   └── requirements.txt
├── deploy/                    # Cloud Run deploy.ps1 + seed-job.ps1 + DEPLOY.md
├── Dockerfile                 # production image (build context = sentinel/)
├── frontend/
│   ├── static/css/styles.css  # Atrium-matched design system
│   ├── static/js/             # app.js (shell) + one file per page + kiosk.js
│   ├── pages/                 # dashboard, attendance, gym, tasks, people, leave, reports, settings, login, kiosk, scanner
│   ├── manifest.json          # PWA
│   └── sw.js                  # service worker (offline kiosk)
├── .env.example
├── docker-compose.yml
└── README.md
```

The interactive **API docs** are at **http://localhost:8000/docs** (FastAPI / OpenAPI).

---

## Key API endpoints (all enforce RBAC)

```
POST /api/auth/dev-login            pick a seeded user (dev)
GET  /api/auth/me                   current user + role + team
POST /api/attendance/scan|event     kiosk QR → employee + punch
POST /api/attendance/offline-sync   bulk IndexedDB upload
GET  /api/tasks                     role-filtered board
PATCH /api/tasks/{id}/priority      Account Manager ONLY (403 otherwise)
POST /api/tasks/{id}/send-to-atrium client-safe fields → Atrium bridge
GET  /api/gym/library               exercises + PREVIOUS lookups
GET  /api/people/{id}/qr            QR badge PNG
GET  /api/reports/{type}?export=csv 6 reports + CSV
GET/PATCH /api/admin/settings       system config (audit-logged)
```

---

## Notes & production hardening
- Set a strong `JWT_SECRET`, `SECURE_COOKIES=true` (behind HTTPS), and `DEV_LOGIN_ENABLED=false`.
- Wire real **Google OAuth** (`GOOGLE_CLIENT_ID/SECRET`) — the DEV_LOGIN fallback covers local dev.
- Lock the kiosk endpoints with `KIOSK_KEY` (sent via `X-Kiosk-Key`) or a LAN allow-list.
- Point `DATABASE_URL` at Postgres and run `alembic upgrade head` instead of relying on
  `create_all`.
- Task attachments record metadata only in this MVP — wire an object store (GCS/S3) for the bytes.

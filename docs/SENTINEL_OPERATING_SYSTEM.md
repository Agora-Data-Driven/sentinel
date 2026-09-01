# Sentinel as Agora's operating system — assessment, gap analysis, adapted architecture

> Written 2026-09-01 against the code as it stands (Sentinel `main` ≈ dc191d1, Atrium, Mastery
> Engine). Steps 1–5 of the brief: **inspect → gap analysis → adapted architecture → mockup →
> role instructions.** Step 6 (implementation plan) is deliberately NOT here — it follows review.
> Mockup: `docs/sentinel_ops_mockup.html` (also published as an Artifact). Companion docs:
> [TASKBOARD_REBUILD.md](TASKBOARD_REBUILD.md) (D1–D16, all built), [ARCHITECTURE.md](ARCHITECTURE.md).

The one-sentence finding: **Sentinel is not a greenfield and the brief under-estimates it.** Roughly
60% of the proposed P0 already exists, is tested, and is live. What is genuinely missing is small
and specific: **a role-shaped landing page ("Today"), per-task work time, an account-level view for
the AM, an exceptions view for the COO, a calendar projection, and a worker-stage/certification
record.** None of those need a rewrite. The task entity IS already the central operating object.

---

## A. What exists today

### A.1 Screens (vanilla JS, one file per page — `frontend/static/js/`)

| Screen | URL | What it does today |
|---|---|---|
| **Overview** | `/dashboard` | Landing page for everyone. Order: greeting + **Clock in/out** + gym strip → **Your Growth** (4 rings into the Mastery Engine) → **Time on growth** (engine minutes per dimension, Today/Week/30d, manual "Log time") → **My work** (open / overdue / waiting-on-me tiles + "Up next" five cards) → Pace → Mentor library → (admins) **Across Agora**: team progress table, team time, "Run daily processing". |
| **Task Board** | `/tasks` | Kanban (To Do · In Progress · Revision Needed · Completed · Parked), **By Employee** swimlanes, **Monitor** (per-person workload rollup, relative load band, overdue, untouched, cycle days, on-time, finished 7d, throughput chart). Role-shaped filter bar; attention pills (overdue / client asked / to approve / urgent / on you); bulk bar; New Task property-row form with service templates; wide task modal (record left, breakdown + comments + activity right; Move / Edit / Submit for review / Approve / Request changes / Park / Resume / File / Send to Atrium). |
| Growth group | `/academy` `/philosophical` `/spiritual` `/gym` | Mastery Engine iframes (one per program) + gym tracker. Coach FAB = the engine's assistant fed by `/internal/work-digest`, `holistic-profile`, `mentor-search`. |
| Time & Leave | `/attendance` `/leave` `/approvals` `/scanner` | Attendance records, leave, one approvals inbox (attendance + leave), kiosk. |
| People | `/people` | Directory + profile (attendance, gym, tasks, leave), badges. |
| Admin | `/reports` `/payroll` `/manage` `/permissions` `/settings` | 6 CSV reports; payroll; Manage console (clients mirror, teams, shift templates, leave types, **service templates**, **task vocabulary**); role × capability console; settings + audit log. |

### A.2 Models that matter here (`backend/app/models/`)

- **`tasks`** — already carries: `client_id`, `campaign` (grouping key), `content_type`, `account_manager_id`, `assigned_team_id` (department), `assigned_to_id` (ONE lead) + `task_supporters` (many), `created_by_id`, `origin` (planned/added), `priority`, `status` (label; identity = `task_vocab.key` + `stage`), `due_date`, `start_date`, `completed_at`, `archived`, **`on_hold` + `hold_reason` + `resume_to`**, **`review_state` + `reviewer_id`**, `client_changes_open`, `service_charge`, two-level `maintasks_json` breakdown with per-step owners, `atrium_visible` / `atrium_task_id` / `atrium_sync_error`, `deliverable_url`, `internal_notes`, `client_facing_notes`. `task_history` = per-field audit. `task_comments`.
- **`service_templates`** (12 seeded recipes, per department) · **`recurring_services`** (monthly/weekly, idempotent period keys) · **`task_requests`** (client intake queue from Atrium) · **`task_vocab`** (statuses with stage, priorities).
- **`users`** — role (7 incl. read-only `viewer`), primary `team_id` + `user_teams` (multi-department), shift template, hired date. **No stage/level column.** `skills` has `source=certification` as an enum value — that is the entire certification footprint.
- **`clients`** — a **mirror of Atrium's registry** (`atrium_client_id` is the bridge key; Manage → Clients is read-only). **No account manager on the client.**
- **`time_entries`** — hand-logged *growth* minutes by dimension. **Not task time; has no `task_id`.**
- Attendance (`attendance_events`, `daily_attendance_summary`, requests), leave, gym, development (goals per 4 dimensions, growth journal, reading, mentor transcripts), `notifications`, `audit_logs`, `role_capabilities` / `user_capabilities`.

### A.3 Services / rules already enforced (`backend/app/services/`)

- `task_workflow.py` — the lifecycle: `completed_at` stamped by the transition; park/resume with reason + remembered column (`_sync_hold` fires from every door incl. drag); **review gate: entry into a done column requires `review_state = approved` (409 otherwise)**; approval is spent by completion; submit → notifies team leads; request changes → moves to Revision Needed + notifies owner.
- `task_perms.py` — the ONE permission model: `is_assigned` (lead ∪ supporters ∪ step owners) = `mine`; employees see their work + team queue + whole department (read-only); leads act on what they can see; capability-gated `can_review` / `can_reassign` / `can_prioritize`; `viewer` writes nothing.
- `task_analytics.py` — Monitor: median cycle days, on-time rate (None never 0), aging (two clocks), approved-leave capacity, **relative** load bands. Explicit design note: *no estimate field, deliberately — a half-populated one is worse than none.*
- `task_recurring.py`, `task_templates.py` (create + apply-to-existing), `task_adoption.py`, `task_bridge.py` (client-safe projection: 6 fields), `board_mirror.py` (staff mirror Atrium pulls), `client_sync.py`, `work_digest.py` (the board, role-scoped, for the Coach), `time_spent.py` + `engine_bridge.py` (engine minutes + manual, merged at read), `daily.py` (attendance summaries, overdue/approval reminders, client mirror, recurring tick — **built, never scheduled in prod**), `notifications.py`, `audit.py`, `teams.py`, `team_growth.py`.

### A.4 APIs — see [ARCHITECTURE.md](ARCHITECTURE.md) and `routers/tasks.py` (≈40 routes). Notable for this brief: `GET /api/tasks/summary` (Monitor), `/throughput`, `/filed-by-me`, `/requests/*`, `/{id}/park|resume|archive|send-back|apply-template|review/*|bulk`, `GET /api/stream` (SSE), `/api/internal/*` (HMAC: `work-digest`, `board`, `task-request`, `task-feedback`, `holistic-profile`…), `/api/development/time*`.

### A.5 Integrations
- **Atrium** (Flask, no DB — one JSON per client in GCS). Owns clients, comms, reports, intel, Watcher. Two-way task bridge (Sentinel edits Atrium cards in place; Sentinel rows project a 6-field client-safe copy; Atrium pulls the full staff mirror). Atrium files client asks into Sentinel's intake queue and sends client comments/change requests back. Atrium has the AI layer (Vertex Gemini via runtime SA, DeepSeek, Kimi) and **`assistant_actions.py` — propose → validate → human approves → execute**, exactly the shape §12/§28 of the brief describe.
- **Mastery Engine** (Node). Owns curriculum, per-topic mastery, enrollments, roadmaps (`assignedRoadmaps` = admin-assigned learning), and **minute-bucket time-in-engine** (3-min grace, frame-visible, minute = key). Sentinel reads `time-spent`/`time-detail`/`team-progress`/`learner-detail` and may only *remove* minutes. **Sentinel itself calls no LLM anywhere.**

### A.6 What I checked and did NOT find
No task timer / work sessions · no estimate or effort · no `due_time` (dates only) · no dependencies · no task calendar (only the gym calendar) · no client health · no client-level AM · no worker stage · no certifications table · no morning brief · no AI in Sentinel · SSE broker is per-instance · attachments are a stub · daily cron dormant.

---

## B. Retain as-is (already satisfies the vision)

| Brief item | Where it already lives | Verdict |
|---|---|---|
| Auth / roles / permissions | 7 roles, capability registry + object-scoped `task_perms`, `/permissions` console | **Keep. Don't add a parallel ACL.** |
| Clock in / out | Kiosk + self clock-in on the Overview | Keep |
| Task board + task as central object | `/tasks`, `tasks` table | Keep — it is already the operating object |
| Task fields: client, workstream, priority, due, status, assignee, reviewer, department, AM | `client_id`, `campaign`+`content_type`, `priority`, `due_date`, `status/stage`, `assigned_to_id`+supporters, `reviewer_id`, `assigned_team_id`, `account_manager_id` | Keep. "Workstream" = `campaign` — do not add a new field |
| Submit for Review → Approved / Changes Requested; review gates done | `task_workflow`, review routes, 409 gate | Keep |
| Blocked + reason | Park (`on_hold`, `hold_reason`, `resume_to`) | Keep; extend (see C) |
| Task templates + checklists | `service_templates`, `maintasks` breakdown, apply-template | Keep |
| Recurring tasks | `recurring_services` (API only) | Keep; needs a Manage UI + the cron switched on |
| Mastery Engine learning time | `time_spent.py` (engine minutes, 3-min idle rule lives in the engine) | Keep; **never re-derive in Sentinel** |
| Workload visibility | Monitor + throughput | Keep as the capacity core; extend with hours once real time exists |
| Audit trail | `task_history` + `audit_logs` + notifications | Keep |
| AM → structured work | New Task form (D10/D12 routing), intake queue (client ask → accept/decline) | Keep |
| Client-safe vs internal split | `task_bridge.SAFE`, serializers boundary, Atrium mirror | Keep — this IS the Sentinel/Atrium distinction |
| Notifications (assigned / review / overdue / approval) | `notifications.py`, bell, SSE | Keep; add a digest, not more alerts |

## C. Modify / extend (existing concepts that stretch to the vision)

| Brief item | Existing concept | Extension |
|---|---|---|
| **Today page** | The Overview's "My work" strip + attendance strip + time-on-growth | **Re-cut the Overview by role.** Same URL, same components, different order and a few new blocks (see E.1). Growth rings stay, but below the work for staff. |
| **Waiting / Blocked** | Parked cards with `hold_reason` (free text) | Add a **structured `hold_kind`** (`client`, `access`, `asset`, `am_decision`, `reviewer`, `task`, `other`) + optional `blocked_by_task_id`. "Blocked since" = existing history row. Renders as the Today "Waiting" list and as the AM/COO "blocked by client vs blocked by us" split. |
| **Task time / Start Work** | Nothing on tasks; `time_entries` exists for growth | **New table `task_sessions`** (the one genuinely new primitive). Start Work moves the card to In Progress through `task_workflow`, opens a session; Pause/Submit/Complete/clock-out closes it. Read-merged into the existing time views next to engine minutes (same `source` pattern). |
| **Time Today (attendance / task / learning)** | Attendance summary; engine minutes; manual entries | One "Time today" block that stacks the three sources — `attendance.recompute_summary`, `task_sessions`, `time_spent` — with *Unallocated = attendance − (task + learning)*. No new storage beyond sessions. |
| **Capacity (hours)** | Monitor's relative band | Keep the relative band as the truthful default. Add an **optional `estimate_minutes`** whose *default comes from the service template* (so coverage is high where it matters) and only show hours when coverage on screen ≥ 70%; otherwise the band. Actual session time then gives estimate accuracy per person — the QA/capability evidence the brief wants. |
| **Calendar** | `due_date`, `start_date`, `recurring_services`, approved leave, shift templates; Atrium `calendar[]` (meetings) | A **read-only projection endpoint** `GET /api/calendar?from&to` — no calendar table. Week default. Sources: task due/start, recurring next periods, leave, (later) Atrium meetings/report dates via the bridge. Changing a due date changes the calendar for free. |
| **Client health / My accounts** | `clients` (mirror), per-task `account_manager_id`, Monitor's `by_client` throughput | Add **`clients.account_manager_id`** (a staffing fact → belongs in Sentinel, not Atrium) and a **Clients page** whose health is *derived*: overdue, blocked-by-us vs by-client, reviews waiting >24h, `client_changes_open`, stale cards, next commitment. Green/Amber/Red by rule, rule printed on screen. |
| **COO exceptions view** | Monitor, throughput, overdue pills, team growth, "Run daily processing" | An **Operations block** (admin+) that lists only exceptions: red/amber clients, overdue, blocked >2d by client, reviews >24h, heavy people, absences without cover, stalled learners. Built from `task_analytics` + `work_digest` + `team_growth` — all existing rollups. |
| **Morning brief** | `daily.py` reminders; `work_digest` | The same Operations payload rendered as one notification per manager per morning **once the daily pass is scheduled**. Not a new notification type per event. |
| **Worker stage** | `users.role` only | Add **`users.stage`** (`shadow` / `contributor` / `workstream_owner` / `client_owner`). Orthogonal to role (role = authority; stage = readiness). Surfaced, not enforced, in v1: a Shadow assigned as lead gets "reviewer required" set automatically. |
| **Certification-aware tasks** | `skills.source=certification` | A small **`certifications`** table (user, name/key, granted_by, granted_at, expires_at, evidence_url) + `service_templates.required_certification`. v1 = **warn at assignment**, never block; enforce later once the data is populated. |
| **AI task drafting** | Atrium has the provider layer + `assistant_actions` approval pattern; Sentinel has none | Add one Sentinel service (`services/ai_draft.py`, Vertex Gemini via runtime SA — same as Atrium, no key) that returns **proposed tasks** in `TaskCreateIn` shape; the UI previews and the human clicks Create. Reuses `create_task` verbatim so every permission/label/origin rule applies. |
| **Notifications: summary not spam** | 6 types, bell | Keep types; add the morning digest; deadline-approaching folds into the digest. |
| **Atrium → Sentinel loop** | `task_requests` (client ask), `task-feedback`, `assistant_actions.add_task` | Already the right shape. Later: Atrium intel/report `next_steps` file a `task_request` with `source_ref` — it lands in the intake queue the AM already triages. No new mechanism. |

## D. Do NOT build (duplicates or complicates)

| Proposed | Why not |
|---|---|
| A new "Today" page/URL | The Overview IS the landing page; notifications, palette and bookmarks point at `/dashboard`. Re-cut it, don't fork it. |
| A "Pod" entity | Pod = *client → its AM → the people holding its open cards*. `clients.account_manager_id` + the board already express it. An explicit pod table would be a second source of truth that drifts. Departments = existing Teams (already multi-membership). |
| A "workstream" / "project" field | `campaign` + `content_type` + department label already partition work three ways. |
| New statuses (Backlog, Ready, Submitted, Waiting) | Statuses are DB vocabulary with Atrium stage mapping; `review_state` and `on_hold` are **orthogonal flags** precisely so the column count stays at five. "Submitted" = `review_state=pending`; "Waiting" = Parked + `hold_kind`. Adding columns re-opens the D13 drift. |
| `due_time` on every task | Dates suffice for 95% of agency work; a "due 2 PM" is a `campaign`/meeting fact. Add `due_time` nullable only if the calendar proves it necessary. |
| A `Team.lead_id` | Rejected already (D9): leads are a query, `notify_managers(team_id=)` fans out. |
| A separate "Reviews" nav | The attention pills ("to approve") and the Approvals inbox exist; add review counts to the Operations block instead. |
| A separate "Insights" page | Monitor + throughput are the insights; extend them. |
| A separate learning-assignment system in Sentinel | The engine owns enrollments/`assignedRoadmaps`. Sentinel reads and links; a "recommend training" action posts to the engine, it does not store curricula. |
| Autonomous AI assignment / writes | Human-approved proposals only (matches Atrium's pattern). |
| Gantt, portfolios, workflow builder, billing, forecasting, HRIS | Out of scope; payroll/leave already exist and are enough. |
| Full task-dependency graph in v1 | `blocked_by_task_id` on the hold record gives 90% of the value (why is this waiting, and on whom). Multi-parent DAGs later, if ever. |
| Re-implementing idle detection for learning time | Lives in the engine's `activityTracker`; Sentinel must never re-derive it. |

---

## E. Recommended Sentinel architecture (adapted)

### E.1 One landing page, three shapes
`/dashboard` stays the landing page, assembled from components as today (`dashboard.js` hosts `GrowthPanel`, the my-work strip, the admin block). Add a **role shape**:

```
employee / intern / team_lead ─► TODAY      : attendance · Work today · Training today · Waiting · Time today · growth compass (below)
account_manager              ─► MY ACCOUNTS : attendance · account health table · today's commitments · reviews waiting · own work · growth compass
admin / super_admin (COO)    ─► OPERATIONS  : exceptions first · client health · people at risk · review backlog · learning flags · AM books · (own strip)
viewer                       ─► OPERATIONS, read-only
```
Nothing forks: the Today blocks are new *components* mounted by the same page, and the AM/COO pages are the same components with the manager block on top. Growth stays on the page for everyone (owner decision 2026-08-03) — it moves below the work for staff.

### E.2 The task stays the operating object — with three additions
```
tasks                      (unchanged)  + estimate_minutes (nullable, template default) + hold_kind + blocked_by_task_id
task_sessions   (NEW)      id · task_id · user_id · started_at · ended_at · source(start_work|auto_clockout|manual) · note
certifications  (NEW)      id · user_id · key · label · granted_by_id · granted_at · expires_at · evidence_url
users                      + stage (shadow|contributor|workstream_owner|client_owner)
clients                    + account_manager_id
service_templates          + estimate_minutes · required_certification · review_required
```
Everything else the brief lists (task ID, status history, reassignment history, activity log, created by/at, review record, revision count, acceptance criteria, instructions, deliverable) **already exists** — acceptance criteria = the breakdown steps + `description`; revision count = `task_history` rows where `review_state → changes_requested`.

### E.3 Time: three sources, one read
```
attendance   daily_attendance_summary          (exists)      clock-in → clock-out
task time    task_sessions                     (new)         Start Work → Pause/Submit/Complete/clock-out
learning     engine minutes + time_entries     (exists)      engine beat (3-min grace) + manual
```
Merged at read time in `time_spent`-style payloads with `source` on every row. Rules: one open session per person; clock-out closes it (`source=auto_clockout`, flagged); sessions > 4h are flagged for correction; corrections are new rows with a reason (audit), never edits of the original. **No surveillance heartbeat for task time in v1** — attendance already bounds the day and the engine already covers learning.

### E.4 Routing stays as built; exceptions surface, they don't route
Client → AM files the card (or accepts the client's ask) → department queue or named lead → specialist executes → reviewer approves → done → projection to Atrium. Department heads (team leads) enter only through the existing doors: team queue triage, review, send-back, and the new exception list (absent lead, overload, stage/certification warning, repeated changes-requested). No AM → Dept Head → Specialist hop is introduced.

### E.5 AI: propose → preview → confirm → the same write path
One Sentinel service turns natural language into `TaskCreateIn[]` (+ suggested assignee from: client's AM, the people currently holding that client's cards in that department, stage/cert, leave, load band). The UI shows the cards; **Create** calls `POST /api/tasks` per card. Same for the command bar ("who can cover X tomorrow?" → reads Monitor + leave; "assign Y to best person" → a proposal card). Model: Vertex Gemini through the Cloud Run runtime SA (Atrium's `intel_ai.py` pattern), degrade to "AI unavailable — file it by hand".

### E.6 Sentinel ↔ Atrium ↔ Engine boundaries (unchanged)
- Sentinel owns people, work, time, review, stage, certifications, sessions.
- Atrium owns clients, KPIs, comms, reports, intel; receives the 6 client-safe fields; sends asks and feedback.
- Engine owns curriculum, mastery, learning time; Sentinel links to assigned roadmaps and reads progress.
- The client-health colour uses Sentinel's delivery signals in v1; Atrium's KPI/goal (`ws["goal"]`) can join later through one more internal read.

### E.7 Where I disagree with the brief
1. **Don't start with estimates as the capacity unit.** The codebase already tried and rejected it for a stated reason; template-defaulted estimates + real sessions is the honest path to hours.
2. **Don't add statuses.** Review and hold are flags on purpose (five columns map 1:1 to Atrium's stages).
3. **Don't model pods.** Derive them.
4. **Calendar as projection** — agreed with the brief, and it should have no table at all.
5. **Notifications: one morning digest per manager**, not per-event alerts — and the prerequisite is operational, not code: schedule `POST /api/cron/daily` (deliberately, in daylight; see AGENTS.md §2).
6. **AI in Sentinel is a small new dependency**, not a copy of Atrium's assistant. One service, one purpose (draft tasks / answer capacity questions), human confirmation always.

### E.8 Proposed first vertical slice (revised P0)
| # | Slice | Size | New primitives |
|---|---|---|---|
| 1 | **Specialist Today** — re-cut Overview for staff: Work today (priority/due order), Training today (engine `assignedRoadmaps` link), Waiting (parked on me, with `hold_kind`), Time today (3 sources). **Start Work / Pause / Submit** on the task modal. | M–L | `task_sessions`, `hold_kind` |
| 2 | **AM My Accounts** — `clients.account_manager_id`, Clients page (health table → client drill: priorities, work by specialist, blockers, reviews, commitments, capacity, recent completions). | M | one column, one page |
| 3 | **COO Operations** — exceptions block on the admin Overview; morning digest notification (needs the daily cron scheduled). | M | none |
| 4 | **Calendar projection** — `GET /api/calendar`, Week/Month/Today views; task due-date edits inline. | S–M | none |
| 5 | **AI draft** — text → proposed tasks → confirm. | M | Vertex call |
| 6 | **Stage + certifications (surfaced)** — `users.stage`, `certifications`, template `required_certification`; warnings at assignment. | S–M | two tables |

Strongly-desirable-after (agree with brief): `blocked_by_task_id` dependencies, recurring Manage UI, estimate coverage → hours, client health + Atrium KPI join, command bar.

---

## F. Gap analysis — every proposed feature classified

| Feature (brief §) | Classification | Note |
|---|---|---|
| Auth/roles (§31) | **Already Exists** | + capability console |
| Clock in/out (§9, §31) | **Already Exists** | kiosk + Overview |
| Today page (§6) | **Moderate Build** | new components on the existing Overview |
| Work today ordered by priority/deadline | **Minor Extension** | `Up next` already lists five; widen + sort |
| Training today (§6, §16) | **Minor Extension** | read engine `assignedRoadmaps`/enrollment; link into `/academy` |
| Waiting / Blocked list (§6, §20) | **Minor Extension** | parked cards + `hold_kind` |
| Time today: attendance/task/learning (§6, §9) | **Moderate Build** | needs `task_sessions`; the other two exist |
| Task board retained (§7) | **Already Exists** | |
| Lifecycle Backlog→Ready→…→Done (§7) | **Do Not Recommend** | flags on five stages already express it |
| Task identity/responsibility/planning fields (§7) | **Already Exists** | except `estimate` (Minor, optional) and `due_time` (Do Not Recommend now) |
| Dependencies (§7, §20) | **Moderate Build** | `blocked_by_task_id` first |
| Acceptance criteria / instructions / deliverable (§7) | **Already Exists** | description + breakdown + `deliverable_url` |
| Review record, feedback, revision count (§7, §15) | **Already Exists** | `review_state`, `reviewer_id`, `task_history`, comments |
| QA score (§15) | **Minor Extension** | optional `review_score` 1–5 on approve; report later |
| Required certification / allowed stage / eligibility (§7, §17) | **Moderate Build** | tables + warnings; enforcement later |
| Internal-only vs Atrium-safe (§7) | **Already Exists** | `task_bridge.SAFE` |
| System history (§7) | **Already Exists** | |
| Start Work / Pause / Resume / Submit / Complete (§8) | **Major Build** (the one new primitive) | `task_sessions` + modal buttons + active-task indicator |
| Attendance / task / learning time split (§9) | **Moderate Build** | task half new; merge read |
| Idle detection (§9) | **Already Exists** (learning) / **Do Not Recommend** (task, v1) | clock-out + 4h cap instead |
| Manual correction with audit (§9) | **Already Exists** (learning) / **Minor** (sessions) | |
| Calendar Today/Week/Month (§10) | **Moderate Build** | projection endpoint + view; no table |
| AM My Accounts + health (§11) | **Moderate Build** | one column + one page; derived health |
| Client drill-down (§11) | **Moderate Build** | reuses board filters + Monitor rollups |
| AI task creation (§12) | **Moderate Build** | first LLM call in Sentinel; reuses `create_task` |
| AI assignment logic (§13) | **Moderate Build** | ranker over existing signals; propose only |
| Normal routing vs exceptions (§14) | **Already Exists** (routing) / **Minor** (exception list) | |
| Review/QA workflow (§15) | **Already Exists** | |
| Capability evidence per person (§15) | **Minor Extension** | query over history + sessions |
| Mastery Engine integration (§16) | **Already Exists** (time, progress, coach) / **Minor** (skill-gap tag → recommend roadmap) | |
| Certification-aware assignment (§17) | **Moderate Build**, surfaced-not-enforced | |
| Capacity dashboard (§18) | **Already Exists** (relative) / **Minor** (hours once sessions + estimates exist) | |
| Recurring templates (§19) | **Already Exists** (API) / **Minor** (Manage UI) + **operational**: schedule the cron | |
| Structured blockers (§20) | **Minor Extension** | `hold_kind`, `blocked_by_task_id` |
| Notifications (§21) | **Already Exists** / **Minor** (digest) | |
| COO dashboard (§22) | **Moderate Build** | Operations block from existing rollups |
| Navigation (§26) | **Minor Extension** | + Calendar, + Clients (AM/COO); rest exists |
| AI command bar (§28) | **Moderate Build**, after §12 | same service, read-mostly |
| Atrium → Sentinel loop (§29) | **Already Exists** (shape) / later: intel/report → `task_request` | |

---

## G. Role instructions (based on the mockup)

### G.1 Specialist — daily workflow
**Start of day (≤ 30 s to "what first?")**
1. Clock in (Overview strip or kiosk).
2. Read **Work today** — it is already ordered: Urgent first, then by due date; overdue is red.
3. Check **Training today**. If something is assigned, it shows minutes and a link straight into the engine.
4. Check **Waiting** — anything you parked yesterday that has since been unblocked shows a green "resolved" pill: resume it.
5. Open the top card → read description + breakdown (that is the acceptance criteria) → **Start Work**.

**During work**
- One active task at a time. The green "Working on …" strip stays on every page; Pause when you switch.
- Log unplanned work the moment it appears: **+ Add card** with a one-line name (Campaign | Action | Detail). Don't hide it in an existing card.
- Tick breakdown steps as you go; paste the deliverable link.
- Done → **Submit for review** (a reviewer is required for Contributors; the card says who).
- Blocked → **Park**, choose *why* (client / access / asset / AM decision / reviewer / another task), one line of detail. Never leave a card silently idle — a parked card is not a failure, an idle one is.
- Changes requested → the card moves to Revision Needed on your board with the reviewer's note; fix, resubmit.

**Learning**
- Training assigned in Sentinel opens in the engine; minutes flow back automatically (tab visible + something happening in the last 3 minutes). Nothing to log.
- "I was only moving the mouse" → trim the session from Time today → Details.

**End of day**
- Pause/stop the active task (clock-out stops it anyway and flags it).
- Every open card of yours is in an honest state: In Progress with a session, Parked with a reason, or submitted.
- Glance at **Tomorrow** at the foot of Today — if it's empty, tell your lead now, not tomorrow morning.
- Clock out.

### G.2 Account Manager — daily workflow
**After any client meeting / message (target ≈ 1 minute per commitment)**
1. Open the client (My accounts → row). Type or paste what was agreed into **Draft with AI** — or click **New task**.
2. Each proposed card shows: department, suggested assignee (the person already holding this client's work in that department), due, estimate, reviewer, and any warning (stage/certification, on leave, heavy load). Adjust, then **Create N tasks**. Nothing is created until you click.
3. Client asks that arrive from Atrium land in **Client asks** — accept (becomes a task) or decline with a reason.
4. Share-on-create is on for client-facing services; the client sees only the six safe fields.

**Each morning (My accounts)**
- Scan the health column. Red = overdue or blocked-by-us > 2 days or a review waiting > 24 h. Amber = at-risk due today / client hasn't answered.
- Clear **Reviews waiting on you** first — a waiting review is a specialist who can't finish.
- Check **Commitments today/tomorrow** (meetings, report dates, launches).
- Check the **Capacity** column — a "heavy" specialist on your account is a conversation with their team lead, today.

**Through the day** — coordinate directly with the assigned specialist (comments on the card, not DMs). Escalate to the team lead only when: the lead is absent, the person is heavy, the task needs a certification nobody on the pod holds, changes were requested twice, the deadline is impossible.

**Before a client meeting** — open the client drill: completed this week, open by specialist, blocked (and on whom), next commitments. That list is the agenda.

### G.3 COO — daily & weekly
**Morning (≈ 5 minutes, Operations block)**
Read top to bottom; each line is an exception with an owner and a button:
1. Red/Amber clients — and *why* (the rule is printed).
2. Overdue commitments, split blocked-by-client vs blocked-by-us.
3. Reviews waiting > 24 h (by reviewer).
4. People: heavy / absent without cover / no active work.
5. Learning: stalled learners, assigned training not started, certifications expiring.
6. AM book — per AM: clients, red count, overdue, unresolved asks.

**Intervention rule** — if a line is not on the list, don't touch it. Intervene on: an AM whose book has stale cards; a specialist heavy two days running; a client red two days; repeated changes-requested on one person/task type; a coverage gap; a certification gap blocking assignment; chronic review delay.

**Weekly (Monitor + Throughput + Team growth)**
- Delivery: on-time rate, median cycle days, finished/week trend — by person and by client.
- Time mix: client / training / internal / unallocated per person (this is what capacity really looks like).
- Quality: changes-requested rate per person, first-pass approval rate.
- Learning: velocity per dimension, stalled > 14 days.
- Fix the system, not the incident: a recurring exception becomes a template, a recurrence, a certification requirement, or a stage change.

---

## H. Open decisions for the owner (before Step 6)
1. Landing page order for staff: **work first, growth below** (proposed) vs growth first (today).
2. Estimates: template-defaulted optional field (proposed) vs none.
3. Task time: explicit Start/Pause only (proposed) vs an activity heartbeat like the engine's.
4. `users.stage` names: Shadow / Contributor / Workstream Owner / Client Owner as in the brief?
5. AI provider for Sentinel: Vertex Gemini via runtime SA (proposed, no secret) vs Kimi/DeepSeek key.
6. Scheduling `POST /api/cron/daily` in production (operational prerequisite for digests + recurring).
7. Client health rule thresholds (proposed: red = overdue ∨ blocked-by-us > 2d ∨ review > 24h; amber = due today ∨ client-blocked > 2d ∨ stale > 14d).

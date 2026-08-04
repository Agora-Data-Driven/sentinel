# Taskboard rebuild — analysis, decisions, roadmap

> **Status (2026-08-04): Stage 0, 1.1, Stage 2, 3.1, 3.2, ALL of Stage 4 except 4.3, and ALL of Stage 5 are BUILT — none of it deployed. Remaining: 1.2 (needs 1.1 deployed first — §5.1), 3.3 / 3.4 / 3.5, 4.3 (blocked on 3.4 having RUN), 6.1, 6.2, and the 0.3 human reconciliation pass.** Analysis read off the tree, not remembered —
> every claim carries a file:line anchor.
>
> **The goal:** Sentinel is the one system where tasks are created, assigned, updated and managed.
> Atrium's taskboard becomes a **read-only monitoring view**. Reference UI: `taskboard_prototype.html`
> at the estate root (its own header notes it is the TARGET state, not what ships).
>
> Decisions D1–D15 in §3 are settled. §6 is the build order.

---

## 1. What is actually wired today

There is not one taskboard. There are **three surfaces over two stores**, connected by one HMAC
bridge that only runs in one direction — and it is not the direction you would guess.

| # | Surface | Store | Who can write |
|---|---|---|---|
| S1 | **Sentinel board** — embedded in `/dashboard` (`frontend/static/js/taskboard.js`, `TaskBoard.mount`) | Postgres `tasks` ([task.py:14](../backend/app/models/task.py#L14)) | every staff role, scoped by `task_perms` |
| S2 | **Atrium console board** — Delivery → Task Board in `admin_atrium.html` (`_task_board`, [main.py:4878](../../atrium/services/portal/dash/main.py#L4878)) | `ws["tasks"]` in `workspace/<c>.json`, one file per client | any `is_superadmin()` admin |
| S3 | **Atrium client Tasks tab** — the `progress` pane in `atrium.html` (`_progress_tasks`, [main.py:1335](../../atrium/services/portal/dash/main.py#L1335)) | the same `ws["tasks"]` | the **client** (comment, request-changes, quick-add) **and the team** (drag-to-move, delete ✕) |

### 1.1 The bridge already works — backwards

Sentinel reads *and writes* Atrium's cards through `services/atrium_tasks.py` (HMAC, purposes `tasks`,
`task-detail`, `task-update`, `task-delete`, `task-move`, `task-add`, `task-comment`). An Atrium card
lands on the Sentinel board under the composite id `atrium:<client_key>:<task_id>`, and every route in
`routers/tasks.py` tests that prefix first and writes across the bridge instead of to Postgres
([tasks.py:225](../backend/app/routers/tasks.py#L225), `:311`, `:375`, `:404`, `:440`, `:474`, `:505`).

**Sentinel editing Atrium is built and tested.** That is the foundation the whole plan stands on.

### 1.2 🔴 The direction that does NOT work: Sentinel → the client

`POST /api/tasks/{id}/send-to-atrium` ([tasks.py:534](../backend/app/routers/tasks.py#L534)) — what an
Account Manager presses to share a task with a client — does exactly three things:

```python
task.atrium_visible = True
approval = AtriumApproval(task_id=task.id, sent_at=utcnow())
_log(db, task.id, user.id, "atrium", "internal", "sent_to_atrium")
```

It **creates nothing in Atrium.** `atrium_tasks.add_task()` — the one function that would POST
`/api/internal/task-add` and mint a real client card — is **called from nowhere in the repo** (verified:
zero hits for `atrium_tasks.add_task` under `backend/`). The AM gets a success toast, the drawer shows
an "✓ In Atrium" pill ([taskboard.js:417](../frontend/static/js/taskboard.js#L417)), and the client's
Tasks tab stays empty forever.

Live consequences:

- `Task.atrium_visible` has no referent on a Sentinel-owned row. **Every existing `True` points at a
  card that was never created.**
- `AtriumApproval.client_response` / `responded_at` / `revision_notes` are **never written by any code
  path** — dead columns modelling a client-approval loop that does not exist on this side.
- No reverse channel exists. A client's comment or change-request reaches Sentinel only because
  Sentinel *re-reads Atrium's card*. A Sentinel-owned task can never receive one.

This is the most important defect in scope, and Stage 0 is nothing but fixing it.

---

## 2. Sentinel taskboard audit

### 2.1 Redundant / unnecessary — retire

| Item | Where | Why it goes |
|---|---|---|
| `Task.checklist_json` | [task.py:39](../backend/app/models/task.py#L39) | Legacy flat list, superseded by `maintasks_json`, not written since the two-level breakdown shipped ([tasks.py:288](../backend/app/routers/tasks.py#L288) says so). Keep the read-migration in `maintasks.normalize`; drop it from `task_detail`'s output ([serializers.py:214](../backend/app/serializers.py#L214)), which ships a second copy of the breakdown to every API consumer. |
| `AtriumApproval`'s three response columns | [task.py:135-137](../backend/app/models/task.py#L135) | Never written. Replaced by the real reverse channel (D4). |
| `POST /{id}/attachments` | [tasks.py:515](../backend/app/routers/tasks.py#L515) | Records a filename + byte count as a comment and **throws the bytes away** ("MVP: no blob store wired"). It looks like file upload and is not. |
| `Task.campaign` as a second field | [task.py:21](../backend/app/models/task.py#L21) | The form writes the same string to `title` **and** `campaign` ([taskboard.js:750](../frontend/static/js/taskboard.js#L750)). Two columns, one value, guaranteed to diverge the first time anything edits one via the API. |
| The "✓ In Atrium" pill on unpublished rows | [taskboard.js:417](../frontend/static/js/taskboard.js#L417) | Reports a share that never happened (§1.2). |

Kept, contrary to my first read: **both manager views stay** (§2.4j).

### 2.2 Needs changing / simplifying

1. **🔴 Statuses are stored as display strings, and the bridge is keyed by them.** Sentinel:
   `To Do · In Progress · Revision Needed · Completed · Blocked`
   ([constants.py:117](../backend/app/constants.py#L117)), stored as the literal string on every row,
   editable in Manage → Task Fields. Atrium: keys `todo · in_progress · blocked · revision · completed`,
   canonical, never renamed. `STAGE_BY_STATUS` ([atrium_tasks.py:68](../backend/app/services/atrium_tasks.py#L68))
   is a **5-entry literal map keyed by Sentinel's display strings** — so renaming a status in the Manage
   UI silently breaks the bridge for every card (the move then 400s "Invalid status"). The prototype's
   `Blocked → Parked` rename walks straight into this. **A key/label split is the prerequisite, not a
   nice-to-have.**
2. **Moves are unguarded, and nothing surfaces why they shouldn't be.** Atrium removed its stage guards
   on purpose 2026-07-28 (a drop that bounces back reads as a broken board) — correct. But a card with
   six open steps also drops into Completed with no signal at all. The prototype has the right posture:
   **surface, never enforce** (`taskboard_prototype.html:1032` — "N steps still open — surfaced, not
   enforced").
3. **Two grouping concepts collide.** `labels_json` (Design/Copy/Ads/SEO/Dev) is a free list in
   Sentinel; Atrium *derives* one label from the department (`TASK_DEPT_LABEL`: Acquisition→Paid Media,
   Lifecycle→Organic, rest→Website). Sentinel's form no longer offers labels at all — the server seeds
   them from the service template ([tasks.py:265](../backend/app/routers/tasks.py#L265)) — so the field
   is half-retired: stored, rendered, uneditable. Adopt Atrium's derived model.
4. **One name, two fields** (§2.1). The thing has a **name**; "campaign" is either a real separate
   attribute or it does not exist.
5. **`?open=<id>` deep links point at `/dashboard`** ([tasks.py:301](../backend/app/routers/tasks.py#L301), `:364`)
   because the board is embedded there. Every notification row minted since 2026-07-26 carries that
   URL — extracting the board to its own page (D7) must forward them or they land on a boardless page.
6. **No status affordance on mobile.** Drag-and-drop is the only move control in the board view; the
   drawer's `<select>` is the only one in the drawer. On a phone the board is a horizontal scroll with
   no way to move a card.

### 2.3 Missing — required for an efficient workflow

| # | Missing | Why it matters | In prototype |
|---|---|---|---|
| M1 | **Publish a Sentinel task to a client** | §1.2. Today the AM's only path is to type the task a second time into Atrium's console. | yes |
| M2 | **Review state** (`review_state`, `reviewer_id`) | Sentinel has **no review field at all** — "For Review" was retired as a *status* 2026-07-30 and nothing replaced it. "Done" is one person's unilateral claim. | yes |
| M3 | **Park with a reason + resume target** (`on_hold`, `hold_reason`, `resume_to`) | Atrium-only fields today ([atrium_tasks.py:233](../backend/app/services/atrium_tasks.py#L233), `ONLY_ATRIUM`). A Sentinel task blocked on a client cannot record why, and nothing remembers which column it left. | yes |
| M4 | **Past work / archive** (`archived`, `completed_at`) | A finished service sits in Completed forever; the column becomes a graveyard and the counts stop meaning anything. | yes |
| M5 | **`start_date`** | Atrium has it and renders a Started → Going live timeline. Sentinel has only `due_date`, so a task has no duration and no schedule view is possible. | yes |
| M6 | **Standalone ad services** (Video / Static / Carousel with no campaign) | Those recipes live **only inside** the Google/Meta Campaign template, so "make me one video ad" must raise a campaign shell nobody wants, or Custom (blank) and lose the recipe. | yes |
| M7 | Bulk actions (reassign / move / prioritise N cards) | Triage on a 60-card board is one drawer at a time. | no |
| M8 | Saved views / a my-work default | Every manager re-applies the same four filters on every visit. | no |
| M9 | Overdue surfaced on the board | `_aggregate` counts it for Monitor ([tasks.py:163](../backend/app/routers/tasks.py#L163)); the board only tints the due chip. No "everything overdue" view. | partial |
| M10 | Recurring / retainer services | Monthly deliverables are re-created by hand every month. | no |

### 2.4 Roles, permissions, assignment, monitoring

The model is clean and centralised (`services/task_perms.py`), enforced at the dependency layer. The
problems are at its edges.

**a) 🔴 Two permission models on one board.** A Sentinel row is scoped by *ownership* (assigned / team /
creator); an Atrium card by *role* (`can_view_atrium` = team lead and up) because it has no assignee,
team or creator to test ([task_perms.py:106-128](../backend/app/services/task_perms.py#L106)). Both are
right in isolation. Together they mean **the same board answers a different question depending on which
store a card came from**: for an employee it is "my work"; the day they become a team lead it also
becomes "every client's unassigned work". D1's projection model dissolves this — see §4.

**b) `can_edit = can_view`** — a single alias, [task_perms.py:72](../backend/app/services/task_perms.py#L72).
Anyone who can see a card can rewrite its title, dates, breakdown and notes. **No read-only seat exists
anywhere in the model.** D8 adds one.

**c) Assignment hole: routing to a team puts the card on nobody's board.** `assigned_team_id` exists,
but an employee's `can_view` tests `_assigned` only — team assignment does **not** surface the card.
So the natural flow *AM files it → routes it to Acquisition → the lead delegates the steps* leaves the
card invisible to everyone but managers during the middle step.

**c-bis) 🔴 There is nothing to auto-assign TO: `teams` has no lead column.**
[models/user.py:38-47](../backend/app/models/user.py#L38) is `id · name · shift_template_id · members`.
`_leads_team` works the *other* direction — a user whose role is `team_lead` and whose `team_id` matches
the task — so a team can have zero or several leads and nothing marks a primary. Any design that says
"route it to the team and it lands on the lead" is inventing a column. (Both prototypes had a
"Route to Acquisition · **Ehjay**" button doing exactly that; it now routes to the team and picks
nobody.) So the assignment ladder has to be:

| | Step | Who |
|---|---|---|
| 1 | Service type → **department** (`ServiceTemplate.dept`, already stored — today used only *backwards*, to filter the picker) | the form |
| 2 | Department → card **visible to that team, assigned to nobody** (4.2) | automatic |
| 3 | Per-step owners + `assigned_to_id` | the team lead |
| — | An employee's own quick task self-assigns ([tasks.py:249](../backend/app/routers/tasks.py#L249)) | kept as-is |

**"Routed but unassigned" must be a first-class state**, not a gap — it is the team's triage queue.
Auto-assigning a person who never accepted the work reproduces the phantom-ownership bug that the
creator-tag fix removed in July.

**🔴 And a `Team.lead_id` column is NOT the answer — I was wrong to suggest it.**
[`notifications.notify_managers(db, …, team_id=…)`](../backend/app/services/notifications.py#L28)
already exists and fans a notification out to admins **plus every user whose role is `team_lead` and
whose `team_id` matches**. Leads are found by **query**, which is why zero leads and three leads both
work and no primary has to be invented. The actual defect is narrower than a schema change:

> `create_task` and `update_task` notify **`assigned_to_id` only**
> ([tasks.py:299](../backend/app/routers/tasks.py#L299), [:362](../backend/app/routers/tasks.py#L362)).
> So a card routed to a team **notifies nobody** and silently waits for someone to notice it.

One missing call site, using a helper that already ships. No column, no migration, no guess.

**d) A person may not be named by a non-delegating role — but a TEAM may be.** Filing into
`Development`'s queue is not delegation: nobody is made responsible, the team's lead is notified, and
the card is owned by no one until they triage it. An Acquisition employee who spots a website bug
should not have to own the fix. Priority stays a manager call regardless
([tasks.py:253](../backend/app/routers/tasks.py#L253)).

The consequence to handle: once routed to another team, the card **leaves the filer's board** — the
creator tag deliberately no longer grants board visibility (that was the July regression). "I filed it
and now I can't find it" is its own bug, so the answer is a **separate list**, not a restored board
card: *Filed by me*, showing only **where the work went** (team, current owner or "awaiting triage",
status, client) and none of the internal fields. The creator tag grants that list and nothing else.

**e) 🔴 Step-level assignment bypasses `can_reassign` entirely.** The drawer renders an owner
`<select>` on every main task and every sub-task
([taskboard.js:437-441](../frontend/static/js/taskboard.js#L437), wired at
[:490](../frontend/static/js/taskboard.js#L490) / [:494](../frontend/static/js/taskboard.js#L494)), and
they save through the `maintasks` field. But `update_task`'s delegation guard covers **only**
`assigned_to_id` and `assigned_team_id`
([tasks.py:341](../backend/app/routers/tasks.py#L341)) — `maintasks` goes through its own branch
([:353](../backend/app/routers/tasks.py#L353)) with no assignee check at all.

And `task_perms._assigned` counts **step owners** for visibility
([task_perms.py:48](../backend/app/services/task_perms.py#L48)). So today an employee who cannot
reassign a task *can* put any card onto any colleague's board by naming them on a sub-task. Delegation
by another route, ungated. Fix it where the field is written, not in the UI.

**f) UI and server disagree on priority.** The server lets a team lead set priority within their team
([task_perms.py:85](../backend/app/services/task_perms.py#L85)); the frontend gates on
`isAM = S.can("account_manager")` ([taskboard.js:10](../frontend/static/js/taskboard.js#L10)) and shows
them a read-only value. The server is right.

**g) Refusal has to be expressible, or a wrongly-routed card just rots.** D10 lets anyone file into
another team's queue, which makes "this is not ours" a normal event. Three rules keep it honest:

- **Only while unassigned.** Once somebody on the team picks the card up they own it, and the right
  move is to reassign or re-route — not to bounce.
- **Ownership is never left vague.** A bounce clears `assigned_team_id` and assigns the card **back to
  the filer**, so refused work is always held by someone. A card that lands nowhere is the failure mode
  this avoids.
- **The reason is internal and recorded** (`sent_back_by_id` + `sent_back_reason` in history). It must
  never reach the projection push — a client learning that two departments disagreed about their work
  is exactly the leak the client-safe split exists to prevent.

A consequence worth noting because it looks like a bug and is not: the moment a lead sends a card back,
**they can no longer see it** — the team link is gone and it is not assigned to them, so `can_view`
correctly excludes it. Refusing work stops it being yours.

**h) `completed_week` is derived from `updated_at`** ([tasks.py:170](../backend/app/routers/tasks.py#L170)),
so **editing a finished task re-dates its completion** and inflates this week's throughput. `completed_at`
(M4) fixes it.

**i) Monitoring has no history.** `GET /api/tasks/summary` computes everything from the live table: no
trend, no throughput over time, no per-client rollup (only per-person).

**j) Board views: keep all three.** I proposed merging By-Employee into Monitor; on reading them they
answer different questions — Monitor is a numeric rollup for load-balancing
([taskboard.js:190](../frontend/static/js/taskboard.js#L190)), By-Employee is swimlanes you can drag
*between* ([taskboard.js:154](../frontend/static/js/taskboard.js#L154)). Merging would cost the drag
target. No change.

---

## 3. Decisions

| | Decision | Consequence |
|---|---|---|
| **D1** | **Atrium keeps `ws["tasks"]` as the store for client-facing cards.** Sentinel is the only place anyone edits. No migration. | The Atrium card becomes a **projection** of the Sentinel row — see §4. |
| **D2** | **Atrium's write surfaces are removed**: the console Delivery → Task Board pane goes, and the team's drag-to-move + delete ✕ come off the client Tasks pane. | Atrium's task routes shrink to reads + the two client writes. |
| **D3** | **The client quick-add composer survives as a REQUEST**, not a task. It lands in Sentinel for triage. | Needs an intake queue + a reverse channel (D4). Preserves the live-call capture flow, which is the one thing clients actively use. |
| **D4** | **A reverse channel exists**: client comment / request-a-revision / quick-add reach the Sentinel row. | Replaces the dead `AtriumApproval` columns with something real. |
| **D5** | **A Team Lead must approve before Completed.** Approval gates *done*, not *visible*. | M2. Surfaced-not-enforced everywhere else; this one gate is real. |
| **D6** | **Share-on-create defaults ON** for a client-facing service — the client watches it cross the board from day one. | Publishing must be reliable and instant, so D1's projection has to be synchronous on create. |
| **D7** | ✅ **BUILT 2026-08-03.** **The board gets its own page + sidebar nav**, out of the Dashboard. | `/tasks` is a real page again; `main.dashboard_page` forwards `?open=`/`?new=`/`?view=` and ONLY those (a bare `/dashboard` must stay the landing page). New notifications mint `/tasks?open=`. The dashboard keeps a **my-work strip** (open / overdue / awaiting my approval + the five next tasks) that links in. |
| **D8** | **A real read-only seat exists in Sentinel** — see and not touch. | `can_edit` splits from `can_view`; every write guard has to be audited. §5.3. |
| **D9** | **No `Team.lead_id`.** Routing to a team notifies its leads via the existing `notify_managers(team_id=…)`; leads stay a query. | One missing call site, not a migration. Reverses an earlier suggestion in this doc — see §2.4c-bis. |
| **D10** | **A non-delegating role may route to a TEAM, never to a person.** Self-assign only when no team is implied. | Needs a *Filed by me* list so the filer can still see where it went (§2.4d). |
| **D11** | **A receiving lead may send queued work back to whoever filed it**, with a reason — but only while it is still unassigned. | §2.4g. Refusal becomes explicit and auditable instead of a card rotting in a queue. |
| **D13** | **A new status must declare its Atrium stage.** `task_vocab` gains a `stage` column, required for `kind="status"`; the five stages stay canonical and any number of Sentinel statuses map onto them. | Closes a live hole: a custom status today has no stage, so moving a client card into it 400s. Folds into Stage 1. |
| **D14** | ✅ **BUILT 2026-08-04.** **Labels are DERIVED from the department** (Acquisition→Paid Media, Lifecycle→Organic, rest→Website), like Atrium. Design/Copy/Ads/SEO/Dev go. | Resolves §2.2.3. One label, never wrong, no manual step, and the two boards finally agree. `constants.TASK_DEPT_LABEL` + `label_for_department()` key off the team name's **first word**, so Sentinel's "Data Analyst" and Atrium's "data" answer the same without either hardcoding the other's wording; `TASK_LABELS` is derived from the mapping so the two can never disagree. Create derives it and **ignores** anything the caller (or a template's `default_labels`) sent; re-routing relabels and logs it; **no department = no label** (inventing "Website" would file untriaged work in a real bucket). 🔴 `task_config.reconcile_labels` runs on **every boot**, not only a fresh DB — the boards carrying the retired vocabulary are the non-empty ones — retiring old rows (deactivated, never deleted: history references them), adding the derived ones, and recomputing every task's label. Safe to re-run because the value is a pure function of `assigned_team_id`; idempotent, asserted. Manage's "Default labels" picker is gone. Pinned by `tests/test_task_labels.py` (15 tests). |
| **D15** | **Stale `atrium_visible` rows are reconciled case-by-case**, from a generated per-client report. Never bulk-published. | Stage 0.3 is a report + per-row action, not a migration. These are live client records. |
| **D16** | **Opening a task is a WIDE CENTRED MODAL** (920px, `.modal.wide`) with a **two-column body** — the record left, work + conversation right. Revised the same day: a split-view side panel was built first and **removed**, because the board needs ≈2156px for one (sidebar 248 + 5×288 columns and gaps 1496 + panel 356 + padding), and it already scrolls horizontally at ~1800px with no panel at all. At 340px the `.spread` grid collapsed to one column, stacking eleven label/value pairs above the breakdown; at 920px it gives four. | Kept from the panel attempt: `?open=<id>` in the URL via `replaceState`, so a click, a shared link and a notification all land identically. 🔴 `openTaskModal` must re-point `S.modal`'s ✕ / overlay-click / Esc — all three call its internal close, so wrapping the returned `close` leaves the URL lying. |
| **D12** | **Assignment and routing are CONTROLS, not action buttons.** A team select over every team; an owner picker on every phase and step, the routed team's people first and everyone else still reachable; one bulk "assign the N unowned steps to…". | Replaces the prototype's hardcoded `Route to Acquisition` / `Delegate to Justine & Zhen`. Step owners get gated like any delegation — §2.4e. |

---

## 3.1 The prototype of this plan

**[`taskboard_target_prototype.html`](taskboard_target_prototype.html)** (beside this file) is the
decided state, driveable. Open it with `file://` — no build step, no external requests.

It **supersedes the estate-root `taskboard_prototype.html`** for the bridge mechanics: that one models
the shadow, this one models the projection (§4). The root file is still the reference for the *card and
drawer visual language*, which is unchanged.

What it demonstrates, all interactive: six seats including a **read-only Viewer** (D8) and the client ·
a **Bridge: up/DOWN** switch, so you can watch a failed push become **loud and retryable** instead of
today's success-toast-over-an-empty-tab (0.2) · **Share** minting a real card and storing the returned
id (0.1) · share-on-create defaulting ON (D6) · Park storing the column it left, Resume naming it (M3) ·
review gating **Mark complete** (D5) · file → Past work on both boards (M4) · the client's quick-add
filing into a Sentinel **Intake** queue (D3) · comment / request-a-revision reaching the row (D4) ·
Task Board as its own nav item (D7) · a Team Lead setting priority (4.1) · a card routed to a team
appearing on that team's board (4.2). The inspector shows the record, the exact push payload with the
internal keys **struck through**, the reverse channel, and the whole of what Atrium holds.

The **New service** modal is three fields and a switch, with everything else behind **More options** —
the same progressive disclosure the real form already has. That block is where **Service type** (the
automated task creator, editable at Manage → Services), **Campaign** (shown only for a campaign-shaped
service), **Service charge**, Lead, Priority, Content type and Internal notes live. Picking a service
fills the department from `ServiceTemplate.dept`, previews the phases + step count it will seed, and a
line under the block states **where the card will land** before you commit it (§2.4c-bis).

`taskboard_target_prototype.smoke.js` exercises every one of those paths against a minimal DOM stub
(no jsdom dependency — the estate has none): `node taskboard_target_prototype.smoke.js` → **42/42**.
It caught a real crash in the inspector's serializer, so run it after any edit to the prototype.

---

## 4. The target architecture — the Atrium card is a PROJECTION

D1 keeps Atrium as the store, and D2 removes every writer on that side. Those two together give a
sharper model than the prototype's own:

```
┌──────────────────────── SENTINEL — system of record ────────────────────────┐
│  Postgres `tasks`                                                            │
│  create · assign · delegate · move · park · review · file                     │
│  every internal field · every permission decision · the full audit trail      │
└──────────────┬───────────────────────────────────────────▲──────────────────┘
               │  push the client-safe subset               │  reverse channel
               │  (stage, name, client note, phase           │  (comment · request a
               │   progress, launch date, deliverable)       │   revision · quick-add
               ▼                                            │   request)
┌──────────────────────── ATRIUM — read-only monitor ─────────────────────────┐
│  ws["tasks"]  =  a rendered copy, never authored                             │
│  client Tasks tab: read-only + comment / request-a-revision + quick-add      │
│  team console board: REMOVED                                                 │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Why a projection and not the prototype's "internal shadow".** The prototype has the published
Sentinel row become an internal shadow whose *client-facing fields are then edited on the Atrium card*
(`taskboard_prototype.html:896`). That splits field ownership between two records and needs a rule for
every field, forever. It made sense when both boards were editable. Under D2 nothing edits the Atrium
side, so the simpler rule holds: **the Sentinel row owns every field; Atrium receives a copy of the
client-safe subset on every change.** One authority, one direction, no reconciliation.

Three invariants this preserves, all already load-bearing:

1. **The client-safe split stays enforced in `serializers.py`** — assignee, team, priority, service
   charge, internal notes and every step's "done when" never cross. The projection push is the
   narrowest possible place to enforce it, and `atrium_payload` already exists there.
2. **Reads fail soft, writes fail loud.** An Atrium outage hides cards; it never reports a deletion
   (`_atrium_error`, [tasks.py:74](../backend/app/routers/tasks.py#L74)). A failed *push* must be
   visible and retryable — a silently-unpublished card is exactly today's bug.
3. **Stage keys are canonical.** Labels move; keys never do.

**The one real cost: adoption.** Cards that originated in Atrium — typed into the console board, or
filed by a client's quick-add — have no Sentinel row. With the console board gone, no new ones appear
except via quick-add (D3, which routes to intake). But the existing ones must be **adopted**: import
each into a Sentinel row, link it, and thereafter treat it as a projection. That is WP 3.4, and it is
the one work package that touches live client data.

---

## 5. Two hazards worth reading before starting

### 5.1 The status rename order is load-bearing

Retiring or renaming a status is **two moves in one order**, and doing it wrong makes cards vanish with
no error (AGENTS.md §5). `task_config.RETIRED_STATUSES` + `retire_statuses(db)` do both halves and run
from `main._seed_config` on **every boot**. Meanwhile `constants.TASK_BLOCKED` is a code literal that
feeds that boot-time sweep. So for `Blocked → Parked`: **deploy the code first, then rename.** The
reverse order moves live cards onto a status with no column.

### 5.2 A new column reaches prod two ways, and needs both

Prod runs Alembic on boot now (`backend/entrypoint.sh` → `migrate.py`), but `create_all` usually wins
the race — so a new column needs an **existence-guarded revision** *and* an entry in
`main._ensure_columns`. Copy `a9c4e7f2d5b8_service_templates_task_vocab.py`. Validate the single
revision in isolation (`alembic stamp <parent>` on a seeded DB, then `upgrade head`) — the full chain
**cannot** replay onto a fresh SQLite DB (it dies at `d8f4b2c6a9e3` in batch mode).

### 5.3 The read-only seat (D8) is not a one-line role — ✅ built 2026-08-03, and §5.3 was right

A viewer must see **everything** and write **nothing**, so it does not slot into `ROLE_RANK`'s linear
ladder — `require_min_role` would either give it write endpoints or hide the board. The shape that
works:

- `can_view` / `can_view_atrium` → `True` for viewer (it is a monitoring seat, so it is cross-client).
- `can_edit`, `can_move`, `can_reassign`, `can_prioritize`, `can_delete`, `can_bridge` → `False`, tested
  **first**, before the `_is_full` branch.
- **Every write endpoint audited**, including the ones that guard with `require_min_role` /
  `require_roles` rather than `task_perms` (`/priority`, `/send-to-atrium`, and everything in
  `manage.py`). This audit is the bulk of the work, and `tests/test_security_rbac.py` is where it gets
  pinned.

**What the audit actually turned up** (all fixed): `can_edit` and `can_edit_atrium` were bare aliases
of their view predicates; **four of the five Atrium branches in `routers/tasks.py` were writes guarded
by the read predicate** (`_require_atrium`); posting a **comment** and adding an **attachment** were
writes gated on `can_view`; and `create_task` needed a guard of its own since there is no task yet for
a `task_perms` predicate to take. One more, found only by making Monitor readable to the seat: turning
`canMonitor` true for a viewer in the frontend silently re-enabled the **Delete** and **Approve**
buttons for any viewer carrying a `team_id`, because two predicates were `canMonitor && team match`.

---

## 6. Roadmap

Ordered so each stage ships on its own and none depends on a later one.
Sizes: **XS** < 1h · **S** ≤ half a day · **M** 1–2 days · **L** 3+.

### Stage 0 — make the truth true (unblocks everything else)

| WP | Work | Size |
|---|---|---|
| 0.1 | ✅ **DONE 2026-08-03.** **Wire publish for real.** `send-to-atrium` calls `atrium_tasks.add_task`, stores the returned `atrium:<key>:<id>` on the Sentinel row (new `atrium_task_id` column — §5.2), and fails **loud**. `atrium_visible` finally means what it says. | M |
| 0.2 | ✅ **DONE 2026-08-03.** **The projection push.** Every mutation that touches a client-safe field on a published row pushes the subset over `task-update` / `task-move`. Enforce the split in one place (`atrium_payload` in `serializers.py`). Failures surface and are retryable — never a silent unpublish. | M |
| 0.3 | 🟡 **API done, human pass pending.** **Reconcile the lie** (D15). A per-client report of every `atrium_visible=True` row pointing at nothing, with a per-row publish / clear / leave action. Never a bulk publish — some are months old, some already delivered. | M |
| 0.4 | ✅ **DONE 2026-08-04.** Retired the dead surface. **`AtriumApproval`'s three response columns** (`client_response`, `responded_at`, `revision_notes`) dropped — nothing ever wrote them, so they read as "no client has ever responded to anything"; migration `f1a6d3c8b5e2`, batch mode so SQLite and Postgres both work, and `sent_at` (the share log) is kept. **`checklist`** removed from `task_detail`'s payload — `maintasks` is what every surface renders and `MT.normalize` migrates the flat rows into it, so shipping both sent the same steps twice with one copy going stale; `checklist_json` stays on the model as the migration source. **The attachments route is gone** — it read the upload, THREW THE BYTES AWAY and recorded name/size as a comment, so the board showed a paperclip for files that could never be opened; no frontend ever called it. The read plumbing is kept for the real GCS implementation (§7). The "In Atrium" pill was already gone. | S |

### Stage 1 — status vocabulary made safe (prerequisite for the Parked rename)

| 1.1 | ✅ **DONE 2026-08-03.** `task_vocab.key` + **`stage`** + free label; `STAGE_BY_STATUS` maps **key → stage**; Manage renames labels only, and **a new status must pick a stage** (D13). | M |
| 1.2 | 🟡 **Ready — needs a deploy first.** Deploy 1.1, **then** rename Blocked → Parked in Manage (now a one-field edit). Never the other order (§5.1). **Plus one line in `atrium`** — see below. | S |

**The two boards do NOT need the same columns — but they must not disagree in WORDING.** Three
separate layers, and only the middle one crosses the bridge:

| layer | where | value today | may change? |
|---|---|---|---|
| Sentinel status **label** | `task_vocab.name` | "Blocked" | freely, in Manage |
| the **stage key** | `task_vocab.stage` ↔ `workspace.TASK_STAGES` | `blocked` | 🔴 **never** — canonical both sides |
| Atrium **display label** | `main.TASK_STAGE_META` (team) · `TASK_CLIENT_STAGES` (client) | "Blocked" | freely, it is display-only |

So Atrium having no "Parked" column breaks nothing: the card travels as the KEY `blocked` and each
side renders its own word. Sentinel may also have MORE columns than Atrium — several statuses can
share one stage (Atrium has exactly five) — which is the whole reason `stage` is a column and not a
guess. What it does mean is that the moment 1.2 renames the label, **the team's board says "Parked"
while the client's still says "Blocked"** — two names for one column across surfaces, which is
precisely the drift that caused the For Review / Waiting-for-Client mess (§2.2.1). So 1.2 is two
edits, not one:

1. Sentinel: rename the status in Manage → Task Fields.
2. `atrium/services/portal/dash/main.py`: relabel the same stage. `TASK_CLIENT_STAGES` was
   deliberately kept as its own tuple so a **client-only** wording change stays one line —
   recommended: **"Parked" for the team, "Paused" for the client**, because Atrium already shows a
   held card "⏸ Paused" and the client should never read the word "Blocked" about their own work.
   🔴 Change the LABEL only. Touching the key breaks every stored row on both sides.

Also fixed while checking this (2026-08-03): `task_config._status_rows` now returns rows in **board
order**. `status_for_stage` answers "which column IS the blocked one?" — Park's target, and the
retirement sweep's — and with two columns on one stage that answer was whatever the DB returned
first. Left-most column wins now; pinned by `tests/test_task_status_stages.py`.

### Stage 2 — the missing workflow fields

| 2.1 | ✅ **DONE 2026-08-03.** `start_date` (M5), `completed_at` + `archived` (M4) + the Past work drawer. Fixes the `updated_at` throughput bug (§2.4h): the rollup counts the stamp, and a completion with no stamp is counted on no day at all rather than on whatever day someone last touched it. | M |
| 2.2 | ✅ **DONE 2026-08-03.** `on_hold`, `hold_reason`, `resume_to` + Park / Resume → \<column\> (M3). Dragging a parked card out of the blocked column also ends the hold, so "On hold" can never outlive the pause. | M |
| 2.3 | ✅ **DONE 2026-08-03.** `review_state`, `reviewer_id` + Submit / Approve / Request changes, **gating completion** (M2, D5). Open steps stay surfaced, not enforced (§2.2.2). An approval is SPENT by the completion it authorised. | M |

All three are keyed off the status's **stage**, never its label (`task_config.is_completed`), so the
Stage 1.2 rename cannot break them. Built in `services/task_workflow.py`; pinned by
`tests/test_task_workflow.py` (41 tests). Two things this stage deliberately did NOT do:

- **`completed_at` is not backfilled from `updated_at`.** That number is exactly what this column
  exists to stop trusting — backfilling would date every historically-finished task to its last edit
  and dump a pile of them into "completed this week".
- **A self-approval is possible, and recorded.** Leads are found by query (D9), so a team can have
  ZERO leads; a hard self-approval block would make the done column unreachable for that team
  forever. Every approval stamps `reviewer_id` and writes history, so it is visible instead of
  impossible. Revisit if it gets abused — see §7.

### Stage 3 — Atrium becomes read-only (D2, D3, D4)

| 3.1 | ✅ **DONE 2026-08-03** (in the `atrium` repo). Stripped the team's write affordances from the client Tasks pane — `data-pgcol` drop targets, `data-pgdrag` wrappers, the `data-pgdel` ✕, their CSS, and the whole wiring IIFE (a comment marks where it stood). The board is read-only for EVERYONE now, not merely for clients. `_atrium_smoketest.py`'s assertion was **reversed** — it used to require the team's cards to be draggable — and the atrium `AGENTS.md` + `dash/CLAUDE.md` entries that promised the affordances were rewritten. | S |

> **Not touched by 3.1, on purpose:** the per-column "+ Add card" form and the quick-add composer.
> Those are the D3 request path and 3.3 rebuilds them; removing them piecemeal first would mean
> churning the same markup twice.

| 3.2 | ✅ **DONE 2026-08-03** (in the `atrium` repo). **Read-only, not deleted** — your call, and the better one: every VIEW on the console board survives (columns, search, client/dept/person filters, swimlanes, density, caps, the Delivery Calendar, the tabbed overlay) and every WRITE is gone. The seven `/w/<c>/admin/task*` routes answer **410 Gone** with the reason from one handler; the New-Service overlay + its service-type/ad-production builder, the Edit overlay, the breakdown's checkboxes / inline renames / owner selects / ✕ / add-forms, the hold form, the comment composer, Resolve, Archive and advance-stage are all removed, along with ~340 lines of the optimistic-write JS behind them. The overlay's one action is **Open in Sentinel →** (`?open=atrium:<client_key>:<task_id>`, the composite id Sentinel's own board already uses). The Assistant's `add_task`/`move_task`/`complete_task` proposals are out of its registry (`comment_task` stays). `move_task_stage` keeps its `ValueError` contract. | M |

> **Three consequences worth carrying forward.**
> 1. **`service_templates.py` is now unwired in Atrium** — kept on purpose (it is the written record
>    of the recipe shape, and its `build_maintasks` is still tested), because Sentinel's
>    `ServiceTemplate` table owns the recipes. Don't re-wire it into a form there.
> 2. **410, never 404.** A stale console tab still holding a rendered form must read "managed in
>    Sentinel", not "not found" — one reads as a decision, the other as a bug.
> 3. **The deep link targets `/dashboard`, not `/login`.** Sentinel's `/login` drops the query
>    string (it either short-circuits or renders the form), so `?open=` would be lost. The new
>    `sentinel_base` template var is `SENTINEL_URL` minus `/login` for exactly this.
| 3.3 | **Intake queue** (D3): the quick-add composer files a *request*, which lands in Sentinel as untriaged and becomes a task when someone accepts it. | M |
| 3.4 | **Adoption** (§4): import every existing Atrium-origin card into a linked Sentinel row. Touches live client data — dry-run first, per-client, reversible. | L |
| 3.5 | **Reverse channel** (D4): client comment / request-a-revision reach the Sentinel row and flag it there, rather than being noticed on a re-read. | M |

### Stage 4 — permissions and assignment

| 4.1 | ✅ **DONE 2026-08-03.** Fixed the team-lead priority gate in the frontend (§2.4f — the server was always right). `isAM` survives only for Atrium-owned cards, where AM+ really is the rule; Sentinel rows use `canPrioritize(t)` (lead within their own team) and the create/edit form uses `canPrioritizeOnForm` (a lead may set priority on work they raise, mirroring `create_task`'s `may_delegate`). | XS |
| 4.2 | ✅ **DONE 2026-08-03.** `task_perms._team_queue`: work routed to my team and owned by **nobody** is on my board. Deliberately narrow — the moment somebody owns it, it is their job and leaves everyone else's, or this would undo the July 2026 fix that stopped an employee's board carrying other people's work. | S |
| 4.2b | ✅ **DONE 2026-08-03.** Routed-and-unassigned is a first-class state now: visible to the team (4.2), notified to its leads (4.2c), reachable by the filer (4.2d) and refusable (4.2e). The service → department half already worked (`ServiceTemplate.dept` fills the form). | S |
| 4.2c | ✅ **DONE 2026-08-03.** `_notify_team_routed` on both create and PATCH. Silent when the card already has an owner (that person was notified directly; pinging the leads too is noise). 🔴 It is called with `commit=False` — the caller must commit, and the first cut didn't, so the rows were silently dropped. Caught by the test, not by hand. | XS |
| 4.2d | ✅ **DONE 2026-08-03.** A non-delegating role naming a team gets a routed, UNASSIGNED card; naming a person is still ignored; no team named still self-assigns. `GET /api/tasks/filed-by-me` answers where it went (team · owner or *awaiting triage* · status · client · bounce reason) and carries no internal field. Declared **before** `GET /{task_id}` or FastAPI swallows it (AGENTS.md §5). | S |
| 4.2f | ✅ **DONE 2026-08-03** — the live hole is closed. `update_task` compares the breakdown's owner set before/after (`maintasks.owner_ids`) and refuses any change that involves anybody but the actor, unless `can_reassign`. Ticking, renaming, adding and deleting steps stay open to whoever can edit; self-assignment stays open to everyone. Pinned by 6 cases in `test_security_rbac.py`. | S |
| 4.2g | ✅ **DONE 2026-08-04.** **Assignment as controls** (D12). The prototype's hardcoded `Route to Acquisition` / `Delegate to Justine & Zhen` buttons only ever fit the one example they were drawn for; these are the general form of the same three actions, placed in the drawer where the breakdown already lives. **Routing:** a team select (`#bd-team`) gated by a new frontend `canReassign(t)` mirroring `task_perms.can_reassign` — disabled with a reason rather than hidden, and a failed PATCH snaps it back to the stored value. Re-routing reloads the board because it also moves the derived label (D14). **Owner pickers:** every phase and step picker renders **two `<optgroup>`s** — the routed team first, "Everyone else" below — because work is routed to a department and then owned inside it ~90% of the time, while "anyone in the company" is still a real need and a picker that hid them would send people back to the Edit form to re-route first. An Atrium roster carries no team, so it degrades to one flat list. **Bulk sweep:** "Assign the N unowned steps to…" appears only when N > 0 and touches **only** steps nobody owns — it never reassigns work that already has an owner, because that is someone's job and a sweep is not where you take it off them. Server-side nothing changed: 4.2f already gates owner changes (`maintasks.owner_ids` vs `can_reassign`), and self-assignment stays open to everyone. Verified in the jsdom harness: routing bound to the right team, "Assign the 9 unowned steps to…", optgroups `["Acquisition","Everyone else"]`. ⚠️ Caught pre-flight: `canReassign` did not exist on the frontend and would have been a `ReferenceError` on every drawer open. | M |
| 4.2e | ✅ **DONE 2026-08-03.** `POST /{id}/send-back` — only while unassigned, only for `can_review`, clears the team AND assigns the filer so ownership is never vague, records the reason in **history** (no new columns) and notifies them. The reason reaches the filer's *Filed by me* row and never the projection. | S |
| 4.3 | ⛔ **BLOCKED on 3.4.** Collapse the two permission models — the premise is that client cards *have* Sentinel assignees, which is only true once adoption has run. Doing it first would scope Atrium cards by an ownership they do not yet have, i.e. hide every one of them. | M |
| 4.4 | ✅ **DONE 2026-08-03.** The read-only seat (D8). `ROLE_VIEWER` at the FLOOR of `ROLE_RANK` so no `require_min_role` gate can open, named explicitly in the new `constants.VIEW_ALL_ROLES` for the reads it needs. **`can_edit` split from `can_view` and `can_edit_atrium` from `can_view_atrium`** — the two bare aliases that made the seat impossible. `_require_atrium_write` added: four of the five Atrium branches were writes guarded by the read predicate. Comments and attachments were also writes gated on `can_view`. Pinned by 17 parametrised write cases + the alias check in `test_security_rbac.py`, and verified live (22 cards + the rollup readable, all 9 writes 403). | M |

> **Pulled forward out of Stage 5 (2026-08-03): the client-note field.** The New/Edit task form had
> **no** field for `client_facing_notes` anywhere — the drawer displayed it and only the *Atrium-card*
> edit form could set it. So every task published by Send to Atrium reached the client's board with an
> empty note, even though the bridge has always sent that field. It is now **"What the client will
> read"**, on the front panel beside the internal Description (the pair reads as "what we tell
> ourselves" vs "what they read"). The rest of the prototype's modal — Client + Launch date promoted
> up front, the "where it lands" routing line, share-on-create (D6), Campaign only for a
> campaign-shaped service — is still Stage 5 work and deliberately untouched.

### Stage 5 — board UX

| 5.1 | ✅ **DONE 2026-08-04.** Dedicated Task Board page + sidebar nav (D7), **forwarding every `?open=` notification row**. `/tasks` = `tasks.html` + `tasks.js` mounting `taskboard.js`; `NAV` carries Overview + Task Board; `dashboard_page` forwards `?open=`/`?new=`/`?view=` only. The Overview keeps `renderMyWork()`. 🔴 Landed as a MERGE against origin's same-day "Overview: merge dashboard + growth hub" commit, which had embedded the board instead — the growth rings + ledger stay on the Overview, the board does not. 🔴 Shipping it exposed a latent crash in `taskboard.js`: a backtick inside the injected `<style>` comment closed the template literal, so `mount()` threw `TypeError: "…".spread is not a function` behind a bare "Couldn't load the task board" toast. `node --check` cannot see it — see `frontend/README.md`. | S |
| 5.2 | ✅ **DONE 2026-08-04.** Share-on-create toggle, default ON (D6). `TaskCreateIn.share_with_client` is **tri-state**: absent/null = "decide for me" (share when the task has a client), `True` forces, `False` opts one task out — a plain bool default could not tell "the caller said no" from "the caller said nothing", and the form only sends the field on create. Gated on `can_bridge`, so an employee filing work cannot make a manager's decision. 🔴 A bridge failure is **reported, never raised**: the task is already committed and is valid unshared, so an outage elsewhere must not throw away the AM's typing — the reason lands on `atrium_sync_error` and Retry is one click. Frontend: a checkbox under Client in More options, revealed by choosing a client. Pinned by `tests/test_task_share_on_create.py` (7 tests). | S |
| 5.3 | ✅ **DONE 2026-08-04.** Standalone ad services (M6). The three recipes (Video / Static / Carousel Ad, Acquisition) are now in `SEED_TEMPLATES` — they had existed **only in one dev database**, which is the symptom, not the cause. The cause is that `_seed_config` writes service templates **only when the table is empty**, true exactly once per database, so any service shipped after day one reached nothing and had to be retyped in Manage per environment. New `task_templates.sync_seed(db)` runs on **every boot** and is **INSERT-ONLY, matched by key**: an existing row is left completely alone (label/dept/recipe/defaults are Manage-editable and a boot-time "correction" would revert someone's customisation every deploy), and a deliberately deleted service stays deleted (Manage deletes softly, and an inactive row still counts as present). Their `content_type` is the ad FORMAT, not "Campaign", which is what correctly keeps the Campaign field hidden for them (§7). Pinned by `tests/test_service_template_sync.py` (9 tests). | S |
| 5.4 | ✅ **DONE 2026-08-04.** Bulk actions (M7), saved views (M8), an overdue view (M9). **M7:** `POST /api/tasks/bulk` (`{ids, op: status\|priority\|assignee, value}`). 🔴 **Partial success is the CONTRACT, not a compromise** — a selection is a rectangle drawn over a board, so it will routinely contain a card the actor cannot move, one already in the target column and one the D5 review gate is holding; refusing the whole batch over any of those makes the feature useless on exactly the boards it exists for. Each task is judged alone and the response names what happened to each; the UI reports the skips rather than silently moving 7 of 10. Bulk is **not a way around a guard**: same per-task `can_move`/`can_prioritize`/`can_reassign` predicates, and a move runs through the new shared **`_apply_status`** — extracted so `PATCH /{id}/status` and bulk cannot drift (the first thing to rot would be the Atrium projection). Atrium ids are refused; unassign (`null`) is a real triage action. **M8:** named views in `localStorage` (`sentinel.tb.views`) — one person's working habits, not org config — plus a built-in **My work**; restoring a view writes the values back into the filter controls, or the board would filter by values the bar is not showing. **M9:** an **Overdue** toggle comparing against `PH_TODAY` so it agrees with the server's Asia/Manila rule, excluding finished work (a completed task's due date stopped mattering). Pinned by `tests/test_task_bulk.py` (13 tests) + the jsdom harness (select-all, bulk bar, overdue filter 7-of-23). ⚠️ Two bugs the harness caught that `node --check` could not: a **TDZ** crash from the saved-view helpers being defined below their first call, and `select all` gated on `offsetParent` — a layout question, when this board rebuilds its columns from the filtered list, so every rendered card is already a shown one. | M |
| 5.5 | ✅ **DONE 2026-08-04.** A mobile move control (§2.2.6). Every card carries a **native `<select>`** of the statuses (`.t-move`), which hands a phone the OS picker and is keyboard + screen-reader operable for free — no popup layer, no new dependency. Hidden wherever a real pointer exists (`@media (hover: none)` reveals it) because dragging is better there and a second control per card is clutter; on the desktop it still appears **on focus**, which is the first move affordance a keyboard user has ever had on this board. It routes through the SAME `moveCard`, so the optimistic reposition, the Undo toast and the roll-back on failure are identical however the move was made — there is deliberately no second move path. In swimlanes the target column is matched **within the card's own lane**, mirroring `wireDnD`'s rule that moving between people is a reassignment and belongs in the drawer. `moveCard` re-syncs the select after a drag or an Undo, or the control would read the old column and the next change could be swallowed by its equality guard. Verified end-to-end in the jsdom harness: 23 selects, correct options, move persisted, and the roll-back path confirmed by a deliberately failed write. | S |

### Stage 6 — later

| 6.1 | Recurring / retainer services (M10). | L |
| 6.2 | Throughput history for Monitor (§2.4i). | M |

### Gates — every stage, before any deploy

```powershell
cd sentinel\backend
..\..\.venv\Scripts\python.exe -m pytest              # 377 passing as of 2026-08-04
..\..\.venv\Scripts\python.exe -m pytest tests\test_security_rbac.py -v
..\..\.venv\Scripts\python.exe -c "import app.main"
```

Plus: bump `CACHE` in `frontend/sw.js` for any CSS/JS change; deploy **only** via
`.\deploy\deploy.ps1` (a raw `gcloud run deploy` wipes `PLATFORM_SSO_SECRET` and breaks portal
sign-in). On the Atrium side: `tools/_validate_dash_js.py`, `_atrium_smoketest.py`,
`_workspace_localtest.py`, `_auth_smoketest.py`.

### Suggested milestones

| | Contains | Delivers |
|---|---|---|
| **M-A** | Stage 0 | Publishing works. The board stops lying. |
| **M-B** | Stages 1–2 | The workflow the prototype shows: Parked, review gate, Past work. |
| **M-C** | Stage 3 | Atrium is genuinely read-only; one system of record. |
| **M-D** | Stages 4–5 | Permissions coherent, board its own page, share-on-create. |

---

## 7. Open — deliberately not decided yet

- ~~**`campaign` vs `title`**~~ — **resolved 2026-08-03, ✅ BUILT 2026-08-04.** Not every service is a
  campaign (most of the eleven templates are standalone work), so: **the name field is the name**, and
  `campaign` is a genuinely optional grouping field only *offered* when the chosen service is
  campaign-shaped. Until this was built, ONE input (`#t-campaign`, labelled "Task name") wrote into
  **both** `title` and `campaign`, so the detail modal's Campaign row echoed the title back on every
  task — which is how it was spotted.
  **Built without the flag column:** campaign-shaped is derived from `content_type == "Campaign"`
  (`isCampaignType` in `taskboard.js`), so no `ServiceTemplate` migration was needed. Today exactly
  one seeded template qualifies (`google_meta_campaign`); the three standalone ad services
  (Video/Static/Carousel Ad) deliberately do **not**. The name input is `#t-name`, the campaign input
  is `#t-campaign` inside More options, and it is revealed by the service picker OR by typing
  "Campaign" into Content type (`syncCampaign` watches the field, not just the picker, and never
  hides a value somebody already typed — that would silently drop it on save). The save payload sends
  `campaign: null` when blank; `update_task` uses `exclude_unset`, so an explicit null really clears
  it. The detail modal renders the Campaign row **only when set**.
  🔴 **Existing rows were deliberately NOT backfilled** — every task created before 2026-08-04 still
  has `campaign == title` and will keep showing it until someone edits that task. Verified live:
  create-without-campaign → `None`, create-with → stored, PATCH null → cleared.
- ~~**Labels**~~ — **resolved 2026-08-03 (D14).** Derived from the department, like Atrium. Drop the
  Design/Copy/Ads/SEO/Dev vocabulary and the half-retired `labels_json` free list with it.
- **Attachments**: wire GCS (the pattern exists — Atrium's creatives are private objects + an authed
  proxy) or remove the affordance. Stage 0.4 removes; wiring is its own piece of work.
- **Self-approval** (new 2026-08-03, from Stage 2.3): `can_review` lets an AM or a team lead approve
  a task they submitted themselves. The alternative — refusing it — makes the done column
  unreachable for a team with no lead, because leads are a query and not a column (D9). Recorded on
  every approval (`reviewer_id` + history), so if the audit shows it being used as a rubber stamp the
  rule to add is "not the submitter, unless nobody else can review this task's team".

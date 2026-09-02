# Sentinel — how we work in it (SOP)

> The operating procedure for the live system (release 2026-09-02). Three parts: **one-time setup**
> (what has to be done once, today), the **daily routine per role**, and the **rules of the game**
> (what every word means). Written to be read aloud in a meeting and pinned afterwards.
> Sign in at **sentinel.agoradatadriven.com** (through the portal).

**The one rule for everyone:** if Sentinel doesn't know about it, it didn't happen. Work lives on a
card. Time is captured by pressing **Start Work**. Waiting is recorded by **Park** with a reason.

---

## Part 1 — One-time setup (do this today)

### Owner / Super Admin (~15 minutes)
1. **Change the bootstrap admin password.** The default account still carries the install password —
   sign in as it once (or open People → that account) and set a real password. This is a live
   security hole until it's done.
2. **Name an account manager for every client.** Clients → open each client → **Name an AM**.
   Until this is done, the AM landing shows *every* account and the COO's exceptions have no owner
   to point at. Eleven clients, one minute each.
3. **Set everyone's stage.** People → edit each person → Stage: `Shadow` (learning, always
   reviewed), `Contributor` (does real work, reviewer required on live client work),
   `Workstream Owner` (owns a recurring workstream), `Client Owner` (trusted end-to-end).
   Suggested starting point: interns = Shadow, employees = Contributor, team leads = Workstream
   Owner or Client Owner. This drives the "reviewer required" warnings — nothing is blocked by it.
4. **Decide the daily pass.** The morning-brief notification and auto-generated recurring tasks
   only run once `POST /api/cron/daily` is scheduled (Cloud Scheduler). It also writes attendance
   summaries and reminders estate-wide, so switch it on deliberately, in daylight, watching the
   first run — see AGENTS.md §2. Until then, the Operations page shows the same list on demand.

### Team leads + AMs (~30 minutes, together)
5. **Triage every overdue card.** Overdue = red date. For each: finish it, re-date it to a date you
   actually mean, or park it with the real reason. An August due date sitting red in September tells
   the client-health rule a lie — after triage, red means *red*.
6. **Date the undated.** Most open cards carry no due date, so they can never be late, never appear
   on the calendar, and never count toward a commitment. Every open card gets a due date or an
   explicit decision that it's undated backlog (then say so in the card).
7. **Name a lead on every unowned card.** Unassigned client cards (most are on one client) belong
   to nobody's Today page. Open each → Edit → Lead.
8. **Clear the review queue.** Cards "waiting for review" are specialists who can't finish.
   Approve or Request changes, today, and keep it under 24h from now on.
9. **Set up the recurring deliverables.** Weekly/monthly retainer work (weekly reports, blog +
   newsletter posting, refresher ads) should be a **Recurring service** so Sentinel mints the card
   each period instead of someone remembering. AM+: it's API-driven for now (`/api/tasks/recurring`)
   and generates on the daily pass or the manual "run" — ask for it and it takes minutes to add.

### Everyone (~2 minutes)
10. Sign in through the portal, check your name/photo, find **Today** (your landing page), and press
    **Start Work** on your first card. That's the whole onboarding.

---

## Part 2 — The daily routine

### Specialist (employee / intern / team lead doing delivery work)

**Start of day (about 2 minutes)**
1. **Clock in** — the button at the top of Today (or the kiosk).
2. **Read Work today, top to bottom.** It's already sorted: what you're working on first, then
   late (red), then priority, then deadline. Amber = due today.
3. **Check Training today.** If something's assigned, plan when you'll do it — the minutes shown.
4. **Check Waiting on others.** If something you parked has been answered, resume it first.
5. **Open the top card → read the description and checklist → press Start Work.**

**While working**
6. **One task at a time.** The green **Working on…** strip at the top of every page shows your
   running card and timer. Switching cards pauses the old one automatically; press **Pause** if you
   stop working without switching.
7. **The checklist is what "done" means.** Tick steps as you finish them. Paste the deliverable
   link on the card (Edit → Deliverable URL).
8. **New work that comes up gets a new card, immediately.** Task Board → **+ New Task**, one line:
   `Campaign | Action | Detail` (e.g. `Park & Porch | Refresh creatives | 3 statics`). Never bury
   new work inside an old card, never keep it in your head.
9. **Finished → Submit for review.** The card shows who reviews. You're done with it until they
   answer — start your next card.
10. **Stuck → Park, and pick why:** *Waiting on client / for access / for an asset / for AM
    decision / for reviewer / on another task / other*, plus one line saying who or what it's on.
    Parking stops your timer and moves the card to Parked (the client sees "Paused"). A parked card
    with a reason is normal work; a card silently idle is the only failure.
11. **Changes requested?** The card comes back in **Revision Needed** with the reviewer's note in
    the conversation. Press Start Work, fix it, resubmit.

**Training**
12. Open assigned training from Today — it opens the Mastery Engine and your minutes flow back into
    **Time today** automatically (nothing to log; an idle tab doesn't count).
13. A session that recorded time you didn't really spend can be trimmed from Time today → Details.

**End of day (about 2 minutes)**
14. Pause or submit whatever you're on (clocking out stops the timer anyway and flags long runs).
15. Every card of yours in an honest state: In Progress with time on it, Parked with a reason, or
    Submitted.
16. Look at the **Tomorrow** line under your list. Empty? Tell your lead now, not tomorrow.
17. **Clock out.**

*Test of a good day: your lead can tell what you did, what's waiting, and on whom — without asking.*

### Account Manager

**Each morning (about 5 minutes)**
1. Open **Overview**. The first line: how many accounts are red/amber and how many things need
   your action.
2. **Clear "Needs your action" first** — every item is a specialist who can't move until you do:
   - **Review waiting** → open → Approve, or Request changes with one clear sentence.
   - **Waiting for AM decision** (parked on you) → open → decide → it resumes and the specialist
     is notified.
   - **Client ask** (typed into Atrium by the client) → Accept (becomes a task) or Decline with a
     reason.
3. **Scan My accounts.** The Health column says *why* in words. Red rows first, always.
4. **Check Commitments (today & tomorrow)** — make sure the work behind each is actually moving.
5. **Glance at People on my accounts.** Anyone **Heavy** = a conversation with their team lead
   today.

**After any client meeting or message (about 1 minute per commitment)**
6. Open the client (Clients → row). Press **✦ Draft with AI** and type what was agreed in plain
   words — or **+ New task** to file it yourself.
7. Read each proposal: assignee (the person already holding this client's work in that
   department), due date, estimate, reviewer, and any warning (on leave, heavy, stage needs a
   reviewer). **Edit what's wrong, untick what's not needed, press Create.** Nothing exists until
   you press it. A dependent task is created parked as "waiting on another task."
8. Client-facing tasks share to the client's Atrium board automatically — title, note, dates and
   checklist only. Internal fields never cross.

**Through the day**
9. Talk to the specialist **on the card** (comments), so the reasoning stays with the work.
10. Don't route normal work through the department head. Escalate to them only when: the
    specialist is absent or heavy, the work needs a skill/certification nobody on the account has,
    changes were requested twice on the same work, or the deadline is impossible.

**Before a client meeting (about 3 minutes)**
11. Open the client page — it *is* the agenda: completed last 14 days, open work by specialist,
    blockers and who they're on, the next fortnight's commitments.

*Test of a good day: every client promise is a card with an owner and a date, and nothing has
waited on you for more than a day.*

### COO

**Each morning (about 5 minutes)**
1. Open **Overview → Operations**. The first line says how many things need attention.
   **Everything not on the list is running normally — leave it alone.**
2. Work the exception list top to bottom; each line has an owner and one button:
   - *Client is red* → open it, agree the fix with the AM.
   - *Person carrying more than the team* → rebalance with the lead.
   - *On leave with due work, no cover* → name cover.
   - *Client hasn't answered for days* → the AM chases; decide if the date moves.
   - *Review waiting >24h* → the reviewer clears it today.
   - *Changes requested twice on one person's work* → skill signal: lead tags the gap, assigns
     training.
   - *Not trained in 14 days* → the lead owns the conversation.
3. Don't open individual task cards unless an exception sends you there.

**The intervention rule:** intervene when the **same** exception appears two days running, or the
same person/client appears on two lines. Otherwise the AM ↔ specialist ↔ lead loop is working.

**Weekly (about 30 minutes, Monday)**
4. Task Board → **Monitor** + **Throughput**: on-time rate, days-to-finish, finished-per-week — by
   person and by client. Read the trend, not the number.
5. **Capacity**: planned hours vs the median; the time mix (client / training / internal /
   unallocated). Big unallocated = work happening off the cards.
6. **Quality**: changes-requested rate and first-pass approvals. A repeating miss becomes a
   checklist step in the service template.
7. **Learning**: stalled learners, assessments, certifications due.
8. **Fix the system, not the incident**: a recurring exception becomes a template step, a
   recurring service, a certification requirement, a stage change, or a staffing change.

---

## Part 3 — The rules of the game

| Word | Means |
|---|---|
| **Today** | Your landing page: work, waiting, time, training. The AM's is **My accounts**; the COO's is **Operations**. |
| **Start Work / Pause** | The timer on a card. This is how task time is captured — no timesheets, ever. One running card per person; a forgotten timer is capped at 4h and flagged for you to trim. |
| **Submit for review** | "I believe it's done." A card cannot enter **Completed** without an approval — the one enforced rule on the board. |
| **Changes requested** | The reviewer sent it back with a note; it's yours again, in Revision Needed. |
| **Park** | It's waiting. Always with a *kind* (on client / access / asset / AM decision / reviewer / another task) and one line saying on whom. The client sees "Paused", never the reason. Resume puts it back where it left. |
| **Client ask** | A request the client typed into their Atrium board. The AM accepts (→ task) or declines. |
| **Health** | **Red** = something overdue, blocked on **us** >2 days, or a review waiting >24h. **Amber** = due today, waiting on the **client**, or untouched 14 days. **Green** = none of that. The rule prints on the Clients page. |
| **Heavy / Steady / Light** | Open work vs the team's typical load (relative, not hours). Heavy means *rebalance*, not "work faster". |
| **Stage** | Shadow → Contributor → Workstream Owner → Client Owner. Readiness, not rank. Shadows and Contributors get "reviewer required" on live client work. |
| **Recurring service** | A card Sentinel mints on schedule (weekly optimization, monthly report). Nobody has to remember it. |
| **Estimate** | Optional minutes on a card (`~1h 30m`). Where it exists, capacity shows hours; where it doesn't, the relative band stays the truth. |
| **Calendar** | A projection of due dates, recurring trigger days and approved leave. Change the due date on the card and the calendar moves — there is nothing to keep in sync. |
| **Filed / Past work** | A finished card archived off the board. It still counts as shipped; **Completed is a working column, not a graveyard** — file what's delivered. |

### The 30-second version
- **Specialist:** clock in → Today → open the top card → **Start Work** → tick steps → **Submit**
  or **Park (with a reason)** → clock out with every card honest.
- **AM:** clear **Needs your action** → scan health → every client promise becomes a card
  (Draft with AI → Create) → talk on the card → escalate only exceptions.
- **COO:** read the exception list → act only on what's listed → weekly trends by person and
  client → fix the system, not the incident.

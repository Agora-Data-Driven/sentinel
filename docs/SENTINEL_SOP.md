# Sentinel — how we work in it (SOP)

> Plain-language operating procedures for the three roles. Written against the proposed Sentinel
> Today / Clients / Operations screens (see `sentinel_ops_mockup.html`). Meant to be read aloud in a
> meeting and pinned afterwards. One page per role.

**The one rule for everyone:** if Sentinel doesn't know about it, it didn't happen. Work lives on a
card. Time is captured by pressing Start Work. Waiting is recorded by parking with a reason.

---

## 1. Specialist — your day

### Start of day (about 2 minutes)
1. **Clock in** (kiosk, or the button at the top of Today).
2. **Open Sentinel → Today.** The first line tells you how many tasks you have, how many are due today, and how many are late.
3. **Read the Work today list from the top.** It is already sorted: urgent first, then by deadline. Red = late, amber = due today.
4. **Glance at Training today.** If something is assigned, plan when you'll do it (it shows the minutes).
5. **Glance at Waiting on others.** If something you parked has been unblocked, that's your first job.
6. **Open the top card and press Start Work.**

### While working
7. **One task at a time.** The green strip at the top shows what you're working on and for how long. When you switch tasks, press **Pause** first.
8. **Read the card before you start:** description + the checklist. The checklist is what "done" means.
9. **Tick checklist steps as you finish them.** Paste the deliverable link on the card.
10. **Something new comes up?** Add a card immediately (+ New Task, one line: *Client | Action | Detail*). Never bury new work inside an old card.
11. **Finished → press Submit for review.** The card shows who reviews it. You're done with it until they respond.
12. **Stuck → press Park and pick why:** waiting on client / access / asset / AM decision / reviewer / another task. Add one line saying who it's on. Then move to your next card.
    - A parked card with a reason is **not** a failure. A card sitting idle with no reason is.
13. **Changes requested?** The card comes back to you in Revision Needed with the reviewer's note. Fix it, resubmit.

### Training
14. Assigned training opens in the Mastery Engine from Today. Your minutes are counted automatically — nothing to log.
15. Time counts only while the engine tab is visible and you're actually doing something. If a session looks wrong ("I only had it open"), trim it in Time today → Details.

### End of day (about 2 minutes)
16. **Pause or submit whatever you're working on.** (Clocking out stops the timer anyway, but it flags it.)
17. **Check every card of yours has an honest state:** In Progress with time on it, Parked with a reason, or Submitted.
18. **Look at the "Tomorrow" line under your list.** If it's empty, tell your team lead now — not tomorrow morning.
19. **Clock out.**

**Test of a good day:** your lead can tell what you did, what's waiting, and on whom — without asking you.

---

## 2. Account Manager — your day

### Each morning (about 5 minutes)
1. **Open Sentinel → Overview.** The first line tells you how many accounts are red/amber and how many things need your action.
2. **Clear "Needs your action" first.** Every item there is a specialist who can't move until you do:
   - **Review** → open the card → Approve, or Request changes with one clear sentence.
   - **AM decision** (a parked card waiting on you) → open it → decide → the specialist is notified and the card resumes.
   - **Client ask** (from Atrium) → Accept (it becomes a task) or Decline with a reason.
3. **Scan "My accounts".** Read the Health column — it says *why* in words (e.g. "2 overdue, review waiting 30h"). Red first.
4. **Check "Commitments · today and tomorrow."** Meetings, report dates, launches. Make sure the work behind each one is actually in progress.
5. **Check "People on my accounts".** Anyone marked **Heavy** is a conversation with their team lead today, not Friday.

### After a client meeting or message (about 1 minute per commitment)
6. **Open the client** (Clients → row).
7. **Press "Draft with AI"** and type or paste what was agreed, in plain words. Or press **+ New task** to file it yourself.
8. **Read each proposed task:** assignee (the person already doing that client's work in that department), due, estimate, reviewer, and any warning (on leave, heavy, needs a certification).
9. **Change what's wrong, remove what's not needed, then press Create.** Nothing exists until you press it.
10. Client-facing tasks are shared to the client's Atrium board automatically — they see only the title, note, dates and checklist. Never internal fields.

### Through the day
11. **Talk to the specialist directly** — comment on the card, not in DMs, so the reasoning stays with the work.
12. **Do not route normal work through the department head.** Go to them only when:
    - the specialist is absent or heavy,
    - the task needs a skill/certification nobody on the account has,
    - changes have been requested twice on the same work,
    - the deadline is impossible,
    - the client situation is high-risk.

### Before a client meeting (about 3 minutes)
13. **Open the client page.** It is the agenda: completed last 14 days, open work by specialist, what's blocked and on whom, upcoming commitments.
14. **Update "This week"** (the three priorities) if the meeting changes them.

**Test of a good day:** every client promise is a card with an owner and a date, and nothing has been waiting on you for more than a day.

---

## 3. COO — your day and your week

### Each morning (about 5 minutes)
1. **Open Sentinel → Operations.** The first line says how many things need attention. Everything not on the list is running normally.
2. **Read the exception list top to bottom.** Each line is one problem, one owner, one button:
   - **Client is red** → why, in words → *Open client* → agree the fix with the AM.
   - **Person overloaded** → hours vs team median → *Rebalance* with the team lead.
   - **Absence with no cover** → who holds what → *Name cover*.
   - **Waiting on a client for days** → the AM chases; decide whether the commitment date moves.
   - **Repeated changes-requested** → a training/skill issue, not a task issue → the team lead owns it.
   - **Learner stalled** → the team lead owns it.
3. **Glance at the stats strip** (clients / overdue / blocked / reviews / training). It should match the list above; if it doesn't, something isn't surfacing.
4. **Do not open individual task cards** unless an exception sends you there.

### The intervention rule
5. **If it is not on the exception list, don't touch it.** The AM ↔ specialist ↔ team lead loop is working.
6. Intervene when the **same** exception appears two days running, or the same person/client appears in two lines.

### Weekly review (about 30 minutes, Monday)
7. **Delivery** — Task Board → Monitor + Throughput: on-time rate, days to finish, finished per week — by person and by client. Look at trend, not the number.
8. **Capacity** — planned hours vs the median; time mix per person (client / training / internal / unallocated). Big unallocated = work not on cards.
9. **Quality** — changes-requested rate and first-pass approval rate per person and per task type. A pattern becomes a checklist step in the template.
10. **Learning** — stalled learners, certifications due, assessments waiting. Growth table on the Overview.
11. **Account managers** — each AM's book: red clients, overdue commitments, reviews over 24h, unanswered client asks.
12. **Fix the system, not the incident.** A recurring exception becomes one of: a template checklist step, a recurring task, a certification requirement, a stage change, or a staffing change.

**Test of a good week:** no client went red without the AM already acting; nobody was heavy two weeks running; the CEO didn't have to ask anyone "what's happening with X?"

---

## 4. Words we use (so everyone means the same thing)

| Word | Means |
|---|---|
| **Today** | Your personal landing page: work, waiting, training, time. |
| **Start Work / Pause** | Starts/stops the timer on a card. This is how task time is captured — no timesheets. |
| **Submit for review** | You believe it's done. The reviewer decides. Completed needs an approval. |
| **Changes requested** | Reviewer sent it back with a note. It's on you again. |
| **Park** | It's waiting on someone/something. Always with a reason and who it's on. The client sees "Paused". |
| **Client ask** | A request the client typed into Atrium. AM accepts or declines. |
| **Health (Red / Amber / Green)** | Red = something is overdue, blocked on us, or a review has waited over 24h. Amber = due today or waiting on the client. Green = on track. |
| **Heavy / Steady / Light** | Planned hours vs the team's typical load. Heavy means rebalance, not "work faster". |
| **Stage** | Shadow → Contributor → Workstream Owner → Client Owner. Contributors always have a reviewer on live client work. |
| **Recurring** | A task Sentinel creates on schedule (weekly optimization, monthly report). Nobody has to remember it. |

---

## 5. The 30-second version

- **Specialist:** clock in → Today → open the top card → Start Work → tick steps → Submit or Park (with a reason) → clock out with every card in an honest state.
- **AM:** clear Needs your action → scan account health → turn every client promise into a card (Draft with AI → Create) → talk to specialists on the card → escalate only exceptions.
- **COO:** read the exception list → act only on what's listed → weekly: trends by person and client → fix the system, not the incident.

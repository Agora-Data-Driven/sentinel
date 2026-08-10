"""ONE PERSON, WRITTEN DOWN IN FULL — the daily context report.

This composes everything Sentinel and the Mastery Engine know about a single worker into one
Markdown document, so it can be handed to an outside assistant (Claude, ChatGPT) as a project file.

    build(db, user)  -> {"markdown": str, "gaps": [...], "as_of": "YYYY-MM-DD", ...}

🔴 **THE STANDARD THIS DOCUMENT IS HELD TO**: an assistant given only this file should answer about
this person as well as the coach that runs INSIDE the Mastery Engine. That coach has advantages
this document must make up for in text, and each one dictates a section here:

| The in-app coach has | So this document carries |
|---|---|
| `docs/HOW-IT-WORKS.md` injected into its prompt | §1 — what the two systems ARE |
| the scoring formulas as documented behaviour | §2 — coverage / mastery / priority, stated exactly |
| direct Firestore reads of the whole catalogue | §5 — every topic, with this learner's stats on it |
| `holistic-profile` over HMAC every turn | §8–§13 — goals, journal, career, reading, body, work |
| `growth-detail` retrieval for journal bodies | §9 — the bodies, inline, whole |
| `mentor-search` over the transcript library | §14 — the roster, so the reader knows what exists |

A programme-level average is NOT this standard. "Data Science 96%" supports no advice; "you have
never attempted Bayesian inference, and your accuracy on hypothesis testing is 61% across 18
attempts" does. That is why §5 exists and why it is long.

WHAT THIS IS NOT: a team report. It is deliberately scoped to ONE person's own data — see
`_work_section`. `work_digest` is role-scoped and would hand a manager the whole estate, and this
document is destined for a personal Google Doc wired into third-party AI vendors.

🔴 THREE INVARIANTS, INHERITED FROM THE COACH AND LOAD-BEARING FOR THE SAME REASONS:

  1. **A silent gap becomes a confident denial.** The growth-journal index ships COMPLETE and
     uncapped (a 600-char cap once made the coach deny content the worker could see on their own
     screen). Anything not loaded is NAMED in §15 rather than omitted.
  2. **"The source didn't answer" is not "the value is zero."** An engine outage renders as
     *unknown*, never as 0% — a fabricated zero reads as "you have done nothing".
  3. **Never state what was answered on a missed question.** A quizLog row carries the question
     text and a right/wrong bit and nothing else, so the chosen option cannot be reported.
"""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..constants import (
    DIM_PHILOSOPHICAL,
    DIM_PHYSICAL,
    DIM_PROFESSIONAL,
    DIM_SPIRITUAL,
    GYM_COMPLETED,
    ROLE_LABELS,
)
from ..models import GymLog, User
from ..utils.time import now_ph, today_ph
from . import development as dev_svc
from . import engine_bridge
from . import gym as gym_svc
from . import work_digest as work_svc
# 🔴 Reached into on purpose. These ARE the estate's definitions of overall coverage,
# points-per-week, and which engine programs back a dimension — the admin Team-progress panel ranks
# on exactly these. Re-deriving them would put a second formula in the codebase, and the two would
# disagree about the same person on the same day.
from .team_growth import _programs_for_dim, _velocity, _weighted_pct, fetch_engine

WINDOW_DAYS = 30

# Verbatim missed questions. Beyond this they stop being material and become noise; the counts
# still cover everything and the overflow is declared.
MAX_MISSED_QUESTIONS = 80

# How many topics to name in each "where to focus" list.
FOCUS_N = 25


def _pct(value: float | None, digits: int = 1) -> str:
    """A percentage, or the honest blank. 🔴 Never 0 for a missing value — invariant 2."""
    return f"{value:.{digits}f}%" if value is not None else "not available"


def _line(label: str, value) -> str:
    return f"- **{label}:** {value if value not in (None, '', []) else '—'}"


def _heading(text: str, level: int = 2) -> str:
    return f"\n{'#' * level} {text}\n"


# --- the explanatory front matter --------------------------------------------


def _how_to_use() -> str:
    return (
        _heading("0. How to use this document")
        + """This is a complete, regenerated-daily dossier on one person, assembled from the two
systems that hold their record. It exists so an assistant with no access to those systems can
reason about them as well as the coach built into the app itself.

**Read it as ground truth about this person, not as a general knowledge base.** Every number is
theirs and is dated.

**The rules that keep it honest — please respect them:**

1. **"Not available" means a source could not be reached. It never means zero.** If a section says
   a figure is unavailable, say so; do not substitute an assumption, and do not conclude the
   underlying thing is absent or unstarted.
2. **Coverage is not knowledge.** §2 defines the difference precisely. A high coverage number with
   few attempts behind it is weak evidence, and §5 gives you the attempt counts to check.
3. **Where a list is marked complete, absence is meaningful.** The growth journal (§9) is the
   whole journal. If something is not there, they have not written it down. Where a list is
   marked truncated, absence means nothing at all.
4. **Missed questions (§7) record only that an answer was wrong** — never which option was chosen.
   Do not infer the misconception; ask.
5. **This document is regenerated in full each day.** It is current state, not history. Nothing in
   it needs preserving between versions.
"""
    )


def _systems() -> str:
    """§1 — what the two systems are.

    The in-app coach gets `docs/HOW-IT-WORKS.md` injected into its prompt, so it can explain the
    app it lives in. An outside reader has nothing equivalent, and without it every number below is
    uninterpretable — "priority 78" is meaningless unless you know priority is a 0–100 study-next
    score rather than an importance rating.
    """
    return (
        _heading("1. The systems behind this report")
        + _heading("1a. The Mastery Engine", 3)
        + """A spaced-repetition **mastery-learning** app — the source of every learning number here.
The learner practises AI-generated questions; the app tracks how well each topic is known and
steers them toward what they are weakest at and have not seen recently.

- **Content model:** `Program → Track → Course → Lesson → Topic`. A **topic** (shown in the app as
  a "sub-lesson") is one testable idea, and it is the unit everything keys on — every attempt,
  every score, every row in §5 is per-topic.
- **Programs** are separate curricula sharing one question bank. They split into two kinds:
  **career** programs (Data Science, AI Engineering, Digital Marketing), which require enrolment,
  and **growth** programs (Philosophy, Spiritual), which are open to everyone.
- **The question bank is shared across users; the stats and attempt log are personal.**
- Questions are generated by AI and published straight into the bank, so learners can flag bad
  ones for an admin to fix — a flagged question is a data-quality report, not a wrong answer.

**Deliberate design limits worth knowing before you draw conclusions:**

- The engine records **that** an answer was wrong, never **which** option was picked.
- A topic's identity is its internal id, not its name. Topics get renamed and re-filed, and old
  attempts keep the names they had at the time — which is why some attempts cannot be matched to a
  current topic (§7 reports how many).

"""
        + _heading("1b. Sentinel", 3)
        + """Agora's internal operations system, and the source of everything non-learning here. It
is the system of record for the person's **whole** development, not just their studying:

- **Four growth dimensions** — Professional, Philosophical, Spiritual, Physical — each carrying its
  own goals, notes and pace deadline. This is the organising idea behind the whole profile.
- **A growth journal**: their own titled entries — obstacles, reflections, notes — filed by
  dimension. One idea per entry, by design.
- **A reading canon** curated by the company, with their status and personal reflection on each.
- **Career**: headline, résumé, achievements, and skills tagged by how each was gained.
- **Physical**: body metrics, personal records, target lifts/runs being chased, and a weekly gym
  split with recent training consistency.
- **Work**: the task board, scoped to what this person is permitted to see.
"""
    )


def _methodology() -> str:
    """§2 — the formulas, stated exactly.

    🔴 The single most misreadable number in this document is coverage. It is what the rings and
    the rollups report, it looks like a mastery percentage, and it is not one. The engine's own
    docs record a real shelf at 66% coverage against 32% depth. Anyone reading "96%" without this
    section will plan revision around a number that means "has touched almost everything once".
    """
    return (
        _heading("2. How to read the numbers")
        + """Three different scores appear below and they answer three different questions. Mixing
them up is the easiest way to draw a wrong conclusion from this document.

### Coverage — *how much of this have I touched?*

A topic's plain accuracy, averaged over **every** topic on the shelf with untouched ones counted
as zero. This is what the app shows by default and what every ring and rollup reports.

🔴 **Coverage is not knowledge.** It rises when a topic is touched at all, so a topic answered
correctly once reads as 100%. On a real shelf the engine measured **66% coverage against 32% true
mastery**, because most practised topics rested on two questions or fewer. Treat a high coverage
figure as *"has been over this ground"*, and check the attempt counts in §5 before treating it as
*"knows this"*.

### True Mastery — *how well do I actually know it?*

Weighs how much evidence backs each topic and how fresh that evidence is:

```
mastery   = retention × ( 0.7 × (correct + 1.6)/(attempts + 4)  +  0.3 × attempts/(attempts + 6) )
retention = 1 − 0.35 × min(daysUntouched / 120, 1)      # eases to a 0.65 floor, never to 0
```

- **One correct answer is worth about 40%, not 100%** — the `+1.6/+4` is a prior that assumes
  uncertainty until several questions back it up.
- **More questions always pay**, even at imperfect accuracy — the depth term keeps rewarding
  evidence rather than capping out.
- **It never reaches 100.** Both terms are asymptotic.
- Untouched topics score **0**, and a wrong answer genuinely dents the number.

### Priority — *what should I study next?*

0–100, higher means work on this next. **Not** an importance rating:

```
priority = 100 × ( 0.5·(1 − accuracy) + 0.3·min(daysSince/30, 1) + 0.2·(1 − min(attempts/10, 1)) )
```

Weak accuracy dominates (0.5), then staleness (0.3, saturating at 30 days), then low confidence
from few attempts (0.2, full confidence at 10). A never-attempted topic scores high on purpose so
it surfaces rather than hiding.

*Honest note carried from the engine's own documentation: this is a faithful reconstruction of a
bespoke heuristic from the original spreadsheet, not a textbook algorithm like SM-2.*

### Velocity, streak, active days

**Velocity** is coverage points gained per week, measured by replaying the attempt window and
recomputing where the figure stood when the window opened — a real rate, not a running total.
**Active days** is days with at least one attempt in the window; **streak** is consecutive days up
to today.
"""
    )


# --- sections ----------------------------------------------------------------


def _identity_section(user: User, profile: dict) -> str:
    dev_profile = (profile.get("career") or {}).get("profile") or {}
    out = [_heading("3. Who this document is about")]
    out.append(_line("Name", user.name or user.email))
    out.append(_line("Email", user.email))
    out.append(_line("Role in Sentinel", ROLE_LABELS.get(user.role, user.role)))
    out.append(_line("Headline", dev_profile.get("headline")))
    return "\n".join(out) + "\n"


def _mastery_section(engine: dict | None, engine_error: str) -> str:
    out = [_heading("4. Curriculum coverage by dimension")]
    if not engine or not engine.get("found"):
        reason = engine_error or (engine or {}).get("error") or "the Mastery Engine did not answer"
        out.append(f"_Not available — {reason}._ This is a **gap, not a zero**.\n")
        return "\n".join(out) + "\n"

    programs = list(engine.get("programs") or [])
    velocity = _velocity(programs, WINDOW_DAYS)
    out.append(_line("Overall coverage (topic-weighted)", _pct(_weighted_pct(programs))))
    out.append(_line(f"Velocity (coverage points/week over {WINDOW_DAYS}d)",
                     f"{velocity}" if velocity is not None
                     else "not measurable — the engine reported no baseline for this window"))
    out.append("")
    out.append("| Dimension | Coverage | Topics practised | Programs |")
    out.append("|---|---|---|---|")
    for dim, label in ((DIM_PROFESSIONAL, "Professional"), (DIM_PHILOSOPHICAL, "Philosophical"),
                       (DIM_SPIRITUAL, "Spiritual"), (DIM_PHYSICAL, "Physical")):
        subset = _programs_for_dim(programs, dim)
        names = ", ".join(str(p.get("name") or p.get("id")) for p in subset) or "—"
        practised = sum(p.get("topicsPracticed") or 0 for p in subset)
        total = sum(p.get("topicsTotal") or 0 for p in subset)
        out.append(f"| {label} | {_pct(_weighted_pct(subset))} | "
                   f"{f'{practised}/{total}' if total else '—'} | {names} |")
    out.append("")
    out.append("| Program | Kind | Coverage | Topics practised | Courses |")
    out.append("|---|---|---|---|---|")
    for p in sorted(programs, key=lambda x: -(x.get("topicsTotal") or 0)):
        if not (p.get("topicsTotal") or 0):
            continue
        out.append(f"| {p.get('name') or p.get('id')} | {p.get('category') or 'career'} | "
                   f"{p.get('pct')}% | {p.get('topicsPracticed')}/{p.get('topicsTotal')} | "
                   f"{p.get('courseCount') or '—'} |")
    out.append("\n> Read these as **coverage** (§2), not as knowledge. The Physical row is the "
               "engine's philosophy/physical curriculum; actual training is §13.")
    return "\n".join(out) + "\n"


def _curriculum_section(detail: dict | None, detail_error: str) -> str:
    """§5 — every topic, with this learner's own numbers on it.

    🔴 THIS IS THE SECTION THAT MAKES THE DOCUMENT MATCH THE IN-APP COACH. That coach reads the
    catalogue straight out of Firestore, so it can say "you have never attempted X" and "your
    accuracy on Y is 61% over 18 attempts". Every other section here could be written from the
    programme rollups; none of them supports advice at that grain. It is deliberately long.
    """
    out = [_heading("5. The curriculum in full, with per-topic progress")]
    if not detail:
        out.append(f"_Not available — {detail_error or 'the Mastery Engine did not answer'}._ "
                   "**This does not mean the curriculum is empty.**\n")
        return "\n".join(out) + "\n"

    topics = list(detail.get("topics") or [])
    if not topics:
        out.append("_The engine returned no topics._\n")
        return "\n".join(out) + "\n"

    attempted = [t for t in topics if (t.get("attempts") or 0) > 0]
    out.append(_line("Topics in the curriculum", detail.get("topicsTotal") or len(topics)))
    out.append(_line("Topics ever attempted", f"{len(attempted)} of {len(topics)}"))
    if detail.get("truncated"):
        out.append(_line("Note", "the engine capped this list; some topics are not shown below"))
    out.append("\nEvery topic they have access to is listed below, grouped by program and course. "
               "`—` in the accuracy column means **never attempted** (not 0%).\n")

    # program -> course -> rows
    grouped: dict[str, dict[str, list[dict]]] = {}
    for t in topics:
        grouped.setdefault(t.get("program") or "(unfiled)", {}) \
               .setdefault(t.get("course") or "(no course)", []).append(t)

    for program in sorted(grouped):
        courses = grouped[program]
        prog_rows = [r for rows in courses.values() for r in rows]
        prog_att = [r for r in prog_rows if (r.get("attempts") or 0) > 0]
        out.append(_heading(f"{program} — {len(prog_rows)} topics, {len(prog_att)} attempted", 3))
        for course in sorted(courses):
            rows = sorted(courses[course], key=lambda r: (r.get("lesson") or "", r.get("topic") or ""))
            done = sum(1 for r in rows if (r.get("attempts") or 0) > 0)
            out.append(f"\n**{course}** — {done}/{len(rows)} topics attempted\n")
            out.append("| Lesson | Topic | Qs | Attempts | Accuracy | Mastery | Priority | Last |")
            out.append("|---|---|---|---|---|---|---|---|")
            for r in rows:
                acc = f"{r['accuracy']}%" if r.get("accuracy") is not None else "—"
                last = (r.get("lastAttempted") or "")[:10] or "never"
                out.append(
                    f"| {r.get('lesson') or '—'} | {r.get('topic') or '—'} | "
                    f"{r.get('questions') or 0} | {r.get('attempts') or 0} | {acc} | "
                    f"{r.get('mastery')} | {r.get('priority')} | {last} |"
                )
    return "\n".join(out) + "\n"


def _focus_section(detail: dict | None) -> str:
    """§6 — the actionable read of §5, so an assistant need not re-derive it."""
    if not detail or not (detail.get("topics") or []):
        return ""
    topics = list(detail["topics"])
    out = [_heading("6. Where to focus")]
    out.append("Derived from §5 using the formulas in §2 — offered so the ranking is explicit "
               "rather than something you must reconstruct.\n")

    ranked = sorted(topics, key=lambda t: -(t.get("priority") or 0))[:FOCUS_N]
    out.append(_heading(f"Highest priority — the engine's own \"study next\" order", 3))
    out.append("| Topic | Course | Priority | Attempts | Accuracy |")
    out.append("|---|---|---|---|---|")
    for t in ranked:
        acc = f"{t['accuracy']}%" if t.get("accuracy") is not None else "never tried"
        out.append(f"| {t.get('topic')} | {t.get('course') or '—'} | {t.get('priority')} | "
                   f"{t.get('attempts') or 0} | {acc} |")

    weak = sorted((t for t in topics if (t.get("attempts") or 0) >= 3
                   and t.get("accuracy") is not None),
                  key=lambda t: (t.get("accuracy"), -(t.get("attempts") or 0)))[:FOCUS_N]
    if weak:
        out.append(_heading("Genuinely weak — attempted at least 3 times, lowest accuracy", 3))
        out.append("These are the honest weak spots: enough evidence to trust the number.\n")
        out.append("| Topic | Course | Accuracy | Attempts | Mastery |")
        out.append("|---|---|---|---|---|")
        for t in weak:
            out.append(f"| {t.get('topic')} | {t.get('course') or '—'} | {t['accuracy']}% | "
                       f"{t.get('attempts')} | {t.get('mastery')} |")

    thin = sorted((t for t in topics if 0 < (t.get("attempts") or 0) <= 2),
                  key=lambda t: -(t.get("mastery") or 0))[:FOCUS_N]
    if thin:
        out.append(_heading("Thin evidence — looks known, rests on ≤2 questions", 3))
        out.append("🔴 These inflate coverage the most. A topic answered correctly once reads as "
                   "100% coverage while its true mastery sits near 40%.\n")
        out.append("| Topic | Course | Attempts | Accuracy | Mastery |")
        out.append("|---|---|---|---|---|")
        for t in thin:
            acc = f"{t['accuracy']}%" if t.get("accuracy") is not None else "—"
            out.append(f"| {t.get('topic')} | {t.get('course') or '—'} | {t.get('attempts')} | "
                       f"{acc} | {t.get('mastery')} |")

    never = [t for t in topics if not (t.get("attempts") or 0)]
    if never:
        out.append(_heading(f"Never attempted — {len(never)} topics", 3))
        by_course: dict[str, list[str]] = {}
        for t in never:
            by_course.setdefault(t.get("course") or "(no course)", []).append(t.get("topic") or "?")
        for course in sorted(by_course):
            names = by_course[course]
            out.append(f"- **{course}** ({len(names)}): {', '.join(sorted(names))}")
    return "\n".join(out) + "\n"


def _learning_section(engine: dict | None, activity: dict | None, activity_error: str) -> str:
    out = [_heading(f"7. Recent activity (last {WINDOW_DAYS} days)")]
    window = ((engine or {}).get("activity") or {}) if (engine or {}).get("found") else {}
    attempts = window.get("attempts") or 0
    if window:
        correct = window.get("correct") or 0
        acc = round(correct / attempts * 100, 1) if attempts else None
        out.append(_line("Questions attempted", attempts))
        out.append(_line("Correct", f"{correct} ({_pct(acc)})"))
        out.append(_line("Active days", window.get("activeDays")))
        out.append(_line("Current streak", f"{window.get('streak')} days"))
        out.append(_line("Last active", window.get("lastActive") or "—"))
        # 🔴 Scale this to the real share. Calling a 40% shortfall "slight" invites trust in a
        # number the engine itself does not stand behind.
        unmatched = window.get("unmatched") or 0
        if unmatched:
            share = round(unmatched / attempts * 100) if attempts else 0
            severity = "**materially understated**" if share >= 20 else "understated slightly"
            out.append(_line(
                "Attempts not attributable to a current topic",
                f"{unmatched} of {attempts} ({share}%) — the topic was renamed or re-filed after "
                f"the attempt was logged. The engine excludes these from per-topic progress, so "
                f"coverage and velocity in §4 are {severity}. The attempts themselves happened "
                f"and are counted above."))
    else:
        out.append("_Not available — the Mastery Engine did not report an attempt window._\n")

    out.append(_heading("7a. Questions answered incorrectly", 3))
    if activity is None:
        out.append(f"_Not available — {activity_error or 'the Mastery Engine did not answer'}._ "
                   "**This does not mean nothing was missed.**\n")
        return "\n".join(out) + "\n"

    rows = list(activity.get("rows") or [])
    out.append(_line("Attempts in this window", activity.get("attempts")))
    out.append(_line("Missed", activity.get("wrong")))
    if not rows:
        # "No misses" and "the misses weren't returned" are different facts.
        if activity.get("wrong"):
            out.append(f"\n_The engine reported {activity['wrong']} missed question(s) but returned "
                       f"no detail, so they cannot be listed. Treat this as **missing detail, not a "
                       f"clean sheet**._\n")
        else:
            out.append("\nNo missed questions recorded in this window.\n")
        return "\n".join(out) + "\n"

    shown = rows[:MAX_MISSED_QUESTIONS]
    out.append("\n🔴 The attempt log records the question and that it was answered wrong — **not "
               "which option was chosen, and not the correct answer.** Read each line as \"this was "
               "missed\" and nothing more; ask before diagnosing the misconception.\n")
    for r in shown:
        where = " › ".join(x for x in (r.get("course"), r.get("lesson"), r.get("topic")) if x)
        flag = " _(they flagged this for review)_" if r.get("reviewFlag") else ""
        out.append(f"- **{where or 'Unattributed'}** — {r.get('question') or '(no question text)'}"
                   f" _({(r.get('date') or '')[:10]})_{flag}")
    dropped = len(rows) - len(shown)
    if dropped or activity.get("truncated"):
        out.append(f"\n_{dropped} further missed question(s) not printed. The counts above cover "
                   f"all of them._")
    return "\n".join(out) + "\n"


def _goals_section(profile: dict) -> str:
    out = [_heading("8. Goals, by dimension")]
    goals = ((profile.get("career") or {}).get("goals")) or []
    if not goals:
        out.append("_No goals recorded._\n")
        return "\n".join(out) + "\n"
    by_dim: dict[str, list[dict]] = {}
    for g in goals:
        by_dim.setdefault(g.get("dimension") or DIM_PROFESSIONAL, []).append(g)
    for dim in (DIM_PROFESSIONAL, DIM_PHILOSOPHICAL, DIM_SPIRITUAL, DIM_PHYSICAL):
        rows = by_dim.get(dim) or []
        if not rows:
            continue
        out.append(_heading(dim.capitalize(), 3))
        for g in rows:
            target = f", target {g['target_date']}" if g.get("target_date") else ""
            out.append(f"- **{g.get('title')}** — {g.get('status')}, {g.get('progress_pct', 0)}%{target}")
            if g.get("description"):
                out.append(f"  - {g['description']}")
    return "\n".join(out) + "\n"


def _growth_section(profile: dict, areas: dict) -> str:
    """§9 — the growth journal, COMPLETE, with bodies.

    🔴 Never capped, never excerpted. The in-app coach ships titles every turn and fetches bodies on
    demand because it pays for context repeatedly; a document is read once, so it carries the whole
    thing. Archived entries stay listed and marked — silence is indistinguishable from "never
    existed", and that is exactly the failure this design replaced.
    """
    out = [_heading("9. Growth journal")]
    items = profile.get("growth") or []
    out.append(f"_{len(items)} entries. **This list is complete**, archived ones included — so if "
               f"something is not here, they have not written it down._\n")
    for dim in (DIM_SPIRITUAL, DIM_PHILOSOPHICAL, DIM_PROFESSIONAL, DIM_PHYSICAL):
        rows = [g for g in items if (g.get("dimension") or DIM_SPIRITUAL) == dim]
        if not rows:
            continue
        out.append(_heading(dim.capitalize(), 3))
        for g in rows:
            archived = " **[archived]**" if g.get("status") == "archived" else ""
            out.append(f"\n**{g.get('title')}**{archived} _({g.get('kind')}, {g.get('status')}, "
                       f"{(g.get('created_at') or '')[:10]})_\n")
            body = (g.get("detail") or "").strip()
            # Whole or absent — a truncated note reads exactly like a complete one.
            out.append(body if body else "_(no body text)_")

    if areas:
        out.append(_heading("9a. Per-dimension notes and pace deadlines", 3))
        for dim, a in areas.items():
            deadline, other = a.get("deadline"), (a.get("other_info") or "").strip()
            if not deadline and not other:
                continue
            out.append(f"\n**{dim.capitalize()}**"
                       + (f" — pace deadline {deadline}" if deadline else ""))
            if other:
                out.append(f"\n{other}")
    return "\n".join(out) + "\n"


def _career_section(profile: dict) -> str:
    career = profile.get("career") or {}
    dev_profile = career.get("profile") or {}
    out = [_heading("10. Career")]
    achievements = career.get("achievements") or []
    if achievements:
        out.append(_heading("Achievements", 3))
        for a in achievements:
            when = f" _({a['achieved_on']})_" if a.get("achieved_on") else ""
            out.append(f"- **{a.get('title')}**{when}")
            if a.get("description"):
                out.append(f"  - {a['description']}")
    resume = (dev_profile.get("resume_text") or "").strip()
    if resume:
        out.append(_heading("Résumé (full text)", 3))
        out.append(resume)

    skills = profile.get("skills") or []
    out.append(_heading("11. Skills", 2))
    if skills:
        out.append("| Skill | Level | How it was gained |")
        out.append("|---|---|---|")
        for s in skills:
            out.append(f"| {s.get('name')} | {s.get('level')} | {s.get('source')} |")
        out.append("\n> 🔴 **Their skills are not limited to Mastery Engine topics.** `project` "
                   "means proven on real work, `mastery_engine` means drilled in the quiz app. "
                   "Do not assume a skill is absent because §5 has no topic for it.")
    else:
        out.append("_No skills recorded._")
    return "\n".join(out) + "\n"


def _reading_section(profile: dict) -> str:
    out = [_heading("12. Reading")]
    items = profile.get("reading") or []
    if not items:
        out.append("_No canon items._\n")
        return "\n".join(out) + "\n"
    for status, label in (("reading", "Currently reading"), ("done", "Finished"),
                          ("not_started", "Not started")):
        rows = [r for r in items if (r.get("progress") or {}).get("status") == status]
        if not rows:
            continue
        out.append(_heading(label, 3))
        for r in rows:
            author = f" — {r['author']}" if r.get("author") else ""
            out.append(f"- **{r.get('title')}**{author}")
            reflection = ((r.get("progress") or {}).get("reflection") or "").strip()
            if reflection:
                out.append(f"  - _Their own reflection:_ {reflection}")
    return "\n".join(out) + "\n"


def _physical_section(db: Session, user: User, profile: dict) -> str:
    phys = profile.get("physical") or {}
    latest = phys.get("latest") or {}
    out = [_heading("13. Physical and training")]
    out.append(_line("Weight", f"{latest.get('weight_kg')} kg" if latest.get("weight_kg") else None))
    out.append(_line("Body fat", f"{latest.get('body_fat_pct')}%" if latest.get("body_fat_pct") else None))
    out.append(_line("Measured", latest.get("date")))

    targets = phys.get("targets") or []
    if targets:
        out.append(_heading("Targets being chased", 3))
        for t in targets:
            unit = f" {t['unit']}" if t.get("unit") else ""
            lower = ", lower is better" if t.get("direction") == "lower" else ""
            out.append(f"- **{t.get('name')}** ({t.get('kind')}): {t.get('current_value')}"
                       f"/{t.get('target_value')}{unit} = {t.get('progress_pct')}% "
                       f"({t.get('status')}{lower})")

    prs = phys.get("prs") or []
    if prs:
        out.append(_heading("Personal records", 3))
        for p in prs:
            detail = f" — {p['detail']}" if p.get("detail") else ""
            out.append(f"- **{p.get('exercise_name')}**: {p.get('display') or ''}{detail}")

    # The weekly split, so a reader can reason about training load the way the in-app coach does.
    try:
        week = gym_svc.get_week(db, user.id) or {}
        cardio = gym_svc.get_cardio(db, user.id) or {}
    except Exception:                              # noqa: BLE001 — never fail the report for this
        week, cardio = {}, {}
    if week:
        out.append(_heading("Weekly split", 3))
        for day, kind in week.items():
            extra = f" + {cardio[day]}" if cardio.get(day) else ""
            out.append(f"- **{day}:** {kind}{extra}")

    # The gym LOG is opt-out on the Physical tab (dev_svc.coach_reads_gym_logs). This report is
    # read the same way the coach reads the digest, so it honours the same setting — and, exactly
    # as there, it SAYS the log is withheld rather than leaving a gap that reads as "did nothing".
    out.append(_heading("Training, last 14 days", 3))
    if not dev_svc.coach_reads_gym_logs(db, user.id):
        out.append("_Not shared._ This person has chosen not to expose their workout log. They do "
                   "train; they simply do not log every session, so the log would measure their "
                   "logging habit and not their training. **Draw no conclusion about training "
                   "frequency, consistency or missed sessions from its absence** — the weekly "
                   "split above is what they intend to train.")
    else:
        today = today_ph()
        since = today - timedelta(days=14)
        sessions = db.execute(select(func.count(GymLog.id)).where(
            GymLog.user_id == user.id, GymLog.date >= since)).scalar() or 0
        completed = db.execute(select(func.count(GymLog.id)).where(
            GymLog.user_id == user.id, GymLog.date >= since,
            GymLog.status == GYM_COMPLETED)).scalar() or 0
        out.append(_line("Sessions logged", sessions))
        out.append(_line("Completed", completed))
    out.append("\n> Training load bears on studying: after hard physical days, heavy new material "
               "lands worse than review does. Worth weighing when advising what to study.")
    return "\n".join(out) + "\n"


def _work_section(db: Session, user: User, include_team: bool) -> str:
    """§14 — their OWN work. The estate-wide half is opt-in; see the module docstring."""
    digest = work_svc.work_digest(db, user)
    mine = digest.get("mine") or {}
    out = [_heading("14. Work")]
    out.append(_line("Scope of what they can see", (digest.get("viewer") or {}).get("sees")))
    out.append(_line("Open tasks", mine.get("open_total")))
    out.append(_line("Overdue", mine.get("overdue_total")))
    out.append(_line("Parked", mine.get("parked")))

    open_cards = mine.get("open") or []
    if open_cards:
        out.append(_heading("Open", 3))
        for c in open_cards:
            due = f", due {c['due']}" if c.get("due") else ""
            overdue = f" **{c['overdue_days']}d overdue**" if c.get("overdue_days") else ""
            client = f" [{c['client']}]" if c.get("client") else ""
            out.append(f"- **{c.get('title')}**{client} — {c.get('status')}{due}{overdue}")

    done = mine.get("done") or []
    if done:
        out.append(_heading("Recently completed", 3))
        for c in done[:40]:
            on = f" _({c['on']})_" if c.get("on") else " _(no completion date recorded)_"
            out.append(f"- {c.get('title')}{on}")
        if len(done) > 40 or mine.get("done_truncated"):
            out.append("\n_Older completed work exists beyond what is listed._")

    if include_team:
        board = digest.get("board") or {}
        out.append(_heading("14a. Wider board (opt-in)", 3))
        out.append(_line("Cards visible in total", board.get("visible_total")))
        out.append("\n> 🔴 Per-person rows **do not sum to the number of tasks** — a card with "
                   "steps on two people counts on both. Tasks carry no size estimate, so this "
                   "cannot support the word \"overloaded\".")
    return "\n".join(out) + "\n"


def _mentors_section(profile: dict) -> str:
    """§15 — the mentor library. The in-app coach can retrieve passages from these; a reader of
    this document cannot, so it gets the roster and an explicit statement of that limit."""
    transcripts = profile.get("transcripts") or []
    out = [_heading("15. Mentor library")]
    if not transcripts:
        out.append("_No mentor transcripts imported._\n")
        return "\n".join(out) + "\n"
    by_mentor: dict[str, list[str]] = {}
    for t in transcripts:
        by_mentor.setdefault(t.get("mentor_name") or "Unknown", []).append(t.get("title") or "—")
    out.append(f"_{len(transcripts)} transcripts from {len(by_mentor)} mentors, imported by them "
               f"as a personal knowledge base._\n")
    for mentor in sorted(by_mentor):
        titles = by_mentor[mentor]
        out.append(f"- **{mentor}** ({len(titles)}): {'; '.join(sorted(titles)[:12])}"
                   + (" …" if len(titles) > 12 else ""))
    out.append("\n> 🔴 Titles only — the transcript bodies are NOT in this document. You may say "
               "what is in the library and must not quote or paraphrase what these mentors said.")
    return "\n".join(out) + "\n"


# --- assembly ----------------------------------------------------------------


def build(db: Session, user: User, *, include_team: bool = False) -> dict:
    """Compose the whole report. Never raises on a missing source — it reports the gap instead."""
    gaps: list[str] = []
    profile = dev_svc.full_profile(db, user)
    areas = profile.get("areas") or {}
    email = (user.email or "").lower()

    engine_by_email, engine_error = fetch_engine([email], WINDOW_DAYS)
    engine = engine_by_email.get(email)
    if engine_error:
        gaps.append(f"Mastery Engine rollup: {engine_error}")
    elif not engine or not engine.get("found"):
        gaps.append(f"Mastery Engine has no record for {user.email}"
                    + (f" ({engine['error']})" if engine and engine.get("error") else ""))

    def _call(purpose: str, path: str, params: dict) -> tuple[dict | None, str]:
        status, data, err = engine_bridge.call(purpose, path, params=params,
                                               timeout=engine_bridge.TEAM_TIMEOUT)
        if status == 200 and isinstance(data, dict):
            return data, ""
        return None, (err or f"the Mastery Engine answered {status}")

    detail, detail_error = _call("learner-detail", "/api/internal/learner-detail",
                                 {"email": user.email})
    if detail is None:
        gaps.append(f"Per-topic curriculum detail: {detail_error}")

    activity, activity_error = _call("quiz-activity", "/api/internal/quiz-activity",
                                     {"email": user.email, "days": WINDOW_DAYS,
                                      "wrongOnly": 1, "limit": MAX_MISSED_QUESTIONS * 4})
    if activity is None:
        gaps.append(f"Missed-question detail: {activity_error}")

    now = now_ph()
    header = (
        f"# {user.name or user.email} — complete personal context\n\n"
        f"_Generated {now.strftime('%Y-%m-%d %H:%M')} Asia/Manila by Sentinel. "
        f"Regenerated in full on every run._\n"
    )

    body = "".join([
        _how_to_use(),
        _systems(),
        _methodology(),
        _identity_section(user, profile),
        _mastery_section(engine, engine_error),
        _curriculum_section(detail, detail_error),
        _focus_section(detail),
        _learning_section(engine, activity, activity_error),
        _goals_section(profile),
        _growth_section(profile, areas),
        _career_section(profile),
        _reading_section(profile),
        _physical_section(db, user, profile),
        _work_section(db, user, include_team),
        _mentors_section(profile),
    ])

    gaps_section = _heading("16. Gaps in this report")
    if gaps:
        gaps_section += ("The following could not be loaded on this run. 🔴 **Treat each as "
                         "unknown, not as zero and not as absent.**\n\n")
        gaps_section += "\n".join(f"- {g}" for g in gaps) + "\n"
    else:
        gaps_section += "Every source answered on this run; nothing is missing.\n"

    return {
        "markdown": header + body + gaps_section,
        "gaps": gaps,
        "as_of": today_ph().isoformat(),
        "generated_at": now.isoformat(),
    }

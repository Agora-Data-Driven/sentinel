/* TODAY — the specialist's landing (2026-09-02). Mounted by dashboard.js for employee / intern /
   team_lead, between the greeting and the growth compass.

   One rule per block: Work today is ONE list (priority, then deadline), Waiting on others is the
   parked cards with their reason, Time today is the three sources on one bar, Training today is the
   engine's enrolled programmes. No tiles, no rails — the mockup review found those unreadable.

   Data: /api/tasks (already scoped by the server; `mine` is the server's answer — never re-derive
   it, see AGENTS.md §5 "Is this work on me?") and /api/ops/today (time + training). */
window.TodayPage = {
  async mount(S, root) {
    const U = window.OpsUI;
    root.innerHTML = `<div class="skeleton skel-card" style="height:220px;margin-bottom:18px"></div>`;
    await U.meta(S);
    const [tasks, today] = await Promise.all([
      S.api("/api/tasks").catch((e) => ({ __err: e })),
      S.api("/api/ops/today").catch((e) => ({ __err: e })),
    ]);
    if (!tasks || tasks.__err) {
      const e = tasks && tasks.__err;
      root.innerHTML = `<div class="notice warn"><b>Couldn't load your work.</b> ${S.esc((e && (e.detail || e.message)) || "The task service didn't answer.")}
        <a class="btn sm ghost" href="/tasks" style="margin-left:6px">Open the task board</a></div>`;
      return;
    }
    const PH = U.PH_TODAY();
    const mine = tasks.filter((t) => t.mine && !t.archived);
    const open = mine.filter((t) => !U.isDone(S, t));
    const waiting = open.filter((t) => U.isParked(S, t));
    const active = today && today.time && today.time.active_session;
    const work = open.filter((t) => !U.isParked(S, t)).map((t) => ({ ...t, running: !!active && active.task_id === t.id }))
      .sort((a, b) => {
        // Running first, then late, then priority, then deadline (undated last).
        if (a.running !== b.running) return a.running ? -1 : 1;
        const la = a.due_date && a.due_date < PH, lb = b.due_date && b.due_date < PH;
        if (la !== lb) return la ? -1 : 1;
        const pr = U.prioRank(S, a.priority) - U.prioRank(S, b.priority);
        if (pr) return pr;
        return (a.due_date || "9999") < (b.due_date || "9999") ? -1 : (a.due_date || "9999") > (b.due_date || "9999") ? 1 : b.id - a.id;
      });
    const late = work.filter((t) => t.due_date && t.due_date < PH).length;
    const dueToday = work.filter((t) => t.due_date === PH).length;
    const tomorrow = new Date(Date.parse(PH + "T00:00:00Z") + 864e5).toISOString().slice(0, 10);
    const tmr = work.filter((t) => t.due_date === tomorrow);

    // --- time today -----------------------------------------------------------------------------
    const tm = (today && today.time) || null;
    let timeHtml = `<div class="os-empty">Couldn't read today's time.</div>`;
    if (tm) {
      const att = tm.attendance || {};
      const client = tm.client_minutes || 0, internal = tm.internal_minutes || 0;
      const learn = tm.learning_minutes;            // null = the engine could not be read
      const activeMin = client + internal + (learn || 0);
      const total = att.minutes;
      const w = (n) => (total ? Math.min(100, (n / total) * 100) : 0);
      const leg = (dotColor, k, v, muted) => `<span class="k"><i class="dot" style="background:${dotColor}"></i>${k}</span><span class="v ${muted ? "muted" : ""}">${v}</span>`;
      timeHtml = `
        <div class="os-big">${U.fmtMin(activeMin)}<small>${total != null ? `active of ${U.fmtMin(total)} clocked in` : "active · not clocked in"}</small></div>
        <div class="os-tbar"><i style="width:${w(client)}%;background:var(--green)"></i><i style="width:${w(learn || 0)}%;background:var(--dim-professional, #3A9A2F)"></i><i style="width:${w(internal)}%;background:var(--info)"></i></div>
        <div class="os-tleg">
          ${leg("var(--green)", "Client work", U.fmtMin(client), !client)}
          ${leg("var(--dim-professional, #3A9A2F)", "Training", learn == null ? "—" : U.fmtMin(learn), !learn)}
          ${leg("var(--info)", "Internal", U.fmtMin(internal), !internal)}
          ${total != null ? leg("var(--line-strong)", "Unallocated", U.fmtMin(tm.unallocated_minutes), true) : ""}
        </div>
        <div class="os-note">Task time comes from <b>Start Work</b>. Training comes from the Mastery Engine automatically${learn == null && tm.learning_error ? ` (unreadable right now: ${S.esc(tm.learning_error)})` : ""}. Unallocated is simply time with no session running.</div>`;
    }

    // --- training ---------------------------------------------------------------------------------
    const tr = (today && today.training) || { programs: [], error: "" };
    const progs = (tr.programs || []).filter((p) => p.pct == null || p.pct < 100);
    const trainHtml = progs.length
      ? progs.slice(0, 4).map((p) => `<a class="os-row" href="/academy">
          <span class="os-main"><span class="os-title">${S.esc(p.name)}</span>
          <span class="os-meta">${p.pct != null ? `${p.pct}% mastered` : "enrolled"}${p.topics_total ? ` · ${p.topics_practiced || 0} of ${p.topics_total} topics` : ""}</span></span>
          <span class="os-right"><span class="os-chev">${S.ICON.chev}</span></span></a>`).join("")
      : `<div class="os-empty">${tr.error ? "The Mastery Engine couldn't be read." : "Nothing assigned — open Growth to pick a programme."}</div>`;

    root.innerHTML = `
      <div class="os-two">
        <div>
          ${U.head("Work today", `<b>${work.length}</b> on you${dueToday ? ` · <b class="warn">${dueToday} due today</b>` : ""}${late ? ` · <b class="bad">${late} late</b>` : ""} · priority, then deadline`)}
          <div class="card">${U.list(work.map((t) => U.taskRow(S, t)), `You're clear. <a href="/tasks">Pick something up →</a>`)}
            <div class="os-foot">${tmr.length ? `Tomorrow: ${tmr.map((t) => S.esc(t.title)).join(" · ")}.` : `<b>Nothing is planned for tomorrow yet</b> — tell your lead before you clock out.`}</div>
          </div>
          <div class="os-sect">
            ${U.head("Waiting on others", "parked with a reason — not late, not yours to chase")}
            <div class="card">${U.list(waiting.map((t) => U.taskRow(S, t)), "Nothing is waiting.")}</div>
          </div>
        </div>
        <div>
          ${U.head("Time today", `<a href="/tasks">Details</a>`)}
          <div class="card pad os-time" id="today-time">${timeHtml}</div>
          <div class="os-sect">
            ${U.head("Training today", `<a href="/academy">Open the engine →</a>`)}
            <div class="card">${trainHtml}</div>
          </div>
        </div>
      </div>`;
    // A Start Work / Pause anywhere (the topbar strip, the board) re-reads this page's time card.
    document.addEventListener("sentinel:session", () => TodayPage.mount(S, root), { once: true });
  },
};

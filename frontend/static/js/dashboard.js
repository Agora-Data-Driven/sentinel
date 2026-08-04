/* Overview — the one page you land on (renamed from "Dashboard" 2026-08-03, when the Growth
   hub's own Overview merged into it; /growth now only serves a manager's read-only view of
   somebody else).

   Reading order, top to bottom — personal first, org-wide last:
     1. Greeting + the DAY STRIP: attendance and gym as two compact buttons, not two big tiles.
        (The notifications tile was dropped: the bell in the topbar is the same number, and a
        card whose only content is a count you can already see is a card that earns nothing.)
     2. Your growth — the four dimension rings (GrowthPanel's compass). Each ring OPENS its
        Mastery Engine tab; "Details" expands that dimension in the ledger further down.
     3. The Task Board (taskboard.js) — the work itself, immediately visible.
     4. The growth ledger — pace band, per-dimension details, mentor library (GrowthPanel again).
     5. Across Agora — attendance KPIs, the clock-in trend, late list and handovers. Admins only,
        and last, because it's the one block that isn't about the person reading it. */
window.pageInit = async (S) => {
  const view = S.view();
  // Loading state so the page shows its shape immediately instead of a blank flash.
  view.innerHTML = `
    <div class="skeleton skel-line" style="height:28px;width:min(280px,60%);margin-bottom:22px"></div>
    <div class="skeleton skel-card" style="height:170px;margin-bottom:22px"></div>
    <div class="skeleton skel-card" style="height:260px"></div>`;
  const d = await S.api("/api/dashboard");
  const u = d.user;
  const greeting = new Date().getHours() < 12 ? "Good morning" : new Date().getHours() < 18 ? "Good afternoon" : "Good evening";
  S.qs("#top-sub").textContent = S.fmtDateFull(d.date + "T00:00:00+08:00");

  const kpi = (label, val, sub, cls, icon) => `
    <div class="kpi ${cls || ""}">
      <div class="k-label"><span class="k-ic">${S.ICON[icon] || S.ICON.grid}</span>${label}</div>
      <div class="k-val">${val}</div>
      <div class="k-sub">${sub || ""}</div>
    </div>`;

  // --- 1 · the day strip ---------------------------------------------------------------------
  // Two buttons where two cards used to be. Attendance re-renders in place after a punch (the
  // punch response carries the fresh summary + the remaining valid actions), so the whole strip
  // never needs a reload; the gym half is a plain link to the day's session.
  const me = d.me;
  const attStrip = (at, actions) => {
    const btn =
      (actions.includes("clock_in") ? `<button class="btn sm success" id="clock-in">${S.ICON.check}Clock In</button>` : "") +
      (actions.includes("clock_out") ? `<button class="btn sm danger" id="clock-out">${S.ICON.logout}Clock Out</button>` : "");
    const val = at
      ? `${S.statusPill(at.status)}<span class="ds-when">${S.fmtTime(at.clock_in)}${at.clock_out ? " – " + S.fmtTime(at.clock_out) : ""} · ${at.total_work_hours}h</span>`
      : `<span class="ds-when">Not clocked in yet</span>`;
    return `<span class="ds-ic">${S.ICON.clock}</span>
      <span class="ds-txt"><span class="ds-k">Attendance</span><span class="ds-v">${val}</span></span>
      ${btn}`;
  };
  const gymStrip = () => {
    const g = me.gym_today;
    const val = g
      ? `<span class="pill day ${g.day_type}">${g.day_type}</span>${S.statusPill(g.status)}`
      : `<span class="ds-when">No session logged</span>`;
    return `<a class="day-item" href="/gym" title="${g ? "Open today's session" : "Start a workout"}">
      <span class="ds-ic">${S.ICON.dumbbell}</span>
      <span class="ds-txt"><span class="ds-k">Gym</span><span class="ds-v">${val}</span></span>
      <span class="ds-go">${g ? "Open" : "Start"} &rarr;</span>
    </a>`;
  };

  let html = `<div class="pagehead">
      <div><h2>${greeting}, ${S.esc(u.name.split(" ")[0])}</h2>
        <div class="lead">${S.fmtDateFull(d.date + "T00:00:00+08:00")} · Here's what's happening across Agora today.</div></div>
      <div class="day-strip">
        <div class="day-item" id="att-card">${attStrip(me.attendance_today, me.attendance_actions || [])}</div>
        ${gymStrip()}
      </div>
    </div>`;

  // --- 2 · your growth (the compass) ----------------------------------------------------------
  html += `<div class="row between sect-head">
      <div class="section-label">${S.ICON.sparkle}Your growth</div>
      <span class="sub">Each ring is that tab's Mastery Engine score — open one to go straight in.</span>
    </div>
    <div id="dash-rings"></div>`;

  // --- 3 · my work -----------------------------------------------------------------------------
  // The Task Board left this page on 2026-08-03 (decision D7) — it has its own /tasks page and
  // sidebar item again. What stays is a "my work" strip: the three questions someone opens the
  // Overview to answer, each linking INTO the board rather than duplicating it.
  html += `<div id="dash-mywork"></div>`;

  // --- 4 · the growth ledger ------------------------------------------------------------------
  html += `<div id="dash-growth" style="margin-top:26px"></div>`;

  // --- 5 · across Agora (admins only) ---------------------------------------------------------
  if (d.is_admin) {
    // Presence-focused KPIs — tasks/approvals were dropped 2026-07-27 (tasks live on the
    // board above; approvals have their own page + the bell).
    const k = d.kpis;
    html += `<div class="row between sect-head" style="margin-top:30px">
        <div class="section-label">${S.ICON.users}Across Agora</div>
        ${u.role === "super_admin" ? `<button class="btn sm ghost" id="run-daily" title="Recompute yesterday's attendance and send reminders now">${S.ICON.check}Run daily processing</button>` : ""}
      </div>
      <div class="kpis" style="margin-bottom:18px">
        ${kpi("Present today", k.present_today, `of ${k.headcount} staff`, "", "clock")}
        ${kpi("Late today", k.late_today, "clocked in late", k.late_today ? "warn" : "", "coffee")}
        ${kpi("Gym this week", k.gym_completed_week, "sessions completed", "", "dumbbell")}
      </div>
      <div class="card pad" id="chart-attendance" style="margin-bottom:18px"></div>
      <div class="grid" style="grid-template-columns:1fr 1fr">
        <div class="card"><div class="card-head"><h3>Late today</h3><span class="chip">${d.late_today_list.length}</span></div>
          <div class="card-body">${d.late_today_list.length ? d.late_today_list.map((s) => `
            <div class="row between" style="padding:7px 0;border-bottom:1px solid var(--line)">
              <div class="t-name">${S.avatar(s.user, "sm")}<span>${S.esc(s.user.name)}</span></div>
              <div>${S.statusPill("Late")} <span class="sub">${S.fmtTime(s.clock_in)}</span></div>
            </div>`).join("") : '<div class="empty">Everyone on time.</div>'}</div></div>

        <div class="card"><div class="card-head"><h3>Handover notes</h3><span class="chip">yesterday</span></div>
          <div class="card-body">${d.handovers && d.handovers.length ? d.handovers.map((h) => `
            <div style="padding:9px 0;border-bottom:1px solid var(--line)">
              <div class="t-name" style="margin-bottom:3px">${S.avatar(h.user, "sm")}<strong>${S.esc(h.user.name)}</strong></div>
              <div class="sub" style="font-size:13px">${S.esc(h.note)}</div></div>`).join("") : '<div class="empty">No handover notes.</div>'}</div></div>
      </div>`;
  }

  view.innerHTML = html;

  // Clock In / Clock Out from the strip. The punch response carries the fresh summary +
  // remaining valid actions, so the item re-renders in place without a page reload.
  async function punch(action, extra) {
    try {
      const res = await S.api("/api/attendance/self-event", { method: "POST", body: { action, ...extra } });
      const late = res.late_status === "Late" ? ` · ${res.late_minutes}m late` : "";
      S.toast((action === "clock_in" ? "Clocked in" : "Clocked out") + late, "ok");
      S.qs("#att-card").innerHTML = attStrip(res.summary, res.scan.valid_actions);
      wireAttCard();
    } catch (e) { S.toast(e.detail || "Couldn't record the punch", "err"); }
  }
  function wireAttCard() {
    const ci = S.qs("#clock-in"), co = S.qs("#clock-out");
    if (ci) ci.onclick = () => { ci.disabled = true; punch("clock_in", {}); };
    if (co) co.onclick = () => {
      // Same optional handover note the kiosk asks for on the way out.
      const m = S.modal({
        title: "Clock out",
        body: `<label class="field"><span>Handover note (optional)</span>
          <textarea id="ho-note" placeholder="What should the next shift know?"></textarea></label>`,
        footer: `<button class="btn ghost" id="ho-cancel">Cancel</button>
          <button class="btn danger" id="ho-go">Clock Out</button>`,
      });
      S.qs("#ho-cancel").onclick = () => m.close();
      S.qs("#ho-go").onclick = () => {
        const note = S.qs("#ho-note").value.trim();
        m.close();
        punch("clock_out", { handover_note: note || null });
      };
    };
  }
  wireAttCard();

  // Mount the growth hub across its two hosts — the compass above "my work", the ledger below it.
  // Fail-soft: growth is a section of this page, not the page, so a bad /api/development never
  // costs anyone the rest of their Overview.
  if (window.GrowthPanel) {
    GrowthPanel.mount(S, S.qs("#dash-growth"), { ringsHost: S.qs("#dash-rings") })
      .catch((e) => S.toast(e.detail || "Couldn't load your growth", "err"));
  }

  // "My work": what is on me, what is late, what is waiting on my approval. The board itself lives
  // at /tasks (decision D7) — this strip links INTO it rather than duplicating it. Rendered after
  // the page paints so the greeting never waits on it, and it fails SILENTLY: a task-list hiccup
  // must not put an error toast over someone's morning attendance card.
  renderMyWork();
  async function renderMyWork() {
    // "Today" in Manila as an ISO date (en-CA -> YYYY-MM-DD), so "overdue" matches the SERVER's
    // Asia/Manila business rule rather than the viewer's timezone. Same one-liner taskboard.js uses;
    // deliberately duplicated rather than exported, since these two files share no module system.
    const PH_TODAY = new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Manila" });
    const box = S.qs("#dash-mywork");
    if (!box) return;
    let tasks;
    try { tasks = await S.api("/api/tasks"); }
    catch (e) { return; }
    // The list is already scoped by the server (task_perms.can_view), so "mine" is a filter on top
    // of it, never a second source of truth. Atrium-owned cards have no assignee to be mine.
    const mine = tasks.filter((t) => t.assigned_to_id === S.user.id && !t.archived);
    const open = mine.filter((t) => !t.completed_at);
    const overdue = open.filter((t) => t.due_date && t.due_date < PH_TODAY);
    // Waiting on ME: only a lead/manager sees these, and only for their own team — the same scope
    // task_perms.can_review enforces server-side (the buttons live in the board's panel).
    const canReview = S.can("account_manager")
      || (S.can("team_lead") && S.user.team_id != null);
    const toReview = !canReview ? [] : tasks.filter((t) => t.review_state === "pending"
      && (S.can("account_manager") || t.assigned_team_id === S.user.team_id));
    const tile = (n, label, href, bad) => `<a class="card pad" href="${href}" style="text-decoration:none;flex:1;min-width:150px">
        <div class="section-label">${label}</div>
        <div class="k-val ${bad && n ? "bad" : ""}" style="font-size:30px;margin-top:6px">${n}</div>
      </a>`;
    box.innerHTML = `<div class="pagehead" style="margin:30px 0 14px"><div>
        <h3 style="font-size:18px;letter-spacing:-.01em">My work</h3>
        <div class="lead">Everything else is on the <a href="/tasks">Task Board</a>.</div></div></div>
      <div class="row" style="gap:12px;align-items:stretch;flex-wrap:wrap">
        ${tile(open.length, "Open tasks", "/tasks")}
        ${tile(overdue.length, "Overdue", "/tasks", true)}
        ${canReview ? tile(toReview.length, "Waiting on my approval", "/tasks") : ""}
      </div>
      ${open.length ? `<div class="card" style="margin-top:12px">${open.slice(0, 5).map((t) => `
        <a class="row" href="/tasks?open=${t.id}" style="text-decoration:none;justify-content:space-between;gap:10px;padding:11px 14px;border-bottom:1px solid var(--line-soft)">
          <span style="min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${S.esc(t.title)}</span>
          <span class="sub" style="flex:none;font-size:12px">${S.esc(t.status)}${t.due_date
            ? ` · <span class="${t.due_date < PH_TODAY ? "bad" : ""}">${S.fmtDate(t.due_date + "T00:00:00+08:00")}</span>` : ""}</span>
        </a>`).join("")}</div>` : `<div class="empty card pad" style="margin-top:12px">Nothing assigned to you right now.</div>`}`;
  }

  // Clock-in chart (admin only) — fetched after paint so the page never blocks on it.
  // Clicking a day opens the roster of who clocked in (data rides along in the trend).
  if (d.is_admin && window.SentinelCharts) {
    try {
      const ins = await S.api("/api/insights");
      SentinelCharts.attendanceTrend(S.qs("#chart-attendance"), ins.attendance_trend, (day) => {
        const rows = (day.people || []).map((p) => `
          <div class="row between" style="padding:8px 0;border-bottom:1px solid var(--line)">
            <div class="t-name">${S.avatar(p.user, "sm")}<span>${S.esc(p.user.name)}</span></div>
            <div>${S.statusPill(p.status)} <span class="sub">${S.fmtTime(p.clock_in)}</span></div>
          </div>`).join("");
        S.modal({
          title: `Clocked in · ${S.fmtDateFull(day.date + "T00:00:00+08:00")}`,
          body: rows
            ? `<div class="sub" style="margin-bottom:6px">${day.people.length} ${day.people.length === 1 ? "person" : "people"}, earliest first</div>${rows}`
            : '<div class="empty">No one clocked in.</div>',
        });
      });
    } catch (e) { /* charts are non-critical */ }
  }

  const rb = S.qs("#run-daily");
  if (rb) rb.onclick = async () => {
    rb.disabled = true; const orig = rb.innerHTML; rb.textContent = "Processing…";
    try {
      const r = await S.api("/api/cron/daily", { method: "POST" });
      const a = r.attendance || {}, m = r.reminders || {};
      S.toast(`Processed ${a.date}: ${a.absent || 0} absent, ${a.on_leave || 0} on leave, ${a.missing_clockout || 0} missing clock-out · ${m.overdue_notified || 0} overdue nudges`, "ok");
    } catch (e) { S.toast(e.detail || "Couldn't run daily processing", "err"); }
    finally { rb.disabled = false; rb.innerHTML = orig; }
  };
};

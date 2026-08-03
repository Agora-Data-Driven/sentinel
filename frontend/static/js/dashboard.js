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

  // --- 3 · the task board (its own page until 2026-07-26) — see taskboard.js -------------------
  html += `<div id="dash-taskboard"></div>`;

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

  // Mount the growth hub across its two hosts — the compass above the board, the ledger below it.
  // Fail-soft: growth is a section of this page, not the page, so a bad /api/development never
  // costs anyone their task board.
  if (window.GrowthPanel) {
    GrowthPanel.mount(S, S.qs("#dash-growth"), { ringsHost: S.qs("#dash-rings") })
      .catch((e) => S.toast(e.detail || "Couldn't load your growth", "err"));
  }

  // Mount the embedded Task Board (filters, views, drag-and-drop, detail drawer, SSE) after the
  // page paints, so the greeting/growth never wait on the board's data.
  if (window.TaskBoard) {
    TaskBoard.mount(S, S.qs("#dash-taskboard"))
      .catch((e) => S.toast(e.detail || "Couldn't load the task board", "err"));
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

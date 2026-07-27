window.pageInit = async (S) => {
  const view = S.view();
  // Loading state so the page shows its shape immediately instead of a blank flash.
  view.innerHTML = `
    <div class="skeleton skel-line" style="height:28px;width:min(280px,60%);margin-bottom:22px"></div>
    <div class="kpis" style="margin-bottom:22px">
      ${Array.from({ length: 3 }, () => '<div class="skeleton skel-card" style="height:96px"></div>').join("")}
    </div>
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

  let html = `<div class="pagehead"><div><h2>${greeting}, ${S.esc(u.name.split(" ")[0])}</h2>
    <div class="lead">${S.fmtDateFull(d.date + "T00:00:00+08:00")} · Here's what's happening across Agora today.</div></div></div>`;

  if (d.is_admin) {
    // Presence-focused KPIs — tasks/approvals were dropped 2026-07-27 (tasks live on the
    // board below; approvals have their own page + the bell).
    const k = d.kpis;
    html += `<div class="kpis" style="margin-bottom:22px">
      ${kpi("Present today", k.present_today, `of ${k.headcount} staff`, "", "clock")}
      ${kpi("Late today", k.late_today, "clocked in late", k.late_today ? "warn" : "", "coffee")}
      ${kpi("Gym this week", k.gym_completed_week, "sessions completed", "", "dumbbell")}
    </div>`;

    html += `<div class="row between" style="margin:0 0 10px;align-items:center">
      <div class="section-label">Insights</div>
      ${u.role === "super_admin" ? `<button class="btn sm ghost" id="run-daily" title="Recompute yesterday's attendance and send reminders now">${S.ICON.check}Run daily processing</button>` : ""}
    </div>
    <div class="card pad" id="chart-attendance" style="margin-bottom:18px"></div>`;

    html += `<div class="grid" style="grid-template-columns:1fr 1fr">
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

  // Personal snapshot (all roles)
  const me = d.me;

  // Attendance card: today's punches + Clock In / Clock Out right here (self-punch via
  // /api/attendance/self-event, device "web") — no kiosk or scanner needed.
  const attCard = (at, actions) => {
    const btns =
      (actions.includes("clock_in") ? `<button class="btn sm success" id="clock-in">${S.ICON.check}Clock In</button>` : "") +
      (actions.includes("clock_out") ? `<button class="btn sm danger" id="clock-out">${S.ICON.logout}Clock Out</button>` : "");
    return `<div class="section-label">Attendance today</div>
      ${at ? `<div style="margin-top:10px">${S.statusPill(at.status)}
        <div class="row" style="margin-top:10px;gap:22px">
          <div><div class="sub" style="font-size:11px">CLOCK IN</div><strong>${S.fmtTime(at.clock_in)}</strong></div>
          <div><div class="sub" style="font-size:11px">CLOCK OUT</div><strong>${S.fmtTime(at.clock_out)}</strong></div>
          <div><div class="sub" style="font-size:11px">HOURS</div><strong>${at.total_work_hours}h</strong></div>
        </div></div>` : `<div class="empty" style="padding:14px">Not clocked in yet.</div>`}
      ${btns ? `<div class="row" style="gap:8px;margin-top:12px">${btns}</div>` : ""}`;
  };

  html += `<h3 style="margin:26px 0 12px">Your day</h3>
    <div class="spread">
      <div class="card pad" id="att-card">${attCard(me.attendance_today, me.attendance_actions || [])}</div>
      <div class="card pad">
        <div class="section-label">Gym today</div>
        ${me.gym_today ? `<div style="margin-top:10px"><span class="pill day ${me.gym_today.day_type}">${me.gym_today.day_type}</span> ${S.statusPill(me.gym_today.status)}</div>
          <a class="btn sm ghost" href="/gym" style="margin-top:12px">Open session →</a>`
          : `<div class="empty" style="padding:16px">No session logged.<br><a class="btn sm success" href="/gym" style="margin-top:10px">Start a workout</a></div>`}
      </div>
      <div class="card pad">
        <div class="section-label">Notifications</div>
        <div class="k-val" style="font-size:34px;margin-top:8px">${me.unread_notifications}</div>
        <div class="sub">unread</div>
      </div>
    </div>`;

  // The full Task Board (its own page until 2026-07-26) now lives here — see taskboard.js.
  html += `<div id="dash-taskboard"></div>`;

  view.innerHTML = html;

  // Clock In / Clock Out from the card. The punch response carries the fresh summary +
  // remaining valid actions, so the card re-renders in place without a page reload.
  async function punch(action, extra) {
    try {
      const res = await S.api("/api/attendance/self-event", { method: "POST", body: { action, ...extra } });
      const late = res.late_status === "Late" ? ` · ${res.late_minutes}m late` : "";
      S.toast((action === "clock_in" ? "Clocked in" : "Clocked out") + late, "ok");
      S.qs("#att-card").innerHTML = attCard(res.summary, res.scan.valid_actions);
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

  // Mount the embedded Task Board (filters, views, drag-and-drop, detail drawer, SSE) after the
  // dashboard paints, so the greeting/KPIs never wait on the board's data.
  if (window.TaskBoard) {
    TaskBoard.mount(S, S.qs("#dash-taskboard"))
      .catch((e) => S.toast(e.detail || "Couldn't load the task board", "err"));
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

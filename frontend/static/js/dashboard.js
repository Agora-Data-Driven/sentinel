window.pageInit = async (S) => {
  const view = S.view();
  // Loading state so the page shows its shape immediately instead of a blank flash.
  view.innerHTML = `
    <div class="skeleton skel-line" style="height:28px;width:min(280px,60%);margin-bottom:22px"></div>
    <div class="kpis" style="margin-bottom:22px">
      ${Array.from({ length: 6 }, () => '<div class="skeleton skel-card" style="height:96px"></div>').join("")}
    </div>
    <div class="grid" style="grid-template-columns:1fr 1fr;gap:16px">
      <div class="skeleton skel-card" style="height:220px"></div>
      <div class="skeleton skel-card" style="height:220px"></div>
    </div>`;
  const d = await S.api("/api/dashboard");
  const u = d.user;
  const greeting = new Date().getHours() < 12 ? "Good morning" : new Date().getHours() < 18 ? "Good afternoon" : "Good evening";
  S.qs("#top-sub").textContent = S.fmtDateFull(d.date + "T00:00:00+08:00");

  const kpi = (label, val, sub, cls, icon) => `
    <div class="kpi ${cls || ""}">
      <div class="k-ic">${S.ICON[icon] || S.ICON.grid}</div>
      <div class="k-label">${label}</div>
      <div class="k-val">${val}</div>
      <div class="k-sub">${sub || ""}</div>
    </div>`;

  let html = `<div class="pagehead"><div><h2>${greeting}, ${S.esc(u.name.split(" ")[0])} 👋</h2>
    <div class="lead">Here's what's happening across Agora today.</div></div></div>`;

  if (d.is_admin) {
    const k = d.kpis;
    html += `<div class="kpis" style="margin-bottom:22px">
      ${kpi("Headcount", k.headcount, "active employees", "", "users")}
      ${kpi("Present today", k.present_today, k.late_today + " late", "", "clock")}
      ${kpi("Absent today", k.absent_today, "not clocked in", k.absent_today ? "warn" : "", "coffee")}
      ${kpi("Open tasks", k.open_tasks, k.overdue_tasks + " overdue", k.overdue_tasks ? "danger" : "violet", "board")}
      ${kpi("Pending approvals", k.pending_approvals, "leave + attendance", k.pending_approvals ? "warn" : "", "inbox")}
      ${kpi("Gym this week", k.gym_completed_week, "sessions completed", "", "dumbbell")}
    </div>`;

    html += `<div class="row between" style="margin:0 0 10px;align-items:center">
      <div class="section-label">Insights</div>
      ${u.role === "super_admin" ? `<button class="btn sm ghost" id="run-daily" title="Recompute yesterday's attendance and send reminders now">${S.ICON.check}Run daily processing</button>` : ""}
    </div>
    <div class="grid" style="grid-template-columns:1fr 1fr;margin-bottom:18px">
      <div class="card pad" id="chart-attendance"></div>
      <div class="card pad" id="chart-tasks"></div>
    </div>`;

    html += `<div class="grid" style="grid-template-columns:1fr 1fr">
      <div class="card"><div class="card-head"><h3>Late today</h3><span class="chip">${d.late_today_list.length}</span></div>
        <div class="card-body">${d.late_today_list.length ? d.late_today_list.map((s) => `
          <div class="row between" style="padding:7px 0;border-bottom:1px solid var(--line)">
            <div class="t-name">${S.avatar(s.user, "sm")}<span>${S.esc(s.user.name)}</span></div>
            <div>${S.statusPill("Late")} <span class="sub">${S.fmtTime(s.clock_in)}</span></div>
          </div>`).join("") : '<div class="empty">Everyone on time. 🎯</div>'}</div></div>

      <div class="card"><div class="card-head"><h3>Handover notes</h3><span class="chip">yesterday</span></div>
        <div class="card-body">${d.handovers && d.handovers.length ? d.handovers.map((h) => `
          <div style="padding:9px 0;border-bottom:1px solid var(--line)">
            <div class="t-name" style="margin-bottom:3px">${S.avatar(h.user, "sm")}<strong>${S.esc(h.user.name)}</strong></div>
            <div class="sub" style="font-size:13px">${S.esc(h.note)}</div></div>`).join("") : '<div class="empty">No handover notes.</div>'}</div></div>
    </div>`;
  }

  // Personal snapshot (all roles)
  const me = d.me;
  const at = me.attendance_today;
  html += `<h3 style="margin:26px 0 12px">Your day</h3>
    <div class="spread">
      <div class="card pad">
        <div class="section-label">Attendance today</div>
        ${at ? `<div style="margin-top:10px">${S.statusPill(at.status)}
          <div class="row" style="margin-top:10px;gap:22px">
            <div><div class="sub" style="font-size:11px">CLOCK IN</div><strong>${S.fmtTime(at.clock_in)}</strong></div>
            <div><div class="sub" style="font-size:11px">CLOCK OUT</div><strong>${S.fmtTime(at.clock_out)}</strong></div>
            <div><div class="sub" style="font-size:11px">HOURS</div><strong>${at.total_work_hours}h</strong></div>
          </div></div>` : `<div class="empty" style="padding:20px">Not clocked in yet.<br><span class="sub">Scan your badge at the kiosk.</span></div>`}
      </div>
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

  html += `<div class="card" style="margin-top:18px"><div class="card-head"><h3>My open tasks</h3><a class="btn sm ghost" href="/tasks">View board →</a></div>
    <div class="card-body">${me.open_tasks.length ? me.open_tasks.map((t) => `
      <div class="row between" style="padding:9px 0;border-bottom:1px solid var(--line)">
        <div><div class="labels" style="margin-bottom:3px">${S.labelPills(t.labels)}</div><strong>${S.esc(t.title)}</strong>
          <div class="sub" style="font-size:12px">${S.esc(t.client_name || "Internal")}</div></div>
        <div class="row">${S.priorityDot(t.priority)} <span class="pill grey">${S.esc(t.status)}</span></div>
      </div>`).join("") : '<div class="empty">No open tasks assigned to you.</div>'}</div></div>`;

  view.innerHTML = html;

  // Dashboard charts (admin only) — fetched after paint so the page never blocks on them.
  if (d.is_admin && window.SentinelCharts) {
    try {
      const ins = await S.api("/api/insights");
      SentinelCharts.attendanceTrend(S.qs("#chart-attendance"), ins.attendance_trend);
      SentinelCharts.tasksByStatus(S.qs("#chart-tasks"), ins.tasks_by_status);
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

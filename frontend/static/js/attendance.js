window.pageInit = async (S) => {
  const view = S.view();
  const isMgr = S.can("team_lead");
  const isSA = S.user.role === "super_admin";
  const iso = (d) => d.toISOString().slice(0, 10);
  const toHM = (isoStr) => isoStr ? new Date(isoStr).toLocaleTimeString("en-GB", { timeZone: "Asia/Manila", hour: "2-digit", minute: "2-digit" }) : "";
  const STATUSES = ["OnTime", "Late", "Absent", "HalfDay", "MissingClockOut", "OnLeave"];
  const from = new Date(Date.now() - 30 * 864e5);

  const tabs = isMgr ? ["Team summary", "Approvals", "My attendance"] : ["My attendance"];
  view.innerHTML = `<div class="pagehead"><div><h2>Attendance</h2>
    <div class="lead">${isMgr ? "Time-in / time-out logs, daily summaries, and correction approvals." : "Your attendance history and correction requests."}</div></div>
    <button class="btn primary" id="new-req">${S.ICON.plus}New request</button></div>
    <div class="tabs" id="tabs">${tabs.map((t, i) => `<button class="${i === 0 ? "active" : ""}" data-tab="${t}">${t}</button>`).join("")}</div>
    <div id="tabc"></div>`;

  const tabc = S.qs("#tabc");
  S.qsa("#tabs button").forEach((b) => b.onclick = () => {
    S.qsa("#tabs button").forEach((x) => x.classList.remove("active")); b.classList.add("active"); render(b.dataset.tab);
  });

  let teams = [];
  if (isMgr) { try { teams = await S.api("/api/teams"); } catch (e) {} }

  async function render(tab) {
    tabc.innerHTML = '<div class="skeleton" style="height:200px"></div>';
    if (tab === "Team summary") return renderSummary();
    if (tab === "Approvals") return renderApprovals();
    return renderMine();
  }

  async function renderSummary() {
    tabc.innerHTML = `<div class="filters">
      <label>From <input type="date" id="f-from" value="${iso(from)}"></label>
      <label>To <input type="date" id="f-to" value="${iso(new Date())}"></label>
      <select id="f-team"><option value="">All teams</option>${teams.map((t) => `<option value="${t.id}">${S.esc(t.name)}</option>`).join("")}</select>
      <span class="grow"></span>
    </div><div id="sum-table"></div>`;
    const cols = 7 + (isSA ? 1 : 0);
    const load = async () => {
      const q = new URLSearchParams({ from: S.qs("#f-from").value, to: S.qs("#f-to").value });
      if (S.qs("#f-team").value) q.set("team_id", S.qs("#f-team").value);
      const rows = await S.api("/api/attendance/summary?" + q);
      S.qs("#sum-table").innerHTML = `<div class="table-wrap"><table>
        <thead><tr><th>Employee</th><th>Date</th><th>In</th><th>Out</th><th>Hours</th><th>Status</th><th>Handover</th>${isSA ? "<th></th>" : ""}</tr></thead>
        <tbody>${rows.length ? rows.map((s, i) => `<tr>
          <td class="t-name">${S.avatar(s.user, "sm")}${S.esc(s.user ? s.user.name : "?")}</td>
          <td>${S.fmtDate(s.date + "T00:00:00+08:00")}</td>
          <td>${S.fmtTime(s.clock_in)}</td><td>${S.fmtTime(s.clock_out)}</td>
          <td>${s.total_work_hours}h</td>
          <td>${S.statusPill(s.status)}</td>
          <td class="sub" style="max-width:220px">${S.esc(s.handover_note || "—")}</td>
          ${isSA ? `<td style="text-align:right"><button class="btn sm ghost" data-edit="${i}">Edit</button></td>` : ""}</tr>`).join("") : `<tr><td colspan="${cols}"><div class="empty">No records for this range.</div></td></tr>`}</tbody></table></div>`;
      if (isSA) S.qsa("[data-edit]").forEach((b) => b.onclick = () => openEdit(rows[+b.dataset.edit], load));
    };
    ["f-from", "f-to", "f-team"].forEach((id) => S.qs("#" + id).onchange = load);
    load();
  }

  // Super Admin: correct a day's punches / status directly.
  function openEdit(s, refresh) {
    const m = S.modal({
      title: `Edit attendance — ${S.esc(s.user ? s.user.name : "")} · ${S.fmtDate(s.date + "T00:00:00+08:00")}`,
      body: `<div class="row" style="gap:10px">
          <label class="field" style="flex:1"><span>Clock in</span><input type="time" id="e-in" value="${toHM(s.clock_in)}"></label>
          <label class="field" style="flex:1"><span>Clock out</span><input type="time" id="e-out" value="${toHM(s.clock_out)}"></label></div>
        <label class="field"><span>Status</span><select id="e-status">${STATUSES.map((x) => `<option ${x === s.status ? "selected" : ""}>${x}</option>`).join("")}</select></label>
        <div class="muted" style="font-size:12px">Times are PH time. Leave blank to clear. Hours recompute automatically (minus the 1-hour lunch).</div>`,
      footer: `<button class="btn ghost" id="e-cancel">Cancel</button><button class="btn primary" id="e-save">Save</button>`,
    });
    S.qs("#e-cancel").onclick = m.close;
    S.qs("#e-save").onclick = async () => {
      try {
        await S.api(`/api/attendance/summary/${s.id}`, { method: "PATCH", body: {
          clock_in: S.qs("#e-in").value, clock_out: S.qs("#e-out").value, status: S.qs("#e-status").value } });
        S.toast("Attendance updated", "ok"); m.close(); refresh();
      } catch (e) { S.toast(e.detail || "Couldn't update", "err"); }
    };
  }

  async function renderApprovals() {
    const reqs = await S.api("/api/attendance/requests?status=Pending");
    tabc.innerHTML = `<div class="card"><div class="card-head"><h3>Pending requests</h3><span class="chip">${reqs.length}</span></div>
      <div class="card-body">${reqs.length ? reqs.map((r) => `
        <div class="row between" style="padding:12px 0;border-bottom:1px solid var(--line);gap:12px;flex-wrap:wrap">
          <div style="min-width:220px"><div class="t-name" style="margin-bottom:4px">${S.avatar(r.user, "sm")}<strong>${S.esc(r.user.name)}</strong>
            <span class="pill ${r.request_type === "overtime" ? "blue" : "violet"}">${S.esc(r.request_type)}</span></div>
            <div class="sub">${S.fmtDate(r.date + "T00:00:00+08:00")} · ${S.esc(r.reason)}</div>
            ${r.old_value || r.new_value ? `<div class="sub" style="font-size:12px">${S.esc(r.old_value || "—")} → <strong>${S.esc(r.new_value || "—")}</strong></div>` : ""}</div>
          <div class="row"><button class="btn sm success" data-ok="${r.id}">Approve</button><button class="btn sm ghost" data-no="${r.id}">Reject</button></div>
        </div>`).join("") : '<div class="empty">No pending requests. ✅</div>'}</div></div>`;
    S.qsa("[data-ok]").forEach((b) => b.onclick = () => decide(b.dataset.ok, "Approved"));
    S.qsa("[data-no]").forEach((b) => b.onclick = () => decide(b.dataset.no, "Rejected"));
    async function decide(id, status) {
      try { await S.api(`/api/attendance/request/${id}`, { method: "PATCH", body: { status } }); S.toast("Request " + status.toLowerCase(), "ok"); renderApprovals(); }
      catch (e) { S.toast(e.detail, "err"); }
    }
  }

  async function renderMine() {
    const d = await S.api("/api/attendance/my");
    const t = d.today;
    tabc.innerHTML = `<div class="card pad" style="margin-bottom:16px">
        <div class="section-label">Today</div>
        <div class="row" style="margin-top:8px;gap:14px"><span class="pill ${t.state === "in" ? "green" : t.state === "on_break" ? "amber" : t.state === "out" ? "grey" : "grey"}">${t.state === "none" ? "Not clocked in" : t.state === "in" ? "Clocked in" : t.state === "on_break" ? "On break" : "Clocked out"}</span>
        <span class="sub">Punch at the kiosk — actions available: ${t.valid_actions.length ? t.valid_actions.map((a) => a.replace("_", " ")).join(", ") : "none"}</span></div>
      </div>
      <div class="table-wrap"><table>
        <thead><tr><th>Date</th><th>In</th><th>Out</th><th>Hours</th><th>Status</th></tr></thead>
        <tbody>${d.history.length ? d.history.map((s) => `<tr>
          <td>${S.fmtDateFull(s.date + "T00:00:00+08:00")}</td><td>${S.fmtTime(s.clock_in)}</td><td>${S.fmtTime(s.clock_out)}</td>
          <td>${s.total_work_hours}h</td><td>${S.statusPill(s.status)}</td></tr>`).join("") : '<tr><td colspan="5"><div class="empty">No attendance yet.</div></td></tr>'}</tbody></table></div>`;
  }

  S.qs("#new-req").onclick = () => {
    const today = iso(new Date());
    const m = S.modal({
      title: "Attendance request",
      body: `<input type="hidden" id="r-type" value="regularization">
        <label class="field"><span>Date</span><input type="date" id="r-date" value="${today}"></label>
        <div class="row" style="gap:10px"><label class="field" style="flex:1"><span>Old value</span><input id="r-old" placeholder="e.g. — or 8h"></label>
        <label class="field" style="flex:1"><span>New value</span><input id="r-new" placeholder="e.g. 17:10 or 9h40m"></label></div>
        <label class="field"><span>Reason</span><textarea id="r-reason" placeholder="Explain the correction…"></textarea></label>`,
      footer: `<button class="btn ghost" id="r-cancel">Cancel</button><button class="btn primary" id="r-submit">Submit request</button>`,
    });
    S.qs("#r-cancel").onclick = m.close;
    S.qs("#r-submit").onclick = async () => {
      try {
        await S.api("/api/attendance/request", { method: "POST", body: {
          date: S.qs("#r-date").value, request_type: S.qs("#r-type").value,
          reason: S.qs("#r-reason").value, old_value: S.qs("#r-old").value, new_value: S.qs("#r-new").value } });
        S.toast("Request submitted", "ok"); m.close();
      } catch (e) { S.toast(e.detail, "err"); }
    };
  };

  render(tabs[0]);
};

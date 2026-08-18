window.pageInit = async (S) => {
  const view = S.view();
  const isMgr = S.can("team_lead");
  const canEditRecords = S.hasCap("attendance.edit_records");
  const iso = (d) => d.toISOString().slice(0, 10);
  const toHM = (isoStr) => isoStr ? new Date(isoStr).toLocaleTimeString("en-GB", { timeZone: "Asia/Manila", hour: "2-digit", minute: "2-digit" }) : "";
  const STATUSES = ["OnTime", "Late", "Absent", "HalfDay", "MissingClockOut", "OnLeave"];
  const from = new Date(Date.now() - 30 * 864e5);

  // Correction approvals moved to the unified /approvals inbox.
  const tabs = isMgr ? ["Team summary", "My attendance"] : ["My attendance"];
  view.innerHTML = `<div class="pagehead"><div><h2>Attendance</h2>
    <div class="lead">${isMgr ? "Time-in / time-out logs and daily summaries. Correction approvals live in Approvals." : "Your attendance history and correction requests."}</div></div>
    <button class="btn primary" id="new-req">${S.ICON.plus}New request</button></div>
    <div class="tabs" id="tabs">${tabs.map((t, i) => `<button class="${i === 0 ? "active" : ""}" data-tab="${t}">${t}</button>`).join("")}</div>
    <div id="tabc"></div>`;

  const tabc = S.qs("#tabc");
  S.qsa("#tabs button").forEach((b) => b.onclick = () => {
    S.qsa("#tabs button").forEach((x) => x.classList.remove("active")); b.classList.add("active"); render(b.dataset.tab);
  });

  // The department filter's option source. A bare `catch {}` left the picker with only "All teams", so
  // a manager saw a filter that could not filter and no reason why. Non-fatal — the summary table is
  // the point of the page — but say so. A 403 is the normal answer for a role without team scope.
  let teams = [];
  if (isMgr) {
    try { teams = await S.api("/api/teams"); }
    catch (e) { if (e.status !== 401 && e.status !== 403) S.toast("Departments couldn't be loaded — the team filter is empty", "err"); }
  }

  async function render(tab) {
    tabc.innerHTML = '<div class="skeleton" style="height:200px"></div>';
    if (tab === "Team summary") return renderSummary();
    return renderMine();
  }

  async function renderSummary() {
    tabc.innerHTML = `<div class="filters">
      <label>From <input type="date" id="f-from" value="${iso(from)}"></label>
      <label>To <input type="date" id="f-to" value="${iso(new Date())}"></label>
      <select id="f-team"><option value="">All teams</option>${teams.map((t) => `<option value="${t.id}">${S.esc(t.name)}</option>`).join("")}</select>
      <span class="grow"></span>
    </div><div id="sum-table"></div>`;
    const cols = 7 + (canEditRecords ? 1 : 0);
    const load = async () => {
      // Same guard as reports.js: From > To makes the server answer zero rows, which rendered "No
      // records for this range." — a sentence about the DATA when the fault is in the question, and on
      // an ATTENDANCE page that reads as "nobody clocked in", which is alarming and false. ISO
      // `YYYY-MM-DD` from <input type="date"> sorts chronologically as text, so this needs no parsing.
      const f = S.qs("#f-from").value, t = S.qs("#f-to").value;
      if (f && t && f > t) {
        S.qs("#sum-table").innerHTML = `<div class="notice warn"><b>That date range is backwards.</b>
          “From” (${S.esc(f)}) is after “To” (${S.esc(t)}), so there is nothing to show. Swap them.</div>`;
        return;
      }
      const q = new URLSearchParams({ from: f, to: t });
      if (S.qs("#f-team").value) q.set("team_id", S.qs("#f-team").value);
      // `render(tab)` puts a skeleton in #tabc, but renderSummary has already replaced that with the
      // filter bar plus an EMPTY #sum-table by the time this runs — so without these two lines a
      // filter change showed no loading state at all, and a failure showed nothing whatsoever: just
      // a filter bar over blank space, indistinguishable from a range with no records.
      S.qs("#sum-table").innerHTML = S.skeleton({ rows: 6 });
      let rows;
      try { rows = await S.api("/api/attendance/summary?" + q); }
      catch (e) { S.loadErr("#sum-table", e, load); return; }
      S.qs("#sum-table").innerHTML = `<div class="table-wrap tall"><table>
        <thead><tr><th class="sortable">Employee</th><th class="sortable">Date</th><th class="sortable">In</th><th class="sortable">Out</th><th class="sortable">Hours</th><th class="sortable">Status</th><th class="sortable">Handover</th>${canEditRecords ? "<th></th>" : ""}</tr></thead>
        <tbody>${rows.length ? rows.map((s, i) => `<tr>
          <td class="t-name">${S.avatar(s.user, "sm")}${S.esc(s.user ? s.user.name : "?")}</td>
          ${/* 🔴 `data-sort` carries the RAW value for every cell whose display form does not sort:
                the date prints "Aug 17" (alphabetical by month name), and the times print "9:05 AM",
                which as text puts 10:00 before 9:05. An empty punch stays empty so `sortTable` treats
                it as UNKNOWN and sinks it in both directions — a missing clock-out is not midnight. */""}
          <td data-sort="${s.date}">${S.fmtDate(s.date + "T00:00:00+08:00")}</td>
          <td data-sort="${s.clock_in || ""}">${S.fmtTime(s.clock_in)}</td>
          <td data-sort="${s.clock_out || ""}">${S.fmtTime(s.clock_out)}</td>
          <td>${s.total_work_hours}h</td>
          <td>${S.statusPill(s.status)}</td>
          <td class="sub" style="max-width:220px">${S.esc(s.handover_note || "—")}</td>
          ${canEditRecords ? `<td style="text-align:right"><button class="btn sm ghost" data-edit="${i}">Edit</button></td>` : ""}</tr>`).join("") : `<tr><td colspan="${cols}"><div class="empty">No records for this range.</div></td></tr>`}</tbody></table></div>`;
      if (canEditRecords) S.qsa("#sum-table [data-edit]").forEach((b) => b.onclick = () => openEdit(rows[+b.dataset.edit], load));
      // 🔴 Sorting REORDERS the DOM rows, but `data-edit` is an INDEX into `rows` — which does not move.
      // That is why the handler above reads `rows[+b.dataset.edit]` rather than the row's position, and
      // why sorting cannot desync Edit from the record it opens. Don't switch it to a row index.
      if (rows.length) S.sortTable(S.qs("#sum-table table"));
    };
    ["f-from", "f-to", "f-team"].forEach((id) => S.qs("#" + id).onchange = load);
    load();
  }

  // Super Admin: correct a day's punches / status directly.
  function openEdit(s, refresh) {
    const m = S.modal({
      title: `Edit attendance · ${S.esc(s.user ? s.user.name : "")} · ${S.fmtDate(s.date + "T00:00:00+08:00")}`,
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

  async function renderMine() {
    const d = await S.api("/api/attendance/my");
    const t = d.today;
    tabc.innerHTML = `<div class="card pad" style="margin-bottom:16px">
        <div class="section-label">Today</div>
        <div class="row" style="margin-top:8px;gap:14px"><span class="pill ${t.state === "in" ? "green" : t.state === "on_break" ? "amber" : t.state === "out" ? "grey" : "grey"}">${t.state === "none" ? "Not clocked in" : t.state === "in" ? "Clocked in" : t.state === "on_break" ? "On break" : "Clocked out"}</span>
        <span class="sub">Punch at the kiosk. Actions available: ${t.valid_actions.length ? t.valid_actions.map((a) => a.replace("_", " ")).join(", ") : "none"}</span></div>
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
        <div class="row" style="gap:10px"><label class="field" style="flex:1"><span>Old value</span><input id="r-old" placeholder="e.g. 8h"></label>
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

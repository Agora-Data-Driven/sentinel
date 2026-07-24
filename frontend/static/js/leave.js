window.pageInit = async (S) => {
  const view = S.view();
  const types = await S.api("/api/leave/types");

  // Approvals moved to the unified /approvals inbox — this page is now just personal leave.
  view.innerHTML = `<div class="pagehead"><div><h2>Leave</h2><div class="lead">Your balances and requests. Approvals live in the Approvals inbox.</div></div>
      <button class="btn primary" id="req">${S.ICON.plus}Request leave</button></div>
    <div id="tabc"></div>`;
  S.qs("#req").onclick = requestForm;

  async function renderMine() {
    const [balances, mine] = await Promise.all([S.api("/api/leave/balance"), S.api("/api/leave/my")]);
    S.qs("#tabc").innerHTML = `
      <div class="section-label">Balances · ${new Date().getFullYear()}</div>
      <div class="kpis" style="margin:10px 0 20px">${balances.map((b) => `
        <div class="kpi"><div class="k-label">${S.esc(b.leave_type)}</div>
          <div class="k-val">${b.unlimited ? "∞" : b.remaining}</div>
          <div class="k-sub">${b.unlimited ? "unlimited · " + b.used + " used" : b.used + " used"}</div></div>`).join("")}</div>
      <div class="card"><div class="card-head"><h3>My requests</h3></div><div class="card-body">
        ${mine.length ? `<div class="table-wrap" style="border:none"><table><thead><tr><th>Type</th><th>Dates</th><th>Days</th><th>Reason</th><th>Status</th></tr></thead>
          <tbody>${mine.map((r) => `<tr><td>${S.esc(r.leave_type)}</td>
            <td>${S.fmtDate(r.start_date + "T00:00:00+08:00")} – ${S.fmtDate(r.end_date + "T00:00:00+08:00")}</td>
            <td>${r.total_days}</td><td class="sub">${S.esc(r.reason)}</td><td>${S.statusPill(r.status)}</td></tr>`).join("")}</tbody></table></div>`
          : '<div class="empty">No leave requests yet.</div>'}</div></div>`;
  }

  function requestForm() {
    const today = new Date().toISOString().slice(0, 10);
    const m = S.modal({
      title: "Request leave",
      body: `<label class="field"><span>Type</span><select id="l-type">${types.map((t) => `<option value="${t.id}">${S.esc(t.name)}${t.annual_balance >= 0 ? " (" + t.annual_balance + "d/yr)" : " (unlimited)"}</option>`).join("")}</select></label>
        <div class="row" style="gap:10px"><label class="field" style="flex:1"><span>Start</span><input type="date" id="l-start" value="${today}"></label>
        <label class="field" style="flex:1"><span>End</span><input type="date" id="l-end" value="${today}"></label></div>
        <label class="field"><span>Reason</span><textarea id="l-reason" placeholder="Reason for leave…"></textarea></label>`,
      footer: `<button class="btn ghost" id="l-cancel">Cancel</button><button class="btn primary" id="l-submit">Submit</button>`,
    });
    S.qs("#l-cancel").onclick = m.close;
    S.qs("#l-submit").onclick = async () => {
      try {
        await S.api("/api/leave/request", { method: "POST", body: {
          leave_type_id: Number(S.qs("#l-type").value), start_date: S.qs("#l-start").value,
          end_date: S.qs("#l-end").value, reason: S.qs("#l-reason").value } });
        S.toast("Leave request submitted", "ok"); m.close();
        renderMine();
      } catch (e) { S.toast(e.detail, "err"); }
    };
  }

  renderMine();
};

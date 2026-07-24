/* Payroll & Accounting — Super Admin ONLY.
   Reads /api/payroll?period=YYYY-MM (net pay computed from attendance + overtime + leave), lets the
   Super Admin set each person's monthly salary and a per-period bonus/deduction, finalize a month,
   and export the sheet to CSV. Everything is gated server-side too — this page just draws it. */
window.pageInit = async (S) => {
  const view = S.view();
  if (S.user.role !== "super_admin") {
    view.innerHTML = `<div class="empty card pad" style="margin-top:30px">Payroll is restricted to Super Admins.</div>`;
    return;
  }

  const peso = (n) => "₱" + Number(n || 0).toLocaleString("en-PH", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const nowPeriod = new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Manila" }).slice(0, 7);
  const monthLabel = (p) => { const [y, m] = p.split("-"); return new Date(y, m - 1, 1).toLocaleDateString("en-PH", { month: "long", year: "numeric" }); };
  let period = nowPeriod;
  let data = null;

  view.innerHTML = `
    <div class="pagehead"><div>
      <h2>Payroll &amp; Accounting</h2>
      <div class="lead">Net pay computed from salary, attendance and leave. Adjust salaries and bonuses, then finalize the month.</div>
    </div></div>

    <div class="row between wrap" style="gap:12px;margin-bottom:16px">
      <label class="field" style="max-width:220px;margin:0">
        <span>Pay period</span>
        <input type="month" id="pr-month" value="${period}" max="${nowPeriod}">
      </label>
      <div class="row" style="gap:8px;align-items:flex-end">
        <a class="btn ghost" id="pr-csv" download>${S.ICON.download}Export CSV</a>
      </div>
    </div>

    <div id="pr-stats" class="pr-stats" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:18px"></div>
    <div id="pr-body"></div>`;

  // Scoped styling for the stat cards + net-pay emphasis (theme-aware via CSS vars).
  const style = document.createElement("style");
  style.textContent = `
    .pr-stat{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:14px 16px}
    .pr-stat .k{font-size:12px;color:var(--muted);font-weight:600;letter-spacing:.02em}
    .pr-stat .v{font-size:20px;font-weight:800;margin-top:4px;letter-spacing:-.01em}
    .pr-stat.net{background:var(--grad-green);border:none;color:#fff;box-shadow:var(--glow-green)}
    .pr-stat.net .k,.pr-stat.net .v{color:#fff}
    td.num,th.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
    .pr-net{font-weight:800}
    .lock{opacity:.6}`;
  view.appendChild(style);

  const monthEl = S.qs("#pr-month");
  monthEl.onchange = () => { period = monthEl.value || nowPeriod; load(); };

  function syncCsv() {
    const a = S.qs("#pr-csv");
    a.href = `/api/payroll?period=${encodeURIComponent(period)}&export=csv`;
  }

  function renderStats(t) {
    S.qs("#pr-stats").innerHTML = `
      <div class="pr-stat"><div class="k">Base salaries</div><div class="v">${peso(t.base)}</div></div>
      <div class="pr-stat"><div class="k">Bonuses</div><div class="v">${peso(t.bonus)}</div></div>
      <div class="pr-stat"><div class="k">Deductions</div><div class="v">${peso(t.deductions)}</div></div>
      <div class="pr-stat net"><div class="k">Net payout · ${S.esc(monthLabel(period))}</div><div class="v">${peso(t.net)}</div></div>`;
  }

  function renderTable(rows, workingDays) {
    const body = S.qs("#pr-body");
    if (!rows.length) { body.innerHTML = `<div class="empty">No active employees to pay.</div>`; return; }
    body.innerHTML = `
      <div class="lead" style="margin-bottom:8px">${workingDays} working days this month · unpaid leave and absences are deducted at the daily rate.</div>
      <div class="table-wrap"><table>
        <thead><tr>
          <th>Employee</th>
          <th class="num">Monthly salary</th>
          <th class="num">Present</th>
          <th class="num">Absent</th>
          <th class="num">Unpaid</th>
          <th class="num">Bonus</th>
          <th class="num">Deductions</th>
          <th class="num">Net pay</th>
          <th style="text-align:right">Actions</th>
        </tr></thead>
        <tbody>${rows.map((r) => {
          const ded = (r.deduction || 0) + (r.absence_deduction || 0);
          return `<tr class="${r.finalized ? "lock" : ""}">
            <td>${S.avatar(r)}<div style="display:inline-block;vertical-align:middle;margin-left:8px">
              <div style="font-weight:600">${S.esc(r.name)}${r.finalized ? ' <span class="pill green" title="Finalized, locked">Final</span>' : ""}</div>
              <div class="sub" style="font-size:12px;color:var(--muted)">${S.esc(r.email || "")}</div></div></td>
            <td class="num">${r.monthly_salary ? peso(r.monthly_salary) : '<span style="color:var(--muted)">—</span>'}</td>
            <td class="num">${r.present_days}</td>
            <td class="num">${r.absent_days || 0}</td>
            <td class="num">${r.unpaid_leave_days || 0}</td>
            <td class="num">${peso(r.bonus)}</td>
            <td class="num">${peso(ded)}</td>
            <td class="num pr-net">${peso(r.net_pay)}</td>
            <td style="text-align:right;white-space:nowrap">
              <button class="btn sm ghost" data-edit="${r.user_id}">Edit</button>
            </td></tr>`;
        }).join("")}</tbody></table></div>`;
    S.qsa("[data-edit]").forEach((b) => b.onclick = () => openEdit(rows.find((r) => r.user_id == b.dataset.edit)));
  }

  function openEdit(r) {
    const m = S.modal({
      title: `${r.name} · ${monthLabel(period)}`,
      body: `
        <label class="field"><span>Monthly salary (₱)</span>
          <input type="number" id="pr-salary" min="0" step="0.01" value="${r.monthly_salary || 0}"></label>
        <div class="row" style="gap:10px">
          <label class="field" style="flex:1"><span>Bonus (₱)</span>
            <input type="number" id="pr-bonus" min="0" step="0.01" value="${r.bonus || 0}"></label>
          <label class="field" style="flex:1"><span>Deduction (₱)</span>
            <input type="number" id="pr-ded" min="0" step="0.01" value="${r.deduction || 0}"></label>
        </div>
        <label class="field"><span>Note (optional)</span>
          <input type="text" id="pr-note" value="${S.esc(r.note || "")}" placeholder="e.g. 13th month advance, cash advance"></label>
        <div class="card pad" style="background:var(--canvas);font-size:13px">
          <div class="row between"><span>Auto deduction (absences + unpaid leave)</span><strong>${peso(r.absence_deduction)}</strong></div>
        </div>
        <label class="chip" style="cursor:pointer;margin-top:12px;display:inline-flex;align-items:center;gap:8px">
          <input type="checkbox" id="pr-final" style="width:auto" ${r.finalized ? "checked" : ""}> Mark this month finalized (locks the row)</label>`,
      footer: `<button class="btn ghost" id="pr-cancel">Cancel</button><button class="btn primary" id="pr-save">Save</button>`,
    });
    S.qs("#pr-cancel").onclick = m.close;
    S.qs("#pr-save").onclick = async () => {
      const salary = Number(S.qs("#pr-salary").value || 0);
      const bonus = Number(S.qs("#pr-bonus").value || 0);
      const deduction = Number(S.qs("#pr-ded").value || 0);
      const note = S.qs("#pr-note").value.trim() || null;
      const finalized = S.qs("#pr-final").checked;
      try {
        // Unlock first so the adjust write is never blocked by a finalized period.
        if (r.finalized) await S.api(`/api/payroll/finalize/${r.user_id}`, { method: "POST", body: { period, finalized: false } });
        if (salary !== (r.monthly_salary || 0)) await S.api(`/api/payroll/salary/${r.user_id}`, { method: "PUT", body: { monthly_salary: salary } });
        await S.api(`/api/payroll/adjust/${r.user_id}`, { method: "POST", body: { period, bonus, deduction, note } });
        if (finalized) await S.api(`/api/payroll/finalize/${r.user_id}`, { method: "POST", body: { period, finalized: true } });
        S.toast("Payroll updated", "ok");
        m.close(); load();
      } catch (e) { S.toast(e.detail || "Couldn't save", "err"); }
    };
  }

  async function load() {
    syncCsv();
    const body = S.qs("#pr-body");
    body.innerHTML = '<div class="skeleton" style="height:200px"></div>';
    try {
      data = await S.api(`/api/payroll?period=${encodeURIComponent(period)}`);
    } catch (e) {
      body.innerHTML = `<div class="empty">${S.esc(e.detail || "Failed to load payroll")}</div>`;
      return;
    }
    renderStats(data.totals);
    renderTable(data.rows, data.working_days);
  }

  load();
};

window.pageInit = async (S) => {
  const view = S.view();
  const role = S.user.role;
  const admin = S.can("admin");
  const teams = await S.api("/api/teams");

  const ALL = [
    { key: "attendance", label: "Attendance", access: () => admin },
    { key: "gym", label: "Gym Compliance", access: () => admin },
    { key: "tasks", label: "Task Summary", access: () => true },
    { key: "team", label: "Team Performance", access: () => admin || role === "account_manager" },
    { key: "leave", label: "Leave Summary", access: () => admin },
    { key: "overdue", label: "Overdue Tasks", access: () => admin || role === "team_lead" },
  ].filter((r) => r.access());

  const iso = (d) => d.toISOString().slice(0, 10);
  const from = new Date(Date.now() - 30 * 864e5);
  let current = ALL[0].key;

  view.innerHTML = `<div class="pagehead"><div><h2>Reports</h2><div class="lead">View and export operational data as CSV.</div></div></div>
    <div class="tabs" id="rtabs">${ALL.map((r, i) => `<button class="${i ? "" : "active"}" data-r="${r.key}">${r.label}</button>`).join("")}</div>
    <div class="filters">
      <label>From <input type="date" id="r-from" value="${iso(from)}"></label>
      <label>To <input type="date" id="r-to" value="${iso(new Date())}"></label>
      <select id="r-team"><option value="">All teams</option>${teams.map((t) => `<option value="${t.id}">${S.esc(t.name)}</option>`).join("")}</select>
      <span class="grow"></span>
      <a class="btn success" id="r-csv">${S.ICON.download}Export CSV</a>
    </div>
    <div id="r-out"></div>`;

  S.qsa("#rtabs button").forEach((b) => b.onclick = () => {
    S.qsa("#rtabs button").forEach((x) => x.classList.remove("active")); b.classList.add("active"); current = b.dataset.r; load();
  });
  ["r-from", "r-to", "r-team"].forEach((id) => S.qs("#" + id).onchange = load);

  function qstr() {
    const q = new URLSearchParams({ from: S.qs("#r-from").value, to: S.qs("#r-to").value });
    if (S.qs("#r-team").value) q.set("team_id", S.qs("#r-team").value);
    return q;
  }

  async function load() {
    S.qs("#r-out").innerHTML = '<div class="skeleton" style="height:220px"></div>';
    S.qs("#r-csv").href = `/api/reports/${current}?${qstr()}&export=csv`;
    try {
      const d = await S.api(`/api/reports/${current}?${qstr()}`);
      S.qs("#r-out").innerHTML = `<div class="row between" style="margin-bottom:10px"><span class="section-label">${d.count} rows</span></div>
        <div class="table-wrap"><table><thead><tr>${d.columns.map((c) => `<th>${S.esc(c)}</th>`).join("")}</tr></thead>
        <tbody>${d.rows.length ? d.rows.map((r) => `<tr>${r.map((c) => `<td>${S.esc(c)}</td>`).join("")}</tr>`).join("") : `<tr><td colspan="${d.columns.length}"><div class="empty">No data for this range.</div></td></tr>`}</tbody></table></div>`;
    } catch (e) {
      S.loadErr("#r-out", e, load);
    }
  }
  load();
};

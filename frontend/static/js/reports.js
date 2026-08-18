window.pageInit = async (S) => {
  const view = S.view();
  const teams = await S.api("/api/teams");

  const ALL = [
    // Each report follows its own CAPABILITY (capabilities.REPORT_CAPS), so a Super Admin moving
    // one in Admin -> Permissions shows/hides the tab to match. The server enforces the same key.
    { key: "attendance", label: "Attendance", access: () => S.hasCap("reports.attendance") },
    { key: "gym", label: "Gym Compliance", access: () => S.hasCap("reports.gym") },
    { key: "tasks", label: "Task Summary", access: () => S.hasCap("reports.tasks") },
    { key: "team", label: "Team Performance", access: () => S.hasCap("reports.team") },
    { key: "leave", label: "Leave Summary", access: () => S.hasCap("reports.leave") },
    { key: "overdue", label: "Overdue Tasks", access: () => S.hasCap("reports.overdue") },
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
      <a class="btn success" id="r-csv" download>${S.ICON.download}Export CSV</a>
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
    const a = S.qs("#r-csv");
    // 🔴 AN INVERTED RANGE IS A TYPO, AND IT USED TO READ AS A FINDING. From > To makes the server
    // answer zero rows, which rendered "No data for this range." — a sentence that describes the
    // DATA when the problem is the question. Somebody reads that as "nobody clocked in all month".
    // Checked here rather than on each input's change so it also guards the tab switch and the very
    // first load, and so the export cannot be armed with a range the table refused to run.
    const f = S.qs("#r-from").value, t = S.qs("#r-to").value;
    if (f && t && f > t) {
      // Lexicographic compare is correct and deliberate: an <input type="date"> value is always
      // ISO `YYYY-MM-DD`, which sorts chronologically as text — no Date parsing, no timezone.
      S.qs("#r-out").innerHTML = `<div class="notice warn"><b>That date range is backwards.</b>
        “From” (${S.esc(f)}) is after “To” (${S.esc(t)}), so there is nothing to report. Swap them.</div>`;
      // A control must never be able to only fail: disable the export rather than let it hand back an
      // empty CSV that looks like a real answer.
      a.removeAttribute("href");
      a.classList.add("disabled");
      a.title = "Fix the date range first";
      return;
    }
    a.classList.remove("disabled");
    a.removeAttribute("title");
    S.qs("#r-out").innerHTML = '<div class="skeleton" style="height:220px"></div>';
    // 🔴 THE `download` ATTRIBUTE IS WHAT STOPS THIS BEING A NAVIGATION (added 2026-08-17; the anchor
    // in the markup above carries it too, so it is never armed without one). Without it the browser
    // LEAVES the app to open the URL, so a 401/403/500 replaced the whole page with a raw JSON error
    // body — losing the report, the tab and the date range the user had built, with the only way back
    // being the Back button. With it the response is saved instead, so a failure costs one junk file
    // rather than the session. payroll.js has always done this; Reports was the one that did not.
    // The explicit filename beats the server's Content-Disposition here because there are six report
    // types x a date range each, and they all land in one Downloads folder.
    a.setAttribute("download", `sentinel-${current}-${f}-to-${t}.csv`);
    a.href = `/api/reports/${current}?${qstr()}&export=csv`;
    try {
      const d = await S.api(`/api/reports/${current}?${qstr()}`);
      render(d);
    } catch (e) {
      S.loadErr("#r-out", e, load);
    }
  }

  // 🔴 THE ROW CAP IS A REAL PERFORMANCE FIX, not tidiness (2026-08-17). This used to build EVERY row
  // returned into one string and hand it to `innerHTML`: an Attendance report is one row per person per
  // day, so a six-month range across the team is tens of thousands of `<tr>`s parsed and laid out in a
  // single synchronous go, which visibly hangs the tab. Nothing capped it and nothing said so, so a
  // slow render was indistinguishable from a hung page.
  //
  // 🔴 It caps the RENDER, never the data. Two things follow, and both are the point:
  //  • the count above the table stays the SERVER's `d.count`, so the number is always the true one;
  //  • **the CSV export is untouched** — it goes straight to the API, so "I can only see 500 rows" and
  //    "I can only export 500 rows" are never the same sentence. The notice says so, because a capped
  //    table with a silent export is exactly how somebody concludes the data is missing.
  const RENDER_CAP = 500;
  function render(d) {
    const total = d.rows.length;
    const shown = Math.min(total, RENDER_CAP);
    const rows = total > RENDER_CAP ? d.rows.slice(0, RENDER_CAP) : d.rows;
    const capped = total > RENDER_CAP
      ? `<div class="notice"><b>Showing the first ${shown.toLocaleString()} of ${total.toLocaleString()} rows</b>
           to keep the page responsive. <b>Export CSV gives you all ${total.toLocaleString()}</b> —
           or narrow the date range.</div>`
      : "";
    const body = rows.length
      ? rows.map((r) => `<tr>${r.map((c) => `<td>${S.esc(c)}</td>`).join("")}</tr>`).join("")
      : `<tr><td colspan="${d.columns.length}"><div class="empty">No data for this range.</div></td></tr>`;
    S.qs("#r-out").innerHTML = `<div class="row between" style="margin-bottom:10px">
        <span class="section-label">${d.count.toLocaleString()} rows</span></div>
      ${capped}
      <div class="table-wrap tall"><table><thead><tr>${
        // Every column is sortable: a report's shape is server-driven (`d.columns`), so there is no
        // per-column knowledge to gate this on — and `sortTable` decides numeric-vs-text per cell.
        d.columns.map((c) => `<th class="sortable">${S.esc(c)}</th>`).join("")
      }</tr></thead>
      <tbody>${body}</tbody></table></div>`;
    if (rows.length) S.sortTable(S.qs("#r-out table"));
  }
  load();
};

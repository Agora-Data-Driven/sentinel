window.pageInit = async (S) => {
  const view = S.view();
  const d = await S.api("/api/admin/settings");
  const s = d.settings, desc = d.descriptions;

  // Shift times & breaks live in Manage → Shift Templates now (one is the ★ company default), so
  // they're intentionally not here. This card holds only the company-wide rules.
  const FIELDS = [
    ["late_grace", "number"], ["gym_required_hours", "number"], ["work_days", "text"],
    ["timezone", "text"],
  ];
  const nice = (k) => k.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

  view.innerHTML = `<div class="pagehead"><div><h2>Settings</h2><div class="lead">System configuration. Every change is written to the audit log.</div></div></div>
    <div class="grid" style="grid-template-columns:1fr;gap:18px">
      <div class="card"><div class="card-head"><div><h3>Work & attendance rules</h3>
          <div class="sub" style="font-size:12px;margin-top:2px">Company-wide rules. Shift times &amp; breaks live in <b>Manage → Shift Templates</b> (one is the ★ company default). Late grace is the default for every shift — a template can override it; work days &amp; timezone apply everywhere.</div></div>
          <button class="btn primary sm" id="save">Save changes</button></div>
        <div class="card-body"><div class="grid" style="grid-template-columns:1fr 1fr;gap:14px">
          ${FIELDS.map(([k, t]) => `<label class="field"><span title="${S.esc(desc[k] || "")}">${nice(k)}</span>
            ${t === "bool"
              ? `<select data-k="${k}"><option value="true" ${s[k] === "true" ? "selected" : ""}>Yes</option><option value="false" ${s[k] !== "true" ? "selected" : ""}>No</option></select>`
              : `<input data-k="${k}" type="${t === "number" ? "number" : t === "time" ? "time" : "text"}" value="${S.esc(s[k] || "")}">`}
            <small class="muted">${S.esc(desc[k] || "")}</small></label>`).join("")}
        </div></div></div>

      <div class="card"><div class="card-head"><h3>Broadcast announcement</h3></div>
        <div class="card-body">
          <label class="field"><span>Title</span><input id="a-title" placeholder="e.g. Office closed on July 12"></label>
          <label class="field"><span>Message</span><textarea id="a-body" placeholder="Details…"></textarea></label>
          <button class="btn success" id="a-send">${S.ICON.bell}Send to everyone</button>
        </div></div>

      <div class="card"><div class="card-head"><h3>Audit log</h3>
        <select id="a-table" style="width:auto"><option value="">All tables</option>${["tasks", "users", "leave_requests", "attendance_requests", "system_settings", "notifications", "atrium_approvals"].map((t) => `<option>${t}</option>`).join("")}</select></div>
        <div class="card-body" id="audit"></div></div>
    </div>`;

  S.qs("#save").onclick = async () => {
    const payload = {};
    S.qsa("[data-k]").forEach((el) => payload[el.dataset.k] = el.value);
    try { await S.api("/api/admin/settings", { method: "PATCH", body: { settings: payload } }); S.toast("Settings saved", "ok"); }
    catch (e) { S.toast(e.detail, "err"); }
  };

  S.qs("#a-send").onclick = async () => {
    const title = S.qs("#a-title").value.trim(); if (!title) { S.toast("Add a title", "err"); return; }
    try { const r = await S.api("/api/admin/announce", { method: "POST", body: { title, body: S.qs("#a-body").value } });
      S.toast(`Sent to ${r.recipients} people`, "ok"); S.qs("#a-title").value = ""; S.qs("#a-body").value = ""; loadAudit(); }
    catch (e) { S.toast(e.detail, "err"); }
  };

  S.qs("#a-table").onchange = loadAudit;
  async function loadAudit() {
    const q = new URLSearchParams(); if (S.qs("#a-table").value) q.set("table", S.qs("#a-table").value);
    const logs = await S.api("/api/audit-logs?" + q);
    S.qs("#audit").innerHTML = logs.length ? `<div class="table-wrap" style="border:none"><table>
      <thead><tr><th>When</th><th>Actor</th><th>Table</th><th>Action</th><th>Record</th></tr></thead>
      <tbody>${logs.map((a) => `<tr><td class="sub">${S.timeAgo(a.created_at)}</td>
        <td>${a.actor ? S.esc(a.actor.name) : "System"}</td><td>${S.esc(a.table)}</td>
        <td><span class="pill grey">${S.esc(a.action)}</span></td><td class="sub">${S.esc(a.record_id || "—")}</td></tr>`).join("")}</tbody></table></div>`
      : '<div class="empty">No audit entries.</div>';
  }
  loadAudit();
};

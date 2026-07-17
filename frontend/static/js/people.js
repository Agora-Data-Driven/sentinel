window.pageInit = async (S) => {
  const view = S.view();
  const isSA = S.user.role === "super_admin";
  const isAdmin = S.can("admin");
  const [teams, vocab] = await Promise.all([S.api("/api/teams"), S.api("/api/vocab")]);
  const teamName = Object.fromEntries(teams.map((t) => [t.id, t.name]));
  let filters = { search: "", team: "", role: "", status: "" };

  view.innerHTML = `<div class="pagehead"><div><h2>People</h2><div class="lead">Employee directory — profiles, QR badges, attendance & gym at a glance.</div></div>
      ${isSA ? `<button class="btn primary" id="add">${S.ICON.plus}Add Employee</button>` : ""}</div>
    <div class="filters">
      <div class="grow" style="position:relative"><input id="f-search" placeholder="Search by name, email, department…"></div>
      <select id="f-team"><option value="">All Departments</option>${teams.map((t) => `<option value="${t.id}">${S.esc(t.name)}</option>`).join("")}</select>
      <select id="f-role"><option value="">All Roles</option>${vocab.roles.map((r) => `<option value="${r.value}">${S.esc(r.label)}</option>`).join("")}</select>
      <select id="f-status"><option value="">All Status</option><option>Active</option><option>On Leave</option><option>Inactive</option></select>
    </div>
    <div id="tbl"></div>`;

  const deb = (fn, ms) => { let h; return (...a) => { clearTimeout(h); h = setTimeout(() => fn(...a), ms); }; };
  S.qs("#f-search").oninput = deb((e) => { filters.search = e.target.value; load(); }, 250);
  S.qs("#f-team").onchange = (e) => { filters.team = e.target.value; load(); };
  S.qs("#f-role").onchange = (e) => { filters.role = e.target.value; load(); };
  S.qs("#f-status").onchange = (e) => { filters.status = e.target.value; load(); };
  if (isSA) S.qs("#add").onclick = addForm;

  async function load() {
    const q = new URLSearchParams();
    if (filters.search) q.set("search", filters.search);
    if (filters.team) q.set("team", filters.team);
    if (filters.role) q.set("role", filters.role);
    if (filters.status) q.set("status", filters.status);
    S.qs("#tbl").innerHTML = `<div class="card pad">${S.skeleton({ rows: 7 })}</div>`;
    const rows = await S.api("/api/people?" + q);
    S.qs("#tbl").innerHTML = `<div class="table-wrap"><table>
      <thead><tr><th>Name</th><th>Email</th><th>Department</th><th>Role</th><th>Status</th><th></th></tr></thead>
      <tbody>${rows.length ? rows.map((u) => `<tr>
        <td class="t-name">${S.avatar(u, "sm")}<strong>${S.esc(u.name)}</strong></td>
        <td class="sub">${S.esc(u.email)}</td>
        <td>${S.esc(u.team_name || "—")}</td>
        <td>${S.esc(u.role_label)}</td>
        <td>${S.statusPill(u.status)}</td>
        <td><button class="btn sm ghost" data-view="${u.id}">View</button></td></tr>`).join("") : '<tr><td colspan="6"><div class="empty">No people match.</div></td></tr>'}</tbody></table></div>`;
    S.qsa("[data-view]").forEach((b) => b.onclick = () => profile(b.dataset.view));
  }

  async function profile(id) {
    const d = await S.api("/api/people/" + id);
    const p = d.profile;
    const body = `<div class="grid" style="grid-template-columns:1fr 1.2fr;gap:22px">
      <div style="text-align:center">
        ${S.avatar(p, "lg")}
        <h2 style="margin:12px 0 2px">${S.esc(p.name)}</h2>
        <div>${S.statusPill(p.status)}</div>
        <div class="stack" style="margin-top:14px;text-align:left">
          ${row("Email", p.email)}${row("Phone", p.phone)}${row("Role", p.role_label)}
          ${row("Department", p.team_name)}${row("Hired", p.hired_date ? S.fmtDateFull(p.hired_date + "T00:00:00+08:00") : "—")}
        </div>
        ${isAdmin ? `<div style="margin-top:16px"><div class="section-label">Badge QR</div>
          <img src="/api/people/${id}/qr" alt="QR" style="width:150px;height:150px;margin-top:8px;border:1px solid var(--line);border-radius:10px;padding:6px;background:#fff">
          <div><a class="btn sm ghost" href="/api/people/${id}/qr" download="badge-${id}.png" style="margin-top:8px">${S.ICON.download}Download badge</a></div></div>` : ""}
      </div>
      <div>
        <div class="section-label">Attendance · this month</div>
        <div class="kpis" style="margin:8px 0 16px;grid-template-columns:repeat(3,1fr)">
          <div class="kpi"><div class="k-label">On time</div><div class="k-val">${d.attendance.on_time}</div></div>
          <div class="kpi warn"><div class="k-label">Late</div><div class="k-val">${d.attendance.late}</div></div>
          <div class="kpi"><div class="k-label">Hours</div><div class="k-val">${d.attendance.total_hours}</div></div>
        </div>
        <div class="section-label">Gym · this week</div>
        <div class="row" style="margin:8px 0 16px">${d.gym.recent.length ? d.gym.recent.map((g) => `<span class="pill day ${g.day_type}" title="${g.status}">${g.day_type}</span>`).join("") : '<span class="muted">No sessions</span>'} <span class="chip">${d.gym.completed} completed</span></div>
        <div class="section-label">Current tasks</div>
        <div class="stack" style="margin:8px 0 16px">${d.tasks.length ? d.tasks.map((t) => `<div class="row between"><span>${S.esc(t.title)}</span><span class="pill grey">${S.esc(t.status)}</span></div>`).join("") : '<span class="muted">No open tasks</span>'}</div>
        <div class="section-label">Leave balance</div>
        <div class="stack" style="margin-top:8px">${d.leave_balances.map((b) => `<div class="row between"><span>${S.esc(b.leave_type)}</span><strong>${b.unlimited ? "∞" : b.remaining + " left"}</strong></div>`).join("")}</div>
      </div></div>`;
    let footer = "";
    if (isSA) footer += `<button class="btn danger" id="p-delete">Remove</button>`;
    if (isAdmin) footer += `<button class="btn ghost" id="p-edit">Edit</button>`;
    if (isAdmin) footer += `<button class="btn ghost" id="p-regen">Reissue QR</button>`;
    footer += `<button class="btn primary" id="p-close">Close</button>`;
    const m = S.modal({ title: "Profile", body, footer, wide: true });
    S.qs("#p-close").onclick = m.close;
    if (isAdmin && S.qs("#p-edit")) S.qs("#p-edit").onclick = () => { m.close(); addForm(p); };
    if (isAdmin && S.qs("#p-regen")) S.qs("#p-regen").onclick = async () => {
      if (!confirm(`Reissue ${p.name}'s QR badge? Their current badge will stop working.`)) return;
      try {
        await S.api(`/api/people/${id}/qr/regenerate`, { method: "POST" });
        S.toast("New QR badge issued", "ok");
        const img = S.qs(`img[alt="QR"]`); if (img) img.src = `/api/people/${id}/qr?t=` + Date.now();
      } catch (e) { S.toast(e.detail, "err"); }
    };
    if (isSA && S.qs("#p-delete")) S.qs("#p-delete").onclick = async () => {
      if (Number(id) === S.user.id) { S.toast("You can't remove your own account", "err"); return; }
      if (!confirm(`Permanently remove ${p.name}? Their attendance, gym, leave and notifications will be deleted. This can't be undone.\n\n(To keep their history instead, use Edit and set status to Inactive.)`)) return;
      try { await S.api(`/api/people/${id}`, { method: "DELETE" }); S.toast(`${p.name} removed`, "ok"); m.close(); load(); }
      catch (e) { S.toast(e.detail, "err"); }
    };
  }
  const row = (l, v) => `<div class="row between"><span class="sub">${l}</span><strong>${S.esc(v || "—")}</strong></div>`;

  function addForm(existing) {
    const e = existing || {};
    const editing = !!existing;
    const m = S.modal({
      title: editing ? "Edit employee" : "Add employee",
      body: `<div class="grid" style="grid-template-columns:1fr 1fr;gap:14px">
        <label class="field"><span>Name</span><input id="e-name" value="${S.esc(e.name || "")}"></label>
        <label class="field"><span>Email</span><input id="e-email" value="${S.esc(e.email || "")}"></label>
        <label class="field"><span>Role</span><select id="e-role">${vocab.roles.map((r) => `<option value="${r.value}" ${r.value === e.role ? "selected" : ""}>${S.esc(r.label)}</option>`).join("")}</select></label>
        <label class="field"><span>Department</span><select id="e-team"><option value="">—</option>${teams.map((t) => `<option value="${t.id}" ${t.id === e.team_id ? "selected" : ""}>${S.esc(t.name)}</option>`).join("")}</select></label>
        <label class="field"><span>Phone</span><input id="e-phone" value="${S.esc(e.phone || "")}"></label>
        <label class="field"><span>Hired date</span><input type="date" id="e-hired" value="${e.hired_date || ""}"></label>
        <label class="field"><span>Shift start (override)</span><input id="e-ss" placeholder="08:00" value="${S.esc(e.shift_start || "")}"></label>
        <label class="field"><span>Shift end (override)</span><input id="e-se" placeholder="17:00" value="${S.esc(e.shift_end || "")}"></label>
        ${editing ? `<label class="field"><span>Status</span><select id="e-active"><option value="true" ${e.is_active !== false ? "selected" : ""}>Active</option><option value="false" ${e.is_active === false ? "selected" : ""}>Inactive</option></select></label>` : ""}
      </div>`,
      footer: `<button class="btn ghost" id="e-cancel">Cancel</button><button class="btn primary" id="e-save">${editing ? "Save" : "Create"}</button>`,
    });
    S.qs("#e-cancel").onclick = m.close;
    S.qs("#e-save").onclick = async () => {
      const payload = {
        name: v("e-name"), email: v("e-email"), role: S.qs("#e-role").value,
        team_id: S.qs("#e-team").value ? Number(S.qs("#e-team").value) : null,
        phone: v("e-phone"), hired_date: v("e-hired") || null, shift_start: v("e-ss"), shift_end: v("e-se"),
      };
      if (editing) payload.is_active = S.qs("#e-active").value === "true";
      try {
        if (editing) await S.api("/api/people/" + existing.id, { method: "PATCH", body: payload });
        else await S.api("/api/people", { method: "POST", body: payload });
        S.toast(editing ? "Employee updated" : "Employee added", "ok"); m.close(); load();
      } catch (err) { S.toast(err.detail, "err"); }
    };
    function v(id) { return S.qs("#" + id).value || null; }
  }

  await load();
  // Deep-link: /people?open=<id> (from the command palette / a notification).
  const open = new URLSearchParams(location.search).get("open");
  if (open) profile(open);
};

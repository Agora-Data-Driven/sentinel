window.pageInit = async (S) => {
  const view = S.view();
  const isAdmin = S.can("admin");  // gates the QR badge view (managers+); all edits now live in Manage
  const [teams, vocab] = await Promise.all([S.api("/api/teams"), S.api("/api/vocab")]);
  let filters = { search: "", team: "", role: "", status: "" };

  view.innerHTML = `<div class="pagehead"><div><h2>People</h2><div class="lead">Employee directory: profiles, QR badges, attendance & gym at a glance. Add or edit people in the Manage console.</div></div></div>
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
    // Anyone may change their OWN photo; admins may change anyone's.
    const canPhoto = isAdmin || (S.user && S.user.id === p.id);
    const body = `<div class="grid" style="grid-template-columns:1fr 1.2fr;gap:22px">
      <div style="text-align:center">
        <div id="pf-avatar" style="display:inline-block">${S.avatar(p, "lg")}</div>
        ${canPhoto ? `<div class="row" style="justify-content:center;gap:6px;margin-top:8px">
          <button class="btn sm ghost" id="pf-photo-btn">${S.ICON.plus}${p.profile_pic_url ? "Change photo" : "Add photo"}</button>
          ${p.profile_pic_url ? `<button class="btn sm ghost" id="pf-photo-del">Remove</button>` : ""}
          <input type="file" id="pf-photo-file" accept="image/*" hidden></div>` : ""}
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
    // Read-only directory: create / edit / delete / reissue-badge all live in the Manage console
    // (super-admin), so there's a single source of truth for employee records. Here we only view.
    const footer = `<button class="btn primary" id="p-close">Close</button>`;
    const m = S.modal({ title: "Profile", body, footer, wide: true });
    S.qs("#p-close").onclick = m.close;

    // Photo upload/remove (self or admin). Re-render the drawer avatar in place on success.
    if (canPhoto) {
      const paint = (url) => { const box = S.qs("#pf-avatar"); if (box) box.innerHTML = S.avatar({ name: p.name, profile_pic_url: url }, "lg"); };
      const fileInput = S.qs("#pf-photo-file");
      S.qs("#pf-photo-btn").onclick = () => fileInput.click();
      fileInput.onchange = async () => {
        const f = fileInput.files && fileInput.files[0];
        if (!f) return;
        try { const url = await S.uploadAvatar(p.id, f); paint(url); S.toast("Photo updated", "ok"); load(); }
        catch (e) { S.toast(e.detail || e.message || "Couldn't upload photo", "err"); }
        finally { fileInput.value = ""; }
      };
      const del = S.qs("#pf-photo-del");
      if (del) del.onclick = async () => {
        try { await S.removeAvatar(p.id); paint(null); S.toast("Photo removed", "ok"); m.close(); load(); }
        catch (e) { S.toast(e.detail || "Couldn't remove photo", "err"); }
      };
    }
  }
  const row = (l, v) => `<div class="row between"><span class="sub">${l}</span><strong>${S.esc(v || "—")}</strong></div>`;

  await load();
  // Deep-link: /people?open=<id> (from the command palette / a notification).
  const open = new URLSearchParams(location.search).get("open");
  if (open) profile(open);
};

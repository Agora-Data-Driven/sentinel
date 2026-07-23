/* Manage — Super Admin console. Config-driven CRUD for everything behind the app:
   Employees (the whole team) + the reference data other tabs' dropdowns use
   (gym exercises, clients, departments, leave types). */
window.pageInit = async (S) => {
  const view = S.view();
  if (S.user.role !== "super_admin") {
    view.innerHTML = `<div class="empty card pad" style="margin-top:30px">This console is for Super Admins only.</div>`;
    return;
  }

  // Dynamic option sources for select fields.
  const [teams, vocab] = await Promise.all([S.api("/api/teams"), S.api("/api/vocab")]);
  const OPTS = { roles: vocab.roles, teams: teams.map((t) => ({ value: t.id, label: t.name })) };

  const ENTITIES = {
    Employees: {
      api: "/api/people", singular: "employee",
      cols: [
        { k: "name", label: "Name" },
        { k: "email", label: "Email" },
        { k: "role_label", label: "Role" },
        { k: "team_name", label: "Department" },
        { k: "status", label: "Status", fmt: (v) => S.statusPill(v) },
      ],
      fields: [
        { k: "name", label: "Name", type: "text", req: true },
        { k: "email", label: "Email", type: "text", req: true },
        { k: "role", label: "Role", type: "select", optsKey: "roles" },
        { k: "team_id", label: "Department", type: "select", optsKey: "teams", allowEmpty: true, coerce: "intOrNull" },
        { k: "phone", label: "Phone", type: "text" },
        { k: "hired_date", label: "Hired date", type: "date" },
        { k: "password", label: "Password (blank = leave unchanged; they can also use Google)", type: "password", omitIfBlank: true },
      ],
      help: "Everyone in Sentinel — attendance, gym, tasks, leave. Add a person here and they're available across the whole app (they get a QR badge + code automatically). Use Badge to view/print their QR or copy the code if they lost it.",
      rowActions: [{ label: "Badge", handler: (item) => openBadge(item) }],
    },
    Exercises: {
      api: "/api/manage/exercises", singular: "exercise",
      cols: [
        { k: "name", label: "Name" },
        { k: "muscle_group", label: "Muscle group" },
        { k: "day_types", label: "Day types", fmt: (v) => (v || []).map((d) => `<span class="pill day ${d}">${d}</span>`).join(" ") },
        { k: "equipment", label: "Equipment" },
      ],
      fields: [
        { k: "name", label: "Name", type: "text", req: true },
        { k: "muscle_group", label: "Muscle group", type: "text" },
        { k: "day_types", label: "Shows under which day types", type: "multi", opts: ["Push", "Pull", "Legs", "Custom"] },
        { k: "equipment", label: "Equipment", type: "text" },
        { k: "instructions", label: "Instructions", type: "textarea" },
      ],
      help: "The exercises employees can pick in the Gym Tracker, grouped by day type.",
    },
    Clients: {
      api: "/api/manage/clients", singular: "client",
      cols: [
        { k: "name", label: "Name" },
        { k: "contact_email", label: "Contact email" },
        { k: "atrium_client_id", label: "Atrium ID" },
      ],
      fields: [
        { k: "name", label: "Name", type: "text", req: true },
        { k: "contact_email", label: "Contact email", type: "text" },
        { k: "atrium_client_id", label: "Atrium workspace ID (optional)", type: "text" },
      ],
      help: "Clients appear in the Task Board's client filter and the New Task form.",
    },
    Departments: {
      api: "/api/manage/teams", singular: "department",
      cols: [
        { k: "name", label: "Name" },
        { k: "shift_start", label: "Shift start" },
        { k: "shift_end", label: "Shift end" },
        { k: "break_duration_min", label: "Break (min)" },
      ],
      fields: [
        { k: "name", label: "Name", type: "text", req: true },
        { k: "shift_start", label: "Shift start", type: "time" },
        { k: "shift_end", label: "Shift end", type: "time" },
        { k: "break_duration_min", label: "Break duration (minutes)", type: "number" },
      ],
      help: "Departments (teams) drive the Task Board department filter, People, and each team's shift/late rules.",
    },
    "Leave Types": {
      api: "/api/manage/leave-types", singular: "leave type",
      cols: [
        { k: "name", label: "Name" },
        { k: "annual_balance", label: "Annual balance", fmt: (v) => (v < 0 ? "∞ unlimited" : v) },
        { k: "accrual_type", label: "Accrual" },
        { k: "requires_approval", label: "Approval" },
        { k: "carry_over_days", label: "Carry over" },
      ],
      fields: [
        { k: "name", label: "Name", type: "text", req: true },
        { k: "annual_balance", label: "Annual balance (days) — use -1 for unlimited", type: "number" },
        { k: "accrual_type", label: "Accrual", type: "select", opts: ["Monthly", "Yearly", "—"] },
        { k: "requires_approval", label: "Approval rule", type: "text" },
        { k: "carry_over_days", label: "Carry-over days", type: "number" },
      ],
      help: "Leave types appear in the Leave request form; changing balances affects new balances going forward.",
    },
  };

  const keys = Object.keys(ENTITIES);
  view.innerHTML = `<div class="pagehead"><div><h2>Manage</h2>
      <div class="lead">Add your team and edit everything behind the app — no developer needed.</div></div></div>
    <div class="tabs" id="mtabs">${keys.map((k, i) => `<button class="${i ? "" : "active"}" data-k="${k}">${k}</button>`).join("")}</div>
    <div id="mbody"></div>`;
  S.qsa("#mtabs button").forEach((b) => b.onclick = () => {
    S.qsa("#mtabs button").forEach((x) => x.classList.remove("active")); b.classList.add("active"); render(b.dataset.k);
  });

  function resolveOpts(f) {
    let arr = f.optsKey ? (OPTS[f.optsKey] || []) : (f.opts || []).map((o) => (typeof o === "string" ? { value: o, label: o } : o));
    if (f.allowEmpty) arr = [{ value: "", label: "—" }].concat(arr);
    return arr;
  }

  async function render(key) {
    const cfg = ENTITIES[key];
    const body = S.qs("#mbody");
    body.innerHTML = '<div class="skeleton" style="height:180px"></div>';
    let rows;
    try { rows = await S.api(cfg.api); }
    catch (e) { body.innerHTML = `<div class="empty">${S.esc(e.detail || "Failed to load")}</div>`; return; }
    body.innerHTML = `
      <div class="row between" style="margin-bottom:12px">
        <div class="lead">${cfg.help}</div>
        <button class="btn primary" id="m-add">${S.ICON.plus}Add ${cfg.singular}</button>
      </div>
      <div class="table-wrap"><table>
        <thead><tr>${cfg.cols.map((c) => `<th>${c.label}</th>`).join("")}<th style="text-align:right">Actions</th></tr></thead>
        <tbody>${rows.length ? rows.map((r) => `<tr>
          ${cfg.cols.map((c) => `<td>${c.fmt ? c.fmt(r[c.k]) : S.esc(r[c.k] == null || r[c.k] === "" ? "—" : r[c.k])}</td>`).join("")}
          <td style="text-align:right;white-space:nowrap">
            ${(cfg.rowActions || []).map((a, ai) => `<button class="btn sm ghost" data-rowact="${ai}" data-id="${r.id}">${S.esc(a.label)}</button>`).join("")}
            <button class="btn sm ghost" data-edit="${r.id}">Edit</button>
            <button class="btn sm danger" data-del="${r.id}">Delete</button></td></tr>`).join("")
        : `<tr><td colspan="${cfg.cols.length + 1}"><div class="empty">No ${cfg.singular}s yet. Add one.</div></td></tr>`}</tbody></table></div>`;

    S.qs("#m-add").onclick = () => openForm(key, null);
    S.qsa("[data-edit]").forEach((b) => b.onclick = () => openForm(key, rows.find((r) => r.id == b.dataset.edit)));
    S.qsa("[data-del]").forEach((b) => b.onclick = () => del(key, rows.find((r) => r.id == b.dataset.del)));
    S.qsa("[data-rowact]").forEach((b) => b.onclick = () => cfg.rowActions[+b.dataset.rowact].handler(rows.find((r) => r.id == b.dataset.id)));
  }

  // Employee badge: view/print the QR + copy the typeable code, or reissue if lost.
  async function openBadge(item) {
    const m = S.modal({ title: `${item.name} — attendance badge`, body: `<div id="bg" style="text-align:center;min-height:120px">Loading…</div>` });
    const load = async () => {
      try {
        const b = await S.api(`/api/people/${item.id}/badge`);
        S.qs("#bg").innerHTML = `
          <img alt="QR badge" src="/api/people/${item.id}/qr?t=${Date.now()}" style="width:190px;height:190px;border:1px solid var(--line);border-radius:12px;padding:8px;background:#fff">
          <label class="field" style="margin-top:12px;text-align:left"><span>Badge code (type this if they can't scan the QR)</span>
            <div class="row" style="gap:6px"><input id="bg-code" readonly value="${S.esc(b.code)}" style="flex:1;font-family:monospace">
              <button class="btn ghost" id="bg-copy">Copy</button></div></label>
          <div class="row" style="justify-content:center;gap:8px;margin-top:6px">
            <a class="btn ghost" href="/api/people/${item.id}/qr" download="badge-${item.id}.png">${S.ICON.download}Download / print</a>
            <button class="btn primary" id="bg-regen">Reissue new code</button></div>
          <div class="muted" style="font-size:12px;margin-top:8px">Print the QR or send it to their phone. If they lose it, copy the code or reissue a new one.</div>`;
        S.qs("#bg-copy").onclick = async () => {
          const inp = S.qs("#bg-code");
          try { await navigator.clipboard.writeText(inp.value); S.toast("Code copied", "ok"); }
          catch (e) { inp.select(); document.execCommand("copy"); S.toast("Code copied", "ok"); }
        };
        S.qs("#bg-regen").onclick = async () => {
          if (!confirm("Reissue a new code? Their current QR and code will stop working.")) return;
          try { await S.api(`/api/people/${item.id}/qr/regenerate`, { method: "POST" }); S.toast("New badge issued", "ok"); load(); }
          catch (e) { S.toast(e.detail || "Couldn't reissue", "err"); }
        };
      } catch (e) { S.qs("#bg").innerHTML = `<div class="empty">${S.esc(e.detail || "Couldn't load badge")}</div>`; }
    };
    load();
  }

  // Readable-but-strong password: 12 chars, no ambiguous glyphs (0/O, 1/l/I).
  function genPassword() {
    const sets = ["ABCDEFGHJKLMNPQRSTUVWXYZ", "abcdefghijkmnpqrstuvwxyz", "23456789", "!@#$%*?"];
    const pick = (s) => s[Math.floor(Math.random() * s.length)];
    let out = sets.map(pick).join("");  // guarantee one of each class
    const all = sets.join("");
    while (out.length < 12) out += pick(all);
    return out.split("").sort(() => Math.random() - 0.5).join("");
  }

  function fieldHtml(f, item) {
    const v = item ? item[f.k] : undefined;
    if (f.type === "textarea") return `<textarea data-mf="${f.k}">${S.esc(v || "")}</textarea>`;
    if (f.type === "password") {
      // Text input (not masked) so the admin can read the password they're setting, plus
      // one-click Generate + Copy — handy when creating accounts for the team.
      return `<div class="row" style="gap:6px;align-items:stretch">
        <input type="text" data-mf="${f.k}" value="${S.esc(v == null ? "" : v)}" autocomplete="new-password" placeholder="Blank = leave unchanged" style="flex:1">
        <button type="button" class="btn sm ghost" data-genpw="${f.k}" title="Generate a strong password">Generate</button>
        <button type="button" class="btn sm ghost" data-copypw="${f.k}" title="Copy to clipboard">Copy</button>
      </div>`;
    }
    if (f.type === "select") {
      return `<select data-mf="${f.k}">${resolveOpts(f).map((o) => `<option value="${S.esc(o.value)}" ${String(o.value) === String(v == null ? "" : v) ? "selected" : ""}>${S.esc(o.label)}</option>`).join("")}</select>`;
    }
    if (f.type === "multi") return `<div class="row wrap">${resolveOpts(f).map((o) => `<label class="chip" style="cursor:pointer"><input type="checkbox" style="width:auto" data-mf="${f.k}" value="${S.esc(o.value)}" ${(v || []).includes(o.value) ? "checked" : ""}> ${S.esc(o.label)}</label>`).join("")}</div>`;
    const t = f.type === "number" ? "number" : f.type === "time" ? "time" : f.type === "date" ? "date" : f.type === "password" ? "password" : "text";
    return `<input type="${t}" data-mf="${f.k}" value="${S.esc(v == null ? "" : v)}"${f.type === "number" ? ' step="1"' : ""}${f.type === "password" ? ' autocomplete="new-password"' : ""}>`;
  }

  function openForm(key, item) {
    const cfg = ENTITIES[key];
    const editing = !!item;
    const m = S.modal({
      title: `${editing ? "Edit" : "Add"} ${cfg.singular}`,
      body: cfg.fields.map((f) => `<label class="field"><span>${f.label}${f.req ? " *" : ""}</span>${fieldHtml(f, item)}</label>`).join(""),
      footer: `<button class="btn ghost" id="m-cancel">Cancel</button><button class="btn primary" id="m-save">${editing ? "Save" : "Create"}</button>`,
    });
    S.qs("#m-cancel").onclick = m.close;
    S.qsa("[data-genpw]").forEach((b) => b.onclick = () => {
      const inp = S.qs(`[data-mf="${b.dataset.genpw}"]`);
      inp.value = genPassword(); inp.focus(); inp.select();
      S.toast("Password generated - copy it before saving", "ok");
    });
    S.qsa("[data-copypw]").forEach((b) => b.onclick = async () => {
      const inp = S.qs(`[data-mf="${b.dataset.copypw}"]`);
      if (!inp.value) { S.toast("Nothing to copy yet", "err"); return; }
      try { await navigator.clipboard.writeText(inp.value); S.toast("Password copied", "ok"); }
      catch (e) { inp.select(); document.execCommand("copy"); S.toast("Password copied", "ok"); }
    });
    S.qs("#m-save").onclick = async () => {
      const payload = {};
      for (const f of cfg.fields) {
        let val;
        if (f.type === "multi") val = S.qsa(`[data-mf="${f.k}"]:checked`).map((c) => c.value);
        else val = S.qs(`[data-mf="${f.k}"]`).value;
        if (f.coerce === "intOrNull") val = (val === "" ? null : Number(val));
        else if ((f.type === "date" || f.type === "number") && val === "") val = null;
        if (f.omitIfBlank && (val === "" || val == null)) continue;
        payload[f.k] = val;
      }
      if (cfg.fields.some((f) => f.req && !String(payload[f.k] || "").trim())) { S.toast("Please fill the required field(s)", "err"); return; }
      try {
        if (editing) await S.api(`${cfg.api}/${item.id}`, { method: "PATCH", body: payload });
        else await S.api(cfg.api, { method: "POST", body: payload });
        S.toast(`${cfg.singular[0].toUpperCase() + cfg.singular.slice(1)} ${editing ? "updated" : "added"}`, "ok");
        m.close(); render(key);
      } catch (e) { S.toast(e.detail, "err"); }
    };
  }

  async function del(key, item) {
    const extra = key === "Employees" ? " Their attendance, gym, leave and notifications will be deleted (can't undo)."
      : key === "Leave Types" ? " Existing balances and requests for this type will be removed."
      : key === "Departments" ? " Employees/tasks in it will just be unassigned."
      : key === "Clients" ? " Tasks for this client will be unassigned." : "";
    if (!confirm(`Delete "${item.name}"?${extra}`)) return;
    try { await S.api(`${ENTITIES[key].api}/${item.id}`, { method: "DELETE" }); S.toast("Deleted", "ok"); render(key); }
    catch (e) { S.toast(e.detail, "err"); }
  }

  render(keys[0]);
};

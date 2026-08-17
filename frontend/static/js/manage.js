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
  // 🔴 A FAILED OPTION SOURCE IS NOT AN EMPTY ONE (2026-08-17). This used to end in
  // `.catch(() => [])`, so a 500 on shift-templates rendered the Shift picker with NO OPTIONS — which
  // reads as "this company has no shift templates", and the operator's next move is to create a
  // duplicate of one that already exists. Whether a shift is late is decided by
  // `Team.shift_template_id`, so a wrong pick here has consequences well beyond this form.
  // Still non-fatal — the rest of Manage must open — but the failure is now reported once, loudly,
  // instead of being disguised as an empty list.
  let shiftTemplates = [];
  let shiftTemplatesFailed = false;
  // 🔴 `let`, not `const`, and re-read after every write — THIS is the page that edits the
  // vocabulary. `S.vocab` is boot()'s snapshot (saving a round trip and seven SELECTs), but statuses,
  // priorities and labels are all editable HERE, so a snapshot held across a save is stale. Every
  // save/delete path calls `syncVocab()` below.
  const teams = await S.api("/api/teams");
  let vocab = S.vocab || { roles: [], priorities: [] };
  // Re-publishes the app-wide snapshot AND re-points this module's local copy at it. Both, or the
  // rest of the app sees the new list while this page keeps rendering the old one.
  async function syncVocab() { vocab = (await S.refreshVocab()) || vocab; }
  try { shiftTemplates = await S.api("/api/manage/shift-templates"); }
  catch (e) {
    // A 403 is this endpoint's normal answer for a role that cannot manage shifts — not a fault.
    if (e.status !== 401 && e.status !== 403) {
      shiftTemplatesFailed = true;
      S.toast("Shift templates couldn't be loaded — the Shift picker will be empty", "err");
    }
  }
  const OPTS = {
    roles: vocab.roles,
    teams: teams.map((t) => ({ value: t.id, label: t.name })),
    teamNames: teams.map((t) => ({ value: t.name, label: t.name })),  // service dept is stored by name
    // The toast above is transient; this puts the reason IN the control, where somebody who opens the
    // form five minutes later still sees it instead of an empty picker they'd read as "none exist".
    shiftTemplates: shiftTemplatesFailed
      ? [{ value: "", label: "— couldn't load shift templates · reopen Manage to retry —" }]
      : shiftTemplates.map((t) => ({ value: t.id, label: `${t.name} (${t.start}–${t.end})${t.is_default ? " · company default" : ""}` })),
  };

  const ENTITIES = {
    Employees: {
      api: "/api/people", singular: "employee",
      cols: [
        { k: "name", label: "Name" },
        { k: "email", label: "Email" },
        { k: "role_label", label: "Role" },
        { k: "team_name", label: "Department", fmt: (v, r) => _deptCell(v, r) },
        { k: "status", label: "Status", fmt: (v) => S.statusPill(v) },
      ],
      fields: [
        { k: "name", label: "Name", type: "text", req: true },
        { k: "email", label: "Email", type: "text", req: true },
        { k: "role", label: "Role", type: "select", optsKey: "roles" },
        { k: "team_id", label: "Department (their main one — drives their shift, payroll and the People directory)", type: "select", optsKey: "teams", allowEmpty: true, coerce: "intOrNull" },
        // 🔴 ADDITIONAL departments (models.UserTeam, 2026-08-14). People here are not all in exactly
        // one department — a designer who also sits with Acquisition, a lead covering a second team
        // — and until this existed the only way to say so was to change their main one, which moved
        // their shift and their payroll row with it. Ticking a box here widens what they SEE (that
        // department's board, queue, notifications and rollups) and nothing else; a team lead leads
        // every department ticked here, an employee reads them exactly as they read their own.
        { k: "team_ids", label: "Also works with (extra departments — they see and, if they're a team lead, lead these too)", type: "multi", optsKey: "teams", coerce: "intList", omitValueOf: "team_id" },
        { k: "shift_template_id", label: "Shift (override; blank = use department's)", type: "select", optsKey: "shiftTemplates", allowEmpty: true, coerce: "intOrNull" },
        { k: "phone", label: "Phone", type: "text" },
        { k: "hired_date", label: "Hired date", type: "date" },
        { k: "password", label: "Password (blank = leave unchanged; they can also use Google)", type: "password", omitIfBlank: true },
      ],
      help: "Everyone in Sentinel: attendance, gym, tasks, leave. Add a person here and they're available across the whole app (they get a QR badge + code automatically). Use Badge to view/print their QR or copy the code if they lost it.",
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
    // 🔴 READ-ONLY since 2026-08-05, by owner decision: **Atrium owns the client list; Sentinel owns
    // staff.** The Add/Edit/Delete affordances are gone and so are the routes behind them — a client
    // row typed in here had no `atrium_client_id`, which is the exact state that makes adoption
    // refuse to run and Send to Atrium unable to address a workspace. `services/client_sync` mirrors
    // Atrium's registry instead. Do not re-add `fields` here: `readOnly` is what suppresses the
    // buttons, and a form with nowhere to POST would just fail at the click.
    Clients: {
      // The query string lives on `listUrl`, not `api`: the generic editor builds per-row URLs as
      // `${cfg.api}/${id}`, and a `?…` baked into `api` would silently corrupt them if this tab ever
      // stopped being read-only.
      api: "/api/manage/clients", listUrl: "/api/manage/clients?include_inactive=1",
      singular: "client",
      readOnly: true,
      cols: [
        { k: "name", label: "Name" },
        { k: "contact_email", label: "Contact email" },
        { k: "atrium_client_id", label: "Atrium workspace", fmt: (v) => (v
          ? S.esc(v)
          : '<span class="pill amber" title="The bridge cannot address this client: publishing to Atrium and adoption both fail for it. Fix it in Atrium so the workspace name matches.">not linked</span>') },
        { k: "is_active", label: "Status", fmt: (v) => (v
          ? '<span class="pill green">Active</span>'
          : '<span class="pill grey" title="Atrium no longer lists this client. Its past tasks keep their attribution; it is only out of the pickers.">Not in Atrium</span>') },
      ],
      help: "Mirrored from Atrium, which owns the client list — these appear in the Task Board's "
        + "client filter and the New Task form. Add or rename a client in Atrium; it syncs here.",
      notice: clientsNotice,
    },
    Departments: {
      api: "/api/manage/teams", singular: "department",
      cols: [
        { k: "name", label: "Name" },
        { k: "shift_template_id", label: "Shift", fmt: (v) => _tplName(v) },
      ],
      fields: [
        { k: "name", label: "Name", type: "text", req: true },
        { k: "shift_template_id", label: "Shift template (blank = the ★ company-default template)", type: "select", optsKey: "shiftTemplates", allowEmpty: true, coerce: "intOrNull" },
      ],
      help: "Departments drive the Task Board filter, People, and each team's shift/late rules. A department's hours come entirely from its Shift Template: edit the times once in the Shift Templates tab and everyone on it updates. Leave blank to use the ★ company-default template.",
    },
    "Shift Templates": {
      api: "/api/manage/shift-templates", singular: "shift template",
      cols: [
        { k: "name", label: "Name" },
        { k: "is_default", label: "Default", fmt: (v) => (v ? `<span class="pill green">★ Company default</span>` : "") },
        { k: "start", label: "Start" },
        { k: "end", label: "End" },
        { k: "break_min", label: "Break (min)" },
        { k: "grace_min", label: "Grace (min)", fmt: (v) => (v == null ? "system default" : v) },
        { k: "paid_hours", label: "Paid hours", fmt: (v) => `${v}h` },
      ],
      fields: [
        { k: "name", label: "Name", type: "text", req: true },
        { k: "start", label: "Start (24-hour, e.g. 13:00)", type: "time" },
        { k: "end", label: "End (24-hour, e.g. 22:00)", type: "time" },
        { k: "break_min", label: "Unpaid break minutes (set 0 for short/part-time shifts)", type: "number" },
        { k: "grace_min", label: "Late grace minutes (blank = system default)", type: "number" },
        { k: "is_default", label: "Company default: the shift everyone uses unless their department/employee overrides it (only one template can be default)", type: "bool" },
      ],
      help: "Reusable shift schedules, the single place shift times live. Assign one to a department or an individual employee; editing a template updates everyone on it. Set break to 0 on a short shift (e.g. 6PM–10PM) so a 4-hour day isn't docked a lunch. One template is the ★ company default (the base every shift falls back to).",
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
        { k: "annual_balance", label: "Annual balance (days); use -1 for unlimited", type: "number" },
        { k: "accrual_type", label: "Accrual", type: "select", opts: ["Monthly", "Yearly", "—"] },
        { k: "requires_approval", label: "Approval rule", type: "text" },
        { k: "carry_over_days", label: "Carry-over days", type: "number" },
      ],
      help: "Leave types appear in the Leave request form; changing balances affects new balances going forward.",
    },
    Services: {
      api: "/api/manage/service-templates", singular: "service",
      cols: [
        { k: "label", label: "Service" },
        { k: "dept", label: "Department" },
        { k: "content_type", label: "Content type" },
        { k: "maintasks", label: "Recipe", fmt: (v) => `${(v || []).length} main · ${(v || []).reduce((n, m) => n + (m.subs || []).length, 0)} sub-tasks` },
        { k: "default_priority", label: "Defaults", fmt: (_v, r) => _svcDefaults(r) },
        { k: "is_active", label: "In picker", fmt: (v) => (v === false ? `<span class="muted">Archived</span>` : `<span class="pill day Push">Active</span>`) },
      ],
      customForm: true,  // has a nested main-task -> sub-task recipe editor (openServiceForm)
      rowActions: [{ label: "Duplicate", handler: (item) => openServiceForm(item, true) }],
      help: "The services the New Task form offers per department. Pick one and its whole main-task → sub-task breakdown (plus any default priority, labels and description) is seeded into the new task. Fully editable here, no developer needed.",
    },
    // One tab for the three Task Board vocabularies — they're the same shape (name + colour) and the
    // same endpoint, differing only by `kind`. A sub-selector switches between them so admins learn
    // one screen instead of three near-identical tabs.
    "Task Fields": {
      api: "/api/manage/task-vocab",
      cols: [{ k: "name", label: "Name" }, { k: "color", label: "Colour", fmt: (v) => _swatch(v) }],
      fields: [{ k: "name", label: "Name", type: "text", req: true }, { k: "color", label: "Colour", type: "color" }],
      kinds: [
        // 🔴 A STATUS CARRIES A THIRD FACET THE OTHER TWO DO NOT: its Atrium client stage (D13).
        // The server has REQUIRED it since WP 1.1 (`POST /task-vocab` 400s a stage-less status), but
        // this form only ever sent name + colour — so adding a status through the UI was IMPOSSIBLE,
        // failing every time with "Pick which client stage this status maps to". Found 2026-08-04,
        // on a production board that had no blocked column and therefore nowhere to park work: the
        // gap did not cause that, but it is why nobody could put the column back.
        // The picker is per-kind, not on the shared `fields`: a label or a priority has no stage,
        // and the server sets theirs to None regardless, so offering one would be a lie.
        { kind: "status", tab: "Statuses", singular: "status",
          help: "The Task Board's columns, in order. Each maps to one of the client's five stages — that is what a published card travels as, so the wording here is free to differ from what the client sees. Renaming one updates every task using it; you can't delete a status still in use.",
          cols: [{ k: "name", label: "Name" },
                 { k: "stage", label: "Client stage", fmt: (v) => v || "—" },
                 { k: "color", label: "Colour", fmt: (v) => _swatch(v) }],
          fields: [{ k: "name", label: "Name", type: "text", req: true },
                   { k: "stage", label: "Client stage", type: "select", req: true,
                     opts: [{ value: "todo", label: "To Do" },
                            { value: "in_progress", label: "In Progress" },
                            { value: "revision", label: "Revision" },
                            { value: "blocked", label: "Blocked / parked" },
                            { value: "completed", label: "Completed" }] },
                   { k: "color", label: "Colour", type: "color" }] },
        { kind: "label", tab: "Labels", singular: "label",
          help: "The colour-coded label chips on task cards. Renaming updates tasks; deleting is blocked while a task still uses it." },
        { kind: "priority", tab: "Priorities", singular: "priority",
          help: "Priority levels + their dot colour. Renaming updates tasks; deleting is blocked while a task still uses it." },
      ],
    },
  };

  // Which sub-vocabulary the "Task Fields" tab is showing (persists while the tab is open).
  let vocabKind = "status";

  // Resolve a tab's config, applying the active sub-kind for the merged "Task Fields" tab.
  function cfgFor(key) {
    const cfg = ENTITIES[key];
    if (!cfg.kinds) return cfg;
    const k = cfg.kinds.find((x) => x.kind === vocabKind) || cfg.kinds[0];
    // A kind may override `cols`/`fields` — statuses carry a stage the other two vocabularies don't.
    return { ...cfg, fixed: { kind: k.kind }, singular: k.singular, help: k.help,
             cols: k.cols || cfg.cols, fields: k.fields || cfg.fields,
             listUrl: `${cfg.api}?kind=${k.kind}` };
  }

  const _swatch = (hex) => hex
    ? `<span class="dot" style="background:${S.esc(hex)};vertical-align:middle"></span> <span class="muted">${S.esc(hex)}</span>`
    : "—";

  // Resolve a department's shift_template_id to a readable name (blank = the company default in Settings).
  const _tplName = (id) => {
    if (!id) return `<span class="muted">Company default</span>`;
    const t = shiftTemplates.find((x) => x.id === id);
    return t ? S.esc(`${t.name} (${t.start}–${t.end})`) : "—";
  };

  // A person's departments for the Employees table: their MAIN one, plus a chip for the extras
  // (models.UserTeam). Without the chip the console cannot show that somebody is in two departments
  // at all — the column reads `team_name`, which is the primary one and always will be — so a
  // super-admin editing the row would have no way to know the extras existed before opening it.
  const _deptCell = (name, r) => {
    const extra = (r.team_ids || []).filter((id) => id !== r.team_id);
    const names = extra.map((id) => (teams.find((t) => t.id === id) || {}).name).filter(Boolean);
    const chip = names.length
      ? ` <span class="pill grey" title="${S.esc("Also works with: " + names.join(", "))}">+${names.length}</span>`
      : "";
    return (name ? S.esc(name) : `<span class="muted">—</span>`) + chip;
  };

  // Compact summary of a service's auto-fill defaults for the Services table.
  const _svcDefaults = (r) => {
    const bits = [];
    if (r.default_priority) bits.push(S.esc(r.default_priority));
    // default_labels is deliberately not summarised — a task's label comes from its department
    // now (D14), so a stored per-template default is inert and showing it would mislead.
    if (r.default_description) bits.push("brief");
    return bits.length ? bits.join(" · ") : "—";
  };

  const keys = Object.keys(ENTITIES);
  view.innerHTML = `<div class="pagehead"><div><h2>Manage</h2>
      <div class="lead">Add your team and edit everything behind the app, no developer needed.</div></div></div>
    <div class="tabs" id="mtabs">${keys.map((k, i) => `<button class="${i ? "" : "active"}" data-k="${k}">${k}</button>`).join("")}</div>
    <div id="mbody"></div>`;
  S.qsa("#mtabs button").forEach((b) => b.onclick = () => {
    S.qsa("#mtabs button").forEach((x) => x.classList.remove("active")); b.classList.add("active"); render(b.dataset.k);
  });

  function resolveOpts(f, item) {
    let arr = f.optsKey ? (OPTS[f.optsKey] || []) : (f.opts || []).map((o) => (typeof o === "string" ? { value: o, label: o } : o));
    if (f.allowEmpty) arr = [{ value: "", label: "—" }].concat(arr);
    // 🔴 Drop the option already held by another field (`omitValueOf`). Used by Employees, where
    // "Also works with" must not offer the person's MAIN department: the server drops it from the
    // extras (`services/teams.set_extra_teams` — storing it twice would put one department in two
    // places and make un-ticking it in one of them do nothing), so a box that could be ticked and
    // then came back empty would read as a save that silently failed.
    if (f.omitValueOf && item && item[f.omitValueOf] != null) {
      arr = arr.filter((o) => String(o.value) !== String(item[f.omitValueOf]));
    }
    return arr;
  }

  async function render(key) {
    const cfg = cfgFor(key);
    const body = S.qs("#mbody");
    body.innerHTML = '<div class="skeleton" style="height:180px"></div>';
    let rows;
    // `() => render(key)` and not a bare `render` — `loadErr` invokes the retry with NO arguments,
    // so the tab this failed on has to be closed over here or the retry re-renders `undefined`.
    try { rows = await S.api(cfg.listUrl || cfg.api); }
    catch (e) { S.loadErr(body, e, () => render(key)); return; }
    // Sub-selector for a multi-kind tab (Task Fields → Statuses / Labels / Priorities).
    const subTabs = cfg.kinds
      ? `<div class="tabs sub" id="msub">${cfg.kinds.map((k) => `<button class="${k.kind === vocabKind ? "active" : ""}" data-sub="${k.kind}">${k.tab}</button>`).join("")}</div>`
      : "";
    // A READ-ONLY tab (Clients — mirrored from Atrium) has no Add button and no per-row Edit/Delete.
    // The Actions column is dropped entirely rather than rendered empty: a column of blank cells
    // reads as "the buttons failed to load", which is how somebody ends up hunting a bug.
    const ro = !!cfg.readOnly;
    const actionsCol = ro && !(cfg.rowActions || []).length;
    body.innerHTML = `${subTabs}
      <div class="row between" style="margin-bottom:12px">
        <div class="lead">${cfg.help}</div>
        ${ro ? "" : `<button class="btn primary" id="m-add">${S.ICON.plus}Add ${cfg.singular}</button>`}
      </div>
      <div id="m-notice"></div>
      <div class="table-wrap"><table>
        <thead><tr>${cfg.cols.map((c) => `<th>${c.label}</th>`).join("")}${actionsCol ? "" : '<th style="text-align:right">Actions</th>'}</tr></thead>
        <tbody>${rows.length ? rows.map((r) => `<tr>
          ${cfg.cols.map((c) => `<td>${c.fmt ? c.fmt(r[c.k], r) : S.esc(r[c.k] == null || r[c.k] === "" ? "—" : r[c.k])}</td>`).join("")}
          ${actionsCol ? "" : `<td style="text-align:right;white-space:nowrap">
            ${(cfg.rowActions || []).map((a, ai) => `<button class="btn sm ghost" data-rowact="${ai}" data-id="${r.id}">${S.esc(a.label)}</button>`).join("")}
            ${ro ? "" : `<button class="btn sm ghost" data-edit="${r.id}">Edit</button>
            <button class="btn sm danger" data-del="${r.id}">Delete</button>`}</td>`}</tr>`).join("")
        : `<tr><td colspan="${cfg.cols.length + (actionsCol ? 0 : 1)}"><div class="empty">${ro
            ? `No ${cfg.singular}s are mirrored yet.`
            : `No ${cfg.singular}s yet. Add one.`}</div></td></tr>`}</tbody></table></div>`;

    S.qsa("#msub button").forEach((b) => b.onclick = () => { vocabKind = b.dataset.sub; render(key); });
    const openEditor = (item) => (cfg.customForm ? openServiceForm(item) : openForm(key, item));
    if (S.qs("#m-add")) S.qs("#m-add").onclick = () => openEditor(null);
    S.qsa("[data-edit]").forEach((b) => b.onclick = () => openEditor(rows.find((r) => r.id == b.dataset.edit)));
    S.qsa("[data-del]").forEach((b) => b.onclick = () => del(key, rows.find((r) => r.id == b.dataset.del)));
    S.qsa("[data-rowact]").forEach((b) => b.onclick = () => cfg.rowActions[+b.dataset.rowact].handler(rows.find((r) => r.id == b.dataset.id)));
    // Fails silently and AFTER the table: it is context about the mirror, and losing it must never
    // cost the list itself.
    if (cfg.notice) cfg.notice(S.qs("#m-notice")).catch(() => {});
  }

  // The Clients pane's extra strip: where clients are actually managed, whether the mirror is
  // healthy, and — the actionable part — which clients the bridge cannot address.
  async function clientsNotice(host) {
    if (!host) return;
    const s = await S.api("/api/manage/clients/sync-status");
    const link = s.atrium_console_url
      ? `<a href="${S.esc(s.atrium_console_url)}" target="_blank" rel="noopener">Manage clients in Atrium →</a>`
      : '<span class="muted">Atrium\'s address is not configured here, so the mirror is off.</span>';
    // An unlinked client is the one thing on this pane somebody must act on: publishing and adoption
    // both fail for it, silently, until its Atrium workspace name matches.
    const unlinked = (s.unlinked || []).length
      ? `<div class="mgr-warn"><div>
           <b>${s.unlinked.length} client${s.unlinked.length === 1 ? "" : "s"} not linked to an Atrium workspace:</b>
           ${s.unlinked.map((c) => S.esc(c.name)).join(", ")}.
           Sending work to Atrium and importing client cards both fail for these. Create or rename the
           matching workspace in Atrium — the names are matched automatically on the next sync.
         </div></div>`
      : "";
    // 🔴 SYNC NOW is a recovery affordance, not a convenience (added 2026-08-07). This pane is
    // read-only by design — Atrium owns clients — so when the mirror is stale there was NOTHING a
    // human could do here: no button, and the only automatic trigger was a boot, which stopped
    // happening once the service got `--min-instances 1`. The observed failure was somebody creating
    // a client in Atrium and being unable to raise a service for it here at all, with no error to
    // read anywhere. `services/daily.mirror_clients` is what keeps it fresh unattended; this is for
    // the person who needs it in the next thirty seconds.
    //
    // Deliberately does NOT pass `?deactivate=1`: switching a client off is driven by absence and
    // stays a deliberate two-step (AGENTS.md §2). This button only ever creates and links.
    host.innerHTML = `<div class="mgr-strip">
        <span>${s.active} active${s.inactive ? ` · ${s.inactive} no longer in Atrium` : ""}</span>
        <span>${link}</span>
        <button class="btn sm ghost" id="cl-sync" title="Pull Atrium's client list now. Only adds and links — never retires a client.">Sync now</button>
      </div>${unlinked}`;
    const btn = S.qs("#cl-sync");
    if (btn) btn.onclick = async () => {
      btn.disabled = true;
      const was = btn.textContent;
      btn.textContent = "Syncing…";
      try {
        const r = await S.api("/api/manage/clients/sync", { method: "POST" });
        const added = (r.created || 0) + (r.linked || 0);
        S.toast(added
          ? `${r.created || 0} new client${r.created === 1 ? "" : "s"}, ${r.linked || 0} linked`
          : "Already up to date with Atrium", "ok");
        // Re-render the pane so the counts and the unlinked list reflect what just happened —
        // a sync that says "1 new" beside an unchanged list is the same class of lie as the
        // "shared with the client" flag that pointed at nothing.
        // "Clients" is the ENTITIES key, and it has to match exactly — `render` looks the pane's
        // config up by it, so a lowercase key silently renders nothing.
        if (added) render("Clients"); else clientsNotice(host);
      } catch (err) {
        // 409 = Atrium didn't return a list we dare act on; the detail says which. Never silent:
        // an unreported failure here is exactly how the list went stale unnoticed in the first place.
        S.toast(err.detail || "Could not reach Atrium to sync clients", "err");
        btn.disabled = false;
        btn.textContent = was;
      }
    };
  }

  // Employee badge: view/print the QR + copy the typeable code, or reissue if lost.
  async function openBadge(item) {
    const m = S.modal({ title: `${item.name} · attendance badge`, body: `<div id="bg" style="text-align:center;min-height:120px">Loading…</div>` });
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
      return `<select data-mf="${f.k}">${resolveOpts(f, item).map((o) => `<option value="${S.esc(o.value)}" ${String(o.value) === String(v == null ? "" : v) ? "selected" : ""}>${S.esc(o.label)}</option>`).join("")}</select>`;
    }
    // Compared as STRINGS: a checkbox's value always is one, while these ids arrive as numbers
    // (`team_ids`) or as text (`day_types`), and `includes` across the two types silently checks
    // nothing — the form would open with every box clear and saving would wipe the row.
    if (f.type === "multi") {
      const on = (v || []).map(String);
      return `<div class="row wrap">${resolveOpts(f, item).map((o) => `<label class="chip" style="cursor:pointer"><input type="checkbox" style="width:auto" data-mf="${f.k}" value="${S.esc(o.value)}" ${on.includes(String(o.value)) ? "checked" : ""}> ${S.esc(o.label)}</label>`).join("")}</div>`;
    }
    if (f.type === "color") return `<input type="color" data-mf="${f.k}" value="${S.esc(v || "#6B7280")}" style="width:56px;height:34px;padding:2px">`;
    if (f.type === "bool") return `<label class="chip" style="cursor:pointer;align-self:start"><input type="checkbox" style="width:auto" data-mf="${f.k}" ${v ? "checked" : ""}> Enabled</label>`;
    const t = f.type === "number" ? "number" : f.type === "time" ? "time" : f.type === "date" ? "date" : f.type === "password" ? "password" : "text";
    return `<input type="${t}" data-mf="${f.k}" value="${S.esc(v == null ? "" : v)}"${f.type === "number" ? ' step="1"' : ""}${f.type === "password" ? ' autocomplete="new-password"' : ""}>`;
  }

  function openForm(key, item) {
    const cfg = cfgFor(key);
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
      const payload = { ...(cfg.fixed || {}) };   // e.g. {kind:"status"} for task-vocab
      for (const f of cfg.fields) {
        let val;
        if (f.type === "multi") val = S.qsa(`[data-mf="${f.k}"]:checked`).map((c) => c.value);
        else if (f.type === "bool") val = S.qs(`[data-mf="${f.k}"]`).checked;
        else val = S.qs(`[data-mf="${f.k}"]`).value;
        if (f.coerce === "intList") val = (val || []).map(Number).filter((n) => Number.isFinite(n));
        else if (f.coerce === "intOrNull") val = (val === "" ? null : Number(val));
        else if ((f.type === "date" || f.type === "number") && val === "") val = null;
        if (f.omitIfBlank && (val === "" || val == null)) continue;
        payload[f.k] = val;
      }
      if (cfg.fields.some((f) => f.req && !String(payload[f.k] || "").trim())) { S.toast("Please fill the required field(s)", "err"); return; }
      try {
        if (editing) await S.api(`${cfg.api}/${item.id}`, { method: "PATCH", body: payload });
        else await S.api(cfg.api, { method: "POST", body: payload });
        S.toast(`${cfg.singular[0].toUpperCase() + cfg.singular.slice(1)} ${editing ? "updated" : "added"}`, "ok");
        // This is the generic save for EVERY entity on this page, including Task Fields — so a status
        // rename lands in the app-wide snapshot here rather than staying stale until the next
        // navigation. Unconditional on purpose: gating it on `key === "Task Fields"` would be a second
        // place that has to know which entities are vocabulary, and one refresh is cheap.
        await syncVocab();
        m.close(); render(key);
      } catch (e) { S.toast(e.detail, "err"); }
    };
  }

  async function del(key, item) {
    const extra = key === "Employees" ? " Their attendance, gym, leave and notifications will be deleted (can't undo)."
      : key === "Leave Types" ? " Existing balances and requests for this type will be removed."
      : key === "Departments" ? " Employees/tasks in it will just be unassigned."
      : key === "Clients" ? " Tasks for this client will be unassigned." : "";
    if (!confirm(`Delete "${item.name || item.label}"?${extra}`)) return;
    try {
      await S.api(`${ENTITIES[key].api}/${item.id}`, { method: "DELETE" });
      S.toast("Deleted", "ok");
      await syncVocab();   // same reason as the save path above
      render(key);
    } catch (e) { S.toast(e.detail, "err"); }
  }

  // Service recipe editor — a main-task title + one-sub-task-per-line textarea per group. Low-code:
  // the whole two-level breakdown a new task is seeded with, edited without touching any code.
  function openServiceForm(item, asNew) {
    // asNew = pre-fill from `item` but save as a brand-new service (the Duplicate action).
    const editing = !!item && !asNew;
    // recipe rows: {title, subsText}
    let recipe = (item && item.maintasks || []).map((m) => ({
      title: m.title || "", subsText: (m.subs || []).map((s) => s.text).join("\n"),
    }));
    if (!recipe.length) recipe = [{ title: "", subsText: "" }];
    const deptOpts = [{ value: "", label: "—" }].concat(OPTS.teamNames);
    const prioOpts = [{ value: "", label: "— none —" }].concat((vocab.priorities || []).map((p) => ({ value: p, label: p })));
    let defLabel = item ? item.label : "";
    if (asNew && item) defLabel = `${item.label} (copy)`;
    const m = S.modal({
      title: `${editing ? "Edit" : "Add"} service`, wide: true,
      body: `
        <label class="field"><span>Service name *</span><input id="sf-label" value="${S.esc(defLabel)}"></label>
        <div class="grid" style="grid-template-columns:1fr 1fr;gap:12px">
          <label class="field"><span>Department</span><select id="sf-dept">${deptOpts.map((o) => `<option value="${S.esc(o.value)}" ${item && item.dept === o.value ? "selected" : ""}>${S.esc(o.label)}</option>`).join("")}</select></label>
          <label class="field"><span>Content type</span><input id="sf-ctype" value="${S.esc(item ? item.content_type || "" : "")}"></label>
        </div>
        <div class="section-label" style="margin:6px 0 4px">Recipe: main tasks &amp; their sub-tasks</div>
        <div class="muted" style="font-size:12px;margin-bottom:8px">One sub-task per line. This is what gets seeded into a new task's breakdown.</div>
        <div id="sf-recipe"></div>
        <button type="button" class="btn sm ghost" id="sf-addmain" style="margin-top:8px">${S.ICON.plus}Add main task</button>
        <div class="section-label" style="margin:16px 0 4px">Auto-fill defaults</div>
        <div class="muted" style="font-size:12px;margin-bottom:8px">Pre-filled onto a new task when this service is picked. Each stays editable on the task.</div>
        <div class="grid" style="grid-template-columns:1fr 1fr;gap:12px">
          <label class="field"><span>Default priority</span><select id="sf-prio">${prioOpts.map((o) => `<option value="${S.esc(o.value)}" ${item && item.default_priority === o.value ? "selected" : ""}>${S.esc(o.label)}</option>`).join("")}</select></label>
          <label class="field"><span>Show in the New Task picker</span><label class="chip" style="cursor:pointer;align-self:start"><input type="checkbox" id="sf-active" style="width:auto" ${item && item.is_active === false ? "" : "checked"}> Active</label></label>
        </div>
        <!-- Default labels was REMOVED 2026-08-04 (decision D14): a task's one label is derived
             from its department, so a per-template default could only ever be ignored. The
             'default_labels_json' column stays for now but nothing reads it.
             NO BACKTICKS in this comment: it is inside a template literal. -->
        <div class="field" style="grid-column:1/-1"><div class="form-hint">The task's label is set automatically from the department this service belongs to — Acquisition → Paid Media, Lifecycle → Organic, everything else → Website.</div></div>
        <label class="field"><span>Default description / brief</span><textarea id="sf-desc" rows="3">${S.esc(item ? item.default_description || "" : "")}</textarea></label>`,
      footer: `<button class="btn ghost" id="sf-cancel">Cancel</button><button class="btn primary" id="sf-save">${editing ? "Save" : "Create"}</button>`,
    });

    function readDom() {
      recipe = S.qsa("#sf-recipe .mtask").map((row) => ({
        title: row.querySelector(".mtask-title").value,
        subsText: row.querySelector("textarea").value,
      }));
    }
    function renderRecipe() {
      S.qs("#sf-recipe").innerHTML = recipe.map((r, i) => `
        <div class="mtask" data-i="${i}">
          <div class="mtask-head">
            <input class="mtask-title" value="${S.esc(r.title)}" placeholder="Main task title">
            <button type="button" class="bd-x" data-del="${i}" title="Remove main task">✕</button>
          </div>
          <div style="padding:8px 10px"><textarea rows="4" placeholder="One sub-task per line…">${S.esc(r.subsText)}</textarea></div>
        </div>`).join("");
      S.qsa("#sf-recipe [data-del]").forEach((b) => b.onclick = () => { readDom(); recipe.splice(+b.dataset.del, 1); if (!recipe.length) recipe = [{ title: "", subsText: "" }]; renderRecipe(); });
    }
    renderRecipe();
    S.qs("#sf-addmain").onclick = () => { readDom(); recipe.push({ title: "", subsText: "" }); renderRecipe(); };
    S.qs("#sf-cancel").onclick = m.close;
    S.qs("#sf-save").onclick = async () => {
      const label = S.qs("#sf-label").value.trim();
      if (!label) { S.toast("Service name is required", "err"); return; }
      readDom();
      const maintasks = recipe
        .map((r) => ({ title: r.title.trim(), subs: r.subsText.split("\n").map((l) => l.trim()).filter(Boolean).map((text) => ({ text })) }))
        .filter((g) => g.title || g.subs.length);
      const payload = {
        label, dept: S.qs("#sf-dept").value || null, content_type: S.qs("#sf-ctype").value || null, maintasks,
        default_priority: S.qs("#sf-prio").value || null,
        // default_labels is no longer sent: the label is derived from the department (D14).
        default_description: S.qs("#sf-desc").value.trim() || null,
        is_active: S.qs("#sf-active").checked,
      };
      try {
        if (editing) await S.api(`/api/manage/service-templates/${item.id}`, { method: "PATCH", body: payload });
        else await S.api("/api/manage/service-templates", { method: "POST", body: payload });
        S.toast(`Service ${editing ? "updated" : "created"}`, "ok"); m.close(); render("Services");
      } catch (e) { S.toast(e.detail || "Couldn't save the service", "err"); }
    };
  }

  render(keys[0]);
};

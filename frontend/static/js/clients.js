/* CLIENTS — every account's health, and one client in depth (2026-09-02).

   `/clients` is the table (services/client_health.rollup). `/clients?client=<id>` is the drill-down:
   open work by specialist, blockers and on whom, reviews, the next fortnight's commitments, what
   shipped in the last one — and "Draft with AI", which PROPOSES tasks that are then created through
   POST /api/tasks exactly as New Task does (every permission, label and origin rule applies).

   The Task Board opens cards; this page links into it (`/tasks?open=`) rather than duplicating the
   record. */
window.pageInit = async (S) => {
  const U = window.OpsUI;
  const view = S.view();
  const params = new URLSearchParams(location.search);
  const clientId = params.get("client");
  const meta = await U.meta(S);

  if (!clientId) {
    view.innerHTML = `<div class="skeleton skel-card" style="height:260px"></div>`;
    let d;
    try { d = await S.api("/api/ops/clients"); }
    catch (e) { view.innerHTML = `<div class="notice warn"><b>Couldn't load clients.</b> ${S.esc(e.detail || "")}</div>`; return; }
    view.innerHTML = `<div class="pagehead"><div><h2>Clients</h2><div class="lead">${S.esc(d.rule || meta.health_rule || "")}</div></div></div>
      ${U.clientsTable(S, d.clients || [], { am: true })}`;
    U.wireClientRows(view);
    return;
  }

  // ---- one client -------------------------------------------------------------------------------
  view.innerHTML = `<div class="skeleton skel-card" style="height:260px"></div>`;
  let o;
  try { o = await S.api(`/api/ops/clients/${encodeURIComponent(clientId)}`); }
  catch (e) { view.innerHTML = `<div class="notice warn"><b>Couldn't load that client.</b> ${S.esc(e.detail || "")}</div>`; return; }
  const c = o.client;
  const canAssign = S.hasCap("clients.assign_am");
  const canDraft = S.hasCap("ai.draft");
  const counts = o.counts || {};
  const byLead = (o.by_lead || []).map((g) => `
    <div class="os-group">${g.user ? `${S.avatar(g.user, "xs")} ${S.esc(g.user.name)}${g.user.stage ? ` <span class="muted">· ${S.esc(g.user.stage.replace("_", " "))}</span>` : ""}` : "Unassigned"}<span class="n">${g.tasks.length}</span></div>
    ${g.tasks.map((t) => U.taskRow(S, t)).join("")}`);
  const blockers = (o.blockers || []).map((t) => U.taskRow(S, t));
  const reviews = (o.reviews || []).map((t) => U.taskRow(S, t, { who: true }));
  const completed = (o.completed || []).slice(0, 8).map((t) => U.taskRow(S, t, { who: true, quiet: true }));
  const commitments = (o.commitments || []).map((k) => `<div class="os-kv"><span>${U.dueChip(k.due_date)}</span><b>${S.esc(k.title)}</b>${k.assignee ? `<span class="muted">${S.esc(k.assignee.name.split(" ")[0])}</span>` : ""}</div>`);

  view.innerHTML = `
    <div class="pagehead">
      <div><div class="os-kick"><a href="/clients">Clients</a>${c.account_manager ? ` · ${S.esc(c.account_manager.name)}` : " · no account manager named"}</div>
        <h2>${S.esc(c.name)}</h2>
        <div class="lead">${U.healthPill(o.health)} · ${S.esc((o.why || []).join(", "))} · ${counts.open || 0} open${counts.completed_14d ? ` · ${counts.completed_14d} completed in 14 days` : ""}</div></div>
      <div class="row" style="gap:8px;flex-wrap:wrap">
        ${canAssign ? `<button class="btn" id="cl-am">${c.account_manager ? "Change AM" : "Name an AM"}</button>` : ""}
        ${canDraft ? `<button class="btn" id="cl-ai" ${meta.ai_enabled ? "" : `title="AI drafting isn't switched on for this deployment"`}>✦ Draft with AI</button>` : ""}
        <a class="btn primary" href="/tasks?new=1&client_id=${c.id}">${S.ICON.plus}New task</a>
      </div>
    </div>
    <div id="cl-ai-box" hidden class="card pad os-ai">
      <label class="field"><span>What was agreed? The AI proposes tasks — nothing is created until you confirm.</span>
        <textarea id="ai-in" rows="3" placeholder="We promised ${S.esc(c.name)} the September analysis before Thursday's meeting…"></textarea></label>
      <div class="row" style="gap:10px;align-items:center"><button class="btn primary" id="ai-go">Draft tasks</button><span class="muted" style="font-size:13px">Suggested assignee = who already holds this client's work in that department, checked against stage, leave and load.</span></div>
      <div id="ai-out"></div>
    </div>
    <div class="os-two">
      <div>
        ${U.head("Open work by specialist")}
        <div class="card">${byLead.length ? byLead.join("") : `<div class="os-empty">No open work for this client.</div>`}</div>
        <div class="os-sect">${U.head("Completed · last 14 days")}<div class="card">${U.list(completed, "Nothing completed in the last two weeks.")}</div></div>
      </div>
      <div>
        ${U.head("Blockers", "who is it on?")}<div class="card">${U.list(blockers, "Nothing blocked.")}</div>
        <div class="os-sect">${U.head("Reviews waiting")}<div class="card">${U.list(reviews, "Nothing waiting for review.")}</div></div>
        <div class="os-sect">${U.head("Commitments · next 14 days")}<div class="card pad">${commitments.join("") || `<div class="os-empty">No dated work in the next fortnight.</div>`}</div></div>
      </div>
    </div>`;

  // --- name / change the account manager -------------------------------------------------------
  const amBtn = S.qs("#cl-am");
  if (amBtn) amBtn.onclick = async () => {
    const people = await S.api("/api/people").catch(() => []);
    const ams = (Array.isArray(people) ? people : []).filter((p) => p.is_active !== false && ["account_manager", "admin", "super_admin"].includes(p.role));
    const m = S.modal({
      title: `Account manager for ${c.name}`,
      body: `<label class="field"><span>Who owns this account at Agora?</span>
        <select id="am-sel"><option value="">— nobody yet —</option>${ams.map((p) => `<option value="${p.id}" ${c.account_manager_id === p.id ? "selected" : ""}>${S.esc(p.name)}</option>`).join("")}</select></label>`,
      footer: `<button class="btn ghost" id="am-cancel">Cancel</button><button class="btn primary" id="am-save">Save</button>`,
    });
    S.qs("#am-cancel").onclick = m.close;
    S.qs("#am-save").onclick = async () => {
      const v = S.qs("#am-sel").value;
      try {
        await S.api(`/api/ops/clients/${c.id}/account-manager`, { method: "PATCH", body: { account_manager_id: v ? +v : null } });
        S.toast("Saved", "ok"); m.close(); location.reload();
      } catch (e) { S.toast(e.detail || "Couldn't save", "err"); }
    };
  };

  // --- Draft with AI ----------------------------------------------------------------------------
  const aiBtn = S.qs("#cl-ai"), box = S.qs("#cl-ai-box");
  if (aiBtn) aiBtn.onclick = () => { box.hidden = !box.hidden; if (!box.hidden) S.qs("#ai-in").focus(); };
  const go = S.qs("#ai-go");
  if (go) go.onclick = async () => {
    const text = S.qs("#ai-in").value.trim();
    if (text.length < 3) { S.toast("Say what was agreed first", "err"); return; }
    const out = S.qs("#ai-out");
    out.innerHTML = `<div class="os-empty">Reading the request, this client's open cards, who holds them, leave and load…</div>`;
    go.disabled = true;
    let d;
    try { d = await S.api("/api/ops/ai/draft-tasks", { method: "POST", body: { text, client_id: c.id } }); }
    catch (e) {
      out.innerHTML = `<div class="notice warn"><b>AI unavailable — file it by hand.</b> ${S.esc(e.detail || "")} <a class="btn sm ghost" href="/tasks?new=1&client_id=${c.id}">New task</a></div>`;
      go.disabled = false; return;
    }
    go.disabled = false;
    const props = d.proposals || [];
    out.innerHTML = `<div class="card os-props">${props.map((p, i) => `
      <div class="os-prop" data-i="${i}">
        <div class="os-prop-main">
          <input class="os-prop-title" value="${S.esc(p.title)}" aria-label="Task ${i + 1} title">
          <div class="os-meta wrap">${p.assignee ? `${S.esc(p.assignee.name)}` : "unassigned → department queue"} · ${S.esc(p.department || "no department")} · due <b>${p.due_date ? S.fmtDate(p.due_date + "T00:00:00+08:00") : "—"}</b>${p.estimate_minutes ? ` · ~${U.fmtMin(p.estimate_minutes)}` : ""}${p.reviewer ? ` · reviewer ${S.esc(p.reviewer.name)}` : ""}${p.depends_on ? ` · waits on task ${p.depends_on}` : ""}</div>
          ${p.why ? `<div class="os-why-line">${S.esc(p.why)}</div>` : ""}
          ${(p.warnings || []).map((w) => `<div class="os-warn-line">${S.esc(w)}</div>`).join("")}
        </div>
        <label class="os-prop-keep"><input type="checkbox" checked> keep</label>
      </div>`).join("")}
      <div class="os-prop-foot"><button class="btn primary" id="ai-create">Create the kept tasks</button><span class="muted" style="font-size:13px">Same permissions and rules as New Task.</span></div>
    </div>`;
    S.qs("#ai-create").onclick = async () => {
      const keep = [...out.querySelectorAll(".os-prop")].filter((el) => el.querySelector("input[type=checkbox]").checked);
      if (!keep.length) { S.toast("Nothing kept", "err"); return; }
      const created = {};   // proposal index → task id, for dependencies
      let n = 0;
      for (const el of keep) {
        const p = props[+el.dataset.i];
        const title = el.querySelector(".os-prop-title").value.trim() || p.title;
        try {
          const t = await S.api("/api/tasks", { method: "POST", body: {
            title, description: p.description, client_id: c.id, assigned_team_id: p.assigned_team_id,
            assigned_to_id: p.assigned_to_id, due_date: p.due_date, estimate_minutes: p.estimate_minutes,
            priority: "Medium",
          } });
          created[p.index] = t.id; n++;
          // "Waits on task N": park it as waiting on another task so it is visibly not live yet.
          if (p.depends_on && created[p.depends_on]) {
            await S.api(`/api/tasks/${t.id}/park`, { method: "POST", body: { kind: "task", blocked_by_task_id: created[p.depends_on], reason: `Starts when task ${created[p.depends_on]} is approved.` } }).catch(() => {});
          }
        } catch (e) { S.toast(`“${title}”: ${e.detail || "couldn't create"}`, "err"); }
      }
      if (n) { S.toast(`Created ${n} task${n === 1 ? "" : "s"}`, "ok"); location.reload(); }
    };
  };
};

/* Shared drawing for the operating-system pages (2026-09-02): Today (today.js), the AM's landing
   (accounts.js), Operations (ops.js), Clients (clients.js), Projects (projects.js) and the
   Calendar (calendar.js).

   One row shape for one task, everywhere — title with a priority dot, one grey meta line, a due chip
   — because the mockup review found the old strip unreadable precisely where every row carried five
   competing signals. Everything here is READ-ONLY drawing plus ONE shared write flow (the AI
   planner, which proposes and lets a human create); the other writes stay in the pages and in the
   board's own record (taskboard.js).

   🔴 Stage, never the status LABEL: statuses are renameable in Manage (D13), so every test here goes
   through `stageOf()`, which reads `S.vocab.task_status_meta`. */
window.OpsUI = (() => {
  const PH_TODAY = () => new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Manila" });
  const dayDiff = (iso) => Math.round((Date.parse(iso + "T00:00:00Z") - Date.parse(PH_TODAY() + "T00:00:00Z")) / 864e5);
  const plural = (n, w) => n + " " + w + (n === 1 ? "" : "s");

  let META = null;            // /api/ops/meta — hold kinds, stages, health rule, ai_enabled
  async function meta(S) {
    S_ = S;
    if (META) return META;
    try { META = await S.api("/api/ops/meta"); } catch (e) { META = { hold_kinds: {}, stages: [], health_rule: "", ai_enabled: false }; }
    return META;
  }

  function stageOf(S, status) {
    const v = S.vocab;
    const m = ((v && v.task_status_meta) || []).find((s) => s.name === status);
    return m ? m.stage : null;
  }
  const isDone = (S, t) => stageOf(S, t.status) === "completed";
  const isParked = (S, t) => !!t.on_hold || stageOf(S, t.status) === "blocked";
  // Priority rank follows the vocabulary's declared order (first = most urgent); unknown sinks.
  function prioRank(S, p) {
    const list = (S.vocab && S.vocab.priorities) || [];
    const i = list.indexOf(p);
    return i === -1 ? 99 : i;
  }
  const fmtMin = (m) => {
    if (m == null) return "—";
    m = Math.max(0, Math.round(m));
    return m >= 60 ? `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, "0")}m` : `${m}m`;
  };
  // `S_` is whichever page last drew with us; app.js exports the same object as window.Sentinel, so a
  // helper called before any page passed S still formats correctly.
  let S_ = null;
  const SS = () => S_ || window.Sentinel;
  const fmtDay = (iso) => SS().fmtDate(iso + "T00:00:00+08:00");

  function dueChip(iso, opts = {}) {
    if (!iso) return `<span class="os-due none">no date</span>`;
    if (opts.done) return `<span class="os-due done">${fmtDay(iso)}</span>`;
    const n = dayDiff(iso);
    if (opts.parked) return `<span class="os-due">${fmtDay(iso)}</span>`;
    const txt = n < 0 ? plural(-n, "day") + " late" : n === 0 ? "Today" : n === 1 ? "Tomorrow" : fmtDay(iso);
    return `<span class="os-due ${n < 0 ? "late" : n === 0 ? "today" : ""}">${txt}</span>`;
  }

  /** One task, one row. `opts.who` adds the lead's first name; `opts.quiet` greys a parked row. */
  function taskRow(S, t, opts = {}) {
    S_ = S;
    const bits = [];
    bits.push(`<b>${S.esc(t.client_name || "Internal")}</b>`);
    if (opts.who && t.assignee) bits.push(S.esc(t.assignee.name.split(" ")[0]));
    const parked = isParked(S, t);
    if (parked) {
      const kind = (META && META.hold_kinds && META.hold_kinds[t.hold_kind]) || t.hold_kind_label || "Parked";
      bits.push(S.esc(kind) + (t.blocked_days != null ? ` · ${plural(t.blocked_days, "day")}` : ""));
    } else if (t.review_state === "changes_requested") {
      bits.push("changes requested");
    } else if (t.review_state === "pending") {
      bits.push("waiting for review");
    } else if (t.running) {
      bits.push(`<span class="os-live">working</span>`);
    } else {
      bits.push(S.esc(t.status));
      if (t.estimate_minutes) bits.push("~" + fmtMin(t.estimate_minutes));
    }
    if (t.my_slots && t.assigned_to_id !== S.user.id) bits.push(plural(t.my_slots, "step") + " on you");
    return `<a class="os-row ${parked || opts.quiet ? "quiet" : ""}" href="/tasks?open=${t.id}">
      <span class="os-main">
        <span class="os-title">${S.priorityDot(t.priority)}${S.esc(t.title)}</span>
        <span class="os-meta">${bits.join(" · ")}</span>
      </span>
      <span class="os-right">${dueChip(t.due_date, { done: isDone(S, t), parked })}<span class="os-chev">${S.ICON.chev}</span></span>
    </a>`;
  }

  function list(rows, empty) {
    return `<div class="os-list">${rows.length ? rows.join("") : `<div class="os-empty">${empty || "Nothing here."}</div>`}</div>`;
  }
  function head(title, right) {
    return `<div class="os-head"><h3>${title}</h3>${right ? `<span class="os-hint">${right}</span>` : ""}</div>`;
  }
  function healthPill(h, why) {
    const label = { red: "Red", amber: "Amber", green: "Green" }[h] || h;
    return `<span class="os-health h-${h}"><i class="dot"></i>${label}${why ? `<span class="os-why">${SS().esc(Array.isArray(why) ? why.join(", ") : why)}</span>` : ""}</span>`;
  }
  function band(b) {
    if (!b) return `<span class="os-band" title="Not enough open work on the team to compare">—</span>`;
    return `<span class="os-band ${b}">${b[0].toUpperCase() + b.slice(1)}</span>`;
  }
  const num = (n, cls) => `<td class="n ${n ? cls || "" : "zero"}">${n}</td>`;

  /** The accounts table both the AM landing and the Clients page draw. */
  function clientsTable(S, rows, opts = {}) {
    S_ = S;
    if (!rows.length) return `<div class="card"><div class="os-empty">No active clients are mirrored from Atrium yet.</div></div>`;
    return `<div class="card table-wrap"><table class="os-tbl">
      <thead><tr><th>Client</th><th>Health</th>${opts.am ? "<th>AM</th>" : ""}<th class="n">Open</th><th class="n">Late</th><th class="n">Blocked</th><th class="n">Reviews</th><th>Next</th></tr></thead>
      <tbody>${rows.map((r) => `<tr class="click" data-client="${r.client.id}">
        <td><b>${S.esc(r.client.name)}</b></td>
        <td>${healthPill(r.health, r.why)}</td>
        ${opts.am ? `<td>${r.account_manager ? S.avatar(r.account_manager, "xs") + " " + S.esc(r.account_manager.name.split(" ")[0]) : '<span class="muted">—</span>'}</td>` : ""}
        ${num(r.open)}${num(r.overdue, "bad")}
        <td class="n ${r.blocked ? (r.blocked_on_us ? "bad" : "warn") : "zero"}">${r.blocked}${r.blocked_on_client ? `<span class="os-sub">${r.blocked_on_client} on client</span>` : ""}</td>
        ${num(r.reviews, "warn")}
        <td class="sub">${r.next ? `${S.esc(r.next.title)} · ${fmtDay(r.next.due_date)}` : "—"}</td>
      </tr>`).join("")}</tbody></table></div>`;
  }
  function wireClientRows(root) {
    root.querySelectorAll("tr[data-client]").forEach((tr) => {
      tr.onclick = () => { location.href = "/clients?client=" + tr.dataset.client; };
    });
  }

  /* ---------------- The AI planner (2026-09-02) ----------------------------------------------
     ONE shared flow for "describe what was agreed → AI proposes tasks → a human edits and creates",
     reachable from the Task Board, a project page and (via the same endpoint) the client drill-down.
     The owner's design, verbatim: "the AI is the one who creates the tasks and suggests assignees,
     but the account manager can just override it."

     Rules it inherits, not invents: /api/ops/ai/draft-tasks PROPOSES only; every kept proposal is
     POSTed to /api/tasks where all the usual permission/label/origin rules apply; warnings (leave,
     load, stage-needs-reviewer, certification) come computed from Sentinel's own facts. The
     OVERRIDE is real: title and assignee are editable per proposal before anything is created. */
  async function openAiPlanner(S, opts = {}) {
    S_ = S;
    const m = await meta(S);
    // The client list: the ops rollup for those who can see it; the board's own picker data
    // otherwise. Fail-soft — "no client" (internal work) is always a valid answer.
    let clients = [];
    try {
      if (S.hasCap("clients.view")) clients = ((await S.api("/api/ops/clients")).clients || []).map((r) => r.client);
      else clients = (await S.api("/api/clients").catch(() => [])) || [];
    } catch (e) { /* internal-only planning still works */ }
    let people = [];
    try { people = (await S.api("/api/people")).filter((p) => p.is_active !== false); } catch (e) {}
    const peopleOpts = (sel) => `<option value="">Department queue</option>` +
      people.map((p) => `<option value="${p.id}" ${p.id === sel ? "selected" : ""}>${S.esc(p.name)}</option>`).join("");

    const modal = S.modal({
      title: "✦ Plan work with AI",
      body: `<div class="os-ai">
        ${m.ai_enabled ? "" : `<div class="notice warn"><b>AI drafting isn't switched on for this deployment.</b> The New Task form always works.</div>`}
        <div class="tf-rows">
          <div class="tf-row"><div class="k">Client</div><div class="v"><select id="pl-client">
            <option value="">No client — internal work</option>
            ${clients.map((c) => `<option value="${c.id}" ${String(c.id) === String(opts.client_id || "") ? "selected" : ""}>${S.esc(c.name)}</option>`).join("")}
          </select></div></div>
        </div>
        <label style="display:block;margin-top:10px">What was agreed? Say it like you'd say it to a colleague.
          <textarea id="pl-in" rows="3" placeholder="We promised the September Meta analysis before Thursday's meeting — analysis first, then three findings added to the report."></textarea></label>
        <div class="row" style="gap:10px;align-items:center;margin-top:8px">
          <button class="btn primary" id="pl-go" ${m.ai_enabled ? "" : "disabled"}>Draft tasks</button>
          <span class="muted" style="font-size:13px">Suggested assignee = who already holds this client's work in that department, checked against stage, leave and load. You can override everything.</span>
        </div>
        <div id="pl-out"></div>
      </div>`,
    });
    const root = modal.root;
    S.qs("#pl-in", root).focus();

    S.qs("#pl-go", root).onclick = async () => {
      const text = S.qs("#pl-in", root).value.trim();
      if (text.length < 3) { S.toast("Say what was agreed first", "err"); return; }
      const out = S.qs("#pl-out", root);
      const go = S.qs("#pl-go", root);
      out.innerHTML = `<div class="os-empty">Reading the request, the open cards, who holds them, leave and load…</div>`;
      go.disabled = true;
      let d;
      const clientId = +S.qs("#pl-client", root).value || null;
      try { d = await S.api("/api/ops/ai/draft-tasks", { method: "POST", body: { text, client_id: clientId } }); }
      catch (e) {
        out.innerHTML = `<div class="notice warn"><b>AI unavailable — file it by hand.</b> ${S.esc(e.detail || "")}</div>`;
        go.disabled = false; return;
      }
      go.disabled = false;
      const props = d.proposals || [];
      out.innerHTML = `<div class="card os-props">${props.map((p, i) => `
        <div class="os-prop" data-i="${i}">
          <div class="os-prop-main">
            <input class="os-prop-title" value="${S.esc(p.title)}" aria-label="Task ${i + 1} title">
            <div class="os-meta wrap">
              <select class="os-prop-assignee" aria-label="Assignee">${peopleOpts(p.assigned_to_id)}</select>
              · ${S.esc(p.department || "no department")} · due <input type="date" class="os-prop-due" value="${p.due_date || ""}">
              ${p.estimate_minutes ? ` · ~${fmtMin(p.estimate_minutes)}` : ""}${p.reviewer ? ` · reviewer ${S.esc(p.reviewer.name)}` : ""}${p.depends_on ? ` · waits on task ${p.depends_on}` : ""}</div>
            ${p.why ? `<div class="os-why-line">${S.esc(p.why)}</div>` : ""}
            ${(p.warnings || []).map((w) => `<div class="os-warn-line">${S.esc(w)}</div>`).join("")}
          </div>
          <label class="os-prop-keep"><input type="checkbox" checked> keep</label>
        </div>`).join("")}
        <div class="os-prop-foot"><button class="btn primary" id="pl-create">Create the kept tasks</button><span class="muted" style="font-size:13px">Nothing exists until you press this. Same permissions and rules as New Task.</span></div>
      </div>`;
      S.qs("#pl-create", root).onclick = async () => {
        const keep = [...out.querySelectorAll(".os-prop")].filter((el) => el.querySelector(".os-prop-keep input").checked);
        if (!keep.length) { S.toast("Nothing kept", "err"); return; }
        const created = {};   // proposal index → task id, for dependencies
        let n = 0;
        for (const el of keep) {
          const p = props[+el.dataset.i];
          const title = el.querySelector(".os-prop-title").value.trim() || p.title;
          const assignee = +el.querySelector(".os-prop-assignee").value || null;
          const due = el.querySelector(".os-prop-due").value || null;
          try {
            const t = await S.api("/api/tasks", { method: "POST", body: {
              title, description: p.description, client_id: clientId,
              assigned_team_id: p.assigned_team_id, assigned_to_id: assignee,
              due_date: due, estimate_minutes: p.estimate_minutes,
              project_id: opts.project_id || null, priority: "Medium",
            } });
            created[p.index] = t.id; n++;
            // "Waits on task N": park it as waiting on another card so it is visibly not live yet.
            if (p.depends_on && created[p.depends_on]) {
              await S.api(`/api/tasks/${t.id}/park`, { method: "POST", body: { kind: "task", blocked_by_task_id: created[p.depends_on], reason: `Starts when task ${created[p.depends_on]} is approved.` } }).catch(() => {});
            }
          } catch (e) { S.toast(`“${title}”: ${e.detail || "couldn't create"}`, "err"); }
        }
        if (n) {
          S.toast(`Created ${n} task${n === 1 ? "" : "s"}`, "ok");
          modal.close();
          if (opts.onDone) opts.onDone(); else location.reload();
        }
      };
    };
  }

  return { PH_TODAY, dayDiff, plural, meta, stageOf, isDone, isParked, prioRank, fmtMin, dueChip,
           taskRow, list, head, healthPill, band, clientsTable, wireClientRows, openAiPlanner };
})();

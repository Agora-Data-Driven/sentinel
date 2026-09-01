/* Shared drawing for the operating-system pages (2026-09-02): Today (today.js), the AM's landing
   (accounts.js), Operations (ops.js), Clients (clients.js) and the Calendar (calendar.js).

   One row shape for one task, everywhere — title with a priority dot, one grey meta line, a due chip
   — because the mockup review found the old strip unreadable precisely where every row carried five
   competing signals. Everything here is READ-ONLY drawing; the writes stay in the pages and in the
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

  return { PH_TODAY, dayDiff, plural, meta, stageOf, isDone, isParked, prioRank, fmtMin, dueChip,
           taskRow, list, head, healthPill, band, clientsTable, wireClientRows };
})();

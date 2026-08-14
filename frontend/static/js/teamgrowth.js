/* TeamGrowth — everyone's growth in one table, and the control that scopes the whole Overview.
   Admin-only, mounted by dashboard.js at the top of the "Across Agora" block:
   TeamGrowth.mount(S, containerEl, { onScope }).

   TWO JOBS, and the second is the reason this isn't just another card:

   1. THE COLLECTIVE VIEW. The four rings above show the reader their own growth. This shows the
      same four numbers for every person the reader may see, from the same Mastery Engine rollup
      (see services/team_growth.py — one batched call, not one per head), so a row here and that
      person's own Overview cannot disagree.

   2. THE DASHBOARD SCOPE. Sorting and filtering here drive the WHOLE page: pick people (or a
      segment like "stalled") and the task board below re-filters to their cards, the Across-Agora
      KPIs recount, the clock-in chart redraws, and the late/handover lists follow. The scope is
      handed up through `onScope` — this component owns the selection, dashboard.js owns what the
      rest of the page does with it. State lives in the URL (?people=&sort=&seg=&win=) so a scoped
      view survives a reload and can be pasted to someone else.

   🔴 RANKED ON MEASURED SPEED, WHICH IS NOT THE PACE CHIP. Speed is points of engine mastery per
   week over the window, computed by replaying each person's attempt log; the pace chip compares a
   score against a calendar. Somebody who banked progress in July and has since stopped still reads
   "▲ ahead" while their speed is 0. Both columns are here on purpose — the sort defaults to speed
   because "who has stopped moving" is the question a ring can't answer.

   🔴 "NO ENGINE DATA" IS NOT ZERO, ANYWHERE IN HERE. A person the engine couldn't answer for
   renders "—", never 0%, sorts to the BOTTOM whichever direction is chosen (a null must never
   take the top of "slowest first" and read as the worst performer), and is counted out loud
   underneath the table. An engine outage would otherwise show a full team of zeroes, which reads
   as "nobody is doing anything" — a confident lie, and the exact shape of the Watcher-bridge
   incident in AGENTS.md §5. */
window.TeamGrowth = {
  async mount(S, root, opts) { return mountTeam(S, root, opts || {}); },
};

async function mountTeam(S, root, opts) {
  const esc = S.esc;
  const G = window.GrowthMath;
  const onScope = opts.onScope || (() => {});

  const SORTS = [
    { v: "speed", t: "Fastest first" },
    { v: "speed-asc", t: "Slowest first" },
    { v: "pace", t: "Furthest behind pace" },
    { v: "overall", t: "Highest overall" },
    { v: "name", t: "Name (A–Z)" },
  ];
  const SEGMENTS = [
    { v: "all", t: "Everyone" },
    { v: "moving", t: "Moving" },
    { v: "stalled", t: "Stalled" },
    { v: "behind", t: "Behind pace" },
    { v: "ahead", t: "Ahead of pace" },
  ];
  const WINDOWS = [7, 30, 90];

  // --- state, mirrored into the URL so a scoped Overview is reloadable and shareable -----------
  const url0 = new URLSearchParams(location.search);
  const pick = (raw, allowed, fallback) => (allowed.indexOf(raw) >= 0 ? raw : fallback);
  let sort = pick(url0.get("sort"), SORTS.map((s) => s.v), "speed");
  let segment = pick(url0.get("seg"), SEGMENTS.map((s) => s.v), "all");
  let days = WINDOWS.indexOf(Number(url0.get("win"))) >= 0 ? Number(url0.get("win")) : 30;
  let search = "";
  const selected = new Set(
    (url0.get("people") || "").split(",").map(Number).filter((n) => Number.isFinite(n) && n > 0),
  );

  let payload = null;   // the last /api/development/team response
  let failed = "";      // why the whole panel has nothing, if so

  root.innerHTML = `<div class="row between sect-head" style="margin-top:30px">
      <div class="section-label">${S.ICON.users}Team progress</div>
      <span class="sub" id="tg-lede">Ranked by measured speed — Mastery Engine points gained per week.</span>
    </div>
    <div class="tg-controls" id="tg-controls"></div>
    <div id="tg-body">${S.skeleton ? S.skeleton({ rows: 4 }) : "Loading…"}</div>`;

  // --- derived views over the rows -------------------------------------------------------------

  /** A person's overall pace is read against their LAST engine deadline: finishing everything
   *  means finishing the slowest dimension, so that is the date the whole row is racing. */
  function lastDeadline(row) {
    const dates = G.DIM_KEYS
      .filter((k) => k !== "physical")
      .map((k) => (row.dimensions[k] || {}).deadline)
      .filter(Boolean);
    return dates.length ? dates.sort()[dates.length - 1] : null;
  }

  const overallExpected = (row) => G.expected(lastDeadline(row));
  const overallDelta = (row) => G.paceDelta(row.overall, overallExpected(row));

  function matchesSegment(row) {
    if (segment === "all") return true;
    const v = row.velocity;
    const d = overallDelta(row);
    // An unknown is excluded from every named segment — it belongs to none of them, and quietly
    // filing it under "stalled" would accuse someone of nothing on the strength of a bridge error.
    switch (segment) {
      case "moving": return v != null && v > 0.05;
      case "stalled": return v != null && v <= 0.05;
      case "behind": return d != null && d < -2;
      case "ahead": return d != null && d > 2;
      default: return true;
    }
  }

  function matchesSearch(row) {
    if (!search) return true;
    return [row.user.name, row.user.email, row.team]
      .some((s) => (s || "").toLowerCase().includes(search));
  }

  /** Rows after segment + search, in the chosen order. */
  function shown() {
    const rows = (payload ? payload.rows : []).filter((r) => matchesSegment(r) && matchesSearch(r));
    // Unknowns always sink, in BOTH directions — see the header comment.
    const nullsLast = (a, b, key) => {
      const av = key(a), bv = key(b);
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      return 0;
    };
    const byName = (a, b) => (a.user.name || "").localeCompare(b.user.name || "");
    const cmp = {
      speed: (a, b) => nullsLast(a, b, (r) => r.velocity) || (b.velocity - a.velocity) || byName(a, b),
      "speed-asc": (a, b) => nullsLast(a, b, (r) => r.velocity) || (a.velocity - b.velocity) || byName(a, b),
      pace: (a, b) => nullsLast(a, b, overallDelta) || (overallDelta(a) - overallDelta(b)) || byName(a, b),
      overall: (a, b) => nullsLast(a, b, (r) => r.overall) || (b.overall - a.overall) || byName(a, b),
      name: byName,
    }[sort] || byName;
    return rows.slice().sort(cmp);
  }

  /** What the rest of the Overview should show.
   *
   *  An explicit tick beats everything. Failing that, a segment or a search IS a filter and must
   *  reach the whole page — "show me the stalled people" that left the task board showing all
   *  twelve would answer half the question. With neither, nothing is scoped and the page renders
   *  exactly as it always has.
   *
   *  `scoped` is what says which of those it is, and consumers MUST branch on it rather than on
   *  `ids.length`. "Stalled" matching nobody and "no filter at all" both produce an empty id list,
   *  and collapsing them would answer "show me the stalled people" with everybody's work — the
   *  loudest possible wrong answer. Empty-and-scoped means an empty board. */
  function scope() {
    // `order` is always the table's CURRENT ordering, scoped or not — it's what lets the task
    // board's swimlanes read fastest-first alongside this table. `rows` rides along so the host
    // can recount its own KPIs for the selection without a second request for the same facts.
    const base = { order: shown().map((r) => r.user.id), rows: payload ? payload.rows : [] };
    if (selected.size) {
      // The tick stays authoritative even if the segment or search since moved past that person —
      // narrowing the table must not silently drop somebody the reader deliberately picked.
      const ids = [...selected];
      return { ...base, ids, scoped: true, label: `${ids.length} selected`, source: "selection" };
    }
    if (segment !== "all" || search) {
      const seg = (SEGMENTS.find((s) => s.v === segment) || {}).t || "";
      const ids = base.order.slice();
      return {
        ...base,
        ids,
        scoped: true,
        label: (search ? `“${search}”${segment !== "all" ? " · " + seg : ""}` : seg)
          + ` · ${ids.length} ${ids.length === 1 ? "person" : "people"}`,
        source: "filter",
      };
    }
    return { ...base, ids: [], scoped: false, label: "", source: "none" };
  }

  function pushUrl() {
    const u = new URLSearchParams(location.search);
    const set = (k, v, dflt) => { if (v && v !== dflt) u.set(k, v); else u.delete(k); };
    set("sort", sort, "speed");
    set("seg", segment, "all");
    set("win", String(days), "30");
    if (selected.size) u.set("people", [...selected].join(",")); else u.delete("people");
    history.replaceState(null, "", location.pathname + (u.toString() ? "?" + u : ""));
  }

  function announce() {
    pushUrl();
    onScope(scope());
  }

  // --- rendering --------------------------------------------------------------------------------

  /** The control strip. Written ONCE per load and then left alone — re-rendering it on every
   *  keystroke would rebuild the search box mid-word and throw away focus and the caret. Only the
   *  scope chip inside it changes, and that redraws into its own node (renderScope). */
  function controlsHtml() {
    const sel = (id, options, current) => `<select id="${id}">${options.map((o) =>
      `<option value="${esc(String(o.v))}" ${String(o.v) === String(current) ? "selected" : ""}>${esc(o.t)}</option>`).join("")}</select>`;
    return `
      <input id="tg-search" class="tb-search" type="search" placeholder="Search teammates…" autocomplete="off" value="${esc(search)}">
      ${sel("tg-sort", SORTS, sort)}
      ${sel("tg-seg", SEGMENTS, segment)}
      ${sel("tg-win", WINDOWS.map((d) => ({ v: d, t: `Last ${d} days` })), days)}
      <button class="btn sm ghost" id="tg-refresh" title="Re-read the Mastery Engine now (the rollup is cached for a couple of minutes)">${S.ICON.sparkle}Refresh</button>
      <span class="tg-scope" id="tg-scope"></span>`;
  }

  function renderScope() {
    const host = S.qs("#tg-scope", root);
    if (!host) return;
    const sc = scope();
    const off = sc.source === "none";
    host.className = "tg-scope " + (off ? "off" : "on");
    host.innerHTML = off
      ? "Whole dashboard · everyone"
      : `${S.ICON.sliders}Dashboard scoped to ${esc(sc.label)} <a href="#" class="linky" id="tg-clear">clear</a>`;
    const c = S.qs("#tg-clear", root);
    if (c) c.onclick = (e) => {
      e.preventDefault();
      selected.clear();
      segment = "all";
      search = "";
      // Put the widgets back in step by hand — they are not re-rendered (see controlsHtml).
      const seg = S.qs("#tg-seg", root); if (seg) seg.value = "all";
      const q = S.qs("#tg-search", root); if (q) q.value = "";
      refresh();
    };
  }

  function dimCell(row, dim) {
    const d = row.dimensions[dim.key] || {};
    const actual = d.actual;
    const exp = G.expected(d.deadline);
    const bits = [
      `${dim.name}: ${actual == null ? "no data" : Math.round(actual) + "%"}`,
      actual == null ? "" : G.paceText(actual, exp),
      dim.key === "physical"
        ? `${d.targets || 0} target PR${d.targets === 1 ? "" : "s"} · speed isn't measurable here`
        : (d.velocity == null ? "speed unavailable" : G.fmtSpeed(d.velocity)),
    ].filter(Boolean);
    if (actual == null) {
      return `<td class="tg-dim" title="${esc(bits.join(" · "))}"><span class="tg-na">—</span></td>`;
    }
    const pct = Math.max(0, Math.min(100, actual));
    return `<td class="tg-dim" style="--hue:var(--dim-${dim.key})" title="${esc(bits.join(" · "))}">
      <span class="tg-pct">${Math.round(actual)}<i>%</i></span>
      <span class="tg-bar"><i style="width:${pct.toFixed(1)}%"></i><b style="left:${exp.toFixed(1)}%"></b></span>
    </td>`;
  }

  function rowHtml(row) {
    const u = row.user;
    const on = selected.has(u.id);
    const exp = overallExpected(row);
    const stale = row.engine && row.engine.unmatched
      ? ` title="${row.engine.unmatched} recent attempts couldn't be matched to a current topic, so this reads slightly low"` : "";
    const activity = row.velocity == null
      ? `<span class="sub">${esc(row.engine && row.engine.error ? row.engine.error : "no engine data")}</span>`
      : `<span class="sub">${row.streak ? `${row.streak}-day streak · ` : ""}${
          row.last_active ? S.timeAgo(row.last_active) : "no attempts in " + payload.days + " days"}</span>`;
    // The tick is a real <button>, so the row is keyboard-reachable and announces its state.
    // It carries no handler of its own: its click bubbles to the row, which is the one toggle.
    return `<tr data-uid="${u.id}" class="${on ? "on" : ""}">
      <td class="tg-tick"><button type="button" class="tg-box" aria-pressed="${on ? "true" : "false"}"
        aria-label="Scope the dashboard to ${esc(u.name)}">${on ? "✓" : ""}</button></td>
      ${/* The flex is on `.who-in`, NEVER on the <td> — a table cell with display:flex stops being
            a cell and the row's border/padding paint on the wrong box. See styles.css `.who > .who-in`. */""}
      <td class="who"><div class="who-in">${S.avatar(u, "sm")}<div><div class="n">${esc(u.name)}</div>
        <div class="r">${esc(row.team || u.role_label || u.role || "")}</div></div></div></td>
      ${G.DIMS.map((d) => dimCell(row, d)).join("")}
      <td class="num">${row.overall == null ? '<span class="tg-na">—</span>' : Math.round(row.overall) + "%"}</td>
      <td class="tg-speed"${stale}>${G.speedChip(row.velocity, row.overall, lastDeadline(row))}</td>
      <td>${G.paceChip(row.overall, exp) || '<span class="tg-na">—</span>'}</td>
      <td class="tg-act">${activity}</td>
      <td class="tg-go"><a class="linky" href="/growth?user=${u.id}" title="Open ${esc(u.name.split(" ")[0])}’s growth profile">view</a></td>
    </tr>`;
  }

  function table() {
    const rows = shown();
    const total = payload.rows.length;
    const unknown = payload.rows.filter((r) => r.velocity == null).length;
    if (!total) return `<div class="empty">No active teammates to show.</div>`;

    const head = `<tr><th></th><th>Teammate</th>
      ${G.DIMS.map((d) => `<th class="tg-dim" title="${esc(d.blurb)}">${esc(d.name)}</th>`).join("")}
      <th class="num">Overall</th><th>Speed</th><th>Pace</th><th>Activity · ${payload.days}d</th><th></th></tr>`;

    const notes = [];
    if (payload.engine_error) {
      notes.push(`<div class="tg-warn">${S.ICON.x}Mastery Engine: ${esc(payload.engine_error)}.
        Those rows read “—”, which means <strong>unknown</strong> — not zero progress.</div>`);
    } else if (unknown) {
      notes.push(`<div class="sub tg-foot">${unknown} ${unknown === 1 ? "person has" : "people have"}
        no Mastery Engine data (no enrolled programme yet). They show “—”, sort last, and are left
        out of the named filters — that's an unknown, not a zero.</div>`);
    }
    if (rows.length !== total) {
      notes.push(`<div class="sub tg-foot">Showing ${rows.length} of ${total}.</div>`);
    }
    notes.push(`<div class="sub tg-foot">Speed is engine mastery gained per week over the last
      ${payload.days} days. Physical has no engine programme — nothing timestamps a PR — so it has a
      score but no speed, and sits outside the ranking.
      ${payload.generated_at ? `Measured ${S.timeAgo(payload.generated_at)}.` : ""}</div>`);

    return `${notes.join("")}
      <div class="tg-wrap"><table class="tg-tbl"><thead>${head}</thead>
        <tbody>${rows.length ? rows.map(rowHtml).join("")
          : `<tr><td colspan="${G.DIMS.length + 7}"><div class="empty">Nobody matches that filter.</div></td></tr>`}</tbody>
      </table></div>`;
  }

  /** Redraw everything that depends on the current sort/filter/selection — the table, the scope
   *  chip, the URL, and the rest of the Overview. Deliberately NOT the control strip. */
  function refresh() {
    renderTable();
    renderScope();
    announce();
  }

  function renderTable() {
    S.qs("#tg-body", root).innerHTML = failed
      ? `<div class="empty card pad">${esc(failed)}</div>`
      : table();
    // A row IS the scope control — clicking anywhere on it toggles that person into the
    // dashboard-wide selection. The "view" link stops propagation so it stays a link.
    S.qsa(".tg-tbl tbody tr[data-uid]", root).forEach((tr) => {
      tr.onclick = () => {
        const id = Number(tr.dataset.uid);
        if (selected.has(id)) selected.delete(id); else selected.add(id);
        refresh();
      };
    });
    S.qsa(".tg-go a", root).forEach((a) => a.onclick = (e) => e.stopPropagation());
  }

  function wireControls() {
    const q = S.qs("#tg-search", root);
    if (q) q.oninput = () => { search = q.value.trim().toLowerCase(); refresh(); };
    const s = S.qs("#tg-sort", root);
    if (s) s.onchange = () => { sort = s.value; refresh(); };
    const g = S.qs("#tg-seg", root);
    if (g) g.onchange = () => { segment = g.value; refresh(); };
    // The window changes what was MEASURED, not how it's displayed, so this one refetches.
    const w = S.qs("#tg-win", root);
    if (w) w.onchange = () => { days = Number(w.value); load(); };
    const r = S.qs("#tg-refresh", root);
    if (r) r.onclick = () => load({ refresh: true });
  }

  async function load(o) {
    S.qs("#tg-body", root).innerHTML = S.skeleton ? S.skeleton({ rows: 4 }) : "Loading…";
    S.qs("#tg-controls", root).innerHTML = controlsHtml();
    wireControls();
    try {
      payload = await S.api(`/api/development/team?days=${days}${(o && o.refresh) ? "&refresh=1" : ""}`);
      failed = "";
    } catch (e) {
      payload = { days, rows: [], engine_error: "" };
      // The panel is one section of the Overview, not the Overview: say what happened here and
      // leave every other section alone.
      failed = e.detail || "Couldn't load team progress.";
    }
    refresh();
  }

  await load();
  return {
    /** dashboard.js re-asks for the scope when it rebuilds a dependent section. */
    scope,
    reload: () => load({ refresh: true }),
  };
}

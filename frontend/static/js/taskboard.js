/* TaskBoard — the full Kanban (Board / By Employee / Monitor), formerly the /tasks page,
   now a mountable component embedded in the dashboard: TaskBoard.mount(S, containerEl).
   Deep links (?open=<id> from notifications, ?new=1 from the command palette, ?view=…) are
   read from the CURRENT page URL, so they work at /dashboard; the old /tasks URL 302s there. */
window.TaskBoard = {
  async mount(S, root) {
  // 🔴 The read-only seat (decision D8). `S.can()` is RANK-based and a viewer sits at the floor, so
  // every rank check already refuses it — but rank cannot express "sees everything, writes nothing",
  // so the seat is named explicitly here exactly as it is server-side (constants.VIEW_ALL_ROLES).
  // The server enforces all of this; hiding the controls is so a viewer is not offered buttons that
  // can only ever answer 403.
  const readOnly = S.user.role === "viewer";
  const canCreate = !readOnly;              // all other staff can add + edit tasks (internal tool)
  const canManage = S.can("account_manager"); // AM+ only: the Atrium bridge
  // Monitor is a READ, and monitoring is the viewer's entire purpose — so it is a rank check OR the
  // seat, matching `employee_summary`'s guard.
  const canMonitor = S.can("team_lead") || readOnly;
  // 🔴 PRIORITY: the server has always let a team lead set it within their own team
  // (task_perms.can_prioritize), and this file gated on `isAM` — so a lead saw a read-only value and
  // had to ask an AM to change a number they are trusted to own (§2.4f). The server was right; this
  // was the bug. `isAM` survives ONLY for Atrium-owned cards, where the server really is AM+
  // (can_manage_atrium): such a card has no Sentinel team for a lead to be the lead OF.
  const isAM = canManage;
  const canPrioritize = (t) => t.source === "atrium" ? canManage : (canManage
    || (canMonitor && t.assigned_team_id != null && t.assigned_team_id === S.user.team_id));
  // On the create/edit FORM there may be no team yet (it is a field on the form), so this mirrors
  // create_task's `may_delegate` instead: a lead may set priority on work they raise.
  const canPrioritizeOnForm = canManage || canMonitor;
  // Mirrors task_perms.can_delete (the server enforces it): AM+ anywhere, team lead in their
  // team, and the creator for their own tasks. Drives the ✕ on cards + Delete in the drawer.
  // An Atrium-owned card (t.source === "atrium") has no assignee, team or creator tag to test, so
  // it follows task_perms.can_manage_atrium instead: managers only, since deleting it removes a
  // client's card (into Atrium's Bin, restorable for 30 days).
  const canDelete = (t) => readOnly ? false : (t.source === "atrium" ? canManage : (canManage
    || (canMonitor && t.assigned_team_id != null && t.assigned_team_id === S.user.team_id)
    || (t.created_by_id != null && t.created_by_id === S.user.id)));
  // Mirrors task_perms.can_review (the server enforces it): AM+ anywhere, a team lead within their
  // own team. Deciding a review is a management call; ASKING for one is not (that's can_edit).
  // Atrium-owned cards have no review state — there is no local row to hold one.
  // Mirrors task_perms.can_reassign (the server enforces it): delegation — changing the team or
  // an owner to SOMEBODY ELSE — is AM+ anywhere, a team lead within their own team. Used by the
  // D12 routing control; self-assignment is deliberately NOT gated on this, which is why the
  // per-step pickers stay open to everyone (§2.4e / WP 4.2f).
  const canReassign = (t) => !readOnly && (canManage
    || (canMonitor && t.assigned_team_id != null && t.assigned_team_id === S.user.team_id));
  const canReview = (t) => !readOnly && t.source !== "atrium" && (canManage
    || (canMonitor && t.assigned_team_id != null && t.assigned_team_id === S.user.team_id));

  // Board-only styles (styles.css stays untouched): the hover ✕ on cards. Injected once,
  // same pattern as the Coach FAB styles in app.js — CSP allows style elements, not inline JS.
  if (!document.getElementById("tb-style")) {
    const st = document.createElement("style");
    st.id = "tb-style";
    st.textContent = `
      /* 🔴 The task detail is a WIDE CENTRED MODAL, not a side panel.
         A split view was tried on 2026-08-03 and REMOVED the same day, because the board's own
         dimensions make it impossible: 5 columns x 288px + gaps = 1496px, plus a 248px sidebar and a
         ~340px panel = ~2150px before anything breathes. The board already scrolls horizontally at
         1800px, so the panel squeezed the columns AND cramped itself -- and at 340px wide the
         '.spread' field grid (minmax 220px) collapsed to ONE column, so eleven label/value pairs
         stacked up before you reached the work breakdown. In '.modal.wide' (920px) that same grid
         gives four columns. Don't re-add a docked panel without doing this arithmetic first.
         🔴 NO BACKTICKS ANYWHERE IN THIS COMMENT: it lives inside a template literal, so a
         markdown-style code span would CLOSE the string and the rest parses as a tagged template
         call ("...".spread is not a function). node --check does NOT catch it -- it is valid
         syntax, and it only blows up at mount() time. Quote selectors with ' instead.
         The body is two columns: the record on the left, the work + conversation on the right --
         which is also what makes the modal shorter than the panel ever was. */
      .tb-cols{display:grid;grid-template-columns:1.05fr .95fr;gap:26px;align-items:start}
      .tb-cols > *{min-width:0}
      /* One column on a narrow screen (or a phone), where 920px is not available anyway. */
      @media (max-width:820px){.tb-cols{grid-template-columns:1fr;gap:22px}}
      .tcard{position:relative}
      .tcard .t-del{position:absolute;top:7px;right:7px;width:24px;height:24px;border:none;border-radius:7px;
        background:transparent;color:var(--muted);font-size:13px;line-height:1;cursor:pointer;
        display:flex;align-items:center;justify-content:center;opacity:0;transition:opacity .12s ease,background .12s ease,color .12s ease}
      .tcard:hover .t-del,.tcard .t-del:focus-visible{opacity:1}
      .tcard .t-del:hover{background:var(--danger);color:#fff}
      @media (hover: none){.tcard .t-del{opacity:.55}}

      /* MOBILE MOVE CONTROL (WP 5.5, problem 2.2.6). Drag-and-drop was the board's ONLY move
         affordance, so on a phone the board is a horizontal scroll of cards that cannot be
         moved at all -- the drawer's status select was the only way, three taps away.
         A native select is deliberate: it hands phones the OS picker, it is keyboard and
         screen-reader operable for free, and it needs no popup layer.
         Hidden wherever a real pointer exists, because dragging is better there and a second
         control on every card is clutter. Still reachable by KEYBOARD on the desktop -- it
         appears on focus, which is the only move affordance a keyboard user has ever had. */
      .tcard .t-move{position:absolute;left:8px;right:34px;bottom:6px;width:auto;height:26px;
        font-size:11px;padding:0 6px;border-radius:7px;border:1px solid var(--line);
        background:var(--card);color:var(--muted);cursor:pointer;
        opacity:0;pointer-events:none}
      .tcard .t-move:focus-visible{opacity:1;pointer-events:auto;color:var(--fg);border-color:var(--accent)}
      @media (hover: none){
        .tcard .t-move{position:static;display:block;width:100%;margin-top:8px;opacity:1;
          pointer-events:auto;height:32px;font-size:12px}
        /* The delete affordance already sits top-right; keep it clear of the select. */
        .tcard{padding-bottom:10px}
      }

      /* BULK SELECTION (M7, WP 5.4). Opt-in: a permanent checkbox on every card is clutter on a
         board people mostly read, and it competes with drag for the same pointer. */
      .tcard .t-pick{position:absolute;top:8px;right:8px;width:16px;height:16px;margin:0;
        cursor:pointer;z-index:2}
      .tcard.picked{outline:2px solid var(--accent);outline-offset:-2px}
      /* With a checkbox in the corner the delete button would sit under it. */
      .tcard .t-pick ~ .t-del{right:30px}
      #tb-bulkbar{gap:10px;align-items:center;flex-wrap:wrap;margin:0 0 12px;padding:10px 12px;
        border:1px solid var(--line);border-radius:10px;background:var(--card)}
      /* Load-bearing: the bar carries .row (display:flex), and an author display rule BEATS the UA
         [hidden]{display:none}. Without this the hidden attribute did nothing and the empty bar
         showed as a stray white strip under the filters on every load. Same trap as .ctxbar.
         (No backticks in this comment -- it lives inside a template literal.) */
      #tb-bulkbar[hidden]{display:none}
      #tb-bulkbar select{height:30px;font-size:12px;width:auto;min-width:130px}

      /* THROUGHPUT (WP 6.2). A plain flex bar chart -- no charting library on this page, and one
         would be absurd for eight numbers. */
      .tp-chart{display:flex;align-items:flex-end;gap:8px;height:120px;padding:0 2px;
        border-bottom:1px solid var(--line)}
      .tp-col{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:flex-end;
        height:100%;gap:4px}
      .tp-bar{width:100%;max-width:46px;border-radius:5px 5px 0 0;background:var(--accent);
        min-height:2px}
      /* The partial week reads as provisional rather than as a cliff. */
      .tp-bar.tp-partial{background:repeating-linear-gradient(45deg,var(--accent),var(--accent) 4px,
        transparent 4px,transparent 8px);border:1px dashed var(--accent);opacity:.75}
      .tp-n{font-size:11px;color:var(--muted)}
      .tp-clients{list-style:none;margin:0;padding:0;max-width:420px}
      .tp-clients li{display:flex;justify-content:space-between;gap:12px;padding:7px 0;
        border-bottom:1px solid var(--line-soft);font-size:13px}`;
    document.head.appendChild(st);
  }

  const [vocab, clients, teams, people, templates] = await Promise.all([
    S.api("/api/vocab"), S.api("/api/clients"), S.api("/api/teams"), S.api("/api/people"),
    S.api("/api/tasks/templates"),
  ]);
  const STATUSES = vocab.task_statuses;
  // Every status carries the client stage it projects onto (task_status_meta, decision D13), which
  // is how the UI asks "is this a DONE column?" without ever naming "Completed" — that label is
  // renameable in Manage and nothing may key off it (AGENTS.md §5).
  const STAGE_OF = Object.fromEntries((vocab.task_status_meta || []).map((s) => [s.name, s.stage]));
  const isDoneStatus = (st) => STAGE_OF[st] === "completed";
  const peopleById = Object.fromEntries(people.map((p) => [p.id, p]));
  const teamsById = Object.fromEntries(teams.map((t) => [t.id, t]));
  // Service templates that match a chosen department (team), by team name.
  const templatesForTeam = (teamId) => {
    const name = teamsById[teamId] ? teamsById[teamId].name : null;
    return name ? templates.filter((t) => t.dept === name) : [];
  };
  let filters = { client_id: "", team_id: "", priority: "", assignee_id: "" };
  let search = "";
  let overdueOnly = false;          // M9 — "what is late?" (see matches)
  // 🔴 "My work" is NOT the assignee filter (fixed 2026-08-05). `?assignee_id=` is a field filter —
  // it matches `Task.assigned_to_id` and nothing else, which is exactly what a manager asking "what
  // is on Jerome?" wants. But "assigned to me" also means owning a phase/step of somebody else's
  // card (task_perms.is_assigned), so pointing this button at that filter hid the delegated work it
  // exists to surface. It is a client-side flag over the server's own `mine` now, so the button and
  // the Overview's strip can never disagree about the count.
  let mineOnly = false;
  let selection = new Set();        // M7 — ids ticked for a bulk action
  let allTasks = [];          // last fetch, unfiltered by the text search
  // View: "board" (status Kanban) | "employee" (swimlanes per person) | "monitor" (manager rollup).
  const params0 = new URLSearchParams(location.search);
  let mode = params0.get("view") || "board";
  if ((mode === "monitor") && !canMonitor) mode = "board";
  if (!["board", "employee", "monitor"].includes(mode)) mode = "board";
  // Employees/interns see only the tasks ASSIGNED to them — including no Atrium client card, which
  // is assigned to nobody here (the server enforces both in task_perms.can_view /
  // can_view_atrium). So the multi-person views and the assignee filter are noise: plain board only.
  if (!canMonitor) mode = "board";

  // Section-style header (h3) so the board reads as a dashboard section, not a second page title.
  root.innerHTML = `<div class="pagehead" style="margin:30px 0 14px"><div><h3 style="font-size:18px;letter-spacing:-.01em">Task Board</h3>
      <div class="lead" id="tb-lead"></div></div>
      <div class="row" style="gap:10px;align-items:center">
        ${canMonitor ? `<div class="seg" id="view-seg" role="tablist">
          <button type="button" data-view="board" role="tab">Board</button>
          <button type="button" data-view="employee" role="tab">By Employee</button>
          <button type="button" data-view="monitor" role="tab">Monitor</button>
        </div>` : ""}
        ${canManage ? `<button class="btn ghost" id="tb-requests" title="What clients have asked for, awaiting triage">Requests<span id="tb-req-n" class="pill violet" style="margin-left:6px" hidden></span></button>` : ""}
        <button class="btn ghost" id="filed-by-me" title="Work you raised for another team, and where it went">Filed by me</button>
        <button class="btn ghost" id="past-work" title="Completed work that has been filed">Past work</button>
        ${canCreate ? `<button class="btn primary" id="new-task">${S.ICON.plus}New Task</button>` : ""}
      </div></div>
    <div class="filters">
      <input id="f-search" class="tb-search" type="search" placeholder="Search tasks…" autocomplete="off">
      <select id="f-client"><option value="">All Clients</option>${clients.map((c) => `<option value="${c.id}">${S.esc(c.name)}</option>`).join("")}</select>
      <select id="f-team"><option value="">All Departments</option>${teams.map((t) => `<option value="${t.id}">${S.esc(t.name)}</option>`).join("")}</select>
      <select id="f-priority"><option value="">All Priority</option>${vocab.priorities.map((p) => `<option>${p}</option>`).join("")}</select>
      ${canMonitor ? `<select id="f-assignee"><option value="">All Assignees</option><option value="none">Unassigned</option>${people.map((p) => `<option value="${p.id}">${S.esc(p.name)}</option>`).join("")}</select>` : ""}
      <label class="chip" style="cursor:pointer" title="Only tasks past their due date (Manila), excluding finished work"><input type="checkbox" id="f-overdue"> Overdue</label>
      <button type="button" class="btn sm ghost" id="f-mine" title="Just the work assigned to me">My work</button>
      <select id="f-view" title="Saved views"><option value="">Saved views…</option></select>
      <button type="button" class="btn sm ghost" id="f-save-view">Save view</button>
      ${!readOnly ? `<button type="button" class="btn sm ghost" id="tb-select-toggle" title="Pick several cards and change them together">Select</button>` : ""}
    </div>
    <div id="tb-bulkbar" class="row" hidden></div>
    <div id="board"></div>`;

  const LEADS = {
    board: canMonitor
      ? "Drag cards across columns. Client cards from Atrium are editable here too — every edit writes straight back to Atrium."
      : "Your tasks — the work assigned to you. Drag cards across columns to update status.",
    employee: "Every teammate's tasks, grouped by person. Drag a card between columns to change its status.",
    monitor: "Team workload at a glance: open work, what's overdue, and what shipped this week. Click a row to see that person's tasks.",
  };

  // --- Saved views (M8, WP 5.4) -----------------------------------------------------------------
  // Every manager re-applied the same four filters on every visit. Stored per browser, like the
  // board's other preferences — these are one person's working habits, not org configuration, so
  // they do not belong in the database.
  const VIEWS_KEY = "sentinel.tb.views";
  const readViews = () => {
    try { return JSON.parse(localStorage.getItem(VIEWS_KEY) || "{}"); } catch (e) { return {}; }
  };
  const writeViews = (v) => {
    try { localStorage.setItem(VIEWS_KEY, JSON.stringify(v)); } catch (e) { /* private mode */ }
  };
  const currentView = () => ({ filters: { ...filters }, search, overdueOnly, mineOnly, mode });

  function applyView(v) {
    if (!v) return;
    filters = { client_id: "", team_id: "", priority: "", assignee_id: "", ...(v.filters || {}) };
    search = v.search || "";
    overdueOnly = !!v.overdueOnly;
    mineOnly = !!v.mineOnly;
    if (v.mode && (v.mode !== "monitor" || canMonitor)) mode = v.mode;
    // Push the restored state back into the controls, or the board would filter by values the
    // filter bar is not showing — which reads as a bug, not a view.
    S.qs("#f-client").value = filters.client_id;
    S.qs("#f-team").value = filters.team_id;
    S.qs("#f-priority").value = filters.priority;
    if (S.qs("#f-assignee")) S.qs("#f-assignee").value = filters.assignee_id;
    S.qs("#f-search").value = search;
    S.qs("#f-overdue").checked = overdueOnly;
    S.qs("#f-mine").classList.toggle("on", mineOnly);
    load();
  }

  S.qs("#f-search").oninput = (e) => { search = e.target.value.trim().toLowerCase(); render(); };
  S.qs("#f-client").onchange = (e) => { filters.client_id = e.target.value; load(); };
  S.qs("#f-team").onchange = (e) => { filters.team_id = e.target.value; load(); };
  S.qs("#f-priority").onchange = (e) => { filters.priority = e.target.value; load(); };
  if (S.qs("#f-assignee")) S.qs("#f-assignee").onchange = (e) => { filters.assignee_id = e.target.value; load(); };
  if (canCreate) S.qs("#new-task").onclick = () => taskForm(null);
  S.qs("#past-work").onclick = () => showPastWork();
  S.qs("#filed-by-me").onclick = () => showFiledByMe();

  S.qsa("#view-seg button").forEach((b) => b.onclick = () => setMode(b.dataset.view));

  // --- M9 overdue + M8 saved views ---------------------------------------------------------
  S.qs("#f-overdue").onchange = (e) => { overdueOnly = e.target.checked; render(); };

  // "My work" is the default M8 asks for, built in rather than saved: it is the same answer for
  // everyone and should not need setting up once per person. A TOGGLE, because the one thing you do
  // after narrowing the board to your own work is widen it back, and there was no way to.
  S.qs("#f-mine").onclick = () => applyView(mineOnly ? { mode } : {
    filters: {}, search: "", overdueOnly: false, mineOnly: true, mode: "board",
  });

  const viewSel = S.qs("#f-view");
  function refreshViewList() {
    const names = Object.keys(readViews()).sort((a, b) => a.localeCompare(b));
    viewSel.innerHTML = `<option value="">Saved views…</option>`
      + names.map((n) => `<option value="${S.esc(n)}">${S.esc(n)}</option>`).join("")
      + (names.length ? `<option value="__del">Delete a view…</option>` : "");
  }
  refreshViewList();
  viewSel.onchange = () => {
    const pick = viewSel.value;
    viewSel.value = "";
    if (!pick) return;
    if (pick === "__del") {
      const name = prompt("Delete which view?\n\n" + Object.keys(readViews()).join("\n"));
      if (!name) return;
      const all = readViews();
      if (!(name in all)) { S.toast("No view called " + name, "err"); return; }
      delete all[name];
      writeViews(all); refreshViewList(); S.toast("View deleted", "ok");
      return;
    }
    applyView(readViews()[pick]);
  };
  S.qs("#f-save-view").onclick = () => {
    const name = (prompt("Save the current filters as:") || "").trim();
    if (!name || name === "__del") return;
    const all = readViews();
    all[name] = currentView();
    writeViews(all); refreshViewList();
    S.toast(`Saved "${name}"`, "ok");
  };

  // --- M7 bulk actions ---------------------------------------------------------------------
  // Selection mode is OPT-IN: a permanent checkbox on every card is clutter on a board people
  // mostly read, and it competes with drag-and-drop for the same pointer.
  let selecting = false;
  const bulkBar = S.qs("#tb-bulkbar");
  const selectBtn = S.qs("#tb-select-toggle");

  function bulkOptions() {
    // Only offer what this actor can actually do, so the bar never promises a 403.
    const status = `<select id="bk-status"><option value="">Move to…</option>${STATUSES.map((s) => `<option>${S.esc(s)}</option>`).join("")}</select>`;
    const prio = canPrioritizeOnForm ? `<select id="bk-prio"><option value="">Priority…</option>${vocab.priorities.map((p) => `<option>${S.esc(p)}</option>`).join("")}</select>` : "";
    const who = canMonitor ? `<select id="bk-who"><option value="">Assign to…</option><option value="none">Unassigned</option>${people.map((p) => `<option value="${p.id}">${S.esc(p.name)}</option>`).join("")}</select>` : "";
    return status + prio + who;
  }

  function renderBulkBar() {
    if (!selecting) { bulkBar.hidden = true; bulkBar.innerHTML = ""; return; }
    bulkBar.hidden = false;
    bulkBar.innerHTML = `<span class="section-label" id="bk-count">${selection.size} selected</span>
      ${bulkOptions()}
      <button type="button" class="btn sm ghost" id="bk-all">Select all shown</button>
      <button type="button" class="btn sm ghost" id="bk-none">Clear</button>`;
    const run = async (op, value) => {
      if (!selection.size) { S.toast("Nothing selected", "err"); return; }
      try {
        const res = await S.api("/api/tasks/bulk", {
          method: "POST", body: { ids: [...selection], op, value },
        });
        // 🔴 Report the skips. Partial success is the contract, and silently moving 7 of 10 cards
        // while the board redraws is exactly how someone loses track of the other three.
        const { updated, skipped } = res;
        if (skipped.length) {
          const why = [...new Set(skipped.map((s) => s.reason))].join("; ");
          S.toast(`${updated.length} updated · ${skipped.length} skipped — ${why}`, updated.length ? "ok" : "err");
        } else {
          S.toast(`${updated.length} updated`, "ok");
        }
        selection.clear();
        load();
      } catch (err) { S.toast(err.detail || "Bulk update failed", "err"); }
    };
    const st = S.qs("#bk-status");
    st.onchange = () => { const v = st.value; st.value = ""; if (v) run("status", v); };
    const pr = S.qs("#bk-prio");
    if (pr) pr.onchange = () => { const v = pr.value; pr.value = ""; if (v) run("priority", v); };
    const wh = S.qs("#bk-who");
    if (wh) wh.onchange = () => {
      const v = wh.value; wh.value = "";
      if (v) run("assignee", v === "none" ? null : Number(v));
    };
    S.qs("#bk-all").onclick = () => {
      // "Shown" needs no visibility test: this board REBUILDS its columns from the filtered list
      // (renderBoard takes `tasks.filter(matches)`), so every .tcard in the DOM is by definition a
      // card the current filters kept. An earlier version gated on `offsetParent !== null`, which
      // is a layout question — it selected nothing wherever layout is not computed.
      // Atrium-owned cards live in another system and the endpoint refuses their composite ids,
      // so they stay out — offering them could only ever produce a skip.
      S.qsa(".tcard").forEach((c) => {
        if (!String(c.dataset.id).startsWith("atrium:")) selection.add(Number(c.dataset.id));
      });
      syncSelection();
    };
    S.qs("#bk-none").onclick = () => { selection.clear(); syncSelection(); };
  }

  function syncSelection() {
    S.qsa(".tcard").forEach((c) => {
      const box = c.querySelector(".t-pick");
      if (box) box.checked = selection.has(Number(c.dataset.id));
      c.classList.toggle("picked", selection.has(Number(c.dataset.id)));
    });
    const n = S.qs("#bk-count");
    if (n) n.textContent = `${selection.size} selected`;
  }

  function wirePickers() {
    S.qsa(".t-pick").forEach((box) => {
      box.onclick = (e) => e.stopPropagation();      // ticking must not open the card
      box.onchange = (e) => {
        e.stopPropagation();
        const id = Number(box.closest(".tcard").dataset.id);
        if (box.checked) selection.add(id); else selection.delete(id);
        syncSelection();
      };
    });
    syncSelection();
  }

  if (selectBtn) {
    selectBtn.onclick = () => {
      selecting = !selecting;
      selectBtn.classList.toggle("primary", selecting);
      selectBtn.textContent = selecting ? "Done" : "Select";
      if (!selecting) selection.clear();
      renderBulkBar();
      render();
    };
  }

  // --- The client intake queue (D3, WP 3.3) ------------------------------------------------
  // A client's ask is NOT a task. It waits here until a manager accepts it, at which point it
  // becomes ordinary work; declining is a first-class outcome and needs a reason, because "we
  // are not doing this, because…" is an answer the client is owed.
  async function refreshRequestCount() {
    const badge = S.qs("#tb-req-n");
    if (!badge) return;
    try {
      const { pending } = await S.api("/api/tasks/requests?status=pending");
      badge.textContent = pending;
      badge.hidden = !pending;      // no badge at all when the queue is empty, not a "0"
    } catch (e) { badge.hidden = true; }
  }

  async function openRequests() {
    let data;
    try { data = await S.api("/api/tasks/requests?status=pending"); }
    catch (err) { S.toast(err.detail || "Couldn't load the requests", "err"); return; }
    const rows = data.requests || [];
    const body = rows.length ? rows.map((r) => `
      <div class="card pad" data-req="${r.id}" style="margin-bottom:10px">
        <div class="row between" style="align-items:flex-start;gap:10px">
          <div style="min-width:0">
            <div style="font-weight:600">${S.esc(r.title)}</div>
            <div class="sub" style="font-size:12px;margin-top:2px">
              ${S.esc(r.client_name || r.client_key)}${r.requester_name ? " · " + S.esc(r.requester_name) : ""} · ${S.timeAgo(r.created_at)}
            </div>
            ${r.details ? `<div class="sub" style="margin-top:6px">${S.esc(r.details)}</div>` : ""}
          </div>
          <div class="row" style="gap:6px;flex:none">
            <select data-rq-team="${r.id}" title="Which department takes this on">
              <option value="">Department…</option>
              ${teams.map((tm) => `<option value="${tm.id}">${S.esc(tm.name)}</option>`).join("")}
            </select>
            <button class="btn sm primary" data-rq-accept="${r.id}">Accept</button>
            <button class="btn sm ghost" data-rq-decline="${r.id}">Decline</button>
          </div>
        </div>
      </div>`).join("")
      : `<div class="empty card pad">Nothing waiting. Client asks filed from Atrium land here.</div>`;

    const m = S.modal({
      title: "Client requests",
      wide: true,
      body: `<div class="lead" style="margin-bottom:12px">Asks filed by clients from their Atrium workspace. Accepting one turns it into a task on this board; declining records why.</div>${body}`,
      footer: `<button class="btn ghost" id="rq-close">Close</button>`,
    });
    S.qs("#rq-close").onclick = m.close;

    const after = async (msg) => {
      S.toast(msg, "ok");
      m.close();
      await refreshRequestCount();
      load();
    };
    S.qsa("[data-rq-accept]").forEach((b) => b.onclick = async () => {
      const id = b.dataset.rqAccept;
      const teamSel = S.qs(`[data-rq-team="${id}"]`);
      b.disabled = true;
      try {
        await S.api(`/api/tasks/requests/${id}/accept`, {
          method: "POST",
          body: { assigned_team_id: teamSel && teamSel.value ? Number(teamSel.value) : null },
        });
        await after("Accepted — it is on the board now");
      } catch (err) { b.disabled = false; S.toast(err.detail || "Couldn't accept that", "err"); }
    });
    S.qsa("[data-rq-decline]").forEach((b) => b.onclick = async () => {
      const reason = (prompt("Why are we not doing this? The client is owed a reason.") || "").trim();
      if (!reason) return;
      b.disabled = true;
      try {
        await S.api(`/api/tasks/requests/${b.dataset.rqDecline}/decline`,
                    { method: "POST", body: { reason } });
        await after("Declined, with the reason on record");
      } catch (err) { b.disabled = false; S.toast(err.detail || "Couldn't decline that", "err"); }
    });
  }

  if (S.qs("#tb-requests")) {
    S.qs("#tb-requests").onclick = openRequests;
    refreshRequestCount();
  }

  function setMode(next) {
    mode = next;
    const u = new URLSearchParams(location.search);
    if (next === "board") u.delete("view"); else u.set("view", next);
    history.replaceState(null, "", location.pathname + (u.toString() ? "?" + u : ""));
    render();
  }

  // Fetch (filters hit the server), then hand off to the active view's renderer.
  async function load() {
    const q = new URLSearchParams();
    Object.entries(filters).forEach(([k, v]) => { if (v) q.set(k, v); });
    // "Unassigned" is a choice, not an id: it becomes its own flag so assignee_id stays an int
    // server-side (?unassigned=1 — see list_tasks).
    if (filters.assignee_id === "none") { q.delete("assignee_id"); q.set("unassigned", "1"); }
    allTasks = await S.api("/api/tasks?" + q);
    render();
  }

  // The text search is applied client-side so typing never re-hits the server.
  function matches(t) {
    // "My work" — the server's `mine` (task_perms.is_assigned: the card's lead OR any phase/step of
    // its breakdown), never `t.assigned_to_id === S.user.id`. An Atrium-owned card carries no flag
    // and correctly drops out: its owners are roster emails, not Sentinel users.
    if (mineOnly && !t.mine) return false;
    // OVERDUE (M9, WP 5.4). The board only ever TINTED the due chip; there was no way to ask
    // "what is late?" — the one question a morning triage starts with. Client-side because the
    // cards are already here, and compared against PH_TODAY so it agrees with the server's
    // Asia/Manila business rule rather than the viewer's timezone.
    // A finished task is never overdue: its due date stopped mattering when it was completed.
    if (overdueOnly && !(t.due_date && t.due_date < PH_TODAY && !isDoneStatus(t.status))) return false;
    if (!search) return true;
    return [t.title, t.assignee && t.assignee.name, t.client_name]
      .some((s) => (s || "").toLowerCase().includes(search));
  }

  function render() {
    S.qs("#tb-lead").textContent = LEADS[mode];
    S.qsa("#view-seg button").forEach((b) => b.classList.toggle("on", b.dataset.view === mode));
    S.qs("#f-search").closest(".filters").style.display = mode === "monitor" ? "none" : "";
    const board = S.qs("#board");
    board.className = mode === "board" ? "board" : "";
    const tasks = allTasks.filter(matches);
    if (mode === "monitor") return renderMonitor(board);
    if (mode === "employee") return renderByEmployee(board, tasks);
    return renderBoard(board, tasks);
  }

  function renderBoard(board, tasks) {
    const byStatus = Object.fromEntries(STATUSES.map((s) => [s, []]));
    tasks.forEach((t) => (byStatus[t.status] || (byStatus[t.status] = [])).push(t));
    board.className = "board";
    board.innerHTML = STATUSES.map((st) => `
      <div class="col" data-status="${S.esc(st)}">
        <div class="col-head"><span class="t">${S.esc(st)}</span><span class="c">${byStatus[st].length}</span></div>
        <div class="col-list" data-status="${S.esc(st)}">${byStatus[st].map(card).join("")}</div>
        ${canCreate ? `<button class="col-add" data-status="${S.esc(st)}">${S.ICON.plus}<span>Add card</span></button>` : ""}
      </div>`).join("");
    wireDnD();
    wireAddButtons();
    wireCardClicks();
    wireMoveSelects();
    wirePickers();
  }

  // Swimlanes: one lane per person that has tasks, plus an Unassigned lane. Cards sit in mini
  // status columns inside the lane; drag stays WITHIN a lane (moving between people would be a
  // reassignment, which belongs in the detail drawer, not a drag).
  function renderByEmployee(board, tasks) {
    const byUser = new Map();
    tasks.forEach((t) => {
      const key = t.assigned_to_id == null ? "none" : t.assigned_to_id;
      if (!byUser.has(key)) byUser.set(key, []);
      byUser.get(key).push(t);
    });
    // Order: named people (alpha) first, Unassigned last.
    const keys = [...byUser.keys()].filter((k) => k !== "none")
      .sort((a, b) => (peopleById[a]?.name || "").localeCompare(peopleById[b]?.name || ""));
    if (byUser.has("none")) keys.push("none");

    if (!keys.length) { board.innerHTML = `<div class="empty">No tasks match.</div>`; return; }

    board.className = "swimlanes";
    board.innerHTML = keys.map((k) => {
      const person = k === "none" ? null : peopleById[k];
      const list = byUser.get(k);
      const byStatus = Object.fromEntries(STATUSES.map((s) => [s, []]));
      list.forEach((t) => (byStatus[t.status] || (byStatus[t.status] = [])).push(t));
      const head = person
        ? `${S.avatar(person, "sm")}<div class="ln"><div class="n">${S.esc(person.name)}</div><div class="r">${S.esc(person.role_label || person.role || "")}</div></div>`
        : `<div class="avatar sm">–</div><div class="ln"><div class="n">Unassigned</div></div>`;
      return `<section class="lane" data-uid="${k}">
        <div class="lane-head">${head}<span class="lane-count">${list.length}</span></div>
        <div class="lane-board">${STATUSES.map((st) => `
          <div class="col" data-status="${S.esc(st)}">
            <div class="col-head"><span class="t">${S.esc(st)}</span><span class="c">${byStatus[st].length}</span></div>
            <div class="col-list" data-status="${S.esc(st)}" data-uid="${k}">${byStatus[st].map(card).join("")}</div>
          </div>`).join("")}</div>
      </section>`;
    }).join("");
    wireDnD({ sameLane: true });
    wireCardClicks();
    wireMoveSelects({ sameLane: true });
    wirePickers();
  }

  async function renderMonitor(board) {
    board.className = "monitor";
    board.innerHTML = `<div class="skeleton-row">Loading team…</div>`;
    let rows;
    try { rows = await S.api("/api/tasks/summary"); }
    catch (err) { board.innerHTML = `<div class="empty">${S.esc(err.detail || "Couldn't load the team summary.")}</div>`; return; }
    if (!rows.length) { board.innerHTML = `<div class="empty">No teammates to show.</div>`; return; }
    // 🔴 Derived from the live vocabulary and coloured by STAGE, never by the status LABEL. This
    // was a hardcoded four-name list, which had two failure modes that look identical to the
    // reader — a silently missing segment. (1) Renaming a column in Manage (WP 1.2 renamed Blocked
    // to Parked) dropped its work off every workload bar, because `r.counts` is keyed by the
    // current label. (2) A status somebody ADDED was never counted at all, so a teammate with ten
    // cards in it read as idle. The bar shows OPEN work, so completed-stage columns are excluded
    // — everything else earns a segment whatever it is called.
    const SEG_CLS = { todo: "s-todo", in_progress: "s-prog", revision: "s-rev", blocked: "s-block" };
    const barSegs = STATUSES.filter((s) => STAGE_OF[s] !== "completed");
    const segCls = Object.fromEntries(barSegs.map((s) => [s, SEG_CLS[STAGE_OF[s]] || "s-todo"]));
    board.innerHTML = `<table class="mon-tbl">
      <thead><tr><th>Teammate</th><th>Workload</th><th class="num">Open</th><th class="num">Overdue</th><th class="num">Done · 7d</th></tr></thead>
      <tbody>${rows.map((r) => {
        const u = r.user;
        const open = r.open_total || 0;
        const segs = barSegs.map((st) => { const n = r.counts[st] || 0; return n ? `<i class="${segCls[st]}" style="flex:${n}" title="${S.esc(st)}: ${n}"></i>` : ""; }).join("");
        return `<tr data-uid="${u.id}" tabindex="0">
          <td class="who">${S.avatar(u, "sm")}<div><div class="n">${S.esc(u.name)}</div><div class="r">${S.esc(u.role_label || u.role || "")}</div></div></td>
          <td class="wl"><div class="wl-bar">${segs || '<i class="s-none" style="flex:1" title="No open tasks"></i>'}</div></td>
          <td class="num">${open}</td>
          <td class="num ${r.overdue ? "bad" : ""}">${r.overdue || 0}</td>
          <td class="num good">${r.completed_week || 0}</td>
        </tr>`;
      }).join("")}</tbody></table>`;
    const jump = (uid) => { setMode("employee"); requestAnimationFrame(() => focusLane(uid)); };
    S.qsa(".mon-tbl tbody tr").forEach((tr) => {
      tr.onclick = () => jump(tr.dataset.uid);
      tr.onkeydown = (e) => { if (e.key === "Enter") jump(tr.dataset.uid); };
    });
    renderThroughput(board);
  }

  // WP 6.2 (§2.4i): Monitor was a snapshot — no trend, no history, no per-client view. Appended
  // after the roster paints and fails SILENTLY: a trend is context, and losing it must never cost
  // a manager the workload table they came for.
  async function renderThroughput(board) {
    let data;
    try { data = await S.api("/api/tasks/throughput?weeks=8"); }
    catch (e) { return; }
    const weeks = data.weeks || [];
    if (!weeks.length) return;
    const peak = Math.max(1, ...weeks.map((w) => w.completed));
    const bars = weeks.map((w) => {
      // 🔴 The current week is PARTIAL. It is drawn, because people want to see it, but marked —
      // a 2-day week next to full ones otherwise reads as a collapse that never happened.
      const h = Math.round(100 * w.completed / peak);
      const label = w.complete ? `Week of ${w.week_start}: ${w.completed} shipped`
                               : `This week so far: ${w.completed} shipped (still running)`;
      return `<div class="tp-col" title="${S.esc(label)}">
        <div class="tp-bar${w.complete ? "" : " tp-partial"}" style="height:${Math.max(h, 2)}%"></div>
        <span class="tp-n">${w.completed}</span>
      </div>`;
    }).join("");
    const clients = (data.by_client || []).slice(0, 5).map((c) =>
      `<li><span>${S.esc(c.client_name)}</span><b>${c.completed}</b></li>`).join("");

    const wrap = document.createElement("div");
    wrap.className = "tp-wrap";
    wrap.innerHTML = `<div class="row between" style="align-items:baseline;margin:26px 0 10px">
        <div class="section-label">Throughput · last ${weeks.length} weeks</div>
        <span class="sub" style="font-size:12px">${data.weekly_average} / week on average<span class="muted"> · complete weeks only</span></span>
      </div>
      <div class="tp-chart">${bars}</div>
      ${clients ? `<div class="section-label" style="margin:22px 0 8px">Shipped by client</div>
        <ul class="tp-clients">${clients}</ul>` : ""}`;
    board.appendChild(wrap);
  }

  function focusLane(uid) {
    const lane = S.qs(`.lane[data-uid="${uid}"]`);
    if (!lane) return;
    lane.scrollIntoView({ behavior: "smooth", block: "start" });
    lane.classList.remove("flash"); requestAnimationFrame(() => lane.classList.add("flash"));
  }

  // Atrium-bridged cards (t.source === "atrium") have no local Task row -- their id is the string
  // "atrium:<client_key>:<task_id>". They open in the SAME drawer: /api/tasks/{id} reads them back
  // across the bridge and every write from the drawer is routed to Atrium. (Until 2026-07-29 this
  // showed "open it in Atrium to view or edit", which is a dead end, not an answer -- the team
  // works this board, so the board has to edit the work.)
  function openTask(id) {
    openDetail(id);
  }

  function wireCardClicks() {
    // Some browsers still dispatch a click on the source element right after a completed native
    // drag (the "dragging" class is already gone by then, since dragend clears it synchronously) --
    // wireDnD also stamps a short-lived data-just-dragged flag so that trailing click is swallowed
    // instead of reopening the drawer on the card that was just moved.
    S.qsa(".tcard").forEach((c) => c.onclick = () => { if (!c.classList.contains("dragging") && !c.dataset.justDragged) openTask(c.dataset.id); });
    // The hover ✕ deletes in place (confirm first — deletion is irreversible). stopPropagation
    // so the click doesn't also open the detail drawer.
    S.qsa(".t-del").forEach((b) => b.onclick = (e) => {
      e.stopPropagation();
      const t = allTasks.find((x) => String(x.id) === b.dataset.del);
      if (t) confirmDelete(t);
    });
  }

  // "Today" in Manila as an ISO date (en-CA → YYYY-MM-DD), so due-date colouring matches the
  // server's Asia/Manila business rule instead of the viewer's local timezone.
  const PH_TODAY = new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Manila" });
  function dueClass(due) {
    if (!due) return "";
    if (due < PH_TODAY) return "over";
    const days = (Date.parse(due + "T00:00:00Z") - Date.parse(PH_TODAY + "T00:00:00Z")) / 864e5;
    return days <= 2 ? "soon" : "";
  }

  // Where the review stands, small enough for a card. Nothing for a task nobody has submitted —
  // most tasks, most of the time, and a pill on all of them would say nothing.
  const REVIEW_PILL = {
    pending: '<span class="pill amber" style="font-size:9px" title="Waiting on a lead\'s approval">◷ review</span>',
    approved: '<span class="pill green" style="font-size:9px" title="Approved — it can be completed">✓ approved</span>',
    changes_requested: '<span class="pill red" style="font-size:9px" title="Changes requested">↺ changes</span>',
  };

  // Filing only makes sense at the two ends: a finished task can be filed, a filed one can come
  // back. Unfinished work that has to leave the board gets PARKED — the server refuses to file it.
  function filingBtn(t, done) {
    if (t.archived) return `<button class="btn ghost" id="d-unarchive">Back on the board</button>`;
    return done ? `<button class="btn ghost" id="d-archive">File to Past work</button>` : "";
  }

  function card(t) {
    const dueCls = dueClass(t.due_date);
    // An Atrium-owned card cannot be bulk-edited (it lives in another system and the endpoint
    // refuses composite ids), so it never gets a checkbox — better than offering one that only
    // ever produces a skip.
    const pickable = selecting && !String(t.id).startsWith("atrium:");
    return `<div class="tcard" draggable="true" data-id="${t.id}">
      ${pickable ? `<input type="checkbox" class="t-pick" aria-label="Select ${S.esc(t.title)}">` : ""}
      ${t.labels.length ? `<div class="labels">${S.labelPills(t.labels)}</div>` : ""}
      <div class="t-title">${S.esc(t.title)}</div>
      <div class="t-meta">${S.priorityDot(t.priority)}<span>${S.esc(t.priority)}</span>
        ${t.due_date ? `<span class="due ${dueCls}">· ${S.fmtDate(t.due_date + "T00:00:00+08:00")}</span>` : ""}
        ${t.client_name ? `<span class="muted">· ${S.esc(t.client_name)}</span>` : ""}
        ${t.created_by ? `<span class="muted" title="Created by ${S.esc(t.created_by.name)}">· by ${S.esc(t.created_by.name.split(" ")[0])}</span>` : ""}</div>
      <div class="t-foot">
        <div class="row">${t.assignee ? S.avatar(t.assignee, "sm") + `<span class="sub" style="font-size:12px">${S.esc(t.assignee.name.split(" ")[0])}</span>` : '<span class="muted" style="font-size:12px">Unassigned</span>'}</div>
        <div class="icons">${t.on_hold ? '<span class="pill amber" style="font-size:9px" title="Parked — see the card for why">⏸ parked</span>' : ""}${REVIEW_PILL[t.review_state] || ""}${t.atrium_sync_error ? '<span class="pill red" style="font-size:9px" title="The client copy of this card is out of date">⚠ stale</span>' : ""}${t.comment_count ? S.ICON.comment + t.comment_count : ""} ${t.attachment_count ? S.ICON.paperclip + t.attachment_count : ""} ${t.checklist_total ? `<span title="checklist">${t.checklist_done}/${t.checklist_total}</span>` : ""}</div>
      </div>
      ${canDelete(t) ? `<button class="t-del" data-del="${t.id}" title="Delete task" aria-label="Delete task">✕</button>` : ""}
      ${!readOnly ? `<select class="t-move" data-move="${t.id}" aria-label="Move ${S.esc(t.title)} to another column">${STATUSES.map((s) => `<option ${s === t.status ? "selected" : ""}>${S.esc(s)}</option>`).join("")}</select>` : ""}</div>`;
  }

  // The mobile/keyboard twin of drag-and-drop (WP 5.5). It routes through the SAME `moveCard`, so
  // the optimistic reposition, the Undo toast and the roll-back on failure are identical however
  // the move was made — there is no second move path to keep in step.
  function wireMoveSelects(opts = {}) {
    S.qsa(".t-move").forEach((sel) => {
      // Interacting with the control must never open the card underneath it.
      sel.onclick = (e) => e.stopPropagation();
      sel.onchange = (e) => {
        e.stopPropagation();
        const cardEl = sel.closest(".tcard");
        const fromList = cardEl.closest(".col-list");
        if (!fromList || fromList.dataset.status === sel.value) return;
        // In swimlanes every lane repeats the same columns, so the target has to be matched
        // WITHIN this card's lane — otherwise the card would jump to another person's row, which
        // is a reassignment, and those belong in the drawer (same rule wireDnD enforces).
        const scope = opts.sameLane ? cardEl.closest(".lane") : document;
        const toList = [...scope.querySelectorAll(".col-list")]
          .find((l) => l.dataset.status === sel.value);
        if (!toList) return;
        moveCard(cardEl, toList, sel.value, fromList, fromList.dataset.status);
      };
    });
  }

  function wireDnD(opts = {}) {
    let dragEl = null;
    S.qsa(".tcard").forEach((c) => {
      c.ondragstart = (e) => { dragEl = c; c.classList.add("dragging"); e.dataTransfer.effectAllowed = "move"; };
      c.ondragend = () => {
        c.classList.remove("dragging");
        S.qsa(".col.drag-over").forEach((x) => x.classList.remove("drag-over"));
        // See wireCardClicks: swallow exactly one trailing click, in case this browser fires one
        // after the drag instead of suppressing it.
        c.dataset.justDragged = "1";
        setTimeout(() => { delete c.dataset.justDragged; }, 0);
      };
    });
    S.qsa(".col-list").forEach((list) => {
      const col = list.closest(".col");
      list.ondragover = (e) => { e.preventDefault(); col.classList.add("drag-over"); };
      list.ondragleave = (e) => { if (!list.contains(e.relatedTarget)) col.classList.remove("drag-over"); };
      list.ondrop = (e) => {
        e.preventDefault(); col.classList.remove("drag-over");
        if (!dragEl) return;
        const fromList = dragEl.closest(".col-list");
        // In swimlanes, only allow moves within the same person's lane (status change, not reassign).
        const sameLane = !opts.sameLane || fromList.dataset.uid === list.dataset.uid;
        if (fromList !== list && sameLane) moveCard(dragEl, list, list.dataset.status, fromList, fromList.dataset.status);
        dragEl = null;
      };
    });
  }

  // Recount every column header from the DOM (after an optimistic move).
  function updateCounts() {
    S.qsa(".col").forEach((col) => {
      const c = col.querySelector(".col-head .c");
      if (c) c.textContent = col.querySelectorAll(".col-list > .tcard").length;
    });
  }

  // Optimistic move: reposition the card immediately, sync in the background, roll back on failure.
  async function moveCard(cardEl, toList, toStatus, fromList, fromStatus, opts = {}) {
    const id = cardEl.dataset.id;
    toList.appendChild(cardEl);
    // Keep the card's own move control showing where the card now IS. Without this a drag (or an
    // Undo) leaves the select reading the previous column, and the next change event can look
    // like a no-op and be swallowed by the equality guard in wireMoveSelects.
    const sel = cardEl.querySelector(".t-move");
    if (sel) sel.value = toStatus;
    updateCounts();
    cardEl.classList.remove("just-moved");
    requestAnimationFrame(() => cardEl.classList.add("just-moved"));   // restart the flash
    try {
      await S.api(`/api/tasks/${id}/status`, { method: "PATCH", body: { status: toStatus } });
      if (!opts.silent) {
        S.toast("Moved to " + toStatus, "ok", {
          action: { label: "Undo", onClick: () => moveCard(cardEl, fromList, fromStatus, toList, toStatus, { silent: true }) },
        });
      }
    } catch (err) {
      fromList.appendChild(cardEl);   // roll back the optimistic move
      updateCounts();
      S.toast(err.detail || "Couldn't move task", "err");
    }
  }

  // "Add card" at the foot of each column opens the SAME full form as Edit (not an inline
  // title box), pre-set to that column's status. Nothing is forced — a blank name saves as
  // "Untitled task" and can be renamed later.
  function wireAddButtons() {
    S.qsa(".col-add").forEach((btn) => btn.onclick = () => taskForm(null, btn.dataset.status));
  }

  // --- Opening a task -----------------------------------------------------------------------------
  // A wide centred modal (see the CSS note above for why not a docked panel). The URL still carries
  // `?open=<id>` — that is the param every task notification uses, so a shared link, a notification
  // and a click all land on the same card, and refreshing keeps the task open.
  function setOpenParam(id) {
    const u = new URLSearchParams(location.search);
    if (id) u.set("open", id); else u.delete("open");
    // replaceState, not pushState: opening six cards in a row must not bury the page under six
    // back-button steps.
    history.replaceState(null, "", location.pathname + (u.toString() ? "?" + u : ""));
  }

  // S.modal's ✕ / overlay-click / Esc all call ITS internal close directly, so wrapping the returned
  // `close` is not enough — the param would survive those three paths. Re-point them here instead.
  function openTaskModal(title, body, footer, id) {
    const m0 = S.modal({ title, body, footer, wide: true });
    const close = () => { setOpenParam(null); m0.close(); };
    if (S.qs("#modal-x")) S.qs("#modal-x").onclick = close;
    m0.root.onclick = (e) => { if (e.target === m0.root) close(); };
    document.addEventListener("keydown", function esc(e) {
      if (e.key !== "Escape") return;
      document.removeEventListener("keydown", esc);
      setOpenParam(null);          // S.modal's own Esc handler does the closing
    });
    setOpenParam(id);
    return { close };
  }

  async function openDetail(id) {
    let t;
    try { t = await S.api("/api/tasks/" + id); }
    catch (err) { S.toast(err.detail || "Couldn't open that task", "err"); return; }
    if (!Array.isArray(t.maintasks)) t.maintasks = [];
    // An Atrium-owned card opens in this SAME drawer, with Atrium's vocabulary: its owners come
    // from ATRIUM's roster (ids are login emails, not Sentinel user ids) and it has fields Sentinel
    // rows don't (department, lead/support, start date, hold, client visibility), so those render
    // from the atrium_* values the bridge sent. Every write below is routed back to Atrium by
    // /api/tasks/{id} — nothing about the card is stored here.
    const isAtrium = t.source === "atrium";
    const owners = isAtrium ? (t.atrium_roster || []) : people;
    const ownerId = (v) => (isAtrium ? (v || "") : (v ? +v : null));
    const prioritySelect = canPrioritize(t)
      ? `<select id="d-priority" style="margin-top:6px">${vocab.priorities.map((p) => `<option ${p === t.priority ? "selected" : ""}>${p}</option>`).join("")}</select>`
      : `<div style="margin-top:6px">${S.priorityDot(t.priority)} ${S.esc(t.priority)}</div>`;
    // The projection's state, said out loud. A push that failed leaves the CLIENT's copy stale
    // while ours is current, and a pre-fix row claims a share that never happened — neither may
    // look like a healthy share (see sentinel/AGENTS.md §5, "Send to Atrium used to publish NOTHING").
    // `.form-hint` is the house inline-notice box (styles.css:198); the amber edge is the
    // file's usual one-off inline style rather than a new class nobody else uses.
    const WARN = 'class="form-hint" style="margin-bottom:14px;border-left:3px solid var(--warn)"';
    const staleNote = (!isAtrium && t.atrium_sync_error)
      ? `<div ${WARN}><strong>The client's copy is out of date.</strong>
           ${S.esc(t.atrium_sync_error)} Your edits saved here — press <em>Retry the client push</em> to send them.</div>`
      : (!isAtrium && t.atrium_visible && !t.atrium_shared)
        ? `<div ${WARN}><strong>This was never actually shared.</strong>
             It is flagged as shared but no client card exists — a row predating the 2026-08-03 fix.
             Press <em>Share with the client</em> to create it for real.</div>`
        : "";
    // 🔴 WHAT THE CLIENT ASKED FOR, WHERE YOU ACTUALLY LOOK (2026-08-04).
    // The reverse channel (D4) delivered correctly from day one, and the card even showed a red
    // "1 change request" pill — but a pill is a COUNT. The words themselves went into the comment
    // thread, in the right-hand column, below the work breakdown, styled identically to a
    // colleague's note. So the board told you a client wanted something changed and never told you
    // WHAT, which is the one thing the team needs in order to act.
    //
    // Two reasons it was invisible rather than merely buried, both worth knowing before touching this:
    //   * `cmt()` renders a red "Changes requested" pill + a resolve button off `c.kind === "changes"`
    //     — but `kind` only exists on an ATRIUM-owned card (atrium_tasks.as_task_detail). A Sentinel
    //     row's comment comes from `serializers.comment_dict`, which has no `kind` to give: the
    //     receiver bumps `tasks.client_changes_open` and does not persist the kind per comment.
    //     So the flag is TASK-level, and the honest UI for it is task-level too — this banner.
    //   * `is_client` was exposed by the serializer, documented there as "what the UI keys off",
    //     and used by NOTHING. It is used now, both here and in `cmt()`.
    // The body shown is the newest client comment, which is what the counter refers to in practice.
    // Resolve posts to /resolve-client-changes (the TASK-level endpoint) — NOT the per-comment
    // Atrium route `wireResolve` uses, which does not exist for a Sentinel row.
    const clientSaid = (t.comments || []).filter((c) => c.is_client);
    const lastClient = clientSaid.length ? clientSaid[clientSaid.length - 1] : null;
    const changeNote = (t.open_changes && !isAtrium)
      ? `<div class="form-hint" style="margin-bottom:14px;border-left:3px solid var(--danger)">
           <strong>The client asked for changes.</strong>
           ${lastClient
             ? `<div style="margin:6px 0 8px;white-space:pre-wrap">${S.esc(String(lastClient.body || "").replace(/\n?\[atrium:[^\]]*\]/g, "").trim())}</div>
                <div class="meta">${S.esc(lastClient.author ? lastClient.author.name : "The client")} · ${S.timeAgo(lastClient.created_at)}</div>`
             : `<div class="meta">Their message is in the conversation below.</div>`}
           <button class="btn sm ghost" id="d-resolve-changes" style="margin-top:8px">Mark as handled</button>
         </div>`
      : "";
    // Park REMEMBERS the column the card left (tasks.resume_to), so say where Resume will put it —
    // otherwise the button is a guess. An Atrium card's hold has no such memory to show.
    const resumeHint = (!isAtrium && t.resume_to)
      ? ` · Resume puts it back in ${S.esc(t.resume_to)}` : "";
    const chips = [
      isAtrium ? `<span class="pill blue">Client card · ${S.esc(t.client_name || "Atrium")}</span>` : "",
      (!isAtrium && t.atrium_shared) ? `<span class="pill blue">Shared with the client</span>` : "",
      (!isAtrium && t.atrium_sync_error) ? `<span class="pill red">⚠ Client copy stale</span>` : "",
      t.on_hold ? `<span class="pill amber">On hold</span>` : "",
      t.archived ? `<span class="pill">Filed · Past work</span>` : "",
      t.review_state === "pending" ? `<span class="pill amber">Awaiting approval</span>` : "",
      t.review_state === "approved" ? `<span class="pill green">Approved${t.reviewer ? " by " + S.esc(t.reviewer.name) : ""}</span>` : "",
      t.review_state === "changes_requested" ? `<span class="pill red">Changes requested</span>` : "",
      t.open_changes ? `<span class="pill red">${t.open_changes} change request${t.open_changes > 1 ? "s" : ""}</span>` : "",
      (isAtrium && t.reporter === "client") ? `<span class="pill violet">Requested by ${S.esc(t.reporter_name || "the client")}</span>` : "",
    ].join("");
    const body = `<div class="tb-cols">
      <div>
        ${changeNote}
        ${staleNote}
        <div class="labels" style="margin-bottom:8px">${S.labelPills(t.labels)}${chips}</div>
        <h2 style="margin-bottom:6px">${S.esc(t.title)}</h2>
        <div class="sub">${S.esc(t.description || "")}</div>
        <div class="spread" style="margin-top:16px">
          ${field("Client", t.client_name)}
          ${/* Optional grouping field — shown only when set, so a task that is not part of a
                campaign does not carry an empty row (it used to echo the title back). */
            t.campaign ? field("Campaign", t.campaign) : ""}
          ${field("Content type", t.content_type)}
          ${field(isAtrium ? "Launch date" : "Due date", t.due_date ? S.fmtDateFull(t.due_date + "T00:00:00+08:00") : "—")}
          ${field("Started", t.start_date ? S.fmtDateFull(t.start_date + "T00:00:00+08:00") : "—")}
          ${t.completed_at ? field("Completed", S.fmtDateFull(t.completed_at)) : ""}
          ${t.service_charge_label ? field("Service charge", t.service_charge_label) : ""}
        </div>
        ${t.deliverable_url ? `<div style="margin-top:12px"><div class="section-label">Deliverable</div><a href="${S.esc(t.deliverable_url)}" target="_blank" class="btn sm ghost" style="margin-top:6px">Open deliverable →</a></div>` : ""}
        ${t.client_facing_notes ? `<div style="margin-top:12px"><div class="section-label">${isAtrium ? "Client note" : "Client notes"}</div><div class="sub">${S.esc(t.client_facing_notes)}</div></div>` : ""}
        <div style="margin-top:18px;padding-top:14px;border-top:1px dashed var(--line)">
          <div class="section-label" style="color:var(--sentinel-2)">${S.ICON.lock}Internal, not visible to clients</div>
          <div class="spread" style="margin-top:10px">
            ${isAtrium ? `
              ${field("Department", t.assigned_team_name)}
              ${field("Lead", t.atrium_lead_name || t.atrium_lead_id)}
              ${field("Support", (t.atrium_support_names || []).join(", "))}
              ${field("Shared with client", t.atrium_visible ? "Yes — on their Progress tab" : "No — internal only")}
            ` : `
              ${field("Account Manager", t.account_manager ? t.account_manager.name : "—")}
              ${field("Created by", t.created_by ? t.created_by.name : "—")}
              ${field("Assigned team", t.assigned_team_name)}
              ${field("Assigned to", t.assignee ? t.assignee.name : "Unassigned")}
            `}
            <div><div class="section-label">Priority</div>${prioritySelect}</div>
          </div>
          ${(t.on_hold && t.hold_reason) ? `<div style="margin-top:12px"><div class="section-label">On hold because${resumeHint}</div><div class="sub">${S.esc(t.hold_reason)}</div></div>` : ""}
          ${t.internal_notes ? `<div style="margin-top:12px"><div class="section-label">Internal notes</div><div class="sub">${S.esc(t.internal_notes)}</div></div>` : ""}
        </div>
      </div>
      <div>
        <div class="spread" style="align-items:center;margin-bottom:2px"><div class="section-label">Work breakdown <span id="d-bd-count"></span></div></div>
        <div class="progress" style="margin:8px 0 12px"><i id="d-bd-bar" style="width:0%"></i></div>
        <div id="d-breakdown"></div>
        ${readOnly ? "" : `<button class="btn sm ghost" id="d-bd-addmain" style="margin-top:10px">${S.ICON.plus}Add main task</button>`}
        <div class="section-label" style="margin-top:18px">Comments${(isAtrium && t.atrium_visible) ? ' <span class="muted" style="font-weight:400">· this card is shared, so the client sees these</span>' : ""}</div>
        <div class="thread" id="d-thread" style="margin:10px 0">${t.comments.map(cmt).join("") || '<div class="muted">No comments yet.</div>'}</div>
        ${readOnly ? "" : `<div class="row" style="gap:8px"><input id="d-comment" placeholder="Write a comment… use @name to mention"><button class="btn primary sm" id="d-send">Send</button></div>`}
        <div class="section-label" style="margin-top:18px">Activity</div>
        <ul class="activity">${t.history.map((h) => `<li><span>${h.actor ? S.esc(h.actor.name) : "System"}</span> ${S.esc(h.field)} ${h.old_value ? `<span class="muted">${S.esc(h.old_value)} → </span>` : ""}<strong>${S.esc(h.new_value || "")}</strong> <span class="muted">· ${S.timeAgo(h.changed_at)}</span></li>`).join("")}</ul>
      </div></div>`;
    // The bridge button means the opposite thing on each kind of card: a Sentinel row is PUSHED to
    // Atrium (one-way, client-safe fields only), while an Atrium card is already there — the toggle
    // just decides whether the client can see it.
    // No "Move to Review" shortcut — the For Review column was removed 2026-07-30 (statuses live in
    // task_vocab; a hardcoded status here would be a name the board no longer has a column for).
    // The lifecycle controls (Stage 2). All Sentinel-only: an Atrium-owned card has no local row to
    // hold a hold, a review or a filing, and faking one would split ownership of the record again.
    // Only the buttons that CAN act appear — the server enforces the same rules either way.
    const done = isDoneStatus(t.status);
    const lifecycle = (isAtrium || readOnly) ? "" : [
      t.on_hold ? `<button class="btn ghost" id="d-resume">Resume</button>`
                : `<button class="btn ghost" id="d-park">Park…</button>`,
      // Nothing to submit once it is approved, and nothing to submit about filed work.
      (!t.archived && t.review_state !== "approved" && t.review_state !== "pending")
        ? `<button class="btn ghost" id="d-submit">Submit for review</button>` : "",
      (canReview(t) && t.review_state === "pending")
        ? `<button class="btn ghost" id="d-approve">Approve</button>
           <button class="btn ghost" id="d-changes">Request changes…</button>` : "",
      filingBtn(t, done),
      // Send back (D11) — refuse queued work and return it to whoever filed it. Offered ONLY in the
      // exact state the rule allows: still unassigned, routed to a team, filed by somebody else, and
      // I am the one who could triage it. Once anyone owns it, reassigning is the honest move.
      (canReview(t) && !t.assigned_to_id && t.assigned_team_id && t.created_by_id
        && t.created_by_id !== S.user.id)
        ? `<button class="btn ghost" id="d-sendback">Not ours…</button>` : "",
    ].join("");
    const footer = `${readOnly ? "" : `<button class="btn ghost" id="d-edit">Edit</button>`}${lifecycle}
      ${canManage ? `<button class="btn ghost" id="d-atrium">${isAtrium
          ? (t.atrium_visible ? "✓ Client can see this" : "Share with client")
          : (t.atrium_shared ? "✓ Shared with the client" : "Share with the client")}</button>` : ""}
      ${(canManage && !isAtrium && t.atrium_sync_error) ? `<button class="btn danger" id="d-atrium-retry">Retry the client push</button>` : ""}
      ${canDelete(t) ? `<button class="btn danger" id="d-delete">Delete</button>` : ""}
      <button class="btn primary" id="d-close">Close</button>`;
    const m = openTaskModal(
      isAtrium ? "Client card · " + (t.client_name || "Atrium") : "Task #" + t.id,
      body, footer, id);
    S.qs("#d-close").onclick = m.close;
    if (S.qs("#d-atrium-retry")) S.qs("#d-atrium-retry").onclick = async () => {
      try {
        await S.api(`/api/tasks/${id}/atrium-retry`, { method: "POST" });
        S.toast("Sent — the client's card is current again", "ok");
        m.close(); load();
      } catch (err) { S.toast(err.detail || "Couldn't reach Atrium", "err"); }
    };

    // ---- Two-level work breakdown (main tasks -> sub-tasks, each optionally assigned) ----
    const mById = (mid) => t.maintasks.find((m) => m.id === mid);
    const sById = (m, sid) => (m ? m.subs.find((s) => s.id === sid) : null);
    // Strip the resolved-assignee objects back to the storable shape the API expects.
    const storable = () => t.maintasks.map((m) => ({
      id: m.id, title: m.title, assignee_id: m.assignee_id,
      subs: m.subs.map((s) => ({ id: s.id, text: s.text, done: s.done, assignee_id: s.assignee_id })),
    }));

    // `owners` is Sentinel's people list, or Atrium's roster on an Atrium card — same widget, one
    // vocabulary each, so the ids that go back are always the ones that system understands.
    //
    // D12 (WP 4.2g): the ROUTED TEAM'S people come first, and everyone else stays reachable below.
    // Work is routed to a department and then owned by someone in it, so that team is the answer
    // ~90% of the time — but "Justine, or anyone in the company" is a real need too, and a picker
    // that only listed one team would send people back to the Edit form to re-route first.
    // Two <optgroup>s rather than a filter, so the common case is at the top without hiding
    // anything. An Atrium roster carries no team, so it degrades to one flat list on its own.
    const optionFor = (p, current) =>
      `<option value="${S.esc(p.id)}" ${p.id === current ? "selected" : ""}>${S.esc(p.name)}</option>`;
    const ownerName = (oid) => {
      const p = owners.find((x) => x.id === oid);
      return p ? p.name : "Somebody else";
    };
    // 🔴 Both of these mirror the server, which is where they are enforced (routers/tasks.py: the
    // per-slot owner diff + task_perms.can_tick_step). Without them the drawer offered every step to
    // everyone and answered with a 403 that ALSO threw away the rest of the edit — the breakdown
    // saves whole.
    // Delegating an owner: AM+ anywhere, a team lead on their own department's card. Self-assignment
    // (taking an unowned step, dropping your own) stays open to every role, which is why a
    // non-delegator still gets a picker — it just only lists them.
    // An ATRIUM-owned card is unchanged: its owners are roster emails, not Sentinel users, so no
    // ownership rule can apply to them and `can_edit_atrium` (team lead and up) governs its content
    // wholesale. Narrowing that here would take an ability team leads have today.
    const mayDelegateStep = isAtrium ? !readOnly : canReassign(t);
    // Ticking: the step's owner, the card's lead, or a lead/manager. An unowned step is anyone's to
    // tick (that is how a team queue gets worked through). Atrium cards have no Sentinel owners at
    // all — their roster is emails — so they keep the old open behaviour.
    const mayTick = (owner) => isAtrium || !owner || owner === S.user.id
      || t.assigned_to_id === S.user.id || canReassign(t);

    function ownerOptions(current) {
      // A non-delegator may only ever write their own id, so listing the company is a promise the
      // server will refuse. They keep sight of who holds it via the disabled select's own value.
      if (!mayDelegateStep) {
        return owners.filter((p) => p.id === S.user.id || p.id === current)
          .map((p) => optionFor(p, current)).join("");
      }
      const teamId = t.assigned_team_id;
      const teamName = teamsById[teamId] ? teamsById[teamId].name : null;
      const inTeam = teamId ? owners.filter((p) => p.team_id === teamId) : [];
      if (!inTeam.length) return owners.map((p) => optionFor(p, current)).join("");
      const rest = owners.filter((p) => p.team_id !== teamId);
      return `<optgroup label="${S.esc(teamName || "This department")}">${inTeam.map((p) => optionFor(p, current)).join("")}</optgroup>`
        + (rest.length ? `<optgroup label="Everyone else">${rest.map((p) => optionFor(p, current)).join("")}</optgroup>` : "");
    }

    const assigneeSelect = (act, mid, sid, current, placeholder) => {
      // Somebody else's slot is shown, never editable: taking work off a colleague is the same power
      // as giving it to them, and the server refuses both.
      const locked = !mayDelegateStep && !!current && current !== S.user.id;
      const title = locked
        ? `${ownerName(current)} owns this — only a team lead or manager can change that`
        : (mayDelegateStep ? "" : "You can take this on yourself, or hand it back");
      return `<select class="bd-assignee" data-act="${act}" data-mid="${mid}"${sid ? ` data-sid="${sid}"` : ""}
        ${locked ? "disabled" : ""} title="${S.esc(title)}">
        <option value="">${placeholder}</option>
        ${ownerOptions(current)}
      </select>`;
    };

    // D12: assignment and routing are CONTROLS, not action buttons. The prototype had hardcoded
    // "Route to Acquisition" / "Delegate to Justine & Zhen" buttons, which only ever fit the one
    // example they were drawn for. These three controls are the general form of the same thing:
    // route the whole task, own a phase, own a step — plus one sweep for "the N nobody owns yet",
    // which is the actual daily action a lead takes after a service seeds twelve empty steps.
    function routingRow() {
      if (isAtrium || readOnly) return "";      // Atrium cards carry Atrium's own department field
      const unowned = t.maintasks.reduce(
        (n, m) => n + m.subs.filter((s) => !s.assignee_id).length, 0);
      const teamName = teamsById[t.assigned_team_id] ? teamsById[t.assigned_team_id].name : null;
      return `<div class="row bd-route" style="gap:10px;align-items:center;flex-wrap:wrap;margin:0 0 10px">
        <span class="sub" style="font-size:12px">Routed to</span>
        <select id="bd-team" ${canReassign(t) ? "" : "disabled"} title="${canReassign(t) ? "Send this task to a department" : "Only a team lead or manager can re-route work"}">
          <option value="">Nobody yet</option>
          ${teams.map((tm) => `<option value="${tm.id}" ${tm.id === t.assigned_team_id ? "selected" : ""}>${S.esc(tm.name)}</option>`).join("")}
        </select>
        ${unowned ? `<select id="bd-bulkown" title="Give every step that nobody owns to one person">
          <option value="">Assign the ${unowned} unowned step${unowned > 1 ? "s" : ""} to…</option>
          ${ownerOptions(null)}
        </select>` : `<span class="sub" style="font-size:12px">${teamName ? "Every step has an owner" : ""}</span>`}
      </div>`;
    }

    function renderBreakdown() {
      let d = 0, total = 0;
      t.maintasks.forEach((m) => m.subs.forEach((s) => { total += 1; if (s.done) d += 1; }));
      S.qs("#d-bd-count").textContent = total ? `· ${d}/${total}` : "";
      S.qs("#d-bd-bar").style.width = (total ? Math.round(100 * d / total) : 0) + "%";
      S.qs("#d-breakdown").innerHTML = routingRow() + t.maintasks.map((m) => `
        <div class="mtask" data-mid="${m.id}">
          <div class="mtask-head">
            <input class="mtask-title" data-act="mt-title" data-mid="${m.id}" value="${S.esc(m.title)}" aria-label="Main task title">
            ${assigneeSelect("mt-assignee", m.id, null, m.assignee_id, "Owner…")}
            <button class="bd-x" data-act="mt-del" data-mid="${m.id}" title="Delete main task">✕</button>
          </div>
          <ul class="mtask-subs">${m.subs.map((s) => `
            <li class="${s.done ? "done" : ""}" data-sid="${s.id}">
              <input type="checkbox" data-act="sub-toggle" data-mid="${m.id}" data-sid="${s.id}" ${s.done ? "checked" : ""}
                ${mayTick(s.assignee_id) ? "" : `disabled title="${S.esc(ownerName(s.assignee_id) + " owns this step — only they or a lead can tick it")}"`}>
              <input class="sub-text" data-act="sub-text" data-mid="${m.id}" data-sid="${s.id}" value="${S.esc(s.text)}" aria-label="Sub-task">
              ${assigneeSelect("sub-assignee", m.id, s.id, s.assignee_id, "Assign…")}
              <button class="bd-x" data-act="sub-del" data-mid="${m.id}" data-sid="${s.id}" title="Delete sub-task">✕</button>
            </li>`).join("")}</ul>
          <div class="mtask-addsub">
            <input placeholder="Add a sub-task, then Enter…" data-act="sub-add-input" data-mid="${m.id}" aria-label="New sub-task">
          </div>
        </div>`).join("") || '<div class="muted" style="padding:4px 0">No breakdown yet. Add a main task to start.</div>';
      wireBreakdown();
    }

    // Persist the whole breakdown; refresh from the server response (gets ids for new items),
    // and roll back to a snapshot if the save fails.
    let saving = false;
    async function commit() {
      if (saving) return;
      saving = true;
      const snapshot = JSON.parse(JSON.stringify(t.maintasks));
      try {
        const updated = await S.api("/api/tasks/" + id, { method: "PATCH", body: { maintasks: storable() } });
        t.maintasks = Array.isArray(updated.maintasks) ? updated.maintasks : [];
        renderBreakdown();
      } catch (err) {
        t.maintasks = snapshot;
        renderBreakdown();
        S.toast(err.detail || "Couldn't save the breakdown", "err");
      } finally { saving = false; }
    }

    function wireBreakdown() {
      const q = (act) => S.qsa(`#d-breakdown [data-act="${act}"]`);
      // A viewer's breakdown is inert: disable the controls rather than let them look editable and
      // then 403 on blur. (The server refuses either way — this is about not lying to the user.)
      if (readOnly) {
        S.qsa("#d-breakdown input, #d-breakdown select, #d-breakdown button")
          .forEach((el) => { el.disabled = true; });
        return;
      }
      // D12 routing + bulk owner sweep. Both live outside the [data-act] grid because they act on
      // the TASK, not on one row of the breakdown.
      const teamSel = S.qs("#bd-team");
      if (teamSel && !teamSel.disabled) {
        teamSel.onchange = async () => {
          const value = teamSel.value ? Number(teamSel.value) : null;
          try {
            await S.api("/api/tasks/" + id, { method: "PATCH", body: { assigned_team_id: value } });
            t.assigned_team_id = value;
            // Re-routing changes the derived label (D14) AND which people head the owner pickers,
            // so the board and this drawer both need the new answer.
            S.toast(value ? "Routed to " + teamsById[value].name : "Routing cleared", "ok");
            renderBreakdown();
            load();
          } catch (err) {
            teamSel.value = t.assigned_team_id || "";
            S.toast(err.detail || "Couldn't re-route this task", "err");
          }
        };
      }
      const bulkOwn = S.qs("#bd-bulkown");
      if (bulkOwn) {
        bulkOwn.onchange = () => {
          const who = ownerId(bulkOwn.value);
          if (who === null) return;
          // Only the steps nobody owns. Never reassigns work that already has an owner — that is
          // someone's job, and a sweep is not the place to take it off them.
          t.maintasks.forEach((m) => m.subs.forEach((s) => { if (!s.assignee_id) s.assignee_id = who; }));
          commit();
        };
      }
      q("mt-title").forEach((el) => el.onchange = () => { const m = mById(el.dataset.mid); if (m) { m.title = el.value.trim() || "Untitled"; commit(); } });
      q("mt-assignee").forEach((el) => el.onchange = () => { const m = mById(el.dataset.mid); if (m) { m.assignee_id = ownerId(el.value); commit(); } });
      q("mt-del").forEach((el) => el.onclick = () => { t.maintasks = t.maintasks.filter((m) => m.id !== el.dataset.mid); commit(); });
      q("sub-toggle").forEach((el) => el.onchange = () => { const s = sById(mById(el.dataset.mid), el.dataset.sid); if (s) { s.done = el.checked; commit(); } });
      q("sub-text").forEach((el) => el.onchange = () => { const s = sById(mById(el.dataset.mid), el.dataset.sid); if (s) { s.text = el.value.trim(); commit(); } });
      q("sub-assignee").forEach((el) => el.onchange = () => { const s = sById(mById(el.dataset.mid), el.dataset.sid); if (s) { s.assignee_id = ownerId(el.value); commit(); } });
      q("sub-del").forEach((el) => el.onclick = () => { const m = mById(el.dataset.mid); if (m) { m.subs = m.subs.filter((s) => s.id !== el.dataset.sid); commit(); } });
      q("sub-add-input").forEach((el) => el.onkeydown = (e) => {
        if (e.key !== "Enter") return;
        const m = mById(el.dataset.mid); const text = el.value.trim();
        // The placeholder id is replaced by a real one on save (both systems mint their own).
        if (m && text) { m.subs.push({ id: "st_new_" + Date.now(), text, done: false, assignee_id: ownerId("") }); commit(); }
      });
    }

    if (S.qs("#d-bd-addmain")) S.qs("#d-bd-addmain").onclick = () => {
      t.maintasks.push({ id: "mt_new_" + Date.now(), title: "New main task", assignee_id: null, subs: [] });
      commit();
    };
    renderBreakdown();
    // Comment
    if (S.qs("#d-send")) S.qs("#d-send").onclick = async () => {
      const val = S.qs("#d-comment").value.trim(); if (!val) return;
      try {
        const c = await S.api(`/api/tasks/${id}/comments`, { method: "POST", body: { body: val } });
        const thr = S.qs("#d-thread"); if (thr.querySelector(".muted")) thr.innerHTML = "";
        thr.insertAdjacentHTML("beforeend", cmt(c)); S.qs("#d-comment").value = "";
      } catch (err) { S.toast(err.detail || "Couldn't post that comment", "err"); }
    };
    // A client's "Request changes" (Atrium cards only — clients raise them on their Progress tab).
    // Clearing one is a team action, so it belongs wherever the team is working: here too.
    // Clears the TASK-level client-changes flag (D4). Separate from wireResolve below, which
    // resolves ONE Atrium comment — a Sentinel row has no per-comment resolve, only this counter.
    // The endpoint is idempotent, so two people clicking it is a race nobody loses.
    const resolveBtn = S.qs("#d-resolve-changes");
    if (resolveBtn) resolveBtn.onclick = async () => {
      resolveBtn.disabled = true;
      try {
        await S.api(`/api/tasks/${id}/resolve-client-changes`, { method: "POST" });
        S.toast("Marked as handled", "ok");
        m.close(); load(); openDetail(id);
      } catch (err) { resolveBtn.disabled = false; S.toast(err.detail || "Couldn't clear that", "err"); }
    };
    wireResolve();
    function wireResolve() {
      S.qsa("[data-resolve]").forEach((b) => b.onclick = async () => {
        b.disabled = true;
        try {
          await S.api(`/api/tasks/${id}/comments/${b.dataset.resolve}/resolve`, { method: "POST" });
          S.toast("Change request resolved", "ok");
          m.close(); load(); openDetail(id);
        } catch (err) { b.disabled = false; S.toast(err.detail || "Couldn't resolve that", "err"); }
      });
    }
    // Priority (AM only)
    if (S.qs("#d-priority")) S.qs("#d-priority").onchange = async (e) => {
      try { await S.api(`/api/tasks/${id}/priority`, { method: "PATCH", body: { priority: e.target.value } }); S.toast("Priority updated", "ok"); }
      catch (err) { S.toast(err.detail, "err"); }
    };
    if (S.qs("#d-atrium")) S.qs("#d-atrium").onclick = async () => {
      try {
        if (isAtrium) {
          // Already in Atrium — this only flips whether the client sees it on their Progress tab.
          await S.api(`/api/tasks/${id}`, { method: "PATCH", body: { atrium_visible: !t.atrium_visible } });
          S.toast(t.atrium_visible ? "Hidden from the client" : "Shared with the client", "ok");
        } else {
          await S.api(`/api/tasks/${id}/send-to-atrium`, { method: "POST" });
          S.toast("Client-safe fields sent to Atrium", "ok");
        }
        m.close(); load();
      } catch (err) { S.toast(err.detail, "err"); }
    };
    // ---- Lifecycle: park / resume / file / review (Stage 2) ----
    // One helper: POST, tell the user what happened, then reopen the drawer so every chip, field
    // and button reflects the new state (the buttons themselves depend on it).
    const act = async (path, body, msg) => {
      try {
        await S.api(`/api/tasks/${id}/${path}`, { method: "POST", body });
        S.toast(msg, "ok");
        m.close(); load(); openDetail(id);
      } catch (err) { S.toast(err.detail || "Couldn't do that", "err"); }
    };
    if (S.qs("#d-park")) S.qs("#d-park").onclick = () => askReason({
      title: "Park this task?",
      hint: `It moves to the ${S.esc(pausedColumn())} column and comes back to <strong>${S.esc(t.status)}</strong> when you resume it.`,
      label: "Why is it paused? (internal — the client never sees this)",
      confirm: "Park it",
      onSubmit: (reason) => act("park", { reason }, "Parked"),
    });
    if (S.qs("#d-resume")) S.qs("#d-resume").onclick = () =>
      act("resume", {}, "Back on the board");
    if (S.qs("#d-submit")) S.qs("#d-submit").onclick = () =>
      act("review/submit", {}, "Sent for review — your lead has been notified");
    if (S.qs("#d-approve")) S.qs("#d-approve").onclick = () =>
      act("review/approve", {}, "Approved — it can be completed now");
    if (S.qs("#d-changes")) S.qs("#d-changes").onclick = () => askReason({
      title: "Request changes",
      hint: "The card moves back to the revision column and whoever holds it is notified.",
      label: "What needs changing?",
      confirm: "Request changes",
      onSubmit: (note) => act("review/request-changes", { note }, "Sent back with your note"),
    });
    if (S.qs("#d-archive")) S.qs("#d-archive").onclick = () =>
      act("archive", {}, "Filed to Past work");
    if (S.qs("#d-sendback")) S.qs("#d-sendback").onclick = () => askReason({
      title: "Send this back?",
      hint: `It leaves your team's queue and goes back to <strong>${S.esc((t.created_by && t.created_by.name) || "whoever filed it")}</strong>, assigned to them.
             You will not see it here afterwards — that is the point.`,
      label: "Why isn't this yours? (internal — the client never sees it)",
      confirm: "Send it back",
      onSubmit: (reason) => act("send-back", { reason }, "Sent back"),
    });
    if (S.qs("#d-unarchive")) S.qs("#d-unarchive").onclick = () =>
      act("unarchive", {}, "Back on the board");

    if (S.qs("#d-edit")) S.qs("#d-edit").onclick = () => { m.close(); taskForm(t); };
    if (S.qs("#d-delete")) S.qs("#d-delete").onclick = () => confirmDelete(t, m);
  }

  // The column parked work sits in, BY STAGE — never the literal "Blocked". That label is
  // renameable in Manage (Blocked → Parked is the planned rename), and the whole point of
  // task_status_meta is that no name is hardcoded here (decision D13).
  const pausedColumn = () =>
    Object.keys(STAGE_OF).find((n) => STAGE_OF[n] === "blocked") || "the blocked";

  // A small "why?" prompt, shared by Park and Request changes. Both write prose that has to be
  // recorded, and both are refusals of a sort, so they ask the same way.
  function askReason({ title, hint, label, confirm, onSubmit }) {
    const rm = S.modal({
      title,
      body: `<div class="stack" style="gap:12px">
        <div class="form-hint">${hint}</div>
        <label class="field"><span>${label}</span><textarea id="rz-text" rows="3"></textarea></label>
      </div>`,
      footer: `<button class="btn ghost" id="rz-cancel">Cancel</button><button class="btn primary" id="rz-ok">${S.esc(confirm)}</button>`,
    });
    S.qs("#rz-cancel").onclick = rm.close;
    S.qs("#rz-text").focus();
    S.qs("#rz-ok").onclick = () => {
      const text = S.qs("#rz-text").value.trim();
      rm.close();
      onSubmit(text);
    };
  }

  // Past work: the filed tasks, out of the way but never lost (M4). A separate fetch rather than a
  // filter on the board's list — `?archived=1` returns filed rows ONLY, and the two never mix.
  async function showPastWork() {
    const pm = S.modal({
      title: "Past work",
      drawer: true,
      body: `<div class="skeleton-row">Loading…</div>`,
      footer: `<button class="btn primary" id="pw-close">Close</button>`,
    });
    S.qs("#pw-close").onclick = pm.close;
    // app.js:298 — the modal's body container. The LAST one: a task drawer may already be open
    // behind this, and qs() would hand back its body instead of ours.
    const box = S.qsa(".overlay.drawer-ov .modal-body").pop();
    let rows;
    try { rows = await S.api("/api/tasks?archived=1"); }
    catch (err) { box.innerHTML = `<div class="empty">${S.esc(err.detail || "Couldn't load past work.")}</div>`; return; }
    if (!rows.length) {
      box.innerHTML = `<div class="empty">Nothing filed yet. Completed work gets filed here so the
        board's Completed column stays a working column, not a graveyard.</div>`;
      return;
    }
    box.innerHTML = `<div class="lead" style="margin-bottom:12px">${rows.length} filed task${rows.length > 1 ? "s" : ""}.
        Filing is internal — a client's card stays exactly where it is.</div>
      <table class="mon-tbl"><thead><tr><th>Task</th><th>Client</th><th>Completed</th><th></th></tr></thead>
      <tbody>${rows.map((r) => `<tr data-id="${r.id}">
        <td><div class="n">${S.esc(r.title)}</div><div class="r muted">${S.esc(r.status)}</div></td>
        <td>${S.esc(r.client_name || "—")}</td>
        <td>${r.completed_at ? S.fmtDate(r.completed_at) : '<span class="muted">—</span>'}</td>
        <td><button class="btn sm ghost" data-restore="${r.id}">Restore</button></td>
      </tr>`).join("")}</tbody></table>`;
    S.qsa("[data-restore]").forEach((b) => b.onclick = async (e) => {
      e.stopPropagation();
      b.disabled = true;
      try {
        await S.api(`/api/tasks/${b.dataset.restore}/unarchive`, { method: "POST" });
        S.toast("Back on the board", "ok"); pm.close(); load();
      } catch (err) { b.disabled = false; S.toast(err.detail || "Couldn't restore that", "err"); }
    });
    S.qsa(".mon-tbl tbody tr").forEach((tr) => tr.onclick = () => { pm.close(); openDetail(tr.dataset.id); });
  }

  // "Filed by me" (§2.4d, decision D10): work you raised that is now somebody else's. It is NOT
  // on your board -- routing a card to another team takes it off yours, deliberately -- so this
  // answers the one question that leaves behind: where did it go? Team, current owner or "awaiting
  // triage", and whether it was sent back. No internal fields: it may be another department's now.
  async function showFiledByMe() {
    const fm = S.modal({
      title: "Filed by me",
      drawer: true,
      body: `<div class="skeleton-row">Loading…</div>`,
      footer: `<button class="btn primary" id="fm-close">Close</button>`,
    });
    S.qs("#fm-close").onclick = fm.close;
    const box = S.qsa(".overlay.drawer-ov .modal-body").pop();
    let rows;
    try { rows = await S.api("/api/tasks/filed-by-me"); }
    catch (err) { box.innerHTML = `<div class="empty">${S.esc(err.detail || "Couldn't load that list.")}</div>`; return; }
    if (!rows.length) {
      box.innerHTML = `<div class="empty">Nothing here. Work you raise and keep stays on your board;
        this list is for what you routed to another team.</div>`;
      return;
    }
    const where = (r) => {
      if (r.sent_back_reason) return `<span class="pill red">Sent back</span> <span class="muted">${S.esc(r.sent_back_reason)}</span>`;
      if (r.awaiting_triage) return `<span class="pill amber">Awaiting triage</span> <span class="muted">in ${S.esc(r.team_name || "a team")}</span>`;
      if (r.owner_name) return `<span class="muted">with ${S.esc(r.owner_name)}${r.team_name ? " · " + S.esc(r.team_name) : ""}</span>`;
      return `<span class="muted">unrouted</span>`;
    };
    box.innerHTML = `<div class="lead" style="margin-bottom:12px">${rows.length} item${rows.length > 1 ? "s" : ""} you
        raised for someone else — where it went, not the internal detail, which is theirs now.</div>
      <div class="card">${rows.map((r) => `<div style="padding:12px 14px;border-bottom:1px solid var(--line-soft)">
        <div class="row" style="justify-content:space-between;gap:10px">
          <strong style="min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${S.esc(r.title)}</strong>
          <span class="sub" style="flex:none;font-size:12px">${S.esc(r.status)}${r.on_hold ? " · ⏸" : ""}</span>
        </div>
        <div style="margin-top:5px;font-size:12.5px">${where(r)}${r.client_name
          ? `<span class="muted"> · ${S.esc(r.client_name)}</span>` : ""}</div>
      </div>`).join("")}</div>`;
  }

  // Confirm-then-delete. A Sentinel row is gone for good (no bin); an Atrium card soft-deletes into
  // Atrium's own Bin, so say so rather than warning about something irreversible that isn't.
  function confirmDelete(t, parent) {
    const cm = S.modal({
      title: t.source === "atrium" ? "Delete this client card?" : "Delete task?",
      body: `<p style="line-height:1.5">Delete <strong>${S.esc(t.title)}</strong>?<br>
        <span class="muted">${t.source === "atrium"
          ? "It leaves this board and the client's Progress tab, and goes to Atrium's Bin — restorable there for 30 days."
          : "This also removes its checklist, comments, and activity. This can't be undone."}</span></p>`,
      footer: `<button class="btn ghost" id="cd-cancel">Cancel</button><button class="btn danger" id="cd-yes">Delete task</button>`,
    });
    S.qs("#cd-cancel").onclick = cm.close;
    S.qs("#cd-yes").onclick = async () => {
      S.qs("#cd-yes").disabled = true;
      try {
        await S.api("/api/tasks/" + t.id, { method: "DELETE" });
        S.toast("Task deleted", "ok"); cm.close(); if (parent) parent.close(); load();
      } catch (err) { S.qs("#cd-yes").disabled = false; S.toast(err.detail || "Couldn't delete the task", "err"); }
    };
  }

  const field = (label, val) => `<div><div class="section-label">${label}</div><div style="margin-top:4px">${S.esc(val || "—")}</div></div>`;
  // Atrium cards carry one comment kind Sentinel rows don't: a client's "Request changes", which
  // stays flagged until someone on the team clears it (see wireResolve in the drawer).
  // 🔴 `is_client` is finally read here. A client's words on an internal thread have to be
  // unmistakable — the reply is written differently depending on who is going to read it — and the
  // serializer has advertised this field for exactly that since D4 while nothing consumed it.
  // The `[atrium:<id>]` de-dupe marker is stripped: it rides in the body so the receiver needs no
  // extra column (see internal.internal_task_feedback), and it is plumbing, not something the
  // client typed.
  const cmt = (c) => `<div class="cmt">${S.avatar(c.author, "sm")}<div class="body">
      <strong>${S.esc(c.author ? c.author.name : "?")}</strong>${c.is_client
        ? `<span class="pill violet" style="margin-left:6px">Client</span>` : ""}${c.kind === "changes"
        ? `<span class="pill ${c.resolved ? "green" : "red"}" style="margin-left:6px">${c.resolved ? "Resolved" : "Changes requested"}</span>` : ""}
      <div>${S.esc(String(c.body || "").replace(/\n?\[atrium:[^\]]*\]/g, "").trim())}</div>
      <div class="meta">${S.timeAgo(c.created_at)}</div>
      ${(c.kind === "changes" && !c.resolved) ? `<button class="btn sm ghost" style="margin-top:6px" data-resolve="${S.esc(c.id)}">Mark resolved</button>` : ""}
    </div></div>`;

  // The Edit form for an Atrium-owned card. A SEPARATE form from taskForm on purpose: it edits
  // Atrium's own fields (its department vocabulary, roster owners as emails, launch + start dates,
  // the hold switch, client visibility) and Sentinel's field names would either be ignored or mean
  // something subtly different. Both forms save through the same PATCH /api/tasks/{id}; the router
  // routes by id, and the bridge translates (services/atrium_tasks.FIELD_MAP).
  function atriumTaskForm(t) {
    const depts = t.atrium_departments || [];
    const roster = t.atrium_roster || [];
    const support = t.atrium_support_ids || [];
    const extrasOpen = !!(t.atrium_department || t.atrium_lead_id || support.length || t.content_type
      || t.service_charge || t.deliverable_url || t.internal_notes || t.on_hold
      || (t.priority && t.priority !== "Medium"));
    const m = S.modal({
      title: "Edit client card",
      wide: true,
      body: `<div class="grid" style="grid-template-columns:1fr 1fr;gap:16px">
        <div class="form-hint" style="grid-column:1/-1">This card lives in ${S.esc(t.client_name || "Atrium")}'s workspace — saving writes straight back to Atrium.</div>
        <label class="field" style="grid-column:1/-1"><span>Task name</span><input id="a-title" value="${S.esc(t.title || "")}" placeholder="What needs doing?"></label>
        <label class="field" style="grid-column:1/-1"><span>Client note — the client reads this</span><textarea id="a-cnote" rows="3" placeholder="Optional">${S.esc(t.client_facing_notes || "")}</textarea></label>
        <label class="field"><span>Launch date</span><input type="date" id="a-due" value="${t.due_date || ""}"></label>
        <label class="field"><span>Start date</span><input type="date" id="a-start" value="${t.start_date || ""}"></label>
        <div class="field" style="grid-column:1/-1">
          <details class="tk-extra"${extrasOpen ? " open" : ""}>
            <summary>More options${extrasOpen ? "" : " — department, lead, priority, visibility…"}</summary>
            <div class="grid" style="grid-template-columns:1fr 1fr;gap:16px;margin-top:12px">
              <label class="field"><span>Department</span><select id="a-dept"><option value="">—</option>${depts.map((d) => `<option value="${S.esc(d.key)}" ${d.key === t.atrium_department ? "selected" : ""}>${S.esc(d.label)}</option>`).join("")}</select></label>
              <label class="field"><span>Lead</span><select id="a-lead"><option value="">Unassigned</option>${roster.map((p) => `<option value="${S.esc(p.id)}" ${p.id === t.atrium_lead_id ? "selected" : ""}>${S.esc(p.name)}</option>`).join("")}</select></label>
              <label class="field" style="grid-column:1/-1"><span>Support — pick as many as you need</span><select id="a-support" multiple size="4">${roster.map((p) => `<option value="${S.esc(p.id)}" ${support.indexOf(p.id) >= 0 ? "selected" : ""}>${S.esc(p.name)}</option>`).join("")}</select></label>
              ${isAM ? `<label class="field"><span>Priority</span><select id="a-priority">${vocab.priorities.map((p) => `<option ${p === (t.priority || "Medium") ? "selected" : ""}>${p}</option>`).join("")}</select></label>` : ""}
              <label class="field"><span>Status</span><select id="a-status">${STATUSES.map((s) => `<option ${s === t.status ? "selected" : ""}>${s}</option>`).join("")}</select></label>
              <label class="field"><span>Content type</span><input id="a-ctype" value="${S.esc(t.content_type || "")}"></label>
              <label class="field"><span>Service charge ($)</span><input id="a-charge" inputmode="decimal" value="${S.esc(t.service_charge || "")}" placeholder="0" pattern="[0-9]*[.]?[0-9]*" title="Optional — numbers only (e.g. 4200 or 4200.50)"></label>
              <label class="field" style="grid-column:1/-1"><span>Deliverable URL (client-safe)</span><input id="a-deliv" value="${S.esc(t.deliverable_url || "")}"></label>
              <label class="field" style="grid-column:1/-1"><span>${S.ICON.lock}Internal notes</span><textarea id="a-inotes">${S.esc(t.internal_notes || "")}</textarea></label>
              ${canManage ? `<div class="field" style="grid-column:1/-1"><span>Client visibility</span>
                <label class="row" style="gap:8px;margin-top:6px"><input type="checkbox" id="a-visible" ${t.atrium_visible ? "checked" : ""}><span class="sub">Show this card on the client's Progress tab</span></label></div>` : ""}
              <div class="field" style="grid-column:1/-1"><span>On hold</span>
                <label class="row" style="gap:8px;margin-top:6px"><input type="checkbox" id="a-hold" ${t.on_hold ? "checked" : ""}><span class="sub">Paused — the client only ever sees "Paused", never the reason</span></label></div>
              <label class="field" style="grid-column:1/-1"><span>${S.ICON.lock}Hold reason</span><input id="a-holdwhy" value="${S.esc(t.hold_reason || "")}" placeholder="Internal — why it's paused"></label>
            </div>
          </details>
        </div>`,
      footer: `<button class="btn ghost" id="a-cancel">Cancel</button><button class="btn primary" id="a-save">Save changes</button>`,
    });
    S.qs("#a-cancel").onclick = m.close;
    S.qs("#a-title").focus();

    S.qs("#a-save").onclick = async () => {
      const body = {
        title: S.qs("#a-title").value.trim() || "Untitled task",
        client_facing_notes: S.qs("#a-cnote").value,
        due_date: S.qs("#a-due").value || null,
        start_date: S.qs("#a-start").value || null,
        atrium_department: S.qs("#a-dept").value,
        atrium_lead_id: S.qs("#a-lead").value,
        atrium_support_ids: Array.from(S.qs("#a-support").options).filter((o) => o.selected).map((o) => o.value),
        content_type: S.qs("#a-ctype").value,
        service_charge: S.qs("#a-charge").value || null,
        deliverable_url: S.qs("#a-deliv").value,
        internal_notes: S.qs("#a-inotes").value,
        on_hold: S.qs("#a-hold").checked,
        hold_reason: S.qs("#a-holdwhy").value,
      };
      if (isAM) body.priority = S.qs("#a-priority").value;
      // Only send client visibility when this user may set it — the server 403s anyone else, and a
      // form that can't change it shouldn't be able to fail because of it.
      if (canManage && S.qs("#a-visible")) body.atrium_visible = S.qs("#a-visible").checked;
      const status = S.qs("#a-status").value;
      const btn = S.qs("#a-save");
      btn.disabled = true;
      try {
        await S.api("/api/tasks/" + t.id, { method: "PATCH", body });
        // Status is not one of those fields: in Atrium it is a stage MOVE, with its own history
        // entry and its own endpoint. Send it separately, and only when the form changed it.
        if (status !== t.status) await S.api(`/api/tasks/${t.id}/status`, { method: "PATCH", body: { status } });
        S.toast("Card updated", "ok"); m.close(); load();
      } catch (err) { btn.disabled = false; S.toast(err.detail || "Couldn't save that card", "err"); }
    };
  }

  function taskForm(existing, presetStatus) {
    if (existing && existing.source === "atrium") return atriumTaskForm(existing);
    const e = existing || {};
    if (presetStatus && !e.status) e.status = presetStatus;  // column "Add card" pre-picks the status
    // Only spring the advanced block open when an EXISTING task already carries one of those
    // values -- otherwise editing would silently hide something the user themselves set. A new
    // task always starts collapsed. (Status is excluded: the column's Add card presets it.)
    const extrasOpen = !!existing && !!(e.client_id || e.assigned_team_id || e.assigned_to_id
      || e.service_charge || e.content_type || e.deliverable_url || e.internal_notes || e.campaign
      || (e.priority && e.priority !== "Medium"));
    // 🔴 Campaign is a GROUPING field, not the name (§7 of docs/TASKBOARD_REBUILD.md, built
    // 2026-08-04). Until then ONE input wrote into both `title` and `campaign`, so the detail
    // modal's Campaign row just echoed the title back on every task. The name field is now the
    // name; Campaign is optional and only OFFERED when the service is campaign-shaped, which is
    // derived from the template's content type — no flag column, no migration (the alternative
    // the doc floated). Existing rows keep their duplicated value until someone edits them.
    const isCampaignType = (ct) => (ct || "").trim().toLowerCase() === "campaign";
    // 🔴 WHO MAY NAME A PERSON — mirrors the server, and the server is what enforces it:
    // an existing card asks `task_perms.can_reassign` (AM+ anywhere, a team lead while the card is
    // routed to their OWN department); a new one asks `create_task`'s `may_delegate`, which is the
    // same rule against the department being picked in this form right now.
    // This field was ungated until 2026-08-05 — the only one in the block that wasn't (Priority two
    // rows down always was) — so an employee could set it, hit Save, and lose the WHOLE edit to a
    // 403; on create the person they picked was silently dropped and the card landed on them.
    const mayNamePerson = (teamId) => (existing
      ? canReassign(existing)
      : (canManage || (S.can("team_lead") && teamId != null && teamId === S.user.team_id)));
    const LEAD_LOCKED = existing
      ? "Only an account manager — or a team lead on this department's work — can change who leads this."
      : "Pick a department instead: its leads are notified and triage it. Naming a person is a lead or manager call.";
    // 🔴 "What the client will read" (#t-cnote) sits UP FRONT with the dates, not behind More
    // options: it is the entire content of the client's card. It had no field ANYWHERE in this form
    // until 2026-08-03, so every task published by Send to Atrium reached the client's board with an
    // empty note — the bridge sends `client_facing_notes`, and nothing here could set it. It sits
    // beside the internal Description on purpose: the pair reads as "what we tell ourselves" vs
    // "what they read", which is the whole client-safe split in two adjacent boxes.
    const m = S.modal({
      title: existing ? "Edit task" : "New task",
      wide: true,
      // SIMPLE BY DEFAULT (2026-07-27): filing a task should need a NAME and nothing else. Only
      // name / description / due date are on show; every other field still exists, one click away
      // under "More options". Atrium's board renders the same three-then-collapse form, so the two
      // surfaces feel identical. The collapsed block auto-opens when editing a task that already
      // uses those fields, so nothing is ever hidden from the person who set it.
      body: `<div class="grid" style="grid-template-columns:1fr 1fr;gap:16px">
        <label class="field" style="grid-column:1/-1"><span>Task name</span><input id="t-name" value="${S.esc(e.title || "")}" placeholder="What needs doing?" autofocus></label>
        <label class="field" style="grid-column:1/-1"><span>Description</span><textarea id="t-desc" rows="3" placeholder="Optional — a sentence of context">${S.esc(e.description || "")}</textarea></label>
        <label class="field"><span>Due date</span><input type="date" id="t-due" value="${e.due_date || ""}"></label>
        <label class="field"><span>Start date</span><input type="date" id="t-start" value="${e.start_date || ""}"></label>
        <label class="field" style="grid-column:1/-1"><span>What the client will read</span>
          <textarea id="t-cnote" rows="2" placeholder="Optional — plain language, no internal detail. Only ever seen if this task is shared with the client.">${S.esc(e.client_facing_notes || "")}</textarea></label>
        <div class="field" style="grid-column:1/-1">
          <details class="tk-extra"${extrasOpen ? " open" : ""}>
            <summary>More options${extrasOpen ? "" : " — client, department, lead, priority…"}</summary>
            <div class="grid" style="grid-template-columns:1fr 1fr;gap:16px;margin-top:12px">
              <label class="field" style="grid-column:1/-1"><span>Client</span><select id="t-client"><option value="">—</option>${clients.map((c) => `<option value="${c.id}" ${c.id === e.client_id ? "selected" : ""}>${S.esc(c.name)}</option>`).join("")}</select></label>
              ${!existing && canManage ? `<div class="field" style="grid-column:1/-1" id="t-share-wrap"${e.client_id ? "" : " hidden"}>
                <label class="chip" style="cursor:pointer;align-self:start"><input type="checkbox" id="t-share" style="width:auto" checked> Share with the client straight away</label>
                <div class="form-hint">On by default (D6) — the client watches the work cross their board from day one instead of meeting it finished. Untick to keep this one internal; you can share it later from the card.</div>
              </div>` : ""}
              <label class="field"><span>Department</span><select id="t-team"><option value="">—</option>${teams.map((t) => `<option value="${t.id}" ${t.id === e.assigned_team_id ? "selected" : ""}>${S.esc(t.name)}</option>`).join("")}</select></label>
              <label class="field"><span>Lead (main)</span>
                <select id="t-assignee"${mayNamePerson(e.assigned_team_id) ? "" : " disabled"} title="${mayNamePerson(e.assigned_team_id) ? "" : S.esc(LEAD_LOCKED)}"><option value="">Unassigned</option>${people.map((p) => `<option value="${p.id}" ${p.id === e.assigned_to_id ? "selected" : ""}>${S.esc(p.name)}</option>`).join("")}</select>
                <div class="form-hint" id="t-assignee-hint"${mayNamePerson(e.assigned_team_id) ? " hidden" : ""}>${LEAD_LOCKED}</div></label>
              ${!existing ? `<label class="field" style="grid-column:1/-1"><span>Service type</span><select id="t-svc"><option value="">Custom (blank)</option></select></label>
              <div class="field" style="grid-column:1/-1"><div class="form-hint">Pick a department, then a service type. The phases, steps, and labels are created for you. Choose Custom (blank) to start empty.</div></div>
              <div class="field" style="grid-column:1/-1" id="t-svc-preview" hidden></div>` : ""}
              ${canPrioritizeOnForm ? `<label class="field"><span>Priority</span><select id="t-priority">${vocab.priorities.map((p) => `<option ${p === (e.priority || "Medium") ? "selected" : ""}>${p}</option>`).join("")}</select></label>` : ""}
              <label class="field"><span>Status</span><select id="t-status">${STATUSES.map((s) => `<option ${s === (e.status || "To Do") ? "selected" : ""}>${s}</option>`).join("")}</select></label>
              <label class="field"><span>Content type</span><input id="t-ctype" value="${S.esc(e.content_type || "")}"></label>
              <label class="field" id="t-campaign-wrap"${isCampaignType(e.content_type) || e.campaign ? "" : " hidden"}><span>Campaign</span>
                <input id="t-campaign" value="${S.esc(e.campaign || "")}" placeholder="Optional — the campaign this belongs to"></label>
              <label class="field"><span>Service charge ($)</span><input id="t-charge" inputmode="decimal" value="${S.esc(e.service_charge || "")}" placeholder="0" pattern="[0-9]*[.]?[0-9]*" title="Optional — numbers only (e.g. 4200 or 4200.50)"></label>
              <label class="field" style="grid-column:1/-1"><span>Deliverable URL (client-safe)</span><input id="t-deliv" value="${S.esc(e.deliverable_url || "")}"></label>
              <label class="field" style="grid-column:1/-1"><span>${S.ICON.lock}Internal notes</span><textarea id="t-inotes">${S.esc(e.internal_notes || "")}</textarea></label>
            </div>
          </details>
        </div>`,
      footer: `<button class="btn ghost" id="t-cancel">Cancel</button><button class="btn primary" id="t-save">${existing ? "Save changes" : "Create task"}</button>`,
    });
    S.qs("#t-cancel").onclick = m.close;
    // `autofocus` is unreliable on a node injected after load, so put the caret in the name field
    // explicitly -- with the form this short, you can now type a task and hit save immediately.
    const nameBox = S.qs("#t-name");
    if (nameBox) nameBox.focus();

    // Campaign follows the content type, which the service picker fills in but a human may also
    // type over — so watch the field itself rather than only the picker. Never hide a campaign
    // somebody already typed: that would silently drop it on save.
    // Share-on-create only means anything once there is a client to share WITH, so the control
    // follows the Client select rather than sitting there greyed out.
    const clientBox = S.qs("#t-client");
    const syncShare = () => {
      const wrap = S.qs("#t-share-wrap");
      if (wrap) wrap.hidden = !clientBox.value;
    };
    if (clientBox) clientBox.addEventListener("change", syncShare);

    // A team lead's right to name somebody follows the DEPARTMENT they are filing into, so on a new
    // card the picker has to follow that select rather than sit there enabled until the save fails.
    // Only on create: on an existing card the server judges `can_reassign` against the department the
    // card has NOW, not the one being picked in this form.
    const assigneeBox = S.qs("#t-assignee");
    const syncAssignee = () => {
      const allowed = mayNamePerson(numOrNull("t-team"));
      assigneeBox.disabled = !allowed;
      assigneeBox.title = allowed ? "" : LEAD_LOCKED;
      const hint = S.qs("#t-assignee-hint");
      if (hint) hint.hidden = allowed;
      // Never leave a name sitting in a locked picker: the server now REFUSES it rather than quietly
      // dropping it, and a save that dies on a field they cannot even reach is no better than the
      // silent version.
      if (!allowed) assigneeBox.value = "";
    };
    if (!existing) S.qs("#t-team").addEventListener("change", syncAssignee);

    const ctypeBox = S.qs("#t-ctype");
    const syncCampaign = () => {
      const wrap = S.qs("#t-campaign-wrap");
      if (!wrap) return;
      const typed = (S.qs("#t-campaign").value || "").trim();
      wrap.hidden = !isCampaignType(ctypeBox ? ctypeBox.value : "") && !typed;
    };
    if (ctypeBox) ctypeBox.addEventListener("input", syncCampaign);

    // Service-type picker (new tasks only): filter recipes by the chosen department, preview the
    // checklist it will seed, and prefill the content type. The server does the actual seeding.
    const svcSel = S.qs("#t-svc");
    if (svcSel) {
      const preview = S.qs("#t-svc-preview");
      const updatePreview = () => {
        const tpl = templates.find((t) => t.key === svcSel.value);
        if (!tpl) { preview.hidden = true; preview.innerHTML = ""; return; }
        preview.hidden = false;
        preview.innerHTML = `<div class="section-label">Auto checklist · ${tpl.steps.length} steps</div>
          <ul class="svc-preview">${tpl.steps.map((s) => `<li>${S.esc(s)}</li>`).join("")}</ul>`;
        // Prefill the template's defaults, but never clobber something the user already set.
        // Labels are no longer a manual field — the server seeds them from the template's
        // default_labels whenever the create request carries none (see routers/tasks.py).
        const ct = S.qs("#t-ctype"); if (ct && !ct.value) ct.value = tpl.content_type || "";
        const prio = S.qs("#t-priority"); if (prio && tpl.default_priority && prio.value === "Medium") prio.value = tpl.default_priority;
        const desc = S.qs("#t-desc"); if (desc && !desc.value.trim() && tpl.default_description) desc.value = tpl.default_description;
        // Picking a campaign-shaped service is what reveals the Campaign field (see isCampaignType).
        syncCampaign();
      };
      const fillServices = () => {
        const opts = templatesForTeam(numOrNull("t-team"));
        svcSel.innerHTML = `<option value="">Custom (blank)</option>` +
          opts.map((o) => `<option value="${S.esc(o.key)}">${S.esc(o.label)}</option>`).join("");
        svcSel.disabled = !opts.length;
        updatePreview();
      };
      S.qs("#t-team").addEventListener("change", fillServices);
      svcSel.addEventListener("change", updatePreview);
      fillServices();
    }

    S.qs("#t-save").onclick = async () => {
      // The name field is the NAME. `campaign` is a separate, optional grouping field and is sent
      // as null when blank — writing the title into both is the bug this replaced (§7 of
      // docs/TASKBOARD_REBUILD.md). Labels aren't sent (the server seeds them from the service
      // template). The name is never forced: blank falls back to "Untitled task" (rename any time).
      const name = val("t-name") || "Untitled task";
      const payload = {
        title: name, campaign: val("t-campaign"), client_id: numOrNull("t-client"),
        assigned_team_id: numOrNull("t-team"), assigned_to_id: numOrNull("t-assignee"),
        content_type: val("t-ctype"), due_date: val("t-due") || null,
        start_date: val("t-start") || null, status: S.qs("#t-status").value,
        service_charge: val("t-charge") || null,
        description: val("t-desc"), deliverable_url: val("t-deliv"), internal_notes: val("t-inotes"),
        // The client-safe note. Sent as "" rather than null when cleared, so emptying the box
        // actually clears the client's card instead of leaving the old text stranded there.
        client_facing_notes: S.qs("#t-cnote").value,
      };
      if (!existing && svcSel) payload.service_key = svcSel.value || null;
      if (canPrioritizeOnForm) payload.priority = S.qs("#t-priority").value;
      // Share-on-create (D6). Sent ONLY on create, and only when the control exists — the server
      // treats an absent value as "decide for me" (share when there is a client), so an omitted
      // field is not the same as false and must not be forged into one.
      const shareBox = S.qs("#t-share");
      if (!existing && shareBox) payload.share_with_client = shareBox.checked;
      try {
        if (existing) await S.api("/api/tasks/" + existing.id, { method: "PATCH", body: payload });
        else await S.api("/api/tasks", { method: "POST", body: payload });
        S.toast(existing ? "Task updated" : "Task created", "ok"); m.close(); load();
      } catch (err) { S.toast(err.detail, "err"); }
    };
    function val(id) { return S.qs("#" + id).value || null; }
    function numOrNull(id) { const v = S.qs("#" + id).value; return v ? Number(v) : null; }
  }

  await load();
  // Deep-links: ?open=<id> (notification) and ?new=1 (command palette) — read from the current
  // URL, which is /dashboard now that the board is embedded there (/tasks 302s here too).
  const params = new URLSearchParams(location.search);
  if (params.get("open")) openTask(params.get("open"));
  if (params.get("new") && canCreate) taskForm(null);

  // Live board: reload when someone ELSE changes a task (SSE). Our own changes are already
  // reflected optimistically, so we skip events we caused. Debounced to coalesce bursts.
  if (window.EventSource) {
    let reloadTimer;
    const es = new EventSource("/api/stream");
    es.addEventListener("task", (e) => {
      let actor = null;
      try { actor = JSON.parse(e.data).actor_id; } catch (_) { /* ignore */ }
      if (actor === S.user.id) return;
      clearTimeout(reloadTimer);
      reloadTimer = setTimeout(load, 400);
    });
    window.addEventListener("beforeunload", () => es.close());
  }
  },
};

window.pageInit = async (S) => {
  const view = S.view();
  const canCreate = true;                   // all staff can add + edit tasks (internal employee tool)
  const canManage = S.can("account_manager"); // AM+ only: the Atrium bridge and deleting tasks
  const canMonitor = S.can("team_lead");    // team leads and up get the Monitor / employee overview
  const isAM = canManage;   // priority is settable by AM + admin + super_admin (not team leads/staff)

  const [vocab, clients, teams, people, templates] = await Promise.all([
    S.api("/api/vocab"), S.api("/api/clients"), S.api("/api/teams"), S.api("/api/people"),
    S.api("/api/tasks/templates"),
  ]);
  const STATUSES = vocab.task_statuses;
  const peopleById = Object.fromEntries(people.map((p) => [p.id, p]));
  const teamsById = Object.fromEntries(teams.map((t) => [t.id, t]));
  // Service templates that match a chosen department (team), by team name.
  const templatesForTeam = (teamId) => {
    const name = teamsById[teamId] ? teamsById[teamId].name : null;
    return name ? templates.filter((t) => t.dept === name) : [];
  };
  let filters = { client_id: "", team_id: "", priority: "", assignee_id: "" };
  let search = "";
  let allTasks = [];          // last fetch, unfiltered by the text search
  // View: "board" (status Kanban) | "employee" (swimlanes per person) | "monitor" (manager rollup).
  const params0 = new URLSearchParams(location.search);
  let mode = params0.get("view") || "board";
  if ((mode === "monitor") && !canMonitor) mode = "board";
  if (!["board", "employee", "monitor"].includes(mode)) mode = "board";

  view.innerHTML = `<div class="pagehead"><div><h2>Task Board</h2>
      <div class="lead" id="tb-lead"></div></div>
      <div class="row" style="gap:10px;align-items:center">
        <div class="seg" id="view-seg" role="tablist">
          <button type="button" data-view="board" role="tab">Board</button>
          <button type="button" data-view="employee" role="tab">By Employee</button>
          ${canMonitor ? `<button type="button" data-view="monitor" role="tab">Monitor</button>` : ""}
        </div>
        ${canCreate ? `<button class="btn primary" id="new-task">${S.ICON.plus}New Task</button>` : ""}
      </div></div>
    <div class="filters">
      <input id="f-search" class="tb-search" type="search" placeholder="Search tasks…" autocomplete="off">
      <select id="f-client"><option value="">All Clients</option>${clients.map((c) => `<option value="${c.id}">${S.esc(c.name)}</option>`).join("")}</select>
      <select id="f-team"><option value="">All Departments</option>${teams.map((t) => `<option value="${t.id}">${S.esc(t.name)}</option>`).join("")}</select>
      <select id="f-priority"><option value="">All Priority</option>${vocab.priorities.map((p) => `<option>${p}</option>`).join("")}</select>
      <select id="f-assignee"><option value="">All Assignees</option>${people.map((p) => `<option value="${p.id}">${S.esc(p.name)}</option>`).join("")}</select>
    </div>
    <div id="board"></div>`;

  const LEADS = {
    board: "Drag cards across columns. Client-safe fields sync to Atrium; internal fields stay here.",
    employee: "Every teammate's tasks, grouped by person. Drag a card between columns to change its status.",
    monitor: "Team workload at a glance: open work, what's overdue, and what shipped this week. Click a row to see that person's tasks.",
  };

  S.qs("#f-search").oninput = (e) => { search = e.target.value.trim().toLowerCase(); render(); };
  S.qs("#f-client").onchange = (e) => { filters.client_id = e.target.value; load(); };
  S.qs("#f-team").onchange = (e) => { filters.team_id = e.target.value; load(); };
  S.qs("#f-priority").onchange = (e) => { filters.priority = e.target.value; load(); };
  S.qs("#f-assignee").onchange = (e) => { filters.assignee_id = e.target.value; load(); };
  if (canCreate) S.qs("#new-task").onclick = () => taskForm(null);

  S.qsa("#view-seg button").forEach((b) => b.onclick = () => setMode(b.dataset.view));

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
    allTasks = await S.api("/api/tasks?" + q);
    render();
  }

  // The text search is applied client-side so typing never re-hits the server.
  function matches(t) {
    if (!search) return true;
    return [t.title, t.assignee && t.assignee.name, t.client_name]
      .some((s) => (s || "").toLowerCase().includes(search));
  }

  function render() {
    S.qs("#tb-lead").textContent = LEADS[mode];
    S.qsa("#view-seg button").forEach((b) => b.classList.toggle("on", b.dataset.view === mode));
    S.qs("#f-assignee").closest(".filters").style.display = mode === "monitor" ? "none" : "";
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
    wireQuickAdd();
    wireCardClicks();
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
  }

  async function renderMonitor(board) {
    board.className = "monitor";
    board.innerHTML = `<div class="skeleton-row">Loading team…</div>`;
    let rows;
    try { rows = await S.api("/api/tasks/summary"); }
    catch (err) { board.innerHTML = `<div class="empty">${S.esc(err.detail || "Couldn't load the team summary.")}</div>`; return; }
    if (!rows.length) { board.innerHTML = `<div class="empty">No teammates to show.</div>`; return; }
    const barSegs = ["To Do", "In Progress", "For Review", "Waiting for Client", "Revision Needed", "Blocked"];
    const segCls = { "To Do": "s-todo", "In Progress": "s-prog", "For Review": "s-review", "Waiting for Client": "s-wait", "Revision Needed": "s-rev", "Blocked": "s-block" };
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
  }

  function focusLane(uid) {
    const lane = S.qs(`.lane[data-uid="${uid}"]`);
    if (!lane) return;
    lane.scrollIntoView({ behavior: "smooth", block: "start" });
    lane.classList.remove("flash"); requestAnimationFrame(() => lane.classList.add("flash"));
  }

  function wireCardClicks() {
    S.qsa(".tcard").forEach((c) => c.onclick = () => { if (!c.classList.contains("dragging")) openDetail(c.dataset.id); });
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

  function card(t) {
    const dueCls = dueClass(t.due_date);
    return `<div class="tcard" draggable="true" data-id="${t.id}">
      ${t.labels.length ? `<div class="labels">${S.labelPills(t.labels)}</div>` : ""}
      <div class="t-title">${S.esc(t.title)}</div>
      <div class="t-meta">${S.priorityDot(t.priority)}<span>${S.esc(t.priority)}</span>
        ${t.due_date ? `<span class="due ${dueCls}">· ${S.fmtDate(t.due_date + "T00:00:00+08:00")}</span>` : ""}
        ${t.client_name ? `<span class="muted">· ${S.esc(t.client_name)}</span>` : ""}</div>
      <div class="t-foot">
        <div class="row">${t.assignee ? S.avatar(t.assignee, "sm") + `<span class="sub" style="font-size:12px">${S.esc(t.assignee.name.split(" ")[0])}</span>` : '<span class="muted" style="font-size:12px">Unassigned</span>'}</div>
        <div class="icons">${t.comment_count ? S.ICON.comment + t.comment_count : ""} ${t.attachment_count ? S.ICON.paperclip + t.attachment_count : ""} ${t.checklist_total ? `<span title="checklist">${t.checklist_done}/${t.checklist_total}</span>` : ""}</div>
      </div></div>`;
  }

  function wireDnD(opts = {}) {
    let dragEl = null;
    S.qsa(".tcard").forEach((c) => {
      c.ondragstart = (e) => { dragEl = c; c.classList.add("dragging"); e.dataTransfer.effectAllowed = "move"; };
      c.ondragend = () => { c.classList.remove("dragging"); S.qsa(".col.drag-over").forEach((x) => x.classList.remove("drag-over")); };
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

  // Inline "add card" at the foot of each column (AM+ only). Enter creates; Esc/empty cancels.
  function wireQuickAdd() {
    S.qsa(".col-add").forEach((btn) => btn.onclick = () => {
      const status = btn.dataset.status;
      const list = S.qs(`.col-list[data-status="${S.esc(status)}"]`);
      const existing = list.querySelector(".quick-add input");
      if (existing) { existing.focus(); return; }
      const wrap = document.createElement("div");
      wrap.className = "quick-add tcard";
      wrap.innerHTML = `<input placeholder="Card title, then Enter…" aria-label="New card title">`;
      list.appendChild(wrap);
      const input = wrap.querySelector("input");
      if (input.scrollIntoView) input.scrollIntoView({ block: "nearest" });
      input.focus();
      let saving = false;
      const cancel = () => { if (!saving) wrap.remove(); };
      const submit = async () => {
        const title = input.value.trim();
        if (!title || saving) { cancel(); return; }
        saving = true; input.disabled = true;
        try { await S.api("/api/tasks", { method: "POST", body: { title, status } }); S.toast("Card added", "ok"); load(); }
        catch (err) { saving = false; input.disabled = false; S.toast(err.detail || "Couldn't add card", "err"); input.focus(); }
      };
      input.onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); submit(); } else if (e.key === "Escape") cancel(); };
      input.onblur = submit;
    });
  }

  async function openDetail(id) {
    let t;
    try { t = await S.api("/api/tasks/" + id); }
    catch (err) { S.toast(err.detail || "Couldn't open that task", "err"); return; }
    if (!Array.isArray(t.maintasks)) t.maintasks = [];
    const body = `<div class="stack" style="gap:22px">
      <div>
        <div class="labels" style="margin-bottom:8px">${S.labelPills(t.labels)}</div>
        <h2 style="margin-bottom:6px">${S.esc(t.title)}</h2>
        <div class="sub">${S.esc(t.description || "")}</div>
        <div class="spread" style="margin-top:16px">
          ${field("Client", t.client_name)}${field("Campaign", t.campaign)}
          ${field("Content type", t.content_type)}${field("Due date", t.due_date ? S.fmtDateFull(t.due_date + "T00:00:00+08:00") : "—")}
        </div>
        ${t.deliverable_url ? `<div style="margin-top:12px"><div class="section-label">Deliverable</div><a href="${S.esc(t.deliverable_url)}" target="_blank" class="btn sm ghost" style="margin-top:6px">Open deliverable →</a></div>` : ""}
        ${t.client_facing_notes ? `<div style="margin-top:12px"><div class="section-label">Client notes</div><div class="sub">${S.esc(t.client_facing_notes)}</div></div>` : ""}
        <div style="margin-top:18px;padding-top:14px;border-top:1px dashed var(--line)">
          <div class="section-label" style="color:var(--sentinel-2)">${S.ICON.lock}Internal, not visible to clients</div>
          <div class="spread" style="margin-top:10px">
            ${field("Account Manager", t.account_manager ? t.account_manager.name : "—")}
            ${field("Assigned team", t.assigned_team_name)}
            ${field("Assigned to", t.assignee ? t.assignee.name : "Unassigned")}
            <div><div class="section-label">Priority</div>
              ${isAM ? `<select id="d-priority" style="margin-top:6px">${vocab.priorities.map((p) => `<option ${p === t.priority ? "selected" : ""}>${p}</option>`).join("")}</select>`
                : `<div style="margin-top:6px">${S.priorityDot(t.priority)} ${S.esc(t.priority)}</div>`}</div>
          </div>
          ${t.internal_notes ? `<div style="margin-top:12px"><div class="section-label">Internal notes</div><div class="sub">${S.esc(t.internal_notes)}</div></div>` : ""}
        </div>
      </div>
      <div>
        <div class="spread" style="align-items:center;margin-bottom:2px"><div class="section-label">Work breakdown <span id="d-bd-count"></span></div></div>
        <div class="progress" style="margin:8px 0 12px"><i id="d-bd-bar" style="width:0%"></i></div>
        <div id="d-breakdown"></div>
        <button class="btn sm ghost" id="d-bd-addmain" style="margin-top:10px">${S.ICON.plus}Add main task</button>
        <div class="section-label" style="margin-top:18px">Comments</div>
        <div class="thread" id="d-thread" style="margin:10px 0">${t.comments.map(cmt).join("") || '<div class="muted">No comments yet.</div>'}</div>
        <div class="row" style="gap:8px"><input id="d-comment" placeholder="Write a comment… use @name to mention"><button class="btn primary sm" id="d-send">Send</button></div>
        <div class="section-label" style="margin-top:18px">Activity</div>
        <ul class="activity">${t.history.map((h) => `<li><span>${h.actor ? S.esc(h.actor.name) : "System"}</span> ${S.esc(h.field)} ${h.old_value ? `<span class="muted">${S.esc(h.old_value)} → </span>` : ""}<strong>${S.esc(h.new_value || "")}</strong> <span class="muted">· ${S.timeAgo(h.changed_at)}</span></li>`).join("")}</ul>
      </div></div>`;
    const footer = `${t.status !== "For Review" ? `<button class="btn ghost" id="d-review">Move to Review</button>` : ""}
      <button class="btn ghost" id="d-edit">Edit</button>
      ${canManage ? `<button class="btn ghost" id="d-atrium">${t.atrium_visible ? "✓ In Atrium" : "Send to Atrium"}</button>
      <button class="btn danger" id="d-delete">Delete</button>` : ""}
      <button class="btn primary" id="d-close">Close</button>`;
    const m = S.modal({ title: "Task #" + t.id, body, footer, drawer: true });
    S.qs("#d-close").onclick = m.close;

    // ---- Two-level work breakdown (main tasks -> sub-tasks, each optionally assigned) ----
    const mById = (mid) => t.maintasks.find((m) => m.id === mid);
    const sById = (m, sid) => (m ? m.subs.find((s) => s.id === sid) : null);
    // Strip the resolved-assignee objects back to the storable shape the API expects.
    const storable = () => t.maintasks.map((m) => ({
      id: m.id, title: m.title, assignee_id: m.assignee_id,
      subs: m.subs.map((s) => ({ id: s.id, text: s.text, done: s.done, assignee_id: s.assignee_id })),
    }));

    const assigneeSelect = (act, mid, sid, current, placeholder) =>
      `<select class="bd-assignee" data-act="${act}" data-mid="${mid}"${sid ? ` data-sid="${sid}"` : ""}>
        <option value="">${placeholder}</option>
        ${people.map((p) => `<option value="${p.id}" ${p.id === current ? "selected" : ""}>${S.esc(p.name)}</option>`).join("")}
      </select>`;

    function renderBreakdown() {
      let d = 0, total = 0;
      t.maintasks.forEach((m) => m.subs.forEach((s) => { total += 1; if (s.done) d += 1; }));
      S.qs("#d-bd-count").textContent = total ? `· ${d}/${total}` : "";
      S.qs("#d-bd-bar").style.width = (total ? Math.round(100 * d / total) : 0) + "%";
      S.qs("#d-breakdown").innerHTML = t.maintasks.map((m) => `
        <div class="mtask" data-mid="${m.id}">
          <div class="mtask-head">
            <input class="mtask-title" data-act="mt-title" data-mid="${m.id}" value="${S.esc(m.title)}" aria-label="Main task title">
            ${assigneeSelect("mt-assignee", m.id, null, m.assignee_id, "Owner…")}
            <button class="bd-x" data-act="mt-del" data-mid="${m.id}" title="Delete main task">✕</button>
          </div>
          <ul class="mtask-subs">${m.subs.map((s) => `
            <li class="${s.done ? "done" : ""}" data-sid="${s.id}">
              <input type="checkbox" data-act="sub-toggle" data-mid="${m.id}" data-sid="${s.id}" ${s.done ? "checked" : ""}>
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
      q("mt-title").forEach((el) => el.onchange = () => { const m = mById(el.dataset.mid); if (m) { m.title = el.value.trim() || "Untitled"; commit(); } });
      q("mt-assignee").forEach((el) => el.onchange = () => { const m = mById(el.dataset.mid); if (m) { m.assignee_id = el.value ? +el.value : null; commit(); } });
      q("mt-del").forEach((el) => el.onclick = () => { t.maintasks = t.maintasks.filter((m) => m.id !== el.dataset.mid); commit(); });
      q("sub-toggle").forEach((el) => el.onchange = () => { const s = sById(mById(el.dataset.mid), el.dataset.sid); if (s) { s.done = el.checked; commit(); } });
      q("sub-text").forEach((el) => el.onchange = () => { const s = sById(mById(el.dataset.mid), el.dataset.sid); if (s) { s.text = el.value.trim(); commit(); } });
      q("sub-assignee").forEach((el) => el.onchange = () => { const s = sById(mById(el.dataset.mid), el.dataset.sid); if (s) { s.assignee_id = el.value ? +el.value : null; commit(); } });
      q("sub-del").forEach((el) => el.onclick = () => { const m = mById(el.dataset.mid); if (m) { m.subs = m.subs.filter((s) => s.id !== el.dataset.sid); commit(); } });
      q("sub-add-input").forEach((el) => el.onkeydown = (e) => {
        if (e.key !== "Enter") return;
        const m = mById(el.dataset.mid); const text = el.value.trim();
        if (m && text) { m.subs.push({ id: "st_new_" + Date.now(), text, done: false, assignee_id: null }); commit(); }
      });
    }

    S.qs("#d-bd-addmain").onclick = () => {
      t.maintasks.push({ id: "mt_new_" + Date.now(), title: "New main task", assignee_id: null, subs: [] });
      commit();
    };
    renderBreakdown();
    // Comment
    S.qs("#d-send").onclick = async () => {
      const val = S.qs("#d-comment").value.trim(); if (!val) return;
      try {
        const c = await S.api(`/api/tasks/${id}/comments`, { method: "POST", body: { body: val } });
        const thr = S.qs("#d-thread"); if (thr.querySelector(".muted")) thr.innerHTML = "";
        thr.insertAdjacentHTML("beforeend", cmt(c)); S.qs("#d-comment").value = "";
      } catch (err) { S.toast(err.detail || "Couldn't post that comment", "err"); }
    };
    // Priority (AM only)
    if (isAM && S.qs("#d-priority")) S.qs("#d-priority").onchange = async (e) => {
      try { await S.api(`/api/tasks/${id}/priority`, { method: "PATCH", body: { priority: e.target.value } }); S.toast("Priority updated", "ok"); }
      catch (err) { S.toast(err.detail, "err"); }
    };
    if (S.qs("#d-review")) S.qs("#d-review").onclick = async () => {
      try { await S.api(`/api/tasks/${id}/status`, { method: "PATCH", body: { status: "For Review" } }); S.toast("Sent to review", "ok"); m.close(); load(); }
      catch (err) { S.toast(err.detail, "err"); }
    };
    if (S.qs("#d-atrium")) S.qs("#d-atrium").onclick = async () => {
      try { await S.api(`/api/tasks/${id}/send-to-atrium`, { method: "POST" }); S.toast("Client-safe fields sent to Atrium", "ok"); m.close(); load(); }
      catch (err) { S.toast(err.detail, "err"); }
    };
    if (S.qs("#d-edit")) S.qs("#d-edit").onclick = () => { m.close(); taskForm(t); };
    if (S.qs("#d-delete")) S.qs("#d-delete").onclick = () => confirmDelete(t, m);
  }

  // Confirm-then-delete. Deletion is irreversible (no bin), so we always ask first.
  function confirmDelete(t, parent) {
    const cm = S.modal({
      title: "Delete task?",
      body: `<p style="line-height:1.5">Delete <strong>${S.esc(t.title)}</strong>?<br>
        <span class="muted">This also removes its checklist, comments, and activity. This can't be undone.</span></p>`,
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
  const cmt = (c) => `<div class="cmt">${S.avatar(c.author, "sm")}<div class="body"><strong>${S.esc(c.author ? c.author.name : "?")}</strong><div>${S.esc(c.body)}</div><div class="meta">${S.timeAgo(c.created_at)}</div></div></div>`;

  function taskForm(existing) {
    const e = existing || {};
    const m = S.modal({
      title: existing ? "Edit task" : "New task",
      wide: true,
      body: `<div class="grid" style="grid-template-columns:1fr 1fr;gap:16px">
        <label class="field" style="grid-column:1/-1"><span>Client</span><select id="t-client"><option value="">—</option>${clients.map((c) => `<option value="${c.id}" ${c.id === e.client_id ? "selected" : ""}>${S.esc(c.name)}</option>`).join("")}</select></label>
        <label class="field"><span>Department</span><select id="t-team"><option value="">—</option>${teams.map((t) => `<option value="${t.id}" ${t.id === e.assigned_team_id ? "selected" : ""}>${S.esc(t.name)}</option>`).join("")}</select></label>
        <label class="field"><span>Lead (main)</span><select id="t-assignee"><option value="">Unassigned</option>${people.map((p) => `<option value="${p.id}" ${p.id === e.assigned_to_id ? "selected" : ""}>${S.esc(p.name)}</option>`).join("")}</select></label>
        ${!existing ? `<label class="field" style="grid-column:1/-1"><span>Service type</span><select id="t-svc"><option value="">Custom (blank)</option></select></label>
        <div class="field" style="grid-column:1/-1"><div class="form-hint">Pick a department, then a service type. The phases, steps, and labels are created for you. Choose Custom (blank) to start empty.</div></div>
        <div class="field" style="grid-column:1/-1" id="t-svc-preview" hidden></div>` : ""}
        <label class="field" style="grid-column:1/-1"><span>Campaign/Title <span class="req">*</span></span><input id="t-campaign" value="${S.esc(e.campaign || e.title || "")}" placeholder="Unique campaign or service name"></label>
        ${isAM ? `<label class="field"><span>Priority</span><select id="t-priority">${vocab.priorities.map((p) => `<option ${p === (e.priority || "Medium") ? "selected" : ""}>${p}</option>`).join("")}</select></label>` : ""}
        <label class="field"><span>Due date</span><input type="date" id="t-due" value="${e.due_date || ""}"></label>
        <div class="field" style="grid-column:1/-1">
          <details class="tk-extra"${existing ? " open" : ""}>
            <summary>Additional details (optional)</summary>
            <div class="grid" style="grid-template-columns:1fr 1fr;gap:16px;margin-top:12px">
              <label class="field"><span>Content type</span><input id="t-ctype" value="${S.esc(e.content_type || "")}"></label>
              <label class="field"><span>Status</span><select id="t-status">${STATUSES.map((s) => `<option ${s === (e.status || "To Do") ? "selected" : ""}>${s}</option>`).join("")}</select></label>
              <label class="field" style="grid-column:1/-1"><span>Description</span><textarea id="t-desc">${S.esc(e.description || "")}</textarea></label>
              <label class="field" style="grid-column:1/-1"><span>Deliverable URL (client-safe)</span><input id="t-deliv" value="${S.esc(e.deliverable_url || "")}"></label>
              <label class="field" style="grid-column:1/-1"><span>${S.ICON.lock}Internal notes</span><textarea id="t-inotes">${S.esc(e.internal_notes || "")}</textarea></label>
            </div>
          </details>
        </div>`,
      footer: `<button class="btn ghost" id="t-cancel">Cancel</button><button class="btn primary" id="t-save">${existing ? "Save changes" : "Create task"}</button>`,
    });
    S.qs("#t-cancel").onclick = m.close;

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
      // The one name field is labelled "Campaign/Title" and drives BOTH — the campaign IS the task's
      // title (mirrors Atrium). Labels aren't sent (the server seeds them from the service template).
      const name = val("t-campaign");
      const payload = {
        title: name, campaign: name, client_id: numOrNull("t-client"),
        assigned_team_id: numOrNull("t-team"), assigned_to_id: numOrNull("t-assignee"),
        content_type: val("t-ctype"), due_date: val("t-due") || null, status: S.qs("#t-status").value,
        description: val("t-desc"), deliverable_url: val("t-deliv"), internal_notes: val("t-inotes"),
      };
      if (!existing && svcSel) payload.service_key = svcSel.value || null;
      if (isAM) payload.priority = S.qs("#t-priority").value;
      if (!name) { S.toast("Campaign/Title is required", "err"); return; }
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
  // Deep-links: /tasks?open=<id> (notification) and /tasks?new=1 (command palette).
  const params = new URLSearchParams(location.search);
  if (params.get("open")) openDetail(params.get("open"));
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
};

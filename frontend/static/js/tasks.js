window.pageInit = async (S) => {
  const view = S.view();
  const canCreate = S.can("account_manager");
  const isAM = S.user.role === "account_manager";

  const [vocab, clients, teams, people] = await Promise.all([
    S.api("/api/vocab"), S.api("/api/clients"), S.api("/api/teams"), S.api("/api/people"),
  ]);
  const STATUSES = vocab.task_statuses;
  const peopleById = Object.fromEntries(people.map((p) => [p.id, p]));
  let filters = { client_id: "", team_id: "", priority: "", assignee_id: "" };

  view.innerHTML = `<div class="pagehead"><div><h2>Task Board</h2>
      <div class="lead">Drag cards across columns. Client-safe fields sync to Atrium; internal fields stay here.</div></div>
      ${canCreate ? `<button class="btn primary" id="new-task">${S.ICON.plus}New Task</button>` : ""}</div>
    <div class="filters">
      <select id="f-client"><option value="">All Clients</option>${clients.map((c) => `<option value="${c.id}">${S.esc(c.name)}</option>`).join("")}</select>
      <select id="f-team"><option value="">All Departments</option>${teams.map((t) => `<option value="${t.id}">${S.esc(t.name)}</option>`).join("")}</select>
      <select id="f-priority"><option value="">All Priority</option>${vocab.priorities.map((p) => `<option>${p}</option>`).join("")}</select>
      <select id="f-assignee"><option value="">All Assignees</option>${people.map((p) => `<option value="${p.id}">${S.esc(p.name)}</option>`).join("")}</select>
    </div>
    <div class="board" id="board"></div>`;

  S.qs("#f-client").onchange = (e) => { filters.client_id = e.target.value; load(); };
  S.qs("#f-team").onchange = (e) => { filters.team_id = e.target.value; load(); };
  S.qs("#f-priority").onchange = (e) => { filters.priority = e.target.value; load(); };
  S.qs("#f-assignee").onchange = (e) => { filters.assignee_id = e.target.value; load(); };
  if (canCreate) S.qs("#new-task").onclick = () => taskForm(null);

  async function load() {
    const q = new URLSearchParams();
    Object.entries(filters).forEach(([k, v]) => { if (v) q.set(k, v); });
    const tasks = await S.api("/api/tasks?" + q);
    const byStatus = Object.fromEntries(STATUSES.map((s) => [s, []]));
    tasks.forEach((t) => (byStatus[t.status] || (byStatus[t.status] = [])).push(t));
    S.qs("#board").innerHTML = STATUSES.map((st) => `
      <div class="col" data-status="${S.esc(st)}">
        <div class="col-head"><span class="t">${S.esc(st)}</span><span class="c">${byStatus[st].length}</span></div>
        <div class="col-list" data-status="${S.esc(st)}">${byStatus[st].map(card).join("")}</div>
        ${canCreate ? `<button class="col-add" data-status="${S.esc(st)}">${S.ICON.plus}<span>Add card</span></button>` : ""}
      </div>`).join("");
    wireDnD();
    wireQuickAdd();
    S.qsa(".tcard").forEach((c) => c.onclick = () => { if (!c.classList.contains("dragging")) openDetail(c.dataset.id); });
  }

  function card(t) {
    const dueCls = t.due_date ? (new Date(t.due_date) < new Date(new Date().toDateString()) ? "over" : (new Date(t.due_date) - Date.now() < 2 * 864e5 ? "soon" : "")) : "";
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

  function wireDnD() {
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
        if (fromList !== list) moveCard(dragEl, list, list.dataset.status, fromList, fromList.dataset.status);
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
    const t = await S.api("/api/tasks/" + id);
    const done = t.checklist.filter((i) => i.done).length;
    const pct = t.checklist.length ? Math.round(100 * done / t.checklist.length) : 0;
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
          <div class="section-label" style="color:var(--sentinel-2)">🔒 Internal — not visible to clients</div>
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
        <div class="section-label">Checklist ${t.checklist.length ? `· ${done}/${t.checklist.length}` : ""}</div>
        <div class="progress" style="margin:8px 0 10px"><i style="width:${pct}%"></i></div>
        <ul class="checklist" id="d-check">${t.checklist.map((c, i) => `<li class="${c.done ? "done" : ""}"><input type="checkbox" data-ci="${i}" ${c.done ? "checked" : ""}><span>${S.esc(c.text)}</span></li>`).join("") || '<li class="muted">No checklist items.</li>'}</ul>
        <div class="section-label" style="margin-top:18px">Comments</div>
        <div class="thread" id="d-thread" style="margin:10px 0">${t.comments.map(cmt).join("") || '<div class="muted">No comments yet.</div>'}</div>
        <div class="row" style="gap:8px"><input id="d-comment" placeholder="Write a comment… use @name to mention"><button class="btn primary sm" id="d-send">Send</button></div>
        <div class="section-label" style="margin-top:18px">Activity</div>
        <ul class="activity">${t.history.map((h) => `<li><span>${h.actor ? S.esc(h.actor.name) : "System"}</span> ${S.esc(h.field)} ${h.old_value ? `<span class="muted">${S.esc(h.old_value)} → </span>` : ""}<strong>${S.esc(h.new_value || "")}</strong> <span class="muted">· ${S.timeAgo(h.changed_at)}</span></li>`).join("")}</ul>
      </div></div>`;
    const footer = `${t.status !== "For Review" ? `<button class="btn ghost" id="d-review">Move to Review</button>` : ""}
      ${canCreate ? `<button class="btn ghost" id="d-atrium">${t.atrium_visible ? "✓ In Atrium" : "Send to Atrium"}</button>
      <button class="btn ghost" id="d-edit">Edit</button>` : ""}
      <button class="btn primary" id="d-close">Close</button>`;
    const m = S.modal({ title: "Task #" + t.id, body, footer, drawer: true });
    S.qs("#d-close").onclick = m.close;

    // Checklist toggle
    S.qsa("#d-check input").forEach((cb) => cb.onchange = async () => {
      t.checklist[+cb.dataset.ci].done = cb.checked;
      await S.api("/api/tasks/" + id, { method: "PATCH", body: { checklist: t.checklist } });
      cb.closest("li").classList.toggle("done", cb.checked);
    });
    // Comment
    S.qs("#d-send").onclick = async () => {
      const val = S.qs("#d-comment").value.trim(); if (!val) return;
      const c = await S.api(`/api/tasks/${id}/comments`, { method: "POST", body: { body: val } });
      const thr = S.qs("#d-thread"); if (thr.querySelector(".muted")) thr.innerHTML = "";
      thr.insertAdjacentHTML("beforeend", cmt(c)); S.qs("#d-comment").value = "";
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
  }

  const field = (label, val) => `<div><div class="section-label">${label}</div><div style="margin-top:4px">${S.esc(val || "—")}</div></div>`;
  const cmt = (c) => `<div class="cmt">${S.avatar(c.author, "sm")}<div class="body"><strong>${S.esc(c.author ? c.author.name : "?")}</strong><div>${S.esc(c.body)}</div><div class="meta">${S.timeAgo(c.created_at)}</div></div></div>`;

  function taskForm(existing) {
    const e = existing || {};
    const m = S.modal({
      title: existing ? "Edit task" : "New task",
      wide: true,
      body: `<div class="grid" style="grid-template-columns:1fr 1fr;gap:16px">
        <label class="field" style="grid-column:1/-1"><span>Title</span><input id="t-title" value="${S.esc(e.title || "")}"></label>
        <label class="field"><span>Client</span><select id="t-client"><option value="">—</option>${clients.map((c) => `<option value="${c.id}" ${c.id === e.client_id ? "selected" : ""}>${S.esc(c.name)}</option>`).join("")}</select></label>
        <label class="field"><span>Campaign</span><input id="t-campaign" value="${S.esc(e.campaign || "")}"></label>
        <label class="field"><span>Department</span><select id="t-team"><option value="">—</option>${teams.map((t) => `<option value="${t.id}" ${t.id === e.assigned_team_id ? "selected" : ""}>${S.esc(t.name)}</option>`).join("")}</select></label>
        <label class="field"><span>Assignee</span><select id="t-assignee"><option value="">Unassigned</option>${people.map((p) => `<option value="${p.id}" ${p.id === e.assigned_to_id ? "selected" : ""}>${S.esc(p.name)}</option>`).join("")}</select></label>
        <label class="field"><span>Content type</span><input id="t-ctype" value="${S.esc(e.content_type || "")}"></label>
        <label class="field"><span>Due date</span><input type="date" id="t-due" value="${e.due_date || ""}"></label>
        ${isAM ? `<label class="field"><span>Priority</span><select id="t-priority">${vocab.priorities.map((p) => `<option ${p === (e.priority || "Medium") ? "selected" : ""}>${p}</option>`).join("")}</select></label>` : ""}
        <label class="field"><span>Status</span><select id="t-status">${STATUSES.map((s) => `<option ${s === (e.status || "To Do") ? "selected" : ""}>${s}</option>`).join("")}</select></label>
        <label class="field" style="grid-column:1/-1"><span>Labels</span><div class="row wrap" id="t-labels">${vocab.task_labels.map((l) => `<label class="chip" style="cursor:pointer"><input type="checkbox" style="width:auto" value="${l}" ${(e.labels || []).includes(l) ? "checked" : ""}> ${l}</label>`).join("")}</div></label>
        <label class="field" style="grid-column:1/-1"><span>Description</span><textarea id="t-desc">${S.esc(e.description || "")}</textarea></label>
        <label class="field"><span>Deliverable URL (client-safe)</span><input id="t-deliv" value="${S.esc(e.deliverable_url || "")}"></label>
        <label class="field"><span>Client-facing notes</span><input id="t-cnotes" value="${S.esc(e.client_facing_notes || "")}"></label>
        <label class="field" style="grid-column:1/-1"><span>🔒 Internal notes</span><textarea id="t-inotes">${S.esc(e.internal_notes || "")}</textarea></label>`,
      footer: `<button class="btn ghost" id="t-cancel">Cancel</button><button class="btn primary" id="t-save">${existing ? "Save changes" : "Create task"}</button>`,
    });
    S.qs("#t-cancel").onclick = m.close;
    S.qs("#t-save").onclick = async () => {
      const payload = {
        title: S.qs("#t-title").value, client_id: numOrNull("t-client"), campaign: val("t-campaign"),
        assigned_team_id: numOrNull("t-team"), assigned_to_id: numOrNull("t-assignee"),
        content_type: val("t-ctype"), due_date: val("t-due") || null, status: S.qs("#t-status").value,
        labels: S.qsa("#t-labels input:checked").map((c) => c.value), description: val("t-desc"),
        deliverable_url: val("t-deliv"), client_facing_notes: val("t-cnotes"), internal_notes: val("t-inotes"),
      };
      if (isAM) payload.priority = S.qs("#t-priority").value;
      if (!payload.title) { S.toast("Title is required", "err"); return; }
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

/* PROJECTS — named outcomes with dates (2026-09-02). The page that answers "is Phase One on
   track, and why not?" for whoever runs the company.

   `/projects` lists every project as one legible card: health with the reason in words, milestone
   progress, the linked work's counts. `/projects?project=<id>` is the drill-down: goal, the
   milestone checklist (tick = a stamped claim, audited), and the linked cards drawn with the same
   `OpsUI.taskRow` every other operating-system page uses. Creating WORK for a project goes through
   the AI planner (OpsUI.openAiPlanner) or the board's own New Task form — this page never grows a
   second task editor. */
window.pageInit = async (S) => {
  const U = window.OpsUI;
  const view = S.view();
  const params = new URLSearchParams(location.search);
  const pid = params.get("project");
  const canManage = S.hasCap("projects.manage");
  await U.meta(S);

  const bar = (done, total) => {
    const pct = total ? Math.round((done / total) * 100) : 0;
    return `<div class="pr-bar" title="${done} of ${total} milestones done"><i style="width:${pct}%"></i></div>`;
  };
  const statusPill = (p) => p.status === "active"
    ? U.healthPill(p.health, p.why)
    : `<span class="os-health"><i class="dot" style="background:var(--muted)"></i>${p.status === "done" ? "Done" : "Archived"}</span>`;

  // ---------- the list ----------
  if (!pid) {
    view.innerHTML = `<div class="skeleton skel-card" style="height:220px"></div>`;
    let d;
    try { d = await S.api("/api/projects"); }
    catch (e) { view.innerHTML = `<div class="notice warn"><b>Couldn't load projects.</b> ${S.esc(e.detail || "")}</div>`; return; }
    const rows = d.projects || [];
    view.innerHTML = `
      <div class="page-head"><div><h2>Projects</h2>
        <div class="sub">${S.esc(d.rule || "")}</div></div>
        ${canManage ? `<button class="btn primary" id="pr-new">${S.ICON.plus}New project</button>` : ""}</div>
      <div class="pr-grid">${rows.map((p) => `
        <a class="card pad pr-card" href="/projects?project=${p.id}">
          <div class="pr-top"><b>${S.esc(p.name)}</b>${statusPill(p)}</div>
          ${p.goal ? `<div class="pr-goal">${S.esc(p.goal)}</div>` : ""}
          <div class="pr-ms"><span>${p.milestones_done}/${p.milestones_total} milestones</span>${bar(p.milestones_done, p.milestones_total)}</div>
          ${p.next_milestone ? `<div class="pr-next">Next: ${S.esc(p.next_milestone.title)}${p.next_milestone.target_date ? " · " + U.dueChip(p.next_milestone.target_date) : ""}</div>` : ""}
          <div class="pr-stats">
            <span><b>${p.tasks_open}</b> open</span>
            <span class="${p.tasks_overdue ? "bad" : ""}"><b>${p.tasks_overdue}</b> late</span>
            <span class="${p.tasks_blocked ? "warn" : ""}"><b>${p.tasks_blocked}</b> parked</span>
            <span><b>${p.tasks_done}</b> done</span>
          </div>
          <div class="pr-foot">${p.owner ? S.avatar(p.owner, "xs") + " " + S.esc(p.owner.name.split(" ")[0]) : '<span class="muted">no owner</span>'}
            ${p.target_date ? `<span class="muted">· target ${U.dueChip(p.target_date, { parked: p.status !== "active" })}</span>` : ""}</div>
        </a>`).join("") || `<div class="card pad"><div class="os-empty">No projects yet${canManage ? " — create the first one (Phase One is the obvious candidate)." : "."}</div></div>`}
      </div>`;
    if (canManage) S.qs("#pr-new").onclick = () => projectForm(null);
    return;
  }

  // ---------- one project ----------
  let d;
  try { d = await S.api(`/api/projects/${encodeURIComponent(pid)}`); }
  catch (e) { view.innerHTML = `<div class="notice warn"><b>Couldn't load that project.</b> ${S.esc(e.detail || "")}</div>`; return; }
  const canDraft = S.hasCap("ai.draft");

  const msRow = (m) => `
    <label class="pr-mrow ${m.done ? "done" : ""}">
      <input type="checkbox" data-ms="${m.id}" ${m.done ? "checked" : ""} ${canManage ? "" : "disabled"}>
      <span class="pr-mtitle">${S.esc(m.title)}${m.detail ? `<span class="pr-mdetail">${S.esc(m.detail)}</span>` : ""}</span>
      <span class="pr-mright">${m.done
        ? `<span class="muted" title="Marked done${m.done_by ? " by " + S.esc(m.done_by.name) : ""}">${m.done_at ? S.fmtDate(m.done_at) : "done"}</span>`
        : (m.target_date ? U.dueChip(m.target_date) : "")}
      ${canManage ? `<button class="iconbtn sm" data-msdel="${m.id}" title="Remove milestone">✕</button>` : ""}</span>
    </label>`;

  view.innerHTML = `
    <div class="page-head"><div>
      <div class="crumb"><a href="/projects">Projects</a> / </div>
      <h2>${S.esc(d.name)} ${statusPill(d)}</h2>
      <div class="sub">${d.owner ? "Owned by " + S.esc(d.owner.name) : "No owner yet"}${d.target_date ? ` · target ${U.dueChip(d.target_date, { parked: d.status !== "active" })}` : ""}</div>
    </div>
    <div class="row" style="gap:8px">
      ${canDraft ? `<button class="btn" id="pr-ai">✦ Plan work with AI</button>` : ""}
      ${canManage ? `<button class="btn ghost" id="pr-edit">Edit</button>` : ""}
    </div></div>
    ${d.goal ? `<div class="card pad pr-goal-card">${S.esc(d.goal)}</div>` : ""}
    <div class="os-cols">
      <div class="os-sect">${U.head("Milestones", `${d.milestones_done}/${d.milestones_total} done`)}
        <div class="card pad-s" id="pr-ms">${(d.milestones || []).map(msRow).join("") || `<div class="os-empty">No milestones yet — a milestone is a checkable statement of done.</div>`}
        ${canManage ? `<form id="pr-msadd" class="pr-msadd"><input id="ms-title" placeholder="Add a milestone — a statement that is true or not" autocomplete="off"><input type="date" id="ms-date" title="Target date (optional)"><button class="btn sm">Add</button></form>` : ""}</div>
      </div>
      <div class="os-sect">${U.head("Open work", `${d.tasks_open} card${d.tasks_open === 1 ? "" : "s"}${d.tasks_overdue ? ` · ${d.tasks_overdue} late` : ""}`)}
        ${U.list((d.open_tasks || []).map((t) => U.taskRow(S, t, { who: true })), "Nothing linked yet — use ✦ Plan work with AI, or pick this project on the New Task form.")}
        ${U.head("Done", `${d.tasks_done}${d.done_truncated ? ` (${d.done_truncated} more in Past work)` : ""}`)}
        ${U.list((d.done_tasks || []).map((t) => U.taskRow(S, t, { who: true, quiet: true })), "Nothing finished yet.")}
      </div>
    </div>`;

  // Milestone ticks — the claim is stamped server-side; re-render keeps the stamp honest.
  S.qsa("#pr-ms input[data-ms]").forEach((cb) => {
    cb.onchange = async () => {
      try { await S.api(`/api/projects/milestones/${cb.dataset.ms}`, { method: "PATCH", body: { done: cb.checked } }); location.reload(); }
      catch (e) { S.toast(e.detail || "Couldn't save", "err"); cb.checked = !cb.checked; }
    };
  });
  S.qsa("#pr-ms [data-msdel]").forEach((b) => {
    b.onclick = async (ev) => {
      ev.preventDefault();
      if (!confirm("Remove this milestone?")) return;
      try { await S.api(`/api/projects/milestones/${b.dataset.msdel}`, { method: "DELETE" }); location.reload(); }
      catch (e) { S.toast(e.detail || "Couldn't remove", "err"); }
    };
  });
  const msAdd = S.qs("#pr-msadd");
  if (msAdd) msAdd.onsubmit = async (ev) => {
    ev.preventDefault();
    const title = S.qs("#ms-title").value.trim();
    if (!title) return;
    try {
      await S.api(`/api/projects/${d.id}/milestones`, { method: "POST", body: { title, target_date: S.qs("#ms-date").value || null } });
      location.reload();
    } catch (e) { S.toast(e.detail || "Couldn't add", "err"); }
  };

  const ai = S.qs("#pr-ai");
  if (ai) ai.onclick = () => U.openAiPlanner(S, { project_id: d.id, onDone: () => location.reload() });
  const edit = S.qs("#pr-edit");
  if (edit) edit.onclick = () => projectForm(d);

  // ---------- create / edit form ----------
  async function projectForm(existing) {
    const e = existing || {};
    const people = await S.api("/api/people").catch(() => []);
    const opts = (Array.isArray(people) ? people : []).filter((p) => p.is_active !== false)
      .map((p) => `<option value="${p.id}" ${e.owner && e.owner.id === p.id ? "selected" : ""}>${S.esc(p.name)}</option>`).join("");
    const m = S.modal({
      title: existing ? "Edit project" : "New project",
      body: `<div class="tf">
        <input id="p-name" class="tf-name" value="${S.esc(e.name || "")}" placeholder="Name the outcome — e.g. Phase One" aria-label="Project name">
        <textarea id="p-goal" class="tf-desc" rows="2" placeholder="The goal in one or two sentences — what is true when this is done">${S.esc(e.goal || "")}</textarea>
        <div class="tf-rows">
          <div class="tf-row"><div class="k">Owner</div><div class="v"><select id="p-owner"><option value="">Nobody yet</option>${opts}</select></div></div>
          <div class="tf-row"><div class="k">Target date</div><div class="v"><input type="date" id="p-date" value="${e.target_date || ""}"></div></div>
          ${existing ? `<div class="tf-row"><div class="k">Status</div><div class="v"><select id="p-status">${["active", "done", "archived"].map((x) => `<option ${x === e.status ? "selected" : ""}>${x}</option>`).join("")}</select></div></div>` : `
          <div class="tf-row"><div class="k">Milestones</div><div class="v"><textarea id="p-ms" rows="5" placeholder="One per line — add a date with a pipe:&#10;Report Standard v1 used live | 2026-09-08&#10;Every client audited and owned"></textarea></div></div>`}
        </div>
        <div class="row" style="justify-content:space-between;margin-top:14px">
          ${existing ? `<button class="btn danger ghost" id="p-del">Delete project</button>` : "<span></span>"}
          <button class="btn primary" id="p-save">${existing ? "Save" : "Create"}</button>
        </div></div>`,
    });
    S.qs("#p-save", m.root).onclick = async () => {
      const body = {
        name: S.qs("#p-name", m.root).value.trim(),
        goal: S.qs("#p-goal", m.root).value.trim() || null,
        owner_id: +S.qs("#p-owner", m.root).value || null,
        target_date: S.qs("#p-date", m.root).value || null,
      };
      if (!body.name) { S.toast("Name the outcome first", "err"); return; }
      try {
        if (existing) {
          body.status = S.qs("#p-status", m.root).value;
          await S.api(`/api/projects/${e.id}`, { method: "PATCH", body });
          location.reload();
        } else {
          body.milestones = S.qs("#p-ms", m.root).value.split("\n").map((l) => l.trim()).filter(Boolean)
            .map((l) => {
              const [title, dt] = l.split("|").map((x) => x.trim());
              return { title, target_date: /^\d{4}-\d{2}-\d{2}$/.test(dt || "") ? dt : null };
            });
          const created = await S.api("/api/projects", { method: "POST", body });
          location.href = "/projects?project=" + created.id;
        }
      } catch (err) { S.toast(err.detail || "Couldn't save", "err"); }
    };
    const del = S.qs("#p-del", m.root);
    if (del) del.onclick = async () => {
      if (!confirm(`Delete “${e.name}”? Its tasks stay on the board — only the grouping goes.`)) return;
      try { await S.api(`/api/projects/${e.id}`, { method: "DELETE" }); location.href = "/projects"; }
      catch (err) { S.toast(err.detail || "Couldn't delete", "err"); }
    };
  }
};

// Development Overview — the holistic hub. Four pillars (Physical / Learning / Career / Reading)
// plus a growth journal, all editable in place. A manager opens ?user=<id> for a read-only view of
// a report's profile. The same data feeds the AI coach (the floating "Coach" widget).
window.pageInit = async (S) => {
  const view = S.view();
  const esc = S.esc;
  const api = S.api;
  const params = new URLSearchParams(location.search);
  const targetId = params.get("user");
  const readOnly = !!targetId;

  let data = null;
  let courses = null;

  const V = "#5C4BD0";               // violet accent for the hub
  const SKILL_LEVELS = ["Beginner", "Intermediate", "Advanced"];
  const SKILL_SOURCES = [
    { v: "project", t: "Project experience" },
    { v: "mastery_engine", t: "Mastery Engine" },
    { v: "course", t: "Course" },
    { v: "certification", t: "Certification" },
    { v: "other", t: "Other" },
  ];
  const srcLabel = (v) => (SKILL_SOURCES.find((s) => s.v === v) || {}).t || v;

  // A tiny dependency-free progress ring.
  function ring(pct, color) {
    pct = Math.max(0, Math.min(100, Math.round(pct || 0)));
    const r = 26, c = 2 * Math.PI * r, off = c * (1 - pct / 100);
    return `<svg width="68" height="68" viewBox="0 0 68 68" style="flex:none">
      <circle cx="34" cy="34" r="${r}" fill="none" stroke="var(--line)" stroke-width="7"/>
      <circle cx="34" cy="34" r="${r}" fill="none" stroke="${color}" stroke-width="7" stroke-linecap="round"
        stroke-dasharray="${c.toFixed(1)}" stroke-dashoffset="${off.toFixed(1)}" transform="rotate(-90 34 34)"/>
      <text x="34" y="38" text-anchor="middle" font-size="15" font-weight="800" fill="var(--text)">${pct}%</text></svg>`;
  }

  function tile(icon, label, ringPct, ringColor, big, sub, href) {
    const inner = ringPct != null
      ? ring(ringPct, ringColor)
      : `<div style="font-size:26px;font-weight:800;color:var(--text);min-width:56px">${big}</div>`;
    return `<${href ? "a" : "div"} ${href ? `href="${href}"` : ""} class="card pad" style="display:flex;align-items:center;gap:14px;text-decoration:none;color:inherit">
      ${inner}
      <div><div class="section-label" style="display:flex;align-items:center;gap:6px">${icon}${label}</div>
      <div class="sub" style="margin-top:4px">${sub}</div></div></${href ? "a" : "div"}>`;
  }

  function courseCount() {
    if (!courses) return 0;
    const list = courses.programs || courses.courses || [];
    return Array.isArray(list) ? list.length : 0;
  }

  function goalAvg() {
    const gs = (data.career.goals || []).filter((g) => g.status === "active");
    if (!gs.length) return 0;
    return gs.reduce((a, g) => a + (g.progress_pct || 0), 0) / gs.length;
  }

  function readingPct() {
    const r = data.reading || [];
    if (!r.length) return 0;
    return (r.filter((x) => x.progress.status === "done").length / r.length) * 100;
  }

  // --- generic form modal ---------------------------------------------------
  function formModal(title, fields, onSave) {
    const body = fields.map((f) => {
      if (f.type === "textarea")
        return `<label class="field"><span>${esc(f.label)}</span><textarea id="f-${f.name}" rows="${f.rows || 4}" placeholder="${esc(f.ph || "")}">${esc(f.value || "")}</textarea></label>`;
      if (f.type === "select")
        return `<label class="field"><span>${esc(f.label)}</span><select id="f-${f.name}">${f.options.map((o) => `<option value="${esc(o.v)}" ${o.v === f.value ? "selected" : ""}>${esc(o.t)}</option>`).join("")}</select></label>`;
      return `<label class="field"><span>${esc(f.label)}</span><input id="f-${f.name}" type="${f.type || "text"}" ${f.step ? `step="${f.step}"` : ""} value="${f.value != null ? esc(String(f.value)) : ""}" placeholder="${esc(f.ph || "")}"></label>`;
    }).join("");
    const m = S.modal({
      title,
      body: `<div class="formgrid">${body}</div>`,
      footer: `<button class="btn ghost" id="fm-cancel">Cancel</button><button class="btn primary" id="fm-save">Save</button>`,
    });
    S.qs("#fm-cancel").onclick = m.close;
    S.qs("#fm-save").onclick = async () => {
      const out = {};
      fields.forEach((f) => { out[f.name] = S.qs(`#f-${f.name}`).value; });
      try { await onSave(out); m.close(); load(); }
      catch (e) { S.toast(e.detail || "Couldn't save", "err"); }
    };
    return m;
  }

  const num = (v) => (v === "" || v == null ? null : Number(v));

  // --- pillar renderers -----------------------------------------------------
  function physicalCard() {
    const p = data.physical;
    const latest = p.latest;
    const prs = p.prs || [];
    const bf = latest && latest.body_fat_pct != null ? `${latest.body_fat_pct}%` : "—";
    const wt = latest && latest.weight_kg != null ? `${latest.weight_kg} kg` : "—";
    const controls = readOnly ? "" : `<button class="btn sm ghost" id="add-metric">${S.ICON.plus}Log body stats</button>`;
    return `<div class="card">
      <div class="card-head"><h3>${S.ICON.heart}Physical</h3>${controls}</div>
      <div class="card-body">
        <div class="spread" style="margin-bottom:14px">
          <div class="stat"><div class="section-label">Body fat</div><strong style="font-size:22px">${bf}</strong></div>
          <div class="stat"><div class="section-label">Weight</div><strong style="font-size:22px">${wt}</strong></div>
          <div class="stat"><div class="section-label">As of</div><strong style="font-size:15px">${latest ? esc(latest.date) : "—"}</strong></div>
        </div>
        <div class="section-label" style="margin-bottom:8px">Personal records ${readOnly ? "" : `<a href="#" id="add-pr" class="linky">+ add</a>`}</div>
        ${prs.length ? `<div class="pr-list">${prs.map((r) => `
          <div class="row between pr-row" style="padding:7px 0;border-top:1px solid var(--line)">
            <div><strong>${esc(r.exercise_name)}</strong> <span class="muted">${esc(r.display || "")}</span></div>
            ${readOnly ? "" : `<div class="row"><a href="#" class="linky" data-edit-pr="${r.id}">edit</a><a href="#" class="linky danger" data-del-pr="${r.id}">delete</a></div>`}
          </div>`).join("")}</div>` : '<div class="empty">No PRs logged yet.</div>'}
      </div></div>`;
  }

  function careerCard() {
    const c = data.career;
    const prof = c.profile || {};
    const ach = c.achievements || [];
    const goals = c.goals || [];
    const resumeBlock = readOnly
      ? `<div class="section-label">Headline</div><div style="margin-bottom:8px">${esc(prof.headline || "—")}</div>
         <div class="section-label">Resume</div><div class="prewrap muted">${esc(prof.resume_text || "—")}</div>`
      : `<label class="field"><span>Headline</span><input id="hl" value="${esc(prof.headline || "")}" placeholder="e.g. Aspiring backend engineer"></label>
         <label class="field"><span>Resume / bio</span><textarea id="rz" rows="5" placeholder="Paste your resume or a career summary…">${esc(prof.resume_text || "")}</textarea></label>
         <div class="row" style="justify-content:flex-end"><button class="btn sm primary" id="save-resume">Save resume</button></div>`;
    return `<div class="card">
      <div class="card-head"><h3>${S.ICON.target}Career</h3></div>
      <div class="card-body">
        ${resumeBlock}
        <div class="section-label" style="margin:14px 0 8px">Goals ${readOnly ? "" : `<a href="#" id="add-goal" class="linky">+ add</a>`}</div>
        ${goals.length ? goals.map((g) => `
          <div class="goal" style="border-top:1px solid var(--line);padding:9px 0">
            <div class="row between"><div><strong>${esc(g.title)}</strong> <span class="pill ${g.status === "done" ? "green" : g.status === "paused" ? "amber" : ""}">${esc(g.status)}</span></div>
              ${readOnly ? "" : `<div class="row"><a href="#" class="linky" data-edit-goal="${g.id}">edit</a><a href="#" class="linky danger" data-del-goal="${g.id}">delete</a></div>`}</div>
            <div class="bar" style="height:7px;background:var(--line);border-radius:99px;margin-top:6px;overflow:hidden"><span style="display:block;height:100%;width:${g.progress_pct || 0}%;background:${V}"></span></div>
            ${g.target_date ? `<div class="sub" style="margin-top:4px">Target ${esc(g.target_date)}</div>` : ""}
          </div>`).join("") : '<div class="empty">No goals yet.</div>'}
        <div class="section-label" style="margin:14px 0 8px">Achievements ${readOnly ? "" : `<a href="#" id="add-ach" class="linky">+ add</a>`}</div>
        ${ach.length ? `<ul class="tickitems">${ach.map((a) => `<li style="padding:6px 0;display:block">
          <div class="row between"><span>${S.ICON.check}${esc(a.title)}${a.achieved_on ? ` <span class="muted">· ${esc(a.achieved_on)}</span>` : ""}</span>${readOnly ? "" : `<a href="#" class="linky danger" data-del-ach="${a.id}">delete</a>`}</div>
          ${a.description ? `<div class="sub" style="margin-left:23px">${esc(a.description)}</div>` : ""}</li>`).join("")}</ul>` : '<div class="empty">No achievements yet.</div>'}
      </div></div>`;
  }

  function skillsCard() {
    const skills = data.skills || [];
    // Group by source so "project experience" reads distinctly from engine-practised.
    const groups = {};
    skills.forEach((s) => { (groups[s.source] = groups[s.source] || []).push(s); });
    const order = SKILL_SOURCES.map((s) => s.v).filter((v) => groups[v]);
    return `<div class="card">
      <div class="card-head"><h3>${S.ICON.target}Skills</h3>${readOnly ? "" : `<button class="btn sm ghost" id="add-skill">${S.ICON.plus}Add skill</button>`}</div>
      <div class="card-body">
        <div class="sub" style="margin-bottom:8px">What you can already do — including skills you proved on real projects, not just in the Academy. Your coach uses these.</div>
        ${skills.length ? order.map((src) => `
          <div style="margin-bottom:10px">
            <div class="section-label" style="margin-bottom:6px">${esc(srcLabel(src))}</div>
            <div class="row wrap" style="gap:6px">${groups[src].map((s) => `
              <span class="chip" style="cursor:${readOnly ? "default" : "pointer"}" ${readOnly ? "" : `data-edit-skill="${s.id}"`} title="${esc(s.level)}${s.note ? " · " + esc(s.note) : ""}">
                ${esc(s.name)} <span class="muted" style="font-size:11px">${esc(s.level)}</span>
                ${readOnly ? "" : `<a href="#" class="linky danger" data-del-skill="${s.id}" style="margin-left:4px">✕</a>`}</span>`).join("")}</div>
          </div>`).join("") : '<div class="empty">No skills listed yet.</div>'}
      </div></div>`;
  }

  function readingCard() {
    const r = data.reading || [];
    const now = r.filter((x) => x.progress.status === "reading");
    const done = r.filter((x) => x.progress.status === "done");
    return `<div class="card">
      <div class="card-head"><h3>${S.ICON.book}Reading &amp; Philosophy</h3><a href="/reading" class="btn sm ghost">Open</a></div>
      <div class="card-body">
        <div class="sub" style="margin-bottom:8px">${done.length}/${r.length} of the canon complete${now.length ? ` · reading ${now.length}` : ""}.</div>
        ${now.length ? `<div class="section-label">Reading now</div><ul class="tickitems">${now.map((x) => `<li>${S.ICON.book}${esc(x.title)}</li>`).join("")}</ul>` : '<div class="empty">Nothing in progress — open the canon to start.</div>'}
      </div></div>`;
  }

  function learningCard() {
    if (readOnly) return "";  // enrollment progress is the viewer's, not the target's
    const n = courseCount();
    return `<div class="card">
      <div class="card-head"><h3>${S.ICON.cap}Learning</h3><a href="/academy" class="btn sm ghost">Open Academy</a></div>
      <div class="card-body"><div class="sub">${n ? `You're enrolled in ${n} course${n === 1 ? "" : "s"}. Keep your streak going in the Academy.` : "Your Academy courses and today's assignment live in the Academy tab."}</div></div></div>`;
  }

  function journalCard() {
    const items = data.growth || [];
    return `<div class="card">
      <div class="card-head"><h3>${S.ICON.sparkle}Growth journal</h3>${readOnly ? "" : `<button class="btn sm ghost" id="add-growth">${S.ICON.plus}Add</button>`}</div>
      <div class="card-body">
        <div class="sub" style="margin-bottom:8px">Obstacles you're working through and reflections. Your coach reads these to help.</div>
        ${items.length ? items.map((g) => `
          <div class="row between" style="border-top:1px solid var(--line);padding:8px 0">
            <div><span class="pill ${g.kind === "obstacle" ? "amber" : ""}">${esc(g.kind)}</span> <strong>${esc(g.title)}</strong>${g.detail ? `<div class="sub">${esc(g.detail)}</div>` : ""}</div>
            ${readOnly ? "" : `<a href="#" class="linky danger" data-del-growth="${g.id}">delete</a>`}
          </div>`).join("") : '<div class="empty">Nothing yet.</div>'}
      </div></div>`;
  }

  function render() {
    const who = readOnly && data.user ? `${esc(data.user.name)}'s development` : "Your development";
    view.innerHTML = `
      <div class="pagehead"><div>
        <h2>${who}</h2>
        <div class="lead">Your whole growth in one place — physical, learning, career, and reading.</div>
      </div>${readOnly ? "" : `<button class="btn primary" id="ask-coach">${S.ICON.sparkle}Ask your coach</button>`}</div>

      <div class="tiles4" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:12px;margin-bottom:16px">
        ${tile(S.ICON.heart, "Physical", null, V, data.physical.latest && data.physical.latest.body_fat_pct != null ? `${data.physical.latest.body_fat_pct}%` : "—", "body fat")}
        ${readOnly ? "" : tile(S.ICON.cap, "Learning", null, V, String(courseCount()), "courses", "/academy")}
        ${tile(S.ICON.target, "Career", goalAvg(), V, "", "avg goal progress")}
        ${tile(S.ICON.book, "Reading", readingPct(), V, "", "canon complete", "/reading")}
      </div>

      <div class="dev-cols" style="display:grid;grid-template-columns:1fr 1fr;gap:16px;align-items:start">
        <div style="display:flex;flex-direction:column;gap:16px">${physicalCard()}${readingCard()}${learningCard()}</div>
        <div style="display:flex;flex-direction:column;gap:16px">${careerCard()}${skillsCard()}${journalCard()}</div>
      </div>`;

    // single-column on narrow screens
    if (window.matchMedia("(max-width:900px)").matches) S.qs(".dev-cols").style.gridTemplateColumns = "1fr";
    wire();
  }

  // --- wiring ---------------------------------------------------------------
  function wire() {
    if (readOnly) return;
    const ac = S.qs("#ask-coach"); if (ac) ac.onclick = () => (window.SentinelOpenCoach ? window.SentinelOpenCoach() : S.toast("Coach isn't configured", "err"));

    const am = S.qs("#add-metric"); if (am) am.onclick = () => formModal("Log body stats", [
      { name: "body_fat_pct", label: "Body fat %", type: "number", step: "0.1" },
      { name: "weight_kg", label: "Weight (kg)", type: "number", step: "0.1" },
      { name: "date", label: "Date (blank = today)", type: "date" },
    ], (o) => api("/api/development/body-metrics", { method: "POST", body: { body_fat_pct: num(o.body_fat_pct), weight_kg: num(o.weight_kg), date: o.date || null } }));

    const addPr = S.qs("#add-pr"); if (addPr) addPr.onclick = (e) => { e.preventDefault(); prForm(); };
    S.qsa("[data-edit-pr]").forEach((a) => a.onclick = (e) => { e.preventDefault(); prForm(data.physical.prs.find((r) => r.id == a.dataset.editPr)); });
    S.qsa("[data-del-pr]").forEach((a) => a.onclick = (e) => { e.preventDefault(); del(`/api/development/prs/${a.dataset.delPr}`); });

    const sr = S.qs("#save-resume"); if (sr) sr.onclick = async () => {
      try { await api("/api/development/resume", { method: "PATCH", body: { headline: S.qs("#hl").value, resume_text: S.qs("#rz").value } }); S.toast("Saved", "ok"); }
      catch (e) { S.toast(e.detail || "Couldn't save", "err"); }
    };

    const ag = S.qs("#add-goal"); if (ag) ag.onclick = (e) => { e.preventDefault(); goalForm(); };
    S.qsa("[data-edit-goal]").forEach((a) => a.onclick = (e) => { e.preventDefault(); goalForm(data.career.goals.find((g) => g.id == a.dataset.editGoal)); });
    S.qsa("[data-del-goal]").forEach((a) => a.onclick = (e) => { e.preventDefault(); del(`/api/development/goals/${a.dataset.delGoal}`); });

    const aa = S.qs("#add-ach"); if (aa) aa.onclick = (e) => { e.preventDefault(); formModal("Add achievement", [
      { name: "title", label: "Title", ph: "e.g. Shipped the Atrium assistant" },
      { name: "description", label: "Description", type: "textarea", rows: 3, ph: "What you did and the impact (optional)" },
      { name: "achieved_on", label: "Date", type: "date" },
    ], (o) => api("/api/development/achievements", { method: "POST", body: { title: o.title, description: o.description || null, achieved_on: o.achieved_on || null } })); };
    S.qsa("[data-del-ach]").forEach((a) => a.onclick = (e) => { e.preventDefault(); del(`/api/development/achievements/${a.dataset.delAch}`); });

    const ask = S.qs("#add-skill"); if (ask) ask.onclick = () => skillForm();
    S.qsa("[data-edit-skill]").forEach((el) => el.onclick = (e) => {
      if (e.target.closest("[data-del-skill]")) return;  // let the ✕ handle its own click
      e.preventDefault(); skillForm((data.skills || []).find((s) => s.id == el.dataset.editSkill));
    });
    S.qsa("[data-del-skill]").forEach((a) => a.onclick = (e) => { e.preventDefault(); e.stopPropagation(); del(`/api/development/skills/${a.dataset.delSkill}`); });

    const agr = S.qs("#add-growth"); if (agr) agr.onclick = () => formModal("Add to journal", [
      { name: "kind", label: "Kind", type: "select", value: "reflection", options: [{ v: "reflection", t: "Reflection" }, { v: "obstacle", t: "Obstacle" }, { v: "note", t: "Note" }] },
      { name: "title", label: "Title", ph: "What's on your mind?" },
      { name: "detail", label: "Detail", type: "textarea" },
    ], (o) => api("/api/development/growth", { method: "POST", body: { kind: o.kind, title: o.title, detail: o.detail } }));
    S.qsa("[data-del-growth]").forEach((a) => a.onclick = (e) => { e.preventDefault(); del(`/api/development/growth/${a.dataset.delGrowth}`); });
  }

  function prForm(pr) {
    formModal(pr ? "Edit PR" : "Add personal record", [
      { name: "exercise_name", label: "Exercise / activity", value: pr && pr.exercise_name, ph: "e.g. Bench Press, or 10 km run" },
      { name: "weight_value", label: "Weight (for lifts)", type: "number", step: "0.5", value: pr && pr.weight_value },
      { name: "weight_unit", label: "Unit", type: "select", value: (pr && pr.weight_unit) || "kg", options: [{ v: "kg", t: "kg" }, { v: "lb", t: "lb" }] },
      { name: "reps", label: "Reps (for lifts)", type: "number", value: (pr && pr.reps) || 1 },
      { name: "detail", label: "Result (for runs/times/distances)", value: pr && pr.detail, ph: "e.g. ~59 min, or 5:30 / km" },
      { name: "achieved_on", label: "Achieved on", type: "date", value: pr && pr.achieved_on },
    ], (o) => {
      const body = { exercise_name: o.exercise_name, weight_value: num(o.weight_value) || 0, weight_unit: o.weight_unit, reps: num(o.reps) || 1, detail: o.detail || null, achieved_on: o.achieved_on || null };
      return pr ? api(`/api/development/prs/${pr.id}`, { method: "PATCH", body }) : api("/api/development/prs", { method: "POST", body });
    });
  }

  function goalForm(g) {
    formModal(g ? "Edit goal" : "Add goal", [
      { name: "title", label: "Goal", value: g && g.title, ph: "e.g. Become Agora backend developer" },
      { name: "description", label: "Description", type: "textarea", value: g && g.description },
      { name: "status", label: "Status", type: "select", value: (g && g.status) || "active", options: [{ v: "active", t: "Active" }, { v: "paused", t: "Paused" }, { v: "done", t: "Done" }] },
      { name: "progress_pct", label: "Progress %", type: "number", value: (g && g.progress_pct) || 0 },
      { name: "target_date", label: "Target date", type: "date", value: g && g.target_date },
    ], (o) => {
      const body = { title: o.title, description: o.description, status: o.status, progress_pct: num(o.progress_pct), target_date: o.target_date || null };
      return g ? api(`/api/development/goals/${g.id}`, { method: "PATCH", body }) : api("/api/development/goals", { method: "POST", body });
    });
  }

  function skillForm(sk) {
    formModal(sk ? "Edit skill" : "Add skill", [
      { name: "name", label: "Skill", value: sk && sk.name, ph: "e.g. SQL, pandas, GitHub" },
      { name: "level", label: "Proficiency", type: "select", value: (sk && sk.level) || "Intermediate", options: SKILL_LEVELS.map((l) => ({ v: l, t: l })) },
      { name: "source", label: "How you gained it", type: "select", value: (sk && sk.source) || "project", options: SKILL_SOURCES },
      { name: "note", label: "Note", type: "textarea", rows: 2, value: sk && sk.note, ph: "e.g. built the whole Upwork pipeline with it (optional)" },
    ], (o) => {
      const body = { name: o.name, level: o.level, source: o.source, note: o.note || null };
      return sk ? api(`/api/development/skills/${sk.id}`, { method: "PATCH", body }) : api("/api/development/skills", { method: "POST", body });
    });
  }

  async function del(path) {
    try { await api(path, { method: "DELETE" }); load(); }
    catch (e) { S.toast(e.detail || "Couldn't delete", "err"); }
  }

  async function load() {
    view.innerHTML = S.skeleton ? S.skeleton({ rows: 6 }) : "Loading…";
    try {
      data = await api(readOnly ? `/api/development/user/${targetId}` : "/api/development/me");
    } catch (e) {
      view.innerHTML = `<div class="empty card pad">${esc(e.detail || "Couldn't load this profile.")}</div>`;
      return;
    }
    if (!readOnly) { try { courses = await api("/api/academy/courses"); } catch (e) { courses = null; } }
    render();
  }

  // Let the global Coach refresh this hub after it applies an approved edit.
  if (!readOnly) window.SentinelReloadDevelopment = load;
  load();
};

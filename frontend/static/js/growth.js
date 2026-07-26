// Development Overview — the holistic hub, organized around FOUR GROWTH DIMENSIONS:
// Spiritual · Professional · Mental · Physical. Layout, top to bottom:
//   1. The compass — four progress rings (goal progress per dimension). Each ring carries a
//      small tick at the "expected by today" position, derived from the goal's created→target
//      window, so ahead/behind is visible at a glance.
//   2. The pace band — the same actual-vs-expected, laid on a date track per dimension.
//   3. Four equal dimension boxes (click to expand). Goals + objectives first, then that
//      dimension's records as collapsible sub-sections. NOTHING from the old hub was dropped:
//      Physical → body stats + PRs · Professional → resume, achievements, skills ·
//      Mental → Academy learning + the book/essay canon · Spiritual → journal + philosophy canon.
// A manager opens ?user=<id> for a read-only view. The same data feeds the AI coach.
window.pageInit = async (S) => {
  const view = S.view();
  const esc = S.esc;
  const api = S.api;
  const params = new URLSearchParams(location.search);
  const targetId = params.get("user");
  const readOnly = !!targetId;

  let data = null;
  let courses = null;

  // UI state that must survive the full re-render load() does after every save.
  const openDims = new Set();      // expanded dimension boxes
  const openSubs = new Set();      // expanded <details> — "dim:sub" and "goal:<id>" keys

  const SKILL_LEVELS = ["Beginner", "Intermediate", "Advanced"];
  const SKILL_SOURCES = [
    { v: "project", t: "Project experience" },
    { v: "mastery_engine", t: "Mastery Engine" },
    { v: "course", t: "Course" },
    { v: "certification", t: "Certification" },
    { v: "other", t: "Other" },
  ];
  const srcLabel = (v) => (SKILL_SOURCES.find((s) => s.v === v) || {}).t || v;

  // The four dimensions. Hues live in styles.css as --dim-<key> so dark mode can retune them.
  const DIMS = [
    { key: "spiritual", name: "Spiritual", icon: "flame", blurb: "Character & inner life" },
    { key: "professional", name: "Professional", icon: "target", blurb: "Craft & career" },
    { key: "mental", name: "Mental", icon: "cap", blurb: "Learning & mind" },
    { key: "physical", name: "Physical", icon: "heart", blurb: "Body & training" },
  ];
  const DIM_KEYS = DIMS.map((d) => d.key);
  // Legacy rows predate `dimension` — anything unknown reads as professional (the old scope).
  const dimOf = (g) => (DIM_KEYS.includes(g.dimension) ? g.dimension : "professional");
  const goalsFor = (key) => (data.career.goals || []).filter((g) => dimOf(g) === key);
  const dimName = (key) => (DIMS.find((d) => d.key === key) || {}).name || key;

  // --- progress + pace math ---------------------------------------------------
  // Actual = avg progress of the dimension's ACTIVE goals; all-done ⇒ 100; no goals ⇒ null.
  function dimActual(key) {
    const gs = goalsFor(key);
    const act = gs.filter((g) => g.status === "active");
    if (act.length) return act.reduce((a, g) => a + (g.progress_pct || 0), 0) / act.length;
    if (gs.length && gs.some((g) => g.status === "done")) return 100;
    return null;
  }

  // Expected-by-today for one goal: linear from created_at → target_date. Null when undated.
  function goalExpected(g) {
    if (!g.target_date || !g.created_at || g.status !== "active") return null;
    const start = new Date(g.created_at).getTime();
    const end = new Date(g.target_date + "T23:59:59").getTime();
    if (!(end > start)) return 100;
    return Math.max(0, Math.min(100, ((Date.now() - start) / (end - start)) * 100));
  }

  function dimExpected(key) {
    const es = goalsFor(key).map(goalExpected).filter((e) => e != null);
    if (!es.length) return null;
    return es.reduce((a, b) => a + b, 0) / es.length;
  }

  // The shared ahead/behind verdict: within ±2 points reads as "on pace".
  function paceChip(actual, expected) {
    if (actual == null || expected == null) return "";
    const d = Math.round(actual - expected);
    if (Math.abs(d) <= 2) return `<span class="pace-chip on">on pace</span>`;
    return d > 0
      ? `<span class="pace-chip ahead">▲ ${d} ahead</span>`
      : `<span class="pace-chip behind">▼ ${Math.abs(d)} behind</span>`;
  }

  // Date window a dimension is pacing against: earliest active-goal start → latest target.
  function dimWindow(key) {
    const gs = goalsFor(key).filter((g) => g.status === "active" && g.target_date && g.created_at);
    if (!gs.length) return null;
    const start = gs.map((g) => g.created_at.slice(0, 10)).sort()[0];
    const end = gs.map((g) => g.target_date).sort().slice(-1)[0];
    return { start, end };
  }

  // --- the compass ring: actual arc + expected-today tick ----------------------
  function ringSvg(actual, expected) {
    const size = 92, r = 37, c = 2 * Math.PI * r, cx = size / 2;
    if (actual == null) {
      return `<svg class="dc-ring" width="${size}" height="${size}" viewBox="0 0 ${size} ${size}" aria-hidden="true">
        <circle cx="${cx}" cy="${cx}" r="${r}" fill="none" stroke="var(--line)" stroke-width="7" stroke-dasharray="2 5"/>
        <text x="${cx}" y="${cx + 6}" text-anchor="middle" font-size="19" font-weight="800" fill="var(--muted)">—</text></svg>`;
    }
    const pct = Math.max(0, Math.min(100, Math.round(actual)));
    const off = c * (1 - pct / 100);
    const tick = expected == null ? "" :
      `<line x1="${cx}" y1="${cx - r - 6}" x2="${cx}" y2="${cx - r + 7}" stroke="var(--ink)" stroke-width="2"
        stroke-linecap="round" transform="rotate(${(expected * 3.6).toFixed(1)} ${cx} ${cx})" opacity=".85"/>`;
    return `<svg class="dc-ring" width="${size}" height="${size}" viewBox="0 0 ${size} ${size}" aria-hidden="true">
      <circle cx="${cx}" cy="${cx}" r="${r}" fill="none" stroke="var(--line)" stroke-width="7"/>
      <circle cx="${cx}" cy="${cx}" r="${r}" fill="none" stroke="var(--hue)" stroke-width="7" stroke-linecap="round"
        stroke-dasharray="${c.toFixed(1)}" stroke-dashoffset="${off.toFixed(1)}" transform="rotate(-90 ${cx} ${cx})"/>
      ${tick}
      <text x="${cx}" y="${cx + 6}" text-anchor="middle" font-size="19" font-weight="800" fill="var(--text)">${pct}%</text></svg>`;
  }

  function ringCell(d) {
    const actual = dimActual(d.key), expected = dimExpected(d.key);
    const active = goalsFor(d.key).filter((g) => g.status === "active").length;
    const sub = actual == null
      ? "no goal set"
      : `${active} active goal${active === 1 ? "" : "s"}`;
    return `<button class="dim-cell" data-goto-dim="${d.key}" style="--hue:var(--dim-${d.key})" title="Open ${esc(d.name)}">
      <span class="dc-label">${S.ICON[d.icon]}${esc(d.name)}</span>
      ${ringSvg(actual, expected)}
      <span class="dc-sub">${esc(sub)}</span>
      <span class="dc-chip">${paceChip(actual, expected) || (actual == null && !readOnly ? '<span class="pace-chip none">+ set one</span>' : "")}</span>
    </button>`;
  }

  // --- the pace band: actual vs where-the-calendar-says per dimension ----------
  function paceRow(d) {
    const actual = dimActual(d.key), expected = dimExpected(d.key);
    const win = dimWindow(d.key);
    const fill = actual == null ? 0 : Math.max(0, Math.min(100, actual));
    const tick = expected == null ? "" : `<b class="pr-tick" style="left:${expected.toFixed(1)}%" title="Where you should be today"></b>`;
    const right = actual == null
      ? `<span class="pr-note">no active goals</span>`
      : expected == null
        ? `<span class="pr-note">no target date</span>`
        : paceChip(actual, expected);
    const dates = win
      ? `<div class="pr-dates"><span>${esc(win.start)}</span><span>target ${esc(win.end)}</span></div>`
      : "";
    return `<div class="pace-row" style="--hue:var(--dim-${d.key})">
      <span class="pr-name">${S.ICON[d.icon]}${esc(d.name)}</span>
      <div class="pr-lane"><div class="pr-track"><i style="width:${fill.toFixed(1)}%"></i>${tick}</div>${dates}</div>
      <span class="pr-delta">${right}</span>
    </div>`;
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

  // --- goals ------------------------------------------------------------------
  // A goal's description doubles as its OBJECTIVES: lines starting with "-", "•" or "*" render
  // as a checklist; anything else stays prose. That keeps objectives free-form and durable.
  function objectivesHtml(desc) {
    if (!desc) return "";
    const lines = String(desc).split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
    const items = [], prose = [];
    lines.forEach((l) => {
      const m = l.match(/^[-•*]\s+(.*)$/);
      if (m) items.push(m[1]); else prose.push(l);
    });
    return (prose.length ? `<div class="goal-desc">${prose.map(esc).join("<br>")}</div>` : "")
      + (items.length ? `<div class="section-label" style="margin:8px 0 4px">Objectives</div>
         <ul class="goal-objectives">${items.map((o) => `<li>${esc(o)}</li>`).join("")}</ul>` : "");
  }

  function goalItem(g) {
    const expected = goalExpected(g);
    const pct = Math.max(0, Math.min(100, g.progress_pct || 0));
    const key = `goal:${g.id}`;
    const tick = expected == null ? "" : `<b class="pr-tick" style="left:${expected.toFixed(1)}%"></b>`;
    return `<details class="goal-item" data-ui="${key}" ${openSubs.has(key) ? "open" : ""}>
      <summary>
        <span class="gi-title">${esc(g.title)}</span>
        <span class="pill ${g.status === "done" ? "green" : g.status === "paused" ? "amber" : ""}">${esc(g.status)}</span>
        <span class="gi-pct">${pct}%</span>
        ${S.ICON.chev}
      </summary>
      <div class="gi-body">
        <div class="pr-track gi-bar"><i style="width:${pct}%"></i>${tick}</div>
        <div class="gi-meta">
          ${g.target_date ? `Target ${esc(g.target_date)}` : "No target date"}
          ${expected != null ? ` · by today you should be at <strong>${Math.round(expected)}%</strong> ` + paceChip(g.progress_pct || 0, expected) : ""}
        </div>
        ${objectivesHtml(g.description)}
        ${readOnly ? "" : `<div class="row" style="gap:10px;margin-top:8px"><a href="#" class="linky" data-edit-goal="${g.id}">edit</a><a href="#" class="linky danger" data-del-goal="${g.id}">delete</a></div>`}
      </div>
    </details>`;
  }

  function goalsBlock(dimKey) {
    const gs = goalsFor(dimKey);
    return `<div class="section-label" style="margin-bottom:6px">Goals ${readOnly ? "" : `<a href="#" class="linky" data-add-goal="${dimKey}">+ add</a>`}</div>
      ${gs.length ? gs.map(goalItem).join("")
        : `<div class="empty">No ${esc(dimName(dimKey).toLowerCase())} goals yet.${readOnly ? "" : " Add one to start the ring."}</div>`}`;
  }

  // --- collapsible record sub-sections (everything the old hub showed) ---------
  function sub(dimKey, id, label, inner, headExtra) {
    const key = `${dimKey}:${id}`;
    return `<details class="dim-sub" data-ui="${key}" ${openSubs.has(key) ? "open" : ""}>
      <summary><span>${esc(label)}</span><span class="ds-right">${headExtra || ""}${S.ICON.chev}</span></summary>
      <div class="ds-body">${inner}</div>
    </details>`;
  }

  function physicalSubs() {
    const p = data.physical;
    const latest = p.latest;
    const prs = p.prs || [];
    const bf = latest && latest.body_fat_pct != null ? `${latest.body_fat_pct}%` : "—";
    const wt = latest && latest.weight_kg != null ? `${latest.weight_kg} kg` : "—";
    const stats = `<div class="spread" style="margin-bottom:10px">
        <div class="stat"><div class="section-label">Body fat</div><strong style="font-size:22px">${bf}</strong></div>
        <div class="stat"><div class="section-label">Weight</div><strong style="font-size:22px">${wt}</strong></div>
        <div class="stat"><div class="section-label">As of</div><strong style="font-size:15px">${latest ? esc(latest.date) : "—"}</strong></div>
      </div>
      ${readOnly ? "" : `<button class="btn sm ghost" id="add-metric">${S.ICON.plus}Log body stats</button>`}`;
    const prList = prs.length ? `<div class="pr-list">${prs.map((r) => `
        <div class="row between pr-row" style="padding:7px 0;border-top:1px solid var(--line)">
          <div><strong>${esc(r.exercise_name)}</strong> <span class="muted">${esc(r.display || "")}</span></div>
          ${readOnly ? "" : `<div class="row"><a href="#" class="linky" data-edit-pr="${r.id}">edit</a><a href="#" class="linky danger" data-del-pr="${r.id}">delete</a></div>`}
        </div>`).join("")}</div>` : '<div class="empty">No PRs logged yet.</div>';
    return sub("physical", "stats", "Body stats", stats, `<span class="ds-hint">${bf} · ${wt}</span>`)
      + sub("physical", "prs", "Personal records", `${readOnly ? "" : `<div style="margin-bottom:6px"><a href="#" id="add-pr" class="linky">+ add</a></div>`}${prList}`,
          `<span class="ds-hint">${prs.length}</span>`);
  }

  function professionalSubs() {
    const c = data.career;
    const prof = c.profile || {};
    const ach = c.achievements || [];
    const skills = data.skills || [];
    const resumeBlock = readOnly
      ? `<div class="section-label">Headline</div><div style="margin-bottom:8px">${esc(prof.headline || "—")}</div>
         <div class="section-label">Resume</div><div class="prewrap muted">${esc(prof.resume_text || "—")}</div>`
      : `<label class="field"><span>Headline</span><input id="hl" value="${esc(prof.headline || "")}" placeholder="e.g. Aspiring backend engineer"></label>
         <label class="field"><span>Resume / bio</span><textarea id="rz" rows="5" placeholder="Paste your resume or a career summary…">${esc(prof.resume_text || "")}</textarea></label>
         <div class="row" style="justify-content:flex-end"><button class="btn sm primary" id="save-resume">Save resume</button></div>`;
    const achList = ach.length ? `<ul class="tickitems">${ach.map((a) => `<li style="padding:6px 0;display:block">
        <div class="row between"><span>${S.ICON.check}${esc(a.title)}${a.achieved_on ? ` <span class="muted">· ${esc(a.achieved_on)}</span>` : ""}</span>${readOnly ? "" : `<a href="#" class="linky danger" data-del-ach="${a.id}">delete</a>`}</div>
        ${a.description ? `<div class="sub" style="margin-left:23px">${esc(a.description)}</div>` : ""}</li>`).join("")}</ul>` : '<div class="empty">No achievements yet.</div>';
    // Group skills by source so "project experience" reads distinctly from engine-practised.
    const groups = {};
    skills.forEach((s) => { (groups[s.source] = groups[s.source] || []).push(s); });
    const order = SKILL_SOURCES.map((s) => s.v).filter((v) => groups[v]);
    const skillsInner = `<div class="sub" style="margin-bottom:8px">What you can already do, including skills you proved on real projects, not just in the Academy. Your coach uses these.</div>
      ${readOnly ? "" : `<div style="margin-bottom:8px"><a href="#" id="add-skill" class="linky">+ add skill</a></div>`}
      ${skills.length ? order.map((src) => `
        <div style="margin-bottom:10px">
          <div class="section-label" style="margin-bottom:6px">${esc(srcLabel(src))}</div>
          <div class="row wrap" style="gap:6px">${groups[src].map((s) => `
            <span class="chip" style="cursor:${readOnly ? "default" : "pointer"}" ${readOnly ? "" : `data-edit-skill="${s.id}"`} title="${esc(s.level)}${s.note ? " · " + esc(s.note) : ""}">
              ${esc(s.name)} <span class="muted" style="font-size:11px">${esc(s.level)}</span>
              ${readOnly ? "" : `<a href="#" class="linky danger" data-del-skill="${s.id}" style="margin-left:4px">✕</a>`}</span>`).join("")}</div>
        </div>`).join("") : '<div class="empty">No skills listed yet.</div>'}`;
    return sub("professional", "profile", "Career profile", resumeBlock,
        prof.headline ? `<span class="ds-hint">${esc(prof.headline)}</span>` : "")
      + sub("professional", "achievements", "Achievements", `${readOnly ? "" : `<div style="margin-bottom:6px"><a href="#" id="add-ach" class="linky">+ add</a></div>`}${achList}`,
          `<span class="ds-hint">${ach.length}</span>`)
      + sub("professional", "skills", "Skills", skillsInner, `<span class="ds-hint">${skills.length}</span>`);
  }

  function mentalSubs() {
    // Books + essays live here; philosophy items belong to the Spiritual dimension below.
    const canon = (data.reading || []).filter((x) => x.kind !== "philosophy");
    const now = canon.filter((x) => x.progress.status === "reading");
    const done = canon.filter((x) => x.progress.status === "done");
    const readingInner = `<div class="sub" style="margin-bottom:8px">${done.length}/${canon.length} of the canon complete${now.length ? ` · reading ${now.length}` : ""}. <a class="linky" href="/reading">Open the canon</a></div>
      ${now.length ? `<div class="section-label">Reading now</div><ul class="tickitems">${now.map((x) => `<li>${S.ICON.book}${esc(x.title)}${x.author ? ` <span class="muted">· ${esc(x.author)}</span>` : ""}</li>`).join("")}</ul>`
        : '<div class="empty">Nothing in progress. Open the canon to start.</div>'}`;
    let out = "";
    if (!readOnly) {  // enrollment progress is the viewer's, not the target's
      const list = courses ? (courses.programs || courses.courses || []) : [];
      const n = Array.isArray(list) ? list.length : 0;
      out += sub("mental", "learning", "Learning · Academy",
        `<div class="sub">${n ? `You're enrolled in ${n} course${n === 1 ? "" : "s"}. Keep your streak going in the Academy.` : "Your Academy courses and today's assignment live in the Academy tab."} <a class="linky" href="/academy">Open Academy</a></div>`,
        n ? `<span class="ds-hint">${n} course${n === 1 ? "" : "s"}</span>` : "");
    }
    out += sub("mental", "reading", "Reading — books & essays", readingInner,
      `<span class="ds-hint">${done.length}/${canon.length}</span>`);
    return out;
  }

  function spiritualSubs() {
    const items = data.growth || [];
    const journalInner = `<div class="sub" style="margin-bottom:8px">Obstacles you're working through and reflections. Your coach reads these to help.</div>
      ${readOnly ? "" : `<div style="margin-bottom:6px"><a href="#" id="add-growth" class="linky">+ add</a></div>`}
      ${items.length ? items.map((g) => `
        <div class="row between" style="border-top:1px solid var(--line);padding:8px 0">
          <div><span class="pill ${g.kind === "obstacle" ? "amber" : ""}">${esc(g.kind)}</span> <strong>${esc(g.title)}</strong>${g.detail ? `<div class="sub">${esc(g.detail)}</div>` : ""}</div>
          ${readOnly ? "" : `<a href="#" class="linky danger" data-del-growth="${g.id}">delete</a>`}
        </div>`).join("") : '<div class="empty">Nothing yet.</div>'}`;
    const phil = (data.reading || []).filter((x) => x.kind === "philosophy");
    const philDone = phil.filter((x) => x.progress.status === "done");
    const philInner = phil.length ? `<ul class="tickitems">${phil.map((x) => `
        <li style="display:block;padding:5px 0"><div class="row between">
          <span>${S.ICON.book}${esc(x.title)}${x.author ? ` <span class="muted">· ${esc(x.author)}</span>` : ""}</span>
          <span class="pill ${x.progress.status === "done" ? "green" : x.progress.status === "reading" ? "amber" : ""}">${esc(x.progress.status.replace("_", " "))}</span>
        </div></li>`).join("")}</ul>
        <div class="sub" style="margin-top:6px"><a class="linky" href="/reading">Open the canon</a></div>`
      : '<div class="empty">No philosophies in the canon yet.</div>';
    let out = sub("spiritual", "journal", "Growth journal", journalInner,
      `<span class="ds-hint">${items.length}</span>`);
    if (phil.length || !readOnly)
      out += sub("spiritual", "philosophy", "Philosophy", philInner,
        phil.length ? `<span class="ds-hint">${philDone.length}/${phil.length}</span>` : "");
    return out;
  }

  const SUBS = { spiritual: spiritualSubs, professional: professionalSubs, mental: mentalSubs, physical: physicalSubs };

  // --- one dimension box --------------------------------------------------------
  function dimBox(d) {
    const gs = goalsFor(d.key);
    const active = gs.filter((g) => g.status === "active");
    const top = active[0] || gs[0];
    const open = openDims.has(d.key);
    const peek = top
      ? `<div class="dp-goal">${esc(top.title)}</div>
         <div class="pr-track dp-bar"><i style="width:${Math.max(0, Math.min(100, top.progress_pct || 0))}%"></i></div>`
      : `<div class="dp-goal muted">${readOnly ? "No goals yet." : "No goals yet — set one to start the ring."}</div>`;
    return `<section class="dim-box ${open ? "open" : ""}" id="dim-${d.key}" style="--hue:var(--dim-${d.key});--hue-bg:var(--dim-${d.key}-bg)">
      <button class="dim-head" data-toggle-dim="${d.key}" aria-expanded="${open}">
        <span class="dim-glyph">${S.ICON[d.icon]}</span>
        <span class="dim-title"><strong>${esc(d.name)}</strong><small>${esc(d.blurb)}</small></span>
        <span class="dim-head-right">
          <span class="dim-count">${active.length ? `${active.length} active` : gs.length ? `${gs.length} goal${gs.length === 1 ? "" : "s"}` : ""}</span>
          ${S.ICON.chev}
        </span>
      </button>
      <div class="dim-peek">${peek}</div>
      <div class="dim-body">
        ${goalsBlock(d.key)}
        <div class="dim-records">${SUBS[d.key]()}</div>
      </div>
    </section>`;
  }

  // --- page render ----------------------------------------------------------------
  function render() {
    const who = readOnly && data.user ? esc(data.user.name.split(" ")[0]) + "’s growth" : "Your growth";
    const eyebrow = readOnly && data.user ? "Development · " + esc(data.user.name) : "Development · Overview";
    const asOf = data.physical.latest ? esc(data.physical.latest.date) : new Date().toISOString().slice(0, 10);

    view.innerHTML = `<div class="dev">
      <div class="dev-mast">
        <div>
          <div class="dev-eyebrow">${eyebrow}</div>
          <h1>${who}</h1>
          <div class="lede">Four dimensions of everything you're becoming: spirit, craft, mind, and body.</div>
        </div>
        <div class="dev-mast-right">
          ${readOnly ? "" : `<button class="btn primary dev-coach" id="ask-coach">${S.ICON.sparkle}Ask your coach</button>`}
          <div class="dev-mast-meta">AS OF ${asOf}</div>
        </div>
      </div>

      <div class="dim-rings">${DIMS.map(ringCell).join("")}</div>

      <div class="dim-pace">
        <div class="dim-pace-head">Pace — where you are vs where the calendar says <span class="pace-key"><b class="pr-tick demo"></b> = expected today</span></div>
        ${DIMS.map(paceRow).join("")}
      </div>

      <div class="dim-grid">${DIMS.map(dimBox).join("")}</div>
    </div>`;

    wire();
  }

  // --- wiring ---------------------------------------------------------------
  function toggleDim(key, forceOpen) {
    const box = S.qs(`#dim-${key}`);
    if (!box) return;
    const willOpen = forceOpen != null ? forceOpen : !openDims.has(key);
    if (willOpen) openDims.add(key); else openDims.delete(key);
    box.classList.toggle("open", willOpen);
    const head = box.querySelector(".dim-head");
    if (head) head.setAttribute("aria-expanded", String(willOpen));
  }

  function wire() {
    // Expand/collapse works in both modes; edits only when it's your own profile.
    S.qsa("[data-toggle-dim]").forEach((b) => b.onclick = () => toggleDim(b.dataset.toggleDim));
    S.qsa("[data-goto-dim]").forEach((b) => b.onclick = () => {
      const key = b.dataset.gotoDim;
      toggleDim(key, true);
      const box = S.qs(`#dim-${key}`);
      const smooth = !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      if (box) box.scrollIntoView({ behavior: smooth ? "smooth" : "auto", block: "start" });
    });
    // Remember which record sub-sections / goal cards are open across re-renders.
    S.qsa("details[data-ui]").forEach((dt) => dt.addEventListener("toggle", () => {
      if (dt.open) openSubs.add(dt.dataset.ui); else openSubs.delete(dt.dataset.ui);
    }));

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

    S.qsa("[data-add-goal]").forEach((a) => a.onclick = (e) => { e.preventDefault(); goalForm(null, a.dataset.addGoal); });
    S.qsa("[data-edit-goal]").forEach((a) => a.onclick = (e) => { e.preventDefault(); goalForm(data.career.goals.find((g) => g.id == a.dataset.editGoal)); });
    S.qsa("[data-del-goal]").forEach((a) => a.onclick = (e) => { e.preventDefault(); del(`/api/development/goals/${a.dataset.delGoal}`); });

    const aa = S.qs("#add-ach"); if (aa) aa.onclick = (e) => { e.preventDefault(); formModal("Add achievement", [
      { name: "title", label: "Title", ph: "e.g. Shipped the Atrium assistant" },
      { name: "description", label: "Description", type: "textarea", rows: 3, ph: "What you did and the impact (optional)" },
      { name: "achieved_on", label: "Date", type: "date" },
    ], (o) => api("/api/development/achievements", { method: "POST", body: { title: o.title, description: o.description || null, achieved_on: o.achieved_on || null } })); };
    S.qsa("[data-del-ach]").forEach((a) => a.onclick = (e) => { e.preventDefault(); del(`/api/development/achievements/${a.dataset.delAch}`); });

    const ask = S.qs("#add-skill"); if (ask) ask.onclick = (e) => { e.preventDefault(); skillForm(); };
    S.qsa("[data-edit-skill]").forEach((el) => el.onclick = (e) => {
      if (e.target.closest("[data-del-skill]")) return;  // let the ✕ handle its own click
      e.preventDefault(); skillForm((data.skills || []).find((s) => s.id == el.dataset.editSkill));
    });
    S.qsa("[data-del-skill]").forEach((a) => a.onclick = (e) => { e.preventDefault(); e.stopPropagation(); del(`/api/development/skills/${a.dataset.delSkill}`); });

    const agr = S.qs("#add-growth"); if (agr) agr.onclick = (e) => { e.preventDefault(); formModal("Add to journal", [
      { name: "kind", label: "Kind", type: "select", value: "reflection", options: [{ v: "reflection", t: "Reflection" }, { v: "obstacle", t: "Obstacle" }, { v: "note", t: "Note" }] },
      { name: "title", label: "Title", ph: "What's on your mind?" },
      { name: "detail", label: "Detail", type: "textarea" },
    ], (o) => api("/api/development/growth", { method: "POST", body: { kind: o.kind, title: o.title, detail: o.detail } })); };
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

  function goalForm(g, dimKey) {
    formModal(g ? "Edit goal" : `Add ${dimName(dimKey || "professional").toLowerCase()} goal`, [
      { name: "title", label: "Goal", value: g && g.title, ph: "e.g. Become Agora backend developer" },
      { name: "dimension", label: "Dimension", type: "select", value: g ? dimOf(g) : (dimKey || "professional"), options: DIMS.map((d) => ({ v: d.key, t: d.name })) },
      { name: "description", label: "Objectives (one per line, start with -)", type: "textarea", value: g && g.description, ph: "- Ship the capstone\n- Read 2 papers a month" },
      { name: "status", label: "Status", type: "select", value: (g && g.status) || "active", options: [{ v: "active", t: "Active" }, { v: "paused", t: "Paused" }, { v: "done", t: "Done" }] },
      { name: "progress_pct", label: "Progress %", type: "number", value: (g && g.progress_pct) || 0 },
      { name: "target_date", label: "Target date (drives the pace tick)", type: "date", value: g && g.target_date },
    ], (o) => {
      const body = { title: o.title, dimension: o.dimension, description: o.description, status: o.status, progress_pct: num(o.progress_pct), target_date: o.target_date || null };
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

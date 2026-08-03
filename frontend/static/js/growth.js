/* GrowthPanel — the holistic growth hub, organized around FOUR GROWTH DIMENSIONS:
   Spiritual · Professional · Philosophical · Physical — mirroring the Growth nav tabs
   one-to-one. Two parts, which the host may place separately:
     1. The compass — four progress rings. A ring's % is the MASTERY ENGINE's score for that
        dimension's program(s) (via /api/academy/courses) — never typed by hand. The tick marks
        "expected by today" on the run from the area's start to its deadline. Each ring is also
        the DOOR into that dimension's Mastery Engine tab (/academy, /philosophical, /spiritual,
        /gym), with a quieter "Details" button for the pace-band expansion below.
     2. The ledger — the pace band (the same actual-vs-expected on a date track; each row's
        deadline is editable, default 2026-11-04, stored per dimension via
        /api/development/areas) plus the mentor library. Each pace row IS its dimension:
        clicking it expands that dimension's details INLINE beneath it — goals + objectives
        first, then its records as collapsible sub-sections, then a free-form "Other info" dump
        the coach can read and edit. NOTHING from the old hub was dropped:
        Physical → body stats + PRs · Professional → resume, achievements, skills, Academy ·
        Philosophical → books/essays + philosophy canon · Spiritual → journal.

   Mounted TWICE over the app (which is why this is a component, not a page controller —
   2026-08-03, when the Dashboard and this hub became one "Overview"):
     • the Overview page (dashboard.js) splits it — rings up top, ledger under the task board;
     • /growth?user=<id> is a manager's read-only view of one person (growth-page.js).
   The same data feeds the AI coach.

   mount(S, root, opts):
     opts.userId    — read-only view of that person (omit for your own, editable, profile)
     opts.ringsHost — render the compass into this element instead of into `root`, so the host
                      can put something (the task board) between the rings and the ledger
     opts.mast      — render the ledger masthead (title/lede). The Overview supplies its own. */
window.GrowthPanel = {
  async mount(S, root, opts) { return mountGrowth(S, root, opts || {}); },
};

async function mountGrowth(S, root, opts) {
  const view = root;
  const ringsHost = opts.ringsHost || null;
  const showMast = !!opts.mast;
  const esc = S.esc;
  const api = S.api;
  const targetId = opts.userId || null;
  const readOnly = !!targetId;

  let data = null;
  let courses = null;

  // UI state that must survive the full re-render load() does after every save.
  const openDims = new Set();      // expanded dimension boxes
  const openSubs = new Set();      // expanded <details> — "dim:sub" and "goal:<id>" keys
  // Mentor-library open/closed state lives in the DOM, not here: expanding a card or a transcript
  // never re-renders, so there is nothing to restore afterwards.
  const transcriptText = {};          // id -> fetched transcript_text, cached across re-renders

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
  // ('philosophical' replaced 'mental' 2026-07-27; old rows were data-migrated.)
  const DIMS = [
    { key: "spiritual", name: "Spiritual", icon: "flame", blurb: "Faith & inner life" },
    { key: "professional", name: "Professional", icon: "target", blurb: "Craft & career" },
    { key: "philosophical", name: "Philosophical", icon: "cap", blurb: "Mindsets & mental models" },
    { key: "physical", name: "Physical", icon: "heart", blurb: "Body & training" },
  ];
  const DIM_KEYS = DIMS.map((d) => d.key);
  // Legacy rows predate `dimension` — anything unknown reads as professional (the old scope).
  const dimOf = (g) => (DIM_KEYS.includes(g.dimension) ? g.dimension : "professional");
  const goalsFor = (key) => (data.career.goals || []).filter((g) => dimOf(g) === key);
  const dimName = (key) => (DIMS.find((d) => d.key === key) || {}).name || key;

  // --- progress + pace math ---------------------------------------------------
  // Ring % = the MASTERY ENGINE's score for the dimension's program(s) — never typed by hand.
  // Each Growth tab is one engine program; the professional ring rolls up every career
  // program. Physical has no engine program yet, so its ring stays dashed until one exists.
  // (courses is fetched only for your own profile, so a manager's read-only view dashes out.)
  const DIM_PROGRAMS = { philosophical: ["philosophy"], spiritual: ["spiritual"] };
  function dimActual(key) {
    // Physical has no engine program — its ring is the mean progress across the
    // TARGET PRs (lifts/runs/skills) being chased, paused ones excluded.
    if (key === "physical") {
      const ts = ((data.physical || {}).targets || []).filter((t) => t.status !== "paused");
      if (!ts.length) return null;
      return ts.reduce((a, t) => a + (t.progress_pct || 0), 0) / ts.length;
    }
    const progs = (courses && courses.programs) || [];
    const mine = key === "professional"
      ? progs.filter((p) => (p.category || "career") !== "growth")
      : progs.filter((p) => (DIM_PROGRAMS[key] || []).includes(p.id));
    if (!mine.length) return null;
    // Topic-weighted across programs (Σ progressSum / Σ topics) — the engine's own "Overall
    // mastery" formula, so this ring and the tab's engine read the same number. Falls back to
    // a plain mean of pct if the engine predates progressSum.
    const total = mine.reduce((a, p) => a + (p.topicsTotal || 0), 0);
    if (total && mine.every((p) => p.progressSum != null)) {
      return mine.reduce((a, p) => a + (p.progressSum || 0), 0) / total;
    }
    return mine.reduce((a, p) => a + (p.pct || 0), 0) / mine.length;
  }

  // The pace window every dimension races on: a fixed start (when the four-tab system began)
  // to the area's own deadline — editable on the pace band, stored per dimension.
  const START_DEFAULT = "2026-07-27";
  const DEADLINE_DEFAULT = "2026-11-04";
  const areaOf = (key) => (data.areas || {})[key] || {};
  const areaDeadline = (key) => areaOf(key).deadline || DEADLINE_DEFAULT;

  // Expected-by-today: linear from the start to this dimension's deadline.
  function dimExpected(key) {
    const start = new Date(START_DEFAULT + "T00:00:00").getTime();
    const end = new Date(areaDeadline(key) + "T23:59:59").getTime();
    if (!(end > start)) return 100;
    return Math.max(0, Math.min(100, ((Date.now() - start) / (end - start)) * 100));
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

  function dimWindow(key) {
    return { start: START_DEFAULT, end: areaDeadline(key) };
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

  // Each dimension's Mastery Engine tab. Physical has no engine program — its "engine" is the
  // gym page, which is where its target PRs actually move.
  const DIM_TAB = {
    spiritual: "/spiritual", professional: "/academy", philosophical: "/philosophical", physical: "/gym",
  };

  // A ring is two affordances, deliberately separate rather than one overloaded click:
  // the cell OPENS that dimension's engine tab (the thing you came to do), and a quiet
  // "Details" button expands its pace row below (the thing you came to read). A manager's
  // read-only view has no engine to open, so there the whole cell is the Details button.
  function ringCell(d) {
    const actual = dimActual(d.key), expected = dimExpected(d.key);
    const active = goalsFor(d.key).filter((g) => g.status === "active").length;
    const sub = actual == null
      ? (d.key === "physical" ? "no target PRs yet" : "no engine program yet")
      : d.key === "physical"
        ? `${((data.physical || {}).targets || []).filter((t) => t.status !== "paused").length} target PRs`
        : `${active} active goal${active === 1 ? "" : "s"}`;
    const face = `<span class="dc-label">${S.ICON[d.icon]}${esc(d.name)}</span>
      ${ringSvg(actual, expected)}
      <span class="dc-sub">${esc(sub)}</span>
      <span class="dc-chip">${paceChip(actual, expected)}</span>`;
    const main = readOnly
      ? `<button class="dc-main" data-goto-dim="${d.key}" title="Open ${esc(d.name)} details">${face}</button>`
      : `<a class="dc-main" href="${DIM_TAB[d.key]}" title="Open the ${esc(d.name)} Mastery Engine">${face}
          <span class="dc-open">${d.key === "physical" ? "Open gym" : "Open engine"} &rarr;</span></a>`;
    return `<div class="dim-cell" style="--hue:var(--dim-${d.key})">
      ${main}
      ${readOnly ? "" : `<button class="dc-more" data-goto-dim="${d.key}">Details</button>`}
    </div>`;
  }

  // --- the pace band: engine score vs where-the-calendar-says per dimension ----
  // The row is also the dimension's header — a div with role=button (not a <button>) because
  // it legitimately nests an interactive element (the ✎ deadline editor).
  function paceRow(d) {
    const actual = dimActual(d.key), expected = dimExpected(d.key);
    const win = dimWindow(d.key);
    const fill = actual == null ? 0 : Math.max(0, Math.min(100, actual));
    const tick = `<b class="pr-tick" style="left:${expected.toFixed(1)}%" title="Where you should be today"></b>`;
    const right = actual == null
      ? `<span class="pr-note">no engine data</span>`
      : paceChip(actual, expected);
    const dates = `<div class="pr-dates"><span>${esc(win.start)}</span>
      <span>target ${esc(win.end)}${readOnly ? "" : ` <a href="#" class="linky" data-edit-deadline="${d.key}" title="Edit this deadline">✎</a>`}</span></div>`;
    return `<div class="pace-row" data-toggle-dim="${d.key}" role="button" tabindex="0"
        aria-expanded="${openDims.has(d.key)}" title="Open ${esc(d.name)} details">
      <span class="pr-name">${S.ICON[d.icon]}${esc(d.name)}</span>
      <div class="pr-lane"><div class="pr-track"><i style="width:${fill.toFixed(1)}%"></i>${tick}</div>${dates}</div>
      <span class="pr-delta">${right}</span>
      <span class="pr-chev">${S.ICON.chev}</span>
    </div>`;
  }

  // One pace-block = the row (always visible, unchanged) + everything the old dimension box
  // held, revealed inline beneath the row when it's clicked.
  function paceBlock(d) {
    const open = openDims.has(d.key);
    return `<div class="pace-block ${open ? "open" : ""}" id="dim-${d.key}" style="--hue:var(--dim-${d.key})">
      ${paceRow(d)}
      <div class="pace-detail">
        ${goalsBlock(d.key)}
        <div class="dim-records">${SUBS[d.key]()}${notesSub(d.key)}</div>
      </div>
    </div>`;
  }

  // --- generic form modal ---------------------------------------------------
  function formModal(title, fields, onSave, opts) {
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
      wide: !!(opts && opts.wide),
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
  // A goal's description is LIGHT MARKDOWN (the AI coach writes it this way — see the
  // add_goal guidance in mastery-engine's assistantProfileOps):
  //   **bold** / *italic* inline; a short label line ("Mission:", "Why it matters:", or a
  //   "**Label**" / "## Label" on its own line) renders as a small-caps section head; lines
  //   starting with "-", "•" or "* " render as an objectives checklist; blank lines split
  //   paragraphs. Anything else stays prose. Escape FIRST, then apply the inline spans.
  function inlineMd(s) {
    return esc(s)
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, "$1<em>$2</em>");
  }
  // Standalone labels the coach uses even without a trailing colon.
  const KNOWN_LABELS = /^(mission|vision|standards?|values?|principles?|why( it matters)?|the why|identity|objectives)$/i;

  // LEGACY TEXT still reads flat: goals written before the markdown convention carry no "**",
  // so a standard like "Emotional mastery. Meet stress with steadiness…" showed as one grey run.
  // Auto-emphasise the lead phrase when a line opens with a short label-ish sentence followed by
  // more text. Deliberately conservative — lines opening with a sentence-starter word ("This",
  // "Because", "To"…) are ordinary prose, not labels, and must stay untouched.
  const PROSE_OPENERS = /^(a|an|the|this|that|these|those|it|its|i|my|we|our|you|your|he|she|they|to|for|because|but|and|so|if|when|there|here|no|not|every|each|by|in|on|at|as|with|without|being|becoming)$/i;
  function autoEmphasis(line) {
    if (line.includes("*")) return line;                    // author already marked it up
    const m = line.match(/^([^.!?:]{3,40}[.:])\s+(\S.*)$/);
    if (!m) return line;                                    // no lead phrase, or nothing after it
    const lead = m[1].replace(/[.:]$/, "").trim();
    const words = lead.split(/\s+/);
    if (words.length > 5 || PROSE_OPENERS.test(words[0])) return line;
    return `**${m[1]}** ${m[2]}`;
  }
  function objectivesHtml(desc) {
    if (!desc) return "";
    const out = [];
    let para = [], items = [];
    // One line = one paragraph. These descriptions are written one-thought-per-line, so
    // <br>-joining them ran four separate standards together into a single grey block.
    const flushPara = () => {
      para.forEach((l) => out.push(`<div class="goal-desc">${inlineMd(autoEmphasis(l))}</div>`));
      para = [];
    };
    const flushItems = () => {
      if (!items.length) return;
      // Only head the list "Objectives" when it isn't already sitting under a section label.
      const headed = out.length && out[out.length - 1].startsWith(`<div class="goal-sec">`);
      out.push((headed ? "" : `<div class="goal-sec">Objectives</div>`)
        + `<ul class="goal-objectives">${items.map((o) => `<li>${inlineMd(o)}</li>`).join("")}</ul>`);
      items = [];
    };
    String(desc).split(/\r?\n/).forEach((raw) => {
      const l = raw.trim();
      if (!l) { flushPara(); flushItems(); return; }        // blank line = block boundary
      const head = l.match(/^#{1,3}\s+(.*)$/) || l.match(/^\*\*([^*]{1,60})\*\*:?$/);
      if (head) { flushPara(); flushItems(); out.push(`<div class="goal-sec">${inlineMd(head[1].replace(/:$/, ""))}</div>`); return; }
      const plain = l.replace(/:$/, "");
      if (l.length <= 40 && (l.endsWith(":") || KNOWN_LABELS.test(plain))) {
        flushPara(); flushItems();
        out.push(`<div class="goal-sec">${inlineMd(plain)}</div>`);
        return;
      }
      const bullet = l.match(/^[-•*]\s+(.*)$/);
      if (bullet) { flushPara(); items.push(bullet[1]); return; }
      flushItems();
      para.push(l);
    });
    flushPara(); flushItems();
    return out.join("");
  }

  // A goal card is qualitative now: title, status, target, objectives. Progress numbers live
  // on the dimension itself (the Mastery Engine score) — goals no longer carry a manual %.
  function goalItem(g) {
    const key = `goal:${g.id}`;
    return `<details class="goal-item" data-ui="${key}" ${openSubs.has(key) ? "open" : ""}>
      <summary>
        <span class="gi-title">${esc(g.title)}</span>
        <span class="pill ${g.status === "done" ? "green" : g.status === "paused" ? "amber" : ""}">${esc(g.status)}</span>
        ${S.ICON.chev}
      </summary>
      <div class="gi-body">
        <div class="gi-meta">${g.target_date ? `Target ${esc(g.target_date)}` : "No target date"}</div>
        ${objectivesHtml(g.description)}
        ${readOnly ? "" : `<div class="row" style="gap:10px;margin-top:8px"><a href="#" class="linky" data-edit-goal="${g.id}">edit</a><a href="#" class="linky danger" data-del-goal="${g.id}">delete</a></div>`}
      </div>
    </details>`;
  }

  function goalsBlock(dimKey) {
    const gs = goalsFor(dimKey);
    return `<div class="section-label" style="margin-bottom:6px">Goals ${readOnly ? "" : `<a href="#" class="linky" data-add-goal="${dimKey}">+ add</a>`}</div>
      ${gs.length ? gs.map(goalItem).join("")
        : `<div class="empty">No ${esc(dimName(dimKey).toLowerCase())} goals yet.</div>`}`;
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

    // Target PRs — the numbers being chased. Their mean progress IS the Physical ring.
    const targets = p.targets || [];
    const kindPill = (k) => `<span class="pill ${k === "run" ? "amber" : k === "skill" ? "green" : ""}">${esc(k)}</span>`;
    const fmt = (v) => (v == null ? "—" : String(Math.round(v * 100) / 100));
    const prByName = new Map(prs.map((r) => [String(r.exercise_name || "").toLowerCase(), r]));
    const tRow = (t) => {
      const pct = Math.max(0, Math.min(100, t.progress_pct || 0));
      const pr = prByName.get(String(t.name || "").toLowerCase());
      return `<div style="padding:8px 0;border-top:1px solid var(--line)">
        <div class="row between" style="gap:10px">
          <div style="min-width:0">${kindPill(t.kind)} <strong>${esc(t.name)}</strong>
            <span class="muted">${fmt(t.current_value)} / ${fmt(t.target_value)}${t.unit ? " " + esc(t.unit) : ""}${t.direction === "lower" ? " · lower wins" : ""}</span>
            ${pr && pr.display ? `<span class="muted" style="font-size:11px"> · PR on file: ${esc(pr.display)}</span>` : ""}
          </div>
          <div class="row" style="gap:8px;flex:none;align-items:center">
            ${t.status !== "active" ? `<span class="pill ${t.status === "achieved" ? "green" : "amber"}">${esc(t.status)}</span>` : ""}
            <strong>${pct}%</strong>
            ${readOnly ? "" : `<a href="#" class="linky" data-edit-ptarget="${t.id}">edit</a><a href="#" class="linky danger" data-del-ptarget="${t.id}">delete</a>`}
          </div>
        </div>
        <div class="pr-track" style="margin-top:6px"><i style="width:${pct}%"></i></div>
        ${t.notes ? `<div class="sub">${esc(t.notes)}</div>` : ""}
      </div>`;
    };
    const targetsInner = `<div class="sub" style="margin-bottom:8px">The numbers you're chasing — lifts, runs, skills (calisthenics, boxing). Their average is the Physical ring. Update the current value as you progress, or just tell your coach.</div>
      ${readOnly ? "" : `<div style="margin-bottom:6px"><a href="#" id="add-ptarget" class="linky">+ add target</a></div>`}
      ${targets.length ? targets.map(tRow).join("") : '<div class="empty">No targets yet — add your first lift, run or skill.</div>'}`;
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
    return sub("physical", "targets", "Target PRs", targetsInner, `<span class="ds-hint">${targets.length}</span>`)
      + sub("physical", "stats", "Body stats", stats, `<span class="ds-hint">${bf} · ${wt}</span>`)
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
    const skillsInner = `<div class="sub" style="margin-bottom:8px">What you can already do, including skills you proved on real projects, not just in the engine. Your coach uses these.</div>
      ${readOnly ? "" : `<div style="margin-bottom:8px"><a href="#" id="add-skill" class="linky">+ add skill</a></div>`}
      ${skills.length ? order.map((src) => `
        <div style="margin-bottom:10px">
          <div class="section-label" style="margin-bottom:6px">${esc(srcLabel(src))}</div>
          <div class="row wrap" style="gap:6px">${groups[src].map((s) => `
            <span class="chip" style="cursor:${readOnly ? "default" : "pointer"}" ${readOnly ? "" : `data-edit-skill="${s.id}"`} title="${esc(s.level)}${s.note ? " · " + esc(s.note) : ""}">
              ${esc(s.name)} <span class="muted" style="font-size:11px">${esc(s.level)}</span>
              ${readOnly ? "" : `<a href="#" class="linky danger" data-del-skill="${s.id}" style="margin-left:4px">✕</a>`}</span>`).join("")}</div>
        </div>`).join("") : '<div class="empty">No skills listed yet.</div>'}`;
    let out = sub("professional", "profile", "Career profile", resumeBlock,
        prof.headline ? `<span class="ds-hint">${esc(prof.headline)}</span>` : "")
      + sub("professional", "achievements", "Achievements", `${readOnly ? "" : `<div style="margin-bottom:6px"><a href="#" id="add-ach" class="linky">+ add</a></div>`}${achList}`,
          `<span class="ds-hint">${ach.length}</span>`)
      + sub("professional", "skills", "Skills", skillsInner, `<span class="ds-hint">${skills.length}</span>`);
    if (!readOnly) {  // enrollment progress is the viewer's, not the target's
      const career = ((courses && courses.programs) || []).filter((p) => (p.category || "career") !== "growth");
      out += sub("professional", "learning", "Learning · engine programs",
        `<div class="sub">${career.length ? `You're enrolled in ${career.length} program${career.length === 1 ? "" : "s"} — this ring is their engine score.` : "Your career programs and today's assignment live in the Professional tab."} <a class="linky" href="/academy">Open Professional</a></div>`,
        career.length ? `<span class="ds-hint">${career.length}</span>` : "");
    }
    return out;
  }

  function philosophicalSubs() {
    // Books, essays and the philosophy canon all live here — the reading dimension.
    // Mastery of them happens in the Philosophical tab's engine (book decks + recall).
    const canon = (data.reading || []).filter((x) => x.kind !== "philosophy");
    const now = canon.filter((x) => x.progress.status === "reading");
    const done = canon.filter((x) => x.progress.status === "done");
    const readingInner = `<div class="sub" style="margin-bottom:8px">${done.length}/${canon.length} of the canon complete${now.length ? ` · reading ${now.length}` : ""}. <a class="linky" href="/reading">Open the canon</a> · <a class="linky" href="/philosophical">Open the engine</a></div>
      ${now.length ? `<div class="section-label">Reading now</div><ul class="tickitems">${now.map((x) => `<li>${S.ICON.book}${esc(x.title)}${x.author ? ` <span class="muted">· ${esc(x.author)}</span>` : ""}</li>`).join("")}</ul>`
        : '<div class="empty">Nothing in progress. Open the canon to start.</div>'}`;
    const phil = (data.reading || []).filter((x) => x.kind === "philosophy");
    const philDone = phil.filter((x) => x.progress.status === "done");
    const philInner = phil.length ? `<ul class="tickitems">${phil.map((x) => `
        <li style="display:block;padding:5px 0"><div class="row between">
          <span>${S.ICON.book}${esc(x.title)}${x.author ? ` <span class="muted">· ${esc(x.author)}</span>` : ""}</span>
          <span class="pill ${x.progress.status === "done" ? "green" : x.progress.status === "reading" ? "amber" : ""}">${esc(x.progress.status.replace("_", " "))}</span>
        </div></li>`).join("")}</ul>
        <div class="sub" style="margin-top:6px"><a class="linky" href="/reading">Open the canon</a></div>`
      : '<div class="empty">No philosophies in the canon yet.</div>';
    return sub("philosophical", "reading", "Reading — books & essays", readingInner,
        `<span class="ds-hint">${done.length}/${canon.length}</span>`)
      + sub("philosophical", "philosophy", "Philosophy", philInner,
          phil.length ? `<span class="ds-hint">${philDone.length}/${phil.length}</span>` : "");
  }

  function spiritualSubs() {
    // The old shared "Growth journal" sub lived here and listed EVERY growth item regardless of
    // area. Entries are per-dimension now, so each tab's own Notes sub renders them and a journal
    // here would just duplicate Spiritual's (2026-08-01).
    return readOnly ? "" : sub("spiritual", "engine", "Scripture & study",
      `<div class="sub">Apologetics, church history and doctrine — mastered book by book in the Spiritual tab's engine. <a class="linky" href="/spiritual">Open Spiritual</a></div>`, "");
  }

  // --- Notes: the worker's own titled entries, one per dimension ---------------------------
  // ONE IDEA PER ENTRY. That's the design, not tidiness: every entry's TITLE goes to the AI coach
  // on every turn as a complete, uncapped index, while the bodies are fetched only for the entries
  // a conversation actually turns out to need (services/development.growth_details). An entry
  // holding five unrelated ideas gets indexed by whichever one reached the title, and the other
  // four are invisible to the coach.
  //
  // This replaced the per-dimension "Other info" blob, which had no titles and therefore no index,
  // so it could only ever be handed over truncated — and the coach then denied the existence of
  // content sitting on this very page (2026-08-01). Whatever is still in that blob renders below as
  // "Unfiled", with a one-click path into a real entry.
  const KINDS = [
    { v: "note", t: "Note" },
    { v: "reflection", t: "Reflection" },
    { v: "obstacle", t: "Obstacle" },
  ];
  const kindLabel = (v) => (KINDS.find((k) => k.v === v) || {}).t || v;
  const kindTone = (v) => (v === "obstacle" ? "amber" : v === "reflection" ? "" : "green");
  // Legacy rows predate `dimension` — they read as spiritual, where the whole journal used to live.
  const noteDimOf = (g) => (DIM_KEYS.includes(g.dimension) ? g.dimension : "spiritual");
  const notesFor = (key) => (data.growth || [])
    .filter((g) => noteDimOf(g) === key)
    // Live entries first, then newest — what you're still working through outranks what you closed.
    .sort((a, b) => ((a.status === "open" ? 0 : 1) - (b.status === "open" ? 0 : 1))
      || String(b.created_at || "").localeCompare(String(a.created_at || "")));

  function noteRow(g) {
    const uiKey = `note:${g.id}`;
    const size = (g.detail || "").trim().length;
    return `<details class="note-item" data-ui="${uiKey}" ${openSubs.has(uiKey) ? "open" : ""}>
      <summary>
        <span class="note-head">
          <span class="pill ${kindTone(g.kind)}">${esc(kindLabel(g.kind))}</span>
          <strong class="note-title">${esc(g.title)}</strong>
          ${g.status !== "open" ? `<span class="pill muted-pill">${esc(g.status)}</span>` : ""}
        </span>
        <span class="ds-right">
          <span class="ds-hint">${size ? `${size.toLocaleString()} chars` : "empty"}</span>${S.ICON.chev}
        </span>
      </summary>
      <div class="ds-body">
        ${g.detail ? `<div class="prewrap">${esc(g.detail)}</div>` : '<div class="empty">No detail yet — open edit to write it.</div>'}
        ${readOnly ? "" : `<div class="row" style="gap:14px;margin-top:10px">
          <a href="#" class="linky" data-edit-note="${g.id}">edit</a>
          <a href="#" class="linky danger" data-del-growth="${g.id}">delete</a>
        </div>`}
      </div>
    </details>`;
  }

  function notesSub(key) {
    const items = notesFor(key);
    const unfiled = (areaOf(key).other_info || "").trim();
    const inner = `<div class="sub" style="margin-bottom:10px">Anything worth keeping for this area — one idea per entry, each with its own title. Your coach always sees every title, and reads an entry's detail when the conversation calls for it.</div>
      ${readOnly ? "" : `<div style="margin-bottom:8px"><a href="#" class="linky" data-add-note="${key}">+ add entry</a></div>`}
      ${items.length ? `<div class="note-list">${items.map(noteRow).join("")}</div>`
        : '<div class="empty">No entries yet.</div>'}
      ${unfiled ? `
        <div class="unfiled">
          <div class="row between" style="align-items:baseline;gap:10px">
            <span class="section-label">Unfiled</span>
            ${readOnly ? "" : `<span class="row" style="gap:12px">
              <a href="#" class="linky" data-file-info="${key}">file as entry</a>
              <a href="#" class="linky" data-edit-info="${key}">edit</a>
            </span>`}
          </div>
          <div class="sub" style="margin:4px 0 8px">Older free-form notes for this area. They have no title, so your coach can't tell what's in here without reading all of it — filing them as entries fixes that.</div>
          <div class="prewrap">${esc(unfiled)}</div>
        </div>` : ""}`;
    const badge = items.length || unfiled
      ? `<span class="ds-hint">${items.length}${unfiled ? " + unfiled" : ""}</span>` : "";
    return sub(key, "notes", "Notes", inner, badge);
  }

  const SUBS = { spiritual: spiritualSubs, professional: professionalSubs, philosophical: philosophicalSubs, physical: physicalSubs };

  // --- mentor library: full transcripts imported from outside mentors (e.g. Atrium creators
  // like Nic Saraev or Carson Reed) — a bottom-up knowledge base so the coach can draw on
  // someone else's playbook. Sits at the bottom of the page, below the four dimensions;
  // transcript_text is fetched lazily per row (the /me payload only carries the light fields).
  /** One transcript inside a mentor card. Compact by design — the body only appears on demand
   *  (the /me payload carries light fields; the text is fetched per row and cached). */
  function transcriptRow(t) {
    return `<div class="mx-row" data-hay="${esc((t.title || "").toLowerCase())}">
      <div class="row between" style="gap:10px;align-items:flex-start">
        <div style="min-width:0">
          <div class="mx-title">${esc(t.title)}</div>
          ${t.source_url ? `<a href="${esc(t.source_url)}" target="_blank" rel="noopener" class="linky sub">source</a>` : ""}
        </div>
        <div class="row" style="gap:8px;flex:none">
          <a href="#" class="linky" data-view-transcript="${t.id}">view</a>
          ${readOnly ? "" : `<a href="#" class="linky danger" data-del-transcript="${t.id}">delete</a>`}
        </div>
      </div>
      <div class="prewrap mx-body" hidden></div>
    </div>`;
  }

  /** Transcripts grouped by mentor, biggest library first — the unit the UI is built around. */
  function mentorGroups() {
    const by = new Map();
    for (const t of data.transcripts || []) {
      const name = t.mentor_name || "Unknown";
      if (!by.has(name)) by.set(name, []);
      by.get(name).push(t);
    }
    return [...by.entries()]
      .map(([name, items]) => ({ name, items }))
      .sort((a, b) => b.items.length - a.items.length || a.name.localeCompare(b.name));
  }

  /** One mentor, collapsed to a tile: name, count, and the newest few titles. */
  function mentorCard(g) {
    const preview = g.items.slice(0, 4);
    const hay = (g.name + " " + g.items.map((t) => t.title || "").join(" ")).toLowerCase();
    return `<div class="mx-card card pad" data-hay="${esc(hay)}">
      <div class="row between" style="gap:8px;align-items:center">
        <div class="row" style="gap:8px;align-items:center;min-width:0">
          ${S.ICON.doc}<strong class="mx-title">${esc(g.name)}</strong>
        </div>
        <span class="pill" style="flex:none">${g.items.length}</span>
      </div>
      <div class="mx-preview sub">${preview.map((t) => `<div class="mx-title">${esc(t.title)}</div>`).join("")}${
        g.items.length > preview.length ? `<div style="margin-top:4px">+ ${g.items.length - preview.length} more</div>` : ""}</div>
      <div class="mx-full" hidden>
        ${g.items.length > 6 ? `<input type="search" class="mx-q" placeholder="Search these transcripts…" autocomplete="off">` : ""}
        <div class="mx-rows">${g.items.map(transcriptRow).join("")}</div>
        <div class="empty mx-nohit" hidden>Nothing matches that search.</div>
      </div>
      <div style="margin-top:8px">
        <a href="#" class="linky mx-toggle">Show all ${g.items.length}</a>
      </div>
    </div>`;
  }

  // Grouped by MENTOR rather than listed flat, mirroring Atrium's Watcher tab. A flat list was
  // unusable the moment a bulk import landed: one creator alone can be 100+ transcripts, so the
  // page became an endless column of near-identical full-width rows. Now each mentor is one tile
  // that expands in place. All of it (expand, search, viewing a body) is DOM-only — no re-render,
  // so scroll position, open cards and typed searches survive every interaction.
  function libraryBlock() {
    const groups = mentorGroups();
    const total = (data.transcripts || []).length;
    return `<div class="card" style="margin-top:16px">
      <div class="card-head">
        <h3>${S.ICON.book}Mentor library</h3>
        ${readOnly ? "" : `<div class="row" style="gap:8px">
          <button class="btn sm primary" id="add-transcript-atrium">${S.ICON.plus}Import from Atrium</button>
          <button class="btn sm ghost" id="add-transcript">${S.ICON.plus}Paste transcript</button>
        </div>`}
      </div>
      <div class="card-body">
        <div class="sub" style="margin-bottom:12px">Full video/lesson transcripts from outside mentors (e.g. Atrium Watcher creators like Nick Saraev or Carson Reed) — a pseudo-mentor knowledge base your coach can draw on.${total ? ` <strong>${total}</strong> transcript${total === 1 ? "" : "s"} from <strong>${groups.length}</strong> mentor${groups.length === 1 ? "" : "s"}.` : ""}</div>
        ${total ? `<input id="mx-search" type="search" placeholder="Search mentors and titles…" autocomplete="off" style="margin-bottom:10px">
          <div id="mx-none" class="empty" hidden>Nothing matches that search.</div>
          <div class="mx-grid">${groups.map(mentorCard).join("")}</div>`
          : '<div class="empty">No transcripts imported yet.</div>'}
      </div>
    </div>`;
  }

  // --- page render ----------------------------------------------------------------
  // The compass and the ledger render into separate hosts when the Overview asks for it, so the
  // task board can sit between them. With no ringsHost they stack in `view` exactly as before.
  // No "Ask your coach" button: the Coach FAB is on every page already (app.js), so a second
  // entry point was just another thing to look at.
  function render() {
    const who = readOnly && data.user ? esc(data.user.name.split(" ")[0]) + "’s growth" : "Your growth";
    const eyebrow = readOnly && data.user ? "Development · " + esc(data.user.name) : "Development · Overview";
    const asOf = data.physical.latest ? esc(data.physical.latest.date) : new Date().toISOString().slice(0, 10);

    const rings = `<div class="dim-rings">${DIMS.map(ringCell).join("")}</div>`;
    const mast = !showMast ? "" : `<div class="dev-mast">
        <div>
          <div class="dev-eyebrow">${eyebrow}</div>
          <h1>${who}</h1>
          <div class="lede">Four dimensions of everything you're becoming: spirit, craft, philosophy, and body — each ring is its tab's Mastery Engine score.</div>
        </div>
        <div class="dev-mast-right"><div class="dev-mast-meta">AS OF ${asOf}</div></div>
      </div>`;

    const ledger = `<div class="dim-pace">
        <div class="dim-pace-head">Pace — where you are vs where the calendar says <span class="pace-key"><b class="pr-tick demo"></b> = expected today · click a row for its details</span></div>
        ${DIMS.map(paceBlock).join("")}
      </div>

      ${libraryBlock()}`;

    if (ringsHost) {
      ringsHost.innerHTML = `<div class="dev">${rings}</div>`;
      view.innerHTML = `<div class="dev">${mast}${ledger}</div>`;
    } else {
      view.innerHTML = `<div class="dev">${mast}${rings}${ledger}</div>`;
    }

    wire();
  }

  // --- wiring ---------------------------------------------------------------
  function toggleDim(key, forceOpen) {
    const box = S.qs(`#dim-${key}`);
    if (!box) return;
    const willOpen = forceOpen != null ? forceOpen : !openDims.has(key);
    if (willOpen) openDims.add(key); else openDims.delete(key);
    box.classList.toggle("open", willOpen);
    const head = box.querySelector(".pace-row");
    if (head) head.setAttribute("aria-expanded", String(willOpen));
  }

  function wire() {
    // Expand/collapse works in both modes; edits only when it's your own profile.
    // Rows are divs (see paceRow), so keyboard toggling is wired by hand.
    S.qsa("[data-toggle-dim]").forEach((b) => {
      b.onclick = () => toggleDim(b.dataset.toggleDim);
      b.onkeydown = (e) => {
        if (e.target !== b) return;  // Enter/Space on a nested link (the ✎) is its own action
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggleDim(b.dataset.toggleDim); }
      };
    });
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

    // --- mentor library: expand / search / read, all without a re-render ------------------------
    // Deliberately DOM-only. Re-rendering the page to open a card would drop scroll position, close
    // every other card and wipe whatever the user had typed into a search box.
    S.qsa(".mx-card").forEach((card) => {
      const toggle = S.qs(".mx-toggle", card);
      const full = S.qs(".mx-full", card);
      const preview = S.qs(".mx-preview", card);
      const count = S.qsa(".mx-row", card).length;
      if (toggle) toggle.onclick = (e) => {
        e.preventDefault();
        const open = full.hidden;
        full.hidden = !open;
        if (preview) preview.hidden = open;
        // An expanded card spans the whole grid — a long list in one narrow column is unreadable.
        card.classList.toggle("expanded", open);
        toggle.textContent = open ? "Show less" : `Show all ${count}`;
        if (open) { const q = S.qs(".mx-q", card); if (q) q.focus(); }
      };
      // Per-mentor title filter (only rendered once a mentor has enough transcripts to need it).
      const q = S.qs(".mx-q", card);
      if (q) q.oninput = () => {
        const term = q.value.trim().toLowerCase();
        let shown = 0;
        S.qsa(".mx-row", card).forEach((row) => {
          const hit = !term || row.dataset.hay.indexOf(term) !== -1;
          row.hidden = !hit;
          if (hit) shown += 1;
        });
        const none = S.qs(".mx-nohit", card); if (none) none.hidden = shown > 0;
      };
    });

    // Top-level search across mentor names AND every title they hold.
    const mxs = S.qs("#mx-search");
    if (mxs) mxs.oninput = () => {
      const term = mxs.value.trim().toLowerCase();
      let shown = 0;
      S.qsa(".mx-card").forEach((card) => {
        const hit = !term || card.dataset.hay.indexOf(term) !== -1;
        card.hidden = !hit;
        if (hit) shown += 1;
      });
      const none = S.qs("#mx-none"); if (none) none.hidden = shown > 0;
    };

    // Viewing a transcript is read-only in both modes; fetch its text once and cache it.
    S.qsa("[data-view-transcript]").forEach((a) => a.onclick = async (e) => {
      e.preventDefault();
      const id = a.dataset.viewTranscript;
      const body = S.qs(".mx-body", a.closest(".mx-row"));
      if (!body.hidden) { body.hidden = true; a.textContent = "view"; return; }
      body.hidden = false;
      a.textContent = "hide";
      if (transcriptText[id] == null) {
        body.textContent = "Loading…";
        try { const t = await api(`/api/development/transcripts/${id}`); transcriptText[id] = t.transcript_text; }
        catch (err) { transcriptText[id] = "(couldn't load this transcript)"; }
      }
      body.textContent = transcriptText[id];
    });

    if (readOnly) return;
    const at = S.qs("#add-transcript"); if (at) at.onclick = (e) => { e.preventDefault(); transcriptForm(); };
    const ata = S.qs("#add-transcript-atrium"); if (ata) ata.onclick = (e) => { e.preventDefault(); atriumImportPicker(); };
    S.qsa("[data-del-transcript]").forEach((a) => a.onclick = (e) => { e.preventDefault(); delete transcriptText[a.dataset.delTranscript]; del(`/api/development/transcripts/${a.dataset.delTranscript}`); });

    const am = S.qs("#add-metric"); if (am) am.onclick = () => formModal("Log body stats", [
      { name: "body_fat_pct", label: "Body fat %", type: "number", step: "0.1" },
      { name: "weight_kg", label: "Weight (kg)", type: "number", step: "0.1" },
      { name: "date", label: "Date (blank = today)", type: "date" },
    ], (o) => api("/api/development/body-metrics", { method: "POST", body: { body_fat_pct: num(o.body_fat_pct), weight_kg: num(o.weight_kg), date: o.date || null } }));

    const addPr = S.qs("#add-pr"); if (addPr) addPr.onclick = (e) => { e.preventDefault(); prForm(); };
    S.qsa("[data-edit-pr]").forEach((a) => a.onclick = (e) => { e.preventDefault(); prForm(data.physical.prs.find((r) => r.id == a.dataset.editPr)); });
    S.qsa("[data-del-pr]").forEach((a) => a.onclick = (e) => { e.preventDefault(); del(`/api/development/prs/${a.dataset.delPr}`); });

    const apt = S.qs("#add-ptarget"); if (apt) apt.onclick = (e) => { e.preventDefault(); ptargetForm(); };
    S.qsa("[data-edit-ptarget]").forEach((a) => a.onclick = (e) => { e.preventDefault(); ptargetForm((data.physical.targets || []).find((t) => t.id == a.dataset.editPtarget)); });
    S.qsa("[data-del-ptarget]").forEach((a) => a.onclick = (e) => { e.preventDefault(); del(`/api/development/physical-goals/${a.dataset.delPtarget}`); });

    const sr = S.qs("#save-resume"); if (sr) sr.onclick = async () => {
      try { await api("/api/development/resume", { method: "PATCH", body: { headline: S.qs("#hl").value, resume_text: S.qs("#rz").value } }); S.toast("Saved", "ok"); }
      catch (e) { S.toast(e.detail || "Couldn't save", "err"); }
    };

    S.qsa("[data-add-goal]").forEach((a) => a.onclick = (e) => { e.preventDefault(); goalForm(null, a.dataset.addGoal); });
    S.qsa("[data-edit-goal]").forEach((a) => a.onclick = (e) => { e.preventDefault(); goalForm(data.career.goals.find((g) => g.id == a.dataset.editGoal)); });
    S.qsa("[data-del-goal]").forEach((a) => a.onclick = (e) => { e.preventDefault(); del(`/api/development/goals/${a.dataset.delGoal}`); });

    // Per-dimension area settings: the pace deadline (✎ on the pace band) and "Other info".
    S.qsa("[data-edit-deadline]").forEach((a) => a.onclick = (e) => {
      e.preventDefault();
      e.stopPropagation();  // the ✎ lives inside the clickable pace row — don't toggle it
      const key = a.dataset.editDeadline;
      formModal(`${dimName(key)} deadline`, [
        { name: "deadline", label: `Deadline (blank = default ${DEADLINE_DEFAULT})`, type: "date", value: areaOf(key).deadline || "" },
      ], (o) => api(`/api/development/areas/${key}`, { method: "PATCH", body: { deadline: o.deadline || null } }));
    });
    // The legacy free-form blob. Still editable so nothing is trapped, but the way OUT of it is
    // "file as entry" — a titled entry is what the coach can actually index.
    S.qsa("[data-edit-info]").forEach((a) => a.onclick = (e) => {
      e.preventDefault();
      const key = a.dataset.editInfo;
      formModal(`${dimName(key)} — unfiled notes`, [
        { name: "other_info", label: "Free-form text with no title. Prefer adding an entry instead — your coach can only see what's in here by reading all of it.", type: "textarea", rows: 10, value: areaOf(key).other_info || "" },
      ], (o) => api(`/api/development/areas/${key}`, { method: "PATCH", body: { other_info: o.other_info || null } }));
    });
    S.qsa("[data-file-info]").forEach((a) => a.onclick = (e) => { e.preventDefault(); fileUnfiledForm(a.dataset.fileInfo); });

    S.qsa("[data-add-note]").forEach((a) => a.onclick = (e) => { e.preventDefault(); noteForm(null, a.dataset.addNote); });
    S.qsa("[data-edit-note]").forEach((a) => a.onclick = (e) => {
      e.preventDefault();
      noteForm((data.growth || []).find((g) => g.id == a.dataset.editNote));
    });

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

  // --- notes -------------------------------------------------------------------
  // The TITLE is the load-bearing field: it's what the AI coach sees for every entry on every turn,
  // and how it decides which bodies to pull. "Misc thoughts" indexes nothing.
  function noteForm(g, dimKey) {
    const key = g ? noteDimOf(g) : (dimKey || "professional");
    formModal(g ? "Edit entry" : `Add ${dimName(key).toLowerCase()} entry`, [
      { name: "title", label: "Title — name the ONE thing this entry is about", value: g && g.title, ph: "e.g. Pareto problem set" },
      { name: "dimension", label: "Area", type: "select", value: key, options: DIMS.map((d) => ({ v: d.key, t: d.name })) },
      { name: "kind", label: "Kind", type: "select", value: (g && g.kind) || "note", options: KINDS },
      { name: "detail", label: "Details — as long as you like, nothing is truncated", type: "textarea", rows: 12, value: g && g.detail, ph: "The full text." },
      { name: "status", label: "Status", type: "select", value: (g && g.status) || "open", options: [{ v: "open", t: "Open" }, { v: "resolved", t: "Resolved" }, { v: "archived", t: "Archived" }] },
    ], (o) => {
      if (!String(o.title || "").trim()) throw { detail: "Give it a title — that's the part your coach always sees." };
      const body = { dimension: o.dimension, kind: o.kind, title: o.title, detail: o.detail || null, status: o.status };
      return g ? api(`/api/development/growth/${g.id}`, { method: "PATCH", body })
        : api("/api/development/growth", { method: "POST", body });
    }, { wide: true });
  }

  /** Move a dimension's leftover free-form blob into a real titled entry, then clear the blob.
   *  Deliberately moves the WHOLE text in one go rather than trying to split it: deciding where one
   *  idea ends is a judgement call, and an auto-split would bury content under a title that doesn't
   *  describe it — the same invisibility this whole change exists to end. Split it afterwards by
   *  trimming this entry and adding siblings. */
  function fileUnfiledForm(key) {
    const txt = (areaOf(key).other_info || "").trim();
    if (!txt) return;
    formModal(`File ${dimName(key).toLowerCase()} notes as an entry`, [
      { name: "title", label: "Title — what is this text about?", ph: "e.g. Learning roadmap" },
      { name: "kind", label: "Kind", type: "select", value: "note", options: KINDS },
      { name: "detail", label: "Details (your unfiled text, moved across whole — edit freely)", type: "textarea", rows: 14, value: txt },
    ], async (o) => {
      if (!String(o.title || "").trim()) throw { detail: "Give it a title — that's the part your coach always sees." };
      await api("/api/development/growth", { method: "POST", body: { dimension: key, kind: o.kind, title: o.title, detail: o.detail || null, status: "open" } });
      // Clear the blob ONLY after the entry is safely stored. If this second call fails the text is
      // duplicated rather than lost, which is the right way round for something irreplaceable.
      await api(`/api/development/areas/${key}`, { method: "PATCH", body: { other_info: null } });
    }, { wide: true });
  }

  // No progress-% field: a dimension's % is its Mastery Engine score, never typed by hand.
  function goalForm(g, dimKey) {
    formModal(g ? "Edit goal" : `Add ${dimName(dimKey || "professional").toLowerCase()} goal`, [
      { name: "title", label: "Goal", value: g && g.title, ph: "e.g. Become Agora backend developer" },
      { name: "dimension", label: "Dimension", type: "select", value: g ? dimOf(g) : (dimKey || "professional"), options: DIMS.map((d) => ({ v: d.key, t: d.name })) },
      { name: "description", label: "Description — labels like \"Mission:\", **bold**, *italic*, - for objectives", type: "textarea", value: g && g.description, ph: "Mission:\nTo become…\n\nStandards:\n**Emotional mastery.** Meet stress with steadiness…\n\n- Ship the capstone" },
      { name: "status", label: "Status", type: "select", value: (g && g.status) || "active", options: [{ v: "active", t: "Active" }, { v: "paused", t: "Paused" }, { v: "done", t: "Done" }] },
      { name: "target_date", label: "Target date", type: "date", value: g && g.target_date },
    ], (o) => {
      const body = { title: o.title, dimension: o.dimension, description: o.description, status: o.status, target_date: o.target_date || null };
      return g ? api(`/api/development/goals/${g.id}`, { method: "PATCH", body }) : api("/api/development/goals", { method: "POST", body });
    });
  }

  // A target PR: the number chased (target) vs where you are (current) — %, and the ring,
  // follow. `direction` lower = time-based goals (a 55-min 10k beats a 59-min one).
  function ptargetForm(t) {
    formModal(t ? "Edit target" : "Add a physical target", [
      { name: "name", label: "Lift / run / skill", value: t && t.name, ph: "e.g. Bench Press, 10k run, Muscle-up" },
      { name: "kind", label: "Kind", type: "select", value: (t && t.kind) || "lift", options: [{ v: "lift", t: "Lift" }, { v: "run", t: "Run" }, { v: "skill", t: "Skill (calisthenics, boxing…)" }] },
      { name: "target_value", label: "Target number", type: "number", step: "0.1", value: t && t.target_value },
      { name: "current_value", label: "Current number", type: "number", step: "0.1", value: t ? t.current_value : 0 },
      { name: "unit", label: "Unit", value: t && t.unit, ph: "kg, lb, min, sec, reps, km…" },
      { name: "direction", label: "What counts as better", type: "select", value: (t && t.direction) || "higher", options: [{ v: "higher", t: "Higher is better (lifts, reps, holds)" }, { v: "lower", t: "Lower is better (times)" }] },
      { name: "status", label: "Status", type: "select", value: (t && t.status) || "active", options: [{ v: "active", t: "Active" }, { v: "achieved", t: "Achieved" }, { v: "paused", t: "Paused" }] },
      { name: "notes", label: "Notes", type: "textarea", rows: 2, value: t && t.notes, ph: "e.g. paused strict form until shoulder heals (optional)" },
    ], (o) => {
      const body = { name: o.name, kind: o.kind, target_value: num(o.target_value), current_value: num(o.current_value) || 0, unit: o.unit || "", direction: o.direction, status: o.status, notes: o.notes || null };
      return t ? api(`/api/development/physical-goals/${t.id}`, { method: "PATCH", body }) : api("/api/development/physical-goals", { method: "POST", body });
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

  // Import-only — a mentor transcript is pasted verbatim, not hand-edited afterward. For anything
  // not (yet) archived in Atrium's Watcher — a one-off video, a non-YouTube source.
  function transcriptForm() {
    formModal("Paste a transcript", [
      { name: "mentor_name", label: "Mentor", ph: "e.g. Nic Saraev, Carson Reed" },
      { name: "title", label: "Video / lesson title", ph: "e.g. Cold email systemization, pt. 2" },
      { name: "source_url", label: "Source URL (optional)", ph: "Link back to the source" },
      { name: "transcript_text", label: "Full transcript", type: "textarea", rows: 14, ph: "Paste the full transcript text…" },
    ], (o) => api("/api/development/transcripts", {
      method: "POST",
      body: { mentor_name: o.mentor_name, title: o.title, source_url: o.source_url || null, transcript_text: o.transcript_text },
    }), { wide: true });
  }

  // --- import from Atrium's Watcher archive: creator -> video -> copy the transcript in ----------
  function atriumImportPicker() {
    // Deliberately NOT `wide`: this is a list to skim, not a form to fill. A compact box plus an
    // internally-scrolling list reads better than a 920px dialog taller than the screen.
    const m = S.modal({ title: "Import from Atrium", body: `<div id="ax-body">${S.skeleton({ rows: 4 })}</div>` });
    const body = () => S.qs("#ax-body", m.root);

    // Both lists filter client-side: the whole set is already in hand, so typing stays instant and
    // never re-hits Atrium. `hay` is prebuilt per row — matching is a substring test, not a rebuild.
    function wireSearch(inputId, rows, onEmpty) {
      const input = S.qs(inputId, body());
      if (!input) return;
      const apply = () => {
        const q = input.value.trim().toLowerCase();
        let shown = 0;
        rows.forEach((r) => {
          const hit = !q || r.hay.indexOf(q) !== -1;
          r.el.style.display = hit ? "" : "none";
          if (hit) shown += 1;
        });
        const none = S.qs(inputId + "-none", body());
        if (none) none.style.display = shown ? "none" : "";
        if (onEmpty) onEmpty(shown);
      };
      input.oninput = apply;
      input.focus();
    }

    function searchBox(id, ph) {
      return `<input id="${id.slice(1)}" type="search" placeholder="${esc(ph)}" autocomplete="off" style="margin-bottom:10px">
        <div id="${id.slice(1)}-none" class="empty" style="display:none">Nothing matches that search.</div>`;
    }

    function showChannels(channels) {
      body().innerHTML = `<div class="sub" style="margin-bottom:10px">Pick a creator to import <strong>every</strong> fetched transcript at once, or open it to choose a single video.</div>
        ${searchBox("#ax-q", "Search creators — name, industry, workspace…")}
        <div class="pick-list">${channels.map((c) => `<div class="card pad ax-row" data-channel="${esc(c.id)}" data-mentor="${esc(c.title)}" style="margin-bottom:8px">
          <div class="row between" style="gap:10px;flex-wrap:wrap">
            <div style="min-width:0;flex:1 1 200px">
              <div class="row" style="gap:8px;align-items:center"><strong>${esc(c.title)}</strong><span class="pill">${esc(c.kind || "creator")}</span></div>
              <div class="sub" style="margin-top:4px">${c.transcript_count || 0}/${c.video_count || 0} transcripts fetched${c.industry ? " · " + esc(c.industry) : ""}${c.client_name ? " · watched in " + esc(c.client_name) : ""}</div>
            </div>
            <div class="row" style="gap:8px;flex:none">
              <button class="btn sm primary ax-all" ${c.transcript_count ? "" : "disabled"}>Import all ${c.transcript_count || 0}</button>
              <button class="btn sm ghost ax-one">Pick one</button>
            </div>
          </div>
        </div>`).join("")}</div>`;
      const rows = S.qsa(".ax-row", body()).map((el) => ({
        el,
        hay: (el.dataset.mentor + " " + el.textContent).toLowerCase(),
      }));
      wireSearch("#ax-q", rows);
      S.qsa(".ax-row", body()).forEach((el) => {
        const go = () => showVideos(el.dataset.channel, el.dataset.mentor);
        S.qs(".ax-one", el).onclick = () => go();
        const all = S.qs(".ax-all", el);
        if (!all.disabled) all.onclick = () => importAll(el.dataset.channel, el.dataset.mentor);
      });
    }

    async function showVideos(channelId, mentorName) {
      body().innerHTML = S.skeleton({ rows: 4 });
      let videos = [];
      // The id is namespaced "<client_key>:<channel_id>" (Atrium needs the workspace to find the
      // archive), so it MUST be encoded — a raw ":" in a path segment is not ours to gamble on.
      try { videos = (await api(`/api/development/atrium/channels/${encodeURIComponent(channelId)}/videos`)).videos || []; }
      catch (e) { videos = []; }
      const withText = videos.filter((v) => v.has_transcript);
      body().innerHTML = `<div class="row between" style="gap:12px;margin-bottom:8px">
          <a href="#" class="linky" id="ax-back">&larr; Creators</a>
          ${withText.length ? `<button class="btn sm primary" id="ax-all-here">Import all ${withText.length}</button>` : ""}
        </div>
        <div class="sub" style="margin:8px 0">${esc(mentorName)} — pick a video that already has a transcript fetched.</div>
        ${withText.length ? searchBox("#ax-vq", "Search this creator’s videos…") + `<div class="pick-list">` + withText.map((v) => `<button class="card pad ax-pick" data-video="${esc(v.id)}" style="display:block;width:100%;text-align:left;margin-bottom:8px;cursor:pointer;appearance:none;font:inherit;color:inherit">
            <strong>${esc(v.title)}</strong>
            <div class="sub" style="margin-top:4px">${v.words} words</div>
          </button>`).join("") + `</div>`
          : '<div class="empty">No fetched transcripts on this creator yet — run "Fetch missing" on it in Atrium first.</div>'}`;
      S.qs("#ax-back", body()).onclick = (e) => { e.preventDefault(); loadChannels(); };
      const allBtn = S.qs("#ax-all-here", body());
      if (allBtn) allBtn.onclick = () => importAll(channelId, mentorName);
      wireSearch("#ax-vq", S.qsa(".ax-pick", body()).map((el) => ({
        el, hay: el.textContent.toLowerCase(),
      })));
      S.qsa(".ax-pick", body()).forEach((b) => b.onclick = () => doImport(channelId, b.dataset.video, mentorName));
    }

    // Bulk import. One request moves the whole creator (Atrium hands its archive over in a few
    // budgeted pages), so this can legitimately run for a while — say so instead of looking hung.
    async function importAll(channelId, mentorName) {
      body().innerHTML = `<div class="empty">${S.skeleton({ rows: 2 })}
        <div style="margin-top:10px">Importing every transcript for <strong>${esc(mentorName)}</strong> — this can take a minute for a big creator. Leave this open.</div>
      </div>`;
      try {
        const r = await api("/api/development/atrium/import-all", {
          method: "POST",
          body: { channel_id: channelId, mentor_name: mentorName },
        });
        m.close();
        S.toast(r.imported
          ? `Imported ${r.imported} transcript${r.imported === 1 ? "" : "s"} from ${mentorName}${r.skipped ? ` · ${r.skipped} already in your library` : ""}`
          : `Already up to date — all ${r.available} of ${mentorName}'s transcripts are in your library`, "ok");
        load();
      } catch (e) {
        S.toast(e.detail || "Couldn't import that creator", "err");
        loadChannels();
      }
    }

    async function doImport(channelId, videoId, mentorName) {
      body().innerHTML = S.skeleton({ rows: 3 });
      try {
        await api("/api/development/atrium/import", {
          method: "POST",
          body: { channel_id: channelId, video_id: videoId, mentor_name: mentorName },
        });
        m.close();
        S.toast("Imported", "ok");
        load();
      } catch (e) {
        S.toast(e.detail || "Couldn't import that transcript", "err");
        showVideos(channelId, mentorName);
      }
    }

    async function loadChannels() {
      body().innerHTML = S.skeleton({ rows: 4 });
      let data;
      try { data = await api("/api/development/atrium/channels"); }
      catch (e) { data = { ready: false, channels: [] }; }
      if (!data.ready) {
        body().innerHTML = `<div class="empty">Atrium isn't connected for this yet — use "Paste transcript" instead.</div>`;
        return;
      }
      if (!(data.channels || []).length) {
        body().innerHTML = `<div class="empty">No creators watched in Atrium yet — add one there first.</div>`;
        return;
      }
      showChannels(data.channels);
    }

    loadChannels();
  }

  async function del(path) {
    try { await api(path, { method: "DELETE" }); load(); }
    catch (e) { S.toast(e.detail || "Couldn't delete", "err"); }
  }

  async function load() {
    // Both hosts get a placeholder: the rings keep their instrument-panel shape (one card, four
    // cells) so the Overview doesn't jump when the data lands.
    if (ringsHost) ringsHost.innerHTML = `<div class="skeleton skel-card" style="height:170px"></div>`;
    view.innerHTML = S.skeleton ? S.skeleton({ rows: 6 }) : "Loading…";
    try {
      data = await api(readOnly ? `/api/development/user/${targetId}` : "/api/development/me");
    } catch (e) {
      if (ringsHost) ringsHost.innerHTML = "";
      view.innerHTML = `<div class="empty card pad">${esc(e.detail || "Couldn't load this profile.")}</div>`;
      return;
    }
    if (!readOnly) { try { courses = await api("/api/academy/courses"); } catch (e) { courses = null; } }
    render();
  }

  // Let the global Coach refresh this hub after it applies an approved edit.
  if (!readOnly) window.SentinelReloadDevelopment = load;
  await load();
}

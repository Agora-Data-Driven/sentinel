/* Academy — a native Sentinel dashboard of the worker's enrolled courses, plus the
   Assignment of the Day. Courses/progress come from the mastery engine via a
   server-to-server call (/api/academy/courses); clicking a course opens the engine
   itself (embedded, carrying the same portal ag_sso cookie — no second sign-in).

   Assignment of the Day is a Phase-E placeholder (a scenario you explain aloud, AI-graded). */
window.pageInit = async (S) => {
  const view = S.view();
  const esc = S.esc;
  S.qs("#top-sub").textContent = "Your learning and today's assignment";

  let data;
  try {
    data = await S.api("/api/academy/courses");
  } catch (e) {
    view.innerHTML = `<div class="card" style="padding:28px;text-align:center">
      <h2 style="margin:0 0 8px">Academy is unavailable</h2>
      <p style="margin:0;color:var(--muted)">Couldn't reach the learning engine. Try again shortly.</p></div>`;
    return;
  }

  // Career/technical programs only — personal-growth/philosophy programs live under the
  // Reading & Philosophy tab (same engine, separate subject). Untagged programs default to career.
  const programs = (data.programs || []).filter((p) => (p.category || "career") !== "growth");
  const engineUrl = data.engineUrl || "";
  const isAdmin = !!data.admin;                 // the engine's own verdict (by email)
  const adminUrl = data.adminUrl || "";         // academy-admin.html?embed=1, when configured

  const ringColor = (p) => (p >= 80 ? "#2E7D32" : p >= 50 ? "#C9A227" : "#B3261E");
  const ring = (pct) => {
    const p = Math.max(0, Math.min(100, Math.round(pct || 0)));
    return `<div class="ac-ring" style="background:conic-gradient(${ringColor(p)} ${p * 3.6}deg, var(--line) 0deg)">
      <span>${p}<i>%</i></span></div>`;
  };
  const card = (p) => `
    <button class="ac-course" data-program="${esc(p.id)}" title="Open ${esc(p.name)} in the mastery engine">
      ${ring(p.pct)}
      <div class="ac-cinfo">
        <div class="ac-cname">${esc(p.name)}</div>
        <div class="ac-csub">${p.courseCount || 0} courses &middot; ${p.topicsPracticed || 0}/${p.topicsTotal || 0} topics practised</div>
      </div>
      <span class="ac-open">Open &rarr;</span>
    </button>`;

  view.innerHTML = `
    <style>
      .ac-wrap { max-width: 900px; }
      .ac-assign { padding: 20px 22px; margin-bottom: 22px; display:flex; align-items:center; gap:18px; flex-wrap:wrap;
        background: linear-gradient(120deg, rgba(79,168,74,.10), rgba(24,86,201,.08)); border:1px solid var(--line); }
      .ac-badge { display:inline-block; font-size:11px; font-weight:800; letter-spacing:.6px; text-transform:uppercase;
        color:#fff; background:#4FA84A; padding:3px 10px; border-radius:999px; }
      .ac-assign h3 { margin:8px 0 4px; font-size:18px; }
      .ac-h { font-size:15px; text-transform:uppercase; letter-spacing:.5px; color:var(--muted); margin:0 0 12px; }
      .ac-courses { display:grid; gap:12px; }
      .ac-course { display:flex; align-items:center; gap:16px; width:100%; text-align:left; cursor:pointer;
        background:var(--card,#fff); border:1px solid var(--line); border-radius:16px; padding:14px 16px;
        transition: box-shadow .15s, transform .05s; font:inherit; color:inherit; }
      .ac-course:hover { box-shadow: var(--shadow); }
      .ac-course:active { transform: translateY(1px); }
      .ac-ring { width:52px; height:52px; border-radius:50%; flex:none; display:grid; place-items:center; }
      .ac-ring::after { content:""; position:absolute; width:38px; height:38px; border-radius:50%; background:var(--card,#fff); }
      .ac-ring span { position:relative; z-index:1; font-weight:800; font-size:13px; }
      .ac-ring i { font-style:normal; font-size:9px; opacity:.7; }
      .ac-cinfo { flex:1; min-width:0; }
      .ac-cname { font-weight:700; font-size:15px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
      .ac-csub { color:var(--muted); font-size:13px; margin-top:2px; }
      .ac-open { color:#4FA84A; font-weight:700; font-size:13px; flex:none; }
      #ac-engine { display:none; }
      #ac-engine.on { display:block; }
      .ac-back { margin-bottom:12px; }
    </style>

    <div class="ac-wrap" id="ac-dash">
      ${isAdmin && adminUrl
        ? `<div class="card ac-assign" style="background:linear-gradient(120deg, rgba(22,163,74,.12), rgba(12,16,34,.06))">
             <div style="flex:1;min-width:220px">
               <span class="ac-badge" style="background:#16a34a">Academy Admin</span>
               <h3>Manage the Academy</h3>
               <p style="margin:0;color:var(--muted)">Build curriculum, attach transcripts, generate the question bank, and enrol people.</p>
             </div>
             <button class="btn" id="ac-admin-open" style="background:#16a34a;color:#fff;font-weight:700">Open admin &rarr;</button>
           </div>`
        : ""}

      <div class="card ac-assign">
        <div style="flex:1;min-width:220px">
          <span class="ac-badge">Assignment of the Day</span>
          <h3>Situational assessment</h3>
          <p style="margin:0;color:var(--muted)">A real scenario you explain out loud, graded by AI. Launching with Phase E.</p>
        </div>
        <button class="btn" disabled title="Coming soon">Coming soon</button>
      </div>
      <!-- The old "Programs assigned" course list was removed: every roadmap is open to
           everyone now, and an assigned roadmap shows up automatically (labelled "required")
           in the learner's Mastery Engine — so there's no per-program course dashboard here. -->
    </div>

    <div id="ac-engine">
      <button class="btn ac-back" id="ac-back">&larr; Back</button>
      <iframe id="ac-frame" title="AGORA Mastery Engine" allow="microphone" loading="eager"
        style="width:100%;height:calc(100vh - 190px);min-height:520px;border:1px solid var(--line);
               border-radius:18px;box-shadow:var(--shadow);background:#fff;display:block"></iframe>
    </div>`;

  const dash = S.qs("#ac-dash");
  const eng = S.qs("#ac-engine");
  const frame = S.qs("#ac-frame");

  const openFrame = (url) => {
    frame.src = url;
    dash.style.display = "none";
    eng.classList.add("on");
  };
  const openEngine = (program) => {
    if (!engineUrl) { S.toast ? S.toast("Learning engine not configured") : alert("Learning engine not configured"); return; }
    // home=quiz opens the engine straight into the course/quiz builder — progress now lives in the
    // Development Overview, so we skip the engine's own "My Progress" landing.
    openFrame(engineUrl + "&home=quiz" + (program ? "&program=" + encodeURIComponent(program) : ""));
  };
  const openAdmin = () => { if (adminUrl) openFrame(adminUrl); };

  const adminBtn = S.qs("#ac-admin-open");
  if (adminBtn) adminBtn.onclick = openAdmin;
  S.qs("#ac-back").onclick = () => { eng.classList.remove("on"); dash.style.display = ""; frame.src = "about:blank"; };

  // Admins land straight in the Academy admin view; everyone else opens straight into their courses
  // (skipping the progress dashboard — progress lives in the Development Overview now). "← Back to
  // courses" still returns to the native list (programs + admin launcher) whenever they want it.
  if (isAdmin && adminUrl) openAdmin();
  else if (engineUrl) openEngine();
};

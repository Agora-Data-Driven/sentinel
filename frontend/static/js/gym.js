window.pageInit = async (S) => {
  const view = S.view();
  const isMgr = S.can("team_lead");
  const isSA = S.user.role === "super_admin";
  const SET_TYPES = ["Normal", "Warm-up", "Drop", "To failure"];
  const GYM_STATUSES = ["Completed", "Incomplete", "Missing"];
  const GYM_DAYS = ["Push", "Pull", "Legs", "Custom"];          // splits you can log
  const PLAN_DAYS = ["Push", "Pull", "Legs", "Custom", "Rest"]; // + Rest for the plan
  const DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  const MONTHS = ["January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December"];
  const DAY_DESC = {
    Push: "Chest · Shoulders · Triceps", Pull: "Back · Biceps · Rear delts",
    Legs: "Quads · Hams · Glutes · Calves", Custom: "Cardio · Core · Full body", Rest: "Recovery day",
  };

  // day: the session currently open in the editor; dayOpts.back: tab to return to (null = inline).
  let state = { tab: "Calendar", cal: null, calY: 0, calM: 0, plan: null, day: null, dayOpts: null,
    exercises: [], library: [], timer: null, saveT: null };

  const tabs = isMgr ? ["Calendar", "Today", "History", "Team compliance"] : ["Calendar", "Today", "History"];
  view.innerHTML = `<div class="dev">
    <div class="dev-mast"><div>
      <div class="dev-eyebrow">Development · Gym</div>
      <h1>Train</h1>
      <div class="lede">Plan your week, log a workout on any day, and edit sets & reps whenever, nothing gets locked. Your body fat and PRs live here too.</div>
    </div><div class="dev-mast-right"><div class="dev-mast-meta">${isMgr ? "TEAM VIEW" : "PUSH · PULL · LEGS"}</div></div></div>
    <div id="gym-body"></div>
    <div class="tabs" id="tabs">${tabs.map((t, i) => `<button class="${i ? "" : "active"}" data-tab="${t}">${t}</button>`).join("")}</div>
    <div id="tabc"></div>
    </div>`;
  S.qsa("#tabs button").forEach((b) => b.onclick = () => switchTab(b.dataset.tab));

  function switchTab(name) {
    state.tab = name;
    S.qsa("#tabs button").forEach((x) => x.classList.toggle("active", x.dataset.tab === name));
    stopTimer();
    if (name === "Calendar") return renderCalendar();
    if (name === "Today") return renderToday();
    if (name === "History") return renderHistory();
    if (name === "Team compliance") return renderCompliance();
  }

  // Let the Coach (or any page action) refresh the plan + current tab after an edit.
  window.SentinelReloadGym = async () => {
    try { state.plan = await S.api("/api/gym/plan"); } catch (e) { /* keep old */ }
    switchTab(state.tab);
  };

  // --- small helpers ----------------------------------------------------------
  const dayNum = (iso) => Number(iso.slice(8, 10));
  const monthLabel = () => `${MONTHS[state.calM - 1]} ${state.calY}`;
  const planPill = (d) => `<span class="pill day ${d}">${d}</span>`;

  // ============================ CALENDAR ============================
  async function renderCalendar() {
    S.qs("#tabc").innerHTML = '<div class="skeleton" style="height:420px"></div>';
    const mm = `${state.calY}-${String(state.calM).padStart(2, "0")}`;
    const data = await S.api(`/api/gym/calendar?month=${mm}`);
    state.cal = data;
    const lead = DOW.indexOf(data.days[0].weekday);       // blanks before day 1
    const blanks = Array.from({ length: lead }, () => '<div class="cal-cell blank"></div>').join("");
    const cells = data.days.map((day) => {
      const rest = day.planned === "Rest";
      const log = day.log;
      const done = log && (log.status === "Completed" || log.status === "Incomplete")
        ? `<span class="cal-done ${log.status}" title="${log.day_type} · ${log.status}">${S.ICON.check}</span>` : "";
      const meta = log ? `<span class="cal-logmeta">${log.exercise_count} ex · ${log.duration_minutes}m</span>` : "";
      const cardio = day.cardio ? `<span class="cal-cardio" title="${S.esc(day.cardio)}">${S.ICON.run}${S.esc(day.cardio)}</span>` : "";
      return `<button class="cal-cell ${day.is_today ? "today" : ""} ${rest ? "rest" : ""}" data-date="${day.date}">
        <span class="d">${dayNum(day.date)}</span>
        <span class="pill day ${day.planned} cal-plan">${day.planned}</span>${cardio}${meta}${done}</button>`;
    }).join("");
    S.qs("#tabc").innerHTML = `
      <div class="gym-cal-head">
        <div class="gym-cal-nav">
          <button class="btn ghost mv" id="cal-prev" aria-label="Previous month">‹</button>
          <b>${monthLabel()}</b>
          <button class="btn ghost mv" id="cal-next" aria-label="Next month">›</button>
          <button class="btn sm ghost" id="cal-today-btn">Today</button>
        </div>
        <button class="btn sm ghost" id="cal-plan-btn">${S.ICON.calendar}Edit weekly plan</button>
      </div>
      <div class="cal-grid">${DOW.map((d) => `<div class="cal-dow">${d}</div>`).join("")}${blanks}${cells}</div>
      <div class="cal-legend">
        <span><span class="cal-done Completed" style="position:static">${S.ICON.check}</span> Completed</span>
        <span><span class="cal-done Incomplete" style="position:static">${S.ICON.check}</span> Logged, under 1h</span>
        <span>Coloured pill = planned split · tap any day to log or re-plan it</span>
      </div>`;
    S.qs("#cal-prev").onclick = () => { shiftMonth(-1); renderCalendar(); };
    S.qs("#cal-next").onclick = () => { shiftMonth(1); renderCalendar(); };
    S.qs("#cal-today-btn").onclick = () => { setMonthFromIso(state.plan.today.date); renderCalendar(); };
    S.qs("#cal-plan-btn").onclick = planEditor;
    S.qsa(".cal-cell[data-date]").forEach((b) => b.onclick = () => dayMenu(b.dataset.date));
  }

  function shiftMonth(delta) {
    let m = state.calM + delta, y = state.calY;
    if (m < 1) { m = 12; y--; } if (m > 12) { m = 1; y++; }
    state.calM = m; state.calY = y;
  }
  function setMonthFromIso(iso) { state.calY = Number(iso.slice(0, 4)); state.calM = Number(iso.slice(5, 7)); }

  // Tap a calendar day: re-plan it (split + cardio) and/or log a workout. Both live here so the grid stays clean.
  function dayMenu(dateStr) {
    const cell = state.cal.days.find((d) => d.date === dateStr) || {};
    const weekly = state.plan.week[cell.weekday];
    const weeklyCardio = (state.plan.cardio || {})[cell.weekday] || "";
    const isOverride = cell.planned !== weekly || (cell.cardio || "") !== weeklyCardio;
    const log = cell.log;
    let chosen = cell.planned;
    const m = S.modal({
      title: `${cell.weekday}, ${S.fmtDateFull(dateStr + "T00:00:00+08:00")}`,
      body: `<div class="section-label">Planned split</div>
        <div class="row" id="dm-plan" style="gap:8px;margin:8px 0 4px;flex-wrap:wrap">
          ${PLAN_DAYS.map((d) => `<button class="btn sm ${d === chosen ? "primary" : "ghost"}" data-plan="${d}">${d}</button>`).join("")}
        </div>
        <label class="field" style="margin:10px 0 6px"><span>Cardio / run (optional)</span>
          <input id="dm-cardio" placeholder="e.g. 5k run, intervals" value="${S.esc(cell.cardio || "")}"></label>
        <div class="sub" style="font-size:12px">${isOverride
          ? `Custom for this day. <a href="#" class="linky" id="dm-revert">Revert to your weekly ${cell.weekday} (${weekly}${weeklyCardio ? " + " + S.esc(weeklyCardio) : ""})</a>`
          : `Matches your weekly ${cell.weekday} plan.`}</div>
        <hr style="border:0;border-top:1px solid var(--line);margin:16px 0">
        ${log
          ? `<div class="row between"><div>${planPill(log.day_type)} ${S.statusPill(log.status)}
               <div class="sub" style="font-size:12px;margin-top:4px">${log.duration_minutes}m · ${log.exercise_count} exercises</div></div></div>`
          : '<div class="sub" style="font-size:13px">No workout logged this day yet.</div>'}`,
      footer: `<button class="btn ghost" id="dm-x">Close</button>
        <button class="btn ghost" id="dm-saveplan">Save plan</button>
        <button class="btn success" id="dm-open">${log ? "Edit workout" : "Log a workout"}</button>`,
    });
    const paint = () => S.qsa("#dm-plan [data-plan]").forEach((x) => x.className = "btn sm " + (x.dataset.plan === chosen ? "primary" : "ghost"));
    S.qsa("#dm-plan [data-plan]").forEach((b) => b.onclick = () => { chosen = b.dataset.plan; paint(); });
    S.qs("#dm-x").onclick = m.close;
    S.qs("#dm-open").onclick = () => { m.close(); openDay(dateStr, "Calendar"); };
    S.qs("#dm-saveplan").onclick = async () => {
      try {
        await S.api("/api/gym/plan/day", { method: "POST", body: { date: dateStr, day_type: chosen, cardio: S.qs("#dm-cardio").value.trim() || null } });
        m.close(); S.toast("Plan updated for this day", "ok"); renderCalendar();
      } catch (e) { S.toast(e.detail || "Couldn't update plan", "err"); }
    };
    const rev = S.qs("#dm-revert");
    if (rev) rev.onclick = async (e) => {
      e.preventDefault();
      try { await S.api(`/api/gym/plan/day/${dateStr}`, { method: "DELETE" }); m.close(); S.toast("Reverted to weekly plan", "ok"); renderCalendar(); }
      catch (err) { S.toast(err.detail || "Couldn't revert", "err"); }
    };
  }

  // Weekly recurring split editor — day-type + an optional cardio note per weekday.
  function planEditor() {
    const wk = state.plan.week, cardio = state.plan.cardio || {};
    const m = S.modal({
      title: "Your weekly split",
      body: `<div class="sub" style="font-size:13px;margin-bottom:10px">This repeats every week. Add a run under any day (e.g. “5k run”, “intervals”), and your Coach reads it too. Override a single date from the calendar.</div>
        ${DOW.map((d) => `<div class="wk-row"><span class="wd">${d}</span>
          <div class="row" style="gap:8px">
            <select data-wd="${d}" style="max-width:128px">${PLAN_DAYS.map((p) => `<option ${p === wk[d] ? "selected" : ""}>${p}</option>`).join("")}</select>
            <input data-cardio="${d}" placeholder="cardio (optional)" value="${S.esc(cardio[d] || "")}" style="flex:1;min-width:0">
          </div></div>`).join("")}`,
      footer: `<button class="btn ghost" id="wk-x">Cancel</button><button class="btn primary" id="wk-save">Save plan</button>`,
    });
    S.qs("#wk-x").onclick = m.close;
    S.qs("#wk-save").onclick = async () => {
      const week = {}, cardioOut = {};
      S.qsa("[data-wd]").forEach((sel) => week[sel.dataset.wd] = sel.value);
      S.qsa("[data-cardio]").forEach((inp) => { const v = inp.value.trim(); if (v) cardioOut[inp.dataset.cardio] = v; });
      try {
        const res = await S.api("/api/gym/plan/week", { method: "POST", body: { week, cardio: cardioOut } });
        state.plan.week = res.week; state.plan.cardio = res.cardio || {};
        m.close(); S.toast("Weekly plan saved", "ok"); renderCalendar();
      } catch (e) { S.toast(e.detail || "Couldn't save", "err"); }
    };
  }

  // ============================ TODAY ============================
  async function renderToday() {
    const today = await S.api("/api/gym/today");
    if (today) return loadDayEditor(today, null);
    const planned = state.plan.today.day_type;
    S.qs("#tabc").innerHTML = `<div class="card pad" style="text-align:center">
      <div class="section-label">Today's plan</div>
      <h2 style="margin:8px 0">${planPill(planned)}</h2>
      <div class="sub">${DAY_DESC[planned] || ""}</div>
      <div class="row" style="justify-content:center;gap:8px;margin-top:18px;flex-wrap:wrap">
        <button class="btn success" id="td-start">${S.ICON.plus}Start ${planned === "Rest" ? "a" : planned} workout</button>
      </div>
      <div class="sub" style="font-size:12px;margin-top:14px">Or log a different split:
        ${GYM_DAYS.filter((d) => d !== planned).map((d) => `<a href="#" class="linky" data-alt="${d}" style="margin:0 5px">${d}</a>`).join("")}</div>
    </div>`;
    const start = (dt) => openDay(state.plan.today.date, null, dt);
    S.qs("#td-start").onclick = () => start(planned === "Rest" ? "Custom" : planned);
    S.qsa("[data-alt]").forEach((a) => a.onclick = (e) => { e.preventDefault(); start(a.dataset.alt); });
  }

  // ============================ DAY EDITOR (any date, no lock) ============================
  async function openDay(dateStr, backTab, dayType) {
    stopTimer();
    S.qs("#tabc").innerHTML = '<div class="skeleton" style="height:260px"></div>';
    const body = { date: dateStr }; if (dayType) body.day_type = dayType;
    const session = await S.api("/api/gym/day", { method: "POST", body });
    loadDayEditor(session, backTab);
  }

  async function loadDayEditor(session, backTab) {
    state.day = session;
    state.dayOpts = { backTab: backTab || null };
    state.exercises = (session.exercises || []).map((e) => ({
      name: e.exercise_name, muscle: e.muscle_group,
      sets: e.sets_detail && e.sets_detail.length ? e.sets_detail
        : [{ set: 1, kg: e.weight_value, reps: e.reps, type: "Normal", done: true }],
      notes: e.notes || "",
    }));
    state.library = await S.api("/api/gym/library?day_type=" + encodeURIComponent(session.day_type));
    renderDayEditor();
  }

  function isTodaySession() { return state.day && state.day.date === state.plan.today.date; }
  function isDone() { return !!(state.day && state.day.end_time); }

  function renderDayEditor() {
    stopTimer();  // re-entrant (split change / done toggle) — never leave a stale interval running
    const log = state.day;
    const back = state.dayOpts.backTab
      ? `<button class="btn sm ghost" id="day-back">‹ ${state.dayOpts.backTab}</button>` : "";
    const timer = isTodaySession() && !isDone()
      ? `<span class="sub" style="font-size:12px">Elapsed <strong id="gym-elapsed" style="font-variant-numeric:tabular-nums">0:00</strong>
          <a href="#" class="linky" id="use-elapsed">use</a></span>` : "";
    S.qs("#tabc").innerHTML = `
      <div class="card pad" style="margin-bottom:16px">
        <div class="row between" style="align-items:flex-start;flex-wrap:wrap;gap:12px">
          <div class="row" style="gap:12px;align-items:center">${back}
            <div><div class="section-label">${S.fmtDateFull(log.date + "T00:00:00+08:00")}</div>
              <div class="row" id="day-status" style="gap:8px;align-items:center;margin-top:4px">${planPill(log.day_type)} ${S.statusPill(log.status)}</div></div>
          </div>
          <div class="row" style="gap:8px;align-items:center;flex-wrap:wrap">
            <span class="save-tag" id="save-tag"></span>
            <button class="btn sm ghost" id="day-add">${S.ICON.plus}Add exercise</button>
            <button class="btn sm ${isDone() ? "success" : "ghost"}" id="day-done">${S.ICON.check}${isDone() ? "Done" : "Mark done"}</button>
            <button class="btn sm ghost" id="day-del" title="Delete this workout" style="color:var(--danger)">${S.ICON.x}Delete</button>
          </div>
        </div>
        <div class="row" style="gap:20px;margin-top:14px;flex-wrap:wrap;align-items:center">
          <label class="field" style="margin:0"><span>Split</span>
            <select id="day-split">${GYM_DAYS.map((d) => `<option ${d === log.day_type ? "selected" : ""}>${d}</option>`).join("")}</select></label>
          <label class="field" style="margin:0"><span>Duration (min)</span>
            <input id="day-dur" type="number" min="0" style="width:110px" value="${log.duration_minutes || ""}"></label>
          ${timer}
        </div>
      </div>
      <div id="ex-list"></div>
      <div id="day-summary" style="margin-top:16px"></div>`;

    if (back) S.qs("#day-back").onclick = () => switchTab(state.dayOpts.backTab);
    S.qs("#day-add").onclick = openLibrary;
    S.qs("#day-done").onclick = toggleDone;
    S.qs("#day-del").onclick = deleteDay;
    S.qs("#day-split").onchange = (e) => changeSplit(e.target.value);
    S.qs("#day-dur").onchange = (e) => saveSession({ duration_minutes: Math.max(0, Number(e.target.value) || 0) });
    renderExercises();
    updateSummary();
    if (isTodaySession() && !isDone()) {
      startTimer(log.start_time);
      S.qs("#use-elapsed").onclick = (e) => {
        e.preventDefault();
        const mins = elapsedMinutes(log.start_time);
        S.qs("#day-dur").value = mins; saveSession({ duration_minutes: mins });
      };
    }
  }

  function renderExercises() {
    const box = S.qs("#ex-list");
    if (!state.exercises.length) { box.innerHTML = '<div class="empty card pad">No exercises yet. Tap “Add exercise”.</div>'; return; }
    box.innerHTML = state.exercises.map((ex, i) => {
      const prev = (state.library.find((l) => l.name === ex.name) || {}).previous;
      return `<div class="card" style="margin-bottom:12px">
        <div class="card-head"><h3>${S.esc(ex.name)} ${ex.muscle ? `<span class="chip">${S.esc(ex.muscle)}</span>` : ""}</h3>
          <span class="x-close" data-del-ex="${i}">${S.ICON.x}</span></div>
        <div class="card-body">
          <div class="table-wrap" style="border:none">
            <table><thead><tr><th>Set</th><th>Previous</th><th>KG</th><th>Reps</th><th>Type</th><th>✓</th><th></th></tr></thead>
            <tbody>${ex.sets.map((s, si) => `<tr>
              <td><strong>${si + 1}</strong></td>
              <td class="muted">${prev ? S.esc(prev.display) : "—"}</td>
              <td><input style="width:70px" type="number" step="0.5" value="${s.kg || ""}" data-ex="${i}" data-si="${si}" data-f="kg"></td>
              <td><input style="width:64px" type="number" value="${s.reps || ""}" data-ex="${i}" data-si="${si}" data-f="reps"></td>
              <td><select data-ex="${i}" data-si="${si}" data-f="type">${SET_TYPES.map((t) => `<option ${t === s.type ? "selected" : ""}>${t}</option>`).join("")}</select></td>
              <td><input type="checkbox" style="width:auto" ${s.done ? "checked" : ""} data-ex="${i}" data-si="${si}" data-f="done"></td>
              <td><span class="x-close" data-del-set="${i}:${si}">${S.ICON.x}</span></td></tr>`).join("")}</tbody></table>
          </div>
          <div class="row between" style="margin-top:8px">
            <button class="btn sm ghost" data-add-set="${i}">${S.ICON.plus}Add set</button>
            <input placeholder="Notes for ${S.esc(ex.name)}…" value="${S.esc(ex.notes)}" data-ex="${i}" data-f="notes" style="max-width:320px">
          </div>
        </div></div>`;
    }).join("");

    box.querySelectorAll("[data-f]").forEach((inp) => inp.onchange = () => {
      const i = +inp.dataset.ex, f = inp.dataset.f;
      if (f === "notes") { state.exercises[i].notes = inp.value; scheduleSave(); return; }
      const si = +inp.dataset.si;
      state.exercises[i].sets[si][f] = f === "done" ? inp.checked : f === "type" ? inp.value : Number(inp.value);
      updateSummary(); scheduleSave();
    });
    box.querySelectorAll("[data-add-set]").forEach((b) => b.onclick = () => {
      const i = +b.dataset.addSet, last = state.exercises[i].sets.slice(-1)[0] || {};
      state.exercises[i].sets.push({ set: state.exercises[i].sets.length + 1, kg: last.kg || 0, reps: last.reps || 0, type: "Normal", done: false });
      renderExercises(); updateSummary(); scheduleSave();
    });
    box.querySelectorAll("[data-del-set]").forEach((b) => b.onclick = () => {
      const [i, si] = b.dataset.delSet.split(":").map(Number);
      state.exercises[i].sets.splice(si, 1); if (!state.exercises[i].sets.length) state.exercises.splice(i, 1);
      renderExercises(); updateSummary(); scheduleSave();
    });
    box.querySelectorAll("[data-del-ex]").forEach((b) => b.onclick = () => {
      state.exercises.splice(+b.dataset.delEx, 1); renderExercises(); updateSummary(); scheduleSave();
    });
  }

  // Live client-side session summary (kept in sync as you edit; server figures the authoritative one).
  function updateSummary() {
    const box = S.qs("#day-summary"); if (!box) return;
    let sets = 0, volume = 0; const muscles = {};
    state.exercises.forEach((ex) => {
      ex.sets.forEach((s) => { sets++; volume += (+s.kg || 0) * (+s.reps || 0); });
      if (ex.muscle) muscles[ex.muscle] = (muscles[ex.muscle] || 0) + ex.sets.length;
    });
    const ms = Object.entries(muscles);
    box.innerHTML = `<div class="kpis">
      <div class="kpi"><div class="k-label">Duration</div><div class="k-val">${state.day.duration_minutes || 0}<span style="font-size:16px">m</span></div></div>
      <div class="kpi"><div class="k-label">Total sets</div><div class="k-val">${sets}</div></div>
      <div class="kpi violet"><div class="k-label">Volume</div><div class="k-val">${Math.round(volume)}<span style="font-size:16px">kg</span></div></div>
      <div class="kpi"><div class="k-label">Exercises</div><div class="k-val">${state.exercises.length}</div></div>
    </div>
    ${ms.length ? `<div style="margin-top:14px"><div class="section-label">Muscle activation</div>
      <div class="row wrap" style="margin-top:8px">${ms.map(([m, n]) => `<span class="chip">${S.esc(m)} · ${n}</span>`).join("")}</div></div>` : ""}`;
  }

  function openLibrary() {
    const items = state.library;
    const muscles = [...new Set(items.map((e) => e.muscle_group).filter(Boolean))].sort();
    const m = S.modal({
      title: "Add exercise",
      body: `<div class="row" style="gap:8px;margin-bottom:12px">
          <input id="lib-search" placeholder="Search exercises…" style="flex:1">
          <select id="lib-muscle" style="max-width:170px"><option value="">All muscles</option>${muscles.map((mg) => `<option value="${S.esc(mg)}">${S.esc(mg)}</option>`).join("")}</select>
        </div>
        <div id="lib-list" style="max-height:360px;overflow:auto"></div>`,
    });
    const draw = () => {
      const q = (S.qs("#lib-search").value || "").toLowerCase();
      const mg = S.qs("#lib-muscle").value;
      const list = items.filter((e) => (!q || e.name.toLowerCase().includes(q)) && (!mg || e.muscle_group === mg));
      S.qs("#lib-list").innerHTML = list.length ? list.map((e) => `
        <div class="row between" style="padding:9px 4px;border-bottom:1px solid var(--line)">
          <div><strong>${S.esc(e.name)}</strong> <span class="chip">${S.esc(e.muscle_group || "")}</span>
            <div class="muted" style="font-size:12px">${e.previous ? "Last: " + S.esc(e.previous.display) : "No history"}</div></div>
          <button class="btn sm success" data-add="${S.esc(e.name)}" data-m="${S.esc(e.muscle_group || "")}">Add</button></div>`).join("")
        : '<div class="empty" style="padding:20px">No matching exercises.</div>';
      S.qsa("[data-add]", S.qs("#lib-list")).forEach((b) => b.onclick = () => {
        state.exercises.push({ name: b.dataset.add, muscle: b.dataset.m, sets: [{ set: 1, kg: 0, reps: 0, type: "Warm-up", done: false }], notes: "" });
        m.close(); renderExercises(); updateSummary(); scheduleSave();
      });
    };
    S.qs("#lib-search").oninput = draw;
    S.qs("#lib-muscle").onchange = draw;
    draw();
  }

  // --- autosave (no finish/lock) ---------------------------------------------
  function scheduleSave() {
    clearTimeout(state.saveT);
    setSaveTag("Saving…", false);
    state.saveT = setTimeout(saveExercises, 700);
  }
  async function saveExercises() {
    const payload = state.exercises.map((ex) => ({
      exercise_name: ex.name, muscle_group: ex.muscle, set_type: "Normal",
      sets_detail: ex.sets.map((s, i) => ({ set: i + 1, kg: +s.kg || 0, reps: +s.reps || 0, type: s.type || "Normal", done: !!s.done, pr: false })),
      notes: ex.notes,
    }));
    try {
      const upd = await S.api(`/api/gym/${state.day.id}/exercises`, { method: "POST", body: payload });
      state.day = upd; setSaveTag("Saved", true); refreshStatusPill();
    } catch (e) { setSaveTag("", false); S.toast(e.detail || "Couldn't save", "err"); }
  }
  async function saveSession(patch) {
    setSaveTag("Saving…", false);
    try {
      const res = await S.api(`/api/gym/${state.day.id}/session`, { method: "PATCH", body: patch });
      state.day = res.log; setSaveTag("Saved", true); refreshStatusPill(); updateSummary();
      return res;
    } catch (e) { setSaveTag("", false); S.toast(e.detail || "Couldn't save", "err"); }
  }
  function setSaveTag(text, ok) {
    const el = S.qs("#save-tag"); if (!el) return;
    el.textContent = text ? (ok ? "✓ " + text : text) : "";
    el.classList.toggle("ok", !!ok);
    if (ok) { clearTimeout(setSaveTag._t); setSaveTag._t = setTimeout(() => { const e = S.qs("#save-tag"); if (e) e.textContent = ""; }, 1600); }
  }
  function refreshStatusPill() {
    const el = S.qs("#day-status");
    if (el && state.day) el.innerHTML = `${planPill(state.day.day_type)} ${S.statusPill(state.day.status)}`;
  }

  async function changeSplit(newType) {
    const res = await saveSession({ day_type: newType });
    if (!res) return;
    state.library = await S.api("/api/gym/library?day_type=" + encodeURIComponent(newType));
    renderDayEditor();
  }
  async function deleteDay() {
    if (!confirm("Delete this whole workout? This can't be undone.")) return;
    try {
      await S.api(`/api/gym/${state.day.id}`, { method: "DELETE" });
      stopTimer(); S.toast("Workout deleted", "ok");
      switchTab(state.dayOpts.backTab || "Calendar");
    } catch (e) { S.toast(e.detail || "Couldn't delete", "err"); }
  }
  async function toggleDone() {
    const willBeDone = !isDone();
    // If marking done with no duration set, fill it from the elapsed timer.
    const patch = { done: willBeDone };
    if (willBeDone && !state.day.duration_minutes && isTodaySession()) patch.duration_minutes = elapsedMinutes(state.day.start_time);
    await saveSession(patch);
    stopTimer(); renderDayEditor();
    if (willBeDone) S.toast("Nice work", "ok");
  }

  // ============================ HISTORY ============================
  async function renderHistory() {
    S.qs("#tabc").innerHTML = '<div class="skeleton" style="height:200px"></div>';
    const rows = await S.api("/api/gym/my");
    if (!rows.length) { S.qs("#tabc").innerHTML = '<div class="empty card pad">No workouts logged yet. Head to the Calendar or Today to start one.</div>'; return; }
    // Group by "Month Year".
    const groups = {};
    rows.forEach((g) => { const k = g.date.slice(0, 7); (groups[k] = groups[k] || []).push(g); });
    S.qs("#tabc").innerHTML = Object.keys(groups).sort().reverse().map((k) => {
      const [y, m] = k.split("-");
      return `<div class="section-label" style="margin:6px 0 8px">${MONTHS[+m - 1]} ${y}</div>
        ${groups[k].map((g) => `<div class="card pad" style="margin-bottom:8px">
          <div class="row between" style="align-items:center;flex-wrap:wrap;gap:8px">
            <div class="row hist-open" data-date="${g.date}" style="gap:10px;align-items:center;cursor:pointer;flex:1;min-width:0">${planPill(g.day_type)} ${S.statusPill(g.status)}
              <span class="sub" style="font-size:13px">${S.fmtDateFull(g.date + "T00:00:00+08:00")}</span></div>
            <div class="row" style="gap:14px;align-items:center">
              <span class="sub" style="font-size:12px">${g.duration_minutes}m · ${g.exercise_count} exercises</span>
              <span class="x-close" data-del="${g.id}" title="Delete this workout">${S.ICON.x}</span></div>
          </div></div>`).join("")}`;
    }).join("");
    S.qsa(".hist-open").forEach((b) => b.onclick = () => openDay(b.dataset.date, "History"));
    S.qsa("#tabc [data-del]").forEach((b) => b.onclick = async () => {
      if (!confirm("Delete this workout? This can't be undone.")) return;
      try { await S.api(`/api/gym/${b.dataset.del}`, { method: "DELETE" }); S.toast("Workout deleted", "ok"); renderHistory(); }
      catch (err) { S.toast(err.detail || "Couldn't delete", "err"); }
    });
  }

  // ============================ TEAM COMPLIANCE (managers) ============================
  async function renderCompliance() {
    S.qs("#tabc").innerHTML = '<div class="skeleton" style="height:200px"></div>';
    const rows = await S.api("/api/gym/summary");
    S.qs("#tabc").innerHTML = `<div class="table-wrap"><table>
      <thead><tr><th>Employee</th><th>Sessions (wk)</th><th>Completed</th><th>Incomplete</th><th>This week</th>${isSA ? "<th></th>" : ""}</tr></thead>
      <tbody>${rows.map((r, i) => `<tr>
        <td class="t-name">${S.avatar({ name: r.name }, "sm")}${S.esc(r.name)}</td>
        <td>${r.sessions}</td><td>${r.completed}</td><td>${r.incomplete}</td>
        <td><div class="row">${r.logs.length ? r.logs.map((g) => `<span class="pill day ${g.day_type}" title="${g.day_type} · ${g.status}">${g.day_type[0]}</span>`).join("") : '<span class="muted">—</span>'}</div></td>
        ${isSA ? `<td style="text-align:right">${r.logs.length ? `<button class="btn sm ghost" data-manage="${i}">Manage</button>` : ""}</td>` : ""}</tr>`).join("")}</tbody></table></div>`;
    if (isSA) S.qsa("[data-manage]").forEach((b) => b.onclick = () => manageSessions(rows[+b.dataset.manage]));
  }

  // Super Admin: edit/delete any employee's gym sessions (this week).
  function manageSessions(r) {
    const m = S.modal({
      title: `${S.esc(r.name)}: sessions this week`,
      body: `<div id="ms-list"></div>`,
    });
    const draw = () => {
      S.qs("#ms-list").innerHTML = r.logs.length ? r.logs.map((g, i) => `
        <div class="card pad" style="margin-bottom:10px" data-row="${i}">
          <div class="row between" style="align-items:center">
            <div><span class="pill day ${g.day_type}">${g.day_type}</span> ${S.statusPill(g.status)}
              <div class="sub" style="font-size:12px;margin-top:4px">${S.fmtDateFull(g.date + "T00:00:00+08:00")} · ${g.duration_minutes}m · ${g.exercise_count} exercises</div></div>
            <div class="row" style="gap:6px">
              <select data-f="day_type" style="max-width:110px">${GYM_DAYS.map((d) => `<option ${d === g.day_type ? "selected" : ""}>${d}</option>`).join("")}</select>
              <select data-f="status" style="max-width:130px">${GYM_STATUSES.map((s) => `<option ${s === g.status ? "selected" : ""}>${s}</option>`).join("")}</select>
              <button class="btn sm success" data-save="${g.id}">Save</button>
              <button class="btn sm danger" data-del="${g.id}">Delete</button>
            </div></div></div>`).join("") : '<div class="empty">No sessions this week.</div>';
      S.qsa("[data-save]").forEach((b) => b.onclick = async () => {
        const row = b.closest("[data-row]");
        const body = { day_type: row.querySelector('[data-f="day_type"]').value, status: row.querySelector('[data-f="status"]').value };
        try { const upd = await S.api(`/api/gym/${b.dataset.save}`, { method: "PATCH", body });
          const idx = r.logs.findIndex((x) => x.id == b.dataset.save); if (idx >= 0) r.logs[idx] = { ...r.logs[idx], ...upd };
          S.toast("Session updated", "ok"); draw(); } catch (e) { S.toast(e.detail || "Couldn't save", "err"); }
      });
      S.qsa("[data-del]").forEach((b) => b.onclick = async () => {
        if (!confirm("Delete this session? This can't be undone.")) return;
        try { await S.api(`/api/gym/${b.dataset.del}`, { method: "DELETE" });
          r.logs = r.logs.filter((x) => x.id != b.dataset.del); S.toast("Session deleted", "ok"); draw(); }
        catch (e) { S.toast(e.detail || "Couldn't delete", "err"); }
      });
    };
    draw();
  }

  // --- timer ------------------------------------------------------------------
  function elapsedMinutes(startIso) { return Math.max(0, Math.floor((Date.now() - new Date(startIso).getTime()) / 60000)); }
  function startTimer(startIso) {
    const t0 = new Date(startIso).getTime();
    const tick = () => { const e = S.qs("#gym-elapsed"); if (!e) return; const m = Math.max(0, Math.floor((Date.now() - t0) / 60000)); e.textContent = Math.floor(m / 60) + ":" + String(m % 60).padStart(2, "0"); };
    tick(); state.timer = setInterval(tick, 1000);
  }
  function stopTimer() { if (state.timer) { clearInterval(state.timer); state.timer = null; } }

  // --- Body stats (body fat / weight / PRs) — shared with the Development hub ---------------------
  const _num = (v) => (v === "" || v == null ? null : Number(v));

  async function renderBodyStats() {
    const box = S.qs("#gym-body"); if (!box) return;
    let data;
    try { data = await S.api("/api/development/me"); } catch (e) { box.innerHTML = ""; return; }
    const p = data.physical || {}, latest = p.latest, prs = p.prs || [];
    const bf = latest && latest.body_fat_pct != null ? latest.body_fat_pct + "%" : "—";
    const wt = latest && latest.weight_kg != null ? latest.weight_kg + " kg" : "—";
    box.innerHTML = `<div class="card pad" style="margin-bottom:16px">
      <div class="row between" style="align-items:center;flex-wrap:wrap;gap:10px">
        <div class="row" style="gap:26px">
          <div><div class="section-label">Body fat</div><strong style="font-size:20px">${bf}</strong></div>
          <div><div class="section-label">Weight</div><strong style="font-size:20px">${wt}</strong></div>
          <div><div class="section-label">PRs</div><strong style="font-size:20px">${prs.length}</strong></div>
        </div>
        <div class="row"><button class="btn sm ghost" id="gb-log">${S.ICON.plus}Update body stats</button>
          <button class="btn sm ghost" id="gb-pr">${S.ICON.trophy}Add PR</button></div>
      </div>
      ${prs.length ? `<div class="row wrap" style="margin-top:12px;gap:6px">${prs.map((r) => `
        <span class="chip">${S.esc(r.exercise_name)}: ${S.esc(r.display || "")}
          <a href="#" class="linky danger" data-delpr="${r.id}" style="margin-left:5px">✕</a></span>`).join("")}</div>` : ""}</div>`;
    S.qs("#gb-log").onclick = statForm;
    S.qs("#gb-pr").onclick = () => prForm();
    S.qsa("[data-delpr]").forEach((a) => a.onclick = async (e) => {
      e.preventDefault();
      try { await S.api(`/api/development/prs/${a.dataset.delpr}`, { method: "DELETE" }); renderBodyStats(); }
      catch (err) { S.toast(err.detail || "Couldn't delete", "err"); }
    });
  }

  function statForm() {
    const m = S.modal({
      title: "Update body stats",
      body: `<div class="formgrid">
        <label class="field"><span>Body fat %</span><input id="bs-bf" type="number" step="0.1" placeholder="e.g. 18.5"></label>
        <label class="field"><span>Weight (kg)</span><input id="bs-wt" type="number" step="0.1" placeholder="e.g. 74"></label></div>`,
      footer: `<button class="btn ghost" id="bs-x">Cancel</button><button class="btn primary" id="bs-save">Save</button>`,
    });
    S.qs("#bs-x").onclick = m.close;
    S.qs("#bs-save").onclick = async () => {
      try { await S.api("/api/development/body-metrics", { method: "POST", body: { body_fat_pct: _num(S.qs("#bs-bf").value), weight_kg: _num(S.qs("#bs-wt").value) } });
        m.close(); renderBodyStats(); S.toast("Saved", "ok"); } catch (e) { S.toast(e.detail || "Couldn't save", "err"); }
    };
  }

  function prForm() {
    const m = S.modal({
      title: "Add personal record",
      body: `<div class="formgrid">
        <label class="field"><span>Exercise / activity</span><input id="pr-name" placeholder="e.g. Bench Press, or 10 km run"></label>
        <label class="field"><span>Weight (for lifts)</span><input id="pr-w" type="number" step="0.5"></label>
        <label class="field"><span>Unit</span><select id="pr-u"><option>kg</option><option>lb</option></select></label>
        <label class="field"><span>Reps (for lifts)</span><input id="pr-r" type="number" value="1"></label>
        <label class="field"><span>Result (for runs/times/distances)</span><input id="pr-d" placeholder="e.g. ~59 min, or 5:30 / km"></label></div>`,
      footer: `<button class="btn ghost" id="pr-x">Cancel</button><button class="btn primary" id="pr-save">Save</button>`,
    });
    S.qs("#pr-x").onclick = m.close;
    S.qs("#pr-save").onclick = async () => {
      const name = S.qs("#pr-name").value.trim();
      if (!name) return S.toast("Exercise is required", "err");
      try { await S.api("/api/development/prs", { method: "POST", body: { exercise_name: name, weight_value: _num(S.qs("#pr-w").value) || 0, weight_unit: S.qs("#pr-u").value, reps: _num(S.qs("#pr-r").value) || 1, detail: S.qs("#pr-d").value.trim() || null } });
        m.close(); renderBodyStats(); S.toast("PR added", "ok"); } catch (e) { S.toast(e.detail || "Couldn't save", "err"); }
    };
  }

  // --- boot -------------------------------------------------------------------
  renderBodyStats();
  state.plan = await S.api("/api/gym/plan");
  setMonthFromIso(state.plan.today.date);
  switchTab("Calendar");
};

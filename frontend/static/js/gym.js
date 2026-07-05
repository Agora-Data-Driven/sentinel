window.pageInit = async (S) => {
  const view = S.view();
  const isMgr = S.can("team_lead");
  const SET_TYPES = ["Normal", "Warm-up", "Drop", "To failure"];
  const DAYS = [
    { t: "Push", d: "Chest · Shoulders · Triceps", c: "push" },
    { t: "Pull", d: "Back · Biceps · Rear delts", c: "pull" },
    { t: "Legs", d: "Quads · Hams · Glutes · Calves", c: "legs" },
    { t: "Custom", d: "Cardio · Core · Full body", c: "custom" },
  ];

  let state = { log: null, exercises: [], library: [], timer: null };

  const tabs = isMgr ? ["My workout", "Team compliance"] : ["My workout"];
  view.innerHTML = `<div class="pagehead"><div><h2>Gym Tracker</h2>
      <div class="lead">Log your training, Hevy-style. Aim for 1h+ to stay compliant.</div></div></div>
    <div class="tabs" id="tabs">${tabs.map((t, i) => `<button class="${i ? "" : "active"}" data-tab="${t}">${t}</button>`).join("")}</div>
    <div id="tabc"></div>`;
  S.qsa("#tabs button").forEach((b) => b.onclick = () => {
    S.qsa("#tabs button").forEach((x) => x.classList.remove("active")); b.classList.add("active");
    b.dataset.tab === "Team compliance" ? renderCompliance() : renderWorkout();
  });

  async function renderWorkout() {
    stopTimer();
    const today = await S.api("/api/gym/today");
    if (today && !today.end_time) {
      state.log = today;
      state.exercises = (today.exercises || []).map((e) => ({
        name: e.exercise_name, muscle: e.muscle_group,
        sets: e.sets_detail && e.sets_detail.length ? e.sets_detail : [{ set: 1, kg: e.weight_value, reps: e.reps, type: "Normal", done: true }],
        notes: e.notes || "",
      }));
      state.library = await S.api("/api/gym/library?day_type=" + encodeURIComponent(today.day_type));
      return renderSession();
    }
    if (today && today.end_time) return renderDone(today);
    renderStart();
  }

  function renderStart() {
    S.qs("#tabc").innerHTML = `<div class="card pad"><div class="section-label">Choose today's split</div>
      <div class="spread" style="margin-top:14px">${DAYS.map((d) => `
        <button class="card pad" data-day="${d.t}" style="text-align:left;cursor:pointer;border-width:2px">
          <span class="pill day ${d.t}" style="font-size:13px">${d.t}</span>
          <div class="sub" style="margin-top:10px">${d.d}</div></button>`).join("")}</div></div>`;
    S.qsa("[data-day]").forEach((b) => b.onclick = async () => {
      state.log = await S.api("/api/gym/start", { method: "POST", body: { day_type: b.dataset.day } });
      state.exercises = [];
      state.library = await S.api("/api/gym/library?day_type=" + encodeURIComponent(b.dataset.day));
      renderSession();
    });
  }

  function renderSession() {
    const log = state.log;
    S.qs("#tabc").innerHTML = `
      <div class="card pad" style="display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-bottom:16px">
        <div class="row"><span class="pill day ${log.day_type}" style="font-size:14px">${log.day_type}</span>
          <div><div class="section-label">Elapsed</div><strong id="gym-timer" style="font-size:20px;font-variant-numeric:tabular-nums">0:00</strong></div></div>
        <div class="row"><button class="btn ghost" id="gym-add">${S.ICON.plus}Add exercise</button>
          <button class="btn success" id="gym-finish">${S.ICON.check}Finish session</button></div>
      </div>
      <div id="ex-list"></div>`;
    renderExercises();
    startTimer(log.start_time);
    S.qs("#gym-add").onclick = openLibrary;
    S.qs("#gym-finish").onclick = finish;
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
      if (f === "notes") { state.exercises[i].notes = inp.value; return; }
      const si = +inp.dataset.si;
      state.exercises[i].sets[si][f] = f === "done" ? inp.checked : f === "type" ? inp.value : Number(inp.value);
    });
    box.querySelectorAll("[data-add-set]").forEach((b) => b.onclick = () => {
      const i = +b.dataset.addSet, last = state.exercises[i].sets.slice(-1)[0] || {};
      state.exercises[i].sets.push({ set: state.exercises[i].sets.length + 1, kg: last.kg || 0, reps: last.reps || 0, type: "Normal", done: false });
      renderExercises();
    });
    box.querySelectorAll("[data-del-set]").forEach((b) => b.onclick = () => {
      const [i, si] = b.dataset.delSet.split(":").map(Number);
      state.exercises[i].sets.splice(si, 1); if (!state.exercises[i].sets.length) state.exercises.splice(i, 1); renderExercises();
    });
    box.querySelectorAll("[data-del-ex]").forEach((b) => b.onclick = () => { state.exercises.splice(+b.dataset.delEx, 1); renderExercises(); });
  }

  function openLibrary() {
    const items = state.library;  // already scoped to the current day type (Push/Pull/Legs)
    // Muscle groups present for THIS day — e.g. Push -> Chest / Shoulders / Triceps.
    const muscles = [...new Set(items.map((e) => e.muscle_group).filter(Boolean))].sort();
    const m = S.modal({
      title: "Add exercise",
      body: `<div class="row" style="gap:8px;margin-bottom:12px">
          <input id="lib-search" placeholder="Search exercises…" style="flex:1">
          <select id="lib-muscle" style="max-width:170px"><option value="">All muscles</option>${muscles.map((mg) => `<option value="${S.esc(mg)}">${S.esc(mg)}</option>`).join("")}</select>
        </div>
        <div id="lib-list" style="max-height:360px;overflow:auto"></div>`,
      wide: false,
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
        m.close(); renderExercises();
      });
    };
    S.qs("#lib-search").oninput = draw;
    S.qs("#lib-muscle").onchange = draw;
    draw();
  }

  async function save() {
    const payload = state.exercises.map((ex) => ({
      exercise_name: ex.name, muscle_group: ex.muscle, set_type: "Normal",
      sets_detail: ex.sets.map((s, i) => ({ set: i + 1, kg: +s.kg || 0, reps: +s.reps || 0, type: s.type || "Normal", done: !!s.done, pr: false })),
      notes: ex.notes,
    }));
    await S.api(`/api/gym/${state.log.id}/exercises`, { method: "POST", body: payload });
  }

  async function finish() {
    try {
      await save();
      const res = await S.api(`/api/gym/${state.log.id}/end`, { method: "POST", body: { notes: "" } });
      stopTimer();
      renderSummary(res.summary, res.log);
    } catch (e) { S.toast(e.detail, "err"); }
  }

  function renderSummary(sum, log) {
    const muscles = Object.entries(sum.muscle_activation || {});
    S.qs("#tabc").innerHTML = `<div class="card pad" style="text-align:center">
        <div class="k-ic" style="margin:0 auto;width:52px;height:52px;background:var(--green-bg);color:var(--green-d)">${S.ICON.trophy}</div>
        <h2 style="margin-top:10px">Session complete 💪</h2>
        <span class="pill day ${log.day_type}">${log.day_type}</span> ${S.statusPill(log.status)}
        <div class="kpis" style="margin-top:18px">
          <div class="kpi"><div class="k-label">Duration</div><div class="k-val">${sum.duration_minutes}<span style="font-size:16px">m</span></div></div>
          <div class="kpi"><div class="k-label">Total sets</div><div class="k-val">${sum.total_sets}</div></div>
          <div class="kpi violet"><div class="k-label">Volume</div><div class="k-val">${sum.total_volume_kg}<span style="font-size:16px">kg</span></div></div>
          <div class="kpi"><div class="k-label">New PRs</div><div class="k-val">${sum.new_prs}</div></div>
        </div>
        ${muscles.length ? `<div style="margin-top:16px;text-align:left"><div class="section-label">Muscle activation</div>
          <div class="row wrap" style="margin-top:8px">${muscles.map(([m, n]) => `<span class="chip">${S.esc(m)} · ${n}</span>`).join("")}</div></div>` : ""}
        <button class="btn ghost" style="margin-top:18px" onclick="location.reload()">Back to gym</button>
      </div>`;
  }

  function renderDone(log) {
    S.qs("#tabc").innerHTML = `<div class="card pad" style="text-align:center">
      <div class="section-label">Today's session</div>
      <h2 style="margin:8px 0"><span class="pill day ${log.day_type}">${log.day_type}</span> ${S.statusPill(log.status)}</h2>
      <div class="sub">${log.duration_minutes} min · ${log.exercise_count} exercises</div>
      <div class="lead" style="margin-top:8px">You've already trained today. See you tomorrow!</div></div>`;
  }

  async function renderCompliance() {
    stopTimer();
    S.qs("#tabc").innerHTML = '<div class="skeleton" style="height:200px"></div>';
    const rows = await S.api("/api/gym/summary");
    S.qs("#tabc").innerHTML = `<div class="table-wrap"><table>
      <thead><tr><th>Employee</th><th>Sessions (wk)</th><th>Completed</th><th>Incomplete</th><th>This week</th></tr></thead>
      <tbody>${rows.map((r) => `<tr>
        <td class="t-name">${S.avatar({ name: r.name }, "sm")}${S.esc(r.name)}</td>
        <td>${r.sessions}</td><td>${r.completed}</td><td>${r.incomplete}</td>
        <td><div class="row">${r.logs.length ? r.logs.map((g) => `<span class="pill day ${g.day_type}" title="${g.status}">${g.day_type[0]}</span>`).join("") : '<span class="muted">—</span>'}</div></td></tr>`).join("")}</tbody></table></div>`;
  }

  function startTimer(startIso) {
    const t0 = new Date(startIso).getTime();
    const el = () => S.qs("#gym-timer");
    const tick = () => { const e = el(); if (!e) return; const m = Math.max(0, Math.floor((Date.now() - t0) / 60000)); e.textContent = Math.floor(m / 60) + ":" + String(m % 60).padStart(2, "0"); };
    tick(); state.timer = setInterval(tick, 1000);
  }
  function stopTimer() { if (state.timer) { clearInterval(state.timer); state.timer = null; } }

  renderWorkout();
};

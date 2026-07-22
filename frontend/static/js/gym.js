window.pageInit = async (S) => {
  const view = S.view();
  const isMgr = S.can("team_lead");
  const isSA = S.user.role === "super_admin";
  const SET_TYPES = ["Normal", "Warm-up", "Drop", "To failure"];
  const GYM_STATUSES = ["Completed", "Incomplete", "Missing"];
  const GYM_DAYS = ["Push", "Pull", "Legs", "Custom"];
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
    <div id="gym-body"></div>
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
      title: `${S.esc(r.name)} — sessions this week`,
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

  function startTimer(startIso) {
    const t0 = new Date(startIso).getTime();
    const el = () => S.qs("#gym-timer");
    const tick = () => { const e = el(); if (!e) return; const m = Math.max(0, Math.floor((Date.now() - t0) / 60000)); e.textContent = Math.floor(m / 60) + ":" + String(m % 60).padStart(2, "0"); };
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

  renderBodyStats();
  renderWorkout();
};

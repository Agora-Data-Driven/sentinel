/* TimeSpent — minutes on growth, per dimension, over Today / This week / 30 days — from TWO sources.

   Two mounts over one component (the same pattern as GrowthPanel / TeamGrowth):
     TimeSpent.mountMine(S, host, { userId })  — one person's strip: a tile per dimension
                                                 (Professional · Philosophical · Spiritual · Physical
                                                 · Coach), a window picker, and a Details door. Your
                                                 own on the Overview; somebody else's on /growth?user=.
     TimeSpent.mountTeam(S, host)              — the admin table: the same numbers for everyone the
                                                 viewer may see, most time first.

   WHERE THE MINUTES COME FROM.
     • The Mastery Engine stamps one key per ACTIVE minute per learner — a visible frame plus a recent
       signal (input, speaking, the AI speaking or streaming, an action), with a three-minute grace so
       silent reading counts and an abandoned tab does not. Several open frames stamp a minute once.
     • MANUAL ENTRIES are what the engine cannot see — a book on paper, a gym session, a course
       elsewhere — logged here against any dimension. Physical is manual-only (no engine programme).
     Sentinel merges the two at read time (services/time_spent.py); every session row says which it is.

   EDITING, from the Details modal:
     • an ENGINE session can be deleted or TRIMMED (✎) — never extended: to add time, log an entry.
       A session that ended in the last few minutes may still be running and is locked ("live").
     • a MANUAL entry is fully editable.
     Only the person (or an admin) gets the buttons; the server enforces the same rule.

   ONLY THE TOTALS SHOW BY DEFAULT. Which lessons the minutes went to is one click away (a tile, or
   Details) — deliberately not on the page, it is too much to read every morning.

   THE WINDOW IS ONE CHOICE, shared by both mounts and remembered in localStorage: "Today" by default.

   🔴 "—" IS UNKNOWN, "0m" IS ZERO. A person with no minutes is a real zero and is shown as one. The
   dash is reserved for the engine not answering, and the reason is printed beside the table. */
window.TimeSpent = {
  async mountMine(S, root, opts) { return TimeSpentImpl.mine(S, root, opts || {}); },
  async mountTeam(S, root, opts) { return TimeSpentImpl.team(S, root, opts || {}); },
};

const TimeSpentImpl = (() => {
  const WINDOWS = [
    { v: "today", t: "Today" },
    { v: "week", t: "This week" },
    { v: "30d", t: "30 days" },
  ];
  // Display order mirrors the compass, then the Coach. "other" (a growth programme not pinned to a
  // tab, or an honest miscellany entry) only appears when it has minutes.
  const BUCKETS = [
    { key: "professional", name: "Professional", hue: "var(--dim-professional)" },
    { key: "philosophical", name: "Philosophical", hue: "var(--dim-philosophical)" },
    { key: "spiritual", name: "Spiritual", hue: "var(--dim-spiritual)" },
    { key: "physical", name: "Physical", hue: "var(--dim-physical)" },
    { key: "coach", name: "Coach", hue: "var(--sub)" },
    { key: "other", name: "Other", hue: "var(--muted)", optional: true },
  ];
  const VIEW_LABEL = {
    quiz: "quiz", flashcards: "flashcards", lesson: "study guide", assistant: "assistant",
    browse: "browsing", progress: "progress", map: "knowledge map", app: "",
  };
  const LS_KEY = "sentinel.timeWindow";
  const listeners = new Set();

  function getWin() {
    try {
      const v = localStorage.getItem(LS_KEY);
      return WINDOWS.some((w) => w.v === v) ? v : "today";
    } catch (e) { return "today"; }
  }
  function setWin(v) {
    try { localStorage.setItem(LS_KEY, v); } catch (e) { /* private mode: still applies for now */ }
    notify();
  }
  // Every mount re-loads: after the window changes, and after any write (a new entry, a trimmed
  // session) so the strip, the team table and an open detail all agree again.
  function notify() {
    listeners.forEach((fn) => { try { fn(getWin()); } catch (e) { /* one listener must not stop the rest */ } });
  }
  const winLabel = (v) => (WINDOWS.find((w) => w.v === v) || WINDOWS[0]).t;

  const fmt = (m) => {
    if (m == null) return "—";
    const n = Math.max(0, Math.round(m));
    if (n < 60) return `${n}m`;
    return `${Math.floor(n / 60)}h ${String(n % 60).padStart(2, "0")}m`;
  };
  const bucketsShown = (buckets) => BUCKETS.filter((b) => !b.optional || (buckets && (buckets[b.key] || 0) > 0));
  const bucketOf = (key) => BUCKETS.find((b) => b.key === key) || BUCKETS[BUCKETS.length - 1];
  const isAdmin = (S) => !!(S.user && (S.user.role === "admin" || S.user.role === "super_admin"));
  const todayIso = () => {
    // PH date, whatever the browser's zone: the server's windows are PH days.
    const d = new Date(Date.now() + 8 * 3600 * 1000);
    return d.toISOString().slice(0, 10);
  };
  const nowHHMM = () => {
    const d = new Date(Date.now() + 8 * 3600 * 1000);
    return d.toISOString().slice(11, 16);
  };

  function winControl(cur) {
    return `<div class="ts-win" role="tablist" aria-label="Window">${WINDOWS.map((w) =>
      `<button type="button" role="tab" data-win="${w.v}" aria-selected="${w.v === cur}" class="${w.v === cur ? "on" : ""}">${w.t}</button>`).join("")}</div>`;
  }
  function wireWin(S, root) {
    S.qsa("[data-win]", root).forEach((b) => { b.onclick = () => setWin(b.dataset.win); });
  }
  const dayLabel = (S, day) => {
    try { return S.fmtDateFull(day + "T00:00:00+08:00"); } catch (e) { return day; }
  };

  // --- a small form modal (growth.js has the same shape; kept local so this file stands alone) ----
  function formModal(S, title, fields, onSave, opts) {
    const esc = S.esc;
    const body = fields.map((f) => {
      if (f.type === "select")
        return `<label class="field"><span>${esc(f.label)}</span><select id="tf-${f.name}">${f.options.map((o) => `<option value="${esc(o.v)}" ${o.v === f.value ? "selected" : ""}>${esc(o.t)}</option>`).join("")}</select></label>`;
      return `<label class="field"><span>${esc(f.label)}</span><input id="tf-${f.name}" type="${f.type || "text"}" ${f.min != null ? `min="${f.min}"` : ""} ${f.max != null ? `max="${f.max}"` : ""} ${f.step ? `step="${f.step}"` : ""} value="${f.value != null ? esc(String(f.value)) : ""}" placeholder="${esc(f.ph || "")}"></label>`;
    }).join("");
    const m = S.modal({
      title,
      body: `${opts && opts.lede ? `<div class="sub" style="margin-bottom:10px">${opts.lede}</div>` : ""}<div class="formgrid">${body}</div>`,
      footer: `<button class="btn ghost" id="tf-cancel">Cancel</button><button class="btn primary" id="tf-save">${esc((opts && opts.saveLabel) || "Save")}</button>`,
    });
    S.qs("#tf-cancel").onclick = m.close;
    S.qs("#tf-save").onclick = async () => {
      const out = {};
      fields.forEach((f) => { out[f.name] = S.qs(`#tf-${f.name}`).value; });
      const btn = S.qs("#tf-save");
      btn.disabled = true;
      try { await onSave(out); m.close(); }
      catch (e) { S.toast(e.detail || "Couldn't save", "err"); btn.disabled = false; }
    };
    return m;
  }

  const dimOptions = (dims) => (dims || BUCKETS.map((b) => b.key)).map((k) => ({ v: k, t: bucketOf(k).name }));

  // --- writes ------------------------------------------------------------------------------------
  function addEntryForm(S, { userId, dims, day, bucket }, done) {
    formModal(S, "Log time", [
      { name: "date", label: "Date", type: "date", value: day || todayIso(), max: todayIso() },
      { name: "start", label: "Started at", type: "time", value: nowHHMM() },
      { name: "minutes", label: "Minutes", type: "number", value: 30, min: 1, max: 720 },
      { name: "dimension", label: "Dimension", type: "select", value: bucket && bucket !== "other" ? bucket : "professional", options: dimOptions(dims) },
      { name: "note", label: "What was it? (optional)", ph: "e.g. read Meditations ch. 4 · gym · client course" },
    ], async (o) => {
      await S.api("/api/development/time/entries", { method: "POST", body: {
        date: o.date, start: o.start, minutes: Number(o.minutes), dimension: o.dimension,
        note: o.note || null, user_id: userId ? Number(userId) : null,
      } });
      S.toast("Time logged", "ok");
      done();
    }, { lede: "For time the engine couldn't see — reading on paper, the gym, a course elsewhere. Engine sessions are recorded on their own; log only what's outside it.", saveLabel: "Log time" });
  }
  function editEntryForm(S, s, dims, done) {
    formModal(S, "Edit entry", [
      { name: "date", label: "Date", type: "date", value: s.day, max: todayIso() },
      { name: "start", label: "Started at", type: "time", value: s.start },
      { name: "minutes", label: "Minutes", type: "number", value: s.minutes, min: 1, max: 720 },
      { name: "dimension", label: "Dimension", type: "select", value: s.dimension || s.bucket, options: dimOptions(dims) },
      { name: "note", label: "Note", value: s.note || "" },
    ], async (o) => {
      await S.api(`/api/development/time/entries/${s.id}`, { method: "PATCH", body: {
        date: o.date, start: o.start, minutes: Number(o.minutes), dimension: o.dimension, note: o.note,
      } });
      S.toast("Entry updated", "ok");
      done();
    });
  }
  function trimEngineForm(S, s, userId, done) {
    formModal(S, "Adjust recorded session", [
      { name: "new_start", label: `Really started at (recorded ${s.start})`, type: "time", value: s.start, min: s.start, max: s.end },
      { name: "new_end", label: `Really stopped at (recorded ${s.end})`, type: "time", value: s.end, min: s.start, max: s.end },
    ], async (o) => {
      const res = await S.api("/api/development/time/engine-edit", { method: "POST", body: {
        day: s.day, start: s.start, end: s.end, new_start: o.new_start, new_end: o.new_end,
        user_id: userId ? Number(userId) : null,
      } });
      S.toast(res.removed ? `Removed ${fmt(res.removed)}` : "Nothing changed", "ok");
      done();
    }, { lede: "Shorten a session the engine recorded — for when you were there but not really working. It can only be shortened; to add time, log an entry.", saveLabel: "Adjust" });
  }
  async function deleteSession(S, s, userId, done) {
    const what = s.source === "manual" ? "this entry" : `this recorded session (${s.start}–${s.end}, ${fmt(s.minutes)})`;
    const m = S.modal({
      title: "Remove time",
      body: `<p>Remove ${S.esc(what)}? ${s.source === "manual" ? "" : "The engine's minutes for it will be deleted."} This can't be undone.</p>`,
      footer: `<button class="btn ghost" id="td-cancel">Cancel</button><button class="btn danger" id="td-go">Remove</button>`,
    });
    S.qs("#td-cancel").onclick = m.close;
    S.qs("#td-go").onclick = async () => {
      try {
        if (s.source === "manual") {
          await S.api(`/api/development/time/entries/${s.id}`, { method: "DELETE" });
        } else {
          await S.api("/api/development/time/engine-edit", { method: "POST", body: {
            day: s.day, start: s.start, end: s.end, user_id: userId ? Number(userId) : null,
          } });
        }
        m.close();
        S.toast("Removed", "ok");
        done();
      } catch (e) { S.toast(e.detail || "Couldn't remove it", "err"); }
    };
  }

  // --- the click-through: one person's sessions, grouped by day, filterable by bucket ----------
  async function openDetail(S, { userId, name, bucket, canWrite }) {
    const esc = S.esc;
    const win = getWin();
    let filter = bucket || "";
    const m = S.modal({
      title: `${name ? esc(name) + " · " : ""}Time · ${winLabel(win)}`,
      body: `<div id="ts-detail">${S.skeleton ? S.skeleton({ rows: 4 }) : "Loading…"}</div>`,
      footer: `<button class="btn ghost" id="ts-close">Close</button>`,
      wide: true,
    });
    S.qs("#ts-close").onclick = () => m.close();
    let data;
    async function load() {
      try {
        data = await S.api(`/api/development/time/detail?win=${win}${userId ? `&user_id=${encodeURIComponent(userId)}` : ""}`);
      } catch (e) {
        const h = S.qs("#ts-detail");
        if (h) h.innerHTML = `<div class="empty">${esc(e.detail || "Couldn't load the detail.")}</div>`;
        return false;
      }
      return true;
    }
    // After any write: re-read this modal AND every mounted strip/table.
    const changed = async () => { if (await load()) render(); notify(); };

    function render() {
      const host = S.qs("#ts-detail");
      if (!host) return;
      const dims = data.dimensions;
      const toolbar = `<div class="ts-toolbar">
        <div class="ts-chips">
          <button type="button" class="ts-chip ${filter ? "" : "on"}" data-b="">All · ${fmt(data.total)}</button>
          ${bucketsShown(data.buckets).map((b) => `<button type="button" class="ts-chip ${filter === b.key ? "on" : ""}" data-b="${b.key}" style="--hue:${b.hue}">${esc(b.name)} · ${fmt(data.buckets[b.key])}</button>`).join("")}
        </div>
        ${canWrite ? `<button type="button" class="btn sm primary" id="ts-add">${S.ICON.plus}Log time</button>` : ""}
      </div>`;
      const engineWarn = data.found ? "" : `<div class="tg-warn">${S.ICON.x}Mastery Engine: ${esc(data.engine_error || "no answer")} — recorded sessions can't be shown right now; manual entries below are still yours.</div>`;
      const sessions = (data.sessions || []).filter((s) => !filter || s.bucket === filter);
      let rows;
      if (!sessions.length) {
        rows = `<div class="empty" style="margin-top:12px">No time recorded ${filter ? "in " + esc(bucketOf(filter).name) : ""} ${win === "today" ? "today" : "in this window"}.${canWrite ? " Use <strong>Log time</strong> for anything outside the engine." : ""}</div>`;
      } else {
        const byDay = new Map();
        sessions.forEach((s) => { if (!byDay.has(s.day)) byDay.set(s.day, []); byDay.get(s.day).push(s); });
        rows = [...byDay.keys()].sort().reverse().map((day) => {
          const list = byDay.get(day).slice().sort((a, b) => (b.start || "").localeCompare(a.start || ""));
          const total = list.reduce((a, s) => a + (s.minutes || 0), 0);
          return `<div class="ts-day">${esc(dayLabel(S, day))} <span class="ts-total">· ${fmt(total)}</span></div>
            ${list.map((s, i) => {
              const b = bucketOf(s.bucket);
              const path = [s.track, s.course, s.lesson].filter(Boolean).map(esc).join(" › ");
              const topics = (s.topics || []).length ? `<small> · ${(s.topics || []).map(esc).join(", ")}</small>` : "";
              const view = s.source === "engine" ? (VIEW_LABEL[s.view] != null ? VIEW_LABEL[s.view] : s.view) : "";
              const what = s.source === "manual"
                ? esc(b.name) + (s.note ? `<span class="ts-note">${esc(s.note)}</span>` : "")
                : (path || esc(s.program_name || (s.bucket === "coach" ? "Coach" : "Mastery Engine"))) + (view ? `<small> · ${esc(view)}</small>` : "") + topics;
              const tag = s.source === "manual" ? `<span class="ts-tag manual">logged</span>` : (s.live ? `<span class="ts-tag live" title="Still running — editable a few minutes after it ends">live</span>` : "");
              const acts = canWrite && s.editable
                ? `<span class="ts-acts"><button type="button" data-act="edit" data-i="${i}" data-day="${esc(day)}" title="${s.source === "manual" ? "Edit entry" : "Shorten this session"}">✎</button><button type="button" class="danger" data-act="del" data-i="${i}" data-day="${esc(day)}" title="Remove">✕</button></span>`
                : `<span></span>`;
              return `<div class="ts-sess" style="--hue:${b.hue}">
                <span class="t">${esc(s.start)}–${esc(s.end)}</span>
                <span class="m">${fmt(s.minutes)}</span>
                <span class="w"><span class="ts-dot" title="${esc(b.name)}"></span>${what}${tag}</span>
                ${acts}
              </div>`;
            }).join("")}`;
        }).join("");
        // Keep the per-day sorted lists so the action buttons can find their row.
        render._lists = byDay;
      }
      host.innerHTML = engineWarn + toolbar + rows;
      S.qsa("[data-b]", host).forEach((c) => { c.onclick = () => { filter = c.dataset.b; render(); }; });
      const add = S.qs("#ts-add", host);
      if (add) add.onclick = () => addEntryForm(S, { userId, dims, bucket: filter }, changed);
      S.qsa("[data-act]", host).forEach((btn) => {
        btn.onclick = () => {
          const list = (render._lists.get(btn.dataset.day) || []).slice().sort((a, b) => (b.start || "").localeCompare(a.start || ""));
          const s = list[Number(btn.dataset.i)];
          if (!s) return;
          if (btn.dataset.act === "del") deleteSession(S, s, userId, changed);
          else if (s.source === "manual") editEntryForm(S, s, dims, changed);
          else trimEngineForm(S, s, userId, changed);
        };
      });
    }
    if (await load()) render();
  }

  // --- one person's strip -----------------------------------------------------------------------
  async function mine(S, root, opts) {
    const esc = S.esc;
    const userId = opts.userId || null;
    const canWrite = !userId || isAdmin(S);
    let data = null, failed = "";

    function tiles() {
      if (failed) return `<div class="ts-note tg-warn">${S.ICON.x}${esc(failed)}</div>`;
      if (!data) return `<div class="ts-note">Loading…</div>`;
      const shown = bucketsShown(data.buckets);
      const warn = data.found ? "" : `<div class="ts-note tg-warn">${S.ICON.x}Mastery Engine: ${esc(data.engine_error || "no answer")} — engine minutes read “—” (unknown, not zero)${data.manual_minutes ? `; ${fmt(data.manual_minutes)} logged by hand` : ""}.</div>`;
      return warn + `<div class="ts-tiles" style="grid-template-columns:repeat(${shown.length},1fr)">${shown.map((b) => {
        const v = data.buckets[b.key];
        const manual = (data.manual_buckets || {})[b.key] || 0;
        const sub = v == null ? (manual ? `${fmt(manual)} logged` : "engine unknown")
          : v ? (manual && manual !== v ? `${fmt(manual)} logged by hand` : (manual ? "logged by hand" : "tap for detail"))
          : (data.window === "today" ? "nothing yet today" : "no time in window");
        return `<button type="button" class="ts-tile" data-bucket="${b.key}" style="--hue:${b.hue}" title="See what the ${esc(b.name)} minutes went to">
          <span class="k">${esc(b.name)}</span>
          <span class="v ${v ? "" : "zero"}">${fmt(v == null && manual ? manual : v)}</span>
          <span class="s">${sub}</span>
        </button>`;
      }).join("")}</div>`;
    }
    function render() {
      const win = getWin();
      const total = data && data.found ? `<span class="ts-total">${fmt(data.total)} total</span>` : "";
      root.innerHTML = `<div class="ts-card">
        <div class="ts-head">
          <div class="ts-title">${S.ICON.clock}Time on growth ${total}</div>
          <div class="row" style="gap:8px;align-items:center">
            ${winControl(win)}
            ${canWrite ? `<button type="button" class="btn sm ghost" id="ts-log" title="Log time the engine couldn't see">${S.ICON.plus}Log time</button>` : ""}
            <button type="button" class="btn sm ghost" id="ts-details" ${data ? "" : "disabled"}>Details</button>
          </div>
        </div>
        ${tiles()}
      </div>`;
      wireWin(S, root);
      const name = data && data.user ? data.user.name : "";
      S.qsa("[data-bucket]", root).forEach((t) => { t.onclick = () => openDetail(S, { userId, name, bucket: t.dataset.bucket, canWrite }); });
      const d = S.qs("#ts-details", root);
      if (d) d.onclick = () => openDetail(S, { userId, name, canWrite });
      const l = S.qs("#ts-log", root);
      if (l) l.onclick = () => addEntryForm(S, { userId }, notify);
    }
    async function load() {
      failed = "";
      try {
        data = await S.api(`/api/development/time?win=${getWin()}${userId ? `&user_id=${encodeURIComponent(userId)}` : ""}`);
      } catch (e) {
        data = null;
        failed = e.detail || "Couldn't load your time.";
      }
      render();
    }
    listeners.add(() => { load(); });
    render();
    await load();
  }

  // --- the admin table --------------------------------------------------------------------------
  async function team(S, root, opts) {
    const esc = S.esc;
    let payload = null, failed = "";

    function table() {
      if (failed) return `<div class="empty card pad">${esc(failed)}</div>`;
      if (!payload) return S.skeleton ? S.skeleton({ rows: 3 }) : "Loading…";
      const rows = payload.rows || [];
      if (!rows.length) return `<div class="empty">No active teammates to show.</div>`;
      const cols = BUCKETS.filter((b) => !b.optional || rows.some((r) => r.buckets && (r.buckets[b.key] || 0) > 0));
      const unknown = rows.filter((r) => r.total == null).length;
      const notes = [];
      if (payload.engine_error) {
        notes.push(`<div class="tg-warn">${S.ICON.x}Mastery Engine: ${esc(payload.engine_error)}. Engine minutes read “—”, which means <strong>unknown</strong> — not zero; hand-logged minutes are still shown.</div>`);
      } else if (unknown) {
        notes.push(`<div class="sub tg-foot">${unknown} ${unknown === 1 ? "row" : "rows"} could not be read from the engine and show “—”.</div>`);
      }
      const head = `<tr><th>Teammate</th>${cols.map((b) => `<th class="num" style="--hue:${b.hue}">${esc(b.name)}</th>`).join("")}<th class="num">Total</th><th>Last active</th></tr>`;
      const body = rows.map((r) => {
        const u = r.user || {};
        const cells = cols.map((b) => {
          const v = r.buckets ? r.buckets[b.key] : null;
          return `<td class="num" style="--hue:${b.hue}">${v == null ? `<span class="tg-na">—</span>` : `<span class="tg-pct">${fmt(v)}</span>`}</td>`;
        }).join("");
        const last = r.last_at ? esc(String(r.last_at).slice(11)) + `<small class="sub"> · ${esc(String(r.last_at).slice(0, 10))}</small>` : `<span class="tg-na">—</span>`;
        const total = r.total == null
          ? (r.manual_minutes ? `<span class="tg-na" title="Engine unknown; hand-logged only">${fmt(r.manual_minutes)}*</span>` : `<span class="tg-na">—</span>`)
          : `<strong>${fmt(r.total)}</strong>${r.manual_minutes ? `<small class="sub" title="of which logged by hand"> · ${fmt(r.manual_minutes)} logged</small>` : ""}`;
        return `<tr data-user="${esc(String(u.id || ""))}" data-name="${esc(u.name || u.email || "")}" title="See what the minutes went to">
          <td class="who"><div class="n">${esc(u.name || u.email || "")}</div></td>
          ${cells}
          <td class="num">${total}</td>
          <td class="tg-act">${last}</td>
        </tr>`;
      }).join("");
      notes.push(`<div class="sub tg-foot">Engine minutes count when the engine is on screen and something happened in the last three
        minutes — an answer, a card, a message, speaking, or the assistant speaking or writing back; frames open side by side
        count once. Hand-logged time (a book, the gym, a course elsewhere) is added on top. Click a row for the sessions.${payload.generated_at ? ` Measured ${S.timeAgo(payload.generated_at)}.` : ""}</div>`);
      return `${notes.join("")}<div class="tg-wrap"><table class="tg-tbl table-sticky-1"><thead>${head}</thead><tbody>${body}</tbody></table></div>`;
    }
    function render() {
      const win = getWin();
      root.innerHTML = `<div class="row between sect-head" style="margin-top:26px">
          <div class="section-label">${S.ICON.clock}Team time on growth</div>
          <div class="row" style="gap:8px;align-items:center">
            <span class="sub">${winLabel(win)}</span>
            ${winControl(win)}
            <button type="button" class="btn sm ghost" id="ts-refresh" title="Re-read the engine now">${S.ICON.check}Refresh</button>
          </div>
        </div>
        <div id="ts-team-body">${table()}</div>`;
      wireWin(S, root);
      const rf = S.qs("#ts-refresh", root);
      if (rf) rf.onclick = () => load({ refresh: true });
      S.qsa("tr[data-user]", root).forEach((tr) => {
        tr.onclick = () => openDetail(S, { userId: tr.dataset.user, name: tr.dataset.name, canWrite: isAdmin(S) });
      });
    }
    async function load(o) {
      failed = "";
      try {
        payload = await S.api(`/api/development/team-time?win=${getWin()}${o && o.refresh ? "&refresh=1" : ""}`);
      } catch (e) {
        payload = null;
        failed = e.detail || "Couldn't load the team's time.";
      }
      render();
    }
    // A write elsewhere (a logged entry, a trimmed session) changed the totals: bypass the cache.
    listeners.add(() => { load({ refresh: true }); });
    render();
    await load();
  }

  return { mine, team };
})();

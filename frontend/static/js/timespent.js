/* TimeSpent — minutes in the Mastery Engine, per growth dimension, over Today / This week / 30 days.

   Two mounts over one component (the same pattern as GrowthPanel / TeamGrowth):
     TimeSpent.mountMine(S, host, { userId })  — one person's strip: four tiles (Professional ·
                                                 Philosophical · Spiritual · Coach), a window
                                                 picker, and a Details door. Your own on the
                                                 Overview; somebody else's on /growth?user=.
     TimeSpent.mountTeam(S, host)              — the admin table: the same four numbers for
                                                 everyone the viewer may see, most time first.

   WHERE THE MINUTES COME FROM. The engine stamps one key per ACTIVE minute per learner — a visible
   frame plus a recent signal (input, speaking, the AI speaking or streaming, an action), with a
   three-minute grace so silent reading counts and an abandoned tab does not. Several open frames
   (the Professional tab, a growth tab, the Coach) stamp the same minute once. Sentinel reads them
   back through services/time_spent.py and maps programmes onto dimensions there; nothing here does
   arithmetic beyond formatting.

   ONLY THE TOTALS SHOW BY DEFAULT. Which lessons the minutes went to is one click away (a tile, or
   Details) — deliberately not on the page, it is too much to read every morning.

   THE WINDOW IS ONE CHOICE, shared by both mounts and remembered in localStorage: "Today" by
   default, because that is the question the Overview answers.

   🔴 "—" IS UNKNOWN, "0m" IS ZERO. Here, unlike the progress rollups, a person with no minutes is a
   real zero and is shown as one. The dash is reserved for the engine not answering, and the reason
   is printed beside the table so a bridge outage never reads as "nobody used it". */
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
  // Display order mirrors the compass. "other" (a growth programme not pinned to a tab) only
  // appears when it has minutes, so the strip stays four tiles wide on an ordinary day.
  const BUCKETS = [
    { key: "professional", name: "Professional", hue: "var(--dim-professional)" },
    { key: "philosophical", name: "Philosophical", hue: "var(--dim-philosophical)" },
    { key: "spiritual", name: "Spiritual", hue: "var(--dim-spiritual)" },
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
    listeners.forEach((fn) => { try { fn(v); } catch (e) { /* one listener must not stop the rest */ } });
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

  // --- the click-through: one person's sessions, grouped by day, filterable by bucket ----------
  async function openDetail(S, { userId, name, bucket }) {
    const esc = S.esc;
    const win = getWin();
    let filter = bucket || "";
    const m = S.modal({
      title: `${name ? esc(name) + " · " : ""}Time in the engine · ${winLabel(win)}`,
      body: `<div id="ts-detail">${S.skeleton ? S.skeleton({ rows: 4 }) : "Loading…"}</div>`,
      footer: `<button class="btn ghost" id="ts-close">Close</button>`,
    });
    S.qs("#ts-close").onclick = () => m.close();
    let data;
    try {
      data = await S.api(`/api/development/time/detail?win=${win}${userId ? `&user_id=${encodeURIComponent(userId)}` : ""}`);
    } catch (e) {
      S.qs("#ts-detail").innerHTML = `<div class="empty">${esc(e.detail || "Couldn't load the detail.")}</div>`;
      return;
    }
    const host = S.qs("#ts-detail");
    if (!host) return;

    function render() {
      if (!data.found) {
        host.innerHTML = `<div class="tg-warn">${S.ICON.x}Mastery Engine: ${esc(data.engine_error || "no answer")}.</div>`;
        return;
      }
      const shown = bucketsShown(data.buckets);
      const chips = `<div class="ts-chips">
        <button type="button" class="ts-chip ${filter ? "" : "on"}" data-b="">All · ${fmt(data.total)}</button>
        ${shown.map((b) => `<button type="button" class="ts-chip ${filter === b.key ? "on" : ""}" data-b="${b.key}" style="--hue:${b.hue}">${esc(b.name)} · ${fmt(data.buckets[b.key])}</button>`).join("")}
      </div>`;
      const sessions = (data.sessions || []).filter((s) => !filter || s.bucket === filter);
      if (!sessions.length) {
        host.innerHTML = chips + `<div class="empty" style="margin-top:12px">No time recorded ${filter ? "in " + esc(bucketOf(filter).name) : ""} ${win === "today" ? "today" : "in this window"}.</div>`;
        wireChips();
        return;
      }
      const byDay = new Map();
      sessions.forEach((s) => { if (!byDay.has(s.day)) byDay.set(s.day, []); byDay.get(s.day).push(s); });
      const days = [...byDay.keys()].sort().reverse();
      const rows = days.map((day) => {
        const list = byDay.get(day).slice().sort((a, b) => (b.start || "").localeCompare(a.start || ""));
        const total = list.reduce((a, s) => a + (s.minutes || 0), 0);
        return `<div class="ts-day">${esc(dayLabel(S, day))} <span class="ts-total">· ${fmt(total)}</span></div>
          ${list.map((s) => {
            const b = bucketOf(s.bucket);
            const path = [s.track, s.course, s.lesson].filter(Boolean).map(esc).join(" › ");
            const topics = (s.topics || []).length ? `<small> · ${(s.topics || []).map(esc).join(", ")}</small>` : "";
            const view = VIEW_LABEL[s.view] != null ? VIEW_LABEL[s.view] : s.view;
            const what = path || esc(s.program_name || (s.bucket === "coach" ? "Coach" : "Mastery Engine"));
            return `<div class="ts-sess" style="--hue:${b.hue}">
              <span class="t">${esc(s.start)}–${esc(s.end)}</span>
              <span class="m">${fmt(s.minutes)}</span>
              <span class="w"><span class="ts-dot" title="${esc(b.name)}"></span>${what}${view ? `<small> · ${esc(view)}</small>` : ""}${topics}</span>
            </div>`;
          }).join("")}`;
      }).join("");
      host.innerHTML = chips + rows;
      wireChips();
    }
    function wireChips() {
      S.qsa("[data-b]", host).forEach((c) => { c.onclick = () => { filter = c.dataset.b; render(); }; });
    }
    render();
  }

  // --- one person's strip -----------------------------------------------------------------------
  async function mine(S, root, opts) {
    const esc = S.esc;
    const userId = opts.userId || null;
    let data = null, failed = "";

    function tiles() {
      if (failed) return `<div class="ts-note tg-warn">${S.ICON.x}${esc(failed)}</div>`;
      if (!data) return `<div class="ts-note">Loading…</div>`;
      if (!data.found) {
        return `<div class="ts-note tg-warn">${S.ICON.x}Mastery Engine: ${esc(data.engine_error || "no answer")} — minutes read “—”, which means unknown, not zero.</div>`;
      }
      const shown = bucketsShown(data.buckets);
      return `<div class="ts-tiles" style="grid-template-columns:repeat(${shown.length},1fr)">${shown.map((b) => {
        const v = data.buckets[b.key];
        return `<button type="button" class="ts-tile" data-bucket="${b.key}" style="--hue:${b.hue}" title="See what the ${esc(b.name)} minutes went to">
          <span class="k">${esc(b.name)}</span>
          <span class="v ${v ? "" : "zero"}">${fmt(v)}</span>
          <span class="s">${v ? "tap for detail" : (data.window === "today" ? "nothing yet today" : "no time in window")}</span>
        </button>`;
      }).join("")}</div>`;
    }
    function render() {
      const win = getWin();
      const total = data && data.found ? `<span class="ts-total">${fmt(data.total)} total</span>` : "";
      root.innerHTML = `<div class="ts-card">
        <div class="ts-head">
          <div class="ts-title">${S.ICON.clock}Time in the engine ${total}</div>
          <div class="row" style="gap:8px;align-items:center">
            ${winControl(win)}
            <button type="button" class="btn sm ghost" id="ts-details" ${data && data.found ? "" : "disabled"}>Details</button>
          </div>
        </div>
        ${tiles()}
      </div>`;
      wireWin(S, root);
      const name = data && data.user ? data.user.name : "";
      S.qsa("[data-bucket]", root).forEach((t) => { t.onclick = () => openDetail(S, { userId, name, bucket: t.dataset.bucket }); });
      const d = S.qs("#ts-details", root);
      if (d) d.onclick = () => openDetail(S, { userId, name });
    }
    async function load() {
      failed = "";
      try {
        data = await S.api(`/api/development/time?win=${getWin()}${userId ? `&user_id=${encodeURIComponent(userId)}` : ""}`);
      } catch (e) {
        data = null;
        failed = e.detail || "Couldn't load your engine time.";
      }
      render();
    }
    listeners.add(() => { data = null; render(); load(); });
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
      // Only show "Other" when somebody actually has minutes there.
      const cols = BUCKETS.filter((b) => !b.optional || rows.some((r) => r.buckets && (r.buckets[b.key] || 0) > 0));
      const unknown = rows.filter((r) => r.total == null).length;
      const notes = [];
      if (payload.engine_error) {
        notes.push(`<div class="tg-warn">${S.ICON.x}Mastery Engine: ${esc(payload.engine_error)}. Those rows read “—”, which means <strong>unknown</strong> — not zero minutes.</div>`);
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
        return `<tr data-user="${esc(String(u.id || ""))}" data-name="${esc(u.name || u.email || "")}" title="See what the minutes went to">
          <td class="who"><div class="n">${esc(u.name || u.email || "")}</div></td>
          ${cells}
          <td class="num">${r.total == null ? `<span class="tg-na">—</span>` : `<strong>${fmt(r.total)}</strong>`}</td>
          <td class="tg-act">${last}</td>
        </tr>`;
      }).join("");
      notes.push(`<div class="sub tg-foot">A minute counts when the engine is on screen and something happened in the last three
        minutes — an answer, a card, a message, speaking, or the assistant speaking or writing back. Frames open side by side
        count once. Click a row for the sessions.${payload.generated_at ? ` Measured ${S.timeAgo(payload.generated_at)}.` : ""}</div>`);
      return `${notes.join("")}<div class="tg-wrap"><table class="tg-tbl table-sticky-1"><thead>${head}</thead><tbody>${body}</tbody></table></div>`;
    }
    function render() {
      const win = getWin();
      root.innerHTML = `<div class="row between sect-head" style="margin-top:26px">
          <div class="section-label">${S.ICON.clock}Team time in the engine</div>
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
        tr.onclick = () => openDetail(S, { userId: tr.dataset.user, name: tr.dataset.name });
      });
    }
    async function load(o) {
      failed = "";
      try {
        payload = await S.api(`/api/development/team-time?win=${getWin()}${o && o.refresh ? "&refresh=1" : ""}`);
      } catch (e) {
        payload = null;
        failed = e.detail || "Couldn't load the team's engine time.";
      }
      render();
    }
    listeners.add(() => { payload = null; render(); load(); });
    render();
    await load();
  }

  return { mine, team };
})();

/* CALENDAR — a projection of dated records (2026-09-02). No table behind it: task due dates,
   recurring services' trigger days and approved leave, read from /api/ops/calendar
   (services/calendar_view.py). Change a due date on the card and this moves.

   Week is the default view (the management rhythm). Mine / Everyone follows the board's own scope
   rule — `mine` is the server's `is_assigned`, Everyone is whatever `can_view` allows. */
window.pageInit = async (S) => {
  const U = window.OpsUI;
  const view = S.view();
  const PH = U.PH_TODAY();
  const isManager = S.can("team_lead") || S.user.role === "viewer";
  const st = { view: "week", mine: !isManager, anchor: PH };
  const iso = (d) => d.toISOString().slice(0, 10);
  const addDays = (s, n) => iso(new Date(Date.parse(s + "T00:00:00Z") + n * 864e5));
  const monday = (s) => { const d = new Date(s + "T00:00:00Z"); return addDays(s, -((d.getUTCDay() + 6) % 7)); };
  const DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  const KIND = { due: "Task due", late: "Overdue", done: "Completed", recurring: "Recurring deliverable", leave: "Leave" };

  async function render() {
    let frm, to;
    if (st.view === "today") { frm = to = PH; }
    else if (st.view === "week") { frm = monday(st.anchor); to = addDays(frm, 6); }
    else { const d = new Date(st.anchor + "T00:00:00Z"); const first = iso(new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), 1))); frm = monday(first); to = addDays(frm, 41); }
    view.innerHTML = `<div class="pagehead">
      <div><h2>Calendar</h2><div class="lead">Task deadlines, recurring deliverables and leave — projected from the board. Move a due date on the card and this moves.</div></div>
      <div class="row" style="gap:8px;flex-wrap:wrap;align-items:center">
        <button class="btn sm ghost" id="cal-prev" aria-label="Previous" style="transform:scaleX(-1)">${S.ICON.chev}</button>
        <button class="btn sm ghost" id="cal-today">Today</button>
        <button class="btn sm ghost" id="cal-next" aria-label="Next">${S.ICON.chev}</button>
        <div class="seg sm" role="tablist">${["today", "week", "month"].map((v) => `<button type="button" data-view="${v}" class="${st.view === v ? "on" : ""}">${v[0].toUpperCase() + v.slice(1)}</button>`).join("")}</div>
        ${isManager ? `<div class="seg sm" role="tablist"><button type="button" data-mine="1" class="${st.mine ? "on" : ""}">Mine</button><button type="button" data-mine="0" class="${st.mine ? "" : "on"}">Everyone</button></div>` : ""}
      </div></div>
      <div id="cal-grid"><div class="skeleton skel-card" style="height:300px"></div></div>
      <div class="os-cal-leg">${Object.entries(KIND).map(([k, l]) => `<span><i class="${k}"></i>${l}</span>`).join("")}</div>`;
    S.qs("#cal-prev").onclick = () => { st.anchor = addDays(st.anchor, st.view === "month" ? -28 : st.view === "week" ? -7 : -1); render(); };
    S.qs("#cal-next").onclick = () => { st.anchor = addDays(st.anchor, st.view === "month" ? 28 : st.view === "week" ? 7 : 1); render(); };
    S.qs("#cal-today").onclick = () => { st.anchor = PH; render(); };
    S.qsa("[data-view]").forEach((b) => b.onclick = () => { st.view = b.dataset.view; render(); });
    S.qsa("[data-mine]").forEach((b) => b.onclick = () => { st.mine = b.dataset.mine === "1"; render(); });

    let d;
    try { d = await S.api(`/api/ops/calendar?from=${frm}&to=${to}&mine=${st.mine ? 1 : 0}`); }
    catch (e) { S.qs("#cal-grid").innerHTML = `<div class="notice warn"><b>Couldn't load the calendar.</b> ${S.esc(e.detail || "")}</div>`; return; }
    // Expand leave spans onto each day they cover; everything else is a single day.
    const byDay = {};
    for (const e of d.events || []) {
      if (e.kind === "leave" && e.end_date) {
        for (let day = e.date; day <= e.end_date; day = addDays(day, 1)) (byDay[day] = byDay[day] || []).push(e);
      } else (byDay[e.date] = byDay[e.date] || []).push(e);
    }
    const ev = (e) => {
      const cls = e.kind === "due" && e.late ? "late" : e.kind;
      const sub = [e.client, e.assignee && !st.mine ? e.assignee.name.split(" ")[0] : null, e.kind === "recurring" ? "recurring" : null].filter(Boolean).join(" · ");
      return `<a class="os-ev ${cls} ${e.parked ? "parked" : ""}" href="${S.esc(e.href || "#")}">${S.esc(e.title)}${sub ? `<small>${S.esc(sub)}</small>` : ""}</a>`;
    };
    const days = [];
    for (let day = frm; day <= to; day = addDays(day, 1)) days.push(day);
    const cell = (day) => {
      const dt = new Date(day + "T00:00:00Z");
      const list = (byDay[day] || []).sort((a, b) => (a.kind === "leave") - (b.kind === "leave"));
      return `<div class="os-cal-day ${day === PH ? "today" : ""} ${dt.getUTCDay() % 6 === 0 ? "wk" : ""}">
        <div class="os-cal-dow">${DOW[(dt.getUTCDay() + 6) % 7]}${st.view === "month" && dt.getUTCDate() === 1 ? ` · ${dt.toLocaleDateString("en-PH", { month: "short", timeZone: "UTC" })}` : ""}</div>
        <div class="os-cal-num">${dt.getUTCDate()}</div>${list.map(ev).join("")}</div>`;
    };
    S.qs("#cal-grid").innerHTML = st.view === "today"
      ? `<div class="os-cal one">${cell(PH)}</div>`
      : `<div class="os-cal ${st.view}">${days.map(cell).join("")}</div>`;
  }
  render();
};

/* Overview — the one page you land on (renamed from "Dashboard" 2026-08-03, when the Growth
   hub's own Overview merged into it; /growth now only serves a manager's read-only view of
   somebody else).

   Reading order, top to bottom — personal first, org-wide last:
     1. Greeting + the DAY STRIP: attendance and gym as two compact buttons, not two big tiles.
        (The notifications tile was dropped: the bell in the topbar is the same number, and a
        card whose only content is a count you can already see is a card that earns nothing.)
     2. Your growth — the four dimension rings (GrowthPanel's compass). Each ring OPENS its
        Mastery Engine tab; "Details" expands that dimension in the ledger further down.
     3. "My work" — the three questions you open this page to answer (open / overdue / waiting on
        me) plus the next five cards. The board itself left for /tasks on 2026-08-03 (decision D7),
        so this strip links INTO it rather than duplicating it.
     4. The growth ledger — pace band, per-dimension details, mentor library (GrowthPanel again).
     5. Across Agora — Team progress (teamgrowth.js) first, then attendance KPIs, the clock-in
        trend, late list and handovers. Admins only, and last, because it's the one block that
        isn't about the person reading it. Team progress is also the page-wide people SCOPE
        control: selecting there re-renders everything under it through applyScope(). */
window.pageInit = async (S) => {
  const view = S.view();
  // Loading state so the page shows its shape immediately instead of a blank flash.
  view.innerHTML = `
    <div class="skeleton skel-line" style="height:28px;width:min(280px,60%);margin-bottom:22px"></div>
    <div class="skeleton skel-card" style="height:170px;margin-bottom:22px"></div>
    <div class="skeleton skel-card" style="height:260px"></div>`;
  const d = await S.api("/api/dashboard");
  const u = d.user;
  const greeting = new Date().getHours() < 12 ? "Good morning" : new Date().getHours() < 18 ? "Good afternoon" : "Good evening";
  S.qs("#top-sub").textContent = S.fmtDateFull(d.date + "T00:00:00+08:00");

  const kpi = (label, val, sub, cls, icon) => `
    <div class="kpi ${cls || ""}">
      <div class="k-label"><span class="k-ic">${S.ICON[icon] || S.ICON.grid}</span>${label}</div>
      <div class="k-val">${val}</div>
      <div class="k-sub">${sub || ""}</div>
    </div>`;

  // --- 1 · the day strip ---------------------------------------------------------------------
  // Two buttons where two cards used to be. Attendance re-renders in place after a punch (the
  // punch response carries the fresh summary + the remaining valid actions), so the whole strip
  // never needs a reload; the gym half is a plain link to the day's session.
  const me = d.me;
  const attStrip = (at, actions) => {
    const btn =
      (actions.includes("clock_in") ? `<button class="btn sm success" id="clock-in">${S.ICON.check}Clock In</button>` : "") +
      (actions.includes("clock_out") ? `<button class="btn sm danger" id="clock-out">${S.ICON.logout}Clock Out</button>` : "");
    const val = at
      ? `${S.statusPill(at.status)}<span class="ds-when">${S.fmtTime(at.clock_in)}${at.clock_out ? " – " + S.fmtTime(at.clock_out) : ""} · ${at.total_work_hours}h</span>`
      : `<span class="ds-when">Not clocked in yet</span>`;
    return `<span class="ds-ic">${S.ICON.clock}</span>
      <span class="ds-txt"><span class="ds-k">Attendance</span><span class="ds-v">${val}</span></span>
      ${btn}`;
  };
  const gymStrip = () => {
    const g = me.gym_today;
    const val = g
      ? `<span class="pill day ${g.day_type}">${g.day_type}</span>${S.statusPill(g.status)}`
      : `<span class="ds-when">No session logged</span>`;
    return `<a class="day-item" href="/gym" title="${g ? "Open today's session" : "Start a workout"}">
      <span class="ds-ic">${S.ICON.dumbbell}</span>
      <span class="ds-txt"><span class="ds-k">Gym</span><span class="ds-v">${val}</span></span>
      <span class="ds-go">${g ? "Open" : "Start"} &rarr;</span>
    </a>`;
  };

  let html = `<div class="pagehead">
      <div><h2>${greeting}, ${S.esc(u.name.split(" ")[0])}</h2>
        <div class="lead">${S.fmtDateFull(d.date + "T00:00:00+08:00")} · Here's what's happening across Agora today.</div></div>
      <div class="day-strip">
        <div class="day-item" id="att-card">${attStrip(me.attendance_today, me.attendance_actions || [])}</div>
        ${gymStrip()}
      </div>
    </div>`;

  // --- 2 · your growth (the compass) ----------------------------------------------------------
  html += `<div class="row between sect-head">
      <div class="section-label">${S.ICON.sparkle}Your growth</div>
      <span class="sub">Each ring is that tab's Mastery Engine score — open one to go straight in.</span>
    </div>
    <div id="dash-rings"></div>`;

  // --- 3 · my work -----------------------------------------------------------------------------
  // The Task Board left this page on 2026-08-03 (decision D7) — it has its own /tasks page and
  // sidebar item again. What stays is a "my work" strip: the three questions someone opens the
  // Overview to answer, each linking INTO the board rather than duplicating it.
  html += `<div id="dash-mywork"></div>`;

  // --- 4 · the growth ledger ------------------------------------------------------------------
  html += `<div id="dash-growth" style="margin-top:26px"></div>`;

  // --- 5 · across Agora (admins only) ---------------------------------------------------------
  // Team progress leads the block: it is both the collective view of everyone's growth AND the
  // control that scopes everything under it (see applyScope below). The KPI row, the clock-in
  // chart and the two lists are rendered by functions rather than baked into this string, because
  // all three re-render when that scope changes.
  if (d.is_admin) {
    html += `<div class="row between sect-head" style="margin-top:30px">
        <div class="section-label">${S.ICON.users}Across Agora</div>
        ${u.role === "super_admin" ? `<button class="btn sm ghost" id="run-daily" title="Recompute yesterday's attendance and send reminders now">${S.ICON.check}Run daily processing</button>` : ""}
      </div>
      <div id="dash-team"></div>
      <div class="kpis" id="dash-kpis" style="margin:18px 0"></div>
      <div class="card pad" id="chart-attendance" style="margin-bottom:18px"></div>
      <div class="grid" id="dash-admin-lists" style="grid-template-columns:1fr 1fr"></div>`;
  }

  view.innerHTML = html;

  // Clock In / Clock Out from the strip. The punch response carries the fresh summary +
  // remaining valid actions, so the item re-renders in place without a page reload.
  async function punch(action, extra) {
    try {
      const res = await S.api("/api/attendance/self-event", { method: "POST", body: { action, ...extra } });
      const late = res.late_status === "Late" ? ` · ${res.late_minutes}m late` : "";
      S.toast((action === "clock_in" ? "Clocked in" : "Clocked out") + late, "ok");
      S.qs("#att-card").innerHTML = attStrip(res.summary, res.scan.valid_actions);
      wireAttCard();
    } catch (e) { S.toast(e.detail || "Couldn't record the punch", "err"); }
  }
  function wireAttCard() {
    const ci = S.qs("#clock-in"), co = S.qs("#clock-out");
    if (ci) ci.onclick = () => { ci.disabled = true; punch("clock_in", {}); };
    if (co) co.onclick = () => {
      // Same optional handover note the kiosk asks for on the way out.
      const m = S.modal({
        title: "Clock out",
        body: `<label class="field"><span>Handover note (optional)</span>
          <textarea id="ho-note" placeholder="What should the next shift know?"></textarea></label>`,
        footer: `<button class="btn ghost" id="ho-cancel">Cancel</button>
          <button class="btn danger" id="ho-go">Clock Out</button>`,
      });
      S.qs("#ho-cancel").onclick = () => m.close();
      S.qs("#ho-go").onclick = () => {
        const note = S.qs("#ho-note").value.trim();
        m.close();
        punch("clock_out", { handover_note: note || null });
      };
    };
  }
  wireAttCard();

  // The page-wide people scope, set by the admin Team-progress table (see applyScope). An empty
  // `ids` means "everyone" and leaves every section exactly as it renders today, which is what a
  // non-admin — who never mounts that table — always sees.
  // `scoped` (not `ids.length`) is the flag every consumer branches on — "the filter matched
  // nobody" and "there is no filter" both carry an empty id list, and one means an empty board
  // while the other means the whole team.
  let scope = { ids: [], set: new Set(), order: [], label: "", rows: [], scoped: false };
  let insights = null;   // /api/insights, fetched once and re-filtered per scope

  // Mount the growth hub across its two hosts — the compass above "my work", the ledger below it.
  // Fail-soft: growth is a section of this page, not the page, so a bad /api/development never
  // costs anyone the rest of their Overview.
  if (window.GrowthPanel) {
    GrowthPanel.mount(S, S.qs("#dash-growth"), { ringsHost: S.qs("#dash-rings") })
      .catch((e) => S.toast(e.detail || "Couldn't load your growth", "err"));
  }

  // "My work": what is on me, what is late, what is waiting on my approval. The board itself lives
  // at /tasks (decision D7) — this strip links INTO it rather than duplicating it. Rendered after
  // the page paints so the greeting never waits on it, and it fails SILENTLY: a task-list hiccup
  // must not put an error toast over someone's morning attendance card.
  renderMyWork();
  async function renderMyWork() {
    // "Today" in Manila as an ISO date (en-CA -> YYYY-MM-DD), so "overdue" matches the SERVER's
    // Asia/Manila business rule rather than the viewer's timezone. Same one-liner taskboard.js uses;
    // deliberately duplicated rather than exported, since these two files share no module system.
    const PH_TODAY = new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Manila" });
    const box = S.qs("#dash-mywork");
    if (!box) return;
    // The vocabulary is what colours each row's stage rail. It is a SECOND, optional fetch: a
    // colourless rail is a cosmetic loss, a missing strip is not, so it degrades on its own.
    const [tasks, vocab] = await Promise.all([
      S.api("/api/tasks").catch(() => null),
      S.api("/api/vocab").catch(() => null),
    ]);
    if (!tasks) return;
    // 🔴 Stage, never the status LABEL. Statuses are renameable in Manage and a rename now ships in
    // the deploy (task_config.RENAMED_STATUSES), so any literal like "Blocked" silently stops
    // matching — that is exactly how the Monitor's workload bar lost ten parked cards on
    // 2026-08-04. The vocabulary names the stage; the class names only the colour.
    const STAGE_OF = Object.fromEntries(((vocab && vocab.task_status_meta) || []).map((s) => [s.name, s.stage]));
    // Same colour vocabulary as the Monitor's workload bar (.wl-bar) on purpose: one hue per stage
    // across the whole product, so a red rail means the same thing wherever you meet it.
    const STAGE_CLS = { todo: "s-todo", in_progress: "s-prog", revision: "s-rev", blocked: "s-block", completed: "s-done" };

    // The list is already scoped by the server (task_perms.can_view), so "mine" is a filter on top
    // of it, never a second source of truth. Atrium-owned cards have no assignee to be mine, so they
    // carry no `mine` flag and fall out here.
    //
    // 🔴 `t.mine` is the SERVER's answer (task_perms.is_assigned via task_card), not
    // `assigned_to_id === S.user.id`. That test was this strip's bug, fixed 2026-08-05: naming
    // somebody on a sub-task is delegation and puts the card on their board (AGENTS.md §5), so a card
    // led by a colleague with a step owned by YOU is on your Task Board — while this strip counted it
    // nowhere and said "0 open tasks · nothing on you right now" with the card one click away. Never
    // re-derive "assigned" here: there is exactly one definition of it and it lives on the server.
    const mine = tasks.filter((t) => t.mine && !t.archived);
    const open = mine.filter((t) => !t.completed_at);
    const overdue = open.filter((t) => t.due_date && t.due_date < PH_TODAY);
    // Waiting on ME: only a lead/manager sees these, and only for their own team — the same scope
    // task_perms.can_review enforces server-side (the buttons live in the board's panel).
    const canReview = S.can("account_manager")
      || (S.can("team_lead") && S.user.team_id != null);
    const toReview = !canReview ? [] : tasks.filter((t) => t.review_state === "pending"
      && (S.can("account_manager") || t.assigned_team_id === S.user.team_id));

    // Whole days between an ISO date and today, both read as UTC midnight so the arithmetic can't
    // drift by a day the way local-midnight Date parsing does.
    const dayDiff = (iso) => Math.round((Date.parse(iso + "T00:00:00Z") - Date.parse(PH_TODAY + "T00:00:00Z")) / 864e5);
    const plural = (n, w) => n + " " + w + (n === 1 ? "" : "s");

    // A tile is a DOOR into the board, not a KPI readout — hence the chevron and the sub-line that
    // says what the number MEANS. A count of zero renders quiet (is-quiet -> muted): "0 overdue" is
    // good news, and drawing it in the same 34px ink as real work makes the strip unreadable at a
    // glance, which is the only thing this strip is for. An empty `tone` keeps the tile's default
    // (green) — only the tiles whose meaning changes with the number name one.
    const tile = (n, label, sub, icon, tone, href) => `
      <a class="mw-tile ${n ? tone : "is-quiet"}" href="${href}">
        <span class="mw-head">
          <span class="mw-ic">${S.ICON[icon] || S.ICON.board}</span>
          <span class="mw-k">${label}</span>
          <span class="mw-go">${S.ICON.chev}</span>
        </span>
        <span class="mw-n">${n}</span>
        <span class="mw-s">${sub}</span>
      </a>`;

    // Sub-lines, in the order they stop being reassuring.
    const dueToday = open.filter((t) => t.due_date === PH_TODAY).length;
    const nextDue = open.filter((t) => t.due_date && t.due_date > PH_TODAY)
      .map((t) => t.due_date).sort()[0];
    const openSub = !open.length ? "nothing on you right now"
      : dueToday ? dueToday + " due today"
      : nextDue ? "next due " + S.fmtDate(nextDue + "T00:00:00+08:00")
      : "none of them dated";
    const worst = overdue.length ? Math.max(...overdue.map((t) => -dayDiff(t.due_date))) : 0;
    const lateSub = overdue.length ? "oldest " + plural(worst, "day") + " late" : "nothing is late";
    const revSub = toReview.length ? "ready for your call" : "nothing waiting";

    // "Up next" = soonest deadline first, undated last. The old strip showed the 5 newest, which is
    // the one ordering that answers no question anybody opens the Overview with.
    // Sorts as "9999-…" so an undated card lands after every dated one without a special case, and
    // never before them the way a bare null-vs-string comparison would.
    const dueKey = (t) => t.due_date || "9999-12-31";
    const upNext = open.slice().sort((a, b) => {
      if (dueKey(a) !== dueKey(b)) return dueKey(a) < dueKey(b) ? -1 : 1;
      return b.id - a.id;
    }).slice(0, 5);

    const dueChip = (iso) => {
      if (!iso) return '<span class="mw-due none">no date</span>';
      const n = dayDiff(iso);
      const txt = n < 0 ? plural(-n, "day") + " late" : n === 0 ? "Today"
        : n === 1 ? "Tomorrow" : S.fmtDate(iso + "T00:00:00+08:00");
      return `<span class="mw-due ${n < 0 ? "late" : n === 0 ? "today" : ""}">${txt}</span>`;
    };
    // Two states that change what you should DO with the card, so they earn a pill; everything else
    // about a task belongs in the drawer, not in a five-row shortlist.
    //
    // The third pill is what keeps the widened "mine" honest. A card whose Assigned-to names a
    // COLLEAGUE is here because you own part of its breakdown — say so, or the row reads as the strip
    // listing somebody else's work (which is the bug directly above, wearing the opposite face).
    const stepPill = (t) => (t.assigned_to_id !== S.user.id && t.my_slots
      ? `<span class="pill blue" title="${t.assignee ? S.esc(t.assignee.name) + " leads this card" : "Nobody leads this card"}">${plural(t.my_slots, "step")} on you</span>`
      : "");
    const flags = (t) => (t.on_hold ? '<span class="pill grey">Paused</span>' : "")
      + (t.review_state === "pending" ? '<span class="pill amber">In review</span>' : "")
      + stepPill(t);

    const row = (t) => `
      <a class="mw-row" href="/tasks?open=${t.id}">
        <i class="mw-stage ${STAGE_CLS[STAGE_OF[t.status]] || "s-todo"}" title="${S.esc(t.status)}"></i>
        <span class="mw-title">${S.esc(t.title)}</span>
        <span class="mw-meta">${flags(t)}<span class="mw-st">${S.esc(t.status)}</span>${dueChip(t.due_date)}</span>
        <span class="mw-chev">${S.ICON.chev}</span>
      </a>`;

    box.innerHTML = `
      <div class="row between sect-head">
        <div class="section-label">${S.ICON.board}My work</div>
        <span class="sub">Everything else is on the <a href="/tasks">Task Board</a>.</span>
      </div>
      <div class="mw-tiles">
        ${tile(open.length, "Open tasks", openSub, "board", "", "/tasks")}
        ${tile(overdue.length, "Overdue", lateSub, "clock", "is-warn", "/tasks")}
        ${canReview ? tile(toReview.length, "Waiting on me", revSub, "inbox", "is-info", "/tasks") : ""}
      </div>
      <div class="card mw-list">
        <div class="card-head">
          <h3>Up next</h3>
          <a class="mw-open" href="/tasks">Open the board${S.ICON.chev}</a>
        </div>
        ${upNext.length
          ? upNext.map(row).join("")
            + (open.length > upNext.length
              ? `<a class="mw-more" href="/tasks">${plural(open.length - upNext.length, "more task")} on the board${S.ICON.chev}</a>`
              : "")
          : `<div class="mw-none">${S.ICON.check}
              <div>You're clear. Nothing is assigned to you right now.</div>
              <a class="btn sm ghost" href="/tasks">Pick something up${S.ICON.chev}</a>
            </div>`}
      </div>`;
  }

  // --- the page-wide people scope ---------------------------------------------------------------
  // Team progress owns the selection; this owns what the rest of the page does with it. Everything
  // below re-renders from data already in hand — no refetch, so scoping is instant and can't fail.
  //
  // The Task Board used to be re-scoped from here as well; it left this page on 2026-08-03
  // (decision D7) and lives at /tasks, so what scopes now is the admin block: the KPI row, the two
  // lists and the clock-in chart. The "my work" strip above is deliberately NOT scoped — it answers
  // "what is on ME", which no selection of other people can change.
  function applyScope(next) {
    scope = {
      ids: next.ids || [],
      set: new Set(next.ids || []),
      order: next.order || [],
      label: next.label || "",
      rows: next.rows || [],
      // Carried through from teamgrowth.js's scope(), never re-derived from `ids.length`: a filter
      // that matched nobody and no filter at all are both an empty id list, and only this flag
      // tells them apart. Dropping it here reads as "unscoped", which silently ignores every
      // selection the admin makes.
      scoped: !!next.scoped,
    };
    renderKpis();
    renderAdminLists();
    renderTrend();
  }

  const inScope = (userId) => !scope.scoped || scope.set.has(userId);

  /** KPIs for the current scope. Unscoped, these are the SERVER's counts over everyone — the
   *  authoritative numbers. Scoped, they're recounted from the per-person facts Team progress
   *  already fetched (present/late/gym), so the tiles and the table can never disagree. */
  function renderKpis() {
    const host = S.qs("#dash-kpis");
    if (!host) return;
    let k = d.kpis;
    let note = "staff";
    if (scope.scoped) {
      const sel = scope.rows.filter((r) => scope.set.has(r.user.id));
      k = {
        headcount: sel.length,
        present_today: sel.filter((r) => r.present_today).length,
        late_today: sel.filter((r) => r.late_today).length,
        gym_completed_week: sel.reduce((a, r) => a + (r.gym_week || 0), 0),
      };
      note = "selected";
    }
    // Presence-focused on purpose: no absent/task/approval counts here (2026-07-27).
    // Tasks live on the board above; approvals have their own page + the bell.
    host.innerHTML =
      kpi("Present today", k.present_today, `of ${k.headcount} ${note}`, "", "clock")
      + kpi("Late today", k.late_today, "clocked in late", k.late_today ? "warn" : "", "coffee")
      + kpi("Gym this week", k.gym_completed_week, "sessions completed", "", "dumbbell");
  }

  function renderAdminLists() {
    const host = S.qs("#dash-admin-lists");
    if (!host) return;
    const late = (d.late_today_list || []).filter((s) => inScope(s.user.id));
    const handovers = (d.handovers || []).filter((h) => inScope(h.user.id));
    const scoped = scope.scoped ? " in this selection" : "";
    host.innerHTML = `
      <div class="card"><div class="card-head"><h3>Late today</h3><span class="chip">${late.length}</span></div>
        <div class="card-body">${late.length ? late.map((s) => `
          <div class="row between" style="padding:7px 0;border-bottom:1px solid var(--line)">
            <div class="t-name">${S.avatar(s.user, "sm")}<span>${S.esc(s.user.name)}</span></div>
            <div>${S.statusPill("Late")} <span class="sub">${S.fmtTime(s.clock_in)}</span></div>
          </div>`).join("") : `<div class="empty">Everyone on time${scoped}.</div>`}</div></div>

      <div class="card"><div class="card-head"><h3>Handover notes</h3><span class="chip">yesterday</span></div>
        <div class="card-body">${handovers.length ? handovers.map((h) => `
          <div style="padding:9px 0;border-bottom:1px solid var(--line)">
            <div class="t-name" style="margin-bottom:3px">${S.avatar(h.user, "sm")}<strong>${S.esc(h.user.name)}</strong></div>
            <div class="sub" style="font-size:13px">${S.esc(h.note)}</div></div>`).join("")
          : `<div class="empty">No handover notes${scoped}.</div>`}</div></div>`;
  }

  /** Clock-in chart. Each day carries its full clocked-in roster, so a scoped chart is recounted
   *  from that roster rather than re-requested — the same 14 days, just the selected people. */
  function renderTrend() {
    const host = S.qs("#chart-attendance");
    if (!host || !insights || !window.SentinelCharts) return;
    const trend = (insights.attendance_trend || []).map((day) => {
      if (!scope.scoped) return day;
      const people = (day.people || []).filter((p) => p.user && scope.set.has(p.user.id));
      return {
        ...day,
        people,
        ontime: people.filter((p) => p.status !== "Late").length,
        late: people.filter((p) => p.status === "Late").length,
      };
    });
    SentinelCharts.attendanceTrend(host, trend, (day) => {
      const rows = (day.people || []).map((p) => `
        <div class="row between" style="padding:8px 0;border-bottom:1px solid var(--line)">
          <div class="t-name">${S.avatar(p.user, "sm")}<span>${S.esc(p.user.name)}</span></div>
          <div>${S.statusPill(p.status)} <span class="sub">${S.fmtTime(p.clock_in)}</span></div>
        </div>`).join("");
      S.modal({
        title: `Clocked in · ${S.fmtDateFull(day.date + "T00:00:00+08:00")}`,
        body: rows
          ? `<div class="sub" style="margin-bottom:6px">${day.people.length} ${day.people.length === 1 ? "person" : "people"}, earliest first</div>${rows}`
          : '<div class="empty">No one clocked in.</div>',
      });
    });
  }

  if (d.is_admin) {
    renderKpis();
    renderAdminLists();

    // Team progress — everyone's growth, and the control that scopes this whole page.
    // Fail-soft like every other section: a broken /api/development/team must not cost an admin
    // their KPIs, their chart or their board.
    if (window.TeamGrowth) {
      TeamGrowth.mount(S, S.qs("#dash-team"), { onScope: applyScope })
        .catch((e) => {
          S.qs("#dash-team").innerHTML =
            `<div class="empty card pad">${S.esc(e.detail || "Couldn't load team progress.")}</div>`;
        });
    }

    // Clock-in chart — fetched after paint so the page never blocks on it. Clicking a day opens
    // the roster of who clocked in (the data rides along in the trend).
    try {
      insights = await S.api("/api/insights");
      renderTrend();
    } catch (e) { /* charts are non-critical */ }
  }

  const rb = S.qs("#run-daily");
  if (rb) rb.onclick = async () => {
    rb.disabled = true; const orig = rb.innerHTML; rb.textContent = "Processing…";
    try {
      const r = await S.api("/api/cron/daily", { method: "POST" });
      const a = r.attendance || {}, m = r.reminders || {};
      S.toast(`Processed ${a.date}: ${a.absent || 0} absent, ${a.on_leave || 0} on leave, ${a.missing_clockout || 0} missing clock-out · ${m.overdue_notified || 0} overdue nudges`, "ok");
    } catch (e) { S.toast(e.detail || "Couldn't run daily processing", "err"); }
    finally { rb.disabled = false; rb.innerHTML = orig; }
  };
};

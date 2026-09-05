/* MY ACCOUNTS — the account manager's landing (2026-09-02). Mounted by dashboard.js for
   account_manager, between the greeting and the rest of the Overview.

   Order is the AM's morning: NEEDS YOUR ACTION first (reviews, decisions parked on you, client asks
   — each one is a specialist who can't move until you do), then the accounts table with the health
   REASON in words, then today's and tomorrow's commitments, then the CAPACITY of your team — the
   same table the COO's Operations landing shows, narrowed server-side to your departments plus
   whoever holds open work on your accounts (`/api/ops/capacity`, 2026-09-03; it replaced a
   people-on-my-accounts list that had no "Now", no hours and no week). */
window.AccountsPage = {
  async mount(S, root) {
    const U = window.OpsUI;
    root.innerHTML = `<div class="skeleton skel-card" style="height:220px;margin-bottom:18px"></div>`;
    const meta = await U.meta(S);
    const PH = U.PH_TODAY();
    const tomorrow = new Date(Date.parse(PH + "T00:00:00Z") + 864e5).toISOString().slice(0, 10);
    const canReq = S.hasCap("tasks.requests");
    const [clients, tasks, requests, cal, capacity] = await Promise.all([
      S.api("/api/ops/clients").catch(() => null),
      S.api("/api/tasks").catch(() => []),
      canReq ? S.api("/api/tasks/requests?status=pending").catch(() => []) : Promise.resolve([]),
      S.api(`/api/ops/calendar?from=${PH}&to=${tomorrow}`).catch(() => ({ events: [] })),
      S.api("/api/ops/capacity").catch(() => null),
    ]);
    const rows = (clients && clients.clients) || [];
    const me = S.user.id;
    const myRows = rows.filter((r) => r.account_manager_id === me);
    const shown = myRows.length ? myRows : rows;
    const open = tasks.filter((t) => !t.archived && !U.isDone(S, t));

    // Needs your action: reviews waiting, decisions parked on the AM, client asks from Atrium.
    const reviews = open.filter((t) => t.review_state === "pending");
    const decisions = open.filter((t) => U.isParked(S, t) && t.hold_kind === "am_decision");
    const asks = (Array.isArray(requests) ? requests : []).map((r) => `
      <div class="os-row static">
        <span class="os-main"><span class="os-title">“${S.esc(r.title || "")}”</span>
        <span class="os-meta"><b>${S.esc(r.client_name || r.client_key || "A client")}</b> · client ask from Atrium${r.requester_name ? ` · ${S.esc(r.requester_name)}` : ""}</span></span>
        <span class="os-right"><a class="btn sm primary" href="/tasks?requests=1">Review</a></span>
      </div>`);
    const needs = [...reviews.map((t) => U.taskRow(S, t, { who: true })),
                   ...decisions.map((t) => U.taskRow(S, t, { who: true })), ...asks];

    // Commitments: due + recurring events for today and tomorrow, from the calendar projection.
    const ev = ((cal && cal.events) || []).filter((e) => e.kind === "due" || e.kind === "recurring");
    const commitments = ev.slice(0, 8).map((e) => `
      <a class="os-row" href="${S.esc(e.href || "/tasks")}">
        <span class="os-main"><span class="os-title">${S.esc(e.title)}</span>
        <span class="os-meta"><b>${S.esc(e.client || "Internal")}</b>${e.assignee ? ` · ${S.esc(e.assignee.name.split(" ")[0])}` : ""}${e.kind === "recurring" ? " · recurring" : ""}</span></span>
        <span class="os-right">${U.dueChip(e.date, { parked: e.parked })}<span class="os-chev">${S.ICON.chev}</span></span>
      </a>`);

    // Capacity of my team: rows already narrowed by the server (operations.capacity_scope), drawn
    // by the same OpsUI.capacityTable the COO sees so the two never disagree about a person.
    const capRows = (capacity && capacity.capacity) || [];
    const capacityHtml = capacity
      ? U.capacityTable(S, capRows, { empty: "Nobody on your team has open work." })
      : `<div class="card"><div class="os-empty">Couldn't load your team's capacity.</div></div>`;

    const red = shown.filter((r) => r.health === "red").length, amber = shown.filter((r) => r.health === "amber").length;
    root.innerHTML = `
      <div class="os-lead">${shown.length} account${shown.length === 1 ? "" : "s"} · <b class="${red ? "bad" : ""}">${red} red</b>, ${amber} amber · <b>${needs.length} thing${needs.length === 1 ? "" : "s"} need your action</b> before anyone else can move.${myRows.length ? "" : rows.length ? ` <span class="muted">No client names you as its account manager yet — showing every account.</span>` : ""}</div>
      ${U.head("Needs your action", "reviews, decisions, client asks")}
      <div class="card">${U.list(needs, "Nothing is waiting on you.")}</div>
      <div class="os-sect">
        ${U.head("My accounts", `<a href="/clients" title="${S.esc(meta.health_rule || "")}">Health rule →</a>`)}
        <div id="acct-table">${U.clientsTable(S, shown)}</div>
      </div>
      <div class="os-sect os-two">
        <div>${U.head("Commitments · today and tomorrow")}<div class="card">${U.list(commitments, "Nothing dated in the next two days.")}</div></div>
      </div>
      <div class="os-sect">
        ${U.head("Capacity · my team", U.capacityHint(capRows))}
        ${capacityHtml}
      </div>`;
    U.wireClientRows(root);
  },
};

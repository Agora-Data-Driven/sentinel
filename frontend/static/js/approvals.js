/* Approvals — one inbox for everything a manager signs off on: attendance-correction requests and
   leave requests, previously split across the Time and Leave pages. Each row carries a type pill and
   routes Approve/Reject to the matching endpoint. Read from the two existing list APIs; no new backend. */
window.pageInit = async (S) => {
  const view = S.view();
  if (!S.can("team_lead")) {
    view.innerHTML = `<div class="empty card pad" style="margin-top:30px">Approvals are for team leads and above.</div>`;
    return;
  }

  view.innerHTML = `<div class="pagehead"><div><h2>Approvals</h2>
      <div class="lead">Pending attendance corrections and leave requests, in one queue.</div></div>
      <div class="seg" id="filter">
        <button class="on" data-f="all">All</button>
        <button data-f="time">Time</button>
        <button data-f="leave">Leave</button>
      </div></div>
    <div id="inbox"></div>`;

  let filter = "all";
  S.qsa("#filter button").forEach((b) => b.onclick = () => {
    S.qsa("#filter button").forEach((x) => x.classList.remove("on")); b.classList.add("on");
    filter = b.dataset.f; render();
  });

  // Normalise both request shapes into one row model. Each endpoint is fetched independently so a
  // failure in one (or a role that can't see one) still shows the other.
  async function fetchAll() {
    const [time, leave] = await Promise.all([
      S.api("/api/attendance/requests?status=Pending").catch(() => []),
      S.api("/api/leave/requests?status=Pending").catch(() => []),
    ]);
    const items = [];
    for (const r of time) items.push({
      kind: "time", id: r.id, user: r.user, badge: r.request_type, badgeClass: "blue",
      detail: `${S.fmtDate(r.date + "T00:00:00+08:00")} · ${S.esc(r.reason || "")}`,
      extra: (r.old_value || r.new_value) ? `${S.esc(r.old_value || "—")} → <strong>${S.esc(r.new_value || "—")}</strong>` : "",
    });
    for (const r of leave) items.push({
      kind: "leave", id: r.id, user: r.user, badge: r.leave_type, badgeClass: "violet",
      detail: `${S.fmtDate(r.start_date + "T00:00:00+08:00")} – ${S.fmtDate(r.end_date + "T00:00:00+08:00")} · ${r.total_days} day(s) · ${S.esc(r.reason || "")}`,
      extra: "",
    });
    return items;
  }

  let all = [];
  async function load() {
    S.qs("#inbox").innerHTML = `<div class="card pad">${S.skeleton({ rows: 5 })}</div>`;
    all = await fetchAll();
    render();
  }

  function render() {
    const rows = all.filter((i) => filter === "all" || i.kind === filter);
    const typePill = (i) => `<span class="pill ${i.badgeClass}">${i.kind === "time" ? "Time" : "Leave"} · ${S.esc(i.badge || "")}</span>`;
    S.qs("#inbox").innerHTML = `<div class="card"><div class="card-head"><h3>Pending</h3><span class="chip">${rows.length}</span></div>
      <div class="card-body">${rows.length ? rows.map((i) => `
        <div class="row between" style="padding:12px 0;border-bottom:1px solid var(--line);gap:12px;flex-wrap:wrap">
          <div style="min-width:240px"><div class="t-name" style="margin-bottom:4px">${S.avatar(i.user, "sm")}<strong>${S.esc(i.user.name)}</strong>
            ${typePill(i)}</div>
            <div class="sub">${i.detail}</div>
            ${i.extra ? `<div class="sub" style="font-size:12px">${i.extra}</div>` : ""}</div>
          <div class="row"><button class="btn sm success" data-ok="${i.kind}:${i.id}">Approve</button>
            <button class="btn sm ghost" data-no="${i.kind}:${i.id}">Reject</button></div>
        </div>`).join("") : '<div class="empty">Nothing to approve.</div>'}</div></div>`;
    S.qsa("[data-ok]").forEach((b) => b.onclick = () => decide(b.dataset.ok, "Approved"));
    S.qsa("[data-no]").forEach((b) => b.onclick = () => decide(b.dataset.no, "Rejected"));
  }

  async function decide(token, status) {
    const [kind, id] = token.split(":");
    const url = kind === "time" ? `/api/attendance/request/${id}` : `/api/leave/request/${id}`;
    try {
      await S.api(url, { method: "PATCH", body: { status } });
      S.toast(`${kind === "time" ? "Request" : "Leave"} ${status.toLowerCase()}`, "ok");
      load();
    } catch (e) { S.toast(e.detail || "Couldn't update", "err"); }
  }

  await load();
};

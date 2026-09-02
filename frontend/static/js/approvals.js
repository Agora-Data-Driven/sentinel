/* Approvals — one inbox for everything a manager signs off on: attendance-correction requests and
   leave requests, previously split across the Time and Leave pages. Each row carries a type pill and
   routes Approve/Reject to the matching endpoint. Read from the two existing list APIs; no new backend. */
window.pageInit = async (S) => {
  const view = S.view();
  if (!S.can("team_lead")) {
    view.innerHTML = `<div class="empty card pad" style="margin-top:30px">Approvals are for department heads and above.</div>`;
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
  // 🔴 A FAILED HALF OF THIS INBOX MUST NOT LOOK LIKE AN EMPTY ONE (2026-08-17).
  // Both calls used to end in `.catch(() => [])`, so a 500 on either endpoint rendered a SHORTER
  // pending list with no warning — an approver read "Nothing to approve", believed they were caught
  // up, and left real requests sitting. This is the same failure the Watcher bridge's empty state
  // hid twice (AGENTS.md §5): degrading a read to `[]` is only safe when absence and failure mean
  // the same thing to the reader, and on an ACTION QUEUE they are opposites.
  // Still fail-soft — one broken endpoint must not cost you the other's requests — but the failure
  // is now reported, so the count is never quietly wrong.
  //
  // 🔴 A 401/403 IS NOT A FAILURE HERE — it is this page's normal answer for a role that does not
  // hold that queue (the comment above has always said so). Reporting "Leave requests could not be
  // loaded" to somebody who is not allowed to see leave requests is a false alarm on every single
  // load, and a warning that cries wolf on every load is one nobody reads on the day it is true.
  // So: an AUTHORISATION answer degrades silently to `[]` exactly as before; only a real fault
  // (500, network, timeout) reaches `failed`.
  const failed = [];
  async function fetchAll() {
    failed.length = 0;
    const pull = async (url, label) => {
      try { return await S.api(url); }
      catch (e) {
        if (e.status !== 401 && e.status !== 403) failed.push(label);
        return [];
      }
    };
    const [time, leave] = await Promise.all([
      pull("/api/attendance/requests?status=Pending", "Time"),
      pull("/api/leave/requests?status=Pending", "Leave"),
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
    // The banner carries the reason the count below it may be short. It sits INSIDE the card and
    // above the rows, so it cannot be scrolled away from the number it qualifies.
    const warn = failed.length
      ? `<div class="notice warn"><b>This list is incomplete.</b>
           ${S.esc(failed.join(" and "))} request${failed.length > 1 ? "s" : ""} could not be loaded.
           <button type="button" class="btn sm ghost" id="ap-retry" style="margin-left:6px">Try again</button>
         </div>`
      : "";
    S.qs("#inbox").innerHTML = `<div class="card"><div class="card-head"><h3>Pending</h3><span class="chip">${rows.length}</span></div>
      <div class="card-body">${warn}${rows.length ? rows.map((i) => `
        <div class="row between" style="padding:12px 0;border-bottom:1px solid var(--line);gap:12px;flex-wrap:wrap">
          <div style="min-width:240px"><div class="t-name" style="margin-bottom:4px">${S.avatar(i.user, "sm")}<strong>${S.esc(i.user.name)}</strong>
            ${typePill(i)}</div>
            <div class="sub">${i.detail}</div>
            ${i.extra ? `<div class="sub" style="font-size:12px">${i.extra}</div>` : ""}</div>
          <div class="row"><button class="btn sm success" data-ok="${i.kind}:${i.id}">Approve</button>
            <button class="btn sm ghost" data-no="${i.kind}:${i.id}">Reject</button></div>
        </div>`).join("") : `<div class="empty">${failed.length
          // "Nothing to approve" is a claim this page cannot make while a source is down.
          ? "Nothing loaded." : "Nothing to approve."}</div>`}</div></div>`;
    S.qsa("#inbox [data-ok]").forEach((b) => b.onclick = () => decide(b.dataset.ok, "Approved"));
    S.qsa("#inbox [data-no]").forEach((b) => b.onclick = () => decide(b.dataset.no, "Rejected"));
    const rb = S.qs("#ap-retry"); if (rb) rb.onclick = () => load();
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

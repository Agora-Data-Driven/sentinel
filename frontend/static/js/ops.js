/* OPERATIONS — the COO's landing (2026-09-02). Mounted by dashboard.js for admin / super_admin /
   viewer, between the greeting and the existing "Across Agora" block.

   The exception list leads: one problem, one owner, one action per line. Everything not on it is
   running normally by construction (services/operations.py). Then a stats strip, client health and
   capacity — the two tables the exceptions were derived from, for the reader who wants to check. */
window.OpsPage = {
  async mount(S, root) {
    const U = window.OpsUI;
    root.innerHTML = `<div class="skeleton skel-card" style="height:260px;margin-bottom:18px"></div>`;
    await U.meta(S);
    let d;
    try { d = await S.api("/api/ops/exceptions"); }
    catch (e) {
      root.innerHTML = `<div class="notice warn"><b>Couldn't load Operations.</b> ${S.esc(e.detail || "The service didn't answer.")}</div>`;
      return;
    }
    const st = d.stats || {};
    const exc = (d.exceptions || []).map((e) => `
      <div class="os-row static exc">
        <i class="os-sev ${e.severity}"></i>
        <span class="os-main"><span class="os-title">${S.esc(e.title)}</span><span class="os-meta wrap">${e.detail}</span></span>
        <span class="os-right">${e.owner ? S.avatar(e.owner, "sm") : ""}<a class="btn sm" href="${S.esc(e.href || "#")}">${S.esc(e.action || "Open")}</a></span>
      </div>`);
    const stat = (k, v, s, cls) => `<div class="os-stat"><div class="k">${k}</div><div class="v ${cls || ""}">${v}</div><div class="s">${s}</div></div>`;
    const clients = (d.clients || []).map((r) => `<tr class="click" data-client="${r.client.id}">
      <td><b>${S.esc(r.client.name)}</b></td><td>${U.healthPill(r.health)}</td>
      <td>${r.account_manager ? S.avatar(r.account_manager, "xs") : '<span class="muted">—</span>'}</td>
      <td class="n">${r.open}</td><td class="n ${r.overdue ? "bad" : "zero"}">${r.overdue}</td><td class="n ${r.blocked ? "warn" : "zero"}">${r.blocked}</td><td class="n ${r.reviews ? "warn" : "zero"}">${r.reviews}</td></tr>`);
    // The capacity table is drawn by OpsUI.capacityTable — the AM's landing shows the same table,
    // narrowed to their team, and one drawing keeps the two identical (2026-09-03).
    root.innerHTML = `
      <div class="os-lead"><b>${exc.length} thing${exc.length === 1 ? " needs" : "s need"} attention.</b> Everything not listed here is running normally — leave it alone.</div>
      <div class="card">${U.list(exc, "Nothing needs management attention right now.")}</div>
      <div class="card os-stats">
        ${stat("Clients", `${st.clients_red || 0} red`, `${st.clients_amber || 0} amber · ${st.clients_green || 0} green`, st.clients_red ? "bad" : "")}
        ${stat("Overdue", st.overdue || 0, st.overdue ? `oldest ${st.oldest_overdue_days} day${st.oldest_overdue_days === 1 ? "" : "s"}` : "nothing late", st.overdue ? "bad" : "")}
        ${stat("Blocked", st.blocked || 0, `${st.blocked_on_client || 0} on clients · ${st.blocked_on_us || 0} on us`)}
        ${stat("Reviews waiting", st.reviews || 0, st.reviews_stale ? `${st.reviews_stale} over ${(d.thresholds || {}).review_stale_hours || 24}h` : "none stale", st.reviews_stale ? "warn" : "")}
        ${stat("Heavy", st.heavy || 0, "vs the team's typical load", st.heavy ? "bad" : "")}
      </div>
      <div class="os-two even os-sect">
        <div>${U.head("Client health", `<a href="/clients">All clients →</a>`)}
          <div class="card table-wrap"><table class="os-tbl"><thead><tr><th>Client</th><th>Health</th><th>AM</th><th class="n">Open</th><th class="n">Late</th><th class="n">Blocked</th><th class="n">Rev.</th></tr></thead><tbody>${clients.join("") || '<tr><td colspan="7" class="os-empty">No active clients.</td></tr>'}</tbody></table></div></div>
        <div>${U.head("Capacity", U.capacityHint(d.capacity))}${U.capacityTable(S, d.capacity, { empty: "No active staff." })}</div>
      </div>`;
    U.wireClientRows(root);
  },
};

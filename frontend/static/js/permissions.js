/* Permissions — the role x capability grid a Super Admin edits.
   Reads GET /api/permissions, saves the CHANGED cells with PUT, re-renders from the response.

   Two things about this file are deliberate and easy to undo by accident:

   1. It renders from the server's payload and NOTHING else. Every cell's `editable` flag and the
      sentence explaining a disabled box come from `capabilities.is_grantable` — re-deriving either
      here would be a second copy of the invariants (no viewer writes, no editing Super Admin, no
      touching a locked capability), and a UI copy of a server rule is how the Team Lead dead-button
      bug shipped (AGENTS.md §5).
   2. Saving sends only the cells that actually moved, and re-renders from `res.matrix` — so a change
      the server REFUSED springs visibly back with its reason instead of appearing to have saved.

   🔴 NO BACKTICKS inside any template literal in this file (including comments inside one) — see
   mastery-engine AGENTS.md §7 / the task-board incident: it terminates the literal and the page
   renders nothing, and `node --check` cannot see it. */
window.pageInit = async (S) => {
  const view = S.view();
  if (!S.hasCap("permissions.view")) {
    view.innerHTML = '<div class="empty card pad" style="margin-top:30px">You don\'t have access to '
      + 'Permissions.</div>';
    return;
  }
  const canEdit = S.hasCap("permissions.manage");

  let data = null;
  // Pending edits, keyed "role|capability" so a role or capability containing a dot can never
  // collide with another key.
  let pending = new Map();
  const cellKey = (role, cap) => role + "|" + cap;

  view.innerHTML = '<div class="pagehead"><div><h2>Permissions</h2>'
    + '<div class="lead">What each role may do. Tick a box to grant a capability, untick to revoke — '
    + 'every change is audit-logged.</div></div></div>'
    + '<div id="pm-body"><div class="skeleton" style="height:320px"></div></div>';

  async function load() {
    const body = S.qs("#pm-body");
    try { data = await S.api("/api/permissions"); }
    catch (e) { S.loadErr(body, e, load); return; }
    pending = new Map();
    render();
  }

  // Current on/off for a cell: the pending edit if there is one, else the server's answer.
  function stateOf(cap, role) {
    const p = pending.get(cellKey(role, cap.key));
    return p === undefined ? cap.roles[role].allowed : p;
  }

  function render() {
    const roles = data.roles;
    const dirty = pending.size;
    const strip = '<div class="mgr-strip">'
      + '<span>' + data.override_count + " change"
      + (data.override_count === 1 ? "" : "s")
      + ' from the built-in defaults</span>'
      + '<span class="muted" style="font-size:12px">Capabilities are cached for up to '
      + data.cache_seconds + 's, so a revoke can take that long to reach every server.</span>'
      + (canEdit
        ? '<button class="btn sm ghost" id="pm-reset" title="Delete every override and return every '
          + 'role to the capabilities the app ships with.">Reset to defaults</button>'
        : '')
      + "</div>";

    const head = '<thead><tr><th style="min-width:280px">Capability</th>'
      + roles.map((r) => '<th style="text-align:center;white-space:nowrap">' + S.esc(r.label)
        + (r.immutable
          ? ' <span class="pill grey" title="Super Admin always holds every capability — that is '
            + 'what keeps this console recoverable.">fixed</span>'
          : "")
        + "</th>").join("")
      + "</tr></thead>";

    let rowsHtml = "";
    for (const group of data.groups) {
      rowsHtml += '<tr><td colspan="' + (roles.length + 1)
        + '" class="section-label" style="padding-top:14px">' + S.esc(group) + "</td></tr>";
      for (const cap of data.capabilities.filter((c) => c.group === group)) {
        rowsHtml += "<tr><td><div>" + S.esc(cap.label)
          + (cap.locked
            ? ' <span class="pill amber" title="Fixed in code: this one grants privilege escalation, '
              + 'or grants access to this page.">locked</span>'
              + " " + S.ICON.lock
            : "")
          + (cap.write ? "" : ' <span class="pill grey" title="A read. Safe to give the read-only '
              + 'Viewer seat.">read</span>')
          + '</div><div class="muted" style="font-size:12px">' + S.esc(cap.description)
          + "</div></td>";
        for (const r of roles) {
          const info = cap.roles[r.value];
          const on = stateOf(cap, r.value);
          const moved = pending.has(cellKey(r.value, cap.key));
          const offDefault = on !== info.default;
          // A disabled box always carries the server's sentence, so "why won't this tick?" is
          // answered in place rather than by a silent no-op.
          const title = info.editable
            ? (offDefault ? "Changed from the built-in default (" + (info.default ? "on" : "off") + ")"
                          : "The built-in default")
            : S.esc(info.reason || "");
          const attrs = 'type="checkbox" style="width:auto"'
            + ' data-role="' + S.esc(r.value) + '" data-cap="' + S.esc(cap.key) + '"'
            + (on ? " checked" : "")
            + (info.editable && canEdit ? "" : " disabled");
          rowsHtml += '<td style="text-align:center" title="' + title + '">'
            + "<input " + attrs + ">"
            + (moved ? '<span class="dot" style="background:var(--warn,#f59e0b)"></span>'
                     : (offDefault ? '<span class="dot" style="background:var(--line)"></span>' : ""))
            + "</td>";
        }
        rowsHtml += "</tr>";
      }
    }

    const footer = canEdit
      ? '<div class="row between" style="margin-top:14px">'
        + '<div class="muted" id="pm-count">' + (dirty ? dirty + " unsaved change" + (dirty === 1 ? "" : "s") : "No unsaved changes")
        + "</div>"
        + '<div class="row" style="gap:8px">'
        + '<button class="btn ghost" id="pm-cancel"' + (dirty ? "" : " disabled") + ">Discard</button>"
        + '<button class="btn primary" id="pm-save"' + (dirty ? "" : " disabled") + ">Save changes</button>"
        + "</div></div>"
      : '<div class="muted" style="margin-top:14px">You can see this grid but not change it — '
        + "editing needs the Edit-the-permissions-matrix capability.</div>";

    S.qs("#pm-body").innerHTML = strip
      + '<div class="table-wrap" style="overflow-x:auto"><table>' + head
      + "<tbody>" + rowsHtml + "</tbody></table></div>" + footer;
    wire();
  }

  function wire() {
    S.qsa('#pm-body input[type="checkbox"]:not([disabled])').forEach((box) => {
      box.onchange = () => {
        const role = box.dataset.role;
        const capKey = box.dataset.cap;
        const cap = data.capabilities.find((c) => c.key === capKey);
        const key = cellKey(role, capKey);
        // Back to the server's value = not a change at all, so the key is dropped rather than
        // stored as a no-op the save would then have to filter out.
        if (box.checked === cap.roles[role].allowed) pending.delete(key);
        else pending.set(key, box.checked);
        render();
      };
    });
    const cancel = S.qs("#pm-cancel");
    if (cancel) cancel.onclick = () => { pending = new Map(); render(); };
    const save = S.qs("#pm-save");
    if (save) save.onclick = doSave;
    const reset = S.qs("#pm-reset");
    if (reset) reset.onclick = doReset;
  }

  async function doSave() {
    const changes = [];
    pending.forEach((allowed, key) => {
      const parts = key.split("|");
      changes.push({ role: parts[0], capability: parts[1], allowed: allowed });
    });
    if (!changes.length) return;
    const btn = S.qs("#pm-save");
    btn.disabled = true;
    btn.textContent = "Saving…";
    try {
      const res = await S.api("/api/permissions", { method: "PUT", body: { changes: changes } });
      data = res.matrix;
      pending = new Map();
      // A refusal is reported, never swallowed: the server keeps the invariants (no viewer writes,
      // no editing Super Admin, no locked capability) and the operator has to know which click of
      // theirs did not land.
      if ((res.refused || []).length) {
        S.toast(res.refused[0].reason || "Some changes were refused", "err");
      } else {
        const n = (res.applied || []).filter((a) => a.changed).length;
        S.toast(n ? n + " permission" + (n === 1 ? "" : "s") + " updated" : "Nothing changed", "ok");
      }
      render();
      // The signed-in user's own capabilities may have just moved, and the nav/buttons were built
      // from the copy /api/auth/me handed us at boot. Re-read it so the shell agrees with the grid.
      await refreshMe();
    } catch (e) {
      S.toast(e.detail || "Couldn't save the permissions", "err");
      btn.disabled = false;
      btn.textContent = "Save changes";
    }
  }

  async function doReset() {
    if (!confirm("Reset every role to the capabilities the app ships with? This clears all "
      + data.override_count + " change(s) made here.")) return;
    try {
      const res = await S.api("/api/permissions/reset", { method: "POST" });
      data = res.matrix;
      pending = new Map();
      S.toast(res.cleared ? "Reset — " + res.cleared + " override(s) cleared" : "Already at defaults", "ok");
      render();
      await refreshMe();
    } catch (e) { S.toast(e.detail || "Couldn't reset", "err"); }
  }

  // Refresh the shell's idea of who we are, so a change to our OWN role's capabilities takes effect
  // without a manual reload. Non-fatal: a stale nav is a cosmetic problem and every endpoint behind
  // it enforces its own capability anyway.
  async function refreshMe() {
    try { S.user = await S.api("/api/auth/me"); } catch (e) { /* keep the boot snapshot */ }
  }

  load();
};

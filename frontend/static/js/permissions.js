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
    + '<div class="tabs" id="pm-tabs">'
    + '<button class="active" data-tab="roles">Roles</button>'
    + '<button data-tab="people">People</button>'
    + '<button data-tab="history">History</button>'
    + '</div>'
    + '<div id="pm-body"><div class="skeleton" style="height:320px"></div></div>';

  // 🔴 Each tab OWNS #pm-body and re-renders it wholesale, so switching away drops any unsaved
  // edits in the other one. That is deliberate over trying to keep two dirty grids alive at once:
  // the Roles grid and a person grid can grant the same capability, and two half-saved views of one
  // answer is how a console starts lying about what is in force.
  S.qsa("#pm-tabs button").forEach((b) => b.onclick = () => {
    S.qsa("#pm-tabs button").forEach((x) => x.classList.remove("active"));
    b.classList.add("active");
    pending = new Map();
    if (b.dataset.tab === "roles") load();
    else if (b.dataset.tab === "people") loadPeople();
    else loadHistory();
  });

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

  // ================= People tab: per-person exceptions =================
  // A grant here is layered ON TOP of the person's role, so the UI must always show BOTH — a
  // checkbox with no indication of where it came from turns "Maria has payroll" into a mystery the
  // next admin cannot unpick. Each row says whether the answer comes from the role or from an
  // exception, and the exceptions are listed separately so they can be found and removed.
  let people = null;
  let editing = null;      // the loaded user_matrix, or null
  let personPending = new Map();

  async function loadPeople() {
    const body = S.qs("#pm-body");
    try { people = (await S.api("/api/permissions/people")).people; }
    catch (e) { S.loadErr(body, e, loadPeople); return; }
    editing = null;
    personPending = new Map();
    renderPeople();
  }

  function renderPeople() {
    const rows = people.length
      ? people.map((p) => '<tr><td><div>' + S.esc(p.name) + '</div>'
          + '<div class="muted" style="font-size:12px">' + S.esc(p.email) + ' · ' + S.esc(p.role_label) + '</div></td>'
          + '<td>' + p.caps.map((c) => '<span class="pill ' + (c.inert ? "grey" : (c.allowed ? "green" : "amber")) + '"'
              + ' title="' + S.esc(c.inert ? (c.reason || "") : (c.allowed ? "Granted on top of their role" : "Revoked from their role")) + '">'
              + (c.allowed ? "+" : "−") + " " + S.esc(c.label)
              + (c.inert ? " (inactive)" : "") + '</span>').join(" ")
          + '</td>'
          + '<td style="text-align:right;white-space:nowrap">'
          + '<button class="btn sm ghost" data-person="' + p.user_id + '">Edit</button>'
          + (canEdit ? ' <button class="btn sm danger" data-clear="' + p.user_id + '">Clear</button>' : "")
          + '</td></tr>').join("")
      : '<tr><td colspan="3"><div class="empty">Nobody has an exception to their role. '
        + 'Everyone gets exactly what the Roles tab says.</div></td></tr>';

    S.qs("#pm-body").innerHTML = '<div class="mgr-strip">'
      + '<span>' + people.length + " person" + (people.length === 1 ? "" : "s") + " with exceptions</span>"
      + '<span class="muted" style="font-size:12px">An exception follows the PERSON, so it survives a '
      + 'role change — and goes inactive if their new role could not hold it.</span>'
      + (canEdit ? '<button class="btn sm ghost" id="pm-addperson">Add an exception</button>' : "")
      + "</div>"
      + '<div class="table-wrap"><table><thead><tr><th style="min-width:220px">Person</th>'
      + '<th>Exceptions</th><th style="text-align:right">Actions</th></tr></thead>'
      + "<tbody>" + rows + "</tbody></table></div>";

    S.qsa("[data-person]").forEach((b) => b.onclick = () => openPerson(+b.dataset.person));
    S.qsa("[data-clear]").forEach((b) => b.onclick = () => clearPerson(+b.dataset.clear));
    const add = S.qs("#pm-addperson");
    if (add) add.onclick = pickPerson;
  }

  async function pickPerson() {
    let staff;
    try { staff = await S.api("/api/people"); }
    catch (e) { S.toast(e.detail || "Couldn't load the team", "err"); return; }
    const opts = staff.map((u) => '<option value="' + u.id + '">' + S.esc(u.name + " · " + u.role_label) + "</option>").join("");
    const m = S.modal({
      title: "Add a per-person exception",
      body: '<label class="field"><span>Who</span><select id="pp-who">' + opts + "</select></label>"
        + '<div class="form-hint">You will pick the capabilities on the next screen. Their role stays '
        + "as it is — this only records the difference.</div>",
      footer: '<button class="btn ghost" id="pp-cancel">Cancel</button>'
        + '<button class="btn primary" id="pp-go">Continue</button>',
    });
    S.qs("#pp-cancel").onclick = m.close;
    S.qs("#pp-go").onclick = () => { const id = +S.qs("#pp-who").value; m.close(); openPerson(id); };
  }

  async function openPerson(userId) {
    try { editing = await S.api("/api/permissions/people/" + userId); }
    catch (e) { S.toast(e.detail || "Couldn't load that person", "err"); return; }
    personPending = new Map();
    renderPerson();
  }

  function personState(cap) {
    const p = personPending.get(cap.key);
    return p === undefined ? cap.allowed : p;
  }

  function renderPerson() {
    const u = editing.user;
    const dirty = personPending.size;
    let rowsHtml = "";
    for (const group of editing.groups) {
      const inGroup = editing.capabilities.filter((c) => c.group === group);
      if (!inGroup.length) continue;
      rowsHtml += '<tr><td colspan="3" class="section-label" style="padding-top:14px">' + S.esc(group) + "</td></tr>";
      for (const cap of inGroup) {
        const on = personState(cap);
        const differs = on !== cap.from_role;
        rowsHtml += "<tr><td><div>" + S.esc(cap.label)
          + (cap.locked ? ' <span class="pill amber">locked</span>' : "")
          + (cap.write ? "" : ' <span class="pill grey">read</span>')
          + '</div><div class="muted" style="font-size:12px">' + S.esc(cap.description) + "</div></td>"
          + '<td class="muted" style="white-space:nowrap">'
          + (cap.from_role ? "Their role: yes" : "Their role: no") + "</td>"
          + '<td style="text-align:center" title="' + S.esc(cap.editable ? "" : (cap.reason || "")) + '">'
          + '<input type="checkbox" style="width:auto" data-pcap="' + S.esc(cap.key) + '"'
          + (on ? " checked" : "") + (cap.editable && canEdit ? "" : " disabled") + ">"
          + (differs ? ' <span class="pill amber">exception</span>' : "")
          + "</td></tr>";
      }
    }
    S.qs("#pm-body").innerHTML = '<div class="mgr-strip">'
      + '<button class="btn sm ghost" id="pm-back">← All people</button>'
      + "<span><b>" + S.esc(u.name) + "</b> · " + S.esc(u.role_label) + "</span>"
      + '<span class="muted" style="font-size:12px">Ticking a box that differs from their role records '
      + "an exception. Matching their role again removes it.</span></div>"
      + '<div class="table-wrap"><table><thead><tr><th style="min-width:280px">Capability</th>'
      + '<th>From their role</th><th style="text-align:center">This person</th></tr></thead>'
      + "<tbody>" + rowsHtml + "</tbody></table></div>"
      + (canEdit
        ? '<div class="row between" style="margin-top:14px"><div class="muted">'
          + (dirty ? dirty + " unsaved change" + (dirty === 1 ? "" : "s") : "No unsaved changes") + "</div>"
          + '<div class="row" style="gap:8px">'
          + '<button class="btn ghost" id="pm-pcancel"' + (dirty ? "" : " disabled") + ">Discard</button>"
          + '<button class="btn primary" id="pm-psave"' + (dirty ? "" : " disabled") + ">Save changes</button>"
          + "</div></div>"
        : "");

    S.qs("#pm-back").onclick = loadPeople;
    S.qsa("[data-pcap]:not([disabled])").forEach((box) => {
      box.onchange = () => {
        const cap = editing.capabilities.find((c) => c.key === box.dataset.pcap);
        if (box.checked === cap.allowed) personPending.delete(cap.key);
        else personPending.set(cap.key, box.checked);
        renderPerson();
      };
    });
    const c = S.qs("#pm-pcancel");
    if (c) c.onclick = () => { personPending = new Map(); renderPerson(); };
    const sv = S.qs("#pm-psave");
    if (sv) sv.onclick = savePerson;
  }

  async function savePerson() {
    const changes = [];
    personPending.forEach((allowed, capability) => changes.push({ capability: capability, allowed: allowed }));
    if (!changes.length) return;
    try {
      const res = await S.api("/api/permissions/people/" + editing.user.id,
        { method: "PUT", body: { changes: changes } });
      editing = res.matrix;
      personPending = new Map();
      if ((res.refused || []).length) S.toast(res.refused[0].reason || "Some changes were refused", "err");
      else S.toast("Saved", "ok");
      renderPerson();
      await refreshMe();
    } catch (e) { S.toast(e.detail || "Couldn't save", "err"); }
  }

  async function clearPerson(userId) {
    if (!confirm("Remove every exception for this person? They will get exactly what their role gives.")) return;
    try {
      const res = await S.api("/api/permissions/people/" + userId + "/reset", { method: "POST" });
      S.toast(res.cleared ? res.cleared + " exception(s) removed" : "Nothing to remove", "ok");
      await loadPeople();
      await refreshMe();
    } catch (e) { S.toast(e.detail || "Couldn't clear", "err"); }
  }

  // ================= History tab =================
  async function loadHistory() {
    const body = S.qs("#pm-body");
    let changes;
    try { changes = (await S.api("/api/permissions/audit")).changes; }
    catch (e) { S.loadErr(body, e, loadHistory); return; }
    const rows = changes.length
      ? changes.map((c) => "<tr><td>" + S.esc(c.at.replace("T", " ").slice(0, 16)) + "</td>"
          + "<td>" + S.esc(c.actor) + "</td>"
          + '<td><span class="pill grey">' + S.esc(c.scope) + "</span></td>"
          + "<td>" + S.esc(c.label || c.target || "") + "</td>"
          + "<td>" + (c.action === "reset"
              ? '<span class="pill grey">reset to defaults</span>'
              : (c.allowed
                  ? '<span class="pill green">granted</span>'
                  : '<span class="pill amber">revoked</span>'))
          + "</td></tr>").join("")
      : '<tr><td colspan="5"><div class="empty">No permission changes recorded yet.</div></td></tr>';
    body.innerHTML = '<div class="mgr-strip"><span>The last ' + changes.length
      + " permission change" + (changes.length === 1 ? "" : "s") + "</span>"
      + '<span class="muted" style="font-size:12px">Every grant and revoke is recorded in the audit '
      + "log; this is that log filtered to permissions.</span></div>"
      + '<div class="table-wrap"><table><thead><tr><th>When</th><th>Who</th><th>Scope</th>'
      + "<th>Target</th><th>Change</th></tr></thead><tbody>" + rows + "</tbody></table></div>";
  }

  load();
};

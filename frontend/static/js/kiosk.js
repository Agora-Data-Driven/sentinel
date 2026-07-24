/* Attendance kiosk + Super-Admin phone scanner.
   Kiosk: idle → scanned (big buttons) → confirm (auto-reset). Camera restarts each idle.
   Scanner (Super Admin): the camera is ALWAYS ON — it stays live continuously; scan detection
   pauses only while a punch is being confirmed, then resumes. Works on phone (back cam) or laptop.
   Offline: punches queue in IndexedDB and sync every 30s when back online. */
window.pageInit = async (S) => {
  const MODE = document.body.dataset.mode;         // "kiosk" | "scanner"
  const DEVICE = document.body.dataset.device;      // "kiosk" | "admin-phone"
  const PERSIST = MODE === "scanner";               // keep the camera always on for the scanner
  const stage = S.qs("#stage");
  const LATE_REASONS = ["Heavy traffic", "Medical", "Personal", "Client meeting", "Transport issue"];
  let scanner = null, scanning = false, resetTimer = null, shellBuilt = false;

  // --- Scanner mode is Super-Admin only -----------------------------------
  if (MODE === "scanner") {
    try {
      const me = await S.api("/api/auth/me");
      if (me.role !== "super_admin") { S.toast("Super Admin only", "err"); setTimeout(() => (location.href = "/dashboard"), 1200); return; }
    } catch (e) { location.href = "/login"; return; }
  }

  // --- Online indicator ----------------------------------------------------
  function setOnline(on) {
    const el = S.qs("#online");
    el.className = "online " + (on ? "on" : "off");
    S.qs("#online-t").textContent = on ? "Online" : "Offline";
  }
  window.addEventListener("online", () => { setOnline(true); syncQueue(); });
  window.addEventListener("offline", () => setOnline(false));
  setOnline(navigator.onLine);

  // --- IndexedDB offline queue --------------------------------------------
  function db() {
    return new Promise((res, rej) => {
      const r = indexedDB.open("sentinel-kiosk", 1);
      r.onupgradeneeded = () => r.result.createObjectStore("queue", { keyPath: "id", autoIncrement: true });
      r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error);
    });
  }
  async function enqueue(p) { const d = await db(); return new Promise((res, rej) => { const tx = d.transaction("queue", "readwrite"); tx.objectStore("queue").add(p); tx.oncomplete = res; tx.onerror = () => rej(tx.error); }); }
  async function queued() { const d = await db(); return new Promise((res) => { const tx = d.transaction("queue", "readonly"); const q = tx.objectStore("queue").getAll(); q.onsuccess = () => res(q.result || []); }); }
  async function deleteByIds(ids) { if (!ids || !ids.length) return; const d = await db(); return new Promise((res) => { const tx = d.transaction("queue", "readwrite"); const st = tx.objectStore("queue"); ids.forEach((id) => st.delete(id)); tx.oncomplete = res; }); }
  async function queueCount() { return (await queued()).length; }
  // Stable per-punch id so a punch is synced exactly once and a lost/partial response can't double- or drop-record it.
  const newUid = () => (self.crypto && crypto.randomUUID) ? crypto.randomUUID() : Date.now() + "-" + Math.random().toString(16).slice(2);

  async function syncQueue() {
    if (!navigator.onLine) return;
    const items = await queued();
    if (!items.length) return;
    try {
      const punches = items.map((i) => ({ uid: i.uid, token: i.token, action: i.action, client_time: i.client_time, late_reason: i.late_reason, handover_note: i.handover_note }));
      const res = await S.api("/api/attendance/offline-sync", { method: "POST", body: { punches } });
      // Delete ONLY punches the server acknowledged — recorded (ok) or permanently rejected
      // (e.g. duplicate). Anything it didn't ack (a truncated/failed response) stays queued for the
      // next attempt, so a punch is never silently dropped.
      const results = res.results || [];
      const acked = new Set(results.filter((r) => r.uid && (r.ok || r.permanent)).map((r) => r.uid));
      const removeIds = items.filter((i) => i.uid && acked.has(i.uid)).map((i) => i.id);
      // Legacy punches queued before uids existed: clear only if the whole batch resolved.
      const legacy = items.filter((i) => !i.uid).map((i) => i.id);
      if (legacy.length && results.length && results.every((r) => r.ok || r.permanent)) removeIds.push(...legacy);
      await deleteByIds(removeIds);
      const synced = results.filter((r) => r.ok).length;
      if (synced) S.toast(`Synced ${synced} offline punch(es)`, "ok");
      if (PERSIST) updateQueueBadge(); else if (!scanning) idle();
    } catch (e) { /* stay queued; retry next tick */ }
  }
  setInterval(syncQueue, 30000);

  // --- Clock ---------------------------------------------------------------
  function clockHTML() {
    const now = new Date();
    return `<div class="k-clock" id="kclock">${now.toLocaleTimeString("en-PH", { timeZone: "Asia/Manila", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: true })}</div>
      <div class="k-date">${now.toLocaleDateString("en-PH", { timeZone: "Asia/Manila", weekday: "long", month: "long", day: "numeric" })}</div>`;
  }
  setInterval(() => { const c = S.qs("#kclock"); if (c) c.textContent = new Date().toLocaleTimeString("en-PH", { timeZone: "Asia/Manila", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: true }); }, 1000);

  // --- Camera lifecycle ----------------------------------------------------
  async function startScanner() {
    const reader = S.qs("#reader");
    if (typeof Html5Qrcode === "undefined") {
      if (reader) reader.innerHTML = '<div class="muted" style="padding:22px 8px">Scanner library didn’t load. Check your connection, or type the badge code below.</div>';
      return;
    }
    try { scanner = new Html5Qrcode("reader", { verbose: false }); } catch (e) { return; }
    // Scan the middle ~75% of the frame (a bigger target reads far more reliably than a small fixed
    // box, esp. on low-res laptop webcams) and use the browser's NATIVE BarcodeDetector when present
    // (Chrome/Edge) — it decodes QR codes much more reliably than the JS fallback.
    const config = {
      fps: 15,
      qrbox: (vw, vh) => { const m = Math.round(Math.min(vw, vh) * 0.75); return { width: m, height: m }; },
      experimentalFeatures: { useBarCodeDetectorIfSupported: true },
      rememberLastUsedCamera: true,
    };
    const onScan = (decoded) => { if (scanning) { scanning = false; handleToken(decoded); } };
    scanning = true;
    try {
      await scanner.start({ facingMode: "environment" }, config, onScan, () => {});
    } catch (e1) {
      // No back camera (e.g. a laptop) → fall back to the first available camera.
      try {
        const cams = await Html5Qrcode.getCameras();
        if (cams && cams.length) await scanner.start(cams[0].id, config, onScan, () => {});
        else throw e1;
      } catch (e2) {
        const r = S.qs("#reader"); if (r) r.innerHTML = '<div class="muted" style="padding:22px 8px">Camera unavailable here — use “type badge code” below.</div>';
        scanner = null; scanning = false;
      }
    }
  }
  async function stopScanner() {
    scanning = false;
    if (scanner) { try { await scanner.stop(); scanner.clear(); } catch (e) {} scanner = null; }
  }
  function pauseScanning() { scanning = false; if (scanner) { try { scanner.pause(false); } catch (e) {} } }  // keep camera ON, stop detecting
  function resumeScanning() { if (scanner) { try { scanner.resume(); } catch (e) {} scanning = true; } }

  // Where transient UI (scanned card / confirm) renders: a panel below the live camera in scanner
  // mode; the whole stage in kiosk mode.
  function showTransient(html) {
    if (PERSIST) { const p = S.qs("#panel"); if (p) p.innerHTML = html; const h = S.qs("#k-hint"); if (h) h.style.display = "none"; }
    else stage.innerHTML = html;
  }

  async function updateQueueBadge() {
    if (!PERSIST) return;
    const el = S.qs("#qbadge"); if (!el) return;
    const qc = await queueCount();
    if (qc) { el.textContent = `${qc} punch(es) waiting to sync`; el.style.display = ""; } else el.style.display = "none";
  }

  // --- Scanner persistent shell (built once; camera never torn down) -------
  function buildScannerShell() {
    stage.innerHTML = `${clockHTML()}
      <div id="reader" style="margin-top:14px"></div>
      <div class="k-hint" id="k-hint">Point the camera at an employee's QR badge</div>
      <div id="panel"></div>
      <div class="manual"><input id="manual" placeholder="…or type badge code" autocomplete="off"><button class="btn primary" id="manual-go">Go</button></div>
      <div id="qbadge" class="queued" style="display:none"></div>
      <div style="margin-top:16px;border-top:1px solid var(--line);padding-top:14px">
        <button class="btn ghost" id="assign-qr">${S.ICON.qr}Generate / assign QR badge</button></div>`;
    S.qs("#manual-go").onclick = () => { const t = S.qs("#manual").value.trim(); if (t) handleToken(t); };
    S.qs("#manual").onkeydown = (e) => { if (e.key === "Enter") S.qs("#manual-go").click(); };
    S.qs("#assign-qr").onclick = openAssignQr;
  }

  // --- Idle ----------------------------------------------------------------
  async function idle() {
    clearTimeout(resetTimer);
    if (PERSIST) {
      if (!shellBuilt) { buildScannerShell(); shellBuilt = true; await startScanner(); }
      else { const p = S.qs("#panel"); if (p) p.innerHTML = ""; const h = S.qs("#k-hint"); if (h) h.style.display = ""; resumeScanning(); }
      updateQueueBadge();
      return;
    }
    // Kiosk mode: rebuild the stage + (re)start the camera each idle.
    const qc = await queueCount();
    stage.innerHTML = `${clockHTML()}
      <div id="reader"></div>
      <div class="k-hint">Scan your Agora badge to punch</div>
      <div class="manual"><input id="manual" placeholder="…or type badge code" autocomplete="off"><button class="btn primary" id="manual-go">Go</button></div>
      ${qc ? `<div class="queued">${qc} punch(es) waiting to sync</div>` : ""}`;
    S.qs("#manual-go").onclick = () => { const t = S.qs("#manual").value.trim(); if (t) handleToken(t); };
    S.qs("#manual").onkeydown = (e) => { if (e.key === "Enter") S.qs("#manual-go").click(); };
    await startScanner();
  }

  // --- Scanner-only: generate + assign a QR badge to an employee -----------
  async function openAssignQr() {
    pauseScanning();  // keep the camera on, just stop detecting while the modal is open
    let people = [];
    try { people = await S.api("/api/people"); } catch (e) { S.toast(e.detail || "Couldn't load employees", "err"); idle(); return; }
    const m = S.modal({
      title: "Assign QR badge",
      body: `<label class="field"><span>Employee</span>
          <select id="qa-user"><option value="">Choose an employee…</option>${people.map((p) => `<option value="${p.id}">${S.esc(p.name)} — ${S.esc(p.role_label || p.role)}</option>`).join("")}</select></label>
        <div id="qa-preview" style="text-align:center;margin-top:8px"></div>`,
      footer: `<button class="btn ghost" id="qa-close">Close</button>`,
    });
    S.qs("#qa-close").onclick = () => { m.close(); idle(); };
    S.qs("#qa-user").onchange = async (e) => {
      const id = e.target.value;
      const box = S.qs("#qa-preview");
      if (!id) { box.innerHTML = ""; return; }
      box.innerHTML = '<div class="muted" style="padding:12px">Loading…</div>';
      let code = "";
      try { code = (await S.api(`/api/people/${id}/badge`)).code; } catch (err) {}
      box.innerHTML = `
        <img alt="QR" src="/api/people/${id}/qr?t=${Date.now()}" style="width:190px;height:190px;border:1px solid var(--line);border-radius:12px;padding:8px;background:#fff">
        <label class="field" style="margin-top:10px;text-align:left"><span>Badge code (type this instead of scanning)</span>
          <div class="row" style="gap:6px"><input id="qa-code" readonly value="${S.esc(code)}" style="flex:1;font-family:monospace"><button class="btn ghost" id="qa-copy">Copy</button></div></label>
        <div class="row" style="justify-content:center;gap:8px;margin-top:6px">
          <a class="btn ghost" href="/api/people/${id}/qr" download="badge-${id}.png">${S.ICON.download}Download / print</a>
          <button class="btn primary" id="qa-regen">Reissue new code</button>
        </div>
        <div class="muted" style="font-size:12px;margin-top:8px">Print it or send to their phone. The scanner reads the QR, or they can type the code.</div>`;
      S.qs("#qa-copy").onclick = async () => {
        const inp = S.qs("#qa-code");
        try { await navigator.clipboard.writeText(inp.value); S.toast("Code copied", "ok"); }
        catch (err) { inp.select(); document.execCommand("copy"); S.toast("Code copied", "ok"); }
      };
      S.qs("#qa-regen").onclick = async () => {
        if (!confirm("Reissue a new QR code? The current badge will stop working.")) return;
        try {
          await S.api(`/api/people/${id}/qr/regenerate`, { method: "POST" });
          S.qs(`#qa-preview img`).src = `/api/people/${id}/qr?t=` + Date.now();
          const nb = await S.api(`/api/people/${id}/badge`); S.qs("#qa-code").value = nb.code;
          S.toast("New badge issued", "ok");
        } catch (err) { S.toast(err.detail, "err"); }
      };
    };
  }

  // --- Handle a scanned/typed token ---------------------------------------
  async function handleToken(token) {
    if (PERSIST) pauseScanning(); else await stopScanner();
    let info;
    try { info = await S.api("/api/attendance/scan", { method: "POST", body: { token } }); }
    catch (e) {
      if (e.status === undefined) showTransient(confirmCard("err", "Offline", "Cannot look up badge while offline. Reconnect and try again."));
      else showTransient(confirmCard("err", "Not recognised", e.detail || "Unknown badge."));
      resetTimer = setTimeout(idle, 3500); return;
    }
    renderScanned(token, info);
  }

  function isLate(shift) {
    const now = new Date(new Date().toLocaleString("en-US", { timeZone: "Asia/Manila" }));
    const [h, m] = (shift.start || "08:00").split(":").map(Number);
    const thr = new Date(now); thr.setHours(h, m + (shift.grace || 0), 0, 0);
    return now > thr;
  }

  function renderScanned(token, info) {
    const va = info.valid_actions;
    const btn = (action, cls, icon, label, enabled) =>
      `<button class="k-btn ${cls}" data-action="${action}" ${enabled ? "" : "disabled"}>${S.ICON[icon]}${label}</button>`;
    const stateLabel = { none: "Not clocked in", in: "Clocked in", on_break: "On break", out: "Clocked out" }[info.state];
    showTransient(`
      ${S.avatar(info.user, "lg")}
      <div class="k-name" style="margin-top:12px">${S.esc(info.user.name)}</div>
      <div class="k-sub">${S.esc(info.team_name || info.role_label)} · <span class="pill grey">${stateLabel}</span></div>
      <div class="k-actions">
        ${btn("clock_in", "in", "check", "Clock In", va.includes("clock_in"))}
        ${btn("clock_out", "out", "logout", "Clock Out", va.includes("clock_out"))}
      </div>
      <div id="extra" style="margin-top:16px"></div>
      <button class="btn ghost" id="cancel" style="margin-top:14px">Cancel</button>`);
    S.qs("#cancel").onclick = idle;
    S.qsa(".k-btn:not([disabled])").forEach((b) => b.onclick = () => onAction(token, info, b.dataset.action));
    resetTimer = setTimeout(idle, 20000);
  }

  function onAction(token, info, action) {
    clearTimeout(resetTimer);
    const extra = S.qs("#extra");
    // Confirm screens must NEVER be dead-ends: keep an auto-reset running so an abandoned punch
    // returns the station to idle (and resumes the scanner) instead of freezing it for everyone.
    if (action === "clock_in" && isLate(info.shift)) {
      let reason = "";
      extra.innerHTML = `<div class="section-label">You're late — pick a reason (optional)</div>
        <div class="chips" id="chips">${LATE_REASONS.map((r) => `<span class="chip-sel" data-r="${S.esc(r)}">${S.esc(r)}</span>`).join("")}</div>
        <button class="btn success block" id="do" style="margin-top:14px">Confirm Clock In</button>`;
      S.qsa("#chips .chip-sel").forEach((c) => c.onclick = () => { S.qsa("#chips .chip-sel").forEach((x) => x.classList.remove("active")); c.classList.add("active"); reason = c.dataset.r; });
      S.qs("#do").onclick = () => { clearTimeout(resetTimer); submit(token, action, { late_reason: reason }); };
      resetTimer = setTimeout(idle, 25000);
      return;
    }
    if (action === "clock_out") {
      extra.innerHTML = `<div class="section-label">Handover note (optional)</div>
        <textarea id="handover" placeholder="What should the next shift know?" style="margin-top:6px"></textarea>
        <button class="btn danger block" id="do" style="margin-top:12px">Confirm Clock Out</button>`;
      S.qs("#do").onclick = () => { clearTimeout(resetTimer); submit(token, action, { handover_note: S.qs("#handover").value }); };
      resetTimer = setTimeout(idle, 25000);
      return;
    }
    submit(token, action, {});
  }

  async function submit(token, action, opts) {
    const payload = { token, action, device: DEVICE, late_reason: opts.late_reason || null, handover_note: opts.handover_note || null };
    const label = { clock_in: "Clocked in", clock_out: "Clocked out", break_start: "Break started", break_end: "Break ended" }[action];
    try {
      const res = await S.api("/api/attendance/event", { method: "POST", body: payload });
      const late = res.late_status === "Late" ? ` · ${res.late_minutes}m late` : "";
      showTransient(confirmCard("ok", label + "!", S.fmtTime(res.summary.clock_in || res.summary.clock_out) + late));
    } catch (e) {
      // Queue anything that might succeed on retry: offline (no status), server errors (5xx),
      // auth/kiosk-key hiccups (401) or rate-limit (429). Only definitive rejections (409 "already
      // clocked in", 400 bad data) are shown as errors and not retried — retrying can't fix them.
      const transient = e.status === undefined || e.status >= 500 || e.status === 401 || e.status === 429;
      if (transient) {
        await enqueue({ uid: newUid(), token, action, client_time: new Date().toISOString(), late_reason: payload.late_reason, handover_note: payload.handover_note });
        if (PERSIST) updateQueueBadge();
        showTransient(confirmCard("warn", e.status === undefined ? "Saved offline" : "Saved — will retry", "It'll sync automatically."));
      } else {
        showTransient(confirmCard("err", "Couldn't punch", e.detail || "Try again."));
      }
    }
    resetTimer = setTimeout(idle, 5000);
  }

  function confirmCard(kind, title, sub) {
    const ic = kind === "ok" ? S.ICON.check : kind === "err" ? S.ICON.x : S.ICON.bell;
    const color = kind === "ok" ? "var(--green)" : kind === "err" ? "var(--danger)" : "var(--warn)";
    return `<div style="width:72px;height:72px;border-radius:50%;background:${color};color:#fff;display:grid;place-items:center;margin:6px auto 0">
        <span style="width:38px;height:38px">${ic}</span></div>
      <div class="big-status" style="margin-top:14px">${S.esc(title)}</div>
      <div class="k-sub">${S.esc(sub)}</div>
      <div class="k-hint">Returning to scan…</div>`;
  }

  idle();
  syncQueue();
};

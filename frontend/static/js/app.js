/* =====================================================================
   Sentinel shared client — shell (sidebar/topbar/bell/drawer) + helpers.
   Pages define window.pageInit(S); app.js guards auth, builds the shell,
   then calls pageInit with the Sentinel helper object `S`.
   ===================================================================== */
(function () {
  "use strict";

  // Apply the saved theme immediately (before paint) to avoid a flash. Standalone pages
  // (login/kiosk/scanner) have their own self-contained designs, so they stay on light tokens.
  const THEME_KEY = "sentinel-theme";
  const _standalone = document.body && document.body.dataset.shell === "off";
  document.documentElement.setAttribute("data-theme", _standalone ? "light" : (localStorage.getItem(THEME_KEY) || "light"));

  const ROLE_RANK = { intern: 1, employee: 1, team_lead: 2, account_manager: 3, admin: 4, super_admin: 5 };

  // Task vocabulary colours (statuses/labels/priorities) — fetched once at boot from /api/vocab,
  // so the shared pills/dots colour custom (admin-defined) values, not just the hardcoded ones.
  let COLORS = { statuses: {}, priorities: {}, labels: {} };

  // 🔴 ONE `/api/vocab` PER PAGE LOAD, NOT TWO — AND IT IS SEVEN DB QUERIES (2026-08-17).
  //
  // `boot()` has always fetched the vocabulary (for `COLORS`), and then `dashboard.js`, `manage.js`,
  // `people.js` and `taskboard.js` each fetched it AGAIN. Nobody noticed because it is a fast, cached
  // -looking GET — but on the server `routers/meta.vocab()` calls `services/task_config` seven times
  // and that module memoizes NOTHING, so every call is seven SELECTs. Loading /people ran FOURTEEN
  // queries for configuration that changes about once a month, on a shared-core db-f1-micro.
  //
  // So the answer boot() already has is published here and pages read `S.vocab`.
  //
  // 🔴 IT IS A SNAPSHOT, AND MANAGE EDITS THE VOCABULARY. Statuses, priorities and labels are all
  // renameable in Manage (which is why nothing here may key off a label — AGENTS.md D13). A page that
  // holds this object across a vocabulary WRITE is holding a stale list, so `manage.js` calls
  // `S.refreshVocab()` after every save and delete. Any future surface that edits vocabulary must do
  // the same; reading `S.vocab` is only safe for a surface that does not change it.
  let VOCAB = null;

  function setVocab(v) {
    VOCAB = v || null;
    if (v && v.colors) COLORS = v.colors;
  }

  // Re-reads the vocabulary and re-publishes it. Returns the fresh object so a caller can use it
  // directly. Swallows failure on purpose: a failed refresh must leave the last-known-good snapshot
  // in place rather than blanking every picker on the page.
  async function refreshVocab() {
    try { setVocab(await api("/api/vocab")); } catch (e) { /* keep the previous snapshot */ }
    return VOCAB;
  }

  // ---- Inline icon set (Atrium stroked style: 24x24, stroke-width 1.8) ----
  // 🔴 EVERY ICON IN THE APP IS DECORATIVE, AND SAYS SO (2026-08-17). Every one of the ~60 entries in
  // `ICON` is built here, so these two attributes cover the whole product from one line — which is the
  // only reason it is worth doing at all.
  //   • `aria-hidden="true"` — an icon is never the label. Where an icon is the ONLY content of a
  //     control, that control carries its own `aria-label` (the ✕, the hamburger, the bell, the Coach
  //     FAB); everywhere else the icon sits beside real text it would otherwise duplicate.
  //   • `focusable="false"` — IE/older-Edge legacy that still bites: an inline <svg> is focusable by
  //     default in some engines, which silently inserts a Tab stop with no name for every icon on the
  //     page. That is also a stop the modal focus trap would have to reason about, so removing them at
  //     the source keeps `focusablesIn` honest.
  const P = (d) => `<svg class="svg-ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">${d}</svg>`;
  const ICON = {
    grid: P('<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>'),
    clock: P('<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>'),
    dumbbell: P('<path d="M6.5 6.5l11 11"/><path d="M4 8l-1.5 1.5a1.5 1.5 0 0 0 0 2.1l0 0"/><path d="M8 4L6.5 5.5"/><path d="M20 16l1.5-1.5a1.5 1.5 0 0 0 0-2.1"/><path d="M16 20l1.5-1.5"/><path d="M3 10l2 2M19 12l2 2M10 3l2 2M12 19l2 2"/>'),
    board: P('<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16M15 4v16"/>'),
    users: P('<circle cx="9" cy="8" r="3.2"/><path d="M3.5 19a5.5 5.5 0 0 1 11 0"/><path d="M16 5.5a3 3 0 0 1 0 5.5M21 19a5 5 0 0 0-4-4.9"/>'),
    calendar: P('<rect x="3" y="4.5" width="18" height="16" rx="2"/><path d="M3 9h18M8 2.5v4M16 2.5v4"/>'),
    chart: P('<path d="M4 20V10M10 20V4M16 20v-7M3 20h18"/>'),
    qr: P('<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><path d="M14 14h3v3M20 14v.01M14 20h.01M20 20h.01M17 20v-3"/>'),
    gear: P('<circle cx="12" cy="12" r="3.2"/><path d="M19.4 15a1.6 1.6 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.6 1.6 0 0 0-2.7 1.1V21a2 2 0 0 1-4 0v-.1a1.6 1.6 0 0 0-2.7-1.1l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1A1.6 1.6 0 0 0 4.6 15H4.5a2 2 0 0 1 0-4h.1a1.6 1.6 0 0 0 1.1-2.7l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.6 1.6 0 0 0 2.7-1.1V4.5a2 2 0 0 1 4 0v.1a1.6 1.6 0 0 0 2.7 1.1l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.6 1.6 0 0 0-.3 1.8"/>'),
    bell: P('<path d="M18 8a6 6 0 1 0-12 0c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.7 21a2 2 0 0 1-3.4 0"/>'),
    logout: P('<path d="M15 4h3a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-3"/><path d="M10 17l-5-5 5-5M5 12h12"/>'),
    menu: P('<path d="M3.5 6h17M3.5 12h17M3.5 18h17"/>'),
    chev: P('<path d="M9 6l6 6-6 6"/>'),
    check: P('<path d="M20 6L9 17l-5-5"/>'),
    plus: P('<path d="M12 5v14M5 12h14"/>'),
    x: P('<path d="M18 6L6 18M6 6l12 12"/>'),
    search: P('<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/>'),
    download: P('<path d="M12 3v12M7 10l5 5 5-5M5 21h14"/>'),
    comment: P('<path d="M21 12a8 8 0 0 1-11.5 7.2L4 20l1-4.6A8 8 0 1 1 21 12z"/>'),
    paperclip: P('<path d="M21 10l-9.2 9.2a4 4 0 0 1-5.7-5.7l9.2-9.2a2.7 2.7 0 0 1 3.8 3.8L9.6 16.6a1.3 1.3 0 0 1-1.9-1.9L16 6.4"/>'),
    // Marks the INTERNAL fields in the task detail/edit forms (taskboard.js) — "not visible to
    // clients". Missing keys render the string "undefined" into the label, so keep this in step
    // with every S.ICON.* the board asks for.
    lock: P('<rect x="4.5" y="10.5" width="15" height="9.5" rx="2"/><path d="M8 10.5V7a4 4 0 0 1 8 0v3.5"/>'),
    trophy: P('<path d="M6 4h12v4a6 6 0 0 1-12 0z"/><path d="M6 5H4a2 2 0 0 0 2 4.5M18 5h2a2 2 0 0 1-2 4.5M12 14v3M9 20h6M10 20c0-1.7.8-3 2-3s2 1.3 2 3"/>'),
    cap: P('<path d="M12 4L2 9l10 5 10-5-10-5z"/><path d="M6 11.5V17c0 1.4 2.7 2.5 6 2.5s6-1.1 6-2.5v-5.5"/><path d="M22 9v5"/>'),
    flame: P('<path d="M12 3s5 4 5 9a5 5 0 0 1-10 0c0-1.5.6-2.7 1.3-3.6C9 10 10 9 10 7c1.5.8 2 2.3 2 4 .9-.7 1.5-1.8 1.5-3 .3.7.5 1.4-1.5 5z"/>'),
    coffee: P('<path d="M4 8h13v4a5 5 0 0 1-5 5H9a5 5 0 0 1-5-5z"/><path d="M17 9h2a2 2 0 0 1 0 5h-2M6 2v2M10 2v2M14 2v2"/>'),
    doc: P('<path d="M6 2.5h8L19 7v14.5H6z"/><path d="M14 2.5V7h4M9 13h6M9 17h5"/>'),
    inbox: P('<path d="M3 12h5l1.5 3h5L21 12M3 12l3-8h12l3 8v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>'),
    sparkle: P('<path d="M12 3l1.8 4.7L18.5 9l-4.7 1.8L12 15l-1.8-4.2L5.5 9l4.7-1.3z"/>'),
    sliders: P('<path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M18 18h2"/><circle cx="16" cy="6" r="2"/><circle cx="10" cy="12" r="2"/><circle cx="16" cy="18" r="2"/>'),
    sun: P('<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>'),
    moon: P('<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/>'),
    wallet: P('<rect x="3" y="6" width="18" height="13" rx="2.5"/><path d="M3 9h18M16 13.5h.01"/><path d="M16 6V4.5a1.5 1.5 0 0 0-2-1.4L4.5 5.5"/>'),
    compass: P('<circle cx="12" cy="12" r="9"/><path d="M15.5 8.5l-2 5-5 2 2-5z"/>'),
    book: P('<path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v15H6.5A2.5 2.5 0 0 0 4 20.5z"/><path d="M4 20.5A2.5 2.5 0 0 1 6.5 18H20v3H6.5A2.5 2.5 0 0 1 4 20.5z"/>'),
    target: P('<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.2"/>'),
    heart: P('<path d="M12 20s-7-4.6-9.2-9A4.7 4.7 0 0 1 12 6a4.7 4.7 0 0 1 9.2 5C19 15.4 12 20 12 20z"/>'),
    lock: P('<rect x="4.5" y="10.5" width="15" height="10" rx="2.2"/><path d="M8 10.5V7a4 4 0 0 1 8 0v3.5"/><path d="M12 14.5v2.5"/>'),
    run: P('<circle cx="14" cy="4.8" r="1.8"/><path d="M13 8.5l-3.2 2 1.6 3.2M11.4 13.7L9.5 20M11.4 13.7l3 1.4.9 4.9M13 8.5l3.2 1.4 1 2.8 2.3.6M13 8.5l-4.5 1"/>'),
    // The task form's property rows (taskboard.js `taskForm`) label each row with one of these.
    // They live HERE rather than inline in that file because this object is the icon registry and
    // taskboard.js deliberately holds no SVG of its own — every icon on the board comes from S.ICON.
    // `user` is the singular of `users`: one Lead vs many Support, which is the whole distinction
    // those two rows draw.
    building: P('<path d="M3 21V6.5L11 3v18"/><path d="M11 9.5l8 3V21"/><path d="M6.5 9h1M6.5 13h1M6.5 17h1M14.5 14h1M14.5 17.5h1"/>'),
    eye: P('<path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7-10-7-10-7z"/><circle cx="12" cy="12" r="2.7"/>'),
    briefcase: P('<rect x="3" y="7.5" width="18" height="12.5" rx="2"/><path d="M8.5 7.5V5.5a2 2 0 0 1 2-2h3a2 2 0 0 1 2 2v2M3 12.5h18"/>'),
    user: P('<circle cx="12" cy="8" r="3.6"/><path d="M4.8 20a7.2 7.2 0 0 1 14.4 0"/>'),
    list: P('<path d="M4 6h16M4 12h10M4 18h6"/>'),
  };

  const AGORA_LOGO =
    '<svg viewBox="0 0 150 40" role="img" aria-label="Agora">' +
    '<g fill="none" stroke="#1A1B1E" stroke-linecap="round" stroke-linejoin="round">' +
    '<path d="M3 37 L19 4 L35 37" stroke-width="1.8"/><path d="M12 37 L24 12" stroke-width="1.1" opacity="0.5"/>' +
    '<path d="M11.5 24 L26.5 24" stroke-width="1.6"/></g>' +
    '<text x="48" y="24.5" font-family="Inter,sans-serif" font-size="21" font-weight="600" letter-spacing="3.2" fill="#1A1B1E">AGORA</text>' +
    '<text x="49.5" y="35" font-family="Inter,sans-serif" font-size="7.3" font-weight="700" letter-spacing="3.6" fill="#353535">OPERATIONS</text></svg>';

  // Cache-bust: bump when the logo file changes so browsers/PWA fetch the new art, not a stale copy.
  const LOGO_V = "?v=21";
  // Dark mode uses the white-ink logo so it stays legible on the dark sidebar.
  function logoCandidates() {
    const dark = document.documentElement.getAttribute("data-theme") === "dark";
    return dark
      ? ["/static/img/logo-dark.png" + LOGO_V, "/static/img/logo.png" + LOGO_V]
      : ["/static/img/logo.png" + LOGO_V, "/static/img/logo.svg"];
  }
  // Paint the custom logo IMMEDIATELY (pill hidden), because every real deployment has one.
  // Rendering the built-in mark first and swapping after the async probe made every RELOAD flash
  // the built-in AGORA mark + the orange SENTINEL pill before settling: on a warm reload the art
  // is in cache, so first paint happened before the probe resolved. applyBrandLogo() below then
  // either confirms this (a no-op) or restores the built-in mark + pill when no logo file exists.
  function brandSlotHTML() { return `<img class="brand-img" src="${logoCandidates()[0]}" alt="Sentinel">`; }

  // Flat, single-level navigation: 6 destinations, no accordions. A destination is either a
  // LEAF (its own page) or a HUB — a set of sibling pages that share a context bar under the
  // topbar. The sidebar row for a hub links to its primary (first allowed) page and lights up
  // whenever any of its pages is current; the siblings surface as tabs in renderContextBar,
  // not as nested rows. Item gating unchanged: `roles` allow-list, `min` rank floor, `hideRoles`
  // deny-list (personal tools like Leave/Gym a super_admin doesn't use). A hub whose every child
  // is filtered out is dropped entirely (e.g. Admin disappears for regular staff).
  const NAV = [
    { section: "Workspace" },
    // "Overview" (the URL stays /dashboard — notifications, the palette and bookmarks all point
    // at it) is the growth compass and ledger (growth.js) plus a "my work" strip. The task board
    // was embedded here from 2026-07-26 until 2026-08-03, when decision D7 gave it its own page
    // again; `/dashboard?open=<id>` forwards to /tasks for the notifications minted in that window.
    { href: "/dashboard", label: "Overview", icon: "grid" },
    { href: "/tasks", label: "Task Board", icon: "board" },
    // The four Growth tabs mirror the Overview's four dimensions one-to-one:
    // Professional (the engine's career programs, formerly "Academy"), Philosophical and
    // Spiritual (each a Mastery Engine pinned to its reading program), Physical (the gym,
    // formerly "Gym"). The Overview's rings roll all four up and link straight into them —
    // which is why this hub no longer carries an "Overview" child of its own.
    { group: "Growth", icon: "sparkle", children: [
      { href: "/academy", label: "Professional", icon: "target" },
      { href: "/philosophical", label: "Philosophical", icon: "cap" },
      { href: "/spiritual", label: "Spiritual", icon: "flame" },
      { href: "/gym", label: "Physical", icon: "dumbbell", hideRoles: ["super_admin"] },
      // No Reading tab: the reading canon overlaps the Philosophical/Spiritual engines.
      // The /reading page itself stays reachable (the Overview's "Open the canon" links).
    ] },
    { group: "Time & Leave", icon: "clock", children: [
      { href: "/attendance", label: "Time", icon: "clock" },
      { href: "/leave", label: "Leave", icon: "calendar", hideRoles: ["super_admin"] },
      // One inbox for attendance-correction + leave approvals (managers+). Replaces the separate
      // "Approvals" tabs that used to live on the Time and Leave pages.
      { href: "/approvals", label: "Approvals", icon: "inbox", min: "team_lead" },
      // Clock in (the QR scanner station) punches OTHER people's badges, and the punch endpoints
      // only trust a Super-Admin session (attendance.kiosk_guard) — so only super_admin gets the
      // tab. Everyone else clocks themselves in from the Overview's day strip.
      { href: "/scanner", label: "Clock in", icon: "qr", roles: ["super_admin"] },
    ] },
    { href: "/north-star", label: "Our North Star", icon: "compass" },
    { section: "Admin" },
    { group: "Admin", icon: "sliders", children: [
      { href: "/people", label: "People", icon: "users", min: "team_lead" },
      { href: "/reports", label: "Reports", icon: "chart", min: "team_lead" },
      { href: "/payroll", label: "Payroll", icon: "wallet", roles: ["super_admin"] },
      { href: "/manage", label: "Manage", icon: "sliders", roles: ["super_admin"] },
      { href: "/settings", label: "Settings", icon: "gear", min: "admin" },
    ] },
  ];

  // ---------------- Helpers ----------------
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const qs = (s, r = document) => r.querySelector(s);
  const qsa = (s, r = document) => Array.from(r.querySelectorAll(s));

  const CSRF_COOKIE = "sentinel_csrf";
  const CSRF_HEADER = "X-CSRF-Token";
  const readCookie = (name) => {
    const m = document.cookie.match("(?:^|; )" + name.replace(/([.*+?^${}()|[\]\\])/g, "\\$1") + "=([^;]*)");
    return m ? decodeURIComponent(m[1]) : "";
  };

  async function api(path, opts = {}) {
    const method = opts.method || "GET";
    const o = { method, headers: {}, credentials: "same-origin" };
    if (opts.body !== undefined) { o.headers["Content-Type"] = "application/json"; o.body = JSON.stringify(opts.body); }
    if (opts.form) { o.body = opts.form; } // FormData: let browser set the boundary
    // Double-submit CSRF token on state-changing requests (server issues the cookie).
    if (!["GET", "HEAD", "OPTIONS"].includes(method.toUpperCase())) {
      const tok = readCookie(CSRF_COOKIE);
      if (tok) o.headers[CSRF_HEADER] = tok;
    }
    const res = await fetch(path, o);
    if (res.status === 204) return null;
    const ct = res.headers.get("content-type") || "";
    const data = ct.includes("application/json") ? await res.json() : await res.text();
    if (!res.ok) {
      // FastAPI hands back a string detail for HTTPExceptions but a list of
      // {loc, msg} objects for 422 validation errors — flatten those to a
      // readable message so the toast never shows a bare "[object Object]".
      let detail = data && data.detail;
      if (Array.isArray(detail)) {
        detail = detail.map((e) => {
          const field = Array.isArray(e.loc) ? e.loc[e.loc.length - 1] : "";
          return field ? `${field}: ${e.msg}` : e.msg;
        }).join("; ");
      } else if (detail && typeof detail === "object") {
        detail = detail.msg || JSON.stringify(detail);
      }
      detail = detail || res.statusText;
      const err = new Error(detail); err.status = res.status; err.detail = detail;
      throw err;
    }
    return data;
  }

  // toast(msg, kind) — kind: "ok" | "err" | undefined.
  // toast(msg, kind, { action: { label, onClick }, duration }) — optional action button (e.g. Undo).
  // Returns { dismiss } so callers can close it early.
  function toast(msg, kind, opts) {
    opts = opts || {};
    let box = qs("#toasts");
    if (!box) {
      box = document.createElement("div"); box.id = "toasts";
      // 🔴 THE LIVE REGION IS NOT DECORATION (added 2026-08-17). `api()` flattens every failure into
      // a toast, so this is the app's ONLY error channel — and until this line it was a plain div
      // appended to the body, which assistive tech never announces. A screen-reader user pressed
      // Approve, the request 403'd, and nothing whatsoever reported it.
      //
      // Two details that are easy to get wrong:
      //  • The region has to exist in the DOM BEFORE the message is put into it, or the insertion is
      //    not an update to a live region and may not be announced at all. That is why the attributes
      //    go on this container rather than on each toast.
      //  • `polite` here, and `role="alert"` per-toast for errors below (which is assertive). One
      //    assertive region for everything would interrupt whatever the user was reading to say
      //    "Photo updated".
      box.setAttribute("role", "status");
      box.setAttribute("aria-live", "polite");
      box.setAttribute("aria-atomic", "false");
      document.body.appendChild(box);
    }
    const t = document.createElement("div");
    t.className = "toast" + (kind ? " " + kind : "");
    // An error is the one kind worth interrupting for; it is also the kind that self-dismisses
    // after 4.2s, so a polite queue could drop it entirely.
    if (kind === "err") t.setAttribute("role", "alert");
    const icon = kind === "ok" ? ICON.check : kind === "err" ? ICON.x : ICON.bell;
    t.innerHTML = icon + '<span class="toast-msg">' + esc(msg) + "</span>";
    let done = false;
    const dismiss = () => {
      if (done) return; done = true;
      t.style.opacity = "0"; t.style.transition = "opacity .3s"; setTimeout(() => t.remove(), 300);
    };
    if (opts.action && opts.action.label) {
      const btn = document.createElement("button");
      btn.type = "button"; btn.className = "toast-action"; btn.textContent = opts.action.label;
      btn.onclick = () => { try { opts.action.onClick && opts.action.onClick(); } finally { dismiss(); } };
      t.appendChild(btn);
      box.appendChild(t);
    } else {
      box.appendChild(t);
    }
    const life = opts.duration != null ? opts.duration : opts.action ? 6000 : kind === "err" ? 4200 : 2600;
    if (life > 0) setTimeout(dismiss, life);
    return { dismiss };
  }

  // skeleton(opts) -> placeholder HTML string while data loads.
  //   { rows: n }                    -> n stacked skeleton lines
  //   { cards: n, cardHeight: px }   -> n card-shaped blocks
  //   { height: px }                 -> one block of a given height
  // Pages set el.innerHTML = S.skeleton({...}) before an await, then replace on resolve.
  function skeleton(opts) {
    opts = opts || {};
    if (opts.cards) {
      const h = opts.cardHeight || 84;
      return `<div class="skel-stack">${Array.from({ length: opts.cards }, () =>
        `<div class="skeleton skel-card" style="height:${h}px"></div>`).join("")}</div>`;
    }
    if (opts.rows) {
      return `<div class="skel-stack">${Array.from({ length: opts.rows }, (_, i) =>
        `<div class="skeleton skel-line"${i % 3 === 2 ? ' style="width:60%"' : ""}></div>`).join("")}</div>`;
    }
    return `<div class="skeleton" style="height:${opts.height || 200}px"></div>`;
  }

  // 🔴 EVERY SKELETON NEEDS AN OWNER FOR THE FAILURE CASE (added 2026-08-17).
  //
  // `skeleton()` above has 13 call sites and only `manage.js` ever replaced one on error. Everywhere
  // else a failed refetch left the skeleton on screen FOREVER: `people.js`'s `load()` had no
  // try/catch at all and is called straight from `oninput`, so a 500 was an unhandled rejection and
  // the page simply read as permanently loading. `boot()` catches the FIRST `pageInit` and toasts,
  // but a toast is gone in 4.2s and the skeleton is not — so the honest signal (a stuck loader) and
  // the informative one (the message) never coexisted, and neither offered a way out. A browser
  // refresh was the only recovery, and it discarded the filters that provoked the error.
  //
  // `loadErr(host, err, retry)` replaces the skeleton with the reason plus a Retry, so the state is
  // legible AND recoverable in the one place it is visible. Two rules:
  //  • Pass `retry` whenever the load is a pure function of on-screen state (a filter, a date
  //    range). Omit it when re-running would repeat a side effect — the button then just does not
  //    render, rather than promising something it should not do (the "a control must never be able
  //    to only fail" rule the task board's footer follows).
  //  • It reads `err.detail` FIRST because `api()` has already flattened FastAPI's error shape into
  //    it; `err.message` alone gives you "Failed to fetch" for a real 403 with a real explanation.
  function loadErr(host, err, retry) {
    const el = typeof host === "string" ? qs(host) : host;
    if (!el) return;
    const msg = (err && (err.detail || err.message)) || "Something went wrong";
    el.innerHTML = `<div class="empty"><div>${esc(msg)}</div>${
      retry ? `<button type="button" class="btn sm ghost empty-retry">Try again</button>` : ""}</div>`;
    if (retry) {
      const b = qs(".empty-retry", el);
      // `() => retry()` and not `retry` — an onclick handler is called with the Event as arg 1, and
      // a loader that takes a parameter would receive it (the app-wide rule in frontend/README.md).
      // Note the consequence for callers: the retry runs with NO arguments, so a loader that needs
      // one must be closed over at the call site — see manage.js's `() => render(key)`.
      if (b) b.onclick = () => retry();
    }
    console.error(err);
  }

  // 🔴 SORTING, FOR EVERY TABLE IN THE APP — and it is the CSS that has been waiting, not the JS.
  //
  // `thead th.sortable` has been styled in styles.css since the first version of this app (cursor,
  // hover colour) and NOTHING ever emitted the class: no table here sorted except the growth table,
  // which rolls its own via `?sort=`. So the affordance was built, styled, and never connected.
  //
  // Mark a `<th class="sortable">` and call `S.sortTable(tableEl)`. Three rules are baked in because
  // each one is a bug this codebase has already paid for:
  //
  //  • 🔴 "—" MEANS UNKNOWN AND SORTS LAST IN BOTH DIRECTIONS. The growth tables learned this the
  //    hard way (frontend/README.md): a person the Mastery Engine could not answer for shows a dash,
  //    and sorting that as a zero renders an outage as "nobody is doing anything". Empty cells get the
  //    same treatment — an absent handover note is not the earliest one.
  //  • **Numbers sort as numbers.** `"9h"` vs `"10h"` as text puts 9 after 10, and every numeric
  //    column here carries a unit or a `%`. The parse is "does the cell start like a number", so
  //    "9h", "10.5", "-2", "83%" and "PHP 1,200" all compare numerically.
  //  • **The control is a real `<button>`**, injected into the th rather than making the th clickable
  //    with `tabindex`. Keyboard-operable and announced for free; `aria-sort` on the th is what a
  //    screen reader reads, so it is set on every change and REMOVED from the other columns.
  //
  // It sorts the DOM rows in place and does not re-fetch, so it composes with whatever filters the
  // page already applied — and a re-render simply calls it again.
  const SORT_UNKNOWN = /^(—|-|–|n\/a|)$/i;
  function sortTable(table, opts) {
    if (!table) return;
    const o = opts || {};
    const heads = qsa("thead th.sortable", table);
    if (!heads.length) return;

    heads.forEach((th, col) => {
      // Idempotent: a page that re-renders its table calls this again on fresh nodes, but a page that
      // calls it twice on the SAME node must not end up with two buttons or two handlers.
      if (th.querySelector(".th-sort")) return;
      const label = th.innerHTML;
      th.innerHTML = `<button type="button" class="th-sort"><span>${label}</span><span class="th-arrow" aria-hidden="true"></span></button>`;
      th.querySelector(".th-sort").onclick = () => {
        // Third click does NOT return to "unsorted": there is no stored original order once rows have
        // been moved, so pretending to restore it would be a lie. asc <-> desc only.
        const dir = th.getAttribute("aria-sort") === "ascending" ? "descending" : "ascending";
        heads.forEach((h) => {
          if (h !== th) { h.removeAttribute("aria-sort"); const a = h.querySelector(".th-arrow"); if (a) a.textContent = ""; }
        });
        th.setAttribute("aria-sort", dir);
        th.querySelector(".th-arrow").textContent = dir === "ascending" ? "▲" : "▼";
        applySort(table, col, dir, o);
      };
    });
  }

  function cellKey(row, col, o) {
    const cells = row.children;
    const cell = cells[col];
    if (!cell) return { unknown: true };
    // An explicit `data-sort` wins, so a caller can sort a formatted cell by its real value — a date
    // rendered "Aug 17" sorts correctly only if the ISO string comes along.
    const raw = (cell.getAttribute("data-sort") || cell.textContent || "").trim();
    if (SORT_UNKNOWN.test(raw)) return { unknown: true };
    if (!o.text) {
      // Strip thousands separators and a leading currency/label prefix, then require what is LEFT to be
      // a complete number with at most a short trailing unit.
      //
      // 🔴 THE `$` ANCHOR IS THE WHOLE POINT, and an ISO DATE is why. A permissive
      // `parseFloat(raw)` "succeeds" on "2026-08-02" and returns 2026 — so every date in a month
      // compared EQUAL, ties kept their original order, and sorting a date column did nothing at all
      // while looking like it worked. That is precisely the `data-sort` value Attendance and Leave
      // pass (found 2026-08-17 by ui.test.js). Anchored, "2026-08-02" has digits after an internal
      // "-" and fails to match, so it falls through to the text branch below — which is CORRECT for
      // ISO, because `YYYY-MM-DD` sorts chronologically as text. A negative like "-2h" still matches,
      // because its "-" is leading.
      const cleaned = raw.replace(/[, ]/g, "").replace(/^[^\d.+-]+/, "");
      if (/^[+-]?\d*\.?\d+[a-z%°]{0,3}$/i.test(cleaned)) {
        const n = parseFloat(cleaned);
        if (!Number.isNaN(n)) return { num: n };
      }
    }
    return { str: raw.toLowerCase() };
  }

  function applySort(table, col, dir, o) {
    const body = table.tBodies[0];
    if (!body) return;
    const rows = Array.from(body.rows).filter((r) => r.children.length > col);
    const mul = dir === "ascending" ? 1 : -1;
    rows.sort((ra, rb) => {
      const a = cellKey(ra, col, o), b = cellKey(rb, col, o);
      // 🔴 Unknown always sinks, regardless of direction — NOT multiplied by `mul`. That is the whole
      // point: reversing the sort must not float an outage to the top.
      if (a.unknown && b.unknown) return 0;
      if (a.unknown) return 1;
      if (b.unknown) return -1;
      if ("num" in a && "num" in b) return (a.num - b.num) * mul;
      return String(a.str ?? a.num).localeCompare(String(b.str ?? b.num)) * mul;
    });
    // One reflow, not one per row.
    const frag = document.createDocumentFragment();
    rows.forEach((r) => frag.appendChild(r));
    body.appendChild(frag);
  }

  const initials = (name) => (String(name || "?").split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join("") || "?").toUpperCase();
  // A photo when the user has one (all serialized users carry profile_pic_url), else the initials
  // chip. This single helper feeds every avatar on every page, so a photo shows everywhere at once.
  const avatar = (u, cls = "") => {
    if (u && u.profile_pic_url) {
      return `<div class="avatar ${cls} has-photo"><img src="${esc(u.profile_pic_url)}" alt="" loading="lazy" decoding="async"></div>`;
    }
    return `<div class="avatar ${cls}">${esc(u ? initials(u.name) : "?")}</div>`;
  };

  // ---- Profile photo upload (shared) ----
  // Resize + square-crop client-side to a small JPEG so uploads are tiny (~30 KB) and the server needs
  // no image library. Returns a Blob. Then uploadAvatar POSTs it and returns the new profile_pic_url.
  function resizeImageToBlob(file, size = 256) {
    return new Promise((resolve, reject) => {
      const url = URL.createObjectURL(file);
      const img = new Image();
      img.onload = () => {
        URL.revokeObjectURL(url);
        const side = Math.min(img.width, img.height);          // cover-crop to a centered square
        const sx = (img.width - side) / 2, sy = (img.height - side) / 2;
        const c = document.createElement("canvas");
        c.width = c.height = size;
        const ctx = c.getContext("2d");
        ctx.drawImage(img, sx, sy, side, side, 0, 0, size, size);
        c.toBlob((b) => (b ? resolve(b) : reject(new Error("Couldn't process that image"))), "image/jpeg", 0.85);
      };
      img.onerror = () => { URL.revokeObjectURL(url); reject(new Error("That file isn't a readable image")); };
      img.src = url;
    });
  }
  async function uploadAvatar(userId, file) {
    if (!/^image\//.test(file.type)) throw new Error("Please choose an image file");
    const blob = await resizeImageToBlob(file);
    const fd = new FormData();
    fd.append("file", blob, "avatar.jpg");
    const res = await api(`/api/people/${userId}/avatar`, { method: "POST", form: fd });
    // Keep the signed-in user's cached object + topbar avatar in sync when they change their own.
    if (USER && USER.id === userId) { USER.profile_pic_url = res.profile_pic_url; refreshUserCard(); }
    return res.profile_pic_url;
  }
  async function removeAvatar(userId) {
    await api(`/api/people/${userId}/avatar`, { method: "DELETE" });
    if (USER && USER.id === userId) { USER.profile_pic_url = null; refreshUserCard(); }
  }
  function refreshUserCard() {
    const card = qs("#user-card"); if (card) { const a = card.querySelector(".avatar"); if (a) a.outerHTML = avatar(USER); }
  }

  const PH = "Asia/Manila";
  function fmtTime(iso) { if (!iso) return "—"; return new Date(iso).toLocaleTimeString("en-PH", { timeZone: PH, hour: "2-digit", minute: "2-digit", hour12: true }); }
  function fmtDate(iso) { if (!iso) return "—"; return new Date(iso).toLocaleDateString("en-PH", { timeZone: PH, month: "short", day: "numeric" }); }
  function fmtDateFull(iso) { if (!iso) return "—"; return new Date(iso).toLocaleDateString("en-PH", { timeZone: PH, weekday: "short", month: "short", day: "numeric", year: "numeric" }); }
  function timeAgo(iso) {
    if (!iso) return ""; const s = (Date.now() - new Date(iso).getTime()) / 1000;
    if (s < 60) return "just now"; if (s < 3600) return Math.floor(s / 60) + "m ago";
    if (s < 86400) return Math.floor(s / 3600) + "h ago"; return Math.floor(s / 86400) + "d ago";
  }

  function priorityDot(p) {
    const hex = COLORS.priorities[p];
    if (hex) return `<span class="dot" style="background:${esc(hex)}"></span>`;
    const c = p === "Urgent" ? "red" : p === "Medium" ? "amber" : "green";  // fallback for unseeded
    return `<span class="dot ${c}"></span>`;
  }
  function labelPills(labels) {
    return (labels || []).map((l) => {
      const hex = COLORS.labels[l] || "#6B7280";  // colour comes from config now (custom-label safe)
      return `<span class="lbl" style="background:${esc(hex)}">${esc(l)}</span>`;
    }).join("");
  }
  function statusPill(s) {
    const map = { OnTime: "green", Late: "amber", Absent: "red", HalfDay: "blue", MissingClockOut: "amber", OnLeave: "violet", Completed: "green", Incomplete: "amber", Missing: "red", Approved: "green", Pending: "amber", Rejected: "red", Active: "green", "On Leave": "violet", Inactive: "grey" };
    return `<span class="pill ${map[s] || "grey"}">${esc(s)}</span>`;
  }

  // ---------------- Modal ----------------
  // modal({ title, body, footer, wide })            -> centered dialog
  // modal({ ..., drawer: true })                     -> right-side slide-in panel (full height)
  // modal({ ..., onClose })                          -> run when it closes, HOWEVER it was closed
  //
  // 🔴 MODALS STACK. Until 2026-08-06 this reused ONE `#modal-ov` element and overwrote its
  // innerHTML, so opening a second dialog DESTROYED the first — and closing the second left
  // nothing behind, because there was only ever one overlay to hide. The task board nests five
  // deep (Park / Request changes / Send back / Delete confirm / Past work all open over an open
  // task), so "Cancel" on any of them threw the user out of the card they were reading. Worse, the
  // card's own close never ran, which is how `?open=<id>` was left in the URL pointing at a modal
  // that was no longer on screen — a refresh then reopened a card the user had cancelled out of.
  //
  // Each call now owns its own overlay node, appended and removed. Three consequences to keep:
  //   • `onClose` fires on EVERY path (button, ✕, backdrop, Esc). Callers that must undo something
  //     on close — the board's `?open=` param — hook it here instead of re-pointing three closers
  //     and hoping they found them all.
  //   • Esc closes the TOP modal only, via ONE document listener held for as long as the stack is
  //     non-empty. The old code added a listener per modal that removed itself only if Escape was
  //     actually pressed, so every dialog closed by a button leaked one for the page's lifetime.
  //   • NOTHING inside a stacked dialog may be found by `id` — ids are not unique while a stack is
  //     open, so a document-wide lookup finds the BOTTOM one. Scope every query to the `root` this
  //     returns (`.modal-body` from `m.root`, never `document`). And scoping alone is not enough for
  //     an ID: this is why the ✕'s own `id="modal-x"` was REMOVED in 2026-08-17 — see the note on
  //     `titleId` below for what a scoped `querySelector("#dup")` is entitled to do instead.
  const modalStack = [];
  let modalKeyHandler = null;
  let modalSeq = 0;

  // 🔴 EVERYTHING BELOW THIS LINE IS THE DIALOG A11Y CONTRACT (added 2026-08-17).
  //
  // `initCommandPalette` further down this file has always done this correctly — `role="dialog"`,
  // `aria-modal`, initial focus, focus restore. `modal()` had NONE of it, which is the app's shared
  // dialog used by every page and nested FIVE DEEP by the task board. So a keyboard user could open
  // a task, press Tab, and walk straight out of the dialog into the page behind it while the overlay
  // still covered the screen — reading and operating controls they could not see. Esc closing the
  // top modal was the only thing that made this survivable.
  //
  // This lifts the palette's pattern into the shared helper. It is deliberately NOT a new mechanism.

  // Everything a keyboard can land on. `:not([disabled])` is load-bearing: this board renders
  // genuinely `disabled` controls (a non-delegator's support picker renders colleagues
  // `selected disabled`), and a trap whose boundary is a dead control cannot be escaped forwards.
  const FOCUSABLE = [
    "a[href]", "button:not([disabled])", "input:not([disabled]):not([type=hidden])",
    "select:not([disabled])", "textarea:not([disabled])", "summary",
    '[tabindex]:not([tabindex="-1"])',
  ].join(",");

  // `offsetParent === null` drops anything inside a `[hidden]` row or a shut `<details>` — the form
  // has both (`.tf-row[hidden]`, the rare-fields block), and a trap that counts invisible controls
  // silently eats Tab presses on the way past them.
  function focusablesIn(root) {
    return qsa(FOCUSABLE, root).filter((el) => el.offsetParent !== null);
  }

  // 🔴 THE COMMAND PALETTE CAN OPEN OVER A MODAL, and when it does it is the top layer — not us.
  // `Ctrl`/`Cmd`+K is bound on `document` and is deliberately NOT gated on the modal stack, so the
  // palette can appear above an open task card. Both this file's modal keydown handler and the
  // palette's own are on `document`, so without this test they BOTH act on one keypress:
  //   • Tab would be trapped into the dialog UNDERNEATH, yanking the caret out of the palette input;
  //   • Escape would close the palette AND the modal beneath it, in one press.
  // The second half was a pre-existing bug; the first would have been introduced by the focus trap.
  // `#cmdk` carries `.open` only while it is showing, which is the cheapest honest test available.
  function paletteOpen() {
    const p = qs("#cmdk");
    return !!p && p.classList.contains("open");
  }

  function closeTopModal() {
    if (paletteOpen()) return;
    const top = modalStack[modalStack.length - 1];
    if (top) top.close();
  }

  // Tab / Shift+Tab cycle within the TOP dialog only. Driven from the one shared keydown listener
  // (see `modalKeyHandler`) rather than one per modal, for the same reason Escape is: a listener per
  // layer is how the pre-2026-08-06 code leaked one per dialog for the page's lifetime.
  function trapTab(e) {
    // The palette owns the top layer when it is up — see `paletteOpen`. It has its own always-present
    // input and needs no trap from us.
    if (paletteOpen()) return;
    const top = modalStack[modalStack.length - 1];
    if (!top || !top.dialog) return;
    const items = focusablesIn(top.dialog);
    if (!items.length) { e.preventDefault(); top.dialog.focus(); return; }
    const first = items[0], last = items[items.length - 1];
    // If focus has escaped the dialog entirely — a stray programmatic focus, or the browser starting
    // a Tab cycle from <body> — pull it back to the appropriate end rather than letting it out.
    if (!top.dialog.contains(document.activeElement)) {
      e.preventDefault(); (e.shiftKey ? last : first).focus(); return;
    }
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  }

  function modal({ title, body, footer, wide, drawer, onClose }) {
    const ov = document.createElement("div");
    ov.className = "overlay" + (drawer ? " drawer-ov" : "");
    // 🔴 A per-overlay id — and the close button lost its id entirely (2026-08-17).
    //
    // `aria-labelledby` CANNOT point at a duplicated id: with a stack open it resolves to the BOTTOM
    // dialog's title, so every dialog would announce itself as the first one. Hence the counter.
    //
    // That investigation turned up a live fragility in the ✕ binding, which was `qs("#modal-x", ov)`.
    // Scoping to `ov` was the right instinct (it is what README §Gotchas tells you to do) but it was
    // resting on DUPLICATE ids existing in the document at all — invalid HTML, and a scoped
    // `querySelector("#dup")` is free to consult the document's id map and answer NULL because the
    // first match lives in another subtree. jsdom does exactly that, so opening a SECOND dialog threw
    // `Cannot set properties of null` and the ✕ was wired to nothing. Rather than scope harder, the
    // duplicate is gone: the head's close button is found by position and held by reference.
    const titleId = "modal-title-" + (++modalSeq);
    // `tabindex="-1"` makes the dialog itself focusable as a fallback target (a body with no
    // controls, e.g. a plain message), without putting it in the Tab order.
    ov.innerHTML = `<div class="modal ${wide ? "wide" : ""}${drawer ? " as-drawer" : ""}"
        role="dialog" aria-modal="true" aria-labelledby="${titleId}" tabindex="-1">
      <div class="modal-head"><h3 id="${titleId}">${esc(title)}</h3><button type="button" class="x-close" aria-label="Close">${ICON.x}</button></div>
      <div class="modal-body">${body}</div>
      ${footer ? `<div class="modal-foot">${footer}</div>` : ""}</div>`;
    document.body.appendChild(ov);
    // `.overlay` is display:none until `.open`, and there is no transition, so this can go on in
    // the same frame the node is inserted.
    ov.classList.add("open");
    // Tuck the coach FAB away while anything is open so it can't sit over the footer buttons.
    const coachFab = qs("#coach-fab"); if (coachFab) coachFab.classList.add("hidden");

    const dialog = qs(".modal", ov);
    // Scoped to `.modal-head` on purpose: a CALLER may render its own `.x-close` controls inside the
    // body (gym.js's routine editor draws one per exercise and per set), and "the dialog's close
    // button" must never resolve to one of those. Held by reference from here on.
    const closeBtn = qs(".modal-head .x-close", ov);
    // Captured BEFORE anything is focused, and held per-entry rather than in one shared slot — that
    // is what makes restore stack-aware: closing a nested confirm returns you to the control inside
    // the task card underneath, not to whatever opened the bottom of the stack.
    const lastFocus = document.activeElement;

    let closed = false;
    const entry = { close: () => close(), dialog };
    function close() {
      // Double-close is ordinary here: a caller's own button handler runs alongside the ✕ and the
      // backdrop, and `act()` on the board closes a modal that a failed request may already have.
      if (closed) return;
      closed = true;
      const i = modalStack.indexOf(entry);
      if (i >= 0) modalStack.splice(i, 1);
      ov.remove();
      // The FAB comes back only when the LAST layer goes, or cancelling a confirm would pop it
      // back over the task modal still sitting underneath.
      if (!modalStack.length) {
        const f = qs("#coach-fab"); if (f) f.classList.remove("hidden");
        if (modalKeyHandler) { document.removeEventListener("keydown", modalKeyHandler); modalKeyHandler = null; }
      }
      // Put focus back where it came from. Guarded three ways: the element may have been REMOVED by
      // the very save this dialog performed (a re-rendered board row), in which case focusing it does
      // nothing and would leave focus on <body> — so fall back to the dialog now under us, if any.
      if (lastFocus && lastFocus.focus && document.contains(lastFocus)) lastFocus.focus();
      else {
        const under = modalStack[modalStack.length - 1];
        if (under && under.dialog) under.dialog.focus();
      }
      if (onClose) onClose();
    }

    closeBtn.onclick = close;
    ov.onclick = (e) => { if (e.target === ov) close(); };
    modalStack.push(entry);
    if (!modalKeyHandler) {
      modalKeyHandler = (e) => {
        if (e.key === "Escape") closeTopModal();
        else if (e.key === "Tab") trapTab(e);
      };
      document.addEventListener("keydown", modalKeyHandler);
    }

    // 🔴 SYNCHRONOUS, and that is the whole reason it works. Several callers focus their own field
    // right after `modal()` returns (`#t-name` on the task form, `#a-title`, manage.js's generated
    // password, growth.js's entry box). Because this runs first, their explicit choice overrides this
    // default — a `requestAnimationFrame` here (which is what the command palette does, correctly,
    // for its own always-present input) would fire AFTER them and STEAL focus back.
    // Never LAND on the ✕: it is first in DOM order (the head precedes the body), and opening a
    // dialog with the keyboard already on "discard this" is the one default worth avoiding. Compared
    // by reference, not by class — a caller's own `.x-close` buttons in the body are ordinary
    // controls and may legitimately be the first thing to focus.
    // 🔴 It is only skipped for the INITIAL landing. The ✕ stays in the Tab cycle (`trapTab` reads
    // `focusablesIn` unfiltered), because making it keyboard-unreachable is the exact bug this whole
    // change exists to fix.
    const initial = focusablesIn(dialog).filter((el) => el !== closeBtn);
    (initial[0] || dialog).focus();

    return { close, root: ov };
  }

  // ---------------- Shell ----------------
  let USER = null;

  function buildShell() {
    const view = qs("#view");
    const title = document.body.dataset.title || "Sentinel";
    const path = location.pathname;
    // The page title lives in each page's own header + the browser tab — not repeated in the topbar.
    document.title = title === "Sentinel" ? "Sentinel" : `${title} · Sentinel`;

    const navItems = renderNav(path);

    const shell = document.createElement("div");
    shell.className = "app";
    shell.innerHTML = `
      <aside class="side" id="side">
        <div class="brand">
          <a class="brand-logo" data-brand-logo href="https://agoradatadriven.com" title="Agora Data Driven">${brandSlotHTML()}</a>
          <span class="badge-sentinel" hidden>Sentinel</span>
        </div>
        <nav class="nav">${navItems}</nav>
        <div class="side-foot">
          <div class="user-card" id="user-card" title="Edit your profile" style="cursor:pointer">
            ${avatar(USER)}
            <div class="who"><div class="n">${esc(USER.name)}</div><div class="r">${esc(USER.role_label || USER.role)}</div></div>
          </div>
          ${/* Collapse the rail to icons. In the FOOTER, not the brand: the brand is a link to
                agoradatadriven.com and putting a second control inside it makes both harder to hit.
                It is desktop-only by CSS — under 900px the rail is already an off-canvas drawer with
                its own hamburger, so a second way to narrow it would be two controls fighting over
                one surface. */""}
          <button class="side-collapse" id="side-collapse" aria-label="Collapse the sidebar" aria-pressed="false">
            ${ICON.chev}<span class="nav-label">Collapse</span>
          </button>
        </div>
      </aside>
      <div class="main">
        <header class="top">
          <button class="iconbtn hamburger" id="ham" aria-label="Menu">${ICON.menu}</button>
          <button class="cmdk-trigger" id="cmdk-trigger" title="Search (Ctrl K)" aria-label="Open command palette">${ICON.search}<span>Search anything</span><kbd>Ctrl K</kbd></button>
          ${/* `role="group"` + a label, because these two buttons only mean something as a PAIR — read
                one at a time they are "Light mode" / "Dark mode" with no hint that they are one
                control. `aria-pressed` is set alongside the `.on` class by `setTheme`, so the current
                theme is announced rather than only coloured in. */""}
          <div class="theme-toggle" id="theme-toggle" role="group" aria-label="Colour theme">
            <button type="button" data-set-theme="light" title="Light mode" aria-label="Light mode">${ICON.sun}</button>
            <button type="button" data-set-theme="dark" title="Dark mode" aria-label="Dark mode">${ICON.moon}</button>
          </div>
          <div style="position:relative">
            <button class="iconbtn" id="bell" aria-label="Notifications">${ICON.bell}<span class="bdot" id="bell-count" style="display:none"></span></button>
            <div class="notif-panel" id="notif-panel"></div>
          </div>
          ${/* `title` alone WAS the accessible name here, which works but is the weakest source and is
                now empty of content entirely: the icon inside carries `aria-hidden` (see `P`), so
                without an explicit label this button would announce as nothing at all. */""}
          <button class="iconbtn" id="logout" title="Log out" aria-label="Log out">${ICON.logout}</button>
          <div class="sub" id="top-sub" hidden></div>
        </header>
        <div class="ctxbar" id="ctxbar" hidden></div>
        <div class="content"></div>
      </div>`;
    document.body.insertBefore(shell, view);
    qs(".content", shell).appendChild(view);

    const scrim = document.createElement("div"); scrim.className = "scrim"; scrim.id = "scrim"; document.body.appendChild(scrim);
    const side = qs("#side");
    const toggle = () => { side.classList.toggle("open"); scrim.classList.toggle("open"); };
    qs("#ham").onclick = toggle; scrim.onclick = toggle;
    wireSideCollapse();
    // Hub siblings render as tabs in the context bar under the topbar (flat rail, no accordions).
    renderContextBar(path);
    qs("#logout").onclick = doLogout;
    // Light/dark toggle (setTheme is shared with the command palette)
    qsa("#theme-toggle button").forEach((b) => b.onclick = () => setTheme(b.dataset.setTheme));
    setTheme(document.documentElement.getAttribute("data-theme") || "light");
    const uc = qs("#user-card"); if (uc) uc.onclick = openChangePassword;

    startClock();
    wireBell();
    initCommandPalette();
    mountAssistant();
  }

  // ---------------- Holistic AI coach (global) ----------------
  // The SAME Study Assistant that lives in the Mastery Engine, surfaced on every Sentinel page as a
  // floating widget. It's an iframe of the engine's assistant-only view; the shared `ag_sso` cookie
  // authenticates the viewer, and the engine feeds it the worker's holistic profile server-side. We
  // create the iframe lazily on first open (so no full-viewport overlay ever swallows page clicks)
  // and keep it alive after, so the conversation persists while navigating within a session.
  //
  // 🔴 ONE DOOR PER PAGE. There is only one assistant in the estate: this FAB, the engine's own
  // dock and "Coach mode" are a frame, a button and a toggle over the same widget and the same
  // `/api/assistant/chat` thread store. On a page that already embeds the engine, BOTH buttons
  // rendered — ours at right:24px, the engine's `#assistantDock` at right:20px inside the iframe,
  // stacked in one corner, opening the same assistant with different powers. See ENGINE_PAGES.
  const ENGINE_PAGES = ["/academy", "/philosophical", "/spiritual"];

  async function mountAssistant() {
    if (qs("#coach-fab")) return;                 // already mounted this page-load
    let cfg;
    try { cfg = await api("/api/academy/config"); } catch (e) { return; }
    const base = cfg && cfg.assistant_url;
    if (!base) return;                            // engine not configured — no coach

    // On an engine page the in-frame dock wins, because it is a strict SUPERSET of this FAB: it
    // proposes the same profile edits (gated on being in a host frame, which it is — the old
    // `actions=1` param gated nothing and is gone from both sides), AND it is the only one of the
    // two that can SEE the learner's screen — the current question, the flashcard, the open visual
    // guide's active tab. This FAB frames a blank engine, so it never can.
    // So we mount everything here EXCEPT the button. 🔴 Mount, never early-return: the
    // `agora-coach-action` listener at the bottom of this function is what EXECUTES an Approve,
    // and those pages' in-frame panel is now the only thing sending one.
    const onEnginePage = ENGINE_PAGES.some(
      (p) => location.pathname === p || location.pathname.startsWith(p + "/"),
    );

    const style = document.createElement("style");
    style.textContent = `
      #coach-fab{position:fixed;right:24px;bottom:24px;z-index:90;display:flex;align-items:center;gap:9px;
        border:none;cursor:pointer;padding:0 18px 0 15px;height:54px;border-radius:var(--pill);
        background:linear-gradient(135deg,#9484FB 0%,#5C4BD0 100%);color:#fff;font:600 14px/1 Inter,sans-serif;
        box-shadow:0 10px 30px rgba(92,75,208,.42);transition:transform .15s ease,box-shadow .15s ease}
      #coach-fab:hover{transform:translateY(-2px);box-shadow:0 14px 38px rgba(92,75,208,.55)}
      #coach-fab svg{width:22px;height:22px;stroke:#fff}
      #coach-fab.hidden{display:none}
      /* Its OWN class, not .hidden: modals toggle .hidden to keep the FAB off their footer, and
         restoring it must not resurrect the button on a page that suppressed it for good. */
      #coach-fab.on-engine-page{display:none}
      #coach-panel{position:fixed;right:24px;bottom:24px;z-index:91;width:min(420px,calc(100vw - 32px));
        height:min(660px,calc(100vh - 96px));background:var(--card);border:1px solid var(--line);
        border-radius:var(--radius);box-shadow:var(--shadow-lg);display:none;flex-direction:column;overflow:hidden}
      #coach-panel.open{display:flex}
      #coach-head{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:12px 14px;
        border-bottom:1px solid var(--line);background:linear-gradient(135deg,rgba(148,132,251,.14),transparent)}
      #coach-head .t{display:flex;align-items:center;gap:9px;font:700 14px/1.2 Inter,sans-serif;color:var(--text)}
      #coach-head .t svg{width:18px;height:18px;stroke:var(--violet-d)}
      #coach-head .t small{display:block;font:500 11px/1.3 Inter,sans-serif;color:var(--sub);margin-top:2px}
      /* A <button> since 2026-08-17 (see .x-close in styles.css) — the resets have to be repeated
         here because this rule sets 'color' and would otherwise inherit the UA button chrome.
         Single quotes, not backticks: this comment lives inside a template literal. */
      #coach-head .x-close{cursor:pointer;color:var(--sub);display:flex;background:none;border:none;padding:0;width:auto}
      #coach-frame{flex:1;border:0;width:100%;background:var(--card)}
      @media (max-width:520px){#coach-panel{right:8px;left:8px;bottom:8px;width:auto;height:min(80vh,660px)}}`;
    document.head.appendChild(style);

    const fab = document.createElement("button");
    fab.id = "coach-fab";
    fab.setAttribute("aria-label", "Open your coach");
    fab.innerHTML = `${ICON.sparkle}<span>Coach</span>`;
    if (onEnginePage) fab.classList.add("on-engine-page");
    document.body.appendChild(fab);

    const panel = document.createElement("div");
    panel.id = "coach-panel";
    panel.innerHTML = `
      <div id="coach-head">
        <div class="t">${ICON.sparkle}<div>Your Coach<small>Knows your growth: learning, training, goals</small></div></div>
        <button type="button" class="x-close" id="coach-x" aria-label="Close coach">${ICON.x}</button>
      </div>
      <div id="coach-frame-wrap" style="flex:1;display:flex"></div>`;
    document.body.appendChild(panel);

    let framed = false;
    const open = () => {
      if (!framed) {
        const f = document.createElement("iframe");
        f.id = "coach-frame";
        f.allow = "microphone; clipboard-write";
        // {engine}/?embed=assistant&theme=… — no `&actions=1`: it was inert (see the engine's
        // app.js boot block) and reads as a gate that isn't there.
        f.src = engineUrl(base);
        qs("#coach-frame-wrap", panel).appendChild(f);
        framed = true;
      }
      panel.classList.add("open"); fab.classList.add("hidden");
    };
    const close = () => { panel.classList.remove("open"); fab.classList.remove("hidden"); };
    fab.onclick = open;
    qs("#coach-x", panel).onclick = close;
    // Let a page deep-link into the coach (e.g. the Development hub's "Ask your coach" button).
    window.SentinelOpenCoach = open;

    // --- Coach edit-actions: execute an assistant-proposed change in the USER's session ----------
    // The coach (in the iframe) proposes an edit; the user taps Approve in the chat; only THEN does
    // the iframe postMessage it here. We execute it against the same /api/development endpoints the
    // user uses (their cookie + CSRF), then report the result back so the chat card resolves. Every
    // op is a fixed endpoint with a whitelisted body — the coach can't reach anything else.
    const coachOrigin = new URL(base, location.href).origin;
    const DEV = "/api/development";
    const GYM = "/api/gym";
    const pick = (o, keys) => { const r = {}; keys.forEach((k) => { if (o && o[k] !== undefined) r[k] = o[k]; }); return r; };
    const PR = ["exercise_name", "weight_value", "weight_unit", "reps", "detail", "achieved_on", "notes"];
    const PHYS = ["name", "kind", "target_value", "current_value", "unit", "direction", "notes", "status"];
    const GOAL = ["title", "dimension", "description", "target_date", "status", "progress_pct"];
    const ACH = ["title", "description", "achieved_on"];
    // `dimension` files the entry under one of the four growth areas. Without it in this whitelist
    // every coach-created entry silently lands in Spiritual (the model default) no matter which
    // area the coach proposed — the server validates the value, this just has to pass it through.
    const GROW = ["dimension", "kind", "title", "detail", "status"];
    const SKILL = ["name", "level", "source", "note"];
    const METRIC = ["body_fat_pct", "weight_kg", "date", "notes"];
    const RESUME = ["headline", "resume_text", "resume_file_url"];
    const READ = ["status", "reflection", "rating"];
    const AREA = ["deadline", "other_info"];

    function coachExecute(action) {
      const a = action || {}, args = a.args || {}, id = args.id;
      switch (a.op) {
        case "add_body_metric": return api(`${DEV}/body-metrics`, { method: "POST", body: pick(args, METRIC) });
        case "add_pr": return api(`${DEV}/prs`, { method: "POST", body: pick(args, PR) });
        case "update_pr": return api(`${DEV}/prs/${id}`, { method: "PATCH", body: pick(args, PR) });
        case "delete_pr": return api(`${DEV}/prs/${id}`, { method: "DELETE" });
        // Physical TARGET goals (lift/run/skill numbers being chased — drive the Physical ring).
        case "add_physical_goal": return api(`${DEV}/physical-goals`, { method: "POST", body: pick(args, PHYS) });
        case "update_physical_goal": return api(`${DEV}/physical-goals/${id}`, { method: "PATCH", body: pick(args, PHYS) });
        case "delete_physical_goal": return api(`${DEV}/physical-goals/${id}`, { method: "DELETE" });
        case "update_resume": return api(`${DEV}/resume`, { method: "PATCH", body: pick(args, RESUME) });
        case "add_achievement": return api(`${DEV}/achievements`, { method: "POST", body: pick(args, ACH) });
        case "update_achievement": return api(`${DEV}/achievements/${id}`, { method: "PATCH", body: pick(args, ACH) });
        case "delete_achievement": return api(`${DEV}/achievements/${id}`, { method: "DELETE" });
        case "add_goal": return api(`${DEV}/goals`, { method: "POST", body: pick(args, GOAL) });
        case "update_goal": return api(`${DEV}/goals/${id}`, { method: "PATCH", body: pick(args, GOAL) });
        case "delete_goal": return api(`${DEV}/goals/${id}`, { method: "DELETE" });
        case "add_growth": return api(`${DEV}/growth`, { method: "POST", body: pick(args, GROW) });
        case "update_growth": return api(`${DEV}/growth/${id}`, { method: "PATCH", body: pick(args, GROW) });
        case "delete_growth": return api(`${DEV}/growth/${id}`, { method: "DELETE" });
        case "add_skill": return api(`${DEV}/skills`, { method: "POST", body: pick(args, SKILL) });
        case "update_skill": return api(`${DEV}/skills/${id}`, { method: "PATCH", body: pick(args, SKILL) });
        case "delete_skill": return api(`${DEV}/skills/${id}`, { method: "DELETE" });
        case "set_reading_progress": return api(`${DEV}/reading/${args.reading_item_id}/progress`, { method: "PUT", body: pick(args, READ) });
        // Growth-area settings: the pace deadline + the per-dimension "Other info" dump.
        // Keyed by dimension NAME (spiritual|professional|philosophical|physical), not an id.
        case "update_area": return api(`${DEV}/areas/${encodeURIComponent(args.dimension || "")}`, { method: "PATCH", body: pick(args, AREA) });
        // Gym schedule (the weekly split + per-date overrides that drive the calendar).
        case "set_gym_week": return api(`${GYM}/plan/week`, { method: "POST", body: { week: args.week || {}, ...(args.cardio ? { cardio: args.cardio } : {}) } });
        case "set_gym_day": return api(`${GYM}/plan/day`, { method: "POST", body: pick(args, ["date", "day_type", "cardio"]) });
        case "clear_gym_day": return api(`${GYM}/plan/day/${args.date}`, { method: "DELETE" });
        default: return Promise.reject(new Error("Unknown action: " + a.op));
      }
    }

    window.addEventListener("message", async (e) => {
      const d = e.data;
      if (!d || d.type !== "agora-coach-action") return;
      if (e.origin !== coachOrigin) return;   // only our own engine iframe may drive edits
      const reply = (ok, message) => { try { e.source.postMessage({ type: "agora-coach-action-result", id: d.id, ok, message }, e.origin); } catch (x) { /* frame gone */ } };
      try {
        await coachExecute(d.action);
        const label = (d.action && d.action.summary) || "Updated";
        reply(true, label);
        toast("Coach: " + label, "ok");
        // Refresh whichever page is showing (Development hub or Gym) so the change appears at once.
        if (window.SentinelReloadDevelopment) window.SentinelReloadDevelopment();
        if (window.SentinelReloadGym) window.SentinelReloadGym();
      } catch (err) {
        reply(false, err.detail || err.message || "Couldn't apply that");
      }
    });
  }

  function startClock() {
    const el = qs("#clock"); if (!el) return;
    const tick = () => { el.textContent = new Date().toLocaleTimeString("en-PH", { timeZone: PH, hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: true }); };
    tick(); setInterval(tick, 1000);
  }

  // ---------------- Notifications ----------------
  // 🔴 `type` HAS ALWAYS BEEN SENT AND WAS NEVER READ. `serializers.notification_dict` publishes it,
  // `constants` defines six of them, and the panel rendered every row identically — so "your leave
  // was approved", "this task is overdue" and an all-staff announcement were three lines of grey text
  // that could only be told apart by reading them. This map is what makes the list scannable, and it
  // is keyed by the SAME constants the server writes (constants.NOTIF_*), not by prose in the title.
  //
  // An unmapped type falls back to the bell rather than being dropped: a new notification type must
  // never become invisible because nobody updated a lookup table here.
  const NOTIF_KINDS = {
    approval:      { icon: "inbox",  tone: "amber",  label: "Approval" },
    task_assigned: { icon: "board",  tone: "green",  label: "Task" },
    task_review:   { icon: "check",  tone: "amber",  label: "Review" },
    task_overdue:  { icon: "clock",  tone: "red",    label: "Overdue" },
    gym_missing:   { icon: "dumbbell", tone: "grey", label: "Gym" },
    announcement:  { icon: "sparkle", tone: "violet", label: "Announcement" },
  };
  const notifKind = (t) => NOTIF_KINDS[t] || { icon: "bell", tone: "grey", label: "Update" };

  /** Which day bucket a notification falls in, in the viewer's own timezone.
   *  Day boundaries, not "24 hours ago" — "yesterday" has to mean the calendar day, or a 9am item
   *  files under Today at 8am the next morning. */
  function dayBucket(iso) {
    if (!iso) return "Earlier";
    const d = new Date(iso);
    const midnight = new Date(); midnight.setHours(0, 0, 0, 0);
    if (d >= midnight) return "Today";
    const y = new Date(midnight); y.setDate(y.getDate() - 1);
    if (d >= y) return "Yesterday";
    return "Earlier";
  }

  // The bell's badge — ONE definition of how it renders, because THREE things move it: the shell on
  // every navigation, the panel after "Mark all read", and the command palette's own action. Two of
  // those used to poke `style.display` themselves.
  function setBadge(n) {
    const badge = qs("#bell-count");
    if (!badge) return;
    if (n > 0) { badge.textContent = n; badge.style.display = ""; } else { badge.style.display = "none"; }
  }

  // 🔴 The shell asks for the COUNT, not the list. This runs on every single navigation, and it used
  // to call `GET /api/notifications` — serializing up to 50 notifications to draw a one-character
  // badge, and re-rendering the whole (closed) panel with them. The panel is built when it opens.
  async function refreshBadge() {
    try { setBadge((await api("/api/notifications/unread-count")).count); }
    catch (e) { /* the badge is decoration — a failed count must never cost anybody the shell */ }
  }

  async function wireBell() {
    const bell = qs("#bell"), panel = qs("#notif-panel");
    let unreadOnly = false;

    function rowHTML(n) {
      const k = notifKind(n.type);
      return `<div class="notif ${n.is_read ? "" : "unread"}" data-id="${n.id}" data-link="${esc(n.link || "")}"
                   role="button" tabindex="0">
        <span class="n-ic ${k.tone}" title="${esc(k.label)}">${ICON[k.icon] || ICON.bell}</span>
        <div class="n-body">
          <div class="nt">${esc(n.title)}</div>
          ${n.body ? `<div class="nb">${esc(n.body)}</div>` : ""}
          <div class="ntime">${esc(k.label)} · ${timeAgo(n.created_at)}</div>
        </div>
        ${n.is_read ? "" : `<span class="n-dot" aria-label="Unread"></span>`}
      </div>`;
    }

    async function load() {
      const d = await api("/api/notifications");
      // The list response carries the count already, so the open panel never needs a second request.
      setBadge(d.unread_count);

      const items = unreadOnly ? d.items.filter((n) => !n.is_read) : d.items;
      // Grouped by day, in the order the server already sorted them (newest first) — the buckets are
      // emitted in that same order rather than from a fixed list, so an empty one never prints a
      // heading with nothing under it.
      let body = "";
      let lastBucket = "";
      items.forEach((n) => {
        const b = dayBucket(n.created_at);
        if (b !== lastBucket) { body += `<div class="n-day">${b}</div>`; lastBucket = b; }
        body += rowHTML(n);
      });
      const empty = unreadOnly
        ? "Nothing unread. Switch to All to see everything."
        : "You're all caught up.";

      panel.innerHTML = `<div class="h">
          <strong>Notifications${d.unread_count ? ` <span class="n-count">${d.unread_count}</span>` : ""}</strong>
          <div class="seg sm" id="n-filter" role="tablist">
            <button type="button" data-f="all" class="${unreadOnly ? "" : "on"}" role="tab">All</button>
            <button type="button" data-f="unread" class="${unreadOnly ? "on" : ""}" role="tab">Unread</button>
          </div>
        </div>
        <div class="notif-list">${body || `<div class="empty">${empty}</div>`}</div>
        ${/* The action only exists while it can do something — a permanently visible "Mark all read"
              on an empty inbox is a control that does nothing, the same rule the task board's Clear
              button follows. */""}
        ${d.unread_count ? `<div class="n-foot"><button class="btn sm ghost" id="read-all">Mark all ${d.unread_count} as read</button></div>` : ""}`;

      const ra = qs("#read-all", panel);
      if (ra) ra.onclick = async (e) => { e.stopPropagation(); await api("/api/notifications/read-all", { method: "PATCH" }); load(); };
      qsa("#n-filter button", panel).forEach((b) => b.onclick = (e) => {
        e.stopPropagation(); unreadOnly = b.dataset.f === "unread"; load();
      });
      const open = async (el) => {
        await api(`/api/notifications/${el.dataset.id}/read`, { method: "PATCH" });
        if (el.dataset.link) location.href = el.dataset.link; else load();
      };
      qsa(".notif", panel).forEach((el) => {
        el.onclick = () => open(el);
        // The row is a `div` acting as a button, so it has to answer the keyboard like one.
        el.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(el); } };
      });
    }
    bell.onclick = (e) => { e.stopPropagation(); panel.classList.toggle("open"); if (panel.classList.contains("open")) load(); };
    document.addEventListener("click", (e) => { if (!panel.contains(e.target) && e.target !== bell) panel.classList.remove("open"); });
    refreshBadge();
  }

  // ---------------- Custom logo ----------------
  // If /static/img/logo.svg (or .png) exists, swap it into every [data-brand-logo] slot.
  // We probe by loading the image first, so a missing logo never shows a broken image —
  // the built-in AGORA mark simply stays.
  function tryImg(url) {
    return new Promise((res, rej) => { const i = new Image(); i.onload = () => res(url); i.onerror = () => rej(); i.src = url; });
  }
  // The lockup already carries the "SENTINEL" wordmark, so the pill is redundant once a custom
  // logo is showing (only the "Sentinel" pill — the scanner's "Scanner" pill must stay).
  function setSentinelPillHidden(hide) {
    qsa(".badge-sentinel").forEach((b) => { if (b.textContent.trim().toLowerCase() === "sentinel") b.hidden = hide; });
  }
  function applyBrandLogo() {
    const slots = qsa("[data-brand-logo]");
    if (!slots.length) return;
    const candidates = logoCandidates();
    (function pick(i) {
      if (i >= candidates.length) {
        // No custom logo file at all — fall back to the built-in mark, and bring the pill back
        // since nothing else names the product then.
        slots.forEach((s) => { s.innerHTML = AGORA_LOGO; });
        setSentinelPillHidden(false);
        return;
      }
      tryImg(candidates[i]).then((url) => {
        // Skip the rewrite when this slot already shows the winning art (the normal path after
        // brandSlotHTML painted it) — reassigning innerHTML would re-create the <img> and flicker.
        slots.forEach((s) => {
          const cur = s.querySelector("img.brand-img");
          if (!cur || cur.getAttribute("src") !== url) s.innerHTML = `<img class="brand-img" src="${url}" alt="Sentinel">`;
        });
        setSentinelPillHidden(true);
      }).catch(() => pick(i + 1));
    })(0);
  }

  // ---------------- Change password ----------------
  function openChangePassword() {
    const m = modal({
      title: "Your profile",
      body: `<div class="profile-photo-row">
          <div id="cp-avatar">${avatar(USER, "lg")}</div>
          <div>
            <div class="section-label">Profile photo</div>
            <div class="sub" style="font-size:12px;margin:2px 0 8px">Shown across Sentinel so people recognise you.</div>
            <div class="row" style="gap:6px">
              <button class="btn sm ghost" id="cp-photo-btn">${ICON.plus}${USER.profile_pic_url ? "Change" : "Add photo"}</button>
              <button class="btn sm ghost" id="cp-photo-del"${USER.profile_pic_url ? "" : " hidden"}>Remove</button>
              <input type="file" id="cp-photo-file" accept="image/*" hidden>
            </div>
          </div>
        </div>
        <div class="section-label" style="margin:18px 0 6px">Change password</div>
        <label class="field"><span>Current password</span><input type="password" id="cp-cur" autocomplete="current-password" placeholder="Leave blank if none set"></label>
        <label class="field"><span>New password</span><input type="password" id="cp-new" autocomplete="new-password" placeholder="At least 6 characters"></label>
        <label class="field"><span>Confirm new password</span><input type="password" id="cp-cnf" autocomplete="new-password"></label>`,
      footer: `<button class="btn ghost" id="cp-cancel">Close</button><button class="btn primary" id="cp-save">Update password</button>`,
    });

    // Photo upload/remove (own account). Re-render the modal avatar + topbar in place.
    const repaint = () => { const b = qs("#cp-avatar"); if (b) b.innerHTML = avatar(USER, "lg"); const del = qs("#cp-photo-del"); if (del) del.hidden = !USER.profile_pic_url; const bt = qs("#cp-photo-btn"); if (bt) bt.lastChild.textContent = USER.profile_pic_url ? "Change" : "Add photo"; };
    const fileInput = qs("#cp-photo-file");
    qs("#cp-photo-btn").onclick = () => fileInput.click();
    fileInput.onchange = async () => {
      const f = fileInput.files && fileInput.files[0];
      if (!f) return;
      try { await uploadAvatar(USER.id, f); repaint(); toast("Photo updated", "ok"); }
      catch (e) { toast(e.detail || e.message || "Couldn't upload photo", "err"); }
      finally { fileInput.value = ""; }
    };
    qs("#cp-photo-del").onclick = async () => {
      try { await removeAvatar(USER.id); repaint(); toast("Photo removed", "ok"); }
      catch (e) { toast(e.detail || "Couldn't remove photo", "err"); }
    };

    qs("#cp-cancel").onclick = m.close;
    qs("#cp-save").onclick = async () => {
      const nw = qs("#cp-new").value, cnf = qs("#cp-cnf").value;
      if (nw.length < 6) return toast("Password must be at least 6 characters", "err");
      if (nw !== cnf) return toast("New passwords don't match", "err");
      try {
        await api("/api/auth/change-password", { method: "POST", body: { current_password: qs("#cp-cur").value, new_password: nw } });
        toast("Password updated", "ok"); m.close();
      } catch (e) { toast(e.detail || "Couldn't update password", "err"); }
    };
  }

  // ---------------- Theme + shared actions ----------------
  function setTheme(t) {
    document.documentElement.setAttribute("data-theme", t);
    try { localStorage.setItem(THEME_KEY, t); } catch (e) { /* private mode */ }
    // `.on` is the colour; `aria-pressed` is the same fact for anyone who cannot see it. Set together
    // here so they can never disagree — the toggle's whole state lived in a class until 2026-08-17.
    qsa("#theme-toggle button").forEach((b) => {
      const on = b.dataset.setTheme === t;
      b.classList.toggle("on", on);
      b.setAttribute("aria-pressed", on ? "true" : "false");
    });
    applyBrandLogo();
    themeEmbeds(t);
  }
  // Every Mastery Engine we embed (the Professional / Philosophical / Spiritual tabs and the
  // Coach FAB) is a cross-origin iframe, so it can't read our theme — we hand it over twice:
  // as `&theme=` on the src (see engineUrl below, for the initial paint) and as this message
  // when the toggle moves, so a running engine flips with the page instead of staying light
  // inside a dark one until the next reload. The engine's theme.js accepts it only from its own
  // parent window. Payload is a colour-scheme name, hence the "*" target origin.
  function themeEmbeds(t) {
    qsa("iframe").forEach((f) => {
      try { f.contentWindow.postMessage({ type: "agora-theme", theme: t }, "*"); } catch (e) { /* frame gone */ }
    });
  }
  // The `&theme=` an engine iframe should boot with. Every embed builds its src through this.
  const engineUrl = (base, extra) =>
    base + (extra || "") + "&theme=" + encodeURIComponent(currentTheme());
  const currentTheme = () => document.documentElement.getAttribute("data-theme") || "light";
  async function doLogout() { try { await api("/api/auth/logout", { method: "POST" }); } finally { location.href = "https://agoradatadriven.com"; } }
  function navAllowed(n) {
    if (n.hideRoles && n.hideRoles.includes(USER.role)) return false;
    if (n.roles) return n.roles.includes(USER.role);
    if (n.min) return (ROLE_RANK[USER.role] || 0) >= ROLE_RANK[n.min];
    return true;
  }

  // ---------------- Collapsible rail ----------------
  // An icon-only sidebar, so a wide page (the task board is five 288px columns) gets its 172px back.
  //
  // 🔴 THE CLASS GOES ON `documentElement`, AND IT IS APPLIED AT SCRIPT PARSE TIME, NOT IN `mount()`.
  // The frontend has no build step and every page is a thin shell that JS fills in, so the sidebar
  // does not exist until `mount()` runs. If the collapsed state were applied there, every navigation
  // would paint a 248px rail and then snap it to 76px — a visible flash on every page, on every load,
  // for anyone who chose the collapsed rail. Applying it to `:root` while the body is still empty
  // means the very first paint is already correct. (Same reasoning as the `data-theme` attribute,
  // which is set the same way for the same reason.)
  const SIDE_KEY = "sentinel.side.collapsed";
  const sideCollapsed = () => {
    try { return localStorage.getItem(SIDE_KEY) === "1"; } catch (e) { return false; }
  };
  if (sideCollapsed()) document.documentElement.classList.add("side-narrow");

  function wireSideCollapse() {
    const btn = qs("#side-collapse");
    if (!btn) return;
    const paint = () => {
      const on = document.documentElement.classList.contains("side-narrow");
      btn.setAttribute("aria-pressed", String(on));
      btn.setAttribute("aria-label", on ? "Expand the sidebar" : "Collapse the sidebar");
      btn.title = on ? "Expand the sidebar" : "Collapse the sidebar";
    };
    paint();
    btn.onclick = () => {
      const on = document.documentElement.classList.toggle("side-narrow");
      try { localStorage.setItem(SIDE_KEY, on ? "1" : "0"); } catch (e) { /* private mode */ }
      paint();
    };
  }

  // A single sidebar link. `title` is load-bearing rather than decorative: when the rail is
  // collapsed to icons the label span is hidden, and without a title the whole rail becomes a column
  // of unlabelled glyphs. It is set here, on the one function that builds every row, so a new
  // destination cannot arrive without one.
  function navLink(n, path) {
    return `<a href="${n.href}" class="${path === n.href ? "active" : ""}" title="${esc(n.label)}">${ICON[n.icon]}<span class="nav-label">${esc(n.label)}</span></a>`;
  }

  // Renders the flat rail. Leaves and hubs are BOTH single links. A hub links to its primary
  // (first allowed) child and lights up when any of its pages is current; its siblings live in
  // the context bar (renderContextBar), not as nested rows. A hub with no allowed child is dropped.
  function renderNav(path) {
    // Section markers ({ section }) group the rail into "Workspace" / "Admin". A label is only
    // emitted once its section actually produced ≥1 allowed link, so role-gated empty sections
    // (e.g. Admin for regular staff) never leave an orphan heading.
    let out = "";
    let pendingLabel = null;
    let buf = "";
    const flush = () => {
      if (buf) { if (pendingLabel) out += `<div class="navlabel">${esc(pendingLabel)}</div>`; out += buf; }
      buf = ""; pendingLabel = null;
    };
    NAV.forEach((n) => {
      if (n.section) { flush(); pendingLabel = n.section; return; }
      if (!n.children) { if (navAllowed(n)) buf += navLink(n, path); return; }
      const kids = n.children.filter(navAllowed);
      if (!kids.length) return;
      const here = kids.some((k) => k.href === path);
      // 🔴 Built through `navLink` rather than inline, so a HUB row is identical to a leaf row:
      // same `title` and same `.nav-label` span. Both are what the collapsed icon rail depends on,
      // and this branch used to hand-roll its own markup — which meant "Growth" and "Time & Leave"
      // were the two rows in the whole sidebar that lost their label and gained no tooltip when the
      // rail narrowed. Caught by the jsdom mount harness, not by eye.
      buf += navLink({ href: kids[0].href, icon: n.icon, label: n.group }, here ? kids[0].href : path);
    });
    flush();
    return out;
  }

  // The hub context bar: when the current page belongs to a hub, show its sibling pages as tabs
  // directly under the topbar (the "many features, one surface" pattern). Hidden on leaf pages.
  function renderContextBar(path) {
    const bar = qs("#ctxbar");
    if (!bar) return;
    const hub = NAV.find((n) => n.children && n.children.some((k) => k.href === path));
    const kids = hub ? hub.children.filter(navAllowed) : [];
    if (!hub || kids.length < 2) { bar.hidden = true; bar.innerHTML = ""; return; }
    bar.hidden = false;
    bar.innerHTML = `<div class="ctxbar-in">
      <span class="ctxbar-hub">${ICON[hub.icon]}<span>${esc(hub.group)}</span></span>
      ${kids.map((k) => `<a href="${k.href}" class="ctab${k.href === path ? " active" : ""}">${esc(k.label)}</a>`).join("")}
    </div>`;
  }

  // ---------------- Command palette (Ctrl/Cmd + K) ----------------
  // Searches pages, quick actions, people, and tasks. Pages/actions are instant; people + tasks
  // are fetched once on first open and cached. Everything degrades gracefully if a fetch 403s.
  const GROUP_ORDER = ["Actions", "Pages", "People", "Tasks"];

  function initCommandPalette() {
    let cache = { people: null, tasks: null };
    let visible = [];   // flat, in render order — keyboard nav walks this
    let sel = 0;
    let open = false;
    let lastFocus = null;

    const ov = document.createElement("div");
    ov.className = "cmdk-ov"; ov.id = "cmdk";
    ov.innerHTML = `
      <div class="cmdk" role="dialog" aria-modal="true" aria-label="Command palette">
        <div class="cmdk-in">${ICON.search}<input id="cmdk-input" type="text" role="combobox" aria-expanded="true" aria-controls="cmdk-list" aria-autocomplete="list" placeholder="Search people, tasks, pages, or run a command…" autocomplete="off" spellcheck="false"></div>
        <div class="cmdk-list" id="cmdk-list" role="listbox"></div>
        <div class="cmdk-foot"><span><kbd>↑</kbd><kbd>↓</kbd> navigate</span><span><kbd>↵</kbd> open</span><span><kbd>esc</kbd> close</span></div>
      </div>`;
    document.body.appendChild(ov);
    const input = qs("#cmdk-input", ov);
    const listEl = qs("#cmdk-list", ov);

    function actions() {
      const a = [
        { group: "Actions", icon: currentTheme() === "dark" ? "sun" : "moon", label: `Switch to ${currentTheme() === "dark" ? "light" : "dark"} mode`, hint: "Theme", run: () => { setTheme(currentTheme() === "dark" ? "light" : "dark"); return true; } },
        { group: "Actions", icon: "bell", label: "Mark all notifications read", hint: "", run: async () => { try { await api("/api/notifications/read-all", { method: "PATCH" }); toast("All caught up", "ok"); setBadge(0); } catch (e) {} } },
        { group: "Actions", icon: "gear", label: "Change password", hint: "Account", run: () => { openChangePassword(); } },
        { group: "Actions", icon: "logout", label: "Log out", hint: "Account", run: doLogout },
      ];
      if ((ROLE_RANK[USER.role] || 0) >= ROLE_RANK.account_manager) {
        a.unshift({ group: "Actions", icon: "plus", label: "New task", hint: "Task Board", run: () => go("/dashboard?new=1") });
      }
      return a;
    }
    function pages() {
      // Flatten the nav tree to its allowed leaf pages (groups themselves aren't navigable).
      const leaves = NAV.flatMap((n) => (n.children ? n.children : [n]));
      return leaves.filter((n) => n.href && navAllowed(n))
        .map((n) => ({ group: "Pages", icon: n.icon, label: n.label, hint: n.href, run: () => go(n.href) }));
    }
    function peopleItems() {
      return (cache.people || []).map((p) => ({
        group: "People", icon: "users", label: p.name,
        hint: [p.role_label || p.role, p.team_name].filter(Boolean).join(" · "),
        run: () => go("/people?open=" + p.id),
      }));
    }
    function taskItems() {
      return (cache.tasks || []).map((t) => ({
        group: "Tasks", icon: "board", label: t.title,
        hint: [t.status, t.client_name].filter(Boolean).join(" · "),
        run: () => go("/dashboard?open=" + t.id),
      }));
    }
    const go = (href) => { close(); location.href = href; };

    // Subsequence-aware scorer: prefix > substring > scattered match; -1 means no match.
    function score(q, text) {
      text = (text || "").toLowerCase();
      const idx = text.indexOf(q);
      if (idx === 0) return 1000;
      if (idx > 0) return 600 - idx;
      let ti = 0, first = -1;
      for (const ch of q) { const f = text.indexOf(ch, ti); if (f < 0) return -1; if (first < 0) first = f; ti = f + 1; }
      return 200 - (ti - q.length) - first;
    }

    function render() {
      const q = input.value.trim().toLowerCase();
      let pool = actions().concat(pages());
      if (q) pool = pool.concat(peopleItems(), taskItems());   // only surface records when searching
      const scored = pool.map((it) => ({ it, s: q ? Math.max(score(q, it.label), score(q, it.hint) - 200) : 1 }))
        .filter((x) => x.s > -1);
      // Fixed group order; within a group sort by score, then cap records so the list stays tight.
      visible = [];
      const html = GROUP_ORDER.map((g) => {
        let rows = scored.filter((x) => x.it.group === g).sort((a, b) => b.s - a.s).map((x) => x.it);
        if ((g === "People" || g === "Tasks") && q) rows = rows.slice(0, 6);
        if (!rows.length) return "";
        const items = rows.map((it) => {
          const i = visible.push(it) - 1;
          return `<div class="cmdk-item" role="option" data-i="${i}" id="cmdk-opt-${i}">
            <span class="cmdk-ic">${ICON[it.icon] || ICON.grid}</span>
            <span class="cmdk-label">${esc(it.label)}</span>
            ${it.hint ? `<span class="cmdk-hint">${esc(it.hint)}</span>` : ""}</div>`;
        }).join("");
        return `<div class="cmdk-group">${esc(g)}</div>${items}`;
      }).join("");
      listEl.innerHTML = html || `<div class="cmdk-empty">No matches for “${esc(input.value)}”.</div>`;
      if (sel >= visible.length) sel = Math.max(0, visible.length - 1);
      paintSel();
      qsa(".cmdk-item", listEl).forEach((el) => {
        el.onmousemove = () => { const i = +el.dataset.i; if (i !== sel) { sel = i; paintSel(); } };
        el.onclick = () => runItem(visible[+el.dataset.i]);
      });
    }
    function paintSel() {
      qsa(".cmdk-item", listEl).forEach((el) => el.classList.toggle("sel", +el.dataset.i === sel));
      const cur = qs(`#cmdk-opt-${sel}`, listEl);
      if (cur) { if (cur.scrollIntoView) cur.scrollIntoView({ block: "nearest" }); input.setAttribute("aria-activedescendant", cur.id); }
    }
    function runItem(it) {
      if (!it || !it.run) return;
      // Actions return true to keep the palette open (e.g. theme toggle re-renders in place);
      // everything else closes it — importantly so modal-opening actions aren't hidden behind it.
      if (it.run() === true) { render(); return; }
      close();
    }

    async function ensureData() {
      if (cache.people && cache.tasks) return;
      const [pp, tt] = await Promise.allSettled([api("/api/people"), api("/api/tasks")]);
      cache.people = pp.status === "fulfilled" ? pp.value : [];
      cache.tasks = tt.status === "fulfilled" ? tt.value : [];
      if (open) render();
    }

    function openPalette() {
      if (open) return;
      open = true; lastFocus = document.activeElement;
      ov.classList.add("open"); input.value = ""; sel = 0; render();
      requestAnimationFrame(() => input.focus());
      ensureData();
    }
    function close() {
      if (!open) return;
      open = false; ov.classList.remove("open");
      if (lastFocus && lastFocus.focus) lastFocus.focus();
    }

    input.addEventListener("input", () => { sel = 0; render(); });
    ov.addEventListener("mousedown", (e) => { if (e.target === ov) close(); });
    document.addEventListener("keydown", (e) => {
      const key = e.key.toLowerCase();
      if ((e.ctrlKey || e.metaKey) && key === "k") { e.preventDefault(); open ? close() : openPalette(); return; }
      if (!open) return;
      if (e.key === "Escape") { e.preventDefault(); close(); }
      else if (e.key === "ArrowDown") { e.preventDefault(); if (visible.length) { sel = (sel + 1) % visible.length; paintSel(); } }
      else if (e.key === "ArrowUp") { e.preventDefault(); if (visible.length) { sel = (sel - 1 + visible.length) % visible.length; paintSel(); } }
      else if (e.key === "Enter") { e.preventDefault(); runItem(visible[sel]); }
    });
    const trig = qs("#cmdk-trigger"); if (trig) trig.onclick = openPalette;
  }

  // ---------------- Boot ----------------
  async function boot() {
    // Standalone pages (login, kiosk, scanner) skip the shell + auth guard.
    if (document.body.dataset.shell === "off") {
      applyBrandLogo();
      if (window.pageInit) window.pageInit(Sentinel);
      return;
    }
    // 🔴 THESE TWO RUN IN PARALLEL, AND THAT IS THE POINT (2026-08-17).
    //
    // They used to be two sequential `await`s, so EVERY navigation in the app paid two full round
    // trips end to end before the shell was even built — measured at 250-440ms each to
    // asia-southeast1, i.e. half a second of pure waterfall on every page, forever. `/api/vocab`
    // does not depend on the answer to `/api/auth/me`; it only needs the same cookie.
    //
    // Two details that make this safe:
    //  • vocab carries its OWN `.catch`, so it can never reject the `Promise.all` — only `auth/me`
    //    decides whether we are signed in, exactly as before.
    //  • when `auth/me` 401s we redirect, and the parallel vocab request 401s harmlessly alongside
    //    it. One wasted request on the sign-in path is cheaper than a guaranteed serial round trip
    //    on every authenticated page load.
    let vocabRes = null;
    try {
      const [me, v] = await Promise.all([
        api("/api/auth/me"),
        api("/api/vocab").catch(() => null),
      ]);
      USER = me;
      vocabRes = v;
    } catch (e) {
      location.href = "/login"; return;
    }
    Sentinel.user = USER;
    setVocab(vocabRes);
    buildShell();
    applyBrandLogo();
    if (window.pageInit) {
      try { await window.pageInit(Sentinel); }
      catch (e) { console.error(e); toast(e.detail || "Something went wrong", "err"); }
    }
  }

  const Sentinel = {
    api, toast, skeleton, loadErr, sortTable, modal, esc, qs, qsa, ICON, avatar, initials, uploadAvatar, removeAvatar,
    engineUrl, theme: currentTheme,
    fmtTime, fmtDate, fmtDateFull, timeAgo, priorityDot, labelPills, statusPill,
    roleRank: ROLE_RANK,
    refreshVocab,
    get user() { return USER; }, set user(u) { USER = u; },
    get colors() { return COLORS; },
    // The snapshot boot() already paid for. A getter, so a `refreshVocab()` is picked up by anyone
    // holding `S` rather than a stale copy of the object. Never null-guard-free: an outage on the
    // parallel vocab fetch leaves it null and every consumer already tolerates that (see the
    // consumers' own fallbacks), because a missing colour is cosmetic and a missing page is not.
    get vocab() { return VOCAB; },
    view: () => qs("#view"),
    can: (min) => (ROLE_RANK[USER.role] || 0) >= ROLE_RANK[min],
  };
  window.Sentinel = Sentinel;

  // ---------------- Local development ----------------
  // 🔴 THE LOCALHOST TEST IS A PRODUCTION GATE, not a convenience. It is gate 2 of the three that
  // keep live reload out of prod (see backend/app/routers/dev.py) and the only one that lives in the
  // browser: a deploy can be misconfigured, but a Cloud Run host can never be "localhost", so a
  // production page structurally never asks for the script. Do not widen this to a LAN IP or a
  // hostname pattern — the value of the check is that it cannot be satisfied off this machine.
  //
  // It sits HERE rather than inside boot() so it also covers the standalone pages (login, kiosk,
  // scanner), which return from boot() early on `data-shell="off"` and would otherwise be the ones
  // you cannot live-edit — the login page being a fairly likely thing to be styling.
  const IS_LOCAL = ["localhost", "127.0.0.1", "[::1]", "::1"].includes(location.hostname);
  // 🔴 /kiosk OPTS OUT and keeps behaving exactly as it does in production, service worker and all.
  // The kiosk's defining requirement is that it BOOTS OFFLINE from cache (AGENTS.md §5), so it is the
  // one page whose caching you have to be able to exercise locally — and unregistering its worker to
  // make styling faster would mean the offline path is only ever tested in production, on a tablet,
  // in a room, on the day it matters. Live-reload the kiosk by editing and refreshing, as before.
  const DEV_RELOAD = IS_LOCAL && location.pathname !== "/kiosk";

  if (DEV_RELOAD) {
    // A file, not inline code: CSP is `script-src 'self'` with no inline scripts anywhere
    // (AGENTS.md §5), and that holds locally too because the same middleware sends the same header.
    const s = document.createElement("script");
    s.src = "/static/js/devreload.js";
    document.head.appendChild(s);
  }

  // Register the PWA service worker (offline kiosk + installable app).
  // 🔴 SKIPPED ON LOCALHOST. The worker's whole job is serving assets from cache, which locally means
  // serving the file you just edited from before you edited it — the local face of the §5 "deployed
  // but the browser shows the old version" bug, with no CACHE bump available to clear it because
  // nobody edits sw.js on every save. devreload.js also unregisters any worker left behind from an
  // earlier session; this stops a new one replacing it on the next load. `/kiosk` is exempt (above),
  // so its offline boot is still testable locally.
  if ("serviceWorker" in navigator && !DEV_RELOAD) {
    window.addEventListener("load", () => navigator.serviceWorker.register("/sw.js").catch(() => {}));
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();

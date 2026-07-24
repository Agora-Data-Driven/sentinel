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

  // ---- Inline icon set (Atrium stroked style: 24x24, stroke-width 1.8) ----
  const P = (d) => `<svg class="svg-ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${d}</svg>`;
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
  };

  const AGORA_LOGO =
    '<svg viewBox="0 0 150 40" role="img" aria-label="Agora">' +
    '<g fill="none" stroke="#1A1B1E" stroke-linecap="round" stroke-linejoin="round">' +
    '<path d="M3 37 L19 4 L35 37" stroke-width="1.8"/><path d="M12 37 L24 12" stroke-width="1.1" opacity="0.5"/>' +
    '<path d="M11.5 24 L26.5 24" stroke-width="1.6"/></g>' +
    '<text x="48" y="24.5" font-family="Inter,sans-serif" font-size="21" font-weight="600" letter-spacing="3.2" fill="#1A1B1E">AGORA</text>' +
    '<text x="49.5" y="35" font-family="Inter,sans-serif" font-size="7.3" font-weight="700" letter-spacing="3.6" fill="#353535">OPERATIONS</text></svg>';

  // Flat, single-level navigation: 6 destinations, no accordions. A destination is either a
  // LEAF (its own page) or a HUB — a set of sibling pages that share a context bar under the
  // topbar. The sidebar row for a hub links to its primary (first allowed) page and lights up
  // whenever any of its pages is current; the siblings surface as tabs in renderContextBar,
  // not as nested rows. Item gating unchanged: `roles` allow-list, `min` rank floor, `hideRoles`
  // deny-list (personal tools like Leave/Gym a super_admin doesn't use). A hub whose every child
  // is filtered out is dropped entirely (e.g. Admin disappears for regular staff).
  const NAV = [
    { section: "Workspace" },
    { href: "/dashboard", label: "Dashboard", icon: "grid" },
    { href: "/tasks", label: "Task Board", icon: "board" },
    { group: "Growth", icon: "sparkle", children: [
      { href: "/growth", label: "Overview", icon: "sparkle" },
      { href: "/academy", label: "Academy", icon: "cap" },
      { href: "/reading", label: "Reading & Philosophy", icon: "book" },
      { href: "/gym", label: "Gym", icon: "dumbbell", hideRoles: ["super_admin"] },
    ] },
    { group: "Time & Leave", icon: "clock", children: [
      { href: "/attendance", label: "Time", icon: "clock" },
      { href: "/leave", label: "Leave", icon: "calendar", hideRoles: ["super_admin"] },
      // One inbox for attendance-correction + leave approvals (managers+). Replaces the separate
      // "Approvals" tabs that used to live on the Time and Leave pages.
      { href: "/approvals", label: "Approvals", icon: "inbox", min: "team_lead" },
      // Check-in (the QR scanner station) is an operational tool, not personal — visible to all
      // roles so a super_admin can reach it too (it was hidden before, hence "missing").
      { href: "/scanner", label: "Check-in", icon: "qr" },
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
    if (!box) { box = document.createElement("div"); box.id = "toasts"; document.body.appendChild(box); }
    const t = document.createElement("div");
    t.className = "toast" + (kind ? " " + kind : "");
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

  const initials = (name) => (String(name || "?").split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join("") || "?").toUpperCase();
  const avatar = (u, cls = "") => `<div class="avatar ${cls}">${esc(u ? initials(u.name) : "?")}</div>`;

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
  function modal({ title, body, footer, wide, drawer }) {
    let ov = qs("#modal-ov");
    if (!ov) { ov = document.createElement("div"); ov.id = "modal-ov"; document.body.appendChild(ov); }
    ov.className = "overlay" + (drawer ? " drawer-ov" : "");
    ov.innerHTML = `<div class="modal ${wide ? "wide" : ""}${drawer ? " as-drawer" : ""}">
      <div class="modal-head"><h3>${esc(title)}</h3><span class="x-close" id="modal-x">${ICON.x}</span></div>
      <div class="modal-body">${body}</div>
      ${footer ? `<div class="modal-foot">${footer}</div>` : ""}</div>`;
    ov.classList.add("open");
    // Tuck the coach FAB away while a modal/drawer is open so it can't sit over the footer buttons.
    const coachFab = qs("#coach-fab"); if (coachFab) coachFab.classList.add("hidden");
    const close = () => { ov.classList.remove("open"); const f = qs("#coach-fab"); if (f) f.classList.remove("hidden"); };
    qs("#modal-x", ov).onclick = close;
    ov.onclick = (e) => { if (e.target === ov) close(); };
    // Esc closes the drawer/modal.
    const onKey = (e) => { if (e.key === "Escape") { close(); document.removeEventListener("keydown", onKey); } };
    document.addEventListener("keydown", onKey);
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
          <a class="brand-logo" data-brand-logo href="https://agoradatadriven.com" title="Agora Data Driven">${AGORA_LOGO}</a>
          <span class="badge-sentinel">Sentinel</span>
        </div>
        <nav class="nav">${navItems}</nav>
        <div class="side-foot">
          <div class="user-card" id="user-card" title="Change password" style="cursor:pointer">
            ${avatar(USER)}
            <div class="who"><div class="n">${esc(USER.name)}</div><div class="r">${esc(USER.role_label || USER.role)}</div></div>
          </div>
        </div>
      </aside>
      <div class="main">
        <header class="top">
          <button class="iconbtn hamburger" id="ham" aria-label="Menu">${ICON.menu}</button>
          <button class="cmdk-trigger" id="cmdk-trigger" title="Search (Ctrl K)" aria-label="Open command palette">${ICON.search}<span>Search anything</span><kbd>Ctrl K</kbd></button>
          <div class="theme-toggle" id="theme-toggle">
            <button data-set-theme="light" title="Light mode">${ICON.sun}</button>
            <button data-set-theme="dark" title="Dark mode">${ICON.moon}</button>
          </div>
          <div style="position:relative">
            <button class="iconbtn" id="bell" aria-label="Notifications">${ICON.bell}<span class="bdot" id="bell-count" style="display:none"></span></button>
            <div class="notif-panel" id="notif-panel"></div>
          </div>
          <button class="iconbtn" id="logout" title="Log out">${ICON.logout}</button>
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
    refreshTaskCount();
    mountAssistant();
  }

  // ---------------- Holistic AI coach (global) ----------------
  // The SAME Study Assistant that lives in the Mastery Engine, surfaced on every Sentinel page as a
  // floating widget. It's an iframe of the engine's assistant-only view; the shared `ag_sso` cookie
  // authenticates the viewer, and the engine feeds it the worker's holistic profile server-side. We
  // create the iframe lazily on first open (so no full-viewport overlay ever swallows page clicks)
  // and keep it alive after, so the conversation persists while navigating within a session.
  async function mountAssistant() {
    if (qs("#coach-fab")) return;                 // already mounted this page-load
    let cfg;
    try { cfg = await api("/api/academy/config"); } catch (e) { return; }
    const base = cfg && cfg.assistant_url;
    if (!base) return;                            // engine not configured — no coach

    const style = document.createElement("style");
    style.textContent = `
      #coach-fab{position:fixed;right:24px;bottom:24px;z-index:90;display:flex;align-items:center;gap:9px;
        border:none;cursor:pointer;padding:0 18px 0 15px;height:54px;border-radius:var(--pill);
        background:linear-gradient(135deg,#9484FB 0%,#5C4BD0 100%);color:#fff;font:600 14px/1 Inter,sans-serif;
        box-shadow:0 10px 30px rgba(92,75,208,.42);transition:transform .15s ease,box-shadow .15s ease}
      #coach-fab:hover{transform:translateY(-2px);box-shadow:0 14px 38px rgba(92,75,208,.55)}
      #coach-fab svg{width:22px;height:22px;stroke:#fff}
      #coach-fab.hidden{display:none}
      #coach-panel{position:fixed;right:24px;bottom:24px;z-index:91;width:min(420px,calc(100vw - 32px));
        height:min(660px,calc(100vh - 96px));background:var(--card);border:1px solid var(--line);
        border-radius:var(--radius);box-shadow:var(--shadow-lg);display:none;flex-direction:column;overflow:hidden}
      #coach-panel.open{display:flex}
      #coach-head{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:12px 14px;
        border-bottom:1px solid var(--line);background:linear-gradient(135deg,rgba(148,132,251,.14),transparent)}
      #coach-head .t{display:flex;align-items:center;gap:9px;font:700 14px/1.2 Inter,sans-serif;color:var(--text)}
      #coach-head .t svg{width:18px;height:18px;stroke:var(--violet-d)}
      #coach-head .t small{display:block;font:500 11px/1.3 Inter,sans-serif;color:var(--sub);margin-top:2px}
      #coach-head .x-close{cursor:pointer;color:var(--sub);display:flex}
      #coach-frame{flex:1;border:0;width:100%;background:var(--card)}
      @media (max-width:520px){#coach-panel{right:8px;left:8px;bottom:8px;width:auto;height:min(80vh,660px)}}`;
    document.head.appendChild(style);

    const fab = document.createElement("button");
    fab.id = "coach-fab";
    fab.setAttribute("aria-label", "Open your coach");
    fab.innerHTML = `${ICON.sparkle}<span>Coach</span>`;
    document.body.appendChild(fab);

    const panel = document.createElement("div");
    panel.id = "coach-panel";
    panel.innerHTML = `
      <div id="coach-head">
        <div class="t">${ICON.sparkle}<div>Your Coach<small>Knows your growth: learning, gym, goals</small></div></div>
        <span class="x-close" id="coach-x">${ICON.x}</span>
      </div>
      <div id="coach-frame-wrap" style="flex:1;display:flex"></div>`;
    document.body.appendChild(panel);

    let framed = false;
    const open = () => {
      if (!framed) {
        const f = document.createElement("iframe");
        f.id = "coach-frame";
        f.allow = "microphone; clipboard-write";
        f.src = base + "&actions=1";               // {engine}/?embed=assistant&actions=1
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
    const GOAL = ["title", "description", "target_date", "status", "progress_pct"];
    const ACH = ["title", "description", "achieved_on"];
    const GROW = ["kind", "title", "detail", "status"];
    const SKILL = ["name", "level", "source", "note"];
    const METRIC = ["body_fat_pct", "weight_kg", "date", "notes"];
    const RESUME = ["headline", "resume_text", "resume_file_url"];
    const READ = ["status", "reflection", "rating"];

    function coachExecute(action) {
      const a = action || {}, args = a.args || {}, id = args.id;
      switch (a.op) {
        case "add_body_metric": return api(`${DEV}/body-metrics`, { method: "POST", body: pick(args, METRIC) });
        case "add_pr": return api(`${DEV}/prs`, { method: "POST", body: pick(args, PR) });
        case "update_pr": return api(`${DEV}/prs/${id}`, { method: "PATCH", body: pick(args, PR) });
        case "delete_pr": return api(`${DEV}/prs/${id}`, { method: "DELETE" });
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

  async function refreshTaskCount() {
    try {
      const d = await api("/api/dashboard");
      const n = d.me && d.me.open_tasks ? d.me.open_tasks.length : 0;
      const el = qs("#nav-tasks"); if (el && n) { el.textContent = n; el.style.display = ""; }
    } catch (e) { /* ignore */ }
  }

  async function wireBell() {
    const bell = qs("#bell"), panel = qs("#notif-panel");
    async function load() {
      const d = await api("/api/notifications");
      const badge = qs("#bell-count");
      if (d.unread_count > 0) { badge.textContent = d.unread_count; badge.style.display = ""; } else { badge.style.display = "none"; }
      panel.innerHTML = `<div class="h"><strong>Notifications</strong><button class="btn sm ghost" id="read-all">Mark all read</button></div>
        <div class="notif-list">${d.items.length ? d.items.map((n) => `
          <div class="notif ${n.is_read ? "" : "unread"}" data-id="${n.id}" data-link="${esc(n.link || "")}">
            <div style="flex:1"><div class="nt">${esc(n.title)}</div>${n.body ? `<div class="nb">${esc(n.body)}</div>` : ""}<div class="ntime">${timeAgo(n.created_at)}</div></div>
          </div>`).join("") : '<div class="empty">You\'re all caught up.</div>'}</div>`;
      const ra = qs("#read-all", panel);
      if (ra) ra.onclick = async (e) => { e.stopPropagation(); await api("/api/notifications/read-all", { method: "PATCH" }); load(); };
      qsa(".notif", panel).forEach((el) => el.onclick = async () => {
        await api(`/api/notifications/${el.dataset.id}/read`, { method: "PATCH" });
        if (el.dataset.link) location.href = el.dataset.link; else load();
      });
    }
    bell.onclick = (e) => { e.stopPropagation(); panel.classList.toggle("open"); if (panel.classList.contains("open")) load(); };
    document.addEventListener("click", (e) => { if (!panel.contains(e.target) && e.target !== bell) panel.classList.remove("open"); });
    load();
  }

  // ---------------- Custom logo ----------------
  // If /static/img/logo.svg (or .png) exists, swap it into every [data-brand-logo] slot.
  // We probe by loading the image first, so a missing logo never shows a broken image —
  // the built-in AGORA mark simply stays.
  function tryImg(url) {
    return new Promise((res, rej) => { const i = new Image(); i.onload = () => res(url); i.onerror = () => rej(); i.src = url; });
  }
  function applyBrandLogo() {
    const slots = qsa("[data-brand-logo]");
    if (!slots.length) return;
    // Dark mode uses the white-ink logo so it stays legible on the dark sidebar.
    const dark = document.documentElement.getAttribute("data-theme") === "dark";
    // Cache-bust: bump when the logo file changes so browsers/PWA fetch the new art, not a stale copy.
    const V = "?v=21";
    const candidates = dark
      ? ["/static/img/logo-dark.png" + V, "/static/img/logo.png" + V]
      : ["/static/img/logo.png" + V, "/static/img/logo.svg"];
    (function pick(i) {
      if (i >= candidates.length) return;  // no custom logo — keep the built-in mark + pill
      tryImg(candidates[i]).then((url) => {
        slots.forEach((s) => { s.innerHTML = `<img class="brand-img" src="${url}" alt="Sentinel">`; });
        // The lockup already carries the "SENTINEL" wordmark, so hide the redundant pill (keep "Scanner").
        qsa(".badge-sentinel").forEach((b) => { if (b.textContent.trim().toLowerCase() === "sentinel") b.style.display = "none"; });
      }).catch(() => pick(i + 1));
    })(0);
  }

  // ---------------- Change password ----------------
  function openChangePassword() {
    const m = modal({
      title: "Change password",
      body: `<label class="field"><span>Current password</span><input type="password" id="cp-cur" autocomplete="current-password" placeholder="Leave blank if none set"></label>
        <label class="field"><span>New password</span><input type="password" id="cp-new" autocomplete="new-password" placeholder="At least 6 characters"></label>
        <label class="field"><span>Confirm new password</span><input type="password" id="cp-cnf" autocomplete="new-password"></label>`,
      footer: `<button class="btn ghost" id="cp-cancel">Cancel</button><button class="btn primary" id="cp-save">Update password</button>`,
    });
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
    qsa("#theme-toggle button").forEach((b) => b.classList.toggle("on", b.dataset.setTheme === t));
    applyBrandLogo();
  }
  const currentTheme = () => document.documentElement.getAttribute("data-theme") || "light";
  async function doLogout() { try { await api("/api/auth/logout", { method: "POST" }); } finally { location.href = "https://agoradatadriven.com"; } }
  function navAllowed(n) {
    if (n.hideRoles && n.hideRoles.includes(USER.role)) return false;
    if (n.roles) return n.roles.includes(USER.role);
    if (n.min) return (ROLE_RANK[USER.role] || 0) >= ROLE_RANK[n.min];
    return true;
  }

  // A single sidebar link. The task count badge rides on the Task Board link.
  function navLink(n, path) {
    return `<a href="${n.href}" class="${path === n.href ? "active" : ""}">${ICON[n.icon]}<span>${n.label}</span>${n.href === "/tasks" ? '<span class="count" id="nav-tasks" style="display:none"></span>' : ""}</a>`;
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
      buf += `<a href="${kids[0].href}" class="${here ? "active" : ""}">${ICON[n.icon]}<span>${esc(n.group)}</span></a>`;
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
        { group: "Actions", icon: "bell", label: "Mark all notifications read", hint: "", run: async () => { try { await api("/api/notifications/read-all", { method: "PATCH" }); toast("All caught up", "ok"); const b = qs("#bell-count"); if (b) b.style.display = "none"; } catch (e) {} } },
        { group: "Actions", icon: "gear", label: "Change password", hint: "Account", run: () => { openChangePassword(); } },
        { group: "Actions", icon: "logout", label: "Log out", hint: "Account", run: doLogout },
      ];
      if ((ROLE_RANK[USER.role] || 0) >= ROLE_RANK.account_manager) {
        a.unshift({ group: "Actions", icon: "plus", label: "New task", hint: "Task Board", run: () => go("/tasks?new=1") });
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
        run: () => go("/tasks?open=" + t.id),
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
    try {
      USER = await api("/api/auth/me");
    } catch (e) {
      location.href = "/login"; return;
    }
    Sentinel.user = USER;
    try { const v = await api("/api/vocab"); if (v && v.colors) COLORS = v.colors; } catch (e) { /* keep fallback */ }
    buildShell();
    applyBrandLogo();
    if (window.pageInit) {
      try { await window.pageInit(Sentinel); }
      catch (e) { console.error(e); toast(e.detail || "Something went wrong", "err"); }
    }
  }

  const Sentinel = {
    api, toast, skeleton, modal, esc, qs, qsa, ICON, avatar, initials,
    fmtTime, fmtDate, fmtDateFull, timeAgo, priorityDot, labelPills, statusPill,
    roleRank: ROLE_RANK,
    get user() { return USER; }, set user(u) { USER = u; },
    get colors() { return COLORS; },
    view: () => qs("#view"),
    can: (min) => (ROLE_RANK[USER.role] || 0) >= ROLE_RANK[min],
  };
  window.Sentinel = Sentinel;

  // Register the PWA service worker (offline kiosk + installable app).
  if ("serviceWorker" in navigator) {
    window.addEventListener("load", () => navigator.serviceWorker.register("/sw.js").catch(() => {}));
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();

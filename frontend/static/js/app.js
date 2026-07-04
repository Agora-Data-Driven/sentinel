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
    check: P('<path d="M20 6L9 17l-5-5"/>'),
    plus: P('<path d="M12 5v14M5 12h14"/>'),
    x: P('<path d="M18 6L6 18M6 6l12 12"/>'),
    search: P('<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/>'),
    download: P('<path d="M12 3v12M7 10l5 5 5-5M5 21h14"/>'),
    comment: P('<path d="M21 12a8 8 0 0 1-11.5 7.2L4 20l1-4.6A8 8 0 1 1 21 12z"/>'),
    paperclip: P('<path d="M21 10l-9.2 9.2a4 4 0 0 1-5.7-5.7l9.2-9.2a2.7 2.7 0 0 1 3.8 3.8L9.6 16.6a1.3 1.3 0 0 1-1.9-1.9L16 6.4"/>'),
    trophy: P('<path d="M6 4h12v4a6 6 0 0 1-12 0z"/><path d="M6 5H4a2 2 0 0 0 2 4.5M18 5h2a2 2 0 0 1-2 4.5M12 14v3M9 20h6M10 20c0-1.7.8-3 2-3s2 1.3 2 3"/>'),
    flame: P('<path d="M12 3s5 4 5 9a5 5 0 0 1-10 0c0-1.5.6-2.7 1.3-3.6C9 10 10 9 10 7c1.5.8 2 2.3 2 4 .9-.7 1.5-1.8 1.5-3 .3.7.5 1.4-1.5 5z"/>'),
    coffee: P('<path d="M4 8h13v4a5 5 0 0 1-5 5H9a5 5 0 0 1-5-5z"/><path d="M17 9h2a2 2 0 0 1 0 5h-2M6 2v2M10 2v2M14 2v2"/>'),
    doc: P('<path d="M6 2.5h8L19 7v14.5H6z"/><path d="M14 2.5V7h4M9 13h6M9 17h5"/>'),
    inbox: P('<path d="M3 12h5l1.5 3h5L21 12M3 12l3-8h12l3 8v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>'),
    sparkle: P('<path d="M12 3l1.8 4.7L18.5 9l-4.7 1.8L12 15l-1.8-4.2L5.5 9l4.7-1.3z"/>'),
    sliders: P('<path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M18 18h2"/><circle cx="16" cy="6" r="2"/><circle cx="10" cy="12" r="2"/><circle cx="16" cy="18" r="2"/>'),
    sun: P('<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>'),
    moon: P('<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/>'),
  };

  const AGORA_LOGO =
    '<svg viewBox="0 0 150 40" role="img" aria-label="Agora">' +
    '<g fill="none" stroke="#1A1B1E" stroke-linecap="round" stroke-linejoin="round">' +
    '<path d="M3 37 L19 4 L35 37" stroke-width="1.8"/><path d="M12 37 L24 12" stroke-width="1.1" opacity="0.5"/>' +
    '<path d="M11.5 24 L26.5 24" stroke-width="1.6"/></g>' +
    '<text x="48" y="24.5" font-family="Inter,sans-serif" font-size="21" font-weight="600" letter-spacing="3.2" fill="#1A1B1E">AGORA</text>' +
    '<text x="49.5" y="35" font-family="Inter,sans-serif" font-size="7.3" font-weight="700" letter-spacing="3.6" fill="#353535">OPERATIONS</text></svg>';

  const NAV = [
    { href: "/dashboard", label: "Dashboard", icon: "grid" },
    { href: "/attendance", label: "Attendance", icon: "clock" },
    { href: "/gym", label: "Gym Tracker", icon: "dumbbell" },
    { href: "/tasks", label: "Task Board", icon: "board" },
    { href: "/people", label: "People", icon: "users" },
    { href: "/leave", label: "Leave", icon: "calendar" },
    { href: "/reports", label: "Reports", icon: "chart", min: "team_lead" },
    { href: "/scanner", label: "Scanner", icon: "qr", roles: ["super_admin"] },
    { href: "/manage", label: "Manage", icon: "sliders", roles: ["super_admin"] },
    { href: "/settings", label: "Settings", icon: "gear", min: "admin" },
  ];

  // ---------------- Helpers ----------------
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const qs = (s, r = document) => r.querySelector(s);
  const qsa = (s, r = document) => Array.from(r.querySelectorAll(s));

  async function api(path, opts = {}) {
    const o = { method: opts.method || "GET", headers: {}, credentials: "same-origin" };
    if (opts.body !== undefined) { o.headers["Content-Type"] = "application/json"; o.body = JSON.stringify(opts.body); }
    if (opts.form) { o.body = opts.form; } // FormData: let browser set the boundary
    const res = await fetch(path, o);
    if (res.status === 204) return null;
    const ct = res.headers.get("content-type") || "";
    const data = ct.includes("application/json") ? await res.json() : await res.text();
    if (!res.ok) {
      const detail = (data && data.detail) || res.statusText;
      const err = new Error(detail); err.status = res.status; err.detail = detail;
      throw err;
    }
    return data;
  }

  function toast(msg, kind) {
    let box = qs("#toasts");
    if (!box) { box = document.createElement("div"); box.id = "toasts"; document.body.appendChild(box); }
    const t = document.createElement("div");
    t.className = "toast" + (kind ? " " + kind : "");
    t.innerHTML = (kind === "ok" ? ICON.check : kind === "err" ? ICON.x : ICON.bell) + "<span>" + esc(msg) + "</span>";
    box.appendChild(t);
    setTimeout(() => { t.style.opacity = "0"; t.style.transition = "opacity .3s"; setTimeout(() => t.remove(), 300); }, kind === "err" ? 4200 : 2600);
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
    const c = p === "Urgent" ? "red" : p === "Medium" ? "amber" : "green";
    return `<span class="dot ${c}"></span>`;
  }
  function labelPills(labels) { return (labels || []).map((l) => `<span class="lbl ${esc(l)}">${esc(l)}</span>`).join(""); }
  function statusPill(s) {
    const map = { OnTime: "green", Late: "amber", Absent: "red", HalfDay: "blue", MissingClockOut: "amber", OnLeave: "violet", Completed: "green", Incomplete: "amber", Missing: "red", Approved: "green", Pending: "amber", Rejected: "red", Active: "green", "On Leave": "violet", Inactive: "grey" };
    return `<span class="pill ${map[s] || "grey"}">${esc(s)}</span>`;
  }

  // ---------------- Modal ----------------
  function modal({ title, body, footer, wide }) {
    let ov = qs("#modal-ov");
    if (!ov) { ov = document.createElement("div"); ov.id = "modal-ov"; ov.className = "overlay"; document.body.appendChild(ov); }
    ov.innerHTML = `<div class="modal ${wide ? "wide" : ""}">
      <div class="modal-head"><h3>${esc(title)}</h3><span class="x-close" id="modal-x">${ICON.x}</span></div>
      <div class="modal-body">${body}</div>
      ${footer ? `<div class="modal-foot">${footer}</div>` : ""}</div>`;
    ov.classList.add("open");
    const close = () => ov.classList.remove("open");
    qs("#modal-x", ov).onclick = close;
    ov.onclick = (e) => { if (e.target === ov) close(); };
    return { close, root: ov };
  }

  // ---------------- Shell ----------------
  let USER = null;

  function buildShell() {
    const view = qs("#view");
    const title = document.body.dataset.title || "Sentinel";
    const path = location.pathname;

    const navItems = NAV.filter((n) => {
      if (n.roles) return n.roles.includes(USER.role);
      if (n.min) return (ROLE_RANK[USER.role] || 0) >= ROLE_RANK[n.min];
      return true;
    }).map((n) => `<a href="${n.href}" class="${path === n.href ? "active" : ""}">${ICON[n.icon]}<span>${n.label}</span>${n.href === "/tasks" ? '<span class="count" id="nav-tasks" style="display:none"></span>' : ""}</a>`).join("");

    const shell = document.createElement("div");
    shell.className = "app";
    shell.innerHTML = `
      <aside class="side" id="side">
        <div class="brand">
          <div class="brand-logo" data-brand-logo>${AGORA_LOGO}</div>
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
          <div class="row">
            <button class="iconbtn hamburger" id="ham" aria-label="Menu">${ICON.menu}</button>
            <div><h1>${esc(title)}</h1><div class="sub" id="top-sub"></div></div>
          </div>
          <div class="top-right">
            ${USER.role === "super_admin" ? '<span class="pill amber" title="You are viewing as Super Admin — full access to every module and record">Super Admin view</span>' : ""}
            <div class="theme-toggle" id="theme-toggle">
              <button data-set-theme="light" title="Light mode">${ICON.sun}</button>
              <button data-set-theme="dark" title="Dark mode">${ICON.moon}</button>
            </div>
            <div class="clock" id="clock"></div>
            <div style="position:relative">
              <button class="iconbtn" id="bell" aria-label="Notifications">${ICON.bell}<span class="bdot" id="bell-count" style="display:none"></span></button>
              <div class="notif-panel" id="notif-panel"></div>
            </div>
            <button class="iconbtn" id="logout" title="Log out">${ICON.logout}</button>
          </div>
        </header>
        <div class="content"></div>
      </div>`;
    document.body.insertBefore(shell, view);
    qs(".content", shell).appendChild(view);

    const scrim = document.createElement("div"); scrim.className = "scrim"; scrim.id = "scrim"; document.body.appendChild(scrim);
    const side = qs("#side");
    const toggle = () => { side.classList.toggle("open"); scrim.classList.toggle("open"); };
    qs("#ham").onclick = toggle; scrim.onclick = toggle;
    qs("#logout").onclick = async () => { await api("/api/auth/logout", { method: "POST" }); location.href = "/login"; };
    // Light/dark toggle
    function paintTheme() {
      const t = document.documentElement.getAttribute("data-theme") || "light";
      qsa("#theme-toggle button").forEach((b) => b.classList.toggle("on", b.dataset.setTheme === t));
    }
    qsa("#theme-toggle button").forEach((b) => b.onclick = () => {
      const t = b.dataset.setTheme;
      document.documentElement.setAttribute("data-theme", t);
      try { localStorage.setItem(THEME_KEY, t); } catch (e) {}
      paintTheme();
      applyBrandLogo();  // swap to the light/white logo variant for the new theme
    });
    paintTheme();
    const uc = qs("#user-card"); if (uc) uc.onclick = openChangePassword;

    startClock();
    wireBell();
    refreshTaskCount();
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
          </div>`).join("") : '<div class="empty">You\'re all caught up 🎉</div>'}</div>`;
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
    const candidates = dark
      ? ["/static/img/logo-dark.png", "/static/img/logo.png"]
      : ["/static/img/logo.png", "/static/img/logo.svg"];
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
    buildShell();
    applyBrandLogo();
    if (window.pageInit) {
      try { await window.pageInit(Sentinel); }
      catch (e) { console.error(e); toast(e.detail || "Something went wrong", "err"); }
    }
  }

  const Sentinel = {
    api, toast, modal, esc, qs, qsa, ICON, avatar, initials,
    fmtTime, fmtDate, fmtDateFull, timeAgo, priorityDot, labelPills, statusPill,
    roleRank: ROLE_RANK,
    get user() { return USER; }, set user(u) { USER = u; },
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

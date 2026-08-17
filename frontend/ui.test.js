/* =====================================================================================
   ui.test.js — real-DOM regression guard for the shared contracts in app.js:
     • modal()    — role/labelling, initial focus, the focus TRAP, stack-aware focus RESTORE
     • sortTable() — the "—" means UNKNOWN rule, numeric-vs-text, aria-sort, data-sort override

   WHY THIS EXISTS AS A FILE. `node --check` — the frontend's only other gate — cannot see any of
   this: every bug it catches parses perfectly. Writing it found two on its first run: the ✕ binding
   resolving to null once a second dialog opened (a scoped `querySelector("#modal-x")` consulting the
   document id map), and the trap wrapping to the wrong end.

   HOW TO RUN. There is no package.json in this repo on purpose (no build step — AGENTS.md §8), so
   jsdom is not a tracked dependency. Install it ad hoc, anywhere outside the repo, and point NODE_PATH
   at it:

     cd %TEMP% && npm install jsdom --no-save
     cd <repo>/frontend && NODE_PATH=%TEMP%/node_modules node ui.test.js

   Exits non-zero on any failure, so CI can adopt it the day this repo grows a package.json. The
   sibling precedent is docs/taskboard_target_prototype.smoke.js, which hand-rolls a DOM stub instead;
   prefer jsdom for anything touching focus, since focus is exactly what a stub gets wrong.

   HOW IT WORKS. app.js is an IIFE that boots on DOMContentLoaded and calls /api/auth/me, so fetch is
   stubbed and the shell is allowed to build; we then drive the REAL modal() through window.Sentinel.
   ===================================================================================== */
// An async test body turns any throw into an unhandled rejection rather than a crash, so surface it
// as a real failure — otherwise a broken assertion section would exit 0 and look like a pass.
process.on("unhandledRejection", (e) => {
  console.log("UNHANDLED: " + (e && (e.stack || e)));
  process.exit(1);
});
const fs = require("fs");
const path = require("path");
const { JSDOM } = require("jsdom");

// Relative to this file, so the test runs from a clone at any path.
const FE = __dirname;
const appJs = fs.readFileSync(path.join(FE, "static/js/app.js"), "utf8");

const USER = {
  id: 1, name: "Test User", email: "t@agora.ph", role: "super_admin",
  role_label: "Super Admin", team_name: "Ops", profile_pic_url: null,
};

const routes = {
  "/api/auth/me": USER,
  "/api/vocab": { colors: {}, roles: [], task_status_meta: [] },
  "/api/notifications": { items: [], unread: 0 },   // the bell reads d.items, not a bare array
  "/api/notifications/unread-count": { count: 0 },
  "/api/dashboard": { me: {}, kpis: {}, late_today_list: [], handovers: [] },
  "/api/teams": [],
  "/api/people": [],
  "/api/tasks": [],
};

const dom = new JSDOM(
  `<!doctype html><html><head></head><body data-title="Test"><div id="view"></div></body></html>`,
  { url: "http://localhost:8010/dashboard", runScripts: "outside-only", pretendToBeVisual: true }
);
const { window } = dom;

// Every request boot() and the pages make, so the vocab contract below can be asserted on counts.
const calls = [];
window.fetch = async (url) => {
  const p = String(url).split("?")[0];
  calls.push(p);
  const body = Object.prototype.hasOwnProperty.call(routes, p) ? routes[p] : [];
  return {
    ok: true, status: 200,
    headers: { get: (h) => (h.toLowerCase() === "content-type" ? "application/json" : null) },
    json: async () => body,
    text: async () => JSON.stringify(body),
  };
};
window.matchMedia = window.matchMedia || (() => ({ matches: false, addEventListener() {}, removeEventListener() {} }));

// jsdom has no layout, so offsetParent is always null — which would make focusablesIn() return []
// and every assertion below vacuous. Report visibility the way a laid-out browser would: visible
// unless the element or an ancestor is [hidden] / display:none / a shut <details>.
Object.defineProperty(window.HTMLElement.prototype, "offsetParent", {
  configurable: true,
  get() {
    for (let n = this; n && n !== window.document.body; n = n.parentElement) {
      if (n.hasAttribute && n.hasAttribute("hidden")) return null;
      if (n.style && n.style.display === "none") return null;
      if (n.tagName === "DETAILS" && !n.open) return null;
      if (n.parentElement && n.parentElement.tagName === "DETAILS"
          && !n.parentElement.open && n.tagName !== "SUMMARY") return null;
    }
    return window.document.body;
  },
});

// 🔴 Do NOT dispatch DOMContentLoaded by hand. jsdom's readyState is "loading" at construction, so
// app.js registers its own listener and jsdom fires that event itself once parsing finishes — a
// manual dispatch makes boot() run TWICE, and the second buildShell() throws NotFoundError from
// `insertBefore(shell, view)` because the first run already moved #view into .content.
dom.window.eval(appJs);

let fails = 0, passes = 0;
const ok = (cond, label, extra) => {
  if (cond) { passes++; console.log("  ok   " + label); }
  else { fails++; console.log("  FAIL " + label + (extra ? "  -> " + extra : "")); }
};
const tab = (shift) => {
  const e = new window.KeyboardEvent("keydown", { key: "Tab", shiftKey: !!shift, bubbles: true, cancelable: true });
  window.document.dispatchEvent(e);
  return e;
};
const esc = () => window.document.dispatchEvent(
  new window.KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true }));

// `async` because section 17 awaits S.refreshVocab(). Any throw inside becomes an unhandled
// rejection rather than a crash, so it is reported explicitly below.
setTimeout(async () => {
  const S = window.Sentinel;
  if (!S || !S.modal) { console.log("FATAL: window.Sentinel.modal missing"); process.exit(1); }
  const D = window.document;

  // A control on the "page" behind the dialog — focus must never reach it while a modal is open,
  // and must come back to it on close.
  const pageBtn = D.createElement("button");
  pageBtn.id = "page-btn"; pageBtn.textContent = "page";
  D.body.appendChild(pageBtn);
  pageBtn.focus();
  ok(D.activeElement === pageBtn, "baseline: page button holds focus");

  console.log("\n=== 1. dialog semantics ===");
  const m = S.modal({
    title: "My Dialog",
    body: '<input id="one"><input id="two"><input id="hidden-one" hidden>',
    footer: '<button id="cancel">Cancel</button><button id="save">Save</button>',
  });
  const dlg = m.root.querySelector(".modal");
  ok(dlg.getAttribute("role") === "dialog", 'role="dialog"');
  ok(dlg.getAttribute("aria-modal") === "true", 'aria-modal="true"');
  const lb = dlg.getAttribute("aria-labelledby");
  const titleEl = lb && D.getElementById(lb);
  ok(!!titleEl && titleEl.textContent === "My Dialog", "aria-labelledby resolves to the title text",
     lb + " -> " + (titleEl && titleEl.textContent));
  ok(dlg.getAttribute("tabindex") === "-1", 'tabindex="-1" fallback target');
  ok(m.root.querySelector(".x-close").tagName === "BUTTON", "close control is a <button>");
  ok(m.root.querySelector(".x-close").getAttribute("aria-label") === "Close", "close has aria-label");

  console.log("\n=== 2. initial focus ===");
  ok(D.activeElement === D.getElementById("one"),
     "focus moved to the first focusable in the body",
     D.activeElement && (D.activeElement.id || D.activeElement.className));
  ok(D.activeElement.id !== "modal-x", "initial focus is NOT the close button");

  console.log("\n=== 3. focus trap ===");
  const closeBtn = dlg.querySelector(".modal-head .x-close");
  // The ✕ IS part of the cycle and is first in DOM order (head precedes body). It is skipped only for
  // the initial landing — keeping it out of the cycle would make it keyboard-unreachable, which is
  // the bug this change exists to fix.
  D.getElementById("save").focus();
  let ev = tab(false);
  ok(ev.defaultPrevented, "Tab on the LAST control is intercepted");
  ok(D.activeElement === closeBtn, "…and wraps to the first focusable, which is the ✕",
     D.activeElement && (D.activeElement.className || D.activeElement.id));
  ev = tab(true);
  ok(ev.defaultPrevented, "Shift+Tab on the FIRST control (the ✕) is intercepted");
  ok(D.activeElement === D.getElementById("save"), "…and wraps to the last",
     D.activeElement && D.activeElement.id);
  // Mid-list Tab must be left alone for the browser to handle natively.
  D.getElementById("one").focus();
  ev = tab(false);
  ok(!ev.defaultPrevented, "Tab in the MIDDLE is not intercepted (native order preserved)");
  // A [hidden] input must never be a trap boundary: Tab off the last control must skip it entirely.
  D.getElementById("save").focus(); tab(false);
  ok(D.activeElement !== D.getElementById("hidden-one"),
     "a [hidden] control is never the wrap target",
     D.activeElement && (D.activeElement.className || D.activeElement.id));
  // Escaped focus gets pulled back.
  pageBtn.focus();
  ev = tab(false);
  ok(ev.defaultPrevented, "Tab is intercepted when focus has escaped the dialog");
  ok(dlg.contains(D.activeElement), "…and focus is pulled back inside",
     D.activeElement && D.activeElement.id);

  console.log("\n=== 4. stacking: trap follows the TOP dialog ===");
  const inner = D.getElementById("two");
  inner.focus();
  const m2 = S.modal({ title: "Confirm", body: "<p>Sure?</p>", footer: '<button id="yes">Yes</button>' });
  const dlg2 = m2.root.querySelector(".modal");
  ok(D.activeElement === D.getElementById("yes"), "second dialog takes focus",
     D.activeElement && D.activeElement.id);
  ok(D.getElementById(dlg2.getAttribute("aria-labelledby")).textContent === "Confirm",
     "second dialog's aria-labelledby is its OWN title (ids not collided)");
  ok(dlg.getAttribute("aria-labelledby") !== dlg2.getAttribute("aria-labelledby"),
     "the two dialogs have DIFFERENT title ids");
  tab(false);
  ok(dlg2.contains(D.activeElement), "Tab stays inside the TOP dialog, not the one beneath",
     D.activeElement && D.activeElement.id);

  console.log("\n=== 5. focus restore is stack-aware ===");
  esc();
  ok(!D.body.contains(dlg2), "Esc closed the top dialog only");
  ok(D.body.contains(dlg), "…the dialog beneath survives");
  ok(D.activeElement === inner,
     "focus returned to the control INSIDE the dialog beneath (not the page)",
     D.activeElement && D.activeElement.id);

  console.log("\n=== 6. closing the last dialog returns focus to the page ===");
  m.close();
  ok(!D.body.contains(dlg), "dialog removed");
  ok(D.activeElement === pageBtn, "focus restored to the page control that opened it",
     D.activeElement && (D.activeElement.id || D.activeElement.tagName));

  console.log("\n=== 7. body with no focusable control falls back to the dialog ===");
  pageBtn.focus();
  const m3 = S.modal({ title: "Just a message", body: "<p>Nothing to focus here.</p>" });
  const dlg3 = m3.root.querySelector(".modal");
  ok(D.activeElement === dlg3 || D.activeElement === dlg3.querySelector(".modal-head .x-close"),
     "focus landed on the dialog itself (or the only control, the ✕)",
     D.activeElement && (D.activeElement.className || D.activeElement.tagName));
  ok(dlg3.contains(D.activeElement), "focus is inside the dialog either way");
  m3.close();
  ok(D.activeElement === pageBtn, "restored again");

  console.log("\n=== 8. the command palette outranks the modal stack ===");
  // Ctrl+K is not gated on the modal stack, so the palette can open OVER a dialog. Both keydown
  // handlers live on document, so the trap and Esc must both stand down while it is up — otherwise
  // Tab yanks the caret out of the palette into the dialog beneath, and Esc closes both at once.
  const held = S.modal({ title: "Underneath", body: '<input id="under-1">' });
  const heldDlg = held.root.querySelector(".modal");
  const cmdk = D.getElementById("cmdk");
  ok(!!cmdk, "palette overlay #cmdk exists");
  cmdk.classList.add("open");
  const pInput = D.getElementById("cmdk-input");
  pInput.focus();
  ev = tab(false);
  ok(!ev.defaultPrevented, "Tab is NOT trapped while the palette is open");
  ok(D.activeElement === pInput, "…and focus stays in the palette input",
     D.activeElement && D.activeElement.id);
  esc();
  ok(D.body.contains(heldDlg), "Esc does NOT close the dialog beneath the palette");
  cmdk.classList.remove("open");
  // With the palette down, the modal is the top layer again.
  ev = tab(false);
  ok(ev.defaultPrevented, "once the palette closes, Tab is trapped again");
  esc();
  ok(!D.body.contains(heldDlg), "…and Esc closes the dialog again");

  console.log("\n=== 9. no listener leak ===");
  const before = S.modal({ title: "a", body: "<input id='x1'>" });
  before.close();
  pageBtn.focus();
  ev = tab(false);
  ok(!ev.defaultPrevented, "with the stack empty, Tab is no longer intercepted anywhere");

  // ==================================================================================
  //                                  sortTable()
  // ==================================================================================
  const mkTable = (heads, rows) => {
    const wrap = D.createElement("div");
    wrap.innerHTML = `<table><thead><tr>${
      heads.map((h) => `<th class="${h.sortable === false ? "" : "sortable"}">${h.label}</th>`).join("")
    }</tr></thead><tbody>${
      rows.map((r) => `<tr>${r.map((c) =>
        typeof c === "object" ? `<td data-sort="${c.sort}">${c.text}</td>` : `<td>${c}</td>`).join("")}</tr>`).join("")
    }</tbody></table>`;
    D.body.appendChild(wrap);
    return wrap.querySelector("table");
  };
  const colText = (table, col) =>
    Array.from(table.tBodies[0].rows).map((r) => r.children[col].textContent.trim());
  const clickHead = (table, col) => table.querySelectorAll("thead th")[col].querySelector(".th-sort").click();

  console.log("\n=== 10. sortTable: wiring ===");
  let t1 = mkTable([{ label: "Name" }, { label: "Qty" }, { label: "Act", sortable: false }],
                   [["Beta", "10", "x"], ["alpha", "9", "x"], ["Gamma", "2", "x"]]);
  S.sortTable(t1);
  ok(t1.querySelectorAll("thead th .th-sort").length === 2, "a <button> is injected into each sortable th only");
  ok(!t1.querySelectorAll("thead th")[2].querySelector(".th-sort"), "a non-sortable th is left alone");
  ok(t1.querySelectorAll("thead th")[0].textContent.includes("Name"), "the header label survives the wrap");
  S.sortTable(t1);
  ok(t1.querySelectorAll("thead th .th-sort").length === 2, "calling it twice does not double the buttons");

  console.log("\n=== 11. sortTable: text and aria-sort ===");
  clickHead(t1, 0);
  ok(t1.querySelectorAll("thead th")[0].getAttribute("aria-sort") === "ascending", 'aria-sort="ascending" on first click');
  ok(JSON.stringify(colText(t1, 0)) === JSON.stringify(["alpha", "Beta", "Gamma"]),
     "text sorts case-insensitively ascending", colText(t1, 0).join(","));
  clickHead(t1, 0);
  ok(t1.querySelectorAll("thead th")[0].getAttribute("aria-sort") === "descending", "second click flips to descending");
  ok(JSON.stringify(colText(t1, 0)) === JSON.stringify(["Gamma", "Beta", "alpha"]), "…and reverses the rows",
     colText(t1, 0).join(","));
  clickHead(t1, 1);
  ok(!t1.querySelectorAll("thead th")[0].hasAttribute("aria-sort"),
     "sorting another column CLEARS the first column's aria-sort");

  console.log("\n=== 12. sortTable: numbers are not text ===");
  ok(JSON.stringify(colText(t1, 1)) === JSON.stringify(["2", "9", "10"]),
     "9 sorts before 10 (numeric, not lexicographic)", colText(t1, 1).join(","));
  let t2 = mkTable([{ label: "Pay" }], [["PHP 1,200"], ["PHP 340"], ["PHP 20,000"]]);
  S.sortTable(t2); clickHead(t2, 0);
  ok(JSON.stringify(colText(t2, 0)) === JSON.stringify(["PHP 340", "PHP 1,200", "PHP 20,000"]),
     "currency with thousands separators sorts numerically", colText(t2, 0).join(" | "));
  let t3 = mkTable([{ label: "H" }], [["10.5h"], ["9h"], ["-2h"]]);
  S.sortTable(t3); clickHead(t3, 0);
  ok(JSON.stringify(colText(t3, 0)) === JSON.stringify(["-2h", "9h", "10.5h"]),
     "units, decimals and negatives sort numerically", colText(t3, 0).join(" | "));

  console.log("\n=== 13. 🔴 sortTable: '—' is UNKNOWN and sinks in BOTH directions ===");
  // The rule the growth tables paid for: rendering an outage as a zero reads as "nobody is doing
  // anything". Reversing the sort must not float the unknowns to the top.
  let t4 = mkTable([{ label: "Score" }], [["50"], ["—"], ["10"], [""], ["90"]]);
  S.sortTable(t4);
  clickHead(t4, 0);
  let got = colText(t4, 0);
  ok(JSON.stringify(got.slice(0, 3)) === JSON.stringify(["10", "50", "90"]),
     "ascending: real values sort first", got.join(" | "));
  ok(got.slice(3).every((v) => v === "—" || v === ""), "ascending: unknowns are LAST", got.join(" | "));
  clickHead(t4, 0);
  got = colText(t4, 0);
  ok(JSON.stringify(got.slice(0, 3)) === JSON.stringify(["90", "50", "10"]), "descending: real values reverse",
     got.join(" | "));
  ok(got.slice(3).every((v) => v === "—" || v === ""),
     "🔴 descending: unknowns are STILL last, not floated to the top", got.join(" | "));

  console.log("\n=== 14. sortTable: data-sort overrides the rendered text ===");
  // Attendance/Leave rely on this: the cell prints "Aug 17" or a date RANGE, neither of which sorts.
  let t5 = mkTable([{ label: "Date" }], [
    [{ sort: "2026-08-02", text: "Aug 2" }],
    [{ sort: "2026-07-30", text: "Jul 30" }],
    [{ sort: "2026-08-11", text: "Aug 11" }],
  ]);
  S.sortTable(t5); clickHead(t5, 0);
  ok(JSON.stringify(colText(t5, 0)) === JSON.stringify(["Jul 30", "Aug 2", "Aug 11"]),
     "sorts by the ISO data-sort, not the displayed month name", colText(t5, 0).join(" | "));
  // An empty data-sort must still count as unknown, so a missing clock-out is not midnight.
  let t6 = mkTable([{ label: "Out" }], [
    [{ sort: "2026-08-02T18:00:00Z", text: "6:00 PM" }],
    [{ sort: "", text: "" }],
    [{ sort: "2026-08-02T09:00:00Z", text: "9:00 AM" }],
  ]);
  S.sortTable(t6); clickHead(t6, 0);
  ok(colText(t6, 0)[2] === "", "an empty data-sort sinks as unknown", colText(t6, 0).join(" | "));
  clickHead(t6, 0);
  ok(colText(t6, 0)[2] === "", "…in both directions", colText(t6, 0).join(" | "));

  console.log("\n=== 15. sortTable: robustness ===");
  ok((() => { try { S.sortTable(null); return true; } catch (e) { return false; } })(),
     "a null table is a no-op, not a throw");
  const noHeads = mkTable([{ label: "A", sortable: false }], [["1"]]);
  ok((() => { try { S.sortTable(noHeads); return true; } catch (e) { return false; } })(),
     "a table with no sortable headers is a no-op");

  // ==================================================================================
  //                    the /api/vocab contract  (perf pass, 2026-08-17)
  // ==================================================================================
  // `/api/vocab` is SEVEN-plus SELECTs server-side and is hit on every page load. It used to be
  // fetched twice per navigation (boot(), then again by dashboard/manage/people/taskboard) and
  // serially after /api/auth/me. These assertions pin the fix; without them the duplicate creeps
  // back the next time a page needs `roles` or `priorities`, and nothing would notice.
  console.log("\n=== 16. /api/vocab is fetched ONCE, in parallel with auth/me ===");
  const vocabCalls = calls.filter((c) => c === "/api/vocab").length;
  ok(vocabCalls === 1, "boot() fetched /api/vocab exactly once", "saw " + vocabCalls);
  ok(!!S.vocab, "the snapshot is published as S.vocab");
  ok(S.vocab && Array.isArray(S.vocab.roles), "…and carries the shape pages read (roles)");
  ok(typeof S.refreshVocab === "function", "S.refreshVocab exists for surfaces that EDIT vocabulary");
  // Parallel, not serial: auth/me must not have resolved before vocab was even requested. Both are
  // issued in the same tick, so their positions in `calls` are adjacent.
  const iMe = calls.indexOf("/api/auth/me"), iV = calls.indexOf("/api/vocab");
  ok(iMe >= 0 && iV >= 0 && Math.abs(iMe - iV) === 1,
     "auth/me and vocab were issued together (parallel, not a waterfall)",
     "positions " + iMe + " and " + iV);

  console.log("\n=== 17. refreshVocab re-reads and re-publishes ===");
  const vocabCallsBefore = calls.filter((c) => c === "/api/vocab").length;
  routes["/api/vocab"] = { colors: {}, roles: [{ value: "x", label: "X" }], task_status_meta: [] };
  const refreshed = await S.refreshVocab();
  ok(calls.filter((c) => c === "/api/vocab").length === vocabCallsBefore + 1,
     "it makes exactly one new request");
  ok(refreshed && refreshed.roles.length === 1 && refreshed.roles[0].value === "x",
     "it returns the FRESH payload");
  ok(S.vocab.roles[0].value === "x", "…and S.vocab now reflects it (so Manage's edits reach the app)");

  console.log("\n" + (fails ? fails + " FAILED, " : "") + passes + " passed");
  process.exit(fails ? 1 : 0);
}, 60);

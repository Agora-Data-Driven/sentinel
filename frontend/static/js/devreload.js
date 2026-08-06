/* Live reload — LOCAL DEVELOPMENT ONLY. Loaded by app.js, and only on localhost.
   The server half is backend/app/routers/dev.py; read its header for the three gates that keep
   this out of production. This file is inert unless something loads it, and the only thing that
   does is a hostname test.

   What it does with a change, and why the split matters:

     a .css edit   -> the <link> href is re-pointed with a fresh ?v= (a real HOT swap: no reload)
     anything else -> location.reload()

   The CSS path is the reason this is worth having. A full reload throws away the state you are
   usually looking at while styling — the open task card, the board's filters, the scroll position,
   an expanded "More options" — so the edit-and-look loop kept costing three clicks to get back to
   where you were. Swapping the stylesheet keeps every one of those.

   🔴 IT ALSO UNREGISTERS THE SERVICE WORKER (once, on localhost). That is not tidiness — it is the
   difference between this feature working and appearing to work. sw.js caches CSS/JS and answers
   from that cache on failure, so a reload could serve the file you just edited *from before you
   edited it*, with no error anywhere. This is the local twin of the deploy-time rule "bump CACHE in
   sw.js" (AGENTS.md §5): in production a version bump purges the cache, and locally there is no
   version to bump because nobody edits sw.js on every save. */
(function () {
  "use strict";

  var SOURCE = "/api/dev/reload";
  var tag = function (m) { return ["%c[dev-reload]%c " + m, "color:#F2820C;font-weight:700", ""]; };
  var log = function (m) { console.log.apply(console, tag(m)); };

  // ---- Kill the service worker locally -----------------------------------------------------
  // Registered by app.js for the PWA/offline kiosk, which is a production concern. Locally it can
  // only ever serve you a stale asset. `unregister()` does not affect any other origin, and the
  // next load of the real site re-registers it — this is per-origin state, not a code change.
  if ("serviceWorker" in navigator && navigator.serviceWorker.getRegistrations) {
    navigator.serviceWorker.getRegistrations().then(function (regs) {
      if (!regs.length) return;
      regs.forEach(function (r) { r.unregister(); });
      // Its cache outlives the registration, so drop that too or the first reload still hits it.
      if (window.caches && caches.keys) {
        caches.keys().then(function (keys) { keys.forEach(function (k) { caches.delete(k); }); });
      }
      log("service worker unregistered + caches cleared (local only) — reloading once");
      // The page currently running was itself possibly served through the worker, so reload once to
      // get a clean one. Guarded by a session flag: without it, an unregister-then-reload cycle
      // could re-run on the fresh page and loop.
      if (!sessionStorage.getItem("devreload.swcleared")) {
        sessionStorage.setItem("devreload.swcleared", "1");
        location.reload();
      }
    }).catch(function () { /* not supported / blocked — the SSE half still works */ });
  }

  // ---- Hot-swap every stylesheet ------------------------------------------------------------
  // Re-points each <link rel=stylesheet> at the same URL with a new cache-buster. The browser
  // fetches it, applies it, and repaints — no reload, no lost state.
  //
  // The new href is applied to the EXISTING element rather than by inserting a second <link>. A
  // second link would render both sheets for a frame (the old one until the new one loads), which
  // is invisible for a colour change and very visible for a layout one.
  function swapStyles() {
    var links = document.querySelectorAll('link[rel="stylesheet"]');
    var swapped = 0;
    for (var i = 0; i < links.length; i++) {
      var href = links[i].getAttribute("href") || "";
      // Only ours. A cache-buster on the Google Fonts URL would refetch the font on every save.
      if (href.indexOf("//") === 0 || href.indexOf("http") === 0) continue;
      links[i].setAttribute("href", href.split("?")[0] + "?v=" + Date.now());
      swapped += 1;
    }
    return swapped;
  }

  // ---- Connect -----------------------------------------------------------------------------
  if (!window.EventSource) { log("EventSource unsupported — live reload off"); return; }

  var es = new EventSource(SOURCE);

  // The server's process id, remembered from the FIRST hello. A different one means uvicorn restarted
  // (a Python edit), so the page is now running against a backend it did not load with — reload it.
  //
  // This is also what makes a mixed Python+JS save reliable. A reconnecting stream rebuilds its
  // baseline from disk, so any frontend file saved while the backend was down is already IN that
  // baseline and would compare equal forever; the change event for it can never arrive. Keying off
  // the restart instead means the reload happens for a reason that is still observable.
  var boot = null;
  es.addEventListener("hello", function (e) {
    var id = null;
    try { id = (JSON.parse(e.data) || {}).boot || null; } catch (_) { /* older server: no id */ }
    if (boot === null) {
      boot = id;
      log("watching frontend/ — save a file");
      return;
    }
    if (id && id !== boot) { log("backend restarted -> reloading"); location.reload(); }
  });

  es.addEventListener("change", function (e) {
    var paths = [];
    try { paths = (JSON.parse(e.data) || {}).paths || []; } catch (_) { /* fall through to reload */ }

    // CSS-only batches swap in place. A mixed batch (someone saved a .js and a .css together, or an
    // editor wrote both) reloads — the JS has to re-run, and a half-applied change is worse than a
    // reload. `every` over an empty array is true, so the parse failure above deliberately lands on
    // "not all CSS" only when paths is non-empty; an unparseable event reloads, which is the safe
    // default for a message we did not understand.
    var allCss = paths.length > 0 && paths.every(function (p) { return /\.css$/i.test(p); });
    if (allCss) {
      var n = swapStyles();
      log(paths.join(", ") + " -> swapped " + n + " stylesheet" + (n === 1 ? "" : "s") + ", no reload");
      return;
    }
    log((paths.join(", ") || "change") + " -> reloading");
    location.reload();
  });

  // EventSource retries on its own (the server sends `retry: 1000`), so an error here is usually
  // uvicorn restarting after a Python edit — the normal case, not a fault. Stay quiet and let the
  // browser reconnect; the `hello` handler above turns that reconnect into the reload.
  es.addEventListener("error", function () {
    if (es.readyState === EventSource.CLOSED) log("stream closed — reload the page to resume");
  });

  window.addEventListener("beforeunload", function () { es.close(); });
})();

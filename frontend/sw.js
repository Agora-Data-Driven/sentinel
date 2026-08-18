/* Sentinel service worker — PWA + offline kiosk support.
   Strategy: NETWORK-FIRST for everything (with cache fallback), so a redeploy's fresh assets
   always win when online, while the kiosk still works offline from cache. API calls are never
   cached — attendance punches queue in IndexedDB (see kiosk.js) instead.
   Bump CACHE on each meaningful change so old caches are purged on activate. */
const CACHE = "sentinel-v106";
const CORE = [
  "/static/css/styles.css",
  "/static/js/app.js",
  // Precached because the login page cannot be signed into without it, and it is the one page every
  // person hits before they have anything else cached.
  "/static/js/login.js",
  "/static/js/charts.js",
  "/static/js/kiosk.js",
  "/static/vendor/html5-qrcode.min.js",
  "/static/favicon.svg",
  "/static/img/logo.png",
  "/kiosk",
  "/manifest.json",
];

self.addEventListener("install", (e) => {
  // no-cache Requests so precaching revalidates instead of copying stale HTTP-cache entries.
  e.waitUntil(
    caches.open(CACHE)
      .then((c) => c.addAll(CORE.map((u) => new Request(u, { cache: "no-cache" }))).catch(() => {}))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== self.location.origin) return; // never touch API/mutations/cross-origin
  if (url.pathname.startsWith("/api/")) return;

  // Page navigations MUST reach the server so its auth redirects are authoritative -- e.g. /login
  // 302s an already-signed-in user straight to /dashboard. Serving a cached HTML page here would
  // show a stale login screen that flashes for ~2s before the client-side SSO forward finishes.
  // So don't intercept navigations (browser -> network directly), EXCEPT keep the attendance kiosk
  // booting offline from cache.
  if (e.request.mode === "navigate") {
    if (url.pathname === "/kiosk") {
      e.respondWith(
        fetch(e.request)
          .then((res) => { const copy = res.clone(); caches.open(CACHE).then((c) => c.put(e.request, copy)); return res; })
          .catch(() => caches.match("/kiosk"))
      );
    }
    return; // every other navigation: straight to the network, no cached-HTML flash
  }

  // Static assets (css/js/img): network-first -- fresh copy when online (cache it for offline),
  // fall back to cache when offline. cache:"no-cache" forces conditional revalidation so the
  // BROWSER HTTP cache can't satisfy this fetch with a heuristically-"fresh" stale asset from
  // before a deploy (the 2026-07-27 "undefined KPIs" incident) — server 304s make it cheap.
  // (Navigations above can't take a RequestInit — fetch(navigate-mode request, init) throws —
  // but they're covered by the server's Cache-Control: no-cache header instead.)
  // 🔴 A MISS FAILS, it does NOT fall back to /kiosk. This used to end
  // `|| caches.match("/kiosk")`, so an offline request for an uncached ASSET was answered with the
  // kiosk's HTML DOCUMENT — a script tag then received `text/html`, which `X-Content-Type-Options:
  // nosniff` blocks outright. On /login that meant login.js never defined pageInit, so the form was
  // never wired: a page that rendered perfectly and could not sign anyone in. Response.error() makes
  // the fetch fail as what it is, so the browser reports it in the console. Never return a
  // wrong-type body (and never an EMPTY 200 either — a blank script is worse, it fails silently).
  // 🔴 The OFFLINE fallback ignores the query string, and that is required by content-versioned
  // asset URLs (backend/app/assets.py, 2026-08-13). Page shells now ask for
  // `/static/js/kiosk.js?v=<hash>`, while CORE above precaches the bare `/static/js/kiosk.js` — an
  // exact-match lookup would MISS and the kiosk would fail to boot offline on a tablet that had
  // installed this worker but never completed an online page load. `?v=` names the same file, so on
  // the fallback path a cached copy under either spelling is the right answer; a slightly older
  // asset beats a dead page, which is the entire point of having a fallback.
  //
  // It changes nothing when online: the fetch above is still network-first and still wins, so a
  // fresh deploy is never served from cache while the network is reachable.
  e.respondWith(
    fetch(e.request, { cache: "no-cache" })
      .then((res) => { const copy = res.clone(); caches.open(CACHE).then((c) => c.put(e.request, copy)); return res; })
      .catch(() => caches.match(e.request, { ignoreSearch: true }).then((hit) => hit || Response.error()))
  );
});

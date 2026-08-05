/* Sentinel service worker — PWA + offline kiosk support.
   Strategy: NETWORK-FIRST for everything (with cache fallback), so a redeploy's fresh assets
   always win when online, while the kiosk still works offline from cache. API calls are never
   cached — attendance punches queue in IndexedDB (see kiosk.js) instead.
   Bump CACHE on each meaningful change so old caches are purged on activate. */
const CACHE = "sentinel-v78";
const CORE = [
  "/static/css/styles.css",
  "/static/js/app.js",
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
  e.respondWith(
    fetch(e.request, { cache: "no-cache" })
      .then((res) => { const copy = res.clone(); caches.open(CACHE).then((c) => c.put(e.request, copy)); return res; })
      .catch(() => caches.match(e.request).then((hit) => hit || caches.match("/kiosk")))
  );
});

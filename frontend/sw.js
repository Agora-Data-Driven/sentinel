/* Sentinel service worker — PWA + offline kiosk support.
   Strategy: NETWORK-FIRST for everything (with cache fallback), so a redeploy's fresh assets
   always win when online, while the kiosk still works offline from cache. API calls are never
   cached — attendance punches queue in IndexedDB (see kiosk.js) instead.
   Bump CACHE on each meaningful change so old caches are purged on activate. */
const CACHE = "sentinel-v14";
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
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(CORE).catch(() => {})).then(() => self.skipWaiting()));
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

  // Network-first: fresh copy when online (cache it for offline), fall back to cache when offline.
  e.respondWith(
    fetch(e.request)
      .then((res) => { const copy = res.clone(); caches.open(CACHE).then((c) => c.put(e.request, copy)); return res; })
      .catch(() => caches.match(e.request).then((hit) => hit || caches.match("/kiosk")))
  );
});

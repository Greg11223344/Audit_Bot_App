const CACHE_NAME = "audit-bot-field-v2";
const APP_SHELL = [
  "/app/",
  "/app/index.html",
  "/app/manifest.json",
  "/app/css/style.css",
  "/app/js/app.js",
  "/app/js/api.js",
  "/app/js/db.js",
  "/app/js/i18n.js",
  "/app/js/sync.js",
  "/app/icons/icon-192.png",
  "/app/icons/icon-512.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(APP_SHELL)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);

  // Never intercept API calls or uploaded attachments -- those need real network/cache semantics
  // handled by the app itself (IndexedDB offline queue), not a generic SW cache.
  if (url.pathname.startsWith("/api/") || url.pathname.startsWith("/attachments/")) {
    return;
  }

  if (event.request.method !== "GET") return;

  // Network-first: while online, always prefer the freshly deployed file (so a redeploy is
  // visible immediately, without depending on someone remembering to bump CACHE_NAME). Only
  // fall back to the cached copy when the network request fails, which is what gives the app
  // its offline capability.
  event.respondWith(
    fetch(event.request)
      .then((response) => {
        if (response.ok) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
        }
        return response;
      })
      .catch(() => caches.match(event.request))
  );
});

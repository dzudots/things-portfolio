const CACHE = "things-v3";
const PRECACHE = [
  "/",
  "/static/styles.css?v=7",
  "/static/charts.js?v=2",
  "/static/icons/icon-192.png",
  "/manifest.webmanifest",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE).then((cache) => cache.addAll(PRECACHE)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;

  const url = new URL(req.url);
  // Never cache private HTML/API — only static shell assets
  const privatePrefixes = [
    "/api/", "/account", "/portfolio", "/items", "/alerts",
    "/metrics", "/scan", "/achievements", "/login", "/register",
  ];
  if (privatePrefixes.some((p) => url.pathname.startsWith(p))) {
    return;
  }

  if (url.pathname.startsWith("/static/") || url.pathname === "/manifest.webmanifest") {
    event.respondWith(
      caches.match(req).then((cached) => {
        const fetched = fetch(req).then((res) => {
          const copy = res.clone();
          caches.open(CACHE).then((cache) => cache.put(req, copy));
          return res;
        }).catch(() => cached);
        return cached || fetched;
      })
    );
  }
});

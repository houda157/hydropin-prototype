// HydroPin farmer app: works offline once opened (app shell cached), always fresh data.
// The app files are served from the cache and refreshed in the background; anything from the
// backend (/api, /health, /ws) always goes to the network.
const CACHE = "hydropin-app-v1";
const SHELL = [
  "./", "index.html", "app.css", "main.js", "screens.js", "farm.js", "demo.js",
  "lib/i18n.js", "lib/strings.js", "lib/severity.js", "lib/savings.js", "lib/status.js", "lib/source.js", "lib/route.js",
  "../config.js", "manifest.webmanifest", "icons/icon.svg", "icons/icon-192.png", "icons/icon-512.png",
];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys()
    .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin || /\/(api|health|ws)(\/|$)/.test(url.pathname)) return;
  e.respondWith(caches.open(CACHE).then(async (cache) => {
    const cached = await cache.match(e.request);
    const fresh = fetch(e.request).then((r) => { if (r.ok) cache.put(e.request, r.clone()); return r; }).catch(() => cached);
    return cached || fresh;
  }));
});

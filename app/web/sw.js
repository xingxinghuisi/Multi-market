/* Cache only the public application shell. Financial and account data stay network-only. */
const CACHE = "market-radar-shell-v12";
const VERSION = "2026.10.11.3";
const SHELL = ["/", ...["mobile.css","mobile.js","mobile-core.js","whales.js","app-update.js"].map(name=>`/static/${name}?v=${VERSION}`),
  "/static/radar-icon.svg", "/static/radar-192.png", "/static/radar-512.png", "/static/manifest.webmanifest"];
self.addEventListener("install", event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", event => {
  event.waitUntil(caches.keys().then(keys => Promise.all(keys
    .filter(key => key.startsWith("market-radar-shell-") && key !== CACHE)
    .map(key => caches.delete(key)))).then(() => self.clients.claim()));
});
self.addEventListener("fetch", event => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET" || url.origin !== self.location.origin ||
      !SHELL.includes(url.pathname+url.search)) return;
  // Revalidate the public shell rather than accepting a fresh but outdated HTTP cache entry.
  event.respondWith(fetch(event.request,{cache:"no-cache"}).then(response => {
    if (response.ok) {
      const copy = response.clone();
      event.waitUntil(caches.open(CACHE).then(cache => cache.put(event.request, copy)));
    }
    return response;
  }).catch(async () => (await caches.match(event.request)) || Response.error()));
});

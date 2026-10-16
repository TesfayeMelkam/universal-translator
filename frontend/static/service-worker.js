// Caches ONLY the app shell (pages, scripts, styles, translations, icons). API responses (translations, history,
// documents, accounts) are never cached. Offline: the shell opens, the offline badge shows, translation needs internet.
const CACHE = "ut-shell-v7";
const SHELL = ["/", "/static/css/app.css", "/static/offline.html", "/static/manifest.json", "/static/icons/icon.svg",
  "/static/i18n/index.json", "/static/i18n/en.json", "/static/i18n/am.json", "/static/i18n/om.json", "/static/i18n/ti.json",
  ...["app", "core", "i18n", "account", "pwa", "translate-camera", "video-call", "large-call", "documents", "server-voice", "setup"]
    .map((n) => `/static/js/${n}.js`)];
self.addEventListener("install", (e) => e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting())));
self.addEventListener("activate", (e) => e.waitUntil(
  caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim())));
self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin || url.pathname.startsWith("/api/") ||
      url.pathname.startsWith("/ws/") || url.pathname === "/health") return;
  e.respondWith(fetch(e.request).then((res) => {
    if (res.ok && SHELL.includes(url.pathname)) { const copy = res.clone(); caches.open(CACHE).then((c) => c.put(e.request, copy)); }
    return res;
  }).catch(() => caches.match(e.request, { ignoreSearch: true }).then((r) => r || (e.request.mode === "navigate" ? caches.match("/static/offline.html") : Response.error()))));
});

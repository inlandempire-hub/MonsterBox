/* MonsterBox service worker — caches the app shell for offline use.
 * Bump CACHE when you change any cached asset to force an update. */
const CACHE = "monsterbox-v35";
const ASSETS = [
  "./", "index.html", "engine.js", "pdfimport.js", "manifest.webmanifest",
  "vendor/pdf.min.js", "vendor/pdf.worker.min.js",
  "bg-light.jpg", "bg-dark.jpg", "MonsterBox.ico",
  "icons/icon-192.png", "icons/icon-512.png", "icons/icon-maskable-512.png",
];

self.addEventListener("install", (e) => {
  e.waitUntil(
    caches.open(CACHE).then((c) => c.addAll(ASSETS)).then(() => self.skipWaiting())
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
  if (url.pathname.indexOf("/api/") !== -1) return;          // local API shim handles these in-page
  if (e.request.method !== "GET") return;
  e.respondWith(
    caches.match(e.request).then((hit) => hit || fetch(e.request))
  );
});

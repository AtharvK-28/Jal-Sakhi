// JalSakhi service worker: the app opens without network, and reports saved offline are sent when it returns.
//   pages      network first, the cached app shell when offline
//   /assets/*  cache first (file names carry a content hash, so a cached copy is never stale)
//   API calls  never cached: live water status must not be served from yesterday
const CACHE = "jalsakhi-shell-v1";
const SYNC_TAG = "jalsakhi-reports";

self.addEventListener("install", (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE);
    const res = await fetch("/index.html", { cache: "no-cache" });
    const html = await res.clone().text();
    await cache.put("/index.html", res);
    const assets = [...new Set(html.match(/\/assets\/[^"'\s)]+/g) || [])];
    await cache.addAll(["/manifest.webmanifest", "/icons/icon-192.png", "/icons/icon-512.png", ...assets]);
    await self.skipWaiting();
  })());
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    for (const k of await caches.keys()) if (k !== CACHE) await caches.delete(k);
    await self.clients.claim();
  })());
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  const url = new URL(req.url);
  if (req.method !== "GET" || url.origin !== self.location.origin || url.pathname.startsWith("/api/") || url.pathname.startsWith("/uploads/")) return;
  if (req.mode === "navigate") {
    event.respondWith((async () => {
      try {
        const res = await fetch(req);
        if (res.ok) (await caches.open(CACHE)).put("/index.html", res.clone());
        return res;
      } catch {
        return (await caches.match("/index.html")) || Response.error();
      }
    })());
    return;
  }
  if (url.pathname.startsWith("/assets/") || url.pathname.startsWith("/icons/")) {
    event.respondWith((async () => {
      const hit = await caches.match(req);
      if (hit) return hit;
      const res = await fetch(req);
      if (res.ok) (await caches.open(CACHE)).put(req, res.clone());
      return res;
    })());
  }
});

// ---------------------------------------------------------------- offline reports (same store as src/lib/offline.ts)
function store(mode) {
  return new Promise((resolve, reject) => {
    const r = indexedDB.open("jalsakhi", 1);
    r.onupgradeneeded = () => r.result.createObjectStore("reports", { keyPath: "id", autoIncrement: true });
    r.onsuccess = () => resolve(r.result.transaction("reports", mode).objectStore("reports"));
    r.onerror = () => reject(r.error);
  });
}
const done = (r) => new Promise((resolve, reject) => { r.onsuccess = () => resolve(r.result); r.onerror = () => reject(r.error); });

async function sendQueued() {
  const items = await done((await store("readonly")).getAll());
  for (const it of items) {
    const fd = new FormData();
    for (const [k, v] of Object.entries(it.fields)) fd.append(k, v);
    if (it.photo) fd.append("photo", it.photo, "photo.jpg");
    const res = await fetch(it.url, { method: "POST", body: fd }); // throws while offline: the browser retries the sync later
    if (res.status >= 500) throw new Error(`server ${res.status}`);
    await done((await store("readwrite")).delete(it.id));
  }
}

self.addEventListener("sync", (event) => {
  if (event.tag === SYNC_TAG) event.waitUntil(sendQueued());
});

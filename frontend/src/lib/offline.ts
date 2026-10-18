// Reports made without network wait on the phone, photo included, and go out when the network returns:
// from the service worker's background sync where the browser has it (public/sw.js reads the same store),
// otherwise from the page while it is open.

const DB = "jalsakhi";
const STORE = "reports";
export const SYNC_TAG = "jalsakhi-reports";
const LEGACY_KEY = "jalsakhi.citizen.queue"; // the earlier queue in localStorage held text only

type Item = { id?: number; url: string; fields: Record<string, string>; photo: Blob | null; created: number };

function open(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB, 1);
    req.onupgradeneeded = () => req.result.createObjectStore(STORE, { keyPath: "id", autoIncrement: true });
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function tx<T>(mode: IDBTransactionMode, fn: (s: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  const db = await open();
  return new Promise((resolve, reject) => {
    const r = fn(db.transaction(STORE, mode).objectStore(STORE));
    r.onsuccess = () => resolve(r.result);
    r.onerror = () => reject(r.error);
  });
}

export async function queueReport(url: string, fields: Record<string, string>, photo: Blob | null) {
  await tx("readwrite", (s) => s.add({ url, fields, photo, created: Date.now() } as Item));
  try {
    const reg: any = await navigator.serviceWorker?.ready;
    await reg?.sync?.register(SYNC_TAG); // Chrome on Android: sends even after the app is closed
  } catch { /* no background sync here: the page sends it instead */ }
}

export async function pendingCount(): Promise<number> {
  try { return await tx("readonly", (s) => s.count()); } catch { return 0; }
}

/** Send what is waiting. Stops at the first network failure; a report the server refuses outright is dropped. */
export async function flushReports(): Promise<number> {
  let items: Item[];
  try { items = await tx("readonly", (s) => s.getAll() as IDBRequest<Item[]>); } catch { return 0; }
  let sent = 0;
  for (const it of items) {
    const fd = new FormData();
    Object.entries(it.fields).forEach(([k, v]) => fd.append(k, v));
    if (it.photo) fd.append("photo", it.photo, "photo.jpg");
    try {
      const res = await fetch(it.url, { method: "POST", body: fd });
      if (res.status >= 500) break; // server trouble: try again later
      if (res.ok) sent++;
    } catch { break; } // still offline
    await tx("readwrite", (s) => s.delete(it.id!));
  }
  return sent;
}

/** Move reports queued by the earlier version of the app into the new store. */
export async function migrateLegacyQueue(url: string) {
  let old: any[] = [];
  try { old = JSON.parse(localStorage.getItem(LEGACY_KEY) || "[]"); } catch { /* unreadable: nothing to move */ }
  if (!old.length) return;
  for (const f of old) await queueReport(url, Object.fromEntries(Object.entries(f).map(([k, v]) => [k, String(v)])), null);
  localStorage.removeItem(LEGACY_KEY);
}

/** A phone photo is often 3-6 MB; village networks are slow. Re-encode to at most 1600 px as JPEG. */
export async function shrinkPhoto(f: File, max = 1600): Promise<Blob> {
  if (f.size < 400_000 || !("createImageBitmap" in window)) return f;
  try {
    const bmp = await createImageBitmap(f);
    const k = Math.min(1, max / Math.max(bmp.width, bmp.height));
    const c = document.createElement("canvas");
    c.width = Math.round(bmp.width * k); c.height = Math.round(bmp.height * k);
    c.getContext("2d")!.drawImage(bmp, 0, 0, c.width, c.height);
    const out = await new Promise<Blob | null>((r) => c.toBlob(r, "image/jpeg", 0.8));
    return out && out.size < f.size ? out : f;
  } catch { return f; }
}

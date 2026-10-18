import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { api, getSession, resolveUrl } from "./api";

type Scope = { level: string; id: string };
type Live = {
  snap: any; meta: any; tree: any; connected: boolean; stale: boolean;
  village: string; setVillage: (v: string) => void;
  scope: Scope; setScope: (s: Scope) => void;
  focus: any; clock: any; refresh: () => void;
};

const Ctx = createContext<Live>(null as any);
export const useLive = () => useContext(Ctx);

/** Subscribes to the server-sent snapshot stream for the selected village and exposes it to every page. */
export function LiveProvider({ children }: { children: React.ReactNode }) {
  const session = getSession()!;
  const mine = session.user.villages;
  const [meta, setMeta] = useState<any>(null);
  const [tree, setTree] = useState<any>(null);
  const [snap, setSnap] = useState<any>(null);
  const [connected, setConnected] = useState(false);
  const [stale, setStale] = useState(false);
  const [village, setVillageRaw] = useState<string>(() => {
    const saved = localStorage.getItem("jalsakhi.village");
    return saved && mine.includes(saved) ? saved : mine.includes("VLG-PW") ? "VLG-PW" : mine[0];
  });
  const [scope, setScopeRaw] = useState<Scope>(() => {
    try {
      const s = JSON.parse(localStorage.getItem("jalsakhi.scope") || "null");
      if (s && s.user === session.user.username) return { level: s.level, id: s.id };
    } catch { /* ignore */ }
    return { level: session.user.scope_level, id: session.user.scope_id };
  });
  const es = useRef<EventSource | null>(null);

  const setVillage = useCallback((v: string) => { localStorage.setItem("jalsakhi.village", v); setVillageRaw(v); }, []);
  const setScope = useCallback((s: Scope) => {
    localStorage.setItem("jalsakhi.scope", JSON.stringify({ ...s, user: session.user.username }));
    setScopeRaw(s);
    if (s.level === "village") setVillage(s.id);
  }, [session.user.username, setVillage]);

  useEffect(() => {
    api("/api/meta").then(setMeta).catch(() => {});
    api("/api/hierarchy").then((h) => setTree(h.tree)).catch(() => {});
  }, []);

  // A server left running across an update still answers, but with its old routes and payloads, and newer
  // screens then have nothing to draw. It reports that in /api/health; a server from before this check has
  // no "stale" field at all, which means the same thing. An unreachable server is the "Reconnecting" case.
  useEffect(() => {
    const ask = () => api("/api/health", { auth: false }).then((h) => setStale(h.stale !== false)).catch(() => {});
    ask();
    const t = setInterval(ask, 8000);
    return () => clearInterval(t);
  }, []);

  const connect = useCallback(() => {
    es.current?.close();
    const src = new EventSource(resolveUrl(`/api/stream?village=${village}&token=${encodeURIComponent(session.token)}`));
    src.onopen = () => setConnected(true);
    src.onmessage = (e) => { setSnap(JSON.parse(e.data)); setConnected(true); };
    src.onerror = () => setConnected(false);
    es.current = src;
  }, [village, session.token]);

  useEffect(() => { connect(); return () => es.current?.close(); }, [connect]);

  const refresh = useCallback(() => {
    api(`/api/snapshot?village=${village}`).then(setSnap).catch(() => {});
  }, [village]);

  const value = useMemo<Live>(() => ({
    snap, meta, tree, connected, stale, village, setVillage, scope, setScope,
    focus: snap?.focus && snap.focus.id === village ? snap.focus : null, clock: snap?.clock, refresh,
  }), [snap, meta, tree, connected, stale, village, setVillage, scope, setScope, refresh]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

/** Villages (from the live summary) that fall under the current scope. */
export function useScopeVillages() {
  const { snap, scope } = useLive();
  return useMemo(() => {
    const all: any[] = snap?.summary || [];
    if (scope.level === "village") return all.filter((v) => v.id === scope.id);
    if (scope.level === "block") return all.filter((v) => v.block_id === scope.id);
    if (scope.level === "district") return all.filter((v) => v.district_id === scope.id);
    return all;
  }, [snap, scope]);
}

/** Fetch a resource and refetch every `every` ms (and whenever deps change).
 *  The answer is kept with the path it was asked for, so a caller never sees one resource's data under
 *  another's path, and a slow answer for a path the caller has already left is dropped. */
export function usePoll<T = any>(path: string | null, every = 4000, deps: any[] = []) {
  const [got, setGot] = useState<{ path: string | null; data: T | null; error: string | null }>({ path: null, data: null, error: null });
  const epoch = useRef(0);
  const load = useCallback(() => {
    if (!path) return;
    const mine = epoch.current;
    api(path)
      .then((d) => { if (mine === epoch.current) setGot({ path, data: d, error: null }); })
      .catch((e) => { if (mine === epoch.current) setGot((g) => ({ path, data: g.path === path ? g.data : null, error: e.message })); });
  }, [path]);
  useEffect(() => {
    epoch.current++;
    load();
    if (!every) return;
    const t = setInterval(load, every);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [load, every, ...deps]);
  const mine = got.path === path;
  return { data: mine ? got.data : null, error: mine ? got.error : null, reload: load };
}

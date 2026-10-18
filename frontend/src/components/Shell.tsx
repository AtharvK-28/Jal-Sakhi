import { useMemo, useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import {
  BarChart3, BellRing, ChevronRight, Cpu, Droplets, FlaskConical, Home, LayoutDashboard, LogOut, Map as MapIcon, Menu, MessageSquareText,
  Moon, Network, Pause, RefreshCw, ShieldCheck, Siren, Smartphone, Sparkles, Sun, Volume2, VolumeX, WifiOff, Wrench,
} from "lucide-react";
import { api, clearSession, getSession } from "../lib/api";
import { useLive } from "../lib/live";
import { Drop, Modal, ToastHost, toast } from "./ui";
import { DemoPanel } from "./DemoPanel";

const NAV = [
  { grp: "Monitor" },
  { to: "/app", end: true, icon: LayoutDashboard, label: "Command centre" },
  { to: "/app/twin", icon: Network, label: "Network twin" },
  { to: "/app/map", icon: MapIcon, label: "GIS map" },
  { to: "/app/households", icon: Home, label: "Households" },
  { grp: "Respond" },
  { to: "/app/incidents", icon: Siren, label: "Alerts & incidents", count: "incidents" },
  { to: "/app/complaints", icon: MessageSquareText, label: "Citizen voice", count: "complaints" },
  { to: "/app/alerts", icon: BellRing, label: "Phone alerts" },
  { to: "/app/quality", icon: FlaskConical, label: "Water quality" },
  { to: "/app/upkeep", icon: Wrench, label: "Upkeep & accounts" },
  { grp: "Intelligence" },
  { to: "/app/ai", icon: Sparkles, label: "AI insights" },
  { to: "/app/analytics", icon: BarChart3, label: "Analytics" },
  { grp: "Platform" },
  { to: "/app/integration", icon: RefreshCw, label: "IMIS / Sujal Gaon sync" },
  { to: "/app/devices", icon: Cpu, label: "Devices & hardware" },
  { to: "/app/about", icon: ShieldCheck, label: "Trust & roadmap" },
] as any[];

export function useTheme() {
  const [theme, setTheme] = useState<string>(() => localStorage.getItem("jalsakhi.theme") || "light");
  document.documentElement.setAttribute("data-theme", theme);
  const toggle = () => { const t = theme === "light" ? "dark" : "light"; localStorage.setItem("jalsakhi.theme", t); setTheme(t); };
  return { theme, toggle };
}

export function Shell() {
  const { snap, clock, connected, stale, scope, setScope, tree, village, setVillage, meta } = useLive();
  const session = getSession()!;
  const nav = useNavigate();
  const { theme, toggle } = useTheme();
  const [open, setOpen] = useState(false);
  const [brief, setBrief] = useState<any>(null);
  const counts = {
    incidents: snap?.incidents?.length || 0,
    complaints: (snap?.summary || []).reduce((a: number, v: any) => a + (v.complaints_open || 0), 0),
  };
  const bubbles = useMemo(() => Array.from({ length: 11 }, (_, i) => ({ left: `${6 + ((i * 37) % 88)}%`, size: 5 + ((i * 7) % 12), dur: 9 + ((i * 5) % 11), delay: -((i * 3) % 14) })), []);

  // Breadcrumb path from the state down to the current scope, limited to the user's jurisdiction.
  const crumbs = useMemo(() => {
    if (!tree) return [];
    const out: any[] = [];
    const walk = (node: any, trail: any[]): boolean => {
      const here = [...trail, node];
      if (node.id === scope.id) { out.push(...here); return true; }
      return (node.children || []).some((c: any) => walk(c, here));
    };
    walk(tree, []);
    const order = ["state", "district", "block", "village"];
    const min = order.indexOf(session.user.scope_level);
    return out.filter((n) => order.indexOf(n.level) >= min);
  }, [tree, scope, session.user.scope_level]);
  const children = useMemo(() => {
    if (!tree) return [];
    let found: any = null;
    const walk = (n: any) => { if (n.id === scope.id) found = n; (n.children || []).forEach(walk); };
    walk(tree);
    return found?.children || [];
  }, [tree, scope]);

  const speak = async (lang: string) => {
    try {
      const b = await api(`/api/brief?village=${village}&lang=${lang}`);
      setBrief(b);
      if ("speechSynthesis" in window) {
        window.speechSynthesis.cancel();
        const u = new SpeechSynthesisUtterance(b.text);
        u.lang = { en: "en-IN", hi: "hi-IN", mr: "mr-IN" }[lang] || "en-IN";
        u.rate = 0.96;
        window.speechSynthesis.speak(u);
      }
    } catch (e: any) { toast(e.message, true); }
  };

  return (
    <>
      <div className="ribbon" role="note">
        <span>Simulated demo data</span>
        <span className="hide-sm">All households, telemetry and IDs are synthetic · integrations are sandboxed</span>
      </div>
      <div className="shell">
        <aside className={`side ${open ? "open" : ""}`}>
          <div className="bubbles" aria-hidden>{bubbles.map((b, i) => <i key={i} style={{ left: b.left, width: b.size, height: b.size, animationDuration: `${b.dur}s`, animationDelay: `${b.delay}s` }} />)}</div>
          <div className="brand"><Drop /><div><b>JalSakhi AI</b><small>Har Ghar Jal · verified</small></div></div>
          <nav className="nav" onClick={() => setOpen(false)}>
            {NAV.map((n, i) => n.grp ? <div className="grp" key={i}>{n.grp}</div> : (
              <NavLink key={n.to} to={n.to} end={n.end} className={({ isActive }) => (isActive ? "active" : "")}>
                <n.icon />{n.label}{n.count && counts[n.count as keyof typeof counts] > 0 && <span className="count">{counts[n.count as keyof typeof counts]}</span>}
              </NavLink>
            ))}
          </nav>
          <div className="side-foot">
            <div className="who">{session.user.name}</div>
            <div>{session.user.role_label}</div>
            <div className="row" style={{ marginTop: 9, gap: 6 }}>
              <button className="btn sm ghost" style={{ background: "rgba(255,255,255,.1)", color: "#fff", boxShadow: "inset 0 0 0 1px rgba(255,255,255,.2)" }} onClick={() => { clearSession(); nav("/"); }}><LogOut />Switch role</button>
              <a className="btn sm ghost" style={{ background: "rgba(255,255,255,.1)", color: "#fff", boxShadow: "inset 0 0 0 1px rgba(255,255,255,.2)" }} href="/citizen" target="_blank" rel="noreferrer"><Smartphone />Citizen app</a>
            </div>
          </div>
        </aside>
        {open && <div className="scrim" style={{ zIndex: 74 }} onClick={() => setOpen(false)} />}

        <div className="main">
          <header className="topbar">
            <button className="btn ghost icon menu-btn" onClick={() => setOpen(true)} aria-label="Menu"><Menu /></button>
            <div className="crumbs grow">
              {crumbs.map((c: any, i: number) => (
                <span key={c.id} className="row" style={{ gap: 2 }}>
                  {i > 0 && <ChevronRight className="sep" size={14} />}
                  <button className={c.id === scope.id ? "cur" : ""} onClick={() => setScope({ level: c.level, id: c.id })}>{c.name}</button>
                </span>
              ))}
              {children.length > 0 && (
                <span className="row" style={{ gap: 2 }}>
                  <ChevronRight className="sep" size={14} />
                  <select className="select" style={{ width: "auto", padding: "4px 26px 4px 9px", fontWeight: 600 }} value="" onChange={(e) => { const c = children.find((x: any) => x.id === e.target.value); if (c) setScope({ level: c.level, id: c.id }); }}>
                    <option value="">Drill down…</option>
                    {children.map((c: any) => <option key={c.id} value={c.id}>{c.name}</option>)}
                  </select>
                </span>
              )}
            </div>
            {!connected && <span className="pill critical hide-sm"><WifiOff />Reconnecting</span>}
            {clock && (
              <div className="clock" title={clock.in_window ? `Supply window ${clock.window_start}–${clock.window_end}` : `Next supply at ${clock.next_window}`}>
                <span className={`dot ${clock.in_window ? "on" : "off"}`}>{clock.running ? <Droplets size={14} /> : <Pause size={13} />}</span>
                <span className="t">{clock.time}</span>
                <span className="muted sm hide-sm">{clock.in_window ? `${clock.window_label} supply · ${clock.min_in_window}/${clock.window_len} min` : `Supply off · next ${clock.next_window}`}</span>
                {clock.speed > 1 && <span className="tag">{clock.speed}×</span>}
              </div>
            )}
            <button className="btn ghost icon" title="Spoken status brief" onClick={() => speak("en")}><Volume2 /></button>
            <button className="btn ghost icon" title="Light / deep-sea theme" onClick={toggle}>{theme === "light" ? <Moon /> : <Sun />}</button>
          </header>
          {stale && (
            <div className="stale-bar" role="alert"><div className="note warn"><RefreshCw /><span>
              <b>The server needs a restart.</b> It was started before the latest update, so newer screens (such as the 3D village map) cannot load their data.
              Close the JalSakhi window and run <b>start.bat</b> again. This page reconnects by itself.
            </span></div></div>
          )}
          <Outlet />
        </div>
      </div>
      <DemoPanel />
      <ToastHost />
      {brief && (
        <Modal onClose={() => { window.speechSynthesis?.cancel(); setBrief(null); }}>
          <div className="row between"><h2 className="row"><Volume2 size={19} color="var(--brand)" />Spoken status brief</h2>
            <button className="btn ghost icon" onClick={() => { window.speechSynthesis?.cancel(); setBrief(null); }}><VolumeX /></button></div>
          <p className="muted sm" style={{ margin: "4px 0 12px" }}>Generated from live state for {(snap?.summary || []).find((v: any) => v.id === village)?.name}. Useful on a shared screen at the Gram Panchayat, or for operators who prefer to listen.</p>
          <div className="seg" style={{ marginBottom: 12 }}>
            {[["en", "English"], ["hi", "हिन्दी"], ["mr", "मराठी"]].map(([k, l]) => <button key={k} className={brief.lang === k ? "on" : ""} onClick={() => speak(k)}>{l}</button>)}
          </div>
          <div className="card pad" style={{ fontSize: 15, lineHeight: 1.65, background: "var(--surface-2)" }}>{brief.text}</div>
          <p className="muted xs" style={{ marginTop: 10 }}>Template-generated from sensor-derived data (no language model). Voice uses the browser's speech engine; available voices vary by device.</p>
        </Modal>
      )}
    </>
  );
}

/** Village picker for pages that show a single village while the scope is wider. */
export function VillagePicker() {
  const { snap, village, setVillage, scope } = useLive();
  const list: any[] = snap?.summary || [];
  if (scope.level === "village" || list.length < 2) return null;
  return (
    <select className="select" style={{ width: "auto", fontWeight: 650 }} value={village} onChange={(e) => setVillage(e.target.value)}>
      {list.map((v) => <option key={v.id} value={v.id}>{v.name} · {v.block}</option>)}
    </select>
  );
}

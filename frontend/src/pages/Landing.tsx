import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowRight, Building2, CalendarCheck2, Eye, HardHat, Landmark, MapPinned, Radar, ShieldCheck, Smartphone, Users, Wrench } from "lucide-react";
import { api, login } from "../lib/api";
import { Drop } from "../components/ui";

const ROLES = [
  { user: "naljal.mitra", icon: Wrench, title: "Nal Jal Mitra", sub: "Village operator. Sees alerts for Pimpalwadi, records inspections, repairs and the daily log." },
  { user: "vwsc.pimpalwadi", icon: Users, title: "VWSC / Gram Panchayat", sub: "Pani Samiti view: village service status, FTK tests, upkeep and accounts, closure and overrides." },
  { user: "je.mulshi", icon: HardHat, title: "Block engineer", sub: "Mulshi block: two villages, escalations and crew assignment." },
  { user: "ee.pune", icon: Building2, title: "District engineer", sub: "Pune district roll-up across blocks with GIS and analytics." },
  { user: "state.mh", icon: Landmark, title: "State JJM cell", sub: "State view: all districts, sync status with JJM platforms." },
];
const LOOP = [
  { n: "01 SENSE", icon: Radar, t: "Sense", d: "Tank, pump, branch pressure and flow, water quality, a few metered homes, and every household's voice." },
  { n: "02 CORRELATE", icon: Eye, t: "Correlate", d: "AI learns each lane's normal, infers every home's tap status from sparse sensors, and merges citizen reports." },
  { n: "03 RESPOND", icon: Wrench, t: "Respond", d: "One prioritised queue with the suspected pipe segment, the assignee, an SLA clock and escalation." },
  { n: "04 VERIFY", icon: ShieldCheck, t: "Verify", d: "An incident closes only when telemetry recovers and the households who reported confirm it." },
  { n: "05 SUSTAIN", icon: CalendarCheck2, t: "Sustain", d: "Upkeep done before things break, an operator log checked against the sensors, and accounts that show whether the charge pays for the scheme." },
];

export function Landing() {
  const nav = useNavigate();
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState("");
  const [health, setHealth] = useState<any>(null);
  const [meta, setMeta] = useState<any>(null);
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", localStorage.getItem("jalsakhi.theme") || "light");
    api("/api/health", { auth: false }).then(setHealth).catch(() => setErr("Backend is not reachable on this address. Start it with start.bat."));
    api("/api/meta", { auth: false }).then(setMeta).catch(() => {});
  }, []);
  const bubbles = useMemo(() => Array.from({ length: 22 }, (_, i) => ({ left: `${(i * 53) % 100}%`, size: 6 + ((i * 11) % 22), dur: 10 + ((i * 7) % 16), delay: -((i * 5) % 20) })), []);
  const enter = async (user: string) => {
    setBusy(user); setErr("");
    try { await login(user, meta?.demo_password || "jal123"); nav("/app"); } catch (e: any) { setErr(e.message); setBusy(null); }
  };
  const households = (meta?.villages || []).reduce((a: number, v: any) => a + v.households, 0);
  const d = "M0 70 Q 150 20 300 70 T 600 70 T 900 70 T 1200 70 T 1500 70 T 1800 70 T 2100 70 T 2400 70 V 160 H 0 Z";

  return (
    <div className="landing">
      <div className="sun" />
      <div className="bubbles" aria-hidden>{bubbles.map((b, i) => <i key={i} style={{ left: b.left, width: b.size, height: b.size, animationDuration: `${b.dur}s`, animationDelay: `${b.delay}s` }} />)}</div>
      <div className="in">
        <div className="row between wrap" style={{ marginBottom: 54 }}>
          <div className="brand" style={{ padding: 0 }}><Drop /><div><b style={{ fontSize: 21 }}>JalSakhi AI</b><small>SIH 2026 · PS 26255 · Ministry of Jal Shakti</small></div></div>
          <span className="pill demo" style={{ fontSize: 12 }}>Proof of concept · simulated data</span>
        </div>

        <h1>From installed taps<br />to <em>verified water service.</em></h1>
        <p className="lede">
          JalSakhi AI watches every Functional Household Tap Connection in a village, in real time, without a sensor in every home.
          It learns what normal looks like, spots trouble early, hears citizens in their own language, and proves the fix worked.
        </p>
        <div className="row wrap" style={{ marginTop: 26, gap: 12 }}>
          <button className="btn" style={{ padding: "13px 22px", fontSize: 15 }} disabled={!!busy || !health} onClick={() => enter("demo.admin")}>Open the command centre<ArrowRight /></button>
          <a className="btn ghost" style={{ padding: "13px 22px", fontSize: 15, background: "rgba(255,255,255,.12)", color: "#fff", boxShadow: "inset 0 0 0 1px rgba(255,255,255,.35)" }} href="/citizen"><Smartphone />Citizen app</a>
        </div>
        {err && <p style={{ marginTop: 14, color: "#fecaca", fontWeight: 600 }}>{err}</p>}

        <div className="stat-strip" style={{ marginTop: 46 }}>
          <div className="glass s"><b>{households || "–"}</b><span>simulated household taps in {meta?.villages?.length || 6} villages</span></div>
          <div className="glass s"><b>76%</b><span>of rural taps were fully functional in the national assessment (JJM FA 2024)</span></div>
          <div className="glass s"><b>15 of 100</b><span>homes metered in the demo village; the other 85 are inferred</span></div>
          <div className="glass s"><b>{health ? health.sim_time.slice(11, 16) : "–"}</b><span>simulation clock, {health?.running ? "running" : "paused"} · tick {health?.tick ?? "–"}</span></div>
        </div>

        <div className="upper" style={{ color: "#7dd3fc", margin: "46px 0 12px" }}>A closed loop, not a dashboard</div>
        <div className="loop">
          {LOOP.map((s) => <div className="glass st" key={s.n}><span className="n">{s.n}</span><b className="row"><s.icon size={17} />{s.t}</b><span>{s.d}</span></div>)}
        </div>

        <div className="upper" style={{ color: "#7dd3fc", margin: "46px 0 12px" }}>Enter as a demo role (one click, role-scoped access)</div>
        <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(168px, 1fr))", gap: 12 }}>
          <a className="glass role" href="/citizen">
            <span className="ico"><Smartphone /></span><b>Household / citizen</b>
            <span>Mobile app in six languages: today's water, report with photo and voice, track, confirm the fix.</span>
          </a>
          {ROLES.map((r) => (
            <button key={r.user} className="glass role" disabled={!!busy || !health} onClick={() => enter(r.user)}>
              <span className="ico"><r.icon /></span><b>{r.title}</b><span>{busy === r.user ? "Signing in…" : r.sub}</span>
            </button>
          ))}
        </div>

        <div className="glass" style={{ marginTop: 40, padding: "16px 18px", fontSize: 12.5, color: "#d3ecfd", lineHeight: 1.6 }}>
          <b className="row" style={{ color: "#fff", marginBottom: 4 }}><MapPinned size={16} />What is real and what is not</b>
          The software, detection logic, ML models, workflows and tests are real and running. The villages, households, sensor readings and
          citizen reports are simulated; place names and all LGD / IMIS / Sujal Gaon identifiers are placeholders. Integration with JJM
          platforms runs against a local sandbox: nothing is sent to any government system. Models are trained on simulator output and
          are not field-validated. The 76% figure is from the Functionality Assessment of Household Tap Connections 2024 (DDWS).
        </div>
      </div>
      <div className="ocean" aria-hidden>
        <svg className="w1" style={{ animation: "drift 16s linear infinite" }} viewBox="0 0 2400 160" preserveAspectRatio="none"><path d={d} fill="rgba(34,211,238,.18)" /></svg>
        <svg style={{ animation: "drift 11s linear infinite reverse" }} viewBox="0 0 2400 160" preserveAspectRatio="none"><path d={d} fill="rgba(125,211,252,.16)" transform="translate(-140 22)" /></svg>
        <svg style={{ animation: "drift 8s linear infinite" }} viewBox="0 0 2400 160" preserveAspectRatio="none"><path d={d} fill="rgba(3,24,41,.75)" transform="translate(-60 46)" /></svg>
      </div>
    </div>
  );
}

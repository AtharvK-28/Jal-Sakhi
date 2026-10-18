import { useEffect, useRef, useState } from "react";
import { FlaskConical, Network, Ruler, Scale, Sparkles } from "lucide-react";
import { api } from "../lib/api";
import { useLive, usePoll } from "../lib/live";
import { Loader, StatusBar } from "../components/ui";
import { LineChart } from "../components/charts";
import { Twin, TwinLegend } from "../components/Twin";
import { Equity, PressureProfile, ReplayBar, WaterBalance, WhatIf } from "../components/twinTools";
import { VillagePicker } from "../components/Shell";
import { HouseholdDrawer } from "./Households";
import { fromMinute, n0, n1 } from "../lib/format";

export function TwinPage() {
  const { focus: liveV, clock: liveClock, village } = useLive();
  const [sel, setSel] = useState<string | null>(null);
  const [lane, setLane] = useState(0);
  const [view, setView] = useState<"profile" | "trend">("profile");
  const [at, setAt] = useState<number | null>(null); // replay tick, or null for live
  const [frame, setFrame] = useState<any>(null);
  const seq = useRef(0);
  const { data: tr } = usePoll(`/api/villages/${village}/trends?limit=150`, 4000);

  useEffect(() => { setAt(null); }, [village]);
  useEffect(() => {
    const mine = ++seq.current;
    if (at === null) { setFrame(null); return; }
    api(`/api/villages/${village}/replay?k=${at}`)
      .then((d) => { if (mine === seq.current) setFrame(d); })
      .catch(() => { if (mine === seq.current) { setAt(null); setFrame(null); } }); // that moment has left the buffer
  }, [at, village]);

  if (!liveV || !liveClock) return <div className="page"><Loader text="Connecting to the live stream" /></div>;
  const replaying = at !== null && frame && frame.focus?.id === village;
  const v = replaying ? frame.focus : liveV;
  const clock = replaying ? frame.clock : liveClock;
  const b = v.branches[Math.min(lane, v.branches.length - 1)];
  const t = tr?.branches?.[b.idx];
  const k = v.kpis;
  const evidence = Math.min(1.5, b.evidence || 0);

  return (
    <div className="page">
      <div className="page-h">
        <div><h1>Network twin · {v.name}</h1>
          <p>A live model of the scheme built only from sensor readings and citizen reports. Wind it back to see how a fault unfolded, read the pressure along any lane, check where today's water went, and try a change before making it.</p></div>
        <VillagePicker />
      </div>
      <div className={`card ${replaying ? "replaying" : ""}`}>
        <div className="card-h">
          <h3><Network />Source to tap{replaying && <span className="pill demo" style={{ marginLeft: 8 }}>replay · {clock.time}</span>}</h3>
          <div style={{ minWidth: 300, flex: "0 1 420px" }}><StatusBar counts={k.counts} total={k.households} /></div>
        </div>
        <div className="card-b">
          <Twin v={v} clock={clock} selected={sel} onSelect={setSel} />
          <div style={{ marginTop: 12 }}><TwinLegend /></div>
          <ReplayBar village={village} at={at} onSeek={setAt} />
        </div>
      </div>

      <div className="grid g2" style={{ marginTop: 16 }}>
        <div className="card">
          <div className="card-h"><h3><Ruler />Lane detail</h3>
            <div className="seg">{v.branches.map((x: any, i: number) => <button key={x.id} className={i === lane ? "on" : ""} onClick={() => setLane(i)}>{x.name}</button>)}</div></div>
          <div className="card-b">
            <div className="seg" style={{ marginBottom: 10 }}>
              <button className={view === "profile" ? "on" : ""} onClick={() => setView("profile")}>Along the lane, now</button>
              <button className={view === "trend" ? "on" : ""} onClick={() => setView("trend")}>Over time</button>
            </div>
            {view === "profile" ? <PressureProfile v={v} lane={b.idx} inWindow={!!clock.in_window} /> : (
              <LineChart height={190} yMin={0} yMax={1.6} unit=" bar" yFmt={(y) => y.toFixed(1)} xFmt={fromMinute}
                series={[{ name: "Entry pressure", color: "var(--s1)", pts: t?.p_in || [] }, { name: "Tail pressure", color: "var(--s2)", pts: t?.p_end || [] }]}
                refLines={[{ y: 0.5, label: "usable pressure 0.5 bar" }]} />)}
            <div className="grid g4" style={{ marginTop: 12 }}>
              {[["Entry", b.fresh_in && clock.in_window ? `${n1(b.p_in, 2)} bar` : "–"], ["Tail", b.fresh_end && clock.in_window ? `${n1(b.p_end, 2)} bar` : "–"], ["Flow in", b.fresh_in && clock.in_window ? `${n0(b.flow)} L/min` : "–"], ["Per person today", `${n0(b.lpcd)} L`]].map(([l, val]) => (
                <div key={l}><div className="upper muted">{l}</div><b className="num" style={{ fontSize: 17 }}>{val}</b></div>))}
            </div>
          </div>
        </div>
        <div className="card">
          <div className="card-h"><h3><Sparkles />What the models make of {b.name}</h3><span className="pill ai">AI baseline</span></div>
          <div className="card-b">
            <LineChart height={150} yMin={0} unit=" L/min" yFmt={(y) => `${Math.round(y)}`} xFmt={fromMinute}
              series={[{ name: `Measured flow into ${b.name}`, color: "var(--s1)", pts: t?.flow || [] }]}
              refLines={b.exp_flow != null && clock.in_window ? [{ y: b.exp_flow, label: `learned demand now ${n0(b.exp_flow)} L/min` }] : []} />
            <div className="meter-row" style={{ marginTop: 12 }}>
              <div>
                <div className="row between sm"><span className="ink2">Evidence of a fault</span><b className="num">{Math.round(Math.min(1, evidence) * 100)}% of alarm level</b></div>
                <div className="bar" style={{ marginTop: 5 }}><i style={{ width: `${Math.min(100, evidence * 100)}%`, background: evidence >= 1 ? "linear-gradient(90deg,#a78bfa,#5b3fd0)" : undefined }} /></div>
              </div>
              <div>
                <div className="row between sm"><span className="ink2">If it is a fault</span><b className="num">{b.p_leak == null ? "–" : b.p_leak >= 0.5 ? `leak ${Math.round(b.p_leak * 100)}%` : `obstruction ${Math.round((1 - b.p_leak) * 100)}%`}</b></div>
                <div className="bar" style={{ marginTop: 5 }}><i style={{ width: `${b.p_leak == null ? 0 : Math.max(b.p_leak, 1 - b.p_leak) * 100}%`, background: b.p_leak == null ? undefined : b.p_leak >= 0.5 ? "var(--crit)" : "var(--low)" }} /></div>
              </div>
            </div>
            <p className="sm ink2" style={{ marginTop: 10 }}>
              The lane's head-loss curve and demand profile were learned from its own sensors. Readings that stray from them add up as evidence; a fault is raised only when enough has accumulated, so a brief dip cannot trip it.
              Right now: flow <b className="num">{n1(b.z_q, 1)}σ</b> from the learned demand, pressure loss <b className="num">{n1(b.z_r, 1)}σ</b> from the curve.
              {b.segment?.near ? <> Fitted position: near <b>{b.segment.near}</b>.</> : b.segment ? <> Unexplained loss sits between <b>{b.segment.from}</b> and <b>{b.segment.to}</b>.</> : null}
            </p>
          </div>
        </div>
      </div>

      <div className="grid g2" style={{ marginTop: 16 }}>
        <div className="card">
          <div className="card-h"><h3><Scale />Water balance and equity today</h3><span className="muted xs">{replaying ? "live figures, not replayed" : "where the water went, and who got it"}</span></div>
          <div className="card-b"><WaterBalance bal={liveV.balance} /><Equity eq={liveV.equity} /></div>
        </div>
        <div className="card">
          <div className="card-h"><h3><FlaskConical />What if…</h3><span className="pill ai">calibrated model, next 24 h</span></div>
          <div className="card-b"><WhatIf v={liveV} tick={liveClock.tick || 0} /></div>
        </div>
      </div>
      {sel && <HouseholdDrawer id={sel} onClose={() => setSel(null)} />}
    </div>
  );
}

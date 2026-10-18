import { useEffect, useMemo, useRef, useState } from "react";
import { History, Pause, Play, Radio, SkipBack } from "lucide-react";
import { api } from "../lib/api";
import { usePoll } from "../lib/live";
import { LineChart } from "./charts";
import { n0, n1 } from "../lib/format";

// Past, present and future of the twin: wind it back (ReplayBar), read it more closely (PressureProfile,
// WaterBalance), and run it forward under a change (WhatIf).

// ---------------------------------------------------------------------------------- replay
// Timeline rows from the server: [tick, "HH:MM", in supply window, homes low, homes dry, homes unknown, lane alert]
type Row = [number, string, number, number, number, number, number];
const tone = (r: Row) => (!r[2] ? "var(--idle)" : r[4] > 0 ? "var(--dry)" : r[3] > 0 ? "var(--low)" : r[6] ? "#7c5cf0" : r[5] > 0 ? "var(--unk)" : "var(--flow)");

/** A strip of every recorded minute, coloured by how the village was doing, with a scrubber to wind the twin back. */
export function ReplayBar({ village, at, onSeek }: { village: string; at: number | null; onSeek: (k: number | null) => void }) {
  const { data } = usePoll<{ frames: Row[] }>(`/api/villages/${village}/timeline`, 4000);
  const rows = data?.frames || [];
  const [playing, setPlaying] = useState(false);
  const idx = at === null ? rows.length - 1 : Math.max(0, rows.findIndex((r) => r[0] === at));
  const cur = rows[idx];
  const live = at === null;

  useEffect(() => {
    if (!playing || live) return;
    const t = setInterval(() => {
      const next = rows[idx + 1];
      if (!next || idx + 1 >= rows.length - 1) { setPlaying(false); onSeek(null); } else onSeek(next[0]);
    }, 320);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [playing, live, idx, rows.length]);
  useEffect(() => { setPlaying(false); }, [village]);

  if (rows.length < 3) return null;
  const back = (mins: number) => { const want = Math.max(0, idx - mins); onSeek(rows[want][0]); };
  return (
    <div className={`replay ${live ? "" : "on"}`}>
      <div className="row between wrap" style={{ gap: 8, marginBottom: 6 }}>
        <span className="row" style={{ gap: 7 }}>
          <History size={15} color="var(--brand)" /><b className="sm">Replay</b>
          <span className="muted xs">{rows[0][1]} to {rows[rows.length - 1][1]} · drag to wind the twin back</span>
        </span>
        <span className="row" style={{ gap: 6 }}>
          {!live && cur && <span className="pill demo">Showing {cur[1]} · {cur[2] ? (cur[3] + cur[4] ? `${cur[3]} low, ${cur[4]} no water` : "all homes supplied") : "supply off"}</span>}
          <button className="btn ghost sm" onClick={() => back(15)} title="Back 15 readings"><SkipBack />15</button>
          <button className="btn ghost sm" disabled={live} onClick={() => setPlaying(!playing)}>{playing ? <Pause /> : <Play />}{playing ? "Pause" : "Play"}</button>
          <button className={`btn sm ${live ? "" : "ghost"}`} onClick={() => { setPlaying(false); onSeek(null); }}><Radio />Live</button>
        </span>
      </div>
      <div className="replay-track">
        <svg viewBox={`0 0 ${rows.length} 10`} preserveAspectRatio="none" shapeRendering="crispEdges" aria-hidden>
          {rows.map((r, i) => <rect key={r[0]} x={i} y={0} width={1.02} height={10} fill={tone(r)} />)}
        </svg>
        <input type="range" min={0} max={rows.length - 1} value={idx} aria-label="Replay position"
          onChange={(e) => { const i = Number(e.target.value); setPlaying(false); onSeek(i >= rows.length - 1 ? null : rows[i][0]); }} />
      </div>
      <div className="legend xs" style={{ marginTop: 6 }}>
        <span><i style={{ background: "var(--flow)" }} />all supplied</span><span><i style={{ background: "#7c5cf0" }} />early warning</span>
        <span><i style={{ background: "var(--low)" }} />homes on low pressure</span><span><i style={{ background: "var(--dry)" }} />homes without water</span>
        <span><i style={{ background: "var(--unk)" }} />status unknown</span><span><i style={{ background: "var(--idle)" }} />supply off</span>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------------ pressure profile
/** Pressure at every tap along one lane, against what the lane's learned healthy profile predicts at this flow. */
export function PressureProfile({ v, lane, inWindow }: { v: any; lane: number; inWindow: boolean }) {
  const b = v.branches[lane];
  const homes = useMemo(() => v.households.filter((h: any) => h.b === lane).sort((p: any, q: any) => p.pos - q.pos), [v.households, lane]);
  const label = (pos: number) => homes.find((h: any) => h.pos === pos)?.l || "";
  const est: [number, number | null][] = homes.map((h: any) => [h.pos, h.s === "idle" || h.s === "unknown" ? null : h.p]);
  const exp: [number, number | null][] = homes.map((h: any) => [h.pos, h.e ?? null]);
  const seg = b.segment;
  const worst = homes.filter((h: any) => h.e != null && h.s !== "unknown").map((h: any) => ({ l: h.l, gap: h.e - h.p })).sort((p: any, q: any) => q.gap - p.gap)[0];
  return (
    <div>
      <LineChart height={190} yMin={0} yMax={1.6} unit=" bar" area={false} yFmt={(y) => y.toFixed(1)} xFmt={label}
        empty={inWindow ? "No pressure points reporting on this lane" : "Supply is off: nothing to profile until the next window"}
        series={[{ name: "Estimated at each tap", color: "var(--s1)", pts: est }, ...(exp.some((p) => p[1] !== null) ? [{ name: "If the lane were healthy (learned)", color: "var(--s3)", dashed: true, pts: exp }] : [])]}
        refLines={[{ y: 0.5, label: "usable pressure 0.5 bar" }]} />
      <p className="sm ink2" style={{ marginTop: 10 }}>
        {seg?.kind === "leak" ? <>The gap opens up to <b>{seg.near}</b> and stays level after it: the signature of a leak. Fitted position: near <b>{seg.near}</b>, between {seg.from} and {seg.to}, with about <b className="num">{n1(seg.loss_bar, 2)} bar</b> lost{seg.citizen ? <> (a citizen sighting near {seg.citizen} is included)</> : null}.</>
          : seg ? <>Pressure steps down between <b>{seg.from}</b> and <b>{seg.to}</b> (about <b className="num">{n1(seg.loss_bar, 2)} bar</b>): a step at one point is how an obstruction or a part-closed valve shows up. It can only be placed between those two measured points.</>
            : worst && worst.gap > 0.08 ? <>Largest gap to the healthy profile is at <b>{worst.l}</b> ({n1(worst.gap, 2)} bar).</>
              : inWindow ? <>Taps on this lane sit on the learned healthy profile. Measured at {homes.filter((h: any) => h.m).map((h: any) => h.l).join(", ")} and the two lane sensors; the rest are estimated between them.</>
                : <>The profile appears when the supply window opens.</>}
      </p>
    </div>
  );
}

// --------------------------------------------------------------------------- water balance
/** What went into the network today against what homes are estimated to have used. */
export function WaterBalance({ bal }: { bal: any }) {
  if (!bal) return null;
  const pct = bal.unaccounted_pct;
  const flagged = pct != null && pct > bal.uncertainty_pct;
  const used = bal.supplied_l > 0 ? Math.max(0, Math.min(100, (bal.consumed_est_l / bal.supplied_l) * 100)) : 0;
  const lanes = bal.settling ? [] : (bal.lanes || []).filter((l: any) => l.gap_pct != null); // lane figures mean nothing until the window's water has arrived
  return (
    <div>
      {bal.supplied_l < 500 ? <div className="empty" style={{ padding: 18 }}>Nothing supplied yet today</div> : <>
        <div className="statusbar" style={{ height: 16 }} title={`${n0(bal.consumed_est_l)} L estimated use of ${n0(bal.supplied_l)} L supplied`}>
          <i style={{ flex: used, background: "var(--flow)" }} />
          {flagged && <i style={{ flex: 100 - used, background: "var(--crit)" }} />}
          {!flagged && used < 100 && <i style={{ flex: 100 - used, background: "var(--surface-3)" }} />}
        </div>
        <div className="grid g4" style={{ marginTop: 12 }}>
          <div><div className="upper muted">Supplied</div><b className="num" style={{ fontSize: 17 }}>{n1(bal.supplied_l / 1000)} kL</b><div className="xs muted">main meter, today</div></div>
          <div><div className="upper muted">Estimated use</div><b className="num" style={{ fontSize: 17 }}>{n1(bal.consumed_est_l / 1000)} kL</b><div className="xs muted">{n1(bal.per_person_l, 0)} L per person so far</div></div>
          <div><div className="upper muted">Unaccounted</div><b className="num" style={{ fontSize: 17, color: flagged ? "var(--crit)" : undefined }}>{flagged ? `${n1(bal.unaccounted_l / 1000)} kL · ${n1(pct, 0)}%` : "none evident"}</b>
            <div className="xs muted">{flagged ? `above the ±${n1(bal.uncertainty_pct, 0)}% margin` : `within the ±${n1(bal.uncertainty_pct, 0)}% margin`}</div></div>
          <div><div className="upper muted">Pumping energy</div><b className="num" style={{ fontSize: 17 }}>{bal.kwh_per_kl != null ? `${n1(bal.kwh_per_kl, 2)} kWh/kL` : "–"}</b><div className="xs muted">{n1(bal.kwh)} kWh for {n1(bal.pumped_l / 1000)} kL lifted</div></div>
        </div>
        {lanes.length > 0 && <div style={{ marginTop: 14 }}>
          <div className="upper muted" style={{ marginBottom: 6 }}>Inflow against estimated use, by lane</div>
          <div className="barlist">{lanes.map((l: any) => {
            const hot = l.gap_pct > bal.lane_margin_pct;
            return (
              <div className="r" key={l.idx} title={`${l.name}: ${n0(l.in_l)} L in, about ${n0(l.est_l)} L used by ${l.people} people`}>
                <span className="ellipsis ink2">{l.name}</span>
                <div className="trk" style={{ background: "var(--surface-3)", borderRadius: 5 }}><i style={{ width: `${Math.min(100, Math.abs(l.gap_pct) * 2.5)}%`, background: hot ? "var(--crit)" : "var(--unk)" }} /></div>
                <b className="num" style={{ color: hot ? "var(--crit)" : undefined }}>{l.gap_pct > 0 ? "+" : ""}{n1(l.gap_pct, 0)}%</b>
              </div>);
          })}</div>
        </div>}
      </>}
      <p className="xs muted" style={{ marginTop: 10 }}>Use is metered at {bal.metered_homes} homes and scaled per person to all {n0(bal.people)} residents. {bal.settling ? <><b>Still settling:</b> homes fill at different times, so the margin is wide while this window's water is arriving and narrows to 6% once it has. The lane-by-lane comparison appears then. </> : <>A lane more than {n1(bal.lane_margin_pct, 0)}% over its estimated use is worth a walk. </>}Energy is estimated from motor current.</p>
    </div>
  );
}

// ---------------------------------------------------------------------------------- equity
/** Do tail-end homes get the service head-end homes get? Usable-pressure time by thirds of the lane, and litres at metered homes. */
export function Equity({ eq }: { eq: any }) {
  if (!eq || eq.head_pct == null) return null;
  const even = eq.ratio == null || eq.ratio >= 0.9;
  const worst = [...(eq.lanes || [])].filter((l: any) => l.head_pct != null && l.tail_pct != null).sort((a: any, b: any) => (a.tail_pct - a.head_pct) - (b.tail_pct - b.head_pct))[0];
  const parts: [string, number | null][] = [["Head end", eq.head_pct], ["Middle", eq.mid_pct], ["Tail end", eq.tail_pct]];
  return (
    <div style={{ marginTop: 16, paddingTop: 14, borderTop: "1px solid var(--line)" }}>
      <div className="row between" style={{ marginBottom: 8 }}>
        <div className="upper muted">Equity: share of supply time with usable pressure</div>
        <span className={`pill ${even ? "good" : "high"}`}>{even ? "even along the lanes" : `tail end gets ${Math.round((eq.ratio || 0) * 100)}% of the head end's service`}</span>
      </div>
      <div className="barlist">{parts.map(([name, v]) => (
        <div className="r" key={name}><span className="ink2">{name}</span>
          <div className="trk" style={{ background: "var(--surface-3)", borderRadius: 5 }}><i style={{ width: `${v ?? 0}%`, background: (v ?? 100) < 80 ? "var(--low)" : "var(--flow)" }} /></div>
          <b className="num">{v == null ? "–" : `${Math.round(v)}%`}</b></div>))}</div>
      <p className="xs muted" style={{ marginTop: 9 }}>
        Thirds of each lane by distance from the tank, over {n0(eq.supply_min)} minutes of supply today.
        {eq.head_lpcd != null && <> Measured at the metered homes: <b className="num">{n1(eq.head_lpcd, 0)} L</b> per person at the first tap of each lane, <b className="num">{n1(eq.tail_lpcd, 0)} L</b> at the last.</>}
        {!even && worst && <> Widest gap: <b>{worst.name}</b> ({Math.round(worst.head_pct)}% at the head, {Math.round(worst.tail_pct)}% at the tail).</>}
      </p>
    </div>
  );
}

// --------------------------------------------------------------------------------- what-if
/** Run the calibrated model of the village forward a day under a change the operator is considering. */
export function WhatIf({ v, tick }: { v: any; tick: number }) {
  const [demand, setDemand] = useState(0);
  const [pumpOut, setPumpOut] = useState(0);
  const [closed, setClosed] = useState<number[]>([]);
  const [r, setR] = useState<any>(null);
  const [err, setErr] = useState("");
  const seq = useRef(0);
  const village = v.id;
  useEffect(() => { setClosed([]); setR(null); }, [village]);
  const stamp = Math.floor(tick / 20); // refresh the starting point now and then while the page is open
  useEffect(() => {
    const mine = ++seq.current;
    const t = setTimeout(() => {
      api(`/api/villages/${village}/whatif`, { body: { demand_pct: demand, pump_out_h: pumpOut, closed } })
        .then((d) => { if (mine === seq.current) { setR(d); setErr(""); } })
        .catch((e) => { if (mine === seq.current) setErr(e.message); });
    }, 220);
    return () => clearTimeout(t);
  }, [village, demand, pumpOut, closed, stamp]);

  const changed = demand !== 0 || pumpOut !== 0 || closed.length > 0;
  const b0 = r?.baseline, s = r?.scenario;
  const off = r?.check?.length ? r.check.reduce((a: number, c: any) => a + Math.abs(c.predicted_tail - c.measured_tail), 0) / r.check.length : null;
  const dry = (x: any) => (x?.empty_at ? `runs dry at ${x.empty_at.slice(11, 16)}` : "does not run dry");
  const toggle = (i: number) => setClosed(closed.includes(i) ? closed.filter((c) => c !== i) : [...closed, i]);
  return (
    <div>
      <div className="whatif-ctl">
        <label><span>Demand <b className="num">{demand > 0 ? "+" : ""}{demand}%</b></span>
          <input type="range" min={-30} max={80} step={5} value={demand} onChange={(e) => setDemand(Number(e.target.value))} />
          <small>festival, summer, new connections</small></label>
        <label><span>Pump unavailable <b className="num">{pumpOut} h</b></span>
          <input type="range" min={0} max={24} step={1} value={pumpOut} onChange={(e) => setPumpOut(Number(e.target.value))} />
          <small>power cut or planned maintenance, from now</small></label>
      </div>
      <div className="row wrap" style={{ gap: 6, margin: "10px 0 2px" }}>
        <span className="sm ink2" style={{ fontWeight: 600 }}>Close a lane for repair:</span>
        {v.branches.map((b: any) => <button key={b.id} className={`btn sm ${closed.includes(b.idx) ? "" : "ghost"}`} onClick={() => toggle(b.idx)}>{b.name}</button>)}
        {changed && <button className="btn ghost sm" onClick={() => { setDemand(0); setPumpOut(0); setClosed([]); }}>Reset</button>}
      </div>
      {err && <div className="note warn" style={{ marginTop: 10 }}><span>{err}</span></div>}
      {r && <>
        <div className="grid g3" style={{ marginTop: 12 }}>
          <Outcome label="Homes below usable pressure at peak" was={b0.homes_low_peak} now={s.homes_low_peak + s.homes_cut_off} worse={(a, b) => b > a}
            sub={s.homes_cut_off ? `${s.homes_cut_off} cut off by the closed lane` : s.low_peak_at ? `worst at ${s.low_peak_at}` : "none in the next 24 h"} changed={changed} />
          <Outcome label="Tank over the next 24 h" was={dry(b0)} now={dry(s)} worse={(a, b) => a !== b && b !== "does not run dry"}
            sub={s.hours_to_empty != null ? `${n1(s.hours_to_empty)} h from now, in a supply window` : "level stays above the outlet"} changed={changed} />
          <Outcome label="Demand that can be met" was={`${n1(b0.demand_met_pct, 0)}%`} now={`${n1(s.demand_met_pct, 0)}%`} worse={() => s.demand_met_pct < b0.demand_met_pct - 0.5}
            sub="share of the day's water homes will ask for" changed={changed} />
        </div>
        <div style={{ marginTop: 12 }}>
          <LineChart height={150} yMin={0} yMax={100} unit="%" area={false} yFmt={(y) => `${Math.round(y)}`} xFmt={(i) => s.curve[i]?.[0] || ""}
            series={[{ name: "Tank as things are", color: "var(--s1)", pts: b0.curve.map((c: any, i: number) => [i, c[1]]) },
              ...(changed ? [{ name: "Tank with this change", color: "var(--s2)", dashed: true, pts: s.curve.map((c: any, i: number) => [i, c[1]]) }] : [])]} />
        </div>
        <div className="tbl-wrap" style={{ marginTop: 8 }}>
          <table className="tbl"><thead><tr><th>Lane</th><th>Lowest tail pressure</th><th>{changed ? "With this change" : ""}</th><th>Homes low at once</th></tr></thead>
            <tbody>{s.lanes.map((l: any, i: number) => {
              const was = b0.lanes[i];
              const bad = l.closed || (l.min_tail != null && l.min_tail < 0.5);
              return (
                <tr key={l.idx}><td><b>{l.name}</b> <span className="muted xs">{l.n} homes</span></td>
                  <td className="num">{was.min_tail != null ? `${n1(was.min_tail, 2)} bar` : "–"}</td>
                  <td className="num">{!changed ? "" : l.closed ? <span className="pill critical">closed</span> : <span className={bad ? "pill high" : ""}>{n1(l.min_tail, 2)} bar</span>}</td>
                  <td className="num">{l.closed ? l.n : l.low_peak}</td></tr>);
            })}</tbody></table>
        </div>
        <p className="xs muted" style={{ marginTop: 10 }}>
          A model run, not a measurement: the head-loss curves and demand profile learned from this village's sensors, run forward from the present tank level.
          {off != null && <> Right now the same model predicts tail pressures within <b className="num">{n1(off, 2)} bar</b> of what the sensors read.</>} Demand is taken as given, so pressure under heavy demand is if anything understated.
        </p>
      </>}
    </div>
  );
}

function Outcome({ label, was, now, sub, worse, changed }: { label: string; was: any; now: any; sub: string; worse: (a: any, b: any) => boolean; changed: boolean }) {
  const bad = changed && worse(was, now);
  return (
    <div className={`outcome ${bad ? "bad" : ""}`}>
      <div className="upper muted">{label}</div>
      <b className="num">{String(now)}</b>
      <div className="xs muted">{changed && String(was) !== String(now) ? <>as things are: {String(was)} · </> : null}{sub}</div>
    </div>
  );
}

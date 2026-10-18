import { useState } from "react";
import { SUPPLY, clamp, n1 } from "../lib/format";

// Schematic digital twin of one village scheme. Everything drawn here is read from sensor-derived
// state: pipe colour = what the water is doing, dash speed = measured flow, a grey dashed element =
// "no recent telemetry", never "healthy".

const W = 1200, H = 606;
const TRUNK_X = 318, X0 = 372, X1 = 1128;
const WATER = "#19a7e0", MUDDY = "#a8793b", WEAK = "#8fd3f1";

type Tip = { x: number; y: number; node: React.ReactNode } | null;

export function Twin({ v, clock, selected, onSelect }: { v: any; clock: any; selected?: string | null; onSelect?: (id: string) => void }) {
  const [tip, setTip] = useState<Tip>(null);
  const nb = v.branches.length;
  const top = 40, bottom = 590;
  const gap = (bottom - top) / nb;
  const by = (b: number) => top + gap * (b + 0.5);
  const inWin = clock?.in_window;
  const muddy = (v.quality || []).some((q: any) => q.fresh && q.turbidity_ntu > 5);
  const water = muddy ? MUDDY : WATER;
  const supplying = inWin && v.branches.some((b: any) => b.fresh_in && b.p_in >= 0.15);
  const tank = v.tank || {};
  const lvl = clamp(tank.level_pct ?? 0, 0, 100);
  const pump = v.pump || {};
  const pumpFault = pump.fresh && pump.cmd && !pump.on;
  const src = v.source || {};
  const show = (e: React.MouseEvent, node: React.ReactNode) => setTip({ x: e.clientX, y: e.clientY, node });
  const hide = () => setTip(null);
  const speed = (flow: number | null) => `${clamp(40 / Math.max(flow || 0, 4), 0.35, 5).toFixed(2)}s`;

  // tank geometry
  const T = { x: 150, y: 104, w: 112, h: 126 };
  const fillY = T.y + T.h * (1 - lvl / 100);
  const wave = `M${T.x} 0 q ${T.w / 4} -7 ${T.w / 2} 0 ${` t ${T.w / 2} 0`.repeat(7)} V ${T.h + 20} H ${T.x} Z`; // 4 wave periods: sliding by half its width loops seamlessly
  const outY = 300;
  const depthFrac = src.depth_m && src.intake_m ? clamp(src.depth_m / src.intake_m, 0, 1) : 0.5;

  return (
    <div style={{ position: "relative" }}>
      <svg className="twin" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Live network diagram of ${v.name}`}>
        <defs>
          <clipPath id="tank-clip"><rect x={T.x + 4} y={T.y + 4} width={T.w - 8} height={T.h - 8} rx="10" /></clipPath>
          <linearGradient id="tank-water" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor={muddy ? "#c9a160" : "#5cc8f2"} /><stop offset="1" stopColor={muddy ? "#8a6230" : "#0a78c2"} /></linearGradient>
          <pattern id="hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="6" height="6" fill="var(--mute-bg)" /><line x1="0" y1="0" x2="0" y2="6" stroke="var(--unk)" strokeWidth="2" /></pattern>
          <filter id="soft" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="3" /></filter>
        </defs>

        {/* ---------------- source, pump, rising main ---------------- */}
        <rect x="26" y="446" width="262" height="146" rx="14" fill="var(--surface-2)" stroke="var(--line)" />
        <text className="cap" x="120" y="470">Source · borewell</text>
        <rect x="84" y="474" width="22" height="112" rx="5" fill="var(--surface-3)" stroke="var(--line-2)" />
        <rect x="86" y={476 + 108 * depthFrac} width="18" height={Math.max(2, 108 * (1 - depthFrac))} rx="3" fill={WATER} opacity={src.fresh === false ? 0.3 : 0.85} style={{ transition: "all 1s" }} />
        <text className="lbl" x="120" y="496">{src.depth_m != null ? `${n1(src.depth_m)} m` : "–"}<tspan className="val" dx="4">below ground</tspan></text>
        <text className="val" x="120" y="514">Pump intake at {n1(src.intake_m, 0)} m</text>
        {src.days_to_limit != null && <text className="val" x="120" y="532" style={{ fill: src.days_to_limit < 45 ? "var(--serious)" : "var(--ink-2)" }}>Falling {n1(src.trend_m_per_day, 2)} m/day · ~{Math.round(src.days_to_limit)} d margin</text>}
        {src.days_to_limit == null && src.trend_m_per_day != null && <text className="val" x="120" y="532">Level stable ({n1(src.trend_m_per_day, 2)} m/day)</text>}

        <path className="pipe" d={`M95 474 V 396`} strokeWidth="9" />
        <path className="pipe" d={`M95 372 V 84 H ${T.x + T.w / 2} V ${T.y}`} strokeWidth="9" />
        {pump.on && <>
          <path className="water" d={`M95 372 V 84 H ${T.x + T.w / 2} V ${T.y}`} stroke={WATER} strokeWidth="5" />
          <path className="dash" d={`M95 372 V 84 H ${T.x + T.w / 2} V ${T.y}`} strokeWidth="2.4" style={{ animationDuration: "0.7s" }} />
        </>}
        <g onMouseMove={(e) => show(e, <><b>Pump</b> {pump.fresh === false ? "· no recent telemetry" : pump.on ? "· running" : pumpFault ? "· NOT running when commanded" : "· idle"}<br />Current {n1(pump.current_a)} A · vibration {n1(pump.vibration_mms)} mm/s<br />Discharge {n1(pump.discharge_lpm, 0)} L/min{pump.risk != null && <><br />Failure risk (AI) {Math.round(pump.risk * 100)}% · health {n1(pump.health, 0)}%</>}{pump.life && <><br />Remaining life (AI): {lifeText(pump.life)}</>}</>)} onMouseLeave={hide}>
          <circle cx="95" cy="384" r="21" fill="var(--surface)" stroke={pumpFault ? "var(--crit)" : pump.on ? WATER : "var(--line-2)"} strokeWidth="3" className={pumpFault ? "pulse" : ""} />
          <g className={pump.on ? "spin" : ""} style={{ transformOrigin: "95px 384px", transformBox: "view-box" }}>
            {[0, 120, 240].map((a) => <path key={a} d="M95 384 q 4 -9 0 -15" stroke={pumpFault ? "var(--crit)" : pump.on ? "#0a78c2" : "var(--unk)"} strokeWidth="3.4" fill="none" strokeLinecap="round" transform={`rotate(${a} 95 384)`} />)}
          </g>
          <circle cx="95" cy="384" r="3" fill={pumpFault ? "var(--crit)" : pump.on ? "#0a78c2" : "var(--unk)"} />
        </g>
        <text className="lbl" x="124" y="380">Pump {pump.fresh === false ? "?" : pumpFault ? "FAULT" : pump.on ? "running" : "idle"}</text>
        <text className="val" x="124" y="396">{pump.on ? `${n1(pump.current_a)} A · ${n1(pump.discharge_lpm, 0)} L/min` : pumpFault ? "commanded on, no current" : "float switch satisfied"}</text>
        {pump.risk != null && pump.risk >= 0.4 && (
          <g><rect x="124" y="404" width="158" height="19" rx="9.5" fill={pump.risk >= 0.6 ? "var(--crit-bg)" : "var(--warn-bg)"} /><text x="203" y="417" textAnchor="middle" style={{ fontSize: 10.5, fontWeight: 700, fill: pump.risk >= 0.6 ? "var(--crit)" : "var(--warn)" }}>AI risk {Math.round(pump.risk * 100)}%{pump.life && !pump.life.capped ? ` · ~${pump.life.h < 10 ? n1(pump.life.h) : Math.round(pump.life.h)} run-h left` : ""}</text></g>
        )}

        {/* ---------------- tank ---------------- */}
        <path d={`M${T.x + 14} ${T.y + T.h} L ${T.x + 4} 330 M${T.x + T.w - 14} ${T.y + T.h} L ${T.x + T.w - 4} 330 M${T.x + 8} 290 H ${T.x + T.w - 8}`} stroke="var(--line-2)" strokeWidth="4" strokeLinecap="round" />
        <rect x={T.x} y={T.y} width={T.w} height={T.h} rx="14" fill="var(--surface)" stroke={tank.fresh === false ? "var(--unk)" : "var(--line-2)"} strokeWidth="3" strokeDasharray={tank.fresh === false ? "6 5" : undefined} />
        <g clipPath="url(#tank-clip)">
          <g style={{ transform: `translateY(${fillY}px)`, transition: "transform 1s ease" }}>
            <path className="gauge-wave b" style={{ transformBox: "fill-box" }} d={wave} fill={muddy ? "#c9a160" : "#7dd3fc"} />
            <path className="gauge-wave" style={{ transformBox: "fill-box" }} d={wave} fill="url(#tank-water)" />
          </g>
        </g>
        <text x={T.x + T.w / 2} y={T.y + T.h / 2 + 4} textAnchor="middle" style={{ fontSize: 26, fontWeight: 760, fill: "var(--ink)", letterSpacing: "-0.03em" }} stroke="var(--surface)" strokeWidth="4" paintOrder="stroke">{tank.level_pct != null ? `${Math.round(lvl)}%` : "?"}</text>
        <text x={T.x + T.w / 2} y={T.y + T.h / 2 + 22} textAnchor="middle" className="val" stroke="var(--surface)" strokeWidth="3" paintOrder="stroke">{tank.volume_l != null ? `${n1(tank.volume_l / 1000)} of ${n1(tank.capacity_l / 1000, 0)} kL` : "no telemetry"}</text>
        <text className="cap" x={T.x} y={T.y - 26}>Elevated tank</text>
        {v.forecast?.empty_at && (
          <g className="pulse"><rect x={T.x - 6} y={T.y + T.h + 8} width={T.w + 12} height="20" rx="10" fill="var(--crit-bg)" /><text x={T.x + T.w / 2} y={T.y + T.h + 22} textAnchor="middle" style={{ fontSize: 10.5, fontWeight: 700, fill: "var(--crit)" }}>Forecast: dry at {v.forecast.empty_at.slice(11, 16)}</text></g>
        )}

        {/* outlet + trunk */}
        <path className="pipe" d={`M${T.x + T.w / 2} ${T.y + T.h} V ${outY} H ${TRUNK_X} M${TRUNK_X} ${by(0)} V ${by(nb - 1)}`} strokeWidth="10" />
        {supplying && <>
          <path className="water" d={`M${T.x + T.w / 2} ${T.y + T.h} V ${outY} H ${TRUNK_X} M${TRUNK_X} ${by(0)} V ${by(nb - 1)}`} stroke={water} strokeWidth="6" />
          <path className="dash" d={`M${T.x + T.w / 2} ${T.y + T.h} V ${outY} H ${TRUNK_X}`} strokeWidth="2.6" style={{ animationDuration: speed((v.main?.flow || 0) / 3) }} />
        </>}
        <text className="val" x={T.x + T.w / 2 + 12} y={outY - 9}>{v.main?.fresh ? `${n1(v.main.flow, 0)} L/min` : "main: no data"}</text>
        {(v.quality || []).slice(0, 1).map((q: any) => <QMark key={q.id} q={q} x={T.x + T.w / 2 + 62} y={outY} show={show} hide={hide} />)}

        {/* ---------------- branches ---------------- */}
        {v.branches.map((b: any, bi: number) => {
          const y = by(bi);
          const step = (X1 - X0) / b.n;
          const hx = (pos: number) => X0 + step * (pos - 0.5);
          const fx = (x: number) => X0 + (X1 - X0) * x; // fraction along branch -> px
          const dry = !inWin || b.status === "interrupted" || !b.fresh_in || (b.p_in ?? 0) < 0.15;
          const seg = b.segment;
          const at = seg ? fx(seg.kind === "leak" && seg.x != null ? seg.x : (seg.x0 + seg.x1) / 2) : 0; // fitted leak position, or the middle of the bracket
          const weakFrom = seg && (b.status === "leak" || b.status === "low") ? at : null;
          const end = X1 + 16;
          const hhs = v.households.filter((h: any) => h.b === bi);
          const alertColor = b.status === "leak" ? "var(--crit)" : b.status === "low" ? "var(--low)" : b.status === "anomaly" ? "#7c5cf0" : null;
          return (
            <g key={b.id}>
              <path className="pipe" d={`M${TRUNK_X} ${y} H ${end}`} strokeWidth="9" style={b.fresh_in === false && inWin ? { stroke: "url(#hatch)" } : undefined} />
              {!dry && <>
                <path className="water" d={`M${TRUNK_X} ${y} H ${weakFrom ?? end}`} stroke={water} strokeWidth="5.2" />
                {weakFrom && <path className="water" d={`M${weakFrom} ${y} H ${end}`} stroke={muddy ? MUDDY : WEAK} strokeWidth="3" opacity="0.8" />}
                <path className="dash" d={`M${TRUNK_X} ${y} H ${end}`} strokeWidth="2.2" style={{ animationDuration: speed(b.flow) }} />
              </>}
              {seg && alertColor && (
                <g>
                  <path d={`M${fx(seg.x0)} ${y} H ${fx(seg.x1)}`} stroke={alertColor} strokeWidth="13" strokeLinecap="round" opacity="0.28" className="seg-alert" />
                  <path d={`M${fx(seg.x0)} ${y} H ${fx(seg.x1)}`} stroke={alertColor} strokeWidth="2" strokeDasharray="5 4" fill="none" />
                  {b.status === "leak" && [0, 1, 2].map((k) => <circle key={k} className="leak" cx={at + (k - 1) * 9} cy={y - 6} r="3.2" fill={WATER} style={{ animationDelay: `${k * 0.3}s` }} />)}
                  {seg.kind === "leak" && <path d={`M${at} ${y + 7} l-5 9 h10 Z`} fill={alertColor} />}
                  <text x={clamp(at, X0 + 120, X1 - 120)} y={y + 38} textAnchor="middle" style={{ fontSize: 10, fontWeight: 700, fill: alertColor }}>
                    {b.status === "leak" ? "suspected leak" : b.status === "low" ? "pressure lost here" : "abnormal loss"} · {seg.near ? `near ${seg.near} (${seg.from} to ${seg.to})` : `${seg.from} to ${seg.to}`}
                  </text>
                </g>
              )}
              {b.status === "interrupted" && inWin && <text x={(X0 + X1) / 2} y={y + 38} textAnchor="middle" style={{ fontSize: 10.5, fontWeight: 700, fill: "var(--crit)" }}>no supply on this lane</text>}

              {/* sensors */}
              <SensorMark x={TRUNK_X + 26} y={y} fresh={b.fresh_in} onEnter={(e) => show(e, <><b>{b.id}-IN</b> entry sensor<br />{b.fresh_in ? <>Pressure {n1(b.p_in, 2)} bar · flow {n1(b.flow, 0)} L/min{b.exp_flow != null && <><br />Learned demand at this minute: {n1(b.exp_flow, 0)} L/min</>}</> : "No recent telemetry"}</>)} onLeave={hide} />
              <SensorMark x={end} y={y} fresh={b.fresh_end} onEnter={(e) => show(e, <><b>{b.id}-END</b> tail-end sensor<br />{b.fresh_end ? `Pressure ${n1(b.p_end, 2)} bar` : "No recent telemetry: tail status cannot be measured"}</>)} onLeave={hide} />
              {bi === nb - 1 && (v.quality || []).slice(1, 2).map((q: any) => <QMark key={q.id} q={q} x={end + 26} y={y} show={show} hide={hide} />)}

              {/* labels */}
              <text className="lbl" x={TRUNK_X + 12} y={y - 30}>{b.name}<tspan className="val" dx="7">{b.n} homes</tspan></text>
              <text className="val" x={end + 8} y={y - 30} textAnchor="end">
                {!inWin ? "supply off (scheduled)" : !b.fresh_in ? "entry sensor silent" : `${n1(b.p_in, 2)} → ${b.fresh_end ? n1(b.p_end, 2) : "?"} bar · ${n1(b.flow, 0)} L/min`}
              </text>
              {inWin && (b.evidence >= 1 || b.anomaly >= 0.72) && (
                <g><rect x={end - 338} y={y - 42} width="112" height="17" rx="8.5" fill="#ece7ff" /><text x={end - 282} y={y - 30} textAnchor="middle" style={{ fontSize: 10, fontWeight: 700, fill: "#5b3fd0" }}>
                  {b.p_leak == null ? `AI anomaly ${n1(b.anomaly, 2)}` : b.p_leak >= 0.5 ? `AI: leak ${Math.round(b.p_leak * 100)}%` : `AI: obstruction ${Math.round((1 - b.p_leak) * 100)}%`}</text></g>
              )}

              {/* institutions */}
              {(v.sites || []).filter((s: any) => s.branch_idx === bi).map((s: any) => (
                <g key={s.id} onMouseMove={(e) => show(e, <><b>{s.name}</b><br />Institutional connection on {b.name}. Incidents on this lane are prioritised.</>)} onMouseLeave={hide}>
                  <rect x={hx(s.pos) - 8} y={y - 8} width="16" height="16" rx="5" fill="#fff" stroke="#7c5cf0" strokeWidth="2" />
                  <text x={hx(s.pos)} y={y + 3.6} textAnchor="middle" style={{ fontSize: 9.5, fontWeight: 800, fill: "#5b3fd0" }}>{s.kind === "school" ? "S" : s.kind === "anganwadi" ? "A" : "H"}</text>
                </g>
              ))}

              {/* households */}
              {hhs.map((h: any) => {
                const up = h.pos % 2 === 1;
                const cx = hx(h.pos), cy = y + (up ? -18 : 18);
                const st = SUPPLY[h.s];
                const sel = selected === h.id;
                return (
                  <g key={h.id} className="hh-g" onClick={() => onSelect?.(h.id)}
                    onMouseMove={(e) => show(e, <><b>{h.l}</b> · {b.name}<br />{st.label}{h.s !== "idle" && h.s !== "unknown" && <> · {n1(h.p, 2)} bar</>}<br />{h.s === "unknown" ? "No fresh pressure point nearby to estimate from" : h.s === "idle" ? "Outside the supply window" : h.hw ? "Measured by the bench node: a real board on the table" : h.m ? "Measured by a smart tap node" : `Estimated from nearby sensors · confidence ${Math.round(h.c * 100)}%`}<br />{n1(h.v, 0)} L/person today{h.r && <><br />Open citizen report</>}{h.q && <><br />Covered by a water quality concern</>}</>)}
                    onMouseLeave={hide}>
                    <line x1={cx} y1={y} x2={cx} y2={cy + (up ? 6 : -6)} stroke="var(--pipe)" strokeWidth="2" />
                    {h.s === "ok" && <circle className="hh-glow" cx={cx} cy={cy} r="10.5" fill={st.color} style={{ animationDelay: `${(h.pos % 5) * 0.3}s` }} />}
                    {h.m && <circle cx={cx} cy={cy} r="10" fill="none" stroke="var(--brand)" strokeWidth="1.3" />}
                    {h.hw && <g className="pulse"><rect x={cx - 13} y={cy - 13} width="26" height="26" rx="6" fill="none" stroke="#c026d3" strokeWidth="2.2" />
                      <text x={cx} y={cy + (up ? -17 : 25)} textAnchor="middle" style={{ fontSize: 8.5, fontWeight: 800, fill: "#a21caf" }}>REAL BOARD</text></g>}
                    {sel && <circle cx={cx} cy={cy} r="13" fill="none" stroke="var(--ink)" strokeWidth="2" />}
                    <circle className="hh" cx={cx} cy={cy} r="6.4"
                      fill={h.s === "dry" ? "var(--surface)" : h.s === "unknown" ? "url(#hatch)" : st.color}
                      stroke={h.s === "dry" ? "var(--dry)" : h.s === "unknown" ? "var(--unk)" : "var(--surface)"} strokeWidth={h.s === "dry" ? 2.6 : 1.6}
                      strokeDasharray={h.s === "unknown" ? "3 2" : undefined} />
                    {h.s === "dry" && <path d={`M${cx - 2.6} ${cy - 2.6} l5.2 5.2 M${cx + 2.6} ${cy - 2.6} l-5.2 5.2`} stroke="var(--dry)" strokeWidth="1.6" strokeLinecap="round" />}
                    {h.r && <circle cx={cx + 6.5} cy={cy - 6.5} r="3.6" fill="#f97316" stroke="var(--surface)" strokeWidth="1.4" />}
                    {h.q && <circle cx={cx - 6.5} cy={cy - 6.5} r="3.4" fill="#a8793b" stroke="var(--surface)" strokeWidth="1.4" />}
                  </g>
                );
              })}
            </g>
          );
        })}
      </svg>
      {tip && <div className="tip" style={{ left: Math.min(tip.x + 14, window.innerWidth - 290), top: tip.y + 16 }}>{tip.node}</div>}
    </div>
  );
}

/** "about 1.8 run-hours (1.3 to 2.6), from its own wear trend" */
export function lifeText(life: any) {
  if (!life) return "–";
  if (life.capped) return "more than 500 run-hours";
  const f = (x: number) => (life.h < 10 ? n1(x) : String(Math.round(x)));
  return `about ${f(life.h)} run-hours (${f(life.lo)} to ${f(life.hi)}), ${life.basis === "own trend" ? "from its own wear trend" : "typical for pumps in this condition"}`;
}

function SensorMark({ x, y, fresh, onEnter, onLeave }: { x: number; y: number; fresh: boolean; onEnter: (e: React.MouseEvent) => void; onLeave: () => void }) {
  return (
    <g onMouseMove={onEnter} onMouseLeave={onLeave} style={{ cursor: "help" }}>
      <rect x={x - 7} y={y - 7} width="14" height="14" rx="4" fill={fresh ? "var(--surface)" : "url(#hatch)"} stroke={fresh ? "var(--brand)" : "var(--unk)"} strokeWidth="2" strokeDasharray={fresh ? undefined : "3 2"} />
      {fresh ? <circle cx={x} cy={y} r="2.4" fill="var(--brand)" /> : <text x={x} y={y + 3.4} textAnchor="middle" style={{ fontSize: 9, fontWeight: 800, fill: "var(--ink-2)" }}>?</text>}
    </g>
  );
}

function QMark({ q, x, y, show, hide }: { q: any; x: number; y: number; show: (e: React.MouseEvent, n: React.ReactNode) => void; hide: () => void }) {
  const c = q.status === "ok" ? "var(--good)" : q.status === "watch" ? "var(--warn)" : q.status === "verify" ? "var(--crit)" : "var(--unk)";
  return (
    <g onMouseMove={(e) => show(e, <><b>Water quality · {q.name}</b><br />{q.fresh ? <>Turbidity {n1(q.turbidity_ntu, 2)} NTU · chlorine {n1(q.chlorine_mgl, 2)} mg/L<br />pH {n1(q.ph, 2)} · TDS {n1(q.tds_mgl, 0)} mg/L<br />{q.status === "verify" ? "Outside reference range: FTK verification required" : q.status === "watch" ? "Above the acceptable limit, within permissible" : "Within IS 10500 reference range"}<br /><i>Screening only: cannot detect bacteria or chemicals.</i></> : "No recent telemetry"}</>)} onMouseLeave={hide} style={{ cursor: "help" }}>
      <circle cx={x} cy={y} r="11" fill="var(--surface)" stroke={c} strokeWidth="2.6" className={q.status === "verify" ? "pulse" : ""} />
      <path d={`M${x - 2.4} ${y - 6} h4.8 M${x - 1.6} ${y - 6} v3.6 l-3.4 5.6 a1.6 1.6 0 0 0 1.4 2.4 h7.2 a1.6 1.6 0 0 0 1.4 -2.4 l-3.4 -5.6 v-3.6`} fill="none" stroke={c} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </g>
  );
}

export function TwinLegend() {
  return (
    <div className="legend">
      <span><i style={{ background: "var(--flow)", borderRadius: "50%" }} />Receiving water</span>
      <span><i style={{ background: "var(--low)", borderRadius: "50%" }} />Low pressure</span>
      <span><i style={{ background: "var(--surface)", border: "2.5px solid var(--dry)", borderRadius: "50%" }} />No water</span>
      <span><i className="ring" />Unknown (no telemetry)</span>
      <span><i style={{ background: "var(--idle)", borderRadius: "50%" }} />Scheduled off</span>
      <span><i style={{ background: "transparent", border: "1.5px solid var(--brand)", borderRadius: "50%" }} />Metered home</span>
      <span><i style={{ background: "#f97316", borderRadius: "50%" }} />Citizen report</span>
      <span><i style={{ background: "transparent", border: "2px solid #c026d3", borderRadius: 3 }} />Real hardware node</span>
      <span><i style={{ background: "var(--surface)", border: "2px solid #7c5cf0", borderRadius: 3 }} />School / anganwadi / health centre</span>
    </div>
  );
}

import { useEffect, useMemo, useRef, useState } from "react";

// Small hand-rolled SVG charts. Rules followed: one y-axis, thin marks (2 px lines, ~10% area wash),
// solid hairline grid, legend for 2+ series, text in ink tokens (never the series colour), hover tooltip.

export type Series = { name: string; color: string; pts: [number, number | null][]; dashed?: boolean; minor?: boolean }; // minor: thinner, lighter context line

function useWidth() {
  const ref = useRef<HTMLDivElement>(null);
  const [w, setW] = useState(480);
  useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver((e) => setW(Math.max(220, e[0].contentRect.width)));
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);
  return [ref, w] as const;
}

function niceMax(v: number) {
  if (v <= 0) return 1;
  const p = Math.pow(10, Math.floor(Math.log10(v)));
  const f = v / p;
  return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10) * p;
}

export function LineChart({ series, height = 190, yMin, yMax, xFmt = (x) => String(x), yFmt = (y) => String(Math.round(y * 100) / 100), unit = "", area = true, refLines = [], empty = "No data yet" }: {
  series: Series[]; height?: number; yMin?: number; yMax?: number; xFmt?: (x: number) => string; yFmt?: (y: number) => string;
  unit?: string; area?: boolean; refLines?: { y: number; label: string; color?: string }[]; empty?: string;
}) {
  const [ref, w] = useWidth();
  const [hover, setHover] = useState<number | null>(null);
  const m = { l: 40, r: 14, t: 10, b: 22 };
  const live = series.filter((s) => s.pts.length > 1);
  const calc = useMemo(() => {
    const xs = live.flatMap((s) => s.pts.map((p) => p[0]));
    const ys = live.flatMap((s) => s.pts.map((p) => p[1]).filter((v): v is number => v !== null)).concat(refLines.map((r) => r.y));
    if (!xs.length || !ys.length) return null;
    const x0 = Math.min(...xs), x1 = Math.max(...xs);
    const lo = yMin ?? Math.min(0, Math.min(...ys));
    const hi = yMax ?? niceMax(Math.max(...ys) * 1.05);
    const sx = (x: number) => m.l + ((x - x0) / Math.max(1e-9, x1 - x0)) * (w - m.l - m.r);
    const sy = (y: number) => m.t + (1 - (y - lo) / Math.max(1e-9, hi - lo)) * (height - m.t - m.b);
    return { x0, x1, lo, hi, sx, sy };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [series, w, height, yMin, yMax]);

  if (!calc) return <div className="chart" ref={ref}><div className="empty" style={{ height, padding: 0, display: "grid", placeItems: "center" }}>{empty}</div></div>;
  const { x0, x1, lo, hi, sx, sy } = calc;
  // round tick values (0, 25, 50 ...), never 22.5 or 67.5
  const raw = (hi - lo) / 4, mag = Math.pow(10, Math.floor(Math.log10(raw || 1))), f = raw / mag;
  const step = (f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10) * mag;
  const ticks: number[] = [];
  for (let t = Math.ceil(lo / step - 1e-9) * step; t <= hi + 1e-9; t += step) ticks.push(t);
  // x positions across all series (series may cover different ranges, e.g. measured + forecast)
  const base: [number, number | null][] = Array.from(new Set(live.flatMap((s) => s.pts.map((p) => p[0])))).sort((p, q) => p - q).map((x) => [x, null]);
  const xt = base.length <= 6 ? base.map((p) => p[0]) : [0, 0.25, 0.5, 0.75, 1].map((f) => Math.round(x0 + f * (x1 - x0)));
  const path = (pts: [number, number | null][]) => {
    let d = "", pen = false;
    for (const [x, y] of pts) {
      if (y === null) { pen = false; continue; }
      d += `${pen ? "L" : "M"}${sx(x).toFixed(1)} ${sy(y).toFixed(1)} `;
      pen = true;
    }
    return d;
  };
  const onMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    const x = x0 + ((e.clientX - r.left - m.l) / (w - m.l - m.r)) * (x1 - x0);
    let best = 0, bd = Infinity;
    base.forEach((p, i) => { const d = Math.abs(p[0] - x); if (d < bd) { bd = d; best = i; } });
    setHover(best);
  };
  const hx = hover !== null && base[hover] ? base[hover][0] : null;

  return (
    <div className="chart" ref={ref}>
      {live.length > 1 && (
        <div className="legend" style={{ marginBottom: 6 }}>
          {live.map((s) => <span key={s.name}><i style={{ background: s.color, height: 3, width: 14, borderRadius: 2 }} />{s.name}</span>)}
        </div>
      )}
      <svg height={height} viewBox={`0 0 ${w} ${height}`} onMouseMove={onMove} onMouseLeave={() => setHover(null)}>
        {ticks.map((t, i) => (
          <g key={i}>
            <line className="gridl" x1={m.l} x2={w - m.r} y1={sy(t)} y2={sy(t)} />
            <text className="axis" x={m.l - 7} y={sy(t) + 3.5} textAnchor="end">{yFmt(t)}</text>
          </g>
        ))}
        {xt.map((x, i) => <text key={i} className="axis" x={sx(x)} y={height - 5} textAnchor={i === 0 ? "start" : i === xt.length - 1 ? "end" : "middle"}>{xFmt(x)}</text>)}
        {refLines.map((r) => (
          <g key={r.label}>
            <line x1={m.l} x2={w - m.r} y1={sy(r.y)} y2={sy(r.y)} stroke={r.color || "var(--axis)"} strokeWidth="1.2" strokeDasharray="5 4" />
            <text className="axis" x={w - m.r} y={sy(r.y) - 4} textAnchor="end" style={{ fill: "var(--ink-2)", fontWeight: 650 }}>{r.label}</text>
          </g>
        ))}
        {area && live.length === 1 && (() => {
          const pts = live[0].pts.filter((p) => p[1] !== null) as [number, number][];
          return <path d={`${path(pts)}L${sx(pts[pts.length - 1][0]).toFixed(1)} ${sy(lo)} L${sx(pts[0][0]).toFixed(1)} ${sy(lo)} Z`} fill={live[0].color} opacity="0.12" />;
        })()}
        {live.map((s) => <path key={s.name} d={path(s.pts)} fill="none" stroke={s.color} strokeWidth={s.minor ? 1.4 : 2.4} opacity={s.minor ? 0.5 : 1} strokeLinejoin="round" strokeLinecap="round" strokeDasharray={s.dashed ? "6 5" : undefined} />)}
        {live.map((s) => {
          const last = [...s.pts].reverse().find((p) => p[1] !== null);
          return last ? <circle key={s.name} cx={sx(last[0])} cy={sy(last[1] as number)} r="4" fill={s.color} stroke="var(--surface)" strokeWidth="2" /> : null;
        })}
        {hx !== null && (
          <g>
            <line x1={sx(hx)} x2={sx(hx)} y1={m.t} y2={height - m.b} stroke="var(--axis)" strokeWidth="1" />
            {live.map((s) => { const p = s.pts.find((q) => q[0] === hx); return p && p[1] !== null ? <circle key={s.name} cx={sx(hx)} cy={sy(p[1])} r="4.5" fill={s.color} stroke="var(--surface)" strokeWidth="2" /> : null; })}
          </g>
        )}
      </svg>
      {hx !== null && (
        <div className="ctip" style={{ left: clampPx(sx(hx), 70, w - 70), top: m.t + 8 }}>
          <div className="muted xs" style={{ marginBottom: 3 }}>{xFmt(hx)}</div>
          {live.map((s) => { const p = s.pts.find((q) => q[0] === hx); return p && p[1] !== null ? <div className="k" key={s.name}><i style={{ background: s.color }} />{s.name}<b>{`${yFmt(p[1])}${unit}`}</b></div> : null; })}
        </div>
      )}
    </div>
  );
}
const clampPx = (v: number, a: number, b: number) => Math.max(a, Math.min(b, v));

export function Sparkline({ pts, color = "var(--s1)", height = 34, min, max }: { pts: number[]; color?: string; height?: number; min?: number; max?: number }) {
  const [ref, w] = useWidth();
  if (pts.length < 2) return <div ref={ref} style={{ height }} />;
  const lo = min ?? Math.min(...pts), hi = max ?? Math.max(...pts);
  const sx = (i: number) => 2 + (i / (pts.length - 1)) * (w - 8);
  const sy = (v: number) => 3 + (1 - (v - lo) / Math.max(1e-9, hi - lo)) * (height - 6);
  const d = pts.map((v, i) => `${i ? "L" : "M"}${sx(i).toFixed(1)} ${sy(v).toFixed(1)}`).join(" ");
  return (
    <div ref={ref} style={{ height }}>
      <svg width={w} height={height} viewBox={`0 0 ${w} ${height}`} aria-hidden>
        <path d={`${d} L${sx(pts.length - 1)} ${height} L${sx(0)} ${height} Z`} fill={color} opacity="0.1" />
        <path d={d} fill="none" stroke={color} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
        <circle cx={sx(pts.length - 1)} cy={sy(pts[pts.length - 1])} r="3.5" fill={color} stroke="var(--surface)" strokeWidth="2" />
      </svg>
    </div>
  );
}

/** Horizontal bars for one measure across categories: one colour, value at the bar tip. */
export function BarList({ items, fmt = (v) => String(v), color = "var(--s1)", max }: { items: { label: string; value: number; hint?: string }[]; fmt?: (v: number) => string; color?: string; max?: number }) {
  const top = max ?? Math.max(1, ...items.map((i) => i.value));
  if (!items.length) return <div className="empty" style={{ padding: 18 }}>Nothing recorded yet</div>;
  return (
    <div className="barlist">
      {items.map((it) => (
        <div className="r" key={it.label} title={it.hint || `${it.label}: ${fmt(it.value)}`}>
          <span className="ellipsis ink2">{it.label}</span>
          <div className="trk"><i style={{ width: `${(it.value / top) * 100}%`, background: color }} /></div>
          <b className="num">{fmt(it.value)}</b>
        </div>
      ))}
    </div>
  );
}

/** Vertical columns over an ordered x (days). Thin, rounded data-end, 2px gaps. */
export function Columns({ data, height = 120, color = "var(--s1)", fmt = (v) => String(v), xFmt = (s) => s }: { data: { x: string; y: number; live?: boolean }[]; height?: number; color?: string; fmt?: (v: number) => string; xFmt?: (s: string) => string }) {
  const [ref, w] = useWidth();
  const [hover, setHover] = useState<number | null>(null);
  const top = niceMax(Math.max(1, ...data.map((d) => d.y)));
  const m = { l: 26, b: 18, t: 6 };
  const bw = Math.min(24, Math.max(3, (w - m.l) / Math.max(1, data.length) - 2));
  const sx = (i: number) => m.l + (i + 0.5) * ((w - m.l) / Math.max(1, data.length));
  const sy = (v: number) => m.t + (1 - v / top) * (height - m.t - m.b);
  return (
    <div className="chart" ref={ref}>
      <svg height={height} viewBox={`0 0 ${w} ${height}`} onMouseLeave={() => setHover(null)}>
        {[0, 0.5, 1].map((f) => <g key={f}><line className="gridl" x1={m.l} x2={w} y1={sy(top * f)} y2={sy(top * f)} /><text className="axis" x={m.l - 6} y={sy(top * f) + 3.5} textAnchor="end">{fmt(top * f)}</text></g>)}
        {data.map((d, i) => (
          <g key={d.x} onMouseEnter={() => setHover(i)}>
            <rect x={sx(i) - bw / 2 - 1} y={m.t} width={bw + 2} height={height - m.t - m.b} fill="transparent" />
            {d.y > 0 && <path d={`M${sx(i) - bw / 2} ${sy(0)} V${sy(d.y) + Math.min(4, bw / 2)} Q${sx(i) - bw / 2} ${sy(d.y)} ${sx(i) - bw / 2 + Math.min(4, bw / 2)} ${sy(d.y)} H${sx(i) + bw / 2 - Math.min(4, bw / 2)} Q${sx(i) + bw / 2} ${sy(d.y)} ${sx(i) + bw / 2} ${sy(d.y) + Math.min(4, bw / 2)} V${sy(0)} Z`} fill={color} opacity={hover === null || hover === i ? 1 : 0.45} />}
          </g>
        ))}
        {[0, Math.floor((data.length - 1) / 2), data.length - 1].filter((v, i, a) => a.indexOf(v) === i && data[v]).map((i) => <text key={i} className="axis" x={sx(i)} y={height - 4} textAnchor="middle">{xFmt(data[i].x)}</text>)}
      </svg>
      {hover !== null && data[hover] && <div className="ctip" style={{ left: clampPx(sx(hover), 50, w - 50), top: sy(data[hover].y) }}><span className="muted xs">{xFmt(data[hover].x)}</span> <b>{fmt(data[hover].y)}</b></div>}
    </div>
  );
}

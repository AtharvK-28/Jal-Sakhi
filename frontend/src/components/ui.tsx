import { useEffect, useId, useState } from "react";
import { createPortal } from "react-dom";
import { AlertTriangle, CheckCircle2, CircleHelp, Droplets, Gauge, Moon, X } from "lucide-react";
import { INC_STATUS, ORIGIN, SUPPLY, clamp, scoreTone } from "../lib/format";

export function Drop({ className = "drop" }: { className?: string }) {
  const id = useId();
  return (
    <svg className={className} viewBox="0 0 32 32" aria-hidden>
      <defs>
        <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#67e8f9" /><stop offset="1" stopColor="#0a6fb8" />
        </linearGradient>
      </defs>
      <path d="M16 2c5 7 10 12 10 18a10 10 0 0 1-20 0c0-6 5-11 10-18z" fill={`url(#${id})`} />
      <path d="M11 20a5.4 5.4 0 0 0 4 5" stroke="#fff" strokeWidth="2" strokeLinecap="round" fill="none" opacity=".8" />
    </svg>
  );
}

/** Three drifting wave layers; sits at the bottom of a coloured hero. */
export function Waves({ fill = "var(--bg)" }: { fill?: string }) {
  const d = "M0 30 Q 150 0 300 30 T 600 30 T 900 30 T 1200 30 T 1500 30 T 1800 30 T 2100 30 T 2400 30 V 60 H 0 Z";
  return (
    <div className="waves" aria-hidden>
      <svg className="w1" viewBox="0 0 2400 60" preserveAspectRatio="none"><path d={d} fill={fill} /></svg>
      <svg className="w2" viewBox="0 0 2400 60" preserveAspectRatio="none"><path d={d} fill={fill} transform="translate(-110 6)" /></svg>
      <svg className="w3" viewBox="0 0 2400 60" preserveAspectRatio="none"><path d={d} fill={fill} transform="translate(-60 14)" /></svg>
    </div>
  );
}

/** Circular gauge filled with moving water to the given percentage. The fill level IS the value. */
export function LiquidGauge({ value, size = 132, label, tone }: { value: number | null | undefined; size?: number; label?: string; tone?: { c1: string; c2: string } }) {
  const id = useId();
  const t = tone || scoreTone(value);
  const pct = clamp(value ?? 0, 0, 100);
  const r = size / 2;
  const amp = size * 0.035;
  const w = size;
  const wave = `M0 ${amp} Q ${w / 4} ${-amp} ${w / 2} ${amp} T ${w} ${amp} T ${1.5 * w} ${amp} T ${2 * w} ${amp} V ${size + amp} H 0 Z`;
  const y = (size - 8) * (1 - pct / 100) + 4 - amp;
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img" aria-label={`${label || "value"} ${value ?? "no data"}`}>
      <defs>
        <clipPath id={id}><circle cx={r} cy={r} r={r - 5} /></clipPath>
        <linearGradient id={`${id}g`} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor={t.c1} /><stop offset="1" stopColor={t.c2} /></linearGradient>
      </defs>
      <circle cx={r} cy={r} r={r - 2} fill="var(--surface-2)" stroke="var(--line-2)" strokeWidth="2" />
      <g clipPath={`url(#${id})`}>
        <g style={{ transform: `translateY(${y}px)`, transition: "transform 1.2s cubic-bezier(.3,.8,.3,1)" }}>
          <path className="gauge-wave b" style={{ transformBox: "fill-box" }} d={wave} fill={t.c1} />
          <path className="gauge-wave" style={{ transformBox: "fill-box" }} d={wave} fill={`url(#${id}g)`} />
        </g>
      </g>
      <text x={r} y={r + size * 0.07} textAnchor="middle" fontSize={size * 0.27} fontWeight="760" fill="var(--ink)"
        stroke="var(--surface)" strokeWidth={size * 0.035} paintOrder="stroke" style={{ letterSpacing: "-0.03em", fontFamily: "var(--font)" }}>
        {value === null || value === undefined ? "–" : Math.round(value)}
      </text>
      {label && (
        <text x={r} y={r + size * 0.24} textAnchor="middle" fontSize={size * 0.085} fontWeight="650" fill="var(--ink-2)"
          stroke="var(--surface)" strokeWidth={size * 0.025} paintOrder="stroke" style={{ fontFamily: "var(--font)" }}>{label}</text>
      )}
    </svg>
  );
}

export function Kpi({ icon, label, value, unit, sub, tone, children }: { icon?: React.ReactNode; label: string; value: React.ReactNode; unit?: string; sub?: React.ReactNode; tone?: "good" | "warn" | "crit" | "mute"; children?: React.ReactNode }) {
  return (
    <div className={`card kpi ${tone ? `t-${tone}` : ""}`}>
      <div className="lab">{icon}{label}</div>
      <div className="val">{value}{unit && value !== "–" && <small>{unit}</small>}</div>
      {sub && <div className="sub">{sub}</div>}
      {children}
    </div>
  );
}

export function SevPill({ sev }: { sev: string }) {
  return <span className={`pill ${sev}`}><AlertTriangle />{sev}</span>;
}
export function StatusPill({ status }: { status: string }) {
  const cls = status === "closed" ? "good" : status === "open" ? "high" : status === "resolved_pending_verification" ? "info" : "medium";
  return <span className={`pill quiet ${cls}`}><span className="d" />{INC_STATUS[status] || status}</span>;
}
export function OriginPill({ origin }: { origin: string }) {
  const o = ORIGIN[origin] || ORIGIN.sensor;
  return <span className={`pill quiet ${o.cls === "ai" ? "o-ai" : ""}`}>{o.label}</span>;
}
export function SupplyPill({ s }: { s: string }) {
  const Icon = s === "ok" ? Droplets : s === "low" ? Gauge : s === "dry" ? AlertTriangle : s === "idle" ? Moon : CircleHelp;
  return <span className={`pill s-${s}`}><Icon />{SUPPLY[s]?.label || s}</span>;
}

export function Loader({ text = "Loading" }: { text?: string }) {
  return <div className="loader"><Drop className="drop" /><span>{text}…</span></div>;
}
export function Empty({ icon, children }: { icon?: React.ReactNode; children: React.ReactNode }) {
  return <div className="empty">{icon || <CheckCircle2 />}<div>{children}</div></div>;
}

export function Drawer({ title, sub, onClose, children, footer, wide }: { title: React.ReactNode; sub?: React.ReactNode; onClose: () => void; children: React.ReactNode; footer?: React.ReactNode; wide?: boolean }) {
  useEffect(() => {
    const h = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose]);
  return createPortal(
    <>
      <div className="scrim" onClick={onClose} />
      <aside className="drawer" style={wide ? { width: "min(820px,100vw)" } : undefined} role="dialog" aria-modal>
        <div className="drawer-h">
          <div className="row between" style={{ alignItems: "flex-start" }}>
            <div className="grow"><h2>{title}</h2>{sub && <div className="muted sm" style={{ marginTop: 4 }}>{sub}</div>}</div>
            <button className="btn ghost icon" onClick={onClose} aria-label="Close"><X /></button>
          </div>
        </div>
        <div className="drawer-b">{children}</div>
        {footer && <div className="drawer-f">{footer}</div>}
      </aside>
    </>, document.body);
}

export function Modal({ onClose, children }: { onClose: () => void; children: React.ReactNode }) {
  return createPortal(<><div className="scrim" style={{ zIndex: 90 }} onClick={onClose} /><div className="modal" role="dialog" aria-modal>{children}</div></>, document.body);
}

// ---- toast (one global slot) -------------------------------------------------
let pushToast: (t: { text: string; err?: boolean }) => void = () => {};
export const toast = (text: string, err = false) => pushToast({ text, err });
export function ToastHost() {
  const [t, setT] = useState<{ text: string; err?: boolean } | null>(null);
  useEffect(() => {
    pushToast = (x) => setT(x);
    return () => { pushToast = () => {}; };
  }, []);
  useEffect(() => {
    if (!t) return;
    const id = setTimeout(() => setT(null), t.err ? 5200 : 3400);
    return () => clearTimeout(id);
  }, [t]);
  if (!t) return null;
  return createPortal(<div className={`toast ${t.err ? "err" : ""}`}>{t.err ? <AlertTriangle /> : <CheckCircle2 />}{t.text}</div>, document.body);
}

/** Proportional bar of household supply states with a labelled legend (never colour alone). */
export function StatusBar({ counts, total }: { counts: Record<string, number>; total: number }) {
  const keys = ["ok", "low", "dry", "unknown", "idle"].filter((k) => counts?.[k]);
  return (
    <div>
      <div className="statusbar" role="img" aria-label="Household supply status distribution">
        {keys.map((k) => <i key={k} style={{ flex: counts[k], background: k === "unknown" ? `repeating-linear-gradient(45deg, var(--unk) 0 4px, var(--mute-bg) 4px 8px)` : SUPPLY[k].color }} title={`${SUPPLY[k].label}: ${counts[k]}`} />)}
      </div>
      <div className="legend" style={{ marginTop: 8 }}>
        {keys.map((k) => <span key={k}><i style={{ background: SUPPLY[k].color }} className={k === "unknown" ? "ring" : ""} /><b className="num">{counts[k]}</b> {SUPPLY[k].label.toLowerCase()}</span>)}
        {!keys.length && <span className="muted">No households</span>}
        <span className="muted" style={{ marginLeft: "auto" }}>of {total}</span>
      </div>
    </div>
  );
}

export function ripple(e: React.MouseEvent<HTMLElement>) {
  const r = e.currentTarget.getBoundingClientRect();
  e.currentTarget.style.setProperty("--rx", `${((e.clientX - r.left) / r.width) * 100}%`);
  e.currentTarget.style.setProperty("--ry", `${((e.clientY - r.top) / r.height) * 100}%`);
}

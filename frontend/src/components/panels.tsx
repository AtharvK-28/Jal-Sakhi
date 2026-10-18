import { useNavigate } from "react-router-dom";
import { AlertTriangle, Bell, CheckCircle2, ChevronRight, FlaskConical, Info, MessageSquareText, Siren, SlidersHorizontal, TrendingUp, Users } from "lucide-react";
import { Empty, OriginPill, SevPill, StatusPill } from "./ui";
import { hhmm } from "../lib/format";
import { useLive } from "../lib/live";

/** Compact, priority-ordered incident list used on overview pages. */
export function IncidentQueue({ items, limit = 6, showVillage, names }: { items: any[]; limit?: number; showVillage?: boolean; names?: Record<string, string> }) {
  const nav = useNavigate();
  if (!items.length) return <Empty>No open incidents. Service is running as scheduled.</Empty>;
  return (
    <div className="stack" style={{ gap: 8 }}>
      {items.slice(0, limit).map((i) => (
        <button key={i.id} className="scn" style={{ gridTemplateColumns: "46px 1fr auto", alignItems: "start" }} onClick={() => nav(`/app/incidents/${i.id}`)}>
          <span className="ic" style={{ width: 46, height: 46, flexDirection: "column", background: "var(--surface-2)", color: "var(--ink)", fontWeight: 760, fontSize: 15, lineHeight: 1 }} title="Maintenance priority score (0-100)">
            {Math.round(i.priority)}<small style={{ fontSize: 8.5, fontWeight: 700, color: "var(--muted)", letterSpacing: ".06em", display: "block" }}>PRIORITY</small>
          </span>
          <span>
            <b style={{ lineHeight: 1.35 }}>{i.title}</b>
            <span className="row wrap" style={{ gap: 6, marginTop: 5 }}>
              <SevPill sev={i.severity} /><StatusPill status={i.status} /><OriginPill origin={i.origin} />
              {i.affected_count > 0 && <span className="pill quiet"><Users />{i.affected_count} homes</span>}
              {i.report_count > 0 && <span className="pill quiet"><MessageSquareText />{i.report_count} reports</span>}
              {showVillage && <span className="pill quiet" style={{ color: "var(--ink)" }}>{names?.[i.village_id] || i.village_id}</span>}
              <span className="muted xs">{i.id} · since {hhmm(i.first_seen)}</span>
            </span>
          </span>
          <ChevronRight size={16} className="muted" />
        </button>
      ))}
      {items.length > limit && <button className="btn soft sm" onClick={() => nav("/app/incidents")}>View all {items.length} incidents</button>}
    </div>
  );
}

/** The single incident to act on first, or a plain all-clear. Sits under the command-centre hero. */
export function AttentionStrip({ items, names }: { items: any[]; names?: Record<string, string> }) {
  const nav = useNavigate();
  const { clock } = useLive();
  const top = [...items].sort((a, b) => b.priority - a.priority)[0];
  if (!top) return (
    <div className="attn ok"><span className="attn-k"><CheckCircle2 />All clear</span>
      <span className="attn-t"><b>Nothing needs attention right now</b><span className="sm ink2">Every scheme in view is supplying as scheduled.</span></span></div>
  );
  const open = top.status === "open";
  const due = open ? top.sla_ack_due : top.sla_resolve_due;
  const where = names?.[top.village_id];
  const late = !!(clock?.iso && due && clock.iso.slice(0, 19) > due.slice(0, 19));  // both are simulation time
  return (
    <button className={`attn sev-${top.severity}`} onClick={() => nav(`/app/incidents/${top.id}`)}>
      <span className="attn-k"><Siren />Needs attention now</span>
      <span className="attn-t"><b>{top.title}</b>
        <span className="sm ink2">{where ? `${where} · ` : ""}{top.affected_count} home{top.affected_count === 1 ? "" : "s"} affected · {top.label} · {late ? <b style={{ color: "var(--crit)" }}>{open ? "acknowledgement" : "resolution"} overdue since {hhmm(due)}</b> : <>{open ? "acknowledge" : "resolve"} by {hhmm(due)}</>}{items.length > 1 ? ` · ${items.length - 1} more in the queue` : ""}</span></span>
      <SevPill sev={top.severity} />
      <span className="btn sm">Open<ChevronRight /></span>
    </button>
  );
}

const FEED_ICON: Record<string, any> = { incident: AlertTriangle, complaint: MessageSquareText, resolved: CheckCircle2, escalation: TrendingUp, demo: SlidersHorizontal, transient: Info, system: Bell, quality: FlaskConical };

export function Feed({ items, limit = 14 }: { items: any[]; limit?: number }) {
  if (!items?.length) return <Empty icon={<Bell />}>Nothing yet. Events appear here as they happen.</Empty>;
  return (
    <div className="feed">
      {items.slice(0, limit).map((f) => {
        const Icon = FEED_ICON[f.kind] || Info;
        return (
          <div key={f.id} className={`it ${f.level}`}>
            <span className="tm">{f.ts}</span>
            <span className="ic"><Icon /></span>
            <span className={f.level === "muted" ? "muted" : ""}>{f.text}</span>
          </div>
        );
      })}
    </div>
  );
}

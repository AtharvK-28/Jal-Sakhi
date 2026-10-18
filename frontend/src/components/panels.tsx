import { useNavigate } from "react-router-dom";
import { AlertTriangle, Bell, CheckCircle2, ChevronRight, FlaskConical, Info, MessageSquareText, SlidersHorizontal, TrendingUp, Users } from "lucide-react";
import { Empty, OriginPill, SevPill, StatusPill } from "./ui";
import { hhmm } from "../lib/format";

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
              {i.affected_count > 0 && <span className="pill"><Users />{i.affected_count} homes</span>}
              {i.report_count > 0 && <span className="pill high"><MessageSquareText />{i.report_count}</span>}
              {showVillage && <span className="pill info">{names?.[i.village_id] || i.village_id}</span>}
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

import { useEffect, useState } from "react";
import { AlertTriangle, BadgeCheck, Clock, Droplets, Scale, ShieldAlert, Users } from "lucide-react";
import { api } from "../lib/api";
import { useLive, usePoll } from "../lib/live";
import { Kpi, Loader, toast } from "../components/ui";

/** What IMIS would report for each village against what is observed: every connection is counted as served
 *  there, and a certified village stays certified, while the households tell a different story. */
export function Reconcile() {
  const { scope } = useLive();
  const [minutes, setMinutes] = useState(30);
  const [ask, setAsk] = useState(30);
  useEffect(() => { const id = setTimeout(() => setAsk(minutes), 300); return () => clearTimeout(id); }, [minutes]);
  const { data: d, error } = usePoll<any>(`/api/reconcile?level=${scope.level}&id=${scope.id}&minutes=${ask}`, 20000, [ask]);
  const [open, setOpen] = useState<string | null>(null);
  const [detail, setDetail] = useState<any>(null);
  useEffect(() => { if (!open) { setDetail(null); return; } api(`/api/villages/${open}/equity`).then(setDetail).catch((e) => toast(e.message, true)); }, [open]);
  if (error) return <div className="page"><p className="muted">{error}</p></div>;
  if (!d) return <div className="page"><Loader /></div>;
  const vs: any[] = d.villages;
  const fhtc = vs.reduce((a, v) => a + v.households, 0), rel = vs.reduce((a, v) => a + v.observed.reliable, 0);
  const atRisk = vs.filter((v) => v.certification_at_risk);
  const left = vs.reduce((a, v) => a + v.chronic, 0), dry = vs.reduce((a, v) => a + v.dry, 0);

  return (
    <div className="page">
      <div className="page-h">
        <div><h1>Reported vs observed</h1><p>IMIS counts a connection once it is made, and a Har Ghar Jal village stays certified. Here every village's reported position stands next to what its households actually received over the last 30 days, and the homes left out are named for the people who can fix it.</p></div>
      </div>

      <div className="grid kpis" style={{ marginBottom: 16 }}>
        <Kpi icon={<Scale />} label="Reported connections" value={fhtc} sub="as IMIS would carry them" />
        <Kpi icon={<BadgeCheck />} label="Reliably served" value={rel} unit={`/ ${fhtc}`} tone={rel / fhtc < 0.85 ? "crit" : undefined} sub={d.rules.reliable} />
        <Kpi icon={<ShieldAlert />} label="Certification at risk" value={atRisk.length} tone={atRisk.length ? "crit" : undefined} sub={atRisk.length ? atRisk.map((v) => v.village).join(", ") : "every certified village holds"} />
        <Kpi icon={<Users />} label="Homes left out" value={left} sub={`${dry} with no water for 14 days`} />
      </div>

      <div className="grid g-main">
        <div className="card tbl-wrap" style={{ alignSelf: "start" }}>
          <div className="card-h" style={{ paddingBottom: 10 }}><h3><Scale />Village by village</h3><span className="muted xs">click a village for its homes</span></div>
          <table className="tbl">
            <thead><tr><th>Village</th><th>Reported</th><th>Observed</th><th>Gap</th><th>Left out</th><th>No water 14 days</th></tr></thead>
            <tbody>{[...vs].sort((a, b) => b.gap - a.gap).map((v) => (
              <tr key={v.village_id} className="click" onClick={() => setOpen(open === v.village_id ? null : v.village_id)} style={open === v.village_id ? { background: "var(--surface-2)" } : undefined}>
                <td><b>{v.village}</b>{v.certification_at_risk && <div><span className="pill critical" style={{ marginTop: 4 }}><ShieldAlert />certification at risk</span></div>}</td>
                <td className="sm">{v.reported.fhtc} connections<div className="xs muted">{v.reported.har_ghar_jal ? `Har Ghar Jal since ${v.reported.har_ghar_jal}` : "not certified"}</div></td>
                <td className="sm"><b className="num">{v.observed.reliable}</b> reliably served<div className="bar" style={{ marginTop: 4, height: 6 }}><i style={{ width: `${v.observed.reliable_pct}%` }} /></div></td>
                <td className="num"><b style={{ color: v.gap > v.households * 0.15 ? "var(--crit)" : undefined }}>{v.gap}</b></td>
                <td className="num">{v.chronic}</td>
                <td className="num">{v.dry ? <b style={{ color: "var(--crit)" }}>{v.dry}</b> : 0}</td>
              </tr>))}</tbody>
          </table>
          {detail && <LeftOut d={detail} />}
        </div>

        <div className="stack">
          <div className="card">
            <div className="card-h"><h3><Clock />The hours it costs</h3><span className="pill demo">your assumption</span></div>
            <div className="card-b stack" style={{ gap: 10 }}>
              <div><div className="row between sm"><span>Minutes fetching water on a day the tap fails</span><b className="num">{minutes} min</b></div>
                <input type="range" min={10} max={120} step={5} value={minutes} onChange={(e) => setMinutes(Number(e.target.value))} style={{ width: "100%" }} /></div>
              <div style={{ fontSize: 30, fontWeight: 780 }} className="num">{d.fetching.hours.toLocaleString("en-IN")} <small className="muted" style={{ fontSize: 14 }}>hours in 30 days</small></div>
              <div className="sm ink2">{d.fetching.household_days.toLocaleString("en-IN")} household-days without enough tap water, almost always made up by a woman or a girl carrying water from somewhere else.</div>
              {d.fetching.villages.map((v: any) => <div key={v.village_id} className="row between sm"><span>{v.village}</span><span className="num">{v.household_days} days · <b>{v.hours} h</b></span></div>)}
              <p className="xs muted">{d.fetching.assumption}</p>
            </div>
          </div>
          <div className="note"><AlertTriangle /><span>Observed figures come from household-level monitoring; the first 30 days are seeded simulated history, replaced by live observation day by day. Har Ghar Jal dates are DEMO placeholders.</span></div>
        </div>
      </div>
    </div>
  );
}

function LeftOut({ d }: { d: any }) {
  return (
    <div style={{ padding: "4px 18px 18px", borderTop: "1px solid var(--line)" }}>
      <div className="row between" style={{ margin: "12px 0 8px" }}><b>{d.village}: homes left out</b><span className="xs muted">{d.rules.chronic}</span></div>
      {d.chronic.length === 0 ? <p className="sm muted">None this week.</p> : (
        <div className="grid g2" style={{ gap: 8 }}>
          {d.chronic.map((h: any) => (
            <div key={h.id} className="row between sm" style={{ padding: "7px 10px", borderRadius: 10, background: "var(--surface-2)" }}>
              <span><b>{h.label}</b> · {h.lane}<div className="xs muted">position {h.position} · {h.members} people{h.metered ? " · metered" : ""}</div></span>
              <span className="num" style={{ textAlign: "right" }}><b style={{ color: "var(--crit)" }}>{h.days_failed}/{h.of}</b> days<div className="xs muted">{h.avg_lpcd} lpcd</div></span>
            </div>))}
        </div>)}
      {d.chronic_by_lane.length > 0 && <p className="xs muted" style={{ marginTop: 8 }}>By lane: {d.chronic_by_lane.map((l: any) => `${l.lane} ${l.n}`).join(" · ")}. Homes at the tail and up the slope fall short first: the investment planner prices the fix.</p>}
      {d.dry.length > 0 && <div className="note warn" style={{ marginTop: 10 }}><Droplets /><span><b>No water at all for 14 days:</b> {d.dry.map((h: any) => `${h.label} (${h.lane})`).join(", ")}. These homes are counted as served in the reported figure.</span></div>}
    </div>
  );
}

import { useState } from "react";
import { BadgeCheck, BarChart3, Check, ClipboardList, Clock, Download, FileCheck2, Hourglass, MessageSquareText, Radar, Send, Stamp, Timer, TrendingUp, Trophy } from "lucide-react";
import { api, download, getSession } from "../lib/api";
import { useLive, usePoll } from "../lib/live";
import { Kpi, Loader, toast } from "../components/ui";
import { BarList, Columns, LineChart } from "../components/charts";
import { CAT_LABEL, dayMon, n0, n1, scoreColor } from "../lib/format";

const TYPE_LABEL: Record<string, string> = {
  SUPPLY_INTERRUPTION: "Supply interruption", LOW_PRESSURE: "Low pressure", SUSPECTED_LEAK: "Suspected leak", ABNORMAL_PATTERN: "Abnormal pattern (AI)",
  QUALITY_VERIFY: "Quality verification", SENSOR_OFFLINE: "Sensor offline", PUMP_FAULT: "Pump failure", PUMP_RISK: "Pump risk (AI)",
  SHORTFALL_PREDICTED: "Shortfall forecast", SOURCE_STRESS: "Source stress", COMMUNITY_CLUSTER: "Community cluster", CITIZEN_REPORT: "Citizen report",
};

export function Analytics() {
  const { scope, village, setScope } = useLive();
  const { data: a } = usePoll<any>(`/api/analytics?level=${scope.level}&id=${scope.id}`, 6000);
  const vid = scope.level === "village" ? scope.id : village;
  const { data: draft, reload } = usePoll<any>(`/api/aankalan/${vid}`, 10000, [vid]);
  const [queued, setQueued] = useState(false);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  if (!a) return <div className="page"><Loader /></div>;
  const t = a.trend;
  const xf = (i: number) => dayMon(t[i]?.day);
  const last = t[t.length - 1] || {};
  const first7 = t.slice(-14, -7), last7 = t.slice(-7);
  const avg = (rows: any[], k: string) => (rows.length ? rows.reduce((s, r) => s + (r[k] || 0), 0) / rows.length : 0);
  const delta = avg(last7, "functional_pct") - avg(first7, "functional_pct");

  const queue = async () => {
    try { await api(`/api/aankalan/${vid}/submit`, { method: "POST" }); setQueued(true); toast("Draft queued for the Jal Seva Aankalan sandbox sync"); reload(); } catch (e: any) { toast(e.message, true); }
  };
  const endorse = async () => {
    setBusy(true);
    try { await api(`/api/aankalan/${vid}/endorse`, { body: { note } }); toast("Endorsement recorded. The assessment is open for 30 days of citizen feedback."); setNote(""); reload(); } catch (e: any) { toast(e.message, true); }
    setBusy(false);
  };
  const csv = async () => {
    try { toast(`Saved ${await download(`/api/villages/${vid}/service.csv`, "daily-service.csv")}`); } catch (e: any) { toast(e.message, true); }
  };
  const st = draft?.stage;
  const at = st ? ["draft", "feedback", "final"].indexOf(st.stage) : 0;  // 0 draft, 1 feedback open, 2 final
  const mayEndorse = getSession()?.user.role !== "operator";

  return (
    <div className="page">
      <div className="page-h"><div><h1>Analytics</h1><p>Thirty days of service delivery for the selected unit, the response record, and the measurements that tell you whether monitoring itself is working.</p></div>
        <div className="row wrap"><span className="pill demo">30-day history is seeded; live days are appended as the simulation runs</span>
          <button className="btn ghost sm" title="One row per day for this village: functionality, supply, incidents, energy, groundwater" onClick={csv}><Download />Daily record (CSV)</button></div></div>

      <div className="grid kpis" style={{ marginBottom: 16 }}>
        <Kpi icon={<BadgeCheck />} label="Functional taps, 7-day average" value={n1(avg(last7, "functional_pct"), 0)} unit="%" tone={delta < -2 ? "warn" : "good"} sub={`${delta >= 0 ? "+" : ""}${n1(delta)} points vs the week before`} />
        <Kpi icon={<TrendingUp />} label="Average supply, 7 days" value={n1(avg(last7, "avg_lpcd"), 0)} unit="lpcd" sub="JJM service level is 55" />
        <Kpi icon={<Clock />} label="Acknowledged within SLA" value={a.sla.ack_within_pct != null ? n0(a.sla.ack_within_pct) : "–"} unit="%" tone={a.sla.ack_within_pct != null && a.sla.ack_within_pct < 70 ? "warn" : undefined} sub={`${a.sla.ack_n} incident${a.sla.ack_n === 1 ? "" : "s"} this session`} />
        <Kpi icon={<Timer />} label="Median detection time" value={a.median_detection_delay_min != null ? n1(a.median_detection_delay_min, 0) : "–"} unit="min" sub="fault injected to incident raised (demo)" />
        <Kpi icon={<Radar />} label="Virtual sensing accuracy" value={a.estimator.agreement_pct != null ? n1(a.estimator.agreement_pct) : "–"} unit="%" tone="good" sub="inferred vs simulated truth" />
        <Kpi icon={<MessageSquareText />} label="Citizen pulse agrees" value={a.pulse.agreement_pct != null ? n0(a.pulse.agreement_pct) : "–"} unit="%" sub={`${a.pulse.responses} daily "did water come?" answers`} />
      </div>

      <div className="grid g2">
        <div className="card"><div className="card-h"><h3><TrendingUp />JJM functionality and its three tests</h3></div>
          <div className="card-b"><LineChart height={230} yMin={40} yMax={100} unit="%" yFmt={(y) => `${Math.round(y)}`} xFmt={xf} area={false}
            series={[{ name: "Functional (all three)", color: "var(--s1)", pts: t.map((r: any, i: number) => [i, r.functional_pct]) }, { name: "Regularity", color: "var(--s2)", pts: t.map((r: any, i: number) => [i, r.regularity_pct]) },
              { name: "Quantity (55 lpcd)", color: "var(--s3)", pts: t.map((r: any, i: number) => [i, r.quantity_pct]) }, { name: "Quality", color: "var(--s4)", pts: t.map((r: any, i: number) => [i, r.quality_pct]) }]}
            refLines={[{ y: 76, label: "national FA 2024: 76%" }]} />
            <p className="xs muted" style={{ marginTop: 6 }}>A tap is functional only when it passes all three: regular supply, adequate quantity and prescribed quality, the definition used in the national Functionality Assessment.</p></div></div>
        <div className="card"><div className="card-h"><h3><BarChart3 />Water supplied per person per day</h3></div>
          <div className="card-b"><LineChart height={230} yMin={0} yMax={90} unit=" lpcd" yFmt={(y) => `${Math.round(y)}`} xFmt={xf}
            series={[{ name: "Average lpcd", color: "var(--s1)", pts: t.map((r: any, i: number) => [i, r.avg_lpcd]) }]} refLines={[{ y: 55, label: "JJM norm 55 lpcd", color: "var(--good)" }]} />
            <p className="xs muted" style={{ marginTop: 6 }}>Latest day: {n1(last.avg_lpcd, 0)} lpcd · {n1(last.supply_hours)} supply hours{last.live ? " (live simulation day)" : ""}.</p></div></div>
      </div>

      <div className="grid g3" style={{ marginTop: 16 }}>
        <div className="card"><div className="card-h"><h3><ClipboardList />Incidents by type</h3><span className="muted xs">30 days + live</span></div>
          <div className="card-b"><BarList items={a.incidents_by_type.map((r: any) => ({ label: TYPE_LABEL[r.type] || r.type, value: r.n }))} /></div></div>
        <div className="card"><div className="card-h"><h3><Hourglass />Mean time to resolve</h3><span className="muted xs">hours</span></div>
          <div className="card-b"><BarList color="var(--s2)" fmt={(v) => `${n1(v)} h`} items={a.mttr_hours.map((r: any) => ({ label: TYPE_LABEL[r.type] || r.type, value: r.hours, hint: `${r.n} incidents` }))} /></div></div>
        <div className="card"><div className="card-h"><h3><MessageSquareText />Open reports by age</h3></div>
          <div className="card-b">
            <BarList color="var(--s3)" items={[["under_1h", "Under 1 hour"], ["1_to_4h", "1 to 4 hours"], ["4_to_24h", "4 to 24 hours"], ["over_24h", "Over 24 hours"]].map(([k, l]) => ({ label: l, value: a.complaint_ageing[k] }))} />
            <div className="upper muted" style={{ margin: "14px 0 8px" }}>Reports by category</div>
            <BarList color="var(--s3)" items={a.complaints_by_category.slice(0, 5).map((r: any) => ({ label: CAT_LABEL[r.category], value: r.n }))} />
          </div></div>
      </div>

      <div className="grid g2" style={{ marginTop: 16 }}>
        <div className="card"><div className="card-h"><h3><ClipboardList />Incidents and citizen reports per day</h3></div>
          <div className="card-b">
            <div className="upper muted" style={{ marginBottom: 4 }}>Incidents</div><Columns height={96} data={t.map((r: any) => ({ x: r.day, y: r.incidents }))} xFmt={dayMon} />
            <div className="upper muted" style={{ margin: "10px 0 4px" }}>Citizen reports</div><Columns height={96} color="var(--s2)" data={t.map((r: any) => ({ x: r.day, y: r.complaints }))} xFmt={dayMon} />
          </div></div>
        <div className="card"><div className="card-h"><h3><Trophy />Scheme ranking</h3><span className="muted xs">click to open a village</span></div>
          <div className="tbl-wrap"><table className="tbl">
            <thead><tr><th>#</th><th>Village</th><th>Service score</th><th>Functional</th><th>Open</th></tr></thead>
            <tbody>{a.ranking.map((v: any, i: number) => (
              <tr key={v.id} className="click" onClick={() => setScope({ level: "village", id: v.id })}>
                <td className="num muted">{i + 1}</td><td><b>{v.name}</b><div className="xs muted">{v.block} · {v.district} · {v.households} taps</div></td>
                <td style={{ minWidth: 150 }}><div className="row"><b className="num" style={{ width: 34 }}>{n0(v.score)}</b><div className="bar grow"><i style={{ width: `${v.score}%`, background: scoreColor(v.score) }} /></div></div></td>
                <td className="num">{v.functional_pct != null ? `${n0(v.functional_pct)}%` : "–"}</td><td className="num">{v.open}</td></tr>))}</tbody>
          </table></div>
          {a.recurring.length > 0 && <div className="card-b sm"><div className="upper muted" style={{ marginBottom: 5 }}>Recurring faults (same lane, same type)</div>{a.recurring.map((r: any) => <div key={r.branch + r.type} className="row between" style={{ padding: "3px 0" }}><span><span className="mono">{r.branch}</span> · {TYPE_LABEL[r.type] || r.type}</span><b className="num">{r.n}×</b></div>)}</div>}
        </div>
      </div>

      {draft && st && (
        <div className="card" style={{ marginTop: 16 }}>
          <div className="card-h"><h3><FileCheck2 />Jal Seva Aankalan: {draft.village}</h3>
            <div className="row wrap"><span className={`pill ${at === 0 ? "medium" : at === 1 ? "info" : "good"}`}>{draft.status}</span>
              {at === 0 && <button className="btn ghost sm" disabled={queued} onClick={queue}><Send />{queued ? "Draft queued for sync" : "Queue draft for sync"}</button>}</div></div>
          <div className="card-b">
            <p className="sm ink2" style={{ maxWidth: 920 }}>Jal Seva Aankalan is the Gram Panchayat's own assessment of its water service on five parameters. The Pani Samiti discusses it, the Gram Sabha endorses it, and it is then open to 30 days of citizen feedback. This draft is filled from continuous monitoring and the village's own registers, so the Gram Sabha reviews evidence instead of relying on recollection. Period: {draft.period}.</p>

            <div className="stage">
              {[["Draft from evidence", "filled automatically"], ["Gram Sabha endorsement", st.endorsed_on ? dayMon(st.endorsed_on) : "open meeting"],
                ["Citizen feedback", at === 1 ? `${st.days_left} days left` : "30 days"], ["Final", st.open_until && at > 0 ? dayMon(st.open_until) : "on the dashboard"]].map(([label, sub], i) => {
                const done = i <= at || at === 2;  // the step after the last finished one is the one being waited on
                return <div key={label} className={`s ${done ? "done" : i === at + 1 ? "cur" : ""}`}><i>{done ? <Check /> : i + 1}</i>{label}<small>{sub}</small></div>;
              })}
            </div>

            <div className="aank">
              {draft.sections.map((x: any) => (
                <div key={x.key}>
                  <div className="row between" style={{ alignItems: "flex-start", gap: 8 }}><b>{x.title}</b><span className="num" style={{ fontSize: 20, fontWeight: 750, color: scoreColor(x.score) }}>{x.score != null ? `${n0(x.score)}%` : "manual"}</span></div>
                  <p className="xs muted" style={{ margin: "3px 0 9px" }}>{x.question}</p>
                  {x.indicators.map((it: any) => <div key={it.label} className="row between xs" style={{ padding: "4px 0", borderTop: "1px solid var(--line)", alignItems: "flex-start", gap: 8 }}><span className="ink2">{it.label}</span><b className="num" style={{ textAlign: "right" }}>{it.value}</b></div>)}
                  {x.caveat && <p className="xs" style={{ marginTop: 7, color: "var(--serious)" }}>{x.caveat}</p>}
                </div>
              ))}
            </div>

            <div className="grid g2" style={{ marginTop: 14 }}>
              <div className="outcome">
                <div className="upper muted">Overall</div><b className="num" style={{ color: scoreColor(draft.overall) }}>{draft.overall != null ? `${n1(draft.overall)}%` : "–"}</b>
                <div className="xs muted">Plain average of the five parts. The national tool has its own scoring; this number is ours and only orders the evidence.</div>
              </div>
              <div className="outcome">
                {at === 0 ? <>
                  <div className="upper muted">Next step</div>
                  {mayEndorse ? <div className="row wrap" style={{ marginTop: 6, gap: 6 }}>
                    <input className="input grow" style={{ minWidth: 150 }} placeholder="Gram Sabha date or resolution number (optional)" value={note} maxLength={120} onChange={(e) => setNote(e.target.value)} />
                    <button className="btn sm" disabled={busy} onClick={endorse}><Stamp />Record Gram Sabha endorsement</button>
                  </div> : <div className="sm" style={{ marginTop: 4 }}>The Pani Samiti records the Gram Sabha's endorsement.</div>}
                  <div className="xs muted" style={{ marginTop: 6 }}>Recording it publishes the assessment to every household's app and starts the 30-day feedback window. It does not write to any government system.</div>
                </> : <>
                  <div className="upper muted">Citizen feedback{at === 1 ? ` · open until ${dayMon(st.open_until)}` : " · closed"}</div>
                  <b className="num">{st.responses ? `${n0((st.agree / st.responses) * 100)}% agree` : "no answers yet"}</b>
                  <div className="bar" style={{ margin: "4px 0 6px" }}><i style={{ width: `${st.responses ? (st.agree / st.responses) * 100 : 0}%`, background: "var(--good)" }} /></div>
                  <div className="xs muted">{st.responses} household{st.responses === 1 ? "" : "s"} answered, {st.agree} agree. Endorsed {dayMon(st.endorsed_on)} · recorded by {st.endorsed_by}{st.note ? ` · ${st.note}` : ""}. Answers that arrive while the simulation runs are simulated.</div>
                  {st.comments.map((c: any, i: number) => <div key={i} className="row xs" style={{ padding: "5px 0", borderTop: "1px solid var(--line)", marginTop: 6, alignItems: "flex-start" }}><span className={`pill ${c.agree ? "good" : "critical"}`}>{c.agree ? "agrees" : "disagrees"}</span><span className="ink2">"{c.comment}"</span></div>)}
                </>}
              </div>
            </div>
            <p className="xs muted" style={{ marginTop: 10 }}>{draft.note} Keyed to {draft.ids.sujal_gaon_id} (placeholder).</p>
          </div>
        </div>
      )}
    </div>
  );
}

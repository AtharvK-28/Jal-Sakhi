import { useNavigate } from "react-router-dom";
import { Activity, BrainCircuit, CircleAlert, FlaskRound, Gauge, GitFork, Hourglass, ListOrdered, MapPin, MessageSquareText, Radar, Ruler, Sparkles, TrendingDown, Waves } from "lucide-react";
import { useLive, usePoll } from "../lib/live";
import { Empty, LiquidGauge, Loader, SevPill } from "../components/ui";
import { LineChart } from "../components/charts";
import { VillagePicker } from "../components/Shell";
import { lifeText } from "../components/Twin";
import { fromMinute, n0, n1 } from "../lib/format";

const PARTS: [string, string, string][] = [["severity", "Severity", "var(--s1)"], ["households_affected", "Households", "var(--s2)"], ["citizen_reports", "Citizen reports", "var(--s3)"], ["health_risk", "Health risk", "var(--s4)"], ["sensitive_sites", "School / AWC / PHC", "#7c5cf0"], ["ageing_sla", "Ageing / SLA", "#8a9fb2"]];

export function AIInsights() {
  const { village, focus, clock } = useLive();
  const nav = useNavigate();
  const { data: a } = usePoll<any>(`/api/ai/insights?village=${village}`, 2500);
  const { data: card } = usePoll<any>("/api/ai/models", 0);
  const { data: tr } = usePoll<any>(`/api/villages/${village}/trends?limit=160`, 5000);
  if (!a) return <div className="page"><Loader /></div>;
  const pump = a.pump || {};
  const risk = pump.risk != null ? Math.round(pump.risk * 100) : null;
  const est = a.estimator;
  const src = a.source || {};
  const nowMin = clock ? Math.floor(new Date(clock.iso).getTime() / 60000) : 0;
  const m = card?.models;

  return (
    <div className="page">
      <div className="page-h">
        <div><h1>AI insights · {focus?.name}</h1><p>Seven models work on the live stream. One infers every home's tap status from a few sensors. Three watch each lane: one raises the alarm, one says leak or obstruction, one places the leak. Two watch the pump: the risk of failure and the life it has left. One reads citizen reports. A forecast projects the tank a day ahead.</p></div>
        <VillagePicker />
      </div>
      <div className="note" style={{ marginBottom: 16 }}><CircleAlert /><span><b>Honest status:</b> every model here is trained and evaluated on simulator output. The metrics below show the models recover injected faults in simulation; they are not field accuracy. Each card also shows what the model replaced and how that scored on the same cases. Field use needs authorised historical data, time-split validation and a pilot calibration period.</span></div>

      <div className="grid g3">
        <div className="card">
          <div className="card-h"><h3><Radar />Virtual sensing</h3><span className="pill ai">state estimation</span></div>
          <div className="card-b">
            <div className="row" style={{ gap: 16 }}>
              <LiquidGauge value={est.agreement_pct} size={104} label="% agree" tone={{ c1: "#a78bfa", c2: "#5b3fd0" }} />
              <div className="sm"><b style={{ fontSize: 15 }}>{est.households - est.instrumented} homes inferred</b><div className="ink2">from {est.instrumented} metered homes plus lane entry and tail sensors</div>
                <div className="muted xs" style={{ marginTop: 6 }}>Agreement with simulator ground truth over {n0(est.samples)} household-minutes. Only measurable in simulation.</div></div>
            </div>
            <p className="sm ink2" style={{ marginTop: 12 }}>Pressure is interpolated along each lane between the points that are reporting, then corrected for each tap's elevation. Homes far from any live sensor are marked <b>unknown</b>, not healthy.{est.confidence_avg != null && <> Average confidence right now: <b>{Math.round(est.confidence_avg * 100)}%</b>.</>}</p>
          </div>
        </div>

        <div className="card">
          <div className="card-h"><h3><Activity />Pump failure risk</h3><span className="pill ai">gradient-boosted trees</span></div>
          <div className="card-b">
            <div className="row" style={{ gap: 16 }}>
              <LiquidGauge value={risk} size={104} label="% risk" tone={risk != null && risk >= 60 ? { c1: "#fb7185", c2: "#d03b3b" } : risk != null && risk >= 30 ? { c1: "#fbbf24", c2: "#e08a1e" } : { c1: "#6ee7b7", c2: "#0e9f6e" }} />
              <div className="sm">
                <b style={{ fontSize: 15 }}>{risk == null ? "Waiting for the pump to run" : risk >= 60 ? "Likely to fail soon" : risk >= 30 ? "Watch" : "Healthy"}</b>
                <div className="ink2">chance of failure within about 72 run-hours</div>
                <div className="num" style={{ marginTop: 6 }}>Health index <b>{n1(pump.health, 0)}%</b></div>
                {pump.life && <div className="xs ink2" style={{ marginTop: 2 }}>Life left: <b>{lifeText(pump.life)}</b></div>}
                <div className="muted xs">{pump.on ? `running · ${n1(pump.current_a)} A · ${n1(pump.vibration_mms)} mm/s · ${n0(pump.discharge_lpm)} L/min` : "pump idle: last signature shown"}</div>
              </div>
            </div>
            <div style={{ marginTop: 10 }}><LineChart height={110} yMin={0} xFmt={fromMinute} yFmt={(y) => y.toFixed(0)} unit=" mm/s" series={[{ name: "Vibration", color: "var(--s2)", pts: (tr?.pump_vibration || []).filter((p: any) => p[1] > 0) }]} empty="vibration appears when the pump runs" /></div>
          </div>
        </div>

        <div className="card">
          <div className="card-h"><h3><Waves />Tank forecast (24 h)</h3><span className="pill ai">mass balance + learned demand</span></div>
          <div className="card-b">
            <LineChart height={150} yMin={0} yMax={100} unit="%" xFmt={fromMinute} yFmt={(y) => `${Math.round(y)}`}
              series={[{ name: "Measured", color: "var(--s1)", pts: (tr?.tank || []).slice(-60) }, { name: "Forecast", color: "var(--s2)", dashed: true, pts: (a.forecast?.curve || []).map((c: any, i: number) => [nowMin + i * 30, c[1]]) }]} />
            {a.forecast?.empty_at ? <div className="note warn" style={{ marginTop: 10 }}><TrendingDown /><span><b>Runs dry at {a.forecast.empty_at.slice(11, 16)}</b> ({n1(a.forecast.hours_to_empty, 1)} h from now), during a supply window. {a.forecast.pump_available ? "" : "The pump is not available."}</span></div>
              : <p className="sm ink2" style={{ marginTop: 10 }}>No shortfall in the next 24 hours. The projection uses the tank level, the pump's recent discharge and the learned minute-by-minute demand.</p>}
          </div>
        </div>
      </div>

      <div className="grid g-main" style={{ marginTop: 16 }}>
        <div className="card">
          <div className="card-h"><h3><Sparkles />Lane fault detection</h3><span className="pill ai">learned baseline + sequential test + classifier</span></div>
          <div className="tbl-wrap">
            <table className="tbl">
              <thead><tr><th>Lane</th><th title="Accumulated evidence that pressure loss is above the lane's learned curve, as a share of the alarm level">Evidence</th><th>Flow: measured / expected</th><th title="How far pressure loss is from the lane's learned head-loss curve">Pressure residual</th><th title="How far flow is from the learned demand profile">Flow deviation</th><th>Reads as</th><th>Where</th></tr></thead>
              <tbody>
                {a.branches.map((b: any) => {
                  const share = Math.min(1.3, b.evidence / a.thresholds.alarm_level);
                  return (
                    <tr key={b.id}>
                      <td><b>{b.name}</b><div className="xs muted mono">{b.id}</div></td>
                      <td style={{ minWidth: 140 }}><div className="row"><b className="num" style={{ width: 40 }}>{Math.round(Math.min(1, share) * 100)}%</b><div className="bar grow"><i style={{ width: `${Math.min(100, share * 100)}%`, background: share >= 1 ? "linear-gradient(90deg,#a78bfa,#5b3fd0)" : undefined }} /></div></div>
                        <div className="xs muted" title="Isolation Forest: how unusual the lane looks overall">unusualness {n1(b.anomaly, 2)}</div></td>
                      <td className="num">{b.exp_flow != null ? `${n0(b.flow)} / ${n0(b.exp_flow)} L/min` : <span className="muted">supply off</span>}</td>
                      <td className="num">{b.residual_bar != null ? <>{n1(b.residual_bar, 2)} bar <span className={Math.abs(b.z_r) >= 3 ? "pill high" : "muted"}>{n1(b.z_r, 1)}σ</span></> : "–"}</td>
                      <td className="num">{b.exp_flow != null ? <span className={b.z_q >= 2 ? "pill high" : "muted"}>{n1(b.z_q, 1)}σ</span> : "–"}</td>
                      <td>{b.p_leak == null ? <span className="muted">no fault</span> : b.p_leak >= 0.5 ? <span className="pill critical">leak {Math.round(b.p_leak * 100)}%</span> : <span className="pill high">obstruction {Math.round((1 - b.p_leak) * 100)}%</span>}</td>
                      <td className="sm">{!b.location ? <span className="muted">–</span> : b.location.near ? <>near <b>{b.location.near}</b><div className="xs muted">{b.location.from} to {b.location.to}{b.location.citizen ? " · with a citizen sighting" : ""}</div></> : <>{b.location.from} to {b.location.to}</>}</td>
                    </tr>);
                })}
              </tbody>
            </table>
          </div>
          <div className="card-b sm ink2">Each reading adds or removes evidence according to how far the lane's pressure loss is from its learned curve. A fault is raised when the total reaches {a.thresholds.alarm_level}, which takes at least four readings, so a two-minute dip cannot do it. A classifier then reads the pattern along the lane (a leak's loss builds up to the leak; an obstruction's appears at one point), and a leak is placed by fitting that shape to the taps that are metered.</div>
        </div>

        <div className="card">
          <div className="card-h"><h3><TrendingDown />Source sustainability</h3><span className="pill ai">trend projection</span></div>
          <div className="card-b">
            <LineChart height={150} yFmt={(y) => y.toFixed(1)} unit=" m" xFmt={(i) => (i === (src.history?.length || 1) - 1 ? "today" : `${(src.history?.length || 1) - 1 - i} d ago`)}
              yMin={Math.floor(Math.min(...(src.history || [0])) - 1)} yMax={Math.ceil(Math.max(...(src.history || [1])) + 1)}
              series={[{ name: "Borewell rest level (m below ground)", color: "var(--s1)", pts: (src.history || []).map((d: number, i: number) => [i, d]) }]} />
            <div className="grid g3" style={{ marginTop: 10 }}>
              <div><div className="upper muted">Rest level</div><b className="num">{n1(src.rest_m ?? src.depth_m)} m</b></div>
              <div><div className="upper muted">Trend</div><b className="num">{n1(src.trend_m_per_day, 2)} m/day</b></div>
              <div><div className="upper muted">Margin</div><b className="num">{src.days_to_limit != null ? `~${n0(src.days_to_limit)} days` : "stable"}</b></div>
            </div>
            <p className="xs muted" style={{ marginTop: 8 }}>Deeper is worse. Linear projection of daily rest levels to the pump intake; seasonal recharge is not modelled.</p>
          </div>
        </div>
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <div className="card-h"><h3><ListOrdered />Maintenance priority, explained</h3>
          <div className="legend">{PARTS.map(([k, l, c]) => <span key={k}><i style={{ background: c }} />{l}</span>)}</div></div>
        <div className="card-b">
          {a.priority_queue.length === 0 ? <Empty>No open incidents to prioritise in this village.</Empty> : a.priority_queue.map((q: any, i: number) => (
            <button key={q.id} className="scn" style={{ gridTemplateColumns: "30px 1fr 150px", marginBottom: 8 }} onClick={() => nav(`/app/incidents/${q.id}`)}>
              <b className="num" style={{ fontSize: 18, textAlign: "center" }}>{i + 1}</b>
              <span><b>{q.title}</b>
                <span className="row wrap" style={{ gap: 6, margin: "5px 0 7px" }}><SevPill sev={q.severity} /><span className="muted xs">{q.id} · {q.affected} homes · {q.reports} reports</span></span>
                <span className="statusbar" style={{ height: 9, maxWidth: 520 }}>{PARTS.filter(([k]) => q.breakdown[k] > 0).map(([k, l, c]) => <i key={k} style={{ flex: q.breakdown[k], background: c }} title={`${l}: ${q.breakdown[k]}`} />)}<i style={{ flex: Math.max(0, 100 - q.priority), background: "var(--surface-3)" }} /></span>
                <span className="desc" style={{ marginTop: 6 }}>Next step: {q.action}</span></span>
              <span style={{ textAlign: "right" }}><b className="num" style={{ fontSize: 24 }}>{Math.round(q.priority)}</b><span className="desc">priority / 100</span></span>
            </button>
          ))}
        </div>
      </div>

      <div className="page-h" style={{ marginTop: 26, marginBottom: 12 }}><div><h2 className="row"><BrainCircuit size={20} color="var(--brand)" />Model cards</h2><p>What each model is, what it was trained on, and how it scored on held-out simulated data.</p></div>
        {card && <span className="muted xs">trained {card.generated} · scikit-learn {card.scikit_learn} · {card.data}</span>}</div>
      {!m ? <Loader /> : (
        <div className="grid g3">
          <ModelCard icon={<Gauge />} title="Lane fault detector" algo={m.branch_anomaly.algorithm} rows={[
            ["Injected faults detected", `${pct(m.branch_anomaly.event_detection_rate)} of ${m.branch_anomaly.events_tested}`, pct(m.branch_anomaly.was.event_detection_rate)],
            ["Median time to detect", `${m.branch_anomaly.median_detection_delay_min} min`, `${m.branch_anomaly.was.median_detection_delay_min} min`],
            ["Smallest leak tested (2.5 L/min)", `${m.branch_anomaly.by_fault["leak 2.5"].detected} of ${m.branch_anomaly.by_fault["leak 2.5"].of}`, `${m.branch_anomaly.by_fault["leak 2.5"].was_detected} of ${m.branch_anomaly.by_fault["leak 2.5"].of}`],
            ["False alarms on normal days", `${m.branch_anomaly.false_events_normal_branch_days} in ${m.branch_anomaly.normal_branch_days_tested} lane-days`, `${m.branch_anomaly.was.false_events_normal_branch_days}`],
            ["Training data", m.branch_anomaly.train_scope]]} note={m.branch_anomaly.alert_rule} was={m.branch_anomaly.was.method} />
          <ModelCard icon={<GitFork />} title="Leak or obstruction" algo={m.fault_classifier.algorithm} rows={[
            ["Correct on test faults", `${pct(m.fault_classifier.accuracy)} of ${m.fault_classifier.test_events}`, pct(m.fault_classifier.was.accuracy)],
            ["In two villages it never trained on", `${pct(m.fault_classifier.accuracy_unseen_villages)} of ${m.fault_classifier.unseen_village_events}`],
            ["Leaks called leaks", pct(m.fault_classifier.leak_recall)], ["Obstructions called obstructions", pct(m.fault_classifier.obstruction_recall)],
            ["Left undetermined", "none", pct(m.fault_classifier.was.undetermined)]]} note={m.fault_classifier.split} was={m.fault_classifier.was.method} />
          <ModelCard icon={<MapPin />} title="Leak locator" algo={m.leak_locator.algorithm} rows={[
            ["Median position error", `${m.leak_locator.median_error_homes} homes`, `${m.leak_locator.was.median_error_homes} homes`],
            ["Worst tenth of cases", `over ${m.leak_locator.p90_error_homes} homes`],
            ["Leaks it could place", `${m.leak_locator.leaks_located}`, `${m.leak_locator.was.leaks_located}`],
            ["True position inside the stated range", pct(m.leak_locator.true_position_inside_interval), pct(m.leak_locator.was.true_position_inside_interval)],
            ["Width of the stated range", `${m.leak_locator.median_interval_homes} homes`, `${m.leak_locator.was.median_interval_homes} homes`]]} note={m.leak_locator.note} was={m.leak_locator.was.method} />
          <ModelCard icon={<Activity />} title="Pump failure risk" algo={m.pump_failure_risk.algorithm} rows={[
            ["ROC AUC (held-out pumps)", m.pump_failure_risk.roc_auc], ["Precision / recall at alert", `${m.pump_failure_risk.precision} / ${m.pump_failure_risk.recall}`],
            ["Pumps flagged before failing", m.pump_failure_risk.pumps_flagged_before_failure], ["Median warning lead time", `${m.pump_failure_risk.median_lead_time_run_hours} run-hours`],
            ["Validation split", m.pump_failure_risk.split]]} note={`${m.pump_failure_risk.target}. Tried and dropped: ${m.pump_failure_risk.tried_and_dropped}.`} />
          <ModelCard icon={<Hourglass />} title="Pump remaining life" algo={m.pump_remaining_life.algorithm} rows={[
            ["Median error, own wear trend", `${m.pump_remaining_life.own_trend_median_error_h} run-hours`],
            ["Readings where the trend is clear", pct(m.pump_remaining_life.own_trend_available)],
            ["Truth inside the stated range", pct(m.pump_remaining_life.own_trend_interval_coverage)],
            ["Median error, fleet prior alone", `${m.pump_remaining_life.fleet_prior_median_error_h} run-hours`],
            ["Fleet range holds the truth", pct(m.pump_remaining_life.fleet_prior_interval_coverage), pct(m.pump_remaining_life.fleet_prior_interval_coverage_before_widening)]]} note={m.pump_remaining_life.note} was="the fleet range before it was widened on pumps the model had not seen" />
          <ModelCard icon={<MessageSquareText />} title="Complaint classifier" algo={m.complaint_classifier.algorithm} rows={[
            ["Accuracy, every phrase held out in turn", `${pct(m.complaint_classifier.accuracy)} of ${m.complaint_classifier.seed_phrases}`],
            ["On the first batch of phrases", pct(m.complaint_classifier.accuracy_on_first_batch), pct(m.complaint_classifier.was.accuracy_on_first_batch)],
            ["On the newer batch", pct(m.complaint_classifier.accuracy_on_newer_phrases), pct(m.complaint_classifier.was.accuracy_on_newer_phrases)],
            ["By language", Object.entries(m.complaint_classifier.accuracy_by_language).map(([k, v]: any) => `${k} ${Math.round(v * 100)}%`).join(" · ")],
            ["Weakest classes", Object.entries(m.complaint_classifier.accuracy_by_class).sort((p: any, q: any) => p[1] - q[1]).slice(0, 2).map(([k, v]: any) => `${k.replace("_", " ")} ${Math.round(v * 100)}%`).join(" · ")]]}
            note={`${m.complaint_classifier.reading} Low-confidence text falls back to the category the citizen tapped.`} was={m.complaint_classifier.was.method} />
        </div>
      )}
      {card && <div className="card pad" style={{ marginTop: 16 }}><div className="upper muted" style={{ marginBottom: 6 }}>Known limits</div><ul className="sm ink2" style={{ margin: 0, paddingLeft: 18, lineHeight: 1.7 }}>{card.limits.map((l: string) => <li key={l}>{l}</li>)}</ul></div>}
    </div>
  );
}

const pct = (v: number | null | undefined) => (v == null ? "–" : `${Math.round(v * 100)}%`);

/** rows: [what, value now, value of the method it replaced (optional)] */
function ModelCard({ icon, title, algo, rows, note, was }: { icon: React.ReactNode; title: string; algo: string; rows: [string, any, any?][]; note: string; was?: string }) {
  return (
    <div className="card">
      <div className="card-h"><h3>{icon}{title}</h3><span className="pill demo">simulated data</span></div>
      <div className="card-b">
        <p className="sm ink2">{algo}</p>
        <div style={{ marginTop: 10 }}>{rows.map(([k, v, old]) => (
          <div key={k} className="row between sm" style={{ padding: "6px 0", borderBottom: "1px solid var(--line)", alignItems: "flex-start" }}>
            <span className="ink2">{k}</span>
            <span style={{ textAlign: "right", maxWidth: "60%" }}><b className="num">{String(v)}</b>{old != null && <span className="muted xs" style={{ marginLeft: 6, whiteSpace: "nowrap" }}>was {String(old)}</span>}</span>
          </div>))}</div>
        {was && <p className="xs muted" style={{ marginTop: 9 }}><b>"Was"</b> is {was}, scored on the same cases.</p>}
        <p className="xs muted" style={{ marginTop: was ? 4 : 9 }}>{note}</p>
      </div>
    </div>
  );
}

export const _unused = { Ruler, FlaskRound };

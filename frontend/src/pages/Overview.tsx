import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Activity, AlertTriangle, BadgeCheck, CheckCircle2, ChevronRight, Cpu, Droplets, FlaskConical, Gauge, HeartHandshake, MessageSquareText,
  Network, Radio, ShieldQuestion, Siren, TrendingUp, Users, Waves as WavesIcon,
} from "lucide-react";
import { useLive, usePoll } from "../lib/live";
import { Empty, Kpi, LiquidGauge, Loader, StatusBar, SupplyPill, Waves } from "../components/ui";
import { LineChart, Sparkline } from "../components/charts";
import { Twin, TwinLegend } from "../components/Twin";
import { Feed, IncidentQueue } from "../components/panels";
import { HouseholdDrawer } from "./Households";
import { dayMon, fromMinute, n0, n1, scoreColor, scoreTone } from "../lib/format";

export function Overview() {
  const { scope } = useLive();
  return scope.level === "village" ? <VillageOverview /> : <UnitOverview />;
}

// ---------------------------------------------------------------- village level
function VillageOverview() {
  const { focus: v, clock, snap, village } = useLive();
  const nav = useNavigate();
  const [sel, setSel] = useState<string | null>(null);
  const { data: tr } = usePoll(`/api/villages/${village}/trends?limit=120`, 5000);
  if (!v || !clock) return <div className="page"><Loader text="Connecting to the live stream" /></div>;
  const k = v.kpis;
  const mine = (snap.incidents || []).filter((i: any) => i.village_id === v.id);
  const crit = mine.some((i: any) => i.severity === "critical");
  const fn = k.functional;
  const tone = scoreTone(k.score);
  const feed = (snap.feed || []).filter((f: any) => !f.village_id || f.village_id === v.id);
  const nowMin = Math.floor(new Date(clock.iso).getTime() / 60000);

  return (
    <div className="page">
      <section className={`hero ${crit ? "alert" : clock.in_window ? "" : "off"}`}>
        <div className="row between wrap" style={{ alignItems: "flex-start", gap: 20 }}>
          <div className="grow" style={{ minWidth: 260 }}>
            <div className="meta">{v.admin.gp} · {v.admin.block} block · {v.admin.district} district · {v.admin.state}</div>
            <h1 style={{ marginTop: 4 }}>{v.name}</h1>
            <div style={{ fontSize: 16, fontWeight: 600, marginTop: 10 }} className="row wrap">
              {clock.in_window ? <><Droplets size={19} />{clock.window_label} supply in progress</> : <><WavesIcon size={19} />Supply is off as scheduled · next at {clock.next_window}</>}
              {crit && <span className="chip" style={{ background: "rgba(0,0,0,.25)" }}><Siren size={12} style={{ verticalAlign: -2 }} /> critical incident open</span>}
            </div>
            {clock.in_window && (
              <div style={{ maxWidth: 440, marginTop: 10 }}>
                <div className="progress"><i style={{ width: `${(clock.min_in_window / clock.window_len) * 100}%` }} /></div>
                <div className="meta" style={{ marginTop: 5 }}>{clock.window_start} to {clock.window_end} · minute {clock.min_in_window} of {clock.window_len} · {k.supply_min} of {k.sched_min} scheduled minutes delivered today</div>
              </div>
            )}
            <div className="chips">
              <span className="chip" title="Placeholder identifier">Sujal Gaon ID {v.ext.sujal_gaon_id}</span>
              <span className="chip" title="Placeholder identifier">IMIS {v.ext.imis_habitation_id}</span>
              <span className="chip">{k.households} FHTCs · {v.branches.length} lanes</span>
              <span className="chip">{k.devices_total} sensors · {v.households.filter((h: any) => h.m).length} metered homes</span>
            </div>
          </div>
          <div className="row" style={{ gap: 16, background: "rgba(255,255,255,.14)", padding: "12px 18px 12px 12px", borderRadius: 20, border: "1px solid rgba(255,255,255,.22)" }}>
            <LiquidGauge value={k.score} size={118} label="service score" tone={tone} />
            <div style={{ fontSize: 12.5, lineHeight: 1.75 }}>
              <div style={{ fontWeight: 750, fontSize: 15 }}>{tone.word}</div>
              {[["Supply", k.score_parts.supply], ["Quantity", k.score_parts.quantity], ["Quality", k.score_parts.quality], ["Data health", k.score_parts.data]].map(([l, p]) => (
                <div key={l as string} className="row" style={{ gap: 8 }}><span style={{ width: 74, opacity: 0.9 }}>{l}</span><div className="progress" style={{ width: 70, height: 5 }}><i style={{ width: `${p}%` }} /></div><b className="num">{p}</b></div>
              ))}
            </div>
          </div>
        </div>
        <Waves />
      </section>

      <div className="grid kpis" style={{ margin: "18px 0" }}>
        <Kpi icon={<Droplets />} label={clock.in_window ? "Receiving water now" : "Supply status"} tone={k.counts.dry ? "crit" : k.counts.low ? "warn" : undefined}
          value={clock.in_window ? k.counts.ok : "Off"} unit={clock.in_window ? `/ ${k.households} homes` : "scheduled"}
          sub={clock.in_window ? <>{k.counts.low} low pressure · {k.counts.dry} no water · {k.counts.unknown} unknown</> : `Next window ${clock.next_window}`} />
        <Kpi icon={<BadgeCheck />} label="Functional taps (JJM 3-test)" tone={fn && fn.pct < 80 ? "warn" : "good"} value={fn ? n1(fn.pct, 0) : "–"} unit="%"
          sub={fn ? <>{fn.basis === "today" ? `today, ${fn.windows} window${fn.windows > 1 ? "s" : ""} scored` : "previous day"} · regular {n0(fn.regular_pct)} · quantity {n0(fn.quantity_pct)} · quality {n0(fn.quality_pct)}</> : "scored when a window closes"} />
        <Kpi icon={<Gauge />} label="Supplied today (est.)" value={n1(k.lpcd_avg, 0)} unit={`/ ${k.lpcd_norm} lpcd`} sub="litres per person so far; norm is 55">
          <div className="bar" style={{ marginTop: 8 }}><i style={{ width: `${Math.min(100, (k.lpcd_avg / k.lpcd_norm) * 100)}%` }} /></div>
        </Kpi>
        <Kpi icon={<Siren />} label="Open incidents" tone={k.critical ? "crit" : k.open_incidents ? "warn" : "good"} value={k.open_incidents} sub={k.open_incidents ? `${k.critical} critical · ${k.high} high` : "nothing needs attention"} />
        <Kpi icon={<MessageSquareText />} label="Citizen reports open" tone={k.complaints_open ? "warn" : undefined} value={k.complaints_open}
          sub={k.pulse ? `Daily pulse: ${k.pulse.got_water}/${k.pulse.responses} got water · ${n0(k.pulse.agreement_pct)}% match sensors` : "daily pulse after each window"} />
        <Kpi icon={<Radio />} label="Sensors online" tone={k.devices_problem ? "warn" : "good"} value={n0(k.devices_online_pct)} unit="%" sub={k.devices_problem ? `${k.devices_problem} stale or offline` : `all ${k.devices_total} reporting`} />
      </div>

      <div className="card">
          <div className="card-h">
            <h3><Network />Live network twin</h3>
            <div className="row"><span className="pill info">{v.households.filter((h: any) => !h.m).length} homes inferred from {v.households.filter((h: any) => h.m).length} meters</span>
              <button className="btn soft sm" onClick={() => nav("/app/twin")}>Full view<ChevronRight /></button></div>
          </div>
          <div className="card-b">
            <Twin v={v} clock={clock} selected={sel} onSelect={setSel} />
            <div style={{ marginTop: 10 }}><TwinLegend /></div>
          </div>
      </div>

      <div className="grid g2" style={{ marginTop: 16 }}>
        <div className="card">
          <div className="card-h"><h3><Siren />Maintenance priority queue</h3><span className="muted xs">ranked by impact</span></div>
          <div className="card-b"><IncidentQueue items={mine} limit={4} /></div>
        </div>
        <div className="card">
          <div className="card-h"><h3><Activity />Live event feed</h3>{v.demo_faults?.length > 0 && <span className="pill demo">{v.demo_faults.length} simulated fault{v.demo_faults.length > 1 ? "s" : ""}</span>}</div>
          <div className="card-b" style={{ maxHeight: 300, overflowY: "auto" }}><Feed items={feed} /></div>
        </div>
      </div>

      <div className="grid g3" style={{ marginTop: 16 }}>
        <div className="card">
          <div className="card-h"><h3><TrendingUp />Tank level: last readings and 24 h forecast</h3></div>
          <div className="card-b">
            <LineChart height={170} yMin={0} yMax={100} unit="%" yFmt={(y) => `${Math.round(y)}`}
              series={[
                { name: "Measured", color: "var(--s1)", pts: (tr?.tank || []).map((p: any) => [p[0], p[1]]) },
                { name: "Forecast (AI)", color: "var(--s2)", dashed: true, pts: (v.forecast?.curve || []).map((c: any, i: number) => [nowMin + i * 30, c[1]]) },
              ]} xFmt={fromMinute} />
            <div className="row between sm" style={{ marginTop: 6 }}>
              <span className="muted">{v.forecast?.basis}</span>
              {v.forecast?.empty_at ? <span className="pill critical"><AlertTriangle />dry at {v.forecast.empty_at.slice(11, 16)}</span> : <span className="pill good"><CheckCircle2 />no shortfall forecast</span>}
            </div>
          </div>
        </div>
        <div className="card">
          <div className="card-h"><h3><Gauge />Lanes: pressure and flow</h3><span className="muted xs">tail pressure trend</span></div>
          <div className="card-b" style={{ paddingTop: 8 }}>
            {v.branches.map((b: any, i: number) => {
              const series = (tr?.branches?.[i]?.p_end || []).map((p: any) => p[1]);
              return (
                <div key={b.id} className="row" style={{ padding: "6px 0", borderBottom: i < v.branches.length - 1 ? "1px solid var(--line)" : 0 }}>
                  <div style={{ width: 96 }}><b className="sm">{b.name}</b><div className="xs muted num">{b.fresh_in && clock.in_window ? `${n1(b.p_in, 2)}→${b.fresh_end ? n1(b.p_end, 2) : "?"} bar` : clock.in_window ? "no data" : "off"}</div></div>
                  <div className="grow"><Sparkline pts={series.slice(-60)} height={30} min={0} max={1.6} color={b.status === "ok" || b.status === "idle" ? "var(--s1)" : b.status === "unknown" ? "var(--unk)" : "var(--s2)"} /></div>
                  <span className={`pill ${b.status === "ok" ? "s-ok" : b.status === "idle" ? "s-idle" : b.status === "unknown" ? "s-unknown" : b.status === "anomaly" ? "ai" : b.status === "low" ? "s-low" : "s-dry"}`} style={{ minWidth: 78, justifyContent: "center" }}>
                    {b.status === "ok" ? `${n0(b.flow)} L/min` : b.status === "idle" ? "off" : b.status === "interrupted" ? "no supply" : b.status === "leak" ? "leak?" : b.status === "low" ? "low" : b.status === "anomaly" ? "AI flag" : "unknown"}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
        <div className="card">
          <div className="card-h"><h3><FlaskConical />Water quality screening</h3><button className="btn soft sm" onClick={() => nav("/app/quality")}>Details</button></div>
          <div className="card-b stack" style={{ gap: 10 }}>
            {v.quality.map((q: any) => (
              <div key={q.id} className="row" style={{ alignItems: "flex-start" }}>
                <span className={`pill ${q.status === "ok" ? "good" : q.status === "watch" ? "medium" : q.status === "verify" ? "critical" : "s-unknown"}`} style={{ minWidth: 92, justifyContent: "center" }}>
                  {q.status === "ok" ? "in range" : q.status === "watch" ? "watch" : q.status === "verify" ? "verify" : "no data"}
                </span>
                <div className="grow sm"><b>{q.name}</b>
                  <div className="muted num">turbidity {n1(q.turbidity_ntu, 2)} NTU · Cl {n1(q.chlorine_mgl, 2)} mg/L · pH {n1(q.ph, 1)} · TDS {n0(q.tds_mgl)}</div></div>
              </div>
            ))}
            <div className="note"><ShieldQuestion /><span>Sensors screen four parameters. They cannot certify the water as safe: bacteria and chemicals need FTK and lab tests.</span></div>
          </div>
        </div>
      </div>
      {sel && <HouseholdDrawer id={sel} onClose={() => setSel(null)} />}
    </div>
  );
}

// ------------------------------------------------- block / district / state level
function UnitOverview() {
  const { scope, setScope, snap } = useLive();
  const { data, error } = usePoll(`/api/overview?level=${scope.level}&id=${scope.id}`, 4000);
  const names = useMemo(() => Object.fromEntries((snap?.summary || []).map((v: any) => [v.id, v.name])), [snap]);
  if (error) return <div className="page"><Empty icon={<AlertTriangle />}>{error}</Empty></div>;
  if (!data) return <div className="page"><Loader /></div>;
  const t = data.totals;
  const tone = scoreTone(t.score);
  const kids: any[] = data.children.length ? data.children : data.villages;
  const childLabel = scope.level === "state" ? "District" : scope.level === "district" ? "Block" : "Gram Panchayat / village";
  const inWin = snap?.clock?.in_window;

  return (
    <div className="page">
      <section className={`hero ${t.critical ? "alert" : inWin ? "" : "off"}`}>
        <div className="row between wrap" style={{ alignItems: "flex-start", gap: 20 }}>
          <div className="grow" style={{ minWidth: 260 }}>
            <div className="meta" style={{ textTransform: "capitalize" }}>{scope.level} view · rural water service delivery</div>
            <h1 style={{ marginTop: 4 }}>{data.name}{scope.level !== "state" ? ` ${scope.level}` : ""}</h1>
            <div className="chips">
              <span className="chip">{t.villages} village schemes</span><span className="chip">{n0(t.households)} household taps (FHTC)</span>
              <span className="chip">{t.open} open incidents</span><span className="chip">{t.complaints_open} citizen reports open</span>
            </div>
            <p className="meta" style={{ marginTop: 12, maxWidth: 560 }}>Every number rolls up from household-level status in each village. Click a row to drill down to the lane and the tap.</p>
          </div>
          <div className="row" style={{ gap: 16, background: "rgba(255,255,255,.14)", padding: "12px 18px 12px 12px", borderRadius: 20, border: "1px solid rgba(255,255,255,.22)" }}>
            <LiquidGauge value={t.score} size={118} label="service score" tone={tone} />
            <div style={{ fontSize: 12.5 }}><div style={{ fontWeight: 750, fontSize: 15 }}>{tone.word}</div><div style={{ opacity: 0.9, maxWidth: 150, marginTop: 4 }}>household-weighted across {t.villages} schemes</div></div>
          </div>
        </div>
        <Waves />
      </section>

      <div className="grid kpis" style={{ margin: "18px 0" }}>
        <Kpi icon={<BadgeCheck />} label="Functional taps (JJM 3-test)" tone={t.functional_pct < 80 ? "warn" : "good"} value={n1(t.functional_pct, 0)} unit="%" sub="regular + adequate + quality, household-weighted" />
        <Kpi icon={<Droplets />} label={inWin ? "Receiving water now" : "Supply status"} value={inWin ? n0(t.counts.ok) : "Off"} unit={inWin ? `/ ${n0(t.households)}` : "scheduled"} tone={t.counts.dry ? "crit" : t.counts.low ? "warn" : undefined}
          sub={inWin ? `${t.counts.low || 0} low · ${t.counts.dry || 0} dry · ${t.counts.unknown || 0} unknown` : "between supply windows"} />
        <Kpi icon={<Siren />} label="Open incidents" tone={t.critical ? "crit" : t.open ? "warn" : "good"} value={t.open} sub={`${t.critical} critical`} />
        <Kpi icon={<MessageSquareText />} label="Citizen reports open" value={t.complaints_open} tone={t.complaints_open ? "warn" : undefined} sub="across all channels" />
        <Kpi icon={<FlaskConical />} label="Quality checks pending" value={t.quality_flags} tone={t.quality_flags ? "crit" : "good"} sub="villages needing FTK verification" />
        <Kpi icon={<Cpu />} label="Sensor issues" value={t.devices_problem} tone={t.devices_problem ? "warn" : "good"} sub="stale or offline devices" />
      </div>

      <div className="grid g-main">
        <div className="stack">
          <div className="card">
            <div className="card-h"><h3><Users />{childLabel} performance</h3><span className="muted xs">click a row to drill down</span></div>
            <div className="tbl-wrap">
              <table className="tbl">
                <thead><tr><th>{childLabel}</th><th>Service score</th><th>Functional</th><th>Households now</th><th>Incidents</th><th>Reports</th><th /></tr></thead>
                <tbody>
                  {[...kids].sort((a, b) => a.score - b.score).map((c: any) => (
                    <tr key={c.id} className="click" onClick={() => setScope({ level: c.level || "village", id: c.id })}>
                      <td><b>{c.name}</b><div className="xs muted">{c.villages ? `${c.villages} schemes · ` : ""}{n0(c.households)} taps{c.block && !c.villages ? ` · ${c.block}` : ""}</div></td>
                      <td style={{ minWidth: 150 }}><div className="row"><b className="num" style={{ width: 34 }}>{n0(c.score)}</b><div className="bar grow"><i style={{ width: `${c.score}%`, background: scoreColor(c.score) }} /></div></div></td>
                      <td className="num">{c.functional_pct != null ? `${n0(c.functional_pct)}%` : "–"}</td>
                      <td style={{ minWidth: 150 }}><div className="statusbar" style={{ height: 9 }}>{["ok", "low", "dry", "unknown", "idle"].filter((s) => c.counts?.[s]).map((s) => <i key={s} style={{ flex: c.counts[s], background: s === "ok" ? "var(--flow)" : s === "low" ? "var(--low)" : s === "dry" ? "var(--dry)" : s === "unknown" ? "var(--unk)" : "var(--idle)" }} title={`${s}: ${c.counts[s]}`} />)}</div>
                        <div className="xs muted" style={{ marginTop: 3 }}>{inWin ? `${c.counts?.ok || 0} ok · ${c.counts?.low || 0} low · ${c.counts?.dry || 0} dry` : "supply off"}</div></td>
                      <td>{c.open ? <span className={`pill ${c.critical ? "critical" : "medium"}`}>{c.open}</span> : <span className="pill good"><CheckCircle2 />0</span>}</td>
                      <td className="num">{c.complaints_open}</td>
                      <td><ChevronRight size={16} className="muted" /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
          <div className="card">
            <div className="card-h"><h3><TrendingUp />Functional taps, last 30 days</h3><span className="muted xs">household-weighted · seeded history + live days</span></div>
            <div className="card-b">
              <LineChart height={190} yMin={40} yMax={100} unit="%" yFmt={(y) => `${Math.round(y)}`}
                series={[{ name: "Functional (all three tests)", color: "var(--s1)", pts: data.trend.map((r: any, i: number) => [i, r.functional_pct]) }]}
                xFmt={(i) => dayMon(data.trend[i]?.day)} refLines={[{ y: 76, label: "national FA 2024: 76%" }]} />
            </div>
          </div>
        </div>
        <div className="stack">
          <div className="card"><div className="card-h"><h3><Siren />Priority queue</h3><span className="muted xs">{data.incidents.length} shown</span></div>
            <div className="card-b"><IncidentQueue items={data.incidents} limit={5} showVillage names={names} /></div></div>
          <div className="card"><div className="card-h"><h3><Activity />Live event feed</h3></div><div className="card-b" style={{ maxHeight: 320, overflowY: "auto" }}><Feed items={snap?.feed || []} /></div></div>
          <div className="note"><HeartHandshake /><span>Villages are the unit of truth. District and state figures are sums and household-weighted averages of village data, so a problem in one lane is never averaged away: it stays visible in the queue above.</span></div>
        </div>
      </div>
    </div>
  );
}

export { SupplyPill };

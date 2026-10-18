import { useMemo, useState } from "react";
import { BadgeCheck, CircleHelp, Home, MessageSquareText, Radio, Ruler, Search, XCircle } from "lucide-react";
import { useLive, usePoll } from "../lib/live";
import { Drawer, Empty, Loader, StatusPill, SupplyPill } from "../components/ui";
import { LineChart } from "../components/charts";
import { VillagePicker } from "../components/Shell";
import { CAT_LABEL, SUPPLY, dt, fromMinute, n0, n1 } from "../lib/format";

/** Two checks on the monitoring itself: do families agree with the sensors, and which homes fall short again and again. */
function TruthCards({ village }: { village: string }) {
  const { data: pulse } = usePoll<any>(`/api/villages/${village}/pulse`, 15000);
  const { data: eq } = usePoll<any>(`/api/villages/${village}/equity`, 30000);
  if (!pulse || !eq) return null;
  return (
    <div className="grid g2" style={{ marginBottom: 14 }}>
      <div className="card pad">
        <div className="row between"><b>Do families agree with the sensors?</b>
          <span className={`pill ${pulse.agreement_pct == null ? "" : pulse.agreement_pct >= 90 ? "good" : "medium"}`}>{pulse.agreement_pct == null ? "first answers after a window" : `${pulse.agreement_pct}% agree`}</span></div>
        <p className="xs muted" style={{ margin: "4px 0 8px" }}>{pulse.answers} "did water come?" answers compared with what the sensors inferred for the same home and window. {pulse.note}</p>
        {pulse.disagreements.slice(0, 5).map((r: any, i: number) => (
          <div key={i} className="row between sm" style={{ padding: "5px 0", borderTop: "1px solid var(--line)" }}>
            <span><b>{r.label}</b> · {r.lane}{r.metered ? " · metered" : ""}</span>
            <span className="xs">family said <b>{r.got_water ? "yes" : "no"}</b>, sensors said <b>{r.inferred ? "yes" : "no"}</b> · {r.window} {r.day.slice(5)}</span>
          </div>))}
      </div>
      <div className="card pad">
        <div className="row between"><b>Homes left out this week</b><span className={`pill ${eq.chronic.length ? "medium" : "good"}`}>{eq.chronic.length} homes</span></div>
        <p className="xs muted" style={{ margin: "4px 0 8px" }}>{eq.rules.chronic}. A village average hides them; these are the same homes every day.</p>
        {eq.chronic.slice(0, 5).map((h: any) => (
          <div key={h.id} className="row between sm" style={{ padding: "5px 0", borderTop: "1px solid var(--line)" }}>
            <span><b>{h.label}</b> · {h.lane} · position {h.position}</span><span className="xs"><b style={{ color: "var(--crit)" }}>{h.days_failed}/{h.of}</b> days · {h.avg_lpcd} lpcd</span>
          </div>))}
        {eq.dry.length > 0 && <div className="xs" style={{ marginTop: 6, color: "var(--crit)", fontWeight: 650 }}>No water for 14 days: {eq.dry.map((h: any) => h.label).join(", ")}</div>}
      </div>
    </div>
  );
}

export function Households() {
  const { village, focus } = useLive();
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [branch, setBranch] = useState("");
  const [sel, setSel] = useState<string | null>(null);
  const { data } = usePoll<any[]>(`/api/households?village=${village}`, 3000);
  const rows = useMemo(() => (data || []).filter((h) =>
    (!q || `${h.id} ${h.label} ${h.lane}`.toLowerCase().includes(q.toLowerCase())) && (!status || h.status === status) && (!branch || h.branch_id === branch)), [data, q, status, branch]);
  const lanes = useMemo(() => Array.from(new Map((data || []).map((h) => [h.branch_id, h.lane])).entries()), [data]);

  return (
    <div className="page">
      <div className="page-h">
        <div><h1>Households</h1><p>Every Functional Household Tap Connection in {focus?.name || "the village"}, with what we know about its service right now and how we know it.</p></div>
        <VillagePicker />
      </div>
      <TruthCards village={village} />
      <div className="card pad row wrap" style={{ marginBottom: 14 }}>
        <div style={{ position: "relative", flex: "1 1 240px" }}>
          <Search size={15} style={{ position: "absolute", left: 11, top: 11, color: "var(--muted)" }} />
          <input className="input" style={{ paddingLeft: 32 }} placeholder="Search household ID or lane, e.g. HH-014" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <select className="select" style={{ width: "auto" }} value={branch} onChange={(e) => setBranch(e.target.value)}>
          <option value="">All lanes</option>{lanes.map(([id, name]) => <option key={id} value={id}>{name}</option>)}
        </select>
        <div className="seg">
          {[["", "All"], ["ok", "Receiving"], ["low", "Low"], ["dry", "No water"], ["unknown", "Unknown"]].map(([k, l]) => <button key={k} className={status === k ? "on" : ""} onClick={() => setStatus(k)}>{l}</button>)}
        </div>
        <span className="muted sm">{rows.length} of {data?.length ?? 0}</span>
      </div>
      <div className="card tbl-wrap" style={{ maxHeight: "calc(100vh - 290px)" }}>
        {!data ? <Loader /> : rows.length === 0 ? <Empty icon={<Search />}>No household matches these filters.</Empty> : (
          <table className="tbl">
            <thead><tr><th>Household</th><th>Lane</th><th>Service now</th><th>Pressure</th><th>How we know</th><th>Today</th><th>Functional today</th><th>Reports</th></tr></thead>
            <tbody>
              {rows.map((h) => (
                <tr key={h.id} className="click" onClick={() => setSel(h.id)}>
                  <td><b>{h.label}</b><div className="xs muted mono">{h.id}</div></td>
                  <td>{h.lane}<div className="xs muted">position {h.position} · {h.members} people</div></td>
                  <td><SupplyPill s={h.status} /></td>
                  <td className="num">{h.status === "idle" || h.status === "unknown" ? "–" : `${n1(h.pressure_bar, 2)} bar`}</td>
                  <td>{h.status === "idle" ? <span className="muted sm">supply off</span> : h.status === "unknown" ? <span className="pill s-unknown"><CircleHelp />no data</span>
                    : h.instrumented ? <span className="pill info"><Radio />measured</span> : <span className="pill"><Ruler />estimated · {Math.round(h.confidence * 100)}%</span>}</td>
                  <td className="num">{n0(h.lpcd_today)} <span className="muted xs">lpcd</span></td>
                  <td>{h.functional === null ? <span className="muted sm">after window</span> : h.functional ? <span className="pill good"><BadgeCheck />yes</span> : <span className="pill critical"><XCircle />no</span>}</td>
                  <td>{h.open_reports ? <span className="pill high"><MessageSquareText />{h.open_reports}</span> : <span className="muted">–</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      {sel && <HouseholdDrawer id={sel} onClose={() => setSel(null)} />}
    </div>
  );
}

export function HouseholdDrawer({ id, onClose }: { id: string; onClose: () => void }) {
  const { data: d } = usePoll<any>(`/api/households/${id}`, 2500);
  if (!d) return <Drawer title="Household" onClose={onClose}><Loader /></Drawer>;
  const h = d.household, live = d.live;
  const f = live.flags;
  return (
    <Drawer onClose={onClose} title={<span className="row"><Home size={19} color="var(--brand)" />{h.label}<span className="tag">DEMO</span></span>}
      sub={<>{h.lane}, position {d.household.position} · {h.village} · {h.members} people · FHTC {h.fhtc_id}</>}>
      <div className="card pad">
        <div className="row between wrap">
          <div><div className="upper muted">Service right now</div><div style={{ marginTop: 6 }}><SupplyPill s={live.state} /></div>
            <p className="sm ink2" style={{ marginTop: 6 }}>{SUPPLY[live.state].hint}</p></div>
          <div style={{ textAlign: "right" }}>
            <div style={{ fontSize: 26, fontWeight: 750 }} className="num">{live.state === "idle" || live.state === "unknown" ? "–" : n1(live.pressure_bar, 2)}<small className="muted" style={{ fontSize: 13 }}> bar</small></div>
            <div className="xs muted">{live.basis === "measured" ? "measured at this tap" : live.basis === "estimated" ? `estimated · confidence ${Math.round(live.confidence * 100)}%` : live.basis === "unknown" ? "cannot be estimated" : "supply window closed"}</div>
          </div>
        </div>
        {d.note && <div className="note" style={{ marginTop: 12 }}><Ruler /><span>{d.note}</span></div>}
      </div>

      <div className="grid g2">
        <div className="card pad"><div className="upper muted">Water received today</div>
          <div style={{ fontSize: 24, fontWeight: 750, marginTop: 4 }} className="num">{n0(live.lpcd_today)}<small className="muted" style={{ fontSize: 13 }}> / 55 lpcd</small></div>
          <div className="bar" style={{ marginTop: 8 }}><i style={{ width: `${Math.min(100, (live.lpcd_today / 55) * 100)}%` }} /></div>
          <div className="xs muted" style={{ marginTop: 5 }}>{n0(live.litres_today)} litres for {h.members} people {h.instrumented ? "(metered)" : "(estimated share of lane inflow)"}</div></div>
        <div className="card pad"><div className="upper muted">JJM functionality today</div>
          {f ? <div className="stack" style={{ gap: 5, marginTop: 8 }}>
            {[["regular", "Regular: water came in each scheduled window"], ["quantity", "Adequate: on track for 55 lpcd"], ["quality", "Quality: no open quality concern"]].map(([k, l]) => (
              <div key={k} className="row sm">{f[k] ? <BadgeCheck size={16} color="var(--good)" /> : <XCircle size={16} color="var(--crit)" />}<span>{l}</span></div>))}
            {!f.known && <div className="xs muted">Status was unknown for most of the window, so this home is not counted as functional.</div>}
          </div> : <p className="sm muted" style={{ marginTop: 8 }}>Scored when the current supply window closes.</p>}</div>
      </div>

      <div className="card pad">
        <div className="upper muted" style={{ marginBottom: 8 }}>Where this status comes from (pressure points on {h.lane})</div>
        <div style={{ position: "relative", height: 46, margin: "4px 8px 0" }}>
          <div style={{ position: "absolute", left: 0, right: 0, top: 18, height: 6, borderRadius: 3, background: "var(--pipe)" }} />
          {d.evidence_sources.map((s: any) => (
            <div key={s.device} title={`${s.device}: ${s.status}`} style={{ position: "absolute", left: `calc(${s.x * 100}% - 8px)`, top: 13, width: 16, height: 16, borderRadius: 5, border: `2px ${s.status === "online" ? "solid var(--brand)" : "dashed var(--unk)"}`, background: s.status === "online" ? "var(--surface)" : "var(--mute-bg)" }} />
          ))}
          <div title="this household" style={{ position: "absolute", left: `calc(${h.x * 100}% - 7px)`, top: 0, width: 14, height: 14, borderRadius: "50%", background: SUPPLY[live.state].color, border: "2px solid var(--ink)" }} />
        </div>
        <div className="row between xs muted"><span>lane entry</span><span>tail end</span></div>
        <div className="legend" style={{ marginTop: 8 }}>
          <span><i style={{ border: "2px solid var(--brand)", background: "var(--surface)" }} />sensor reporting</span>
          <span><i style={{ border: "2px dashed var(--unk)", background: "var(--mute-bg)" }} />sensor silent</span>
          <span><i style={{ borderRadius: "50%", background: SUPPLY[live.state].color, border: "2px solid var(--ink)" }} />this home</span>
        </div>
      </div>

      {h.instrumented && (
        <div className="card pad"><div className="upper muted" style={{ marginBottom: 6 }}>Smart tap node: pressure (bar)</div>
          <LineChart height={150} yMin={0} yMax={1.6} series={[{ name: "Pressure", color: "var(--s1)", pts: d.pressure_series }]} xFmt={fromMinute} yFmt={(y) => y.toFixed(1)} unit=" bar" /></div>
      )}

      {d.incidents.length > 0 && (
        <div><div className="upper muted" style={{ marginBottom: 7 }}>Open incidents affecting this home</div>
          <div className="stack" style={{ gap: 7 }}>{d.incidents.map((i: any) => <div key={i.id} className="card pad sm"><div className="row between"><b>{i.title}</b><StatusPill status={i.status} /></div><div className="muted xs">{i.id}</div></div>)}</div></div>
      )}
      <div><div className="upper muted" style={{ marginBottom: 7 }}>Citizen reports from this home</div>
        {d.complaints.length === 0 ? <p className="sm muted">None.</p> : (
          <div className="stack" style={{ gap: 7 }}>{d.complaints.map((c: any) => (
            <div key={c.id} className="card pad sm"><div className="row between"><b>{CAT_LABEL[c.category]}</b><StatusPill status={c.status} /></div>
              {c.description && <p style={{ marginTop: 3 }}>"{c.description}"</p>}<div className="muted xs">{c.id} · {dt(c.created_at)}</div></div>))}</div>)}
      </div>
    </Drawer>
  );
}

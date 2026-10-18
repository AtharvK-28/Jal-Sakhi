import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  AlertTriangle, BadgeCheck, BellRing, Building2, Camera, CheckCircle2, ClipboardCheck, Clock, FlaskConical, Hammer, Lock, MapPin, MessageSquareText, NotebookPen,
  Play, RotateCcw, ShieldAlert, Siren, Timer, TrendingUp, UserCheck, Users, Wrench, XCircle,
} from "lucide-react";
import { api, getSession, resolveUrl } from "../lib/api";
import { useLive, usePoll } from "../lib/live";
import { Drawer, Empty, Loader, OriginPill, SevPill, StatusPill, toast } from "../components/ui";
import { CAT_LABEL, INC_STATUS, LANG_NAME, dt, dur, hhmm, minsBetween, n1 } from "../lib/format";

const OVERRIDE_ROLES = ["vwsc", "block", "district", "state", "admin"];
const LEVELS = ["", "L1 · Village (VWSC / Nal Jal Mitra)", "L2 · Block engineer", "L3 · District engineer"];

export function Incidents() {
  const { snap, clock } = useLive();
  const { id } = useParams();
  const nav = useNavigate();
  const [tab, setTab] = useState<"open" | "all">("open");
  const { data: all } = usePoll<any[]>(tab === "all" ? "/api/incidents" : null, 5000, [tab]);
  const names = useMemo(() => Object.fromEntries((snap?.summary || []).map((v: any) => [v.id, v.name])), [snap]);
  const rows: any[] = tab === "open" ? snap?.incidents || [] : all || [];
  const multi = (snap?.summary || []).length > 1;

  return (
    <div className="page">
      <div className="page-h">
        <div><h1>Alerts & incidents</h1><p>One queue for sensor alerts, AI warnings and citizen reports. Each incident names what was observed and what to check, is tracked against an SLA, and closes only with proof that service is back.</p></div>
        <div className="seg"><button className={tab === "open" ? "on" : ""} onClick={() => setTab("open")}>Open ({snap?.incidents?.length ?? 0})</button><button className={tab === "all" ? "on" : ""} onClick={() => setTab("all")}>All incl. closed</button></div>
      </div>
      <div className="card tbl-wrap">
        {!snap ? <Loader /> : rows.length === 0 ? <Empty>No {tab === "open" ? "open " : ""}incidents in your jurisdiction.</Empty> : (
          <table className="tbl">
            <thead><tr><th title="Maintenance priority score">Priority</th><th>Incident</th><th>Severity</th><th>Status</th><th>Detected by</th><th>Impact</th><th>Assigned</th><th>SLA to resolve</th></tr></thead>
            <tbody>
              {rows.map((i) => {
                const left = minsBetween(clock?.iso, i.sla_resolve_due);
                return (
                  <tr key={i.id} className="click" onClick={() => nav(`/app/incidents/${i.id}`)}>
                    <td><b className="num" style={{ fontSize: 16 }}>{Math.round(i.priority)}</b></td>
                    <td style={{ maxWidth: 420 }}><b>{i.title}</b><div className="xs muted">{i.id}{multi ? ` · ${names[i.village_id] || i.village_id}` : ""} · since {dt(i.first_seen)}{i.detection_delay_min != null ? ` · detected in ${n1(i.detection_delay_min, 0)} min` : ""}</div></td>
                    <td><SevPill sev={i.severity} /></td>
                    <td><StatusPill status={i.status} />{i.escalation_level > 1 && <div className="xs" style={{ color: "var(--serious)", marginTop: 3, fontWeight: 650 }}>escalated L{i.escalation_level}</div>}</td>
                    <td><OriginPill origin={i.origin} /></td>
                    <td className="sm"><span className="row" style={{ gap: 5 }}><Users size={13} className="muted" />{i.affected_count}</span>{i.report_count > 0 && <span className="row" style={{ gap: 5, color: "var(--serious)" }}><MessageSquareText size={13} />{i.report_count}</span>}</td>
                    <td className="sm">{i.assigned_to || <span className="muted">unassigned</span>}</td>
                    <td className="sm num">{i.status === "closed" ? <span className="muted">closed</span> : left === null ? "–" : left < 0 ? <span style={{ color: "var(--crit)", fontWeight: 700 }}>overdue {dur(left)}</span> : dur(left)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
      {id && <IncidentDrawer id={id} onClose={() => nav("/app/incidents")} />}
    </div>
  );
}

function IncidentDrawer({ id, onClose }: { id: string; onClose: () => void }) {
  const { clock, refresh } = useLive();
  const role = getSession()!.user.role;
  const { data: d, error, reload } = usePoll<any>(`/api/incidents/${id}`, 2000);
  const [mode, setMode] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [assignee, setAssignee] = useState("");
  const [busy, setBusy] = useState(false);
  const [ftk, setFtk] = useState<any>({ turbidity_ntu: "", chlorine_mgl: "", ph: "", h2s_positive: false, sample_point: "Tank outlet" });
  useEffect(() => { setMode(null); setText(""); }, [id]);
  useEffect(() => { if (d && !assignee) setAssignee(d.suggested_assignee); }, [d, assignee]);
  if (error) return <Drawer title="Incident" onClose={onClose}><Empty icon={<AlertTriangle />}>{error}</Empty></Drawer>;
  if (!d) return <Drawer title="Incident" onClose={onClose}><Loader /></Drawer>;

  const act = async (action: string, extra: any = {}) => {
    setBusy(true);
    try {
      await api(`/api/incidents/${id}`, { method: "PATCH", body: { action, ...extra } });
      toast({ acknowledge: "Acknowledged", assign: "Assigned", start: "Work started", note: "Note added", repair: "Repair recorded. Waiting for telemetry and citizens to confirm.", close: "Incident closed", reopen: "Reopened", escalate: "Escalated" }[action] || "Done");
      setMode(null); setText(""); reload(); refresh();
    } catch (e: any) { toast(e.message, true); }
    setBusy(false);
  };
  const sampleFtk = async () => {
    try { const s = await api(`/api/quality/ftk-sample?village=${d.village_id}`); setFtk({ ...ftk, ...s.params }); } catch (e: any) { toast(e.message, true); }
  };
  const submitFtk = async () => {
    setBusy(true);
    try {
      const params: any = { h2s_positive: !!ftk.h2s_positive };
      for (const k of ["turbidity_ntu", "chlorine_mgl", "ph"]) if (ftk[k] !== "" && ftk[k] !== null) params[k] = Number(ftk[k]);
      const r = await api("/api/quality/tests", { body: { village_id: d.village_id, sample_point: ftk.sample_point, kind: "FTK", incident_id: d.id, params } });
      toast(r.result === "pass" ? `FTK test ${r.id}: PASS` : `FTK test ${r.id}: FAIL. Lab confirmation requested.`, r.result !== "pass");
      setMode(null); reload(); refresh();
    } catch (e: any) { toast(e.message, true); }
    setBusy(false);
  };

  const st = d.status;
  const ackLeft = minsBetween(clock?.iso, d.sla_ack_due), resLeft = minsBetween(clock?.iso, d.sla_resolve_due);
  const ev = d.evidence || {};
  const evRows = Object.entries(ev).filter(([k, v]) => !["devices", "segment", "tests", "reporting_households", "last_seen", "readings", "limit", "citizen_leak_reports"].includes(k) && v !== null && typeof v !== "object");
  const isQuality = d.category === "quality" || (d.cond_key || "").includes("quality");
  const needsFtk = isQuality || d.type === "SUSPECTED_LEAK"; // a repaired leak is tested too: an empty, broken pipe can draw contamination in
  const canOverride = OVERRIDE_ROLES.includes(role);

  return (
    <Drawer wide onClose={onClose}
      title={<span>{d.title}</span>}
      sub={<span className="row wrap" style={{ gap: 6 }}><span className="mono">{d.id}</span><SevPill sev={d.severity} /><StatusPill status={st} /><OriginPill origin={d.origin} /><span className="pill"><TrendingUp />{LEVELS[d.escalation_level]}</span><span className="muted">priority {Math.round(d.priority)}</span></span>}
      footer={st === "closed" ? <button className="btn ghost" disabled={busy} onClick={() => act("reopen", { note: "Reopened by staff" })}><RotateCcw />Reopen</button> : <>
        {st === "open" && <button className="btn" disabled={busy} onClick={() => act("acknowledge")}><UserCheck />Acknowledge</button>}
        {(st === "open" || st === "acknowledged") && <button className="btn ghost" disabled={busy} onClick={() => setMode("assign")}><Users />Assign</button>}
        {(st === "open" || st === "acknowledged") && <button className="btn ghost" disabled={busy} onClick={() => act("start")}><Play />Start work</button>}
        {needsFtk && <button className="btn ghost" disabled={busy} onClick={() => { if (d.type === "SUSPECTED_LEAK") setFtk({ ...ftk, sample_point: "Tap downstream of the repair" }); setMode("ftk"); }}><FlaskConical />Record FTK test</button>}
        {["open", "acknowledged", "in_progress"].includes(st) && <button className="btn good" disabled={busy} onClick={() => setMode("repair")}><Wrench />Record repair</button>}
        {st === "resolved_pending_verification" && <button className="btn good" disabled={busy || !d.closure.ok} title={d.closure.ok ? "" : `Needs: ${d.closure.missing}`} onClick={() => act("close")}><BadgeCheck />Verify & close</button>}
        {st === "resolved_pending_verification" && <button className="btn ghost" disabled={busy} onClick={() => act("reopen", { note: "Fix not effective" })}><RotateCcw />Reopen</button>}
        <button className="btn ghost" disabled={busy} onClick={() => setMode("note")}><NotebookPen />Add note</button>
        {d.escalation_level < 3 && <button className="btn ghost" disabled={busy} onClick={() => act("escalate")}><TrendingUp />Escalate</button>}
        {!d.closure.ok && <button className="btn ghost" disabled={busy} onClick={() => setMode("override")} title={canOverride ? "" : "Your role cannot override"}><Lock />Close with override</button>}
      </>}>

      {mode && (
        <div className="card pad" style={{ borderColor: "var(--brand)", boxShadow: "0 0 0 3px color-mix(in srgb, var(--brand) 16%, transparent)" }}>
          {mode === "assign" && <>
            <label className="f">Assign to</label>
            <select className="select" value={assignee} onChange={(e) => setAssignee(e.target.value)}>{d.assignee_options.map((o: string) => <option key={o}>{o}</option>)}</select>
            <div className="xs muted" style={{ margin: "5px 0 10px" }}>Suggested for this incident type: {d.suggested_assignee}</div>
            <div className="row"><button className="btn sm" disabled={busy} onClick={() => act("assign", { assignee })}>Assign</button><button className="btn ghost sm" onClick={() => setMode(null)}>Cancel</button></div>
          </>}
          {(mode === "note" || mode === "repair" || mode === "override") && <>
            <label className="f">{mode === "note" ? "Inspection note" : mode === "repair" ? "What was repaired or done?" : "Reason for closing without verification evidence"}</label>
            <textarea className="input" rows={3} autoFocus value={text} onChange={(e) => setText(e.target.value)}
              placeholder={mode === "repair" ? "e.g. Replaced the cracked 63 mm coupling between HH-024 and HH-031; line flushed" : mode === "override" ? "e.g. Duplicate of a work order already closed on paper" : "e.g. Valve at the lane head checked, fully open"} />
            {mode === "repair" && <div className="note demo" style={{ margin: "8px 0" }}><Hammer /><span><b>DEMO:</b> recording the repair also clears the simulated fault, standing in for the field fix. The incident then waits for telemetry and citizens to confirm.</span></div>}
            {mode === "override" && <div className="note warn" style={{ margin: "8px 0" }}><ShieldAlert /><span>An override is written to the tamper-evident audit log with your name and reason. {canOverride ? "" : "Your role (operator) is not permitted to override; this will be refused."}</span></div>}
            <div className="row" style={{ marginTop: 8 }}>
              <button className={`btn sm ${mode === "override" ? "danger" : ""}`} disabled={busy || !text.trim()} onClick={() => act(mode === "override" ? "close" : mode, { note: text, override: mode === "override" })}>{mode === "note" ? "Save note" : mode === "repair" ? "Record repair" : "Close with override"}</button>
              <button className="btn ghost sm" onClick={() => setMode(null)}>Cancel</button>
            </div>
          </>}
          {mode === "ftk" && <>
            <div className="row between"><b className="row"><FlaskConical size={16} color="var(--brand)" />Field Test Kit result</b><button className="btn soft sm" onClick={sampleFtk}>DEMO: take a simulated sample</button></div>
            <div className="grid g4" style={{ marginTop: 10 }}>
              <div><label className="f">Sample point</label><input className="input" value={ftk.sample_point} onChange={(e) => setFtk({ ...ftk, sample_point: e.target.value })} /></div>
              <div><label className="f">Turbidity (NTU)</label><input className="input" inputMode="decimal" value={ftk.turbidity_ntu} onChange={(e) => setFtk({ ...ftk, turbidity_ntu: e.target.value })} /></div>
              <div><label className="f">Residual Cl (mg/L)</label><input className="input" inputMode="decimal" value={ftk.chlorine_mgl} onChange={(e) => setFtk({ ...ftk, chlorine_mgl: e.target.value })} /></div>
              <div><label className="f">pH</label><input className="input" inputMode="decimal" value={ftk.ph} onChange={(e) => setFtk({ ...ftk, ph: e.target.value })} /></div>
            </div>
            <label className="row sm" style={{ margin: "10px 0", cursor: "pointer" }}><input type="checkbox" checked={!!ftk.h2s_positive} onChange={(e) => setFtk({ ...ftk, h2s_positive: e.target.checked })} />H2S vial turned black (possible bacteriological contamination)</label>
            <div className="row"><button className="btn sm" disabled={busy} onClick={submitFtk}>Save test result</button><button className="btn ghost sm" onClick={() => setMode(null)}>Cancel</button></div>
          </>}
        </div>
      )}

      <div className="card pad">
        <div className="upper muted">What was observed</div>
        <p style={{ marginTop: 5, fontSize: 14 }}>{d.summary}</p>
        <div className="grid g2" style={{ marginTop: 14 }}>
          <div><div className="upper muted">Suspected cause <span className="tag" style={{ marginLeft: 4 }}>not confirmed</span></div><p className="sm" style={{ marginTop: 4 }}>{d.suspected_cause}</p></div>
          <div><div className="upper muted">Suggested inspection</div><p className="sm" style={{ marginTop: 4 }}>{d.suggested_action}</p></div>
        </div>
        <div className="row wrap" style={{ marginTop: 14, gap: 7 }}>
          <span className="pill"><Users />{d.affected_count} households affected</span>
          {d.report_count > 0 && <span className="pill high"><MessageSquareText />{d.report_count} citizen report{d.report_count > 1 ? "s" : ""}</span>}
          {ev.segment && <span className="pill info"><MapPin />between {ev.segment.from} and {ev.segment.to}</span>}
          {d.sites.map((s: any) => <span key={s.id} className="pill ai"><Building2 />{s.name}</span>)}
          <span className="pill" title="How sure the system is about this classification">confidence {Math.round((d.confidence || 0) * 100)}%</span>
          {d.detection_delay_min != null && <span className="pill demo" title="Demo metric: minutes between the simulated fault being injected and this incident being raised"><Timer />detected in {n1(d.detection_delay_min, 0)} min</span>}
        </div>
      </div>

      <div className="grid g2">
        <div className="card pad">
          <div className="upper muted" style={{ marginBottom: 8 }}>Service-level clock</div>
          {[["Acknowledge", d.acknowledged_at, ackLeft, d.sla_ack_due], ["Resolve", d.closed_at || (st === "resolved_pending_verification" ? d.resolved_at : null), resLeft, d.sla_resolve_due]].map(([l, doneAt, left, due]: any) => (
            <div key={l} className="row between sm" style={{ padding: "5px 0" }}>
              <span className="row"><Clock size={14} className="muted" />{l} by {hhmm(due)}</span>
              {doneAt ? <span className={`pill ${doneAt <= due ? "good" : "critical"}`}>{doneAt <= due ? <CheckCircle2 /> : <XCircle />}done {hhmm(doneAt)}</span>
                : left !== null && left < 0 ? <span className="pill critical"><AlertTriangle />overdue {dur(left)}</span> : <span className="pill info"><Timer />{dur(left)} left</span>}
            </div>
          ))}
          <div className="xs muted" style={{ marginTop: 6 }}>Missing a deadline escalates automatically: village → block → district.</div>
          <div className="sm" style={{ marginTop: 10 }}><b>Assigned:</b> {d.assigned_to || <span className="muted">nobody yet</span>}</div>
        </div>
        <div className="card pad">
          <div className="upper muted" style={{ marginBottom: 8 }}>Why this priority ({Math.round(d.priority)} / 100)</div>
          {Object.entries(d.priority_breakdown || {}).map(([k, v]: any) => (
            <div key={k} className="row sm" style={{ padding: "3px 0" }}><span style={{ width: 132 }} className="ink2">{k.replace(/_/g, " ")}</span><div className="bar grow" style={{ height: 6 }}><i style={{ width: `${Math.min(100, (v / 40) * 100)}%` }} /></div><b className="num" style={{ width: 30, textAlign: "right" }}>{v}</b></div>
          ))}
        </div>
      </div>

      <div className="card pad">
        <div className="row between"><div className="upper muted">Closure checklist: proof that service is back</div>{d.closure.ok ? <span className="pill good"><BadgeCheck />ready to close</span> : <span className="pill medium"><Clock />waiting</span>}</div>
        <div className="stack" style={{ gap: 6, marginTop: 9 }}>
          <div className="row sm">{d.repair_note ? <CheckCircle2 size={16} color="var(--good)" /> : <XCircle size={16} color="var(--muted)" />}<span>Repair or action recorded{d.repair_note ? `: "${d.repair_note}"` : ""}</span></div>
          <div className="row sm">{d.recovered_at ? <CheckCircle2 size={16} color="var(--good)" /> : <XCircle size={16} color="var(--muted)" />}<span>Telemetry shows the condition cleared{d.recovered_at ? ` at ${hhmm(d.recovered_at)}` : ""}</span></div>
          <div className="row sm">{ev.citizen_confirmed ? <CheckCircle2 size={16} color="var(--good)" /> : <XCircle size={16} color="var(--muted)" />}<span>Citizens who reported confirm it is fixed ({ev.citizen_confirmed || 0} yes{ev.citizen_disputed ? `, ${ev.citizen_disputed} say not fixed` : ""})</span></div>
          {isQuality && <div className="row sm">{ev.ftk_pass ? <CheckCircle2 size={16} color="var(--good)" /> : <XCircle size={16} color={ev.ftk_pass === false ? "var(--crit)" : "var(--muted)"} />}<span>FTK re-test {ev.ftk_pass ? "passed" : ev.ftk_pass === false ? "FAILED: lab confirmation requested" : "not yet recorded"}</span></div>}
        </div>
        {!d.closure.ok && st !== "closed" && <p className="xs muted" style={{ marginTop: 8 }}>Still needed: {d.closure.missing}.</p>}
        {d.closure_reason && <p className="sm" style={{ marginTop: 8 }}><b>Closed:</b> {d.closure_reason}</p>}
      </div>

      <RepairPhotos d={d} onAdded={reload} />

      {d.deliveries?.length > 0 && (
        <div className="card pad">
          <div className="row between"><div className="upper muted">Phone alerts sent</div><span className="pill info"><BellRing />{d.deliveries.length}</span></div>
          <div className="stack" style={{ gap: 6, marginTop: 9 }}>
            {d.deliveries.map((x: any) => (
              <div key={x.id} className="row between sm" style={{ gap: 8 }}>
                <span><b>{x.name}</b> <span className="xs muted">· {x.channel} {x.address}{x.kind && x.kind.startsWith("escalation") ? " · escalation" : ""}</span></span>
                <span className={`pill ${x.status === "sent" ? "good" : x.status === "sandbox" ? "demo" : x.status === "failed" ? "critical" : "medium"}`} title={x.last_error || ""}>{x.status === "sent" ? "delivered" : x.status}</span>
              </div>
            ))}
          </div>
          {d.deliveries.some((x: any) => x.status === "sandbox") && <p className="xs muted" style={{ marginTop: 8 }}>Sandbox: routed and written, not sent (no channel configured, or a placeholder DEMO number).</p>}
        </div>
      )}

      {evRows.length > 0 && (
        <div className="card pad">
          <div className="upper muted" style={{ marginBottom: 8 }}>Evidence snapshot</div>
          <div className="grid g3" style={{ gap: "8px 16px" }}>
            {evRows.map(([k, v]: any) => <div key={k}><div className="xs muted">{k.replace(/_/g, " ")}</div><b className="num sm">{typeof v === "number" ? n1(v, Math.abs(v) < 10 ? 2 : 0) : String(v)}</b></div>)}
          </div>
          {ev.readings && <div className="sm" style={{ marginTop: 10 }}><span className="muted">Sensor readings: </span>{Object.entries(ev.readings).map(([k, v]: any) => `${k} = ${v}`).join(" · ")} <span className="muted">(reference {ev.reference})</span></div>}
          {ev.devices && <div className="xs muted" style={{ marginTop: 8 }}>Devices used: <span className="mono">{ev.devices.join(", ")}</span></div>}
        </div>
      )}

      {d.complaints.length > 0 && (
        <div>
          <div className="upper muted" style={{ marginBottom: 7 }}>Linked citizen reports ({d.complaints.length})</div>
          <div className="stack" style={{ gap: 7 }}>
            {d.complaints.map((c: any) => (
              <div key={c.id} className="card pad sm row" style={{ alignItems: "flex-start" }}>
                {c.photo && <img src={resolveUrl(c.photo)} alt="citizen photo" style={{ width: 56, height: 56, borderRadius: 10, objectFit: "cover" }} />}
                <div className="grow">
                  <div className="row between wrap"><b>{CAT_LABEL[c.category]} · {c.household_id.split("-").slice(1).join("-")}</b>
                    <span className="row" style={{ gap: 5 }}><span className="tag">{c.channel}</span><span className="tag">{LANG_NAME[c.language] || c.language}</span>{c.source === "simulated-citizen" && <span className="tag">simulated</span>}</span></div>
                  {c.description && <p style={{ marginTop: 3 }}>"{c.description}"</p>}
                  <div className="row between xs muted" style={{ marginTop: 3 }}><span>{c.id} · {dt(c.created_at)}</span>
                    {c.citizen_confirmed === 1 ? <span style={{ color: "var(--good)", fontWeight: 650 }}>confirmed fixed</span> : c.citizen_confirmed === 0 ? <span style={{ color: "var(--crit)", fontWeight: 650 }}>says not fixed</span> : <span>not yet confirmed</span>}</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      <div>
        <div className="upper muted" style={{ marginBottom: 9 }}>Timeline & audit trail</div>
        <div className="tl">
          {d.events.map((e: any) => (
            <div key={e.id} className={`ev ${e.role === "system" ? "sys" : e.role === "citizen" ? "cit" : ""} ${e.to_status === "closed" || e.kind === "recovery" ? "ok" : ""}`}>
              <div className="when">{dt(e.ts)} · {e.actor}{e.role !== "system" && e.role !== e.actor ? ` (${e.role})` : ""}</div>
              <div className="sm">{e.kind === "status" && e.to_status ? <b>{INC_STATUS[e.to_status]}: </b> : e.kind === "created" ? <b>Detected: </b> : e.kind === "recovery" ? <b>Recovery: </b> : null}{e.note}</div>
            </div>
          ))}
        </div>
      </div>
    </Drawer>
  );
}

/** A photo of the work, stamped with when and where it was taken: closure evidence a desk cannot fake. */
function RepairPhotos({ d, onAdded }: { d: any; onAdded: () => void }) {
  const shots: any[] = d.evidence?.repair_photos || [];
  const [busy, setBusy] = useState(false);
  const add = async (f: File | null) => {
    if (!f) return;
    setBusy(true);
    const pos = await new Promise<GeolocationPosition | null>((res) => navigator.geolocation ? navigator.geolocation.getCurrentPosition(res, () => res(null), { timeout: 5000 }) : res(null));
    const fd = new FormData();
    fd.append("photo", f);
    if (pos) { fd.append("lat", String(pos.coords.latitude)); fd.append("lon", String(pos.coords.longitude)); }
    try { await api(`/api/incidents/${d.id}/photo`, { form: fd }); toast(pos ? "Repair photo added with its location" : "Repair photo added (the device gave no location)"); onAdded(); } catch (e: any) { toast(e.message, true); }
    setBusy(false);
  };
  if (d.status === "closed" && !shots.length) return null;
  return (
    <div className="card pad">
      <div className="row between"><div className="upper muted">Proof of repair</div>
        {d.status !== "closed" && <label className="btn ghost sm" style={{ cursor: "pointer" }}><Camera />{busy ? "Uploading…" : "Add a photo of the work"}
          <input type="file" accept="image/*" capture="environment" hidden onChange={(e) => add(e.target.files?.[0] || null)} /></label>}</div>
      {shots.length === 0 ? <p className="xs muted" style={{ marginTop: 6 }}>A photo of the repaired pipe or valve, taken on site, is stored with the time and the phone's location as closure evidence.</p> : (
        <div className="row wrap" style={{ gap: 10, marginTop: 9 }}>{shots.map((s, i) => (
          <a key={i} href={resolveUrl(s.url)} target="_blank" rel="noreferrer" className="sm" style={{ color: "var(--ink)" }}>
            <img src={resolveUrl(s.url)} alt="repair" style={{ width: 96, height: 72, objectFit: "cover", borderRadius: 10, display: "block" }} />
            <span className="xs muted">{dt(s.ts)}{s.lat != null ? ` · ${s.lat.toFixed(4)}, ${s.lon.toFixed(4)}` : " · no location"}</span></a>))}</div>)}
    </div>
  );
}

export const _icons = { Siren, ClipboardCheck };

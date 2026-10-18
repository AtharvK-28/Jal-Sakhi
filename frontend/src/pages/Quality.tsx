import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { AlertTriangle, CheckCircle2, Clock, FlaskConical, ListChecks, Microscope, RotateCcw, ShieldQuestion, Siren, Sparkles, TestTubeDiagonal, X, XCircle } from "lucide-react";
import { api } from "../lib/api";
import { useLive, usePoll } from "../lib/live";
import { Empty, Loader, SevPill, StatusPill, toast } from "../components/ui";
import { LineChart } from "../components/charts";
import { VillagePicker } from "../components/Shell";
import { dt, fromMinute, n0, n1 } from "../lib/format";

const PARAMS = [
  { k: "turbidity_ntu", label: "Turbidity", unit: "NTU", d: 2, max: 12, good: (v: number) => v <= 1, ok: (v: number) => v <= 5, ref: "acceptable 1 · permissible 5" },
  { k: "chlorine_mgl", label: "Residual chlorine", unit: "mg/L", d: 2, max: 1.2, good: (v: number) => v >= 0.2 && v <= 1, ok: (v: number) => v >= 0.2, ref: "minimum 0.2 · maximum 1.0" },
  { k: "ph", label: "pH", unit: "", d: 2, max: 14, good: (v: number) => v >= 6.5 && v <= 8.5, ok: (v: number) => v >= 6.5 && v <= 8.5, ref: "6.5 to 8.5" },
  { k: "tds_mgl", label: "TDS", unit: "mg/L", d: 0, max: 2000, good: (v: number) => v <= 500, ok: (v: number) => v <= 2000, ref: "acceptable 500 · permissible 2000" },
];

const REASON: Record<string, (r: any) => string> = {
  alert: (r) => `quality alert ${r.incident} open`, leak: () => "leak or repair on this lane", pressure: () => "pressure loss or supply cut today",
  chlorine: (r) => `chlorine ${r.v} mg/L (${r.basis})`, turbidity: (r) => `turbidity ${r.v} NTU at the tank`, reports: (r) => `${r.n} dirty-water report(s)`,
  sites: (r) => r.s, intermittent: () => "intermittent supply", stale: (r) => `not tested for ${r.n} days`, never: () => "not tested yet",
};

function limitText(p: any): string {
  if (!p) return "–";
  const u = p.unit ? ` ${p.unit}` : "";
  if (p.max != null) return `${p.min} to ${p.max}`;
  if (p.acceptable == null) return `at least ${p.min}${u}`;
  return p.acceptable === p.permissible ? `up to ${p.acceptable}${u}` : `up to ${p.acceptable}${u} (permissible ${p.permissible})`;
}
const VERDICT: Record<string, [string, string]> = { ok: ["good", "within limit"], caution: ["medium", "above acceptable"], fail: ["critical", "outside limit"], pending: ["info", "waiting"] };

/** The result of a test, why it came out that way, what the system already did, and what to do next. */
function TestResult({ r, params, onClose, onOpen, onRetest, onH2s }: { r: any; params: any[]; onClose: () => void; onOpen: () => void; onRetest: () => void; onH2s: (positive: boolean) => void }) {
  const fail = r.result === "fail", pend = r.result === "pending";
  const by = Object.fromEntries(params.map((p: any) => [p.key, p]));
  const f = r.follow_up || {};
  const nFail = (r.checks || []).filter((c: any) => c.status === "fail").length;
  const tone = fail ? "var(--crit)" : pend ? "var(--warn)" : "var(--good)";
  const done: [boolean, string][] = [
    [!!f.lab_referral, "Laboratory confirmation requested for this sample."],
    [!!f.incident && f.incident_opened, `Incident ${f.incident} opened for ${f.scope || f.advised || "this supply"}, assigned to the FTK team and tracked against its deadline.`],
    [!!f.incident && !f.incident_opened, `Recorded as evidence on incident ${f.incident}${fail ? "" : r.result === "pass" ? ": counts towards closing it" : ""}.`],
    [f.advisory === "boil", `Boil-water advisory sent to ${f.advised_households} households on ${f.advised}, in their language, in the app and on linked phones; the operator and Pani Samiti were alerted.`],
    [f.advisory === "alternate_source", `${f.advised_households} households on ${f.advised} told to drink and cook with water from another safe source (boiling does not remove ${(f.failed || []).join(", ").toLowerCase()}), in their language, in the app and on linked phones.`],
    [fail && !f.advisory, `No household advisory: ${(f.failed || []).join(", ").toLowerCase()} is not an immediate health risk. The operator was alerted to fix it.`],
    [true, "Result queued for WQMIS with the scheme's Sujal Gaon ID."],
  ];
  return (
    <div className="card" style={{ marginTop: 16, borderColor: tone, boxShadow: `inset 4px 0 0 ${tone}, var(--shadow)` }}>
      <div className="card-h">
        <h3 style={{ color: tone }}>{fail ? <XCircle /> : pend ? <Clock /> : <CheckCircle2 />}
          {fail ? `Outside the limits: ${nFail} parameter${nFail === 1 ? "" : "s"} failed` : pend ? "Recorded: waiting for the H2S vial" : "Within the drinking-water limits"}</h3>
        <button className="btn ghost icon sm" onClick={onClose} aria-label="Close"><X /></button>
      </div>
      <div className="card-b stack" style={{ gap: 14 }}>
        <div className="sm muted">{r.id} · {r.kind === "FTK" ? "Field test kit" : "Laboratory"} · {r.sample_point} · {dt(r.ts)} · judged against IS 10500:2012</div>
        <div className="tbl-wrap" style={{ border: "1px solid var(--line)" }}>
          <table className="tbl">
            <thead><tr><th>Parameter</th><th>Reading</th><th>Limit</th><th>Result</th></tr></thead>
            <tbody>{(r.checks || []).map((c: any) => (
              <tr key={c.key} style={c.status === "fail" ? { background: "var(--crit-bg)" } : undefined}>
                <td><b>{c.label}</b></td>
                <td className="num">{c.key === "h2s_positive" ? (c.value === null ? "vial set up" : c.value ? "turned black" : "stayed clear") : `${c.value}${by[c.key]?.unit ? ` ${by[c.key].unit}` : ""}`}</td>
                <td className="sm muted">{c.key === "h2s_positive" ? "must stay clear" : limitText(by[c.key])}</td>
                <td><span className={`pill ${VERDICT[c.status][0]}`}>{VERDICT[c.status][1]}</span></td>
              </tr>))}</tbody>
          </table>
        </div>

        <div>
          <div className="upper muted" style={{ marginBottom: 7 }}>Done automatically</div>
          <div className="stack" style={{ gap: 6 }}>{done.filter(([on]) => on).map(([, text]) => <div key={text} className="row sm" style={{ alignItems: "flex-start" }}><CheckCircle2 size={16} color="var(--good)" style={{ flex: "none", marginTop: 1 }} />{text}</div>)}</div>
        </div>

        {(r.advice?.length > 0 || pend) && <div>
          <div className="upper muted" style={{ marginBottom: 7 }}>What to do next</div>
          <div className="stack" style={{ gap: 10 }}>
            {pend && <div className="note warn"><Clock /><span>Read the H2S vial 24 to 48 hours after setting it up. A black vial means possible faecal contamination.
              <span className="row" style={{ marginTop: 8, gap: 8 }}><button className="btn sm" onClick={() => onH2s(false)}>Stayed clear</button><button className="btn sm" style={{ background: "#1d1d1d" }} onClick={() => onH2s(true)}>Turned black</button></span></span></div>}
            {(r.advice || []).map((a: any) => (
              <div key={a.key} className={`note ${a.status === "fail" ? "warn" : ""}`}><AlertTriangle /><div><b>{a.title}</b>
                <ol style={{ margin: "5px 0 0", paddingLeft: 18, lineHeight: 1.55 }}>{a.steps.map((x: string) => <li key={x}>{x}</li>)}</ol></div></div>))}
          </div>
        </div>}

        <div className="row wrap" style={{ gap: 8 }}>
          {f.incident && <button className="btn sm" onClick={onOpen}><Siren />Open incident {f.incident}</button>}
          {fail && <button className="btn ghost sm" onClick={onRetest}><RotateCcw />Re-test this point after the fix</button>}
          {fail && <span className="xs muted row" style={{ gap: 5 }}><ListChecks size={13} />The incident closes on a passing re-test or a laboratory result.</span>}
        </div>
      </div>
    </div>
  );
}

export function Quality() {
  const { village, focus } = useLive();
  const nav = useNavigate();
  const { data: q, reload } = usePoll<any>(`/api/quality?village=${village}`, 3000);
  const { data: tr } = usePoll<any>(`/api/villages/${village}/trends?limit=160`, 5000);
  const [form, setForm] = useState<any>({ sample_point: "Tank outlet", kind: "FTK", h2s_positive: false, incident_id: "" });
  const { data: plan } = usePoll<any>(`/api/quality/plan?village=${village}`, 6000);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<any>(null);
  if (!q) return <div className="page"><Loader /></div>;

  const sample = async () => {
    try { const s = await api(`/api/quality/ftk-sample?village=${village}&point=${encodeURIComponent(form.sample_point)}`); setForm({ ...form, ...s.params }); } catch (e: any) { toast(e.message, true); }
  };
  const pull = async () => {
    try {
      const r = await api(`/api/quality/wqmis/pull?village=${village}`, { method: "POST" });
      toast(r.imported.length ? `${r.imported.length} laboratory result(s) received from WQMIS (sandbox)` : r.note);
      reload();
    } catch (e: any) { toast(e.message, true); }
  };
  const save = async () => {
    setBusy(true);
    try {
      const params: any = { h2s_positive: !!form.h2s_positive };
      for (const k of [...q.ftk_params.map((p: any) => p.key), "turbidity_ntu", "tds_mgl"]) if (form[k] !== "" && form[k] != null) params[k] = Number(form[k]);
      const r = await api("/api/quality/tests", { body: { village_id: village, sample_point: form.sample_point, kind: form.kind, params, incident_id: form.incident_id || null } });
      setResult(r);
      toast(r.result === "pass" ? `${r.id}: within limits` : r.result === "pending" ? `${r.id}: waiting for the H2S vial` : `${r.id}: outside the limits, see below`, r.result === "fail");
      reload();
    } catch (e: any) { toast(e.message, true); }
    setBusy(false);
  };

  return (
    <div className="page">
      <div className="page-h">
        <div><h1>Water quality · {focus?.name}</h1><p>Continuous screening sensors raise the flag; the trained FTK testers and the laboratory give the answer. The system tracks every flag until a test closes it.</p></div>
        <VillagePicker />
      </div>
      <div className="note warn" style={{ marginBottom: 16 }}><ShieldQuestion /><span><b>Read this first.</b> {q.caveat} Reference values: {q.reference}.</span></div>

      <div className="grid g2">
        {q.sensors.map((s: any) => (
          <div className="card" key={s.id}>
            <div className="card-h"><h3><FlaskConical />{s.name}</h3>
              <span className={`pill ${s.status === "ok" ? "good" : s.status === "watch" ? "medium" : s.status === "verify" ? "critical" : "s-unknown"}`}>{s.status === "ok" ? "within reference range" : s.status === "watch" ? "above acceptable limit" : s.status === "verify" ? "verification required" : "no recent telemetry"}</span></div>
            <div className="card-b grid g2" style={{ gap: 12 }}>
              {PARAMS.map((p) => {
                const v = s[p.k];
                const state = v == null || !s.fresh ? "unk" : p.good(v) ? "good" : p.ok(v) ? "warn" : "crit";
                return (
                  <div key={p.k} style={{ padding: "10px 12px", borderRadius: 13, background: "var(--surface-2)", border: "1px solid var(--line)" }}>
                    <div className="row between"><span className="sm ink2" style={{ fontWeight: 600 }}>{p.label}</span>
                      {state === "good" ? <CheckCircle2 size={15} color="var(--good)" /> : state === "unk" ? null : <XCircle size={15} color={state === "warn" ? "var(--warn)" : "var(--crit)"} />}</div>
                    <div style={{ fontSize: 22, fontWeight: 750 }} className="num">{s.fresh ? n1(v, p.d) : "–"}<small className="muted" style={{ fontSize: 12 }}> {p.unit}</small></div>
                    <div className="xs muted">{p.ref}</div>
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>

      <div className="grid g2" style={{ marginTop: 16 }}>
        <div className="card"><div className="card-h"><h3>Turbidity (NTU)</h3></div><div className="card-b">
          <LineChart height={180} yMin={0} xFmt={fromMinute} yFmt={(y) => y.toFixed(1)} unit=" NTU"
            series={[{ name: "Tank outlet", color: "var(--s1)", pts: tr?.turbidity || [] }, { name: "Tail end", color: "var(--s2)", pts: tr?.turbidity_tail || [] }]}
            refLines={[{ y: 5, label: "permissible 5 NTU", color: "var(--crit)" }]} /></div></div>
        <div className="card"><div className="card-h"><h3>Residual chlorine (mg/L)</h3></div><div className="card-b">
          <LineChart height={180} yMin={0} yMax={0.8} xFmt={fromMinute} yFmt={(y) => y.toFixed(1)} unit=" mg/L"
            series={[{ name: "Tank outlet", color: "var(--s1)", pts: tr?.chlorine || [] }, { name: "Tail end", color: "var(--s2)", pts: tr?.chlorine_tail || [] }]}
            refLines={[{ y: 0.2, label: "minimum 0.2 mg/L", color: "var(--crit)" }]} /></div></div>
      </div>

      <div className="grid g-main" style={{ marginTop: 16 }}>
        <div className="card">
          <div className="card-h"><h3><TestTubeDiagonal />Record a test (Jal Sakhi FTK team or laboratory)</h3><button className="btn soft sm" onClick={sample}>DEMO: take a simulated sample</button></div>
          <div className="card-b">
            <div className="grid g3">
              <div><label className="f">Sample point</label><select className="select" value={form.sample_point} onChange={(e) => setForm({ ...form, sample_point: e.target.value })}>{q.sample_points.map((p: string) => <option key={p}>{p}</option>)}</select></div>
              <div><label className="f">Test type</label><select className="select" value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })}><option value="FTK">Field Test Kit</option><option value="LAB">Laboratory</option></select></div>
              <div><label className="f">Link to open incident</label><select className="select" value={form.incident_id} onChange={(e) => setForm({ ...form, incident_id: e.target.value })}><option value="">None (routine surveillance)</option>{q.open.map((i: any) => <option key={i.id} value={i.id}>{i.id} · {i.title.slice(0, 40)}</option>)}</select></div>
              {q.ftk_params.map((p: any) => <div key={p.key}><label className="f">{p.label}{p.unit ? ` (${p.unit})` : ""}</label>
                <select className="select" value={form[p.key] ?? ""} onChange={(e) => setForm({ ...form, [p.key]: e.target.value === "" ? null : Number(e.target.value) })}>
                  <option value="">not read</option>{p.steps.map((s: number) => <option key={s} value={s}>{s}</option>)}</select></div>)}
              {form.kind === "LAB" && [["turbidity_ntu", "Turbidity (NTU)"], ["tds_mgl", "TDS (mg/L)"]].map(([k, l]) => <div key={k}><label className="f">{l}</label><input className="input" inputMode="decimal" value={form[k] ?? ""} onChange={(e) => setForm({ ...form, [k]: e.target.value })} /></div>)}
            </div>
            <label className="row sm" style={{ margin: "12px 0", cursor: "pointer" }}><input type="checkbox" checked={!!form.h2s_positive} onChange={(e) => setForm({ ...form, h2s_positive: e.target.checked })} />H2S vial turned black within 24 to 48 h (possible bacteriological contamination)</label>
            <button className="btn" disabled={busy} onClick={save}><Microscope />Save and queue for WQMIS sync</button>
            {result && <TestResult r={result} params={q.ftk_params} onClose={() => setResult(null)} onOpen={() => nav(`/app/incidents/${result.incident_id}`)}
              onRetest={() => { setForm({ sample_point: result.sample_point, kind: "FTK", h2s_positive: false, incident_id: result.incident_id || "" }); setResult(null); }}
              onH2s={async (positive: boolean) => { try { setResult(await api(`/api/quality/tests/${result.id}/h2s`, { method: "PATCH", body: { positive } })); reload(); } catch (e: any) { toast(e.message, true); } }} />}
          </div>
        </div>
        <div className="stack">
          {plan && <div className="card"><div className="card-h"><h3><Sparkles />Where to test first</h3><a className="btn soft sm" href="/tester" target="_blank" rel="noreferrer">Jal Sakhi app ↗</a></div>
            <div className="card-b stack" style={{ gap: 8 }}>
              {plan.points.slice(0, 4).map((p: any) => (
                <button key={p.name} className="scn" style={{ gridTemplateColumns: "44px 1fr" }} onClick={() => setForm({ ...form, sample_point: p.name })} title="Use this sample point">
                  <span className="ic" style={{ flexDirection: "column", fontWeight: 760, background: p.today ? (p.score >= 50 ? "var(--crit-bg)" : "var(--warn-bg)") : "var(--surface-2)", color: "var(--ink)" }}>{p.score}</span>
                  <span><b>{p.name}</b>{p.today && <span className="pill medium" style={{ marginLeft: 6 }}>today</span>}
                    <span className="desc">{p.reasons.slice(0, 2).map((r: any) => REASON[r.code]?.(r) || r.code).join(" · ")}</span></span>
                </button>))}
              <p className="xs muted">{plan.method}</p>
            </div></div>}
          <div className="card"><div className="card-h"><h3>Open quality concerns</h3></div><div className="card-b">
            {q.open.length === 0 ? <Empty>No open quality concerns.</Empty> : q.open.map((i: any) => (
              <button key={i.id} className="scn" style={{ gridTemplateColumns: "1fr", marginBottom: 8 }} onClick={() => nav(`/app/incidents/${i.id}`)}>
                <span><b>{i.title}</b><span className="row wrap" style={{ gap: 6, marginTop: 5 }}><SevPill sev={i.severity} /><StatusPill status={i.status} /><span className="muted xs">{i.id}</span></span></span></button>))}
          </div></div>
          <div className="card"><div className="card-h"><h3>Test history</h3>
            {q.tests.some((t: any) => t.lab_status === "requested") && <button className="btn soft sm" onClick={pull}><Microscope />DEMO: lab results from WQMIS</button>}</div><div className="card-b">
            {q.tests.length === 0 ? <p className="sm muted">No tests recorded in this session.</p> : q.tests.map((t: any) => (
              <div key={t.id} className="row between sm" style={{ padding: "7px 0", borderBottom: "1px solid var(--line)" }}>
                <div><b>{t.id}</b> · {t.kind} · {t.sample_point}<div className="xs muted">{dt(t.ts)} · {t.tested_by}{t.incident_id ? ` · ${t.incident_id}` : ""} · turbidity {n1(t.params.turbidity_ntu)} · Cl {n1(t.params.chlorine_mgl, 2)}{t.params.tds_mgl != null ? ` · TDS ${n0(t.params.tds_mgl)}` : ""}</div></div>
                <span className={`pill ${t.result === "pass" ? "good" : t.result === "pending" ? "medium" : "critical"}`} title={t.lab_status || ""}>{t.kind === "LAB" ? "lab " : ""}{t.result}{t.lab_status === "requested" ? " · lab requested" : t.lab_status?.startsWith("lab ") ? ` · ${t.lab_status.split(":")[0]}` : ""}</span>
              </div>))}
          </div></div>
        </div>
      </div>
    </div>
  );
}

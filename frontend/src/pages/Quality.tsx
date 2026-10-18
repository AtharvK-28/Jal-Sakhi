import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { CheckCircle2, FlaskConical, Microscope, ShieldQuestion, TestTubeDiagonal, XCircle } from "lucide-react";
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

export function Quality() {
  const { village, focus } = useLive();
  const nav = useNavigate();
  const { data: q, reload } = usePoll<any>(`/api/quality?village=${village}`, 3000);
  const { data: tr } = usePoll<any>(`/api/villages/${village}/trends?limit=160`, 5000);
  const [form, setForm] = useState<any>({ sample_point: "Tank outlet", kind: "FTK", turbidity_ntu: "", chlorine_mgl: "", ph: "", tds_mgl: "", h2s_positive: false, incident_id: "" });
  const [busy, setBusy] = useState(false);
  if (!q) return <div className="page"><Loader /></div>;

  const sample = async () => {
    try { const s = await api(`/api/quality/ftk-sample?village=${village}`); setForm({ ...form, ...s.params }); } catch (e: any) { toast(e.message, true); }
  };
  const save = async () => {
    setBusy(true);
    try {
      const params: any = { h2s_positive: !!form.h2s_positive };
      for (const p of PARAMS) if (form[p.k] !== "" && form[p.k] != null) params[p.k] = Number(form[p.k]);
      const r = await api("/api/quality/tests", { body: { village_id: village, sample_point: form.sample_point, kind: form.kind, params, incident_id: form.incident_id || null } });
      toast(r.result === "pass" ? `${r.id}: PASS, recorded and queued for WQMIS sync` : `${r.id}: FAIL (${r.failed_checks.join("; ")})`, r.result !== "pass");
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
              {PARAMS.map((p) => <div key={p.k}><label className="f">{p.label}{p.unit ? ` (${p.unit})` : ""}</label><input className="input" inputMode="decimal" value={form[p.k]} onChange={(e) => setForm({ ...form, [p.k]: e.target.value })} placeholder={p.ref} /></div>)}
            </div>
            <label className="row sm" style={{ margin: "12px 0", cursor: "pointer" }}><input type="checkbox" checked={!!form.h2s_positive} onChange={(e) => setForm({ ...form, h2s_positive: e.target.checked })} />H2S vial turned black within 24 to 48 h (possible bacteriological contamination)</label>
            <button className="btn" disabled={busy} onClick={save}><Microscope />Save and queue for WQMIS sync</button>
          </div>
        </div>
        <div className="stack">
          <div className="card"><div className="card-h"><h3>Open quality concerns</h3></div><div className="card-b">
            {q.open.length === 0 ? <Empty>No open quality concerns.</Empty> : q.open.map((i: any) => (
              <button key={i.id} className="scn" style={{ gridTemplateColumns: "1fr", marginBottom: 8 }} onClick={() => nav(`/app/incidents/${i.id}`)}>
                <span><b>{i.title}</b><span className="row wrap" style={{ gap: 6, marginTop: 5 }}><SevPill sev={i.severity} /><StatusPill status={i.status} /><span className="muted xs">{i.id}</span></span></span></button>))}
          </div></div>
          <div className="card"><div className="card-h"><h3>Test history</h3></div><div className="card-b">
            {q.tests.length === 0 ? <p className="sm muted">No tests recorded in this session.</p> : q.tests.map((t: any) => (
              <div key={t.id} className="row between sm" style={{ padding: "7px 0", borderBottom: "1px solid var(--line)" }}>
                <div><b>{t.id}</b> · {t.kind} · {t.sample_point}<div className="xs muted">{dt(t.ts)} · {t.tested_by}{t.incident_id ? ` · ${t.incident_id}` : ""} · turbidity {n1(t.params.turbidity_ntu)} · Cl {n1(t.params.chlorine_mgl, 2)}{t.params.tds_mgl != null ? ` · TDS ${n0(t.params.tds_mgl)}` : ""}</div></div>
                <span className={`pill ${t.result === "pass" ? "good" : "critical"}`}>{t.result}{t.lab_status ? " · lab requested" : ""}</span>
              </div>))}
          </div></div>
        </div>
      </div>
    </div>
  );
}

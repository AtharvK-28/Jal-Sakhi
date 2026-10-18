import { useState } from "react";
import { ArrowRight, CheckCircle2, CloudOff, Cpu, Database, FileJson, Fingerprint, Inbox, Link2, RefreshCw, RotateCw, Server, ShieldAlert, Table2, UploadCloud, XCircle } from "lucide-react";
import { api } from "../lib/api";
import { useLive, usePoll } from "../lib/live";
import { Kpi, Loader, Modal, toast } from "../components/ui";
import { hhmm } from "../lib/format";

const TYPE: Record<string, string> = { incident: "Incident", grievance: "Citizen grievance", service_delivery: "Service delivery record", water_quality_test: "Water quality test", jal_seva_aankalan_draft: "Jal Seva Aankalan draft", jal_seva_aankalan: "Jal Seva Aankalan, endorsed" };
// one tile per kind of record; the assessment's draft and endorsed versions share a tile
const TILES: [string, string[]][] = [["Incident", ["incident"]], ["Citizen grievance", ["grievance"]], ["Service delivery record", ["service_delivery"]],
  ["Water quality test", ["water_quality_test"]], ["Jal Seva Aankalan", ["jal_seva_aankalan_draft", "jal_seva_aankalan"]]];

/** Field-by-field mapping to each JJM platform, and the ministry's own device message format. */
function FieldMapping() {
  const { village } = useLive();
  const { data: m } = usePoll<any>("/api/sync/mapping", 0);
  const { data: dd } = usePoll<any>(`/api/interop/ddws/${village}`, 0, [village]);
  const [sys, setSys] = useState(0);
  if (!m) return null;
  const p = m.platforms[sys];
  return (
    <div className="grid g-main" style={{ marginTop: 16 }}>
      <div className="card">
        <div className="card-h"><h3><Table2 />Field mapping</h3>
          <div className="seg" style={{ flexWrap: "wrap" }}>{m.platforms.map((x: any, i: number) => <button key={x.system} className={sys === i ? "on" : ""} onClick={() => setSys(i)}>{x.system.split(" (")[0]}</button>)}</div></div>
        <div className="card-b">
          <p className="sm ink2" style={{ marginBottom: 10 }}>{p.about} No API specification for this platform is public, so each target field name is a <b>draft</b>; the JalSakhi side is exact. A live adapter swaps in the official names when access is granted.</p>
          {p.records.map((r: any) => (
            <div key={r.record_type} className="tbl-wrap" style={{ marginBottom: 12, border: "1px solid var(--line)" }}>
              <table className="tbl">
                <thead><tr><th>{r.record_type.replace(/_/g, " ")} → field (draft)</th><th>JalSakhi source</th><th>Meaning</th></tr></thead>
                <tbody>{r.fields.map((f: any) => <tr key={f.target}><td className="mono">{f.target}</td><td className="mono xs muted">{f.source}</td><td className="xs">{f.note}</td></tr>)}</tbody>
              </table>
            </div>
          ))}
        </div>
      </div>
      <div className="card" style={{ alignSelf: "start" }}>
        <div className="card-h"><h3><Cpu />Ministry device format</h3><span className="pill info">in and out</span></div>
        <div className="card-b stack" style={{ gap: 10 }}>
          <p className="sm ink2">Village gateways can send readings in the reference payload of the DDWS expert committee's monitoring roadmap (March 2021) to <span className="mono">POST /api/telemetry/ddws</span>, and every village's latest readings are published in it.</p>
          {dd?.messages?.length > 0 && <pre className="code" style={{ maxHeight: 210 }}>{JSON.stringify(dd.messages.slice(0, 2), null, 1)}</pre>}
          <div className="stack" style={{ gap: 4 }}>{m.ddws.types.map((t: any) => <div key={t.dty} className="xs"><b className="mono">{t.dty}</b> {t.what} <span className="muted">· {t.basis.startsWith("report") ? "from the report" : "JalSakhi extension"}</span></div>)}</div>
          <div className="xs muted">Types fm, sl, gl, ca and keys t, f, b, e come from the report; the others extend it in the same style for sensors the report lists without a code.</div>
        </div>
      </div>
    </div>
  );
}

export function Integration() {
  const { data: d, reload } = usePoll<any>("/api/sync", 2000);
  const [view, setView] = useState<any>(null);
  const [tab, setTab] = useState("jalsakhi");
  const [busy, setBusy] = useState(false);
  if (!d) return <div className="page"><Loader /></div>;
  const s = d.summary;
  const pending = s.queued + s.retry;

  const outage = async (on: boolean) => {
    setBusy(true);
    try { await api("/api/sync/outage", { body: { on } }); toast(on ? "Sandbox gateway taken offline. Records now queue and retry." : "Gateway restored. Queue is draining."); reload(); } catch (e: any) { toast(e.message, true); }
    setBusy(false);
  };
  const flush = async () => {
    setBusy(true);
    try { const r = await api("/api/sync/flush", { method: "POST" }); toast(`Sent ${r.sent} record(s)`); reload(); } catch (e: any) { toast(e.message, true); }
    setBusy(false);
  };

  return (
    <div className="page">
      <div className="page-h">
        <div><h1>IMIS / Sujal Gaon sync</h1><p>Every incident, grievance, quality test and service record is keyed to the scheme's Sujal Gaon ID and pushed automatically through an outbox that survives outages. No manual re-entry.</p></div>
        <span className="pill demo" style={{ fontSize: 12.5, padding: "5px 12px" }}>SANDBOX · no live government write</span>
      </div>
      <div className="note demo" style={{ marginBottom: 16 }}><ShieldAlert /><span>{d.notice}</span></div>

      <div className="card pad" style={{ marginBottom: 16, overflow: "hidden" }}>
        <div className="row between wrap" style={{ gap: 10 }}>
          {[
            { icon: Database, t: "JalSakhi events", s: "incidents · grievances · tests · service records", n: s.total },
            { icon: Inbox, t: "Outbox", s: "idempotency key · retry with backoff", n: pending, warn: pending > 0 },
            { icon: Server, t: "Adapter", s: s.adapter, n: s.failed_attempts, label: "failed attempts", warn: s.outage },
            { icon: UploadCloud, t: "Received by gateway", s: "acknowledged with a reference", n: s.received_by_gateway, good: true },
          ].map((n, i, arr) => (
            <div key={n.t} className="row grow" style={{ gap: 10, minWidth: 190 }}>
              <div style={{ flex: 1, padding: 13, borderRadius: 15, border: `1px solid ${n.warn ? "var(--warn)" : "var(--line)"}`, background: n.warn ? "var(--warn-bg)" : "var(--surface-2)" }}>
                <div className="row"><n.icon size={17} color={n.good ? "var(--good)" : "var(--brand)"} /><b>{n.t}</b></div>
                <div style={{ fontSize: 24, fontWeight: 750 }} className="num">{n.n}<small className="muted" style={{ fontSize: 11.5, fontWeight: 600 }}> {n.label || "records"}</small></div>
                <div className="xs muted">{n.s}</div>
              </div>
              {i < arr.length - 1 && <ArrowRight size={18} className={`muted ${s.outage && i === 1 ? "" : pending > 0 ? "pulse" : ""}`} style={{ flex: "none" }} />}
            </div>
          ))}
        </div>
        <div className="row between wrap" style={{ marginTop: 14 }}>
          <div className="row wrap">
            {s.outage ? <span className="pill critical"><CloudOff />gateway offline (simulated)</span> : <span className="pill good"><CheckCircle2 />gateway reachable</span>}
            {s.reconciled ? <span className="pill good"><Fingerprint />reconciled: sent = received</span> : <span className="pill medium"><RotateCw />{pending} awaiting delivery</span>}
            <span className="muted xs">schema {s.schema}{s.oldest_pending_s ? ` · oldest pending ${Math.round(s.oldest_pending_s)} s` : ""}</span>
          </div>
          <div className="row">
            <button className={`btn sm ${s.outage ? "good" : "ghost"}`} disabled={busy} onClick={() => outage(!s.outage)}><CloudOff />{s.outage ? "Restore gateway" : "DEMO: simulate IMIS outage"}</button>
            <button className="btn sm" disabled={busy} onClick={flush}><RefreshCw />Sync now</button>
          </div>
        </div>
      </div>

      <div className="grid kpis" style={{ marginBottom: 16 }}>
        {TILES.map(([label, kinds]) => {
          const rows = d.by_type.filter((r: any) => kinds.includes(r.record_type));
          const acked = rows.filter((r: any) => r.status === "acked").reduce((a: number, r: any) => a + r.n, 0);
          const total = rows.reduce((a: number, r: any) => a + r.n, 0);
          return <Kpi key={label} label={label} value={acked} unit={`/ ${total}`} tone={total === acked ? "good" : "warn"} sub="acknowledged / queued" />;
        })}
      </div>

      <div className="grid g-main">
        <div className="card tbl-wrap" style={{ maxHeight: 560 }}>
          <div className="card-h" style={{ paddingBottom: 10 }}><h3><Inbox />Outbox (newest first)</h3><span className="muted xs">click a row to see the payload</span></div>
          <table className="tbl">
            <thead><tr><th>#</th><th>Record</th><th>Operation</th><th>Status</th><th>Attempts</th><th>Gateway ref</th></tr></thead>
            <tbody>
              {d.outbox.map((r: any) => (
                <tr key={r.id} className="click" onClick={() => { setView(r); setTab(r.payload?.targets?.[0]?.system || "jalsakhi"); }}>
                  <td className="num muted">{r.id}</td>
                  <td><b>{TYPE[r.record_type] || r.record_type}</b><div className="xs muted mono">{r.entity_id} · {hhmm(r.created_ts)}</div></td>
                  <td className="sm">{r.op}</td>
                  <td>{r.status === "acked" ? <span className="pill good"><CheckCircle2 />acknowledged</span> : r.status === "retry" ? <span className="pill critical" title={r.last_error}><XCircle />retrying</span> : <span className="pill medium"><RotateCw />queued</span>}
                    {r.last_error && r.status !== "acked" && <div className="xs muted" style={{ maxWidth: 190 }}>{r.last_error}</div>}</td>
                  <td className="num">{r.attempts}</td>
                  <td className="mono">{r.external_ref || "–"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="stack">
          <div className="card">
            <div className="card-h"><h3><Link2 />Target platforms</h3></div>
            <div className="card-b stack" style={{ gap: 9 }}>
              {d.targets.map((t: any) => (
                <div key={t.system} className="row" style={{ alignItems: "flex-start" }}>
                  <span className={`pill ${t.state === "sandbox" ? "demo" : t.state === "export" ? "info" : ""}`} style={{ minWidth: 68, justifyContent: "center" }}>{t.state}</span>
                  <div className="sm"><b>{t.system}</b><div className="muted">{t.what}</div></div>
                </div>
              ))}
              <div className="xs muted">sandbox: pushed through the outbox to a stand-in gateway · planned: adapter not built · export: a file you download from the GIS map page, nothing is pushed.</div>
            </div>
          </div>
          <div className="card">
            <div className="card-h"><h3><Fingerprint />Identifier mapping</h3><span className="pill demo">placeholders</span></div>
            <div className="tbl-wrap" style={{ maxHeight: 250 }}>
              <table className="tbl">
                <thead><tr><th>Internal</th><th>System</th><th>External ID</th></tr></thead>
                <tbody>{d.mappings.slice(0, 42).map((m: any, i: number) => <tr key={i}><td className="mono">{m.internal_id}</td><td className="sm">{m.system}<div className="xs muted">{m.field.replace(/_/g, " ")}</div></td><td className="mono">{m.external_id}</td></tr>)}</tbody>
              </table>
            </div>
          </div>
        </div>
      </div>

      <FieldMapping />

      {view && (
        <Modal onClose={() => setView(null)}>
          <div className="row between"><h2 className="row"><FileJson size={19} color="var(--brand)" />Payload #{view.id}</h2><button className="btn ghost sm" onClick={() => setView(null)}>Close</button></div>
          <p className="muted sm" style={{ margin: "4px 0 10px" }}>Idempotency key <span className="mono">{view.idem_key}</span>. A retry with the same key never creates a second record downstream.</p>
          <div className="seg" style={{ marginBottom: 10, flexWrap: "wrap" }}>
            {(view.payload?.targets || []).map((t: any) => <button key={t.system} className={tab === t.system ? "on" : ""} onClick={() => setTab(t.system)}>{t.system}</button>)}
            <button className={tab === "jalsakhi" ? "on" : ""} onClick={() => setTab("jalsakhi")}>JalSakhi envelope</button>
          </div>
          {tab === "jalsakhi" ? <pre className="code">{JSON.stringify({ ...view.payload, targets: undefined }, null, 2)}</pre> : <>
            <pre className="code">{JSON.stringify(view.payload.targets.find((t: any) => t.system === tab)?.body, null, 2)}</pre>
            <p className="xs muted" style={{ marginTop: 8 }}>Field names are drafts until the platform's official API specification is issued. The values are exact.</p></>}
        </Modal>
      )}
    </div>
  );
}

import { useEffect, useState } from "react";
import QRCode from "qrcode";
import {
  ArrowDownLeft, ArrowUpRight, BellRing, Building2, CheckCircle2, Clock, Hourglass, Landmark, MessageCircle, Plus, QrCode, Radio, Send,
  ShieldAlert, Smartphone, Trash2, Users, XCircle,
} from "lucide-react";
import { api } from "../lib/api";
import { usePoll } from "../lib/live";
import { Kpi, Loader, Modal, toast } from "../components/ui";

const STATUS: Record<string, [string, string, any]> = {
  sent: ["good", "delivered to provider", CheckCircle2], queued: ["info", "queued", Clock], sending: ["info", "sending", Send],
  retry: ["medium", "retrying", Clock], failed: ["critical", "failed", XCircle], held: ["medium", "held: rate limit", Hourglass],
  sandbox: ["demo", "sandbox", ShieldAlert], received: ["ai", "reply received", ArrowDownLeft],
};
const CH: Record<string, string> = { telegram: "Telegram", whatsapp: "WhatsApp", sms: "SMS" };
const KIND: Record<string, string> = { incident: "new incident", escalation2: "escalated: block", escalation3: "escalated: district", reopened: "reopened by citizen", reply: "reply", test: "test", inbound: "from phone" };
const at = (s: number | null) => (s ? new Date(s * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "–");

export function Alerts() {
  const { data: d, reload } = usePoll<any>("/api/alerts/delivery", 2000);
  const [view, setView] = useState<any>(null);
  if (!d) return <div className="page"><Loader /></div>;
  const c = d.counts || {};
  const live = d.channels.filter((x: any) => x.configured);

  return (
    <div className="page">
      <div className="page-h">
        <div><h1>Phone alerts</h1><p>Every incident reaches a phone, not just this screen: the operator and Pani Samiti first, the block engineer if nobody acknowledges in time, the district if it is not fixed in time. Households get their own lane's alerts in their language, and can answer back.</p></div>
        {d.live ? <span className="pill good" style={{ fontSize: 12.5, padding: "5px 12px" }}><Radio />LIVE · {live.map((x: any) => x.label).join(" + ")}</span>
          : <span className="pill demo" style={{ fontSize: 12.5, padding: "5px 12px" }}>SANDBOX · no channel configured</span>}
      </div>
      {!d.live && <div className="note demo" style={{ marginBottom: 16 }}><ShieldAlert /><span>No messaging channel is configured on this server, so every alert below is routed and written exactly as it would be sent, then kept here as <b>sandbox</b>. Set <span className="mono">TELEGRAM_BOT_TOKEN</span> (a free bot from @BotFather, two minutes) and the same alerts reach real phones.</span></div>}

      <div className="grid kpis" style={{ marginBottom: 16 }}>
        <Kpi icon={<Send />} label="Delivered to phones" value={c.sent || 0} tone={c.sent ? "good" : "mute"} sub="accepted by Telegram, WhatsApp or the SMS gateway" />
        <Kpi icon={<ShieldAlert />} label="Sandbox" value={c.sandbox || 0} sub="routed and written, not sent: no channel, or a DEMO number" />
        <Kpi icon={<ArrowDownLeft />} label="Replies from phones" value={c.received || 0} tone={c.received ? "good" : "mute"} sub="acknowledgements, reports, photos, 'is it fixed?'" />
        <Kpi icon={<XCircle />} label="Failed or held" value={(c.failed || 0) + (c.held || 0) + (c.retry || 0)} tone={(c.failed || 0) > 0 ? "crit" : "mute"} sub={`at most ${d.rate.max} messages per phone per ${d.rate.per_s / 60} min`} />
      </div>

      <div className="grid g-main">
        <div className="card tbl-wrap" style={{ maxHeight: 720, alignSelf: "start" }}>
          <div className="card-h" style={{ paddingBottom: 10 }}><h3><BellRing />Delivery log (newest first)</h3><span className="muted xs">click a row for the full message</span></div>
          {d.log.length === 0 ? <p className="muted sm" style={{ padding: "6px 18px 18px" }}>Nothing yet. Run a scenario from the demo panel, or link your phone and send it a test.</p> : (
            <table className="tbl">
              <thead><tr><th>Time</th><th>To / from</th><th>Message</th><th>Status</th></tr></thead>
              <tbody>
                {d.log.map((r: any) => {
                  const [cls, label, Icon] = STATUS[r.status] || ["", r.status, Clock];
                  return (
                    <tr key={r.id} className="click" onClick={() => setView(r)}>
                      <td className="num sm muted">{at(r.created_wall)}</td>
                      <td className="sm" style={{ minWidth: 170 }}>
                        <span className="row" style={{ gap: 5 }}>{r.direction === "in" ? <ArrowDownLeft size={14} color="var(--brand)" /> : <ArrowUpRight size={14} className="muted" />}<b>{r.name}</b></span>
                        <div className="xs muted">{CH[r.channel]} · {r.address}{r.kind && KIND[r.kind] ? ` · ${KIND[r.kind]}` : ""}</div>
                      </td>
                      <td className="sm" style={{ maxWidth: 360 }}><div style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{r.text.split("\n").slice(0, 2).join(" · ")}</div>
                        {r.incident_id && <div className="xs muted mono">{r.incident_id}</div>}</td>
                      <td><span className={`pill ${cls}`} title={r.last_error || ""}><Icon />{label}</span>{r.last_error && r.status !== "sandbox" && <div className="xs muted" style={{ maxWidth: 180 }}>{r.last_error}</div>}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>

        <div className="stack">
          <LinkPhone d={d} onDone={reload} />
          <Ladder />
          <div className="card">
            <div className="card-h"><h3><MessageCircle />Channels</h3></div>
            <div className="card-b stack" style={{ gap: 10 }}>
              {d.channels.map((x: any) => (
                <div key={x.id} className="row" style={{ alignItems: "flex-start" }}>
                  <span className={`pill ${x.live ? "good" : x.configured ? "medium" : "demo"}`} style={{ minWidth: 82, justifyContent: "center" }}>{x.live ? "live" : x.configured ? "configured" : "sandbox"}</span>
                  <div className="sm grow"><b>{x.label}</b>{x.identity && <span className="mono muted"> {x.identity}</span>}{x.two_way && <span className="tag" style={{ marginLeft: 6 }}>two-way</span>}
                    <div className="xs muted">{x.error ? <span style={{ color: "var(--crit)" }}>{x.error}</span> : x.configured ? "Credentials set on this server." : x.setup}</div></div>
                </div>
              ))}
              <div className="xs muted">SMS in India needs a DLT-registered sender ID and message templates; the gateway belongs to the deploying department.</div>
            </div>
          </div>
          <Recipients d={d} onChange={reload} />
        </div>
      </div>

      {view && (
        <Modal onClose={() => setView(null)}>
          <div className="row between"><h2 className="row">{view.direction === "in" ? <ArrowDownLeft size={19} color="var(--brand)" /> : <ArrowUpRight size={19} color="var(--brand)" />}{view.direction === "in" ? "From" : "To"} {view.name}</h2><button className="btn ghost sm" onClick={() => setView(null)}>Close</button></div>
          <p className="muted sm" style={{ margin: "4px 0 10px" }}>{CH[view.channel]} · {view.address} · {at(view.created_wall)}{view.sent_wall ? ` · delivered ${at(view.sent_wall)}` : ""}{view.provider_ref ? ` · ref ${view.provider_ref}` : ""}</p>
          <div className="card pad" style={{ whiteSpace: "pre-wrap", fontSize: 14.5, lineHeight: 1.55, background: "var(--surface-2)" }}>{view.text}</div>
          {view.buttons?.length > 0 && <div className="row wrap" style={{ marginTop: 10, gap: 6 }}>{view.buttons.flat().map(([l, k]: any) => <span key={k} className="pill info">{l}</span>)}</div>}
          {view.last_error && <p className="xs muted" style={{ marginTop: 10 }}>{view.last_error}</p>}
        </Modal>
      )}
    </div>
  );
}

function LinkPhone({ d, onDone }: { d: any; onDone: () => void }) {
  const [opt, setOpt] = useState<string>(() => d.options[0] ? `${d.options[0].role}|${d.options[0].scope_id}` : "");
  const [link, setLink] = useState<any>(null);
  const [qr, setQr] = useState("");
  const [left, setLeft] = useState(0);
  useEffect(() => {
    if (!link?.telegram && !link?.whatsapp) { setQr(""); return; }
    QRCode.toDataURL(link.telegram?.url || link.whatsapp.url, { margin: 1, width: 210, color: { dark: "#062a4a", light: "#ffffff" } }).then(setQr).catch(() => {});
  }, [link]);
  useEffect(() => {
    if (!link) return;
    const end = Date.now() + link.expires_in_s * 1000;
    const id = setInterval(() => { const s = Math.max(0, Math.round((end - Date.now()) / 1000)); setLeft(s); if (!s) setLink(null); }, 1000);
    return () => clearInterval(id);
  }, [link]);
  const make = async () => {
    const [role, scope_id] = opt.split("|");
    try { setLink(await api("/api/alerts/link", { body: { role, scope_id } })); onDone(); } catch (e: any) { toast(e.message, true); }
  };
  return (
    <div className="card">
      <div className="card-h"><h3><Smartphone />Get these alerts on your phone</h3></div>
      <div className="card-b stack" style={{ gap: 10 }}>
        <div><label className="f">Receive alerts as</label>
          <select className="select" value={opt} onChange={(e) => { setOpt(e.target.value); setLink(null); }}>
            {d.options.map((o: any) => <option key={`${o.role}|${o.scope_id}`} value={`${o.role}|${o.scope_id}`}>Level {o.level} · {o.label}</option>)}
          </select></div>
        <button className="btn" onClick={make}><QrCode />Make a link code</button>
        {link && <>
          {qr && <div className="row" style={{ gap: 14, alignItems: "center" }}><img src={qr} alt="Scan to link this phone" width={150} height={150} style={{ borderRadius: 12, border: "1px solid var(--line)" }} />
            <div className="sm stack" style={{ gap: 6 }}><b>Scan with the phone's camera</b><span className="muted">It opens {link.telegram ? `${link.telegram.bot} in Telegram` : "WhatsApp"}; press Start and the phone is linked. Your replies to alerts act as you.</span>
              {link.telegram && <a className="btn ghost sm" href={link.telegram.url} target="_blank" rel="noreferrer"><Send />Open in Telegram</a>}</div></div>}
          {link.whatsapp && <div className="note"><MessageCircle /><span>On WhatsApp: send <b className="mono">{link.whatsapp.text}</b> to <b>{link.whatsapp.number}</b>.</span></div>}
          {!link.live && <div className="note demo"><ShieldAlert /><span>Code <b className="mono">{link.code}</b> is ready, but no channel is configured on this server, so there is nothing to scan yet. With <span className="mono">TELEGRAM_BOT_TOKEN</span> set, this shows a QR code.</span></div>}
          <div className="xs muted">Code <span className="mono">{link.code}</span> · one phone · expires in {Math.floor(left / 60)}:{String(left % 60).padStart(2, "0")}</div>
        </>}
      </div>
    </div>
  );
}

function Ladder() {
  const steps: [any, string, string, string][] = [
    [Users, "Level 1 · Village", "Nal Jal Mitra and the Pani Samiti", "the moment an incident opens (sensor faults and minor reports: operator only)"],
    [Building2, "Level 2 · Block", "Junior Engineer", "if the village has not acknowledged within the SLA, or at once when critical"],
    [Landmark, "Level 3 · District", "Executive Engineer", "if the incident is not resolved within the SLA"],
    [Smartphone, "Households", "families on the affected lane", "the same alerts as their app, in their language; they reply to report, send a photo or location, or confirm a repair"],
  ];
  return (
    <div className="card">
      <div className="card-h"><h3><BellRing />Who hears, and when</h3></div>
      <div className="card-b stack" style={{ gap: 11 }}>
        {steps.map(([Icon, t, who, when]) => (
          <div key={t} className="row" style={{ alignItems: "flex-start" }}>
            <span style={{ width: 30, height: 30, borderRadius: 10, display: "grid", placeItems: "center", background: "var(--info-bg)", flex: "none" }}><Icon size={16} color="var(--brand)" /></span>
            <div className="sm"><b>{t}</b> · {who}<div className="xs muted">{when}</div></div>
          </div>
        ))}
        <div className="xs muted">Staff alerts carry Acknowledge and Start work buttons; tapping one updates the incident here, with the phone named in the audit trail.</div>
      </div>
    </div>
  );
}

function Recipients({ d, onChange }: { d: any; onChange: () => void }) {
  const [adding, setAdding] = useState(false);
  const [f, setF] = useState<any>({ name: "", opt: d.options[0] ? `${d.options[0].role}|${d.options[0].scope_id}` : "", channel: "whatsapp", address: "", lang: "en" });
  const test = async (id: number) => { try { const r = await api(`/api/alerts/recipients/${id}/test`, { method: "POST" }); toast(r.status === "sandbox" ? "Test written to the log (sandbox)" : "Test message queued"); onChange(); } catch (e: any) { toast(e.message, true); } };
  const remove = async (id: number) => { try { await api(`/api/alerts/recipients/${id}`, { method: "DELETE" }); toast("Recipient removed"); onChange(); } catch (e: any) { toast(e.message, true); } };
  const add = async () => {
    const [role, scope_id] = f.opt.split("|");
    try { await api("/api/alerts/recipients", { body: { name: f.name, role, scope_id, channel: f.channel, address: f.address, lang: f.lang } }); toast("Recipient added"); setAdding(false); setF({ ...f, name: "", address: "" }); onChange(); } catch (e: any) { toast(e.message, true); }
  };
  return (
    <div className="card">
      <div className="card-h"><h3><Users />Recipients ({d.recipients.length})</h3><button className="btn ghost sm" onClick={() => setAdding(!adding)}><Plus />Add by number</button></div>
      <div className="card-b stack" style={{ gap: 8 }}>
        {adding && <div className="card pad stack" style={{ gap: 8, background: "var(--surface-2)" }}>
          <select className="select" value={f.opt} onChange={(e) => setF({ ...f, opt: e.target.value })}>{d.options.map((o: any) => <option key={`${o.role}|${o.scope_id}`} value={`${o.role}|${o.scope_id}`}>Level {o.level} · {o.label}</option>)}</select>
          <input className="input" placeholder="Name" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} />
          <div className="row"><select className="select" style={{ width: 130 }} value={f.channel} onChange={(e) => setF({ ...f, channel: e.target.value })}><option value="whatsapp">WhatsApp</option><option value="sms">SMS</option><option value="telegram">Telegram chat ID</option></select>
            <input className="input grow" placeholder={f.channel === "telegram" ? "chat ID" : "+91 98xxx xxxxx"} value={f.address} onChange={(e) => setF({ ...f, address: e.target.value })} /></div>
          <div className="row"><button className="btn sm" disabled={!f.address} onClick={add}>Add recipient</button><button className="btn ghost sm" onClick={() => setAdding(false)}>Cancel</button></div>
        </div>}
        {d.recipients.map((r: any) => (
          <div key={r.id} className="row sm" style={{ alignItems: "flex-start", paddingBottom: 8, borderBottom: "1px solid var(--line)" }}>
            <div className="grow"><b>{r.name}</b>{r.demo && <span className="pill demo" style={{ marginLeft: 6 }}>DEMO number</span>}
              <div className="xs muted">{r.level ? `Level ${r.level} · ` : ""}{r.role_title} · {CH[r.channel]} {r.address}</div>
              <div className="xs muted">{r.linked_via}</div></div>
            <button className="btn ghost sm" title="Send a test message" onClick={() => test(r.id)}><Send /></button>
            {!r.demo && <button className="btn ghost sm" title="Remove" onClick={() => remove(r.id)}><Trash2 /></button>}
          </div>
        ))}
      </div>
    </div>
  );
}

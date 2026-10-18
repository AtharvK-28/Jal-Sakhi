import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { HeartHandshake, Languages, Link2, MessageCircle, MessageSquareText, MessageSquare, Phone, Send, Smartphone, Sparkles, ThumbsUp } from "lucide-react";
import { api } from "../lib/api";
import { useLive, usePoll } from "../lib/live";
import { Empty, Kpi, Loader, StatusPill, toast } from "../components/ui";
import { BarList } from "../components/charts";
import { CAT_LABEL, LANG_NAME, dt, n0 } from "../lib/format";

const CHANNEL: Record<string, any> = { app: Smartphone, sms: MessageSquare, ivr: Phone, telegram: Send, whatsapp: MessageCircle };

export function Complaints() {
  const { snap, village } = useLive();
  const nav = useNavigate();
  const [tab, setTab] = useState<"open" | "">("open");
  const { data, reload } = usePoll<any[]>(`/api/complaints${tab ? `?status=${tab}` : ""}`, 3500, [tab]);
  const [sms, setSms] = useState("JAL PW-HH-027 nal se ganda pani aa raha hai");
  const [ai, setAi] = useState<any>(null);
  const names = useMemo(() => Object.fromEntries((snap?.summary || []).map((v: any) => [v.id, v.name])), [snap]);
  const rows = data || [];
  const byCat = useMemo(() => Object.entries(rows.reduce((a: any, c: any) => ({ ...a, [c.category]: (a[c.category] || 0) + 1 }), {})).map(([k, v]: any) => ({ label: CAT_LABEL[k], value: v })).sort((a, b) => b.value - a.value), [rows]);
  const langs = new Set(rows.map((r) => r.language)).size;
  const linked = rows.filter((r) => r.incident_id).length;
  const confirmed = rows.filter((r) => r.citizen_confirmed === 1).length;
  const pulse = snap?.focus?.kpis?.pulse;

  const sendSms = async () => {
    try { const r = await api("/api/sms/inbound", { body: { sender: "demo", text: sms }, auth: false }); toast(r.reply_sms); reload(); } catch (e: any) { toast(e.message, true); }
  };
  const classify = async (text: string) => {
    const body = text.replace(/^JAL\s+\S+\s*/i, "");
    if (body.length < 3) return setAi(null);
    try { setAi(await api("/api/nlp/classify", { body: { text: body }, auth: false })); } catch { /* ignore */ }
  };

  return (
    <div className="page">
      <div className="page-h">
        <div><h1>Citizen voice</h1><p>Reports from households by app, SMS and voice call, in their own language. Each one is read by the classifier, matched to what the sensors see, and grouped with neighbours reporting the same thing.</p></div>
        <div className="seg"><button className={tab === "open" ? "on" : ""} onClick={() => setTab("open")}>Open</button><button className={tab === "" ? "on" : ""} onClick={() => setTab("")}>All</button></div>
      </div>

      <div className="grid kpis" style={{ marginBottom: 16 }}>
        <Kpi icon={<MessageSquareText />} label={tab ? "Open reports" : "Reports"} value={rows.length} sub="in your jurisdiction" />
        <Kpi icon={<Link2 />} label="Linked to an incident" value={rows.length ? `${Math.round((linked / rows.length) * 100)}` : "–"} unit="%" tone="good" sub="no report sits alone in a queue" />
        <Kpi icon={<Languages />} label="Languages in use" value={langs} sub="six supported in the citizen app" />
        <Kpi icon={<ThumbsUp />} label="Fix confirmed by citizen" value={confirmed} sub="closure needs their confirmation" />
        <Kpi icon={<HeartHandshake />} label="Daily pulse vs sensors" value={pulse?.agreement_pct != null ? n0(pulse.agreement_pct) : "–"} unit="%" sub={pulse ? `${pulse.responses} households answered "did water come today?"` : "after each supply window"} />
      </div>

      <div className="grid g-main">
        <div className="card tbl-wrap" style={{ maxHeight: 640 }}>
          {!data ? <Loader /> : rows.length === 0 ? <Empty>No {tab ? "open " : ""}citizen reports. Trigger a scenario, or submit one from the citizen app.</Empty> : (
            <table className="tbl">
              <thead><tr><th>Report</th><th>What they said</th><th>AI reading</th><th>Channel</th><th>Status</th><th>Linked incident</th></tr></thead>
              <tbody>
                {rows.map((c) => {
                  const Ch = CHANNEL[c.channel] || Smartphone;
                  return (
                    <tr key={c.id} className={c.incident_id ? "click" : ""} onClick={() => c.incident_id && nav(`/app/incidents/${c.incident_id}`)}>
                      <td><b>{CAT_LABEL[c.category]}</b><div className="xs muted">{c.household} · {c.lane}</div><div className="xs muted">{names[c.village_id]} · {dt(c.created_at)}</div></td>
                      <td style={{ maxWidth: 260 }}>{c.description ? <span>"{c.description}"</span> : <span className="muted">(category only)</span>}
                        <div className="row" style={{ gap: 5, marginTop: 3 }}><span className="tag">{LANG_NAME[c.language] || c.language}</span>{c.source === "simulated-citizen" && <span className="tag">simulated</span>}{c.photo && <span className="tag">photo</span>}{c.urgency === "high" && <span className="pill critical">urgent</span>}</div></td>
                      <td>{c.ai_category ? <span className="pill ai"><Sparkles />{CAT_LABEL[c.ai_category]} {Math.round(c.ai_confidence * 100)}%</span> : <span className="muted">–</span>}</td>
                      <td><span className="row sm" style={{ gap: 5 }}><Ch size={14} className="muted" />{c.channel}</span></td>
                      <td><StatusPill status={c.status} />{c.citizen_confirmed === 1 && <div className="xs" style={{ color: "var(--good)", fontWeight: 650, marginTop: 3 }}>citizen confirmed</div>}{c.citizen_confirmed === 0 && <div className="xs" style={{ color: "var(--crit)", fontWeight: 650, marginTop: 3 }}>says not fixed</div>}</td>
                      <td className="mono">{c.incident_id || "–"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
        <div className="stack">
          <div className="card"><div className="card-h"><h3><MessageSquareText />By category</h3></div><div className="card-b"><BarList items={byCat} /></div></div>
          <div className="card">
            <div className="card-h"><h3><Phone />No smartphone? SMS gateway</h3><span className="pill demo">DEMO</span></div>
            <div className="card-b">
              <p className="sm ink2">Feature-phone users text <span className="mono">JAL &lt;household&gt; &lt;problem&gt;</span>. The classifier reads free text in Hindi, Marathi, English and romanised forms.</p>
              <textarea className="input" rows={2} style={{ marginTop: 9 }} value={sms} onChange={(e) => { setSms(e.target.value); classify(e.target.value); }} />
              <div className="row between wrap" style={{ marginTop: 8 }}>
                {ai?.category ? <span className="pill ai"><Sparkles />reads as {CAT_LABEL[ai.category]} · {Math.round(ai.confidence * 100)}%{ai.urgency === "high" ? " · urgent" : ""}</span> : <span className="xs muted">edit the text to see the AI reading</span>}
                <button className="btn sm" onClick={sendSms}>Send simulated SMS</button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

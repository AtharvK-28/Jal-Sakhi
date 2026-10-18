import { useState } from "react";
import { BadgeIndianRupee, CalendarCheck2, Check, ClipboardPenLine, Fingerprint, Gauge, HandCoins, Lightbulb, NotebookPen, Wrench } from "lucide-react";
import { api } from "../lib/api";
import { useLive, usePoll } from "../lib/live";
import { Kpi, Loader, toast } from "../components/ui";
import { BarList } from "../components/charts";
import { VillagePicker } from "../components/Shell";
import { dayMon, n0, n1 } from "../lib/format";

const HEAD: Record<string, string> = { electricity: "Electricity", operator: "Operator", chlorine: "Chlorine", repairs: "Repairs", other: "Other" };
const WINDOW = ["morning", "evening"];
const rupees = (v: any) => (v == null ? "–" : `₹${n0(v)}`);
const monthName = (m: string) => new Date(`${m}-01T00:00:00`).toLocaleDateString("en-IN", { month: "short", year: "numeric" });
const STATE: Record<string, string> = { good: "good", watch: "medium", poor: "critical" };

/** The registers a Pani Samiti keeps (upkeep, operator log, accounts), each tied to what the sensors know. */
export function Upkeep() {
  const { village, focus } = useLive();
  const { data: d, reload } = usePoll<any>(`/api/om?village=${village}`, 5000);
  const [busy, setBusy] = useState(false);
  if (!d) return <div className="page"><Loader /></div>;
  const { profile: p, upkeep: u, log, accounts: a } = d;
  const act = async (fn: () => Promise<any>, ok: (r: any) => string) => {
    setBusy(true);
    try { toast(ok(await fn())); reload(); } catch (e: any) { toast(e.message, true); } finally { setBusy(false); }
  };

  return (
    <div className="page">
      <div className="page-h">
        <div><h1>Upkeep & accounts · {focus?.name}</h1>
          <p>Monitoring says when something breaks. This is the other half of keeping taps running: work done before it breaks, the operator's daily entry, and whether the user charge pays for the scheme.</p></div>
        <VillagePicker />
      </div>

      <div className="grid kpis" style={{ marginBottom: 16 }}>
        <Kpi icon={<CalendarCheck2 />} label="Upkeep up to date" value={u.on_time} unit={`/ ${u.total}`} tone={u.overdue ? "warn" : "good"} sub={u.overdue ? `${u.overdue} overdue` : "nothing overdue"} />
        <Kpi icon={<NotebookPen />} label="Operator log kept" value={n0(log.kept_pct)} unit="%" tone={log.kept_pct >= 90 ? "good" : "warn"} sub={`${log.kept} of ${log.expected} supply windows, 14 days`} />
        <Kpi icon={<HandCoins />} label="Charges collected" value={n0(a.collection_pct)} unit="%" tone={a.collection_pct >= 85 ? "good" : "warn"} sub={`last 3 months · ${rupees(a.arrears)} in arrears`} />
        <Kpi icon={<Gauge />} label="Running cost covered" value={n0(a.recovery_pct)} unit="%" tone={a.recovery_pct >= 100 ? "good" : a.recovery_pct >= 70 ? "warn" : "crit"} sub={`${rupees(a.monthly_collected)} in, ${rupees(a.monthly_cost)} out a month`} />
      </div>

      <div className="card">
        <div className="card-h"><h3><Fingerprint />Scheme profile</h3><span className="pill demo mono">{p.ids.sujal_gaon_id}</span></div>
        <div className="card-b">
          <div className="grid g-main">
            <div>
              <div className="sm ink2">{p.scheme} · {p.gp} · {p.homes} tap connections on {p.lanes} lanes · {n0(p.people)} people</div>
              <div className="tbl-wrap" style={{ marginTop: 10 }}><table className="tbl"><tbody>
                {p.assets.map((x: any) => <tr key={x.name}><td style={{ width: "32%" }}><b className="sm">{x.name}</b></td><td className="sm ink2">{x.detail}</td><td style={{ textAlign: "right" }}><span className={`pill ${STATE[x.state]}`}>{x.state}</span></td></tr>)}
              </tbody></table></div>
            </div>
            <div className="stack sm" style={{ gap: 9 }}>
              <div><div className="upper muted">Supply reliability, 30 days</div><b className="num">{n0(p.reliability.regular_pct)}%</b> of homes served in scheduled windows · <b className="num">{n0(p.reliability.lpcd)}</b> L per person a day</div>
              <div><div className="upper muted">Operation and maintenance</div>{p.om.operator} · charge {rupees(p.om.tariff)} a household a month · {p.om.upkeep}</div>
              <div><div className="upper muted">Water quality tests on record</div>{p.tests.length ? p.tests.map((t: any) => `${t.kind} ${t.result} (${dayMon(t.ts)})`).join(" · ") : "none recorded in this session"}</div>
              <div className="xs muted">The fields a Sujal Gaon ID profile carries (source, infrastructure condition, supply reliability, O&M arrangements, quality tests), filled from live data. The ID is a placeholder.</div>
            </div>
          </div>
        </div>
      </div>

      <div className="grid g2" style={{ marginTop: 16 }}>
        <div className="card">
          <div className="card-h"><h3><Wrench />Upkeep plan</h3><span className="muted xs">{u.total} items · soonest first</span></div>
          <div className="tbl-wrap" style={{ maxHeight: 470 }}>
            <table className="tbl" style={{ minWidth: 500 }}>
              <thead><tr><th>Work</th><th>Last done</th><th>Due</th><th /></tr></thead>
              <tbody>
                {u.tasks.map((t: any) => (
                  <tr key={t.id}>
                    <td><b className="sm">{t.title}</b><div className="xs muted">{t.asset} · every {t.every_days} days · {t.basis}</div>{t.why && <div className="xs" style={{ color: "var(--serious)" }}>{t.why}</div>}</td>
                    <td className="num sm">{dayMon(t.last_done)}</td>
                    <td><span className={`pill ${t.status === "overdue" ? "critical" : t.status === "due" ? "medium" : "good"}`}>{t.days_left < 0 ? `${-t.days_left} d late` : t.days_left === 0 ? "today" : `in ${t.days_left} d`}</span></td>
                    <td><button className="btn ghost sm" disabled={busy} title="Record this as done today" onClick={() => act(() => api(`/api/om/tasks/${t.id}/done`, { body: { note: null } }), () => `Recorded: ${t.title}`)}><Check />Done</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {u.suggested.length > 0 && <div className="card-b">
            <div className="upper muted" style={{ marginBottom: 6 }}>Suggested by the monitoring</div>
            {u.suggested.map((x: any) => <div key={x.title} className="row sm" style={{ padding: "5px 0", alignItems: "flex-start" }}><Lightbulb size={15} color="var(--warn)" style={{ flex: "none", marginTop: 2 }} /><span><b>{x.title}</b><span className="ink2"> · {x.why}</span></span></div>)}
          </div>}
          <div className="card-b xs muted" style={{ paddingTop: 0 }}>Intervals are typical practice, set per scheme in a deployment. The pump's service is brought forward by the wear model, and a recorded Field Test Kit result counts as that round done.</div>
        </div>

        <div className="card">
          <div className="card-h"><h3><ClipboardPenLine />Operator log</h3><span className={`pill ${log.differs ? "high" : "good"}`}>{log.differs ? `${log.differs} entr${log.differs > 1 ? "ies differ" : "y differs"} from the sensors` : "entries agree with the sensors"}</span></div>
          <div className="card-b"><LogForm village={village} busy={busy} act={act} /></div>
          <div className="tbl-wrap" style={{ maxHeight: 300 }}>
            <table className="tbl" style={{ minWidth: 470 }}>
              <thead><tr><th>Window</th><th>Meter reading</th><th>Check</th><th>Pump</th><th>Chlorine</th></tr></thead>
              <tbody>
                {log.rows.map((r: any) => (
                  <tr key={r.id}>
                    <td className="sm" style={{ whiteSpace: "nowrap" }}><b>{dayMon(r.day)}</b> {WINDOW[r.window_idx] || ""}<div className="xs muted">{r.source === "entered" ? r.entered_by : "operator"}</div></td>
                    <td className="num sm" style={{ whiteSpace: "nowrap" }}>{n1(r.meter_kl)} kL{r.sensor_kl != null && <div className="xs muted">sensor {n1(r.sensor_kl)} kL</div>}</td>
                    <td>{r.verdict === "match" ? <span className="pill good">agrees</span> : r.verdict === "differs" ? <span className="pill critical">{r.diff_pct > 0 ? "+" : ""}{n0(r.diff_pct)}%</span> : <span className="muted xs" title="Entered before this session began, so there is no sensor count to compare with">not checked</span>}</td>
                    <td className="num sm" style={{ whiteSpace: "nowrap" }}>{r.pump_hours != null ? `${n1(r.pump_hours)} h` : "–"}{r.sensor_pump_hours != null && <div className="xs muted">sensor {n1(r.sensor_pump_hours)} h</div>}</td>
                    <td className="num sm" style={{ whiteSpace: "nowrap" }}>{r.chlorine_g != null ? `${n0(r.chlorine_g)} g` : "–"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="card-b xs muted">Each meter reading is compared with what the flow sensor has counted since the session began; more than {n0(log.tolerance_pct)}% apart is flagged. That catches a drifting sensor and a careless or invented entry alike. Entries from before this session have nothing to be checked against. Entries not typed in here are simulated.</div>
        </div>
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <div className="card-h"><h3><BadgeIndianRupee />Accounts</h3><span className="pill demo">simulated ledger</span></div>
        <div className="card-b">
          <div className="grid g-main">
            <div>
              <div className="legend" style={{ marginBottom: 8 }}><span><i style={{ background: "var(--s1)" }} />Collected</span><span><i style={{ background: "var(--s2)" }} />Spent</span></div>
              {a.months.map((m: any) => {
                const top = Math.max(...a.months.map((x: any) => Math.max(x.collected, x.spent, x.demand)), 1);
                return (
                  <div key={m.month} className="acct-row">
                    <div className="sm"><b>{monthName(m.month)}</b>{m.partial && <span className="muted xs"> so far</span>}<div className="xs muted">charged {rupees(m.demand)}</div></div>
                    <div>
                      <div className="row" style={{ gap: 8 }}><div className="grow" style={{ height: 10 }}><i className="acct-bar" style={{ width: `${(m.collected / top) * 100}%`, background: "var(--s1)" }} /></div><b className="num sm" style={{ width: 62, textAlign: "right" }}>{rupees(m.collected)}</b></div>
                      <div className="row" style={{ gap: 8, marginTop: 4 }}><div className="grow" style={{ height: 10 }}><i className="acct-bar" style={{ width: `${(m.spent / top) * 100}%`, background: "var(--s2)" }} /></div><b className="num sm" style={{ width: 62, textAlign: "right" }}>{rupees(m.spent)}</b></div>
                    </div>
                    <div style={{ textAlign: "right" }}>{m.partial ? <span className="muted xs">month not over</span> : <><b className="num" style={{ color: m.recovery_pct >= 100 ? "var(--good)" : "var(--serious)" }}>{n0(m.recovery_pct)}%</b><div className="xs muted">of cost covered</div></>}</div>
                  </div>);
              })}
              <div className="note" style={{ marginTop: 12 }}><Lightbulb /><span>
                At {rupees(a.tariff)} a household a month and {n0(a.collection_pct)}% collected, the charge covers <b>{n0(a.recovery_pct)}%</b> of what the scheme costs to run.
                It would break even at <b>{rupees(a.break_even_if_all_pay)}</b> if every household paid, or <b>{rupees(a.break_even_at_this_rate)}</b> at today's collection rate. Water costs about <b>₹{n1(a.cost_per_kl)}</b> a kilolitre to deliver.</span></div>
            </div>
            <div className="stack" style={{ gap: 14 }}>
              <div><div className="upper muted" style={{ marginBottom: 6 }}>Where the money goes ({monthName(a.months[2].month)})</div>
                <BarList items={Object.entries(a.months[2].costs).filter(([, v]: any) => v > 0).map(([k, v]: any) => ({ label: HEAD[k], value: v }))} fmt={(v) => rupees(v)} /></div>
              <div><div className="upper muted" style={{ marginBottom: 6 }}>Collected by lane, last 3 months</div>
                <BarList items={a.lanes.map((l: any) => ({ label: l.name, value: l.collection_pct }))} fmt={(v) => `${n0(v)}%`} max={100} /></div>
            </div>
          </div>
        </div>
        <div className="grid g2" style={{ padding: "0 18px 18px" }}>
          <div>
            <div className="upper muted" style={{ marginBottom: 6 }}>Households owing the most · {a.homes_in_arrears} in arrears</div>
            <div className="tbl-wrap" style={{ maxHeight: 250 }}><table className="tbl"><tbody>
              {a.dues.map((h: any) => (
                <tr key={h.id}><td><b className="sm">{h.label}</b> <span className="muted xs">{h.lane}</span></td><td className="num sm">{rupees(h.due)}<span className="muted xs"> · {h.months} month{h.months > 1 ? "s" : ""}</span></td>
                  <td style={{ textAlign: "right" }}><button className="btn ghost sm" disabled={busy} onClick={() => act(() => api("/api/om/payments", { body: { household_id: h.id } }), (r) => `Receipt ${r.receipt}: ${rupees(r.amount)} from ${r.household}`)}>Record payment</button></td></tr>
              ))}
            </tbody></table></div>
            <div className="xs muted" style={{ marginTop: 6 }}>Household dues are visible to staff of this village only. A household sees its own charge and receipt in the citizen app.</div>
          </div>
          <div>
            <div className="upper muted" style={{ marginBottom: 6 }}>Recent spending</div>
            <ExpenseForm village={village} busy={busy} act={act} />
            {a.expenses.map((e: any) => <div key={e.id} className="row between sm" style={{ padding: "5px 0", borderTop: "1px solid var(--line)" }}><span><b>{HEAD[e.head]}</b> <span className="ink2">{e.note}</span><span className="muted xs"> · {dayMon(e.day)}</span></span><b className="num">{rupees(e.amount)}</b></div>)}
            <div className="xs muted" style={{ marginTop: 6 }}>Electricity is not typed in: it is the pump's measured energy at ₹{a.rate_per_kwh} a unit.</div>
          </div>
        </div>
      </div>
    </div>
  );
}

function LogForm({ village, busy, act }: { village: string; busy: boolean; act: (fn: () => Promise<any>, ok: (r: any) => string) => void }) {
  const [f, setF] = useState<any>({ meter_kl: "", pump_hours: "", chlorine_g: "", remarks: "" });
  const num = (v: string) => (v === "" ? null : Number(v));
  const read = async () => { try { const m = await api(`/api/om/meter?village=${village}`); setF({ ...f, ...m }); } catch (e: any) { toast(e.message, true); } };
  const save = () => act(() => api("/api/om/log", { body: { village_id: village, meter_kl: Number(f.meter_kl), pump_hours: num(String(f.pump_hours)), chlorine_g: num(String(f.chlorine_g)), remarks: f.remarks } }),
    (r) => (r.verdict === "match" ? "Entry saved: it agrees with the flow sensor" : `Entry saved: ${Math.abs(r.diff_pct)}% ${r.diff_pct > 0 ? "above" : "below"} the flow sensor`));
  return (
    <div className="log-form">
      <div><label className="f">Meter reading (kL)</label><input className="input" inputMode="decimal" value={f.meter_kl} onChange={(e) => setF({ ...f, meter_kl: e.target.value })} /></div>
      <div><label className="f">Pump hours</label><input className="input" inputMode="decimal" value={f.pump_hours} onChange={(e) => setF({ ...f, pump_hours: e.target.value })} /></div>
      <div><label className="f">Chlorine (g)</label><input className="input" inputMode="decimal" value={f.chlorine_g} onChange={(e) => setF({ ...f, chlorine_g: e.target.value })} /></div>
      <div style={{ gridColumn: "1 / -1" }} className="row wrap">
        <input className="input grow" placeholder="Remarks (optional)" value={f.remarks} onChange={(e) => setF({ ...f, remarks: e.target.value })} />
        <button className="btn soft sm" onClick={read}>DEMO: read the meter</button>
        <button className="btn sm" disabled={busy || f.meter_kl === ""} onClick={save}>Save entry</button>
      </div>
    </div>
  );
}

function ExpenseForm({ village, busy, act }: { village: string; busy: boolean; act: (fn: () => Promise<any>, ok: (r: any) => string) => void }) {
  const [f, setF] = useState({ head: "repairs", amount: "", note: "" });
  return (
    <div className="row wrap" style={{ gap: 6, marginBottom: 8 }}>
      <select className="select" style={{ width: "auto" }} value={f.head} onChange={(e) => setF({ ...f, head: e.target.value })}>{["repairs", "chlorine", "operator", "other"].map((h) => <option key={h} value={h}>{HEAD[h]}</option>)}</select>
      <input className="input" style={{ width: 96 }} inputMode="decimal" placeholder="₹" value={f.amount} onChange={(e) => setF({ ...f, amount: e.target.value })} />
      <input className="input grow" style={{ minWidth: 120 }} placeholder="What for" value={f.note} onChange={(e) => setF({ ...f, note: e.target.value })} />
      <button className="btn sm" disabled={busy || !(Number(f.amount) > 0)} onClick={() => { act(() => api("/api/om/expenses", { body: { village_id: village, head: f.head, amount: Number(f.amount), note: f.note } }), () => "Expense recorded"); setF({ ...f, amount: "", note: "" }); }}>Add</button>
    </div>
  );
}

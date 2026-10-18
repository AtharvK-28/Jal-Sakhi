import { useEffect, useState } from "react";
import { CheckCircle2, Circle, IndianRupee, PiggyBank, ShieldCheck, TrendingUp, Wrench } from "lucide-react";
import { useLive, usePoll } from "../lib/live";
import { Kpi, Loader } from "../components/ui";

const inr = (v: number) => (v >= 1e5 ? `₹${(v / 1e5).toLocaleString("en-IN", { maximumFractionDigits: 1 })} lakh` : `₹${Math.round(v).toLocaleString("en-IN")}`);
const EFFECT: Record<string, [string, string]> = { restores: ["good", "restores"], protects: ["info", "protects"], measures: ["", "makes measurable"] };
const UNIT: Record<string, string> = { lane_repair: "Lane leak repair", pressure: "Tail-end pressure fix", chlorination: "Chlorination restored", pump: "Pump overhaul",
  source: "Source strengthening", sensor: "Sensor node repair", connection: "Household connection repair" };

/** Where the next rupee buys the most functional household taps, across the selected jurisdiction. */
export function Planner() {
  const { scope } = useLive();
  const [lakh, setLakh] = useState(10);
  const [ask, setAsk] = useState(10);
  useEffect(() => { const id = setTimeout(() => setAsk(lakh), 300); return () => clearTimeout(id); }, [lakh]);
  const { data: d, error } = usePoll<any>(`/api/invest?level=${scope.level}&id=${scope.id}&budget=${ask * 1e5}`, 15000, [ask]);
  if (error) return <div className="page"><p className="muted">{error}</p></div>;
  if (!d) return <div className="page"><Loader /></div>;
  const chosen = d.options.filter((o: any) => o.chosen);

  return (
    <div className="page">
      <div className="page-h">
        <div><h1>Investment planner</h1><p>Every household failing the JJM functionality test, split by what fails it, matched to the fix that would bring it back, and ranked by homes per lakh. Move the budget and see where it goes.</p></div>
        <div className="card pad" style={{ minWidth: 300 }}>
          <div className="row between"><label className="f" style={{ margin: 0 }}>Budget for this jurisdiction</label><b className="num">{inr(lakh * 1e5)}</b></div>
          <input type="range" min={1} max={50} value={lakh} onChange={(e) => setLakh(Number(e.target.value))} style={{ width: "100%", marginTop: 8 }} />
        </div>
      </div>

      <div className="grid kpis" style={{ marginBottom: 16 }}>
        <Kpi icon={<TrendingUp />} label="Functional taps" value={`${d.pct_now}% → ${d.pct_after}`} unit="%" sub={`${d.functional_now} → ${d.functional_after} of ${d.households} homes`} />
        <Kpi icon={<Wrench />} label="Homes restored" value={d.gained} sub="failing today, fixed by the chosen works" />
        <Kpi icon={<ShieldCheck />} label="Homes protected" value={d.protected} sub="kept from a likely pump or source failure" />
        <Kpi icon={<IndianRupee />} label="Budget used" value={inr(d.spent)} sub={`${chosen.length} works chosen of ${d.options.length}`} />
      </div>

      <div className="grid g-main">
        <div className="card tbl-wrap" style={{ alignSelf: "start" }}>
          <div className="card-h" style={{ paddingBottom: 10 }}><h3><PiggyBank />Works, best value first</h3><span className="muted xs">indicative costs</span></div>
          {d.options.length === 0 ? <p className="muted sm" style={{ padding: "0 18px 18px" }}>Every household in this jurisdiction passes the functionality test. Nothing to fund.</p> : (
            <table className="tbl">
              <thead><tr><th /><th>Work</th><th>Cost</th><th>Homes</th><th>Per lakh</th></tr></thead>
              <tbody>
                {d.options.map((o: any, i: number) => (
                  <tr key={i} style={o.chosen ? undefined : { opacity: 0.55 }}>
                    <td>{o.chosen ? <CheckCircle2 size={17} color="var(--good)" /> : <Circle size={17} className="muted" />}</td>
                    <td><b>{o.action}</b><div className="xs muted">{o.village} · {o.why}</div></td>
                    <td className="num sm" style={{ whiteSpace: "nowrap" }}>{inr(o.cost)}</td>
                    <td className="num"><b>{o.homes}</b> <span className={`pill quiet ${EFFECT[o.effect][0]}`}><span className="d" />{EFFECT[o.effect][1]}</span></td>
                    <td className="num"><b>{o.per_lakh}</b></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
        <div className="stack">
          <div className="card">
            <div className="card-h"><h3><TrendingUp />Villages, before and after</h3></div>
            <div className="card-b stack" style={{ gap: 10 }}>
              {d.villages.map((v: any) => (
                <div key={v.village_id} className="sm">
                  <div className="row between"><b>{v.village}</b><span className="num">{v.functional} → <b>{v.after}</b> / {v.households}</span></div>
                  <div className="bar" style={{ marginTop: 5, height: 8, position: "relative" }}>
                    <i style={{ width: `${(v.after / v.households) * 100}%`, background: "color-mix(in srgb, var(--good) 45%, transparent)", position: "absolute", inset: 0, right: "auto" }} />
                    <i style={{ width: `${(v.functional / v.households) * 100}%`, position: "absolute", inset: 0, right: "auto" }} />
                  </div>
                </div>
              ))}
              <div className="xs muted">Dark: functional now. Light: after the chosen works. Measured over {d.villages[0]?.basis || "today"}.</div>
            </div>
          </div>
          <div className="card">
            <div className="card-h"><h3><IndianRupee />Unit costs used</h3><span className="pill demo">indicative</span></div>
            <div className="card-b stack" style={{ gap: 6 }}>
              {Object.entries(d.unit_costs).map(([k, v]: any) => <div key={k} className="row between sm"><span>{UNIT[k] || k}</span><b className="num">{inr(v)}</b></div>)}
              <p className="xs muted" style={{ marginTop: 6 }}>{d.method}</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

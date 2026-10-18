import { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import QRCode from "qrcode";
import { AlertTriangle, CheckCircle2, Clock, Droplets, FlaskConical, MessageSquare, Smartphone, Waves as WavesIcon } from "lucide-react";
import { api } from "../lib/api";
import { LANGS, Lang, makeT } from "../lib/i18n";
import { Drop, LiquidGauge } from "../components/ui";

// incident type -> the household's own word for the problem
const TYPE_CAT: Record<string, string> = { SUPPLY_INTERRUPTION: "no_water", LOW_PRESSURE: "low_pressure", SUSPECTED_LEAK: "leakage", QUALITY_VERIFY: "dirty_water",
  COMMUNITY_CLUSTER: "dirty_water", PUMP_FAULT: "no_water", TAP_FAULT: "tap_damage", ABNORMAL_PATTERN: "low_pressure" };

/** The village water board: a full-screen page for a TV at the Panchayat office, school or health centre,
 *  as the DDWS monitoring roadmap (2021) asks for. Public, no sign-in, refreshes itself, in the village's language. */
export function Board() {
  const { village = "VLG-PW" } = useParams();
  const [meta, setMeta] = useState<any>(null);
  const [v, setV] = useState<any>(null);
  const [err, setErr] = useState("");
  const [qr, setQr] = useState("");
  const q = new URLSearchParams(window.location.search).get("lang") as Lang | null;
  const vmeta = meta?.villages?.find((x: any) => x.id === village);
  const lang: Lang = q && LANGS.some((l) => l.code === q) ? q : (vmeta?.lang || "hi");
  const t = useMemo(() => makeT(lang), [lang]);
  const en = useMemo(() => makeT("en"), []);
  const citizenUrl = `${window.location.origin}/citizen`;

  useEffect(() => { document.documentElement.setAttribute("data-theme", "light"); api("/api/meta", { auth: false }).then(setMeta).catch(() => {}); }, []);
  useEffect(() => { QRCode.toDataURL(citizenUrl, { margin: 1, width: 260, color: { dark: "#062a4a", light: "#ffffff" } }).then(setQr).catch(() => {}); }, [citizenUrl]);
  useEffect(() => {
    const load = () => api(`/api/citizen/village/${village}`, { auth: false }).then((d) => { setV(d); setErr(""); }).catch((e) => setErr(e.message));
    load();
    const id = setInterval(load, 10000);
    return () => clearInterval(id);
  }, [village]);
  useEffect(() => { document.documentElement.lang = lang; }, [lang]);

  if (!v) return <div className="board"><div className="b-wait"><Drop className="drop" />{err || "…"}</div></div>;
  const c = v.clock;
  const on = c.in_window;
  const served = v.counts?.ok ?? 0;
  const homes = v.households;
  const qv = v.quality.status === "verify";
  const test = v.tests?.[0];
  const issues = v.issues.filter((i: any) => i.status !== "closed");
  const both = (key: string, vars?: any) => (lang === "en" ? <>{t(key, vars)}</> : <>{t(key, vars)}<small>{en(key, vars)}</small></>);

  return (
    <div className="board">
      <header className="b-top">
        <div className="row" style={{ gap: 14 }}><Drop className="drop" /><div><div className="b-vname">{v.village}</div>
          <div className="b-sub">{v.admin.gp} · {v.admin.block} · {v.admin.district}</div></div></div>
        <div className="b-title">{both("bd_title")}</div>
        <div className="row" style={{ gap: 16 }}><span className="b-demo">Simulated demo data</span>
          <div style={{ textAlign: "right" }}><div className="b-clock num">{c.time}</div><div className="b-sub">{c.date}</div></div></div>
      </header>

      <section className={`b-now ${on ? (issues.some((i: any) => i.severity === "high" || i.severity === "critical") ? "warn" : "on") : "off"}`}>
        <div className="grow">
          <div className="b-big">{on ? <Droplets /> : <WavesIcon />}{both(on ? "bd_now_on" : "bd_now_off")}</div>
          <div className="b-line">{on ? both("bd_until", { t: c.window_end }) : both("bd_next", { t: c.next_window })}</div>
          {on && <div className="b-line strong">{both("bd_homes", { n: served, m: homes })}</div>}
        </div>
        <div className="b-tank"><LiquidGauge value={v.tank_pct} size={170} label="%" tone={{ c1: "#67e8f9", c2: "#0a6fb8" }} /><div className="b-cap">{both("tank")}</div></div>
      </section>

      <div className="b-grid">
        <section className="b-card">
          <h3><Clock />{both("bd_times")}</h3>
          {(meta?.supply_windows || []).map((w: any, i: number) => (
            <div key={i} className={`b-win ${on && c.window_idx === i ? "cur" : ""}`}><b className="num">{w.start} – {w.end}</b><span>{w.label}</span></div>
          ))}
        </section>
        <section className={`b-card ${qv ? "bad" : ""}`}>
          <h3><FlaskConical />{both(qv ? "q_verify" : "q_ok")}</h3>
          {test && <div className="b-test"><span>{t("bd_tests")}</span><b>{test.kind} · {test.ts.slice(8, 10)}/{test.ts.slice(5, 7)} · {t(test.result === "pass" ? "bd_pass" : "bd_fail")}</b></div>}
        </section>
        <section className="b-card">
          <h3><CheckCircle2 />{both("functional")}</h3>
          <div className="b-pct num">{v.functional ? `${Math.round(v.functional.pct)}%` : "–"}</div>
          <div className="b-week">{v.week.map((d: any) => <i key={d.day} style={{ height: `${Math.max(6, (d.functional_pct - 50) * 2)}%`,  /* 50-100% fills the bar: small dips stay visible */ background: d.functional_pct >= 85 ? "var(--flow)" : d.functional_pct >= 70 ? "var(--low)" : "var(--dry)" }} title={`${d.day}: ${d.functional_pct}%`} />)}</div>
          <div className="b-sub">{t("last7")}</div>
        </section>
      </div>

      <div className="b-grid two">
        <section className="b-card">
          <h3><AlertTriangle />{both("issues")}</h3>
          {issues.length === 0 ? <p className="b-none">{both("none")}</p> : issues.slice(0, 4).map((i: any) => (
            <div key={i.id} className="b-issue"><b>{t(`cat_${TYPE_CAT[i.type] || "other"}`)}</b><span>{i.lane || v.village} · {i.affected} {t("homes")}</span><em>{t(`st_${i.status}`)}</em></div>
          ))}
        </section>
        <section className="b-card b-qr">
          {qr && <img src={qr} alt="QR code: JalSakhi citizen app" />}
          <div><h3><Smartphone />{both("bd_scan")}</h3><p className="b-sms"><MessageSquare />{t("bd_sms")}</p></div>
        </section>
      </div>
    </div>
  );
}

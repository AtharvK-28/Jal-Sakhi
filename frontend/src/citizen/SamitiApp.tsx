import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertTriangle, CheckCircle2, ChevronRight, Droplets, FlaskConical, IndianRupee, Languages, LogOut, ScrollText, Tv, Users, Waves as WavesIcon, Wrench } from "lucide-react";
import { api, clearSession, getSession, login } from "../lib/api";
import { LANGS, Lang, makeT } from "../lib/i18n";
import { Drop, LiquidGauge, ToastHost, Waves, toast } from "../components/ui";

// The Pani Samiti's phone: the Village Water & Sanitation Committee the problem statement names as a user,
// in the village's language. Today's water, what needs a decision (acknowledge, send the crew), upkeep that
// is due, the water charges, and the Gram Sabha report card.

const LKEY = "jalsakhi.samiti.lang";
const DEMO_USER = "vwsc.pimpalwadi";
const TYPE_CAT: Record<string, string> = { SUPPLY_INTERRUPTION: "no_water", LOW_PRESSURE: "low_pressure", SUSPECTED_LEAK: "leakage", QUALITY_VERIFY: "dirty_water",
  COMMUNITY_CLUSTER: "dirty_water", PUMP_FAULT: "no_water", TAP_FAULT: "tap_damage", ABNORMAL_PATTERN: "low_pressure", SUSPECTED_BOOSTER: "low_pressure", CITIZEN_REPORT: "other" };

export function SamitiApp() {
  const [session, setSession] = useState(getSession);
  const [lang, setLang] = useState<Lang>(() => (localStorage.getItem(LKEY) as Lang) || "mr");
  const t = useMemo(() => makeT(lang), [lang]);
  useEffect(() => { document.documentElement.setAttribute("data-theme", "light"); document.documentElement.lang = lang; localStorage.setItem(LKEY, lang); }, [lang]);
  const ok = session && session.user.role !== "citizen";
  const signIn = async () => { try { setSession(await login(DEMO_USER, "jal123")); } catch (e: any) { toast(e.message, true); } };
  return (
    <>
      <div className="ribbon"><span>Simulated demo data</span></div>
      {ok ? <Main t={t} lang={lang} setLang={setLang} village={session!.user.villages.includes("VLG-PW") ? "VLG-PW" : session!.user.villages[0]} name={session!.user.name}
        onOut={() => { clearSession(); setSession(null); }} /> : (
        <div className="phone" style={{ background: "linear-gradient(170deg,#0a5b99,#07406e 45%,#052a4b)", color: "#fff" }}>
          <div style={{ padding: "34px 22px", display: "flex", flexDirection: "column", gap: 18, flex: 1 }}>
            <div className="brand" style={{ padding: 0 }}><Drop /><div><b style={{ fontSize: 22 }}>JalSakhi</b><small>{t("sm_title")}</small></div></div>
            <div className="lang-grid">{LANGS.map((l) => <button key={l.code} className={lang === l.code ? "on" : ""} onClick={() => setLang(l.code)}>{l.name}</button>)}</div>
            <button className="btn big-btn" style={{ background: "#fff", color: "#0a5b99", marginTop: "auto" }} onClick={signIn}>{t("sm_signin")}<ChevronRight /></button>
          </div>
        </div>
      )}
      <ToastHost />
    </>
  );
}

function Main({ t, lang, setLang, village, name, onOut }: { t: any; lang: Lang; setLang: (l: Lang) => void; village: string; name: string; onOut: () => void }) {
  const [snap, setSnap] = useState<any>(null);
  const [om, setOm] = useState<any>(null);
  const [aank, setAank] = useState<any>(null);
  const [eq, setEq] = useState<any>(null);
  const [langs, setLangs] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const load = useCallback(() => {
    api(`/api/snapshot?village=${village}`).then(setSnap).catch((e) => toast(e.message, true));
    api(`/api/om?village=${village}`).then(setOm).catch(() => {});
    api(`/api/aankalan/${village}`).then(setAank).catch(() => {});
    api(`/api/villages/${village}/equity`).then(setEq).catch(() => {});
  }, [village]);
  useEffect(() => { load(); const id = setInterval(load, 6000); return () => clearInterval(id); }, [load]);
  const act = async (id: string, body: any, msg: string) => {
    setBusy(id);
    try { await api(`/api/incidents/${id}`, { method: "PATCH", body }); toast(msg); load(); } catch (e: any) { toast(e.message, true); }
    setBusy(null);
  };
  const v = snap?.focus;
  if (!v) return <div className="phone"><div className="loader" style={{ flex: 1 }}><Drop className="drop" /></div></div>;
  const c = snap.clock, k = v.kpis;
  const lane = (bid: string | null) => v.branches.find((b: any) => b.id === bid)?.name || v.name;
  const mine = (snap.incidents || []).filter((i: any) => i.village_id === village);
  const tasks = (om?.upkeep?.tasks || []).filter((x: any) => x.status !== "ok");
  const acc = om?.accounts;
  const qv = k.quality_status === "verify";

  return (
    <div className="phone">
      <header className={`c-top ${c.in_window ? (mine.some((i: any) => i.severity === "high" || i.severity === "critical") ? "s-low" : "s-ok") : "s-idle"}`}>
        <div className="row between" style={{ fontSize: 12.5 }}>
          <span className="row" style={{ gap: 7 }}><Drop className="mini-drop" /><b style={{ fontSize: 14 }}>{v.name}</b> · {t("sm_title")}</span>
          <span className="row" style={{ gap: 6 }}><span className="num" style={{ fontWeight: 700 }}>{c.time}</span>
            <button className="btn sm" style={{ background: "rgba(255,255,255,.2)", boxShadow: "none", padding: "5px 9px" }} onClick={() => setLangs(!langs)} aria-label="Language"><Languages /></button>
            <button className="btn sm" style={{ background: "rgba(255,255,255,.2)", boxShadow: "none", padding: "5px 9px" }} onClick={onOut} aria-label="Sign out"><LogOut /></button></span>
        </div>
        {langs && <div className="lang-grid" style={{ marginTop: 10 }}>{LANGS.map((l) => <button key={l.code} className={lang === l.code ? "on" : ""} onClick={() => { setLang(l.code); setLangs(false); }}>{l.name}</button>)}</div>}
        <div className="row" style={{ gap: 14, marginTop: 14, alignItems: "center" }}>
          <LiquidGauge value={k.functional?.pct ?? null} size={92} label="%" />
          <div className="grow">
            <div className="c-big" style={{ fontSize: 22 }}>{c.in_window ? <><Droplets size={20} style={{ verticalAlign: -3 }} /> {t("bd_now_on")}</> : <><WavesIcon size={20} style={{ verticalAlign: -3 }} /> {t("bd_now_off")}</>}</div>
            <div style={{ fontSize: 13.5, opacity: 0.95, marginTop: 4 }}>{c.in_window ? t("bd_homes", { n: k.counts.ok, m: k.households }) : t("bd_next", { t: c.next_window })}</div>
            <div style={{ fontSize: 12.5, opacity: 0.9, marginTop: 4 }}>{t("functional")} · {t("tank")} {Math.round(v.tank?.level_pct ?? 0)}%</div>
          </div>
        </div>
        <Waves fill="var(--bg-2)" />
      </header>
      <div className="c-body">
        <div className={`c-card row sm`} style={{ alignItems: "flex-start", color: qv ? "var(--serious)" : "var(--ink)", fontWeight: qv ? 650 : 500 }}><FlaskConical size={17} style={{ flex: "none", marginTop: 1 }} />{qv ? t("q_verify") : t("q_ok")}</div>

        <div className="c-card">
          <div className="row" style={{ marginBottom: 6 }}><AlertTriangle size={17} color="var(--serious)" /><b>{t("sm_decide")}</b></div>
          {mine.length === 0 ? <p className="sm" style={{ color: "var(--good)", fontWeight: 650 }}>{t("sm_none")}</p> : mine.slice(0, 5).map((i: any) => {
            const open = i.status === "open";
            const due = open ? i.sla_ack_due : i.sla_resolve_due;
            const late = c.iso.slice(0, 19) > (due || "").slice(0, 19);
            return (
              <div key={i.id} style={{ padding: "10px 0", borderTop: "1px solid var(--line)" }}>
                <div className="row between"><b>{i.type === "SUSPECTED_BOOSTER" ? t("sm_booster", { h: (i.scope_id || "").replace(/^[A-Z]+-/, "") }) : t(`cat_${TYPE_CAT[i.type] || "other"}`)} · {lane(i.branch_id)}</b><span className={`pill ${i.severity}`}>{i.severity}</span></div>
                <div className="xs" style={{ marginTop: 3, color: late ? "var(--crit)" : "var(--ink-2)", fontWeight: late ? 700 : 500 }}>
                  <Users size={12} style={{ verticalAlign: -2 }} /> {i.affected_count} {t("homes")} · {t(`st_${i.status}`)} · {late ? t("sm_overdue", { t: due.slice(11, 16) }) : t("sm_due", { t: due.slice(11, 16) })}</div>
                {i.why?.length > 0 && <div className="xs" style={{ marginTop: 4, color: "var(--ink-2)" }}>{i.why.map((w: string) => t(`sm_why_${w}`, { n: w === "citizen_reports" ? i.report_count : i.affected_count, s: (i.site_names || []).join(", ") })).join(" · ")}</div>}
                <div className="row" style={{ marginTop: 8, gap: 8 }}>
                  {open && <button className="btn sm" disabled={busy === i.id} onClick={() => act(i.id, { action: "acknowledge", note: "Seen by the Pani Samiti" }, t("sm_acked"))}><CheckCircle2 />{t("sm_ack")}</button>}
                  {!i.assigned_to && <button className="btn ghost sm" disabled={busy === i.id} onClick={() => act(i.id, { action: "assign", assignee: "Block repair crew" }, t("sm_assigned"))}><Wrench />{t("sm_assign")}</button>}
                </div>
              </div>
            );
          })}
        </div>

        {eq && <div className="c-card">
          <div className="row" style={{ marginBottom: 6 }}><Users size={17} color="var(--serious)" /><b>{t("sm_left_title")}</b></div>
          {eq.chronic.length === 0 ? <p className="sm muted">{t("sm_left_none")}</p> : <>
            <p className="sm">{t("sm_left_body", { n: eq.chronic.length })}</p>
            {eq.chronic.slice(0, 6).map((h: any) => <div key={h.id} className="row between sm" style={{ padding: "6px 0", borderTop: "1px solid var(--line)" }}><span><b>{h.label}</b> · {h.lane}</span><span className="num xs">{h.days_failed}/{h.of}</span></div>)}
          </>}
          {eq.dry.length > 0 && <p className="sm" style={{ color: "var(--crit)", fontWeight: 650, marginTop: 6 }}>{t("sm_dry", { n: eq.dry.length })}</p>}
        </div>}

        <div className="c-card">
          <div className="row" style={{ marginBottom: 6 }}><Wrench size={17} color="var(--brand)" /><b>{t("sm_upkeep")}</b></div>
          {tasks.length === 0 ? <p className="sm muted">{t("sm_ok_all")}</p> : tasks.slice(0, 5).map((x: any) => (
            <div key={x.id} className="row between sm" style={{ padding: "8px 0", borderTop: "1px solid var(--line)", gap: 10 }}>
              <span>{t(`tk_${x.key}`)}</span>
              <span className={`pill ${x.status === "overdue" ? "critical" : "medium"}`} style={{ flex: "none" }}>{x.days_left < 0 ? t("sm_overdue_task", { n: -x.days_left }) : t("sm_due_task", { n: x.days_left })}</span>
            </div>))}
        </div>

        {acc && <div className="c-card">
          <div className="row" style={{ marginBottom: 6 }}><IndianRupee size={17} color="var(--brand)" /><b>{t("sm_money")}</b></div>
          {(() => { const m = acc.months[acc.months.length - 1]; return m?.collection_pct != null && <div className="sm">{t("sm_collect", { p: Math.round(m.collection_pct) })}<div className="bar" style={{ margin: "6px 0 8px" }}><i style={{ width: `${m.collection_pct}%` }} /></div></div>; })()}
          {acc.homes_in_arrears > 0 && <div className="sm" style={{ color: "var(--serious)", fontWeight: 650 }}>{t("sm_arrears", { n: acc.homes_in_arrears, a: acc.arrears.toLocaleString("en-IN") })}</div>}
          {acc.recovery_pct != null && <div className="sm muted" style={{ marginTop: 4 }}>{t("sm_recover", { p: Math.round(acc.recovery_pct) })}</div>}
        </div>}

        {aank && <div className="c-card">
          <div className="row between"><div className="row"><ScrollText size={17} color="var(--brand)" /><b>{t("sm_report")}</b></div><b className="num" style={{ fontSize: 20 }}>{aank.overall != null ? `${Math.round(aank.overall)}%` : "–"}</b></div>
          <p className="sm ink2" style={{ marginTop: 6 }}>{aank.stage?.stage === "feedback" ? t("sm_stage_feedback", { n: aank.stage.days_left }) : aank.stage?.stage === "final" ? t("sm_stage_closed") : t("sm_stage_draft")}</p>
        </div>}

        <a className="btn ghost big-btn" href={`/board/${village}`} target="_blank" rel="noreferrer"><Tv />{t("sm_board")}</a>
        <div className="xs muted" style={{ textAlign: "center" }}>{name} · <a href="/app">full dashboard</a></div>
      </div>
    </div>
  );
}

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Ban, BellRing, Camera, Check, CheckCircle2, ChevronRight, Clock, CloudOff, Download, Droplets, FlaskConical, Gauge, GlassWater, Home, IndianRupee, Languages, ListChecks,
  MapPin, MessageCircle, MessageSquare, Mic, MoreHorizontal, Phone, Receipt, ScrollText, Search, Send, Smartphone, Sparkles, ThumbsDown, ThumbsUp, Users, Volume2, Wind, Wrench,
} from "lucide-react";
import { api, resolveUrl } from "../lib/api";
import { flushReports, migrateLegacyQueue, pendingCount, queueReport, shrinkPhoto } from "../lib/offline";
import { LANGS, Lang, makeT } from "../lib/i18n";
import { Drop, LiquidGauge, ToastHost, Waves, toast } from "../components/ui";
import { hhmm, n0 } from "../lib/format";

const CATS: [string, any][] = [["no_water", Ban], ["low_pressure", Gauge], ["dirty_water", GlassWater], ["leakage", Droplets], ["smell_taste", Wind], ["irregular", Clock], ["tap_damage", Wrench], ["other", MoreHorizontal]];
const STEPS = ["open", "acknowledged", "in_progress", "resolved_pending_verification", "closed"];
const TYPE_CAT: Record<string, string> = { SUPPLY_INTERRUPTION: "no_water", LOW_PRESSURE: "low_pressure", SUSPECTED_LEAK: "leakage", QUALITY_VERIFY: "dirty_water", COMMUNITY_CLUSTER: "dirty_water", PUMP_FAULT: "no_water" };
const SKEY = "jalsakhi.citizen";
const REPORT_URL = () => resolveUrl("/api/complaints");

type Saved = { lang: Lang; household: string; village: string } | null;
const load = (): Saved => { try { return JSON.parse(localStorage.getItem(SKEY) || "null"); } catch { return null; } };

export function CitizenApp() {
  const [saved, setSaved] = useState<Saved>(load);
  const [lang, setLang] = useState<Lang>(saved?.lang || "en");
  const t = useMemo(() => makeT(lang), [lang]);
  useEffect(() => { document.documentElement.setAttribute("data-theme", "light"); document.documentElement.lang = lang; }, [lang]);
  const save = (s: Saved) => { if (s) localStorage.setItem(SKEY, JSON.stringify(s)); else localStorage.removeItem(SKEY); setSaved(s); };
  return (
    <>
      <div className="ribbon"><span>Simulated demo data</span></div>
      {saved ? <Main saved={saved} t={t} lang={lang} onReset={() => save(null)} /> : <Onboard lang={lang} setLang={setLang} t={t} onDone={(household, village) => save({ lang, household, village })} />}
      <ToastHost />
    </>
  );
}

// ------------------------------------------------------------------ onboarding
function Onboard({ lang, setLang, t, onDone }: { lang: Lang; setLang: (l: Lang) => void; t: any; onDone: (hh: string, village: string) => void }) {
  const [meta, setMeta] = useState<any>(null);
  const [village, setVillage] = useState("VLG-PW");
  const [list, setList] = useState<any[]>([]);
  const [hh, setHh] = useState("PW-HH-014");
  useEffect(() => { api("/api/meta", { auth: false }).then(setMeta).catch(() => {}); }, []);
  useEffect(() => {
    api(`/api/public/households?village=${village}`, { auth: false }).then((l) => { setList(l); if (!l.some((x: any) => x.id === hh)) setHh(l[13]?.id || l[0]?.id); }).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [village]);
  return (
    <div className="phone" style={{ background: "linear-gradient(170deg,#0a5b99,#07406e 45%,#052a4b)", color: "#fff" }}>
      <div style={{ padding: "34px 22px 28px", flex: 1, display: "flex", flexDirection: "column", gap: 18 }}>
        <div className="brand" style={{ padding: 0 }}><Drop /><div><b style={{ fontSize: 22 }}>JalSakhi</b><small>Har Ghar Jal</small></div></div>
        <div><div className="row" style={{ marginBottom: 10, fontWeight: 700, fontSize: 16 }}><Languages size={19} />{t("choose_language")}</div>
          <div className="lang-grid">{LANGS.map((l) => <button key={l.code} className={lang === l.code ? "on" : ""} onClick={() => setLang(l.code)}>{l.name}</button>)}</div></div>
        <div><div className="row" style={{ marginBottom: 10, fontWeight: 700, fontSize: 16 }}><Home size={19} />{t("choose_home")}</div>
          <select className="select" style={{ color: "#0a2540", marginBottom: 9, padding: 13, fontSize: 15 }} value={village} onChange={(e) => setVillage(e.target.value)}>
            {(meta?.villages || []).map((v: any) => <option key={v.id} value={v.id}>{v.name} · {v.block}</option>)}</select>
          <select className="select" style={{ color: "#0a2540", padding: 13, fontSize: 15 }} value={hh} onChange={(e) => setHh(e.target.value)}>
            {list.map((h) => <option key={h.id} value={h.id}>{h.label} · {h.lane}</option>)}</select>
          <p style={{ fontSize: 12.5, color: "#bfe3fb", marginTop: 9 }}>{t("demo_note")}</p></div>
        <button className="btn big-btn" style={{ background: "#fff", color: "#0a5b99", marginTop: "auto" }} disabled={!hh} onClick={() => onDone(hh, village)}>{t("cont")}<ChevronRight /></button>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------------ main
function Main({ saved, t, lang, onReset }: { saved: NonNullable<Saved>; t: any; lang: Lang; onReset: () => void }) {
  const [tab, setTab] = useState<"home" | "report" | "track" | "village">(() => (new URLSearchParams(window.location.search).get("tab") === "report" ? "report" : "home"));
  const [home, setHome] = useState<any>(null);
  const [queued, setQueued] = useState(0);
  const [stale, setStale] = useState<string | null>(null);
  const recount = useCallback(() => pendingCount().then(setQueued), []);
  // the last answer is kept on the phone, so without network the app still shows what was last known
  const HKEY = `jalsakhi.citizen.home.${saved.household}`;
  const reload = useCallback(() => api(`/api/citizen/home?household_id=${saved.household}`, { auth: false })
    .then((h) => { setHome(h); setStale(null); try { localStorage.setItem(HKEY, JSON.stringify({ at: new Date().toISOString(), h })); } catch { /* full: fine */ } })
    .catch(() => {
      try {
        const c = JSON.parse(localStorage.getItem(HKEY) || "null");
        if (c) { setHome((x: any) => x || c.h); setStale(c.h.clock?.time || ""); }
      } catch { /* nothing cached */ }
    }), [saved.household, HKEY]);
  useEffect(() => { reload(); const id = setInterval(reload, 3000); return () => clearInterval(id); }, [reload]);

  // offline queue (photos included): retry whenever we come back online, and every few seconds
  useEffect(() => {
    const flush = async () => {
      if (!(await pendingCount())) return setQueued(0);
      const sent = await flushReports();
      recount();
      if (sent > 0) { toast(t("sent")); reload(); }
    };
    migrateLegacyQueue(REPORT_URL()).then(flush);
    const id = setInterval(flush, 6000);
    window.addEventListener("online", flush);
    return () => { clearInterval(id); window.removeEventListener("online", flush); };
  }, [reload, t, recount]);

  if (!home) return <div className="phone"><div className="loader" style={{ flex: 1 }}><Drop className="drop" /></div></div>;
  const TABS: [typeof tab, any, string][] = [["home", Home, t("tab_home")], ["report", MessageSquare, t("tab_report")], ["track", ListChecks, t("tab_track")], ["village", Users, t("tab_village")]];
  return (
    <div className="phone">
      {tab === "home" && <HomeTab home={home} t={t} lang={lang} goReport={() => setTab("report")} onReset={onReset} reload={reload} queued={queued} stale={stale} />}
      {tab === "report" && <ReportTab home={home} t={t} lang={lang} onQueued={recount} onDone={reload} goTrack={() => setTab("track")} />}
      {tab === "track" && <TrackTab home={home} t={t} reload={reload} />}
      {tab === "village" && <VillageTab home={home} t={t} />}
      <nav className="tabs">{TABS.map(([k, Icon, label]) => <button key={k} className={tab === k ? "on" : ""} onClick={() => setTab(k)}><Icon />{label}</button>)}</nav>
    </div>
  );
}

function Top({ home, cls = "", children }: { home: any; cls?: string; children: React.ReactNode }) {
  return (
    <header className={`c-top ${cls}`}>
      <div className="row between" style={{ fontSize: 12.5, opacity: 0.95 }}>
        <span className="row" style={{ gap: 7 }}><Drop className="mini-drop" /><b style={{ fontSize: 14 }}>{home.household.label}</b> · {home.household.lane} · {home.household.village}</span>
        <span className="num" style={{ fontWeight: 700 }}>{home.clock.time}</span>
      </div>
      {children}
      <Waves fill="var(--bg-2)" />
    </header>
  );
}

function TapArt({ state, fill }: { state: string; fill: number }) {
  const dim = state === "dry" || state === "idle" || state === "unknown";
  return (
    <svg className="tapart" viewBox="0 0 132 132" aria-hidden>
      <rect x="6" y="38" width="62" height="16" rx="8" fill="rgba(255,255,255,.55)" />
      <rect x="57" y="22" width="10" height="20" rx="3" fill="#fff" /><rect x="44" y="15" width="36" height="10" rx="5" fill="#fff" />
      <path d="M60 36 h22 a16 16 0 0 1 16 16 v16 h-16 v-14 h-22 z" fill="#fff" opacity={dim ? 0.75 : 1} />
      {state === "ok" && <><path d="M90 70 V 104" stroke="#d6f4ff" strokeWidth="9" strokeLinecap="round" /><path className="stream" d="M90 70 V 104" stroke="#fff" strokeWidth="3" strokeDasharray="5 11" strokeLinecap="round" /></>}
      {state === "low" && [0, 1].map((k) => <path key={k} className="drip slow" style={{ animationDelay: `${k * 1.3}s` }} d="M90 72 c3 5 5 7 5 10 a5 5 0 0 1 -10 0 c0 -3 2 -5 5 -10z" fill="#fff" />)}
      {state === "dry" && <path d="M82 80 l16 16 M98 80 l-16 16" stroke="#fff" strokeWidth="4" strokeLinecap="round" />}
      {state === "unknown" && <text x="90" y="100" textAnchor="middle" fontSize="30" fontWeight="800" fill="#fff">?</text>}
      {state === "idle" && <g fill="none" stroke="#fff" strokeWidth="3.4" strokeLinecap="round"><circle cx="90" cy="92" r="13" /><path d="M90 84 v8 l6 4" /></g>}
      <clipPath id="bkt"><path d="M62 104 h56 l-6 24 h-44 z" /></clipPath>
      <g clipPath="url(#bkt)"><rect x="60" y={128 - 24 * Math.min(1, fill)} width="60" height="30" fill="rgba(214,244,255,.85)" style={{ transition: "y 1s" }} /></g>
      <path d="M62 104 h56 l-6 24 h-44 z" fill="none" stroke="#fff" strokeWidth="3" strokeLinejoin="round" />
    </svg>
  );
}

// ------------------------------------------------------------------- home tab
function HomeTab({ home, t, lang, goReport, onReset, reload, queued, stale }: any) {
  const s = home.supply;
  const st = s.state;
  const [pulse, setPulse] = useState<boolean | null>(home.pulse_today);
  const alertsRef = useRef<HTMLDivElement>(null);
  // ?focus=alerts opens on the messages (the guided tour's phone frame uses it)
  useEffect(() => { if (new URLSearchParams(window.location.search).get("focus") === "alerts") setTimeout(() => alertsRef.current?.scrollIntoView({ block: "center" }), 300); }, []);
  const title = t(`${st}_t`), sub = t(`${st}_s`, { t: home.clock.next_window });
  const pct = Math.min(1, s.lpcd_today / home.lpcd_norm);
  const qv = home.quality.status === "verify" || s.quality_flag;
  const speak = () => {
    if (!("speechSynthesis" in window)) return toast("Speech is not available on this device", true);
    window.speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(`${title}. ${sub}. ${t("today")}: ${Math.round(s.lpcd_today)} ${t("per_person")}. ${qv ? t("q_verify") : t("q_ok")}`);
    u.lang = LANGS.find((l) => l.code === lang)!.speech; u.rate = 0.95;
    window.speechSynthesis.speak(u);
  };
  const answer = async (got: boolean) => {
    setPulse(got);
    try { await api("/api/pulse", { body: { household_id: home.household.id, got_water: got }, auth: false }); toast(t("pulse_thanks")); reload(); } catch (e: any) { toast(e.message, true); }
  };
  return (
    <>
      <Top home={home} cls={`s-${st}`}>
        <div className="row" style={{ gap: 12, marginTop: 14, alignItems: "center" }}>
          <TapArt state={st} fill={pct} />
          <div className="grow">
            <div className="c-big">{title}</div>
            <div style={{ fontSize: 14, opacity: 0.95, marginTop: 5 }}>{sub}</div>
            <div className="row wrap" style={{ marginTop: 10, gap: 6 }}>
              {(st === "ok" || st === "low" || st === "dry") && <span className="chip" style={{ background: "rgba(255,255,255,.2)", padding: "3px 10px", borderRadius: 99, fontSize: 11.5, fontWeight: 600 }}>{s.basis === "measured" ? t("measured") : t("estimated")}</span>}
              <button onClick={speak} className="btn sm" style={{ background: "rgba(255,255,255,.22)", boxShadow: "none" }}><Volume2 />{t("listen")}</button>
            </div>
          </div>
        </div>
      </Top>
      <div className="c-body">
        {stale !== null && <div className="note warn"><CloudOff /><span>{t("offline_view", { t: stale })}</span></div>}
        {queued > 0 && <div className="note warn"><CloudOff /><span>{t("pending", { n: queued })}</span></div>}
        <div className="c-card">
          <div className="row between"><b>{t("today")}</b><span className="muted sm">{t("goal")}</span></div>
          <div className="row" style={{ alignItems: "baseline", gap: 6, marginTop: 4 }}><span className="num" style={{ fontSize: 32, fontWeight: 760, letterSpacing: "-0.03em" }}>{Math.round(s.lpcd_today)}</span><span className="muted">{t("per_person")}</span></div>
          <div className="bar" style={{ height: 10, marginTop: 8 }}><i style={{ width: `${pct * 100}%` }} /></div>
          <div className={`row sm`} style={{ marginTop: 12, alignItems: "flex-start", color: qv ? "var(--serious)" : "var(--ink-2)", fontWeight: qv ? 650 : 500 }}><FlaskConical size={17} style={{ flex: "none", marginTop: 1 }} />{qv ? t("q_verify") : t("q_ok")}</div>
        </div>

        <div className="c-card">
          <b>{t("pulse_q")}</b>
          <div className="thumbs" style={{ marginTop: 10 }}>
            <button className={`y ${pulse === true ? "on" : ""}`} onClick={() => answer(true)}><ThumbsUp size={19} />{t("yes")}</button>
            <button className={`n ${pulse === false ? "on" : ""}`} onClick={() => answer(false)}><ThumbsDown size={19} />{t("no")}</button>
          </div>
        </div>

        <button className="btn big-btn" onClick={goReport}><MessageSquare />{t("report_btn")}</button>

        <div className="c-card" ref={alertsRef}>
          <div className="row" style={{ marginBottom: 8 }}><BellRing size={17} color="var(--brand)" /><b>{t("alerts")}</b></div>
          {home.alerts.length === 0 ? <p className="muted sm">{t("no_alerts")}</p> : home.alerts.slice(0, 6).map((a: any) => (
            <div key={a.id} className="row sm" style={{ padding: "8px 0", borderTop: "1px solid var(--line)", alignItems: "flex-start" }}>
              <span className="muted num xs" style={{ width: 38, paddingTop: 2 }}>{hhmm(a.ts)}</span><span className="grow">{t(`n_${a.kind}`, a.params || {})}</span>
            </div>))}
        </div>
        <PhoneAlerts household={home.household.id} t={t} lang={lang} />
        <InstallCard t={t} />
        <Charge c={home.charges} t={t} lang={lang} />
        <div className="c-card sm ink2"><b style={{ color: "var(--ink)" }}>{t("sms")}</b><div className="mono" style={{ marginTop: 5 }}>JAL {home.household.id} NOWATER</div>
          <button className="btn ghost sm" style={{ marginTop: 12 }} onClick={onReset}><Languages />{t("change")}</button></div>
      </div>
    </>
  );
}

// ----------------------------------------------------------------- report tab
function ReportTab({ home, t, lang, onQueued, onDone, goTrack }: any) {
  const [cat, setCat] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [ai, setAi] = useState<any>(null);
  const [photo, setPhoto] = useState<File | null>(null);
  const [preview, setPreview] = useState("");
  const [geo, setGeo] = useState<{ lat: number; lon: number } | null>(null);
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [rec, setRec] = useState(false);
  const [done, setDone] = useState<any>(null);
  const file = useRef<HTMLInputElement>(null);
  const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;

  useEffect(() => { navigator.geolocation?.getCurrentPosition((p) => setGeo({ lat: p.coords.latitude, lon: p.coords.longitude }), () => {}, { timeout: 4000 }); }, []);
  useEffect(() => {
    if (text.trim().length < 4) { setAi(null); return; }
    const id = setTimeout(() => api("/api/nlp/classify", { body: { text }, auth: false }).then(setAi).catch(() => {}), 450);
    return () => clearTimeout(id);
  }, [text]);

  const listen = () => {
    if (!SR) return toast("Voice input is not available in this browser", true);
    const r = new SR();
    r.lang = LANGS.find((l) => l.code === lang)!.speech; r.interimResults = false;
    r.onresult = (e: any) => setText((x) => `${x} ${e.results[0][0].transcript}`.trim());
    r.onend = () => setRec(false); r.onerror = () => setRec(false);
    setRec(true); r.start();
  };
  const pick = (f: File | null) => { setPhoto(f); setPreview(f ? URL.createObjectURL(f) : ""); };
  const send = async () => {
    setBusy(true);
    const fields: Record<string, string> = { household_id: home.household.id, description: text, language: lang, channel: "app", consent: "true", geo_source: geo ? "device-gps" : "registered-tap-location" };
    if (cat) fields.category = cat;
    if (geo) { fields.lat = String(geo.lat); fields.lon = String(geo.lon); }
    const small = photo ? await shrinkPhoto(photo) : null;
    try {
      const fd = new FormData();
      Object.entries(fields).forEach(([k, v]) => fd.append(k, v));
      if (small) fd.append("photo", small, "photo.jpg");
      const r = await api("/api/complaints", { form: fd, auth: false });
      setDone(r); onDone();
    } catch (e: any) {
      if (e instanceof TypeError) { // network down: keep it on the phone, photo and all, and send it when the network returns
        await queueReport(REPORT_URL(), fields, small); onQueued(); setDone({ offline: true });
      } else toast(e.message, true);
    }
    setBusy(false);
  };
  const reset = () => { setDone(null); setCat(null); setText(""); pick(null); setConsent(false); setAi(null); };

  if (done) return (
    <>
      <Top home={home}><div className="c-big" style={{ marginTop: 18 }}>{done.offline ? <CloudOff size={30} /> : <CheckCircle2 size={34} />}<div style={{ marginTop: 6 }}>{done.offline ? t("offline") : t("sent")}</div></div></Top>
      <div className="c-body">
        {!done.offline && <div className="c-card">
          <div className="muted sm">{t("tracking")}</div><div className="num" style={{ fontSize: 28, fontWeight: 760, letterSpacing: "-0.02em" }}>{done.id}</div>
          <p style={{ marginTop: 10 }}>{done.linked === "opened" ? t("linked_new") : t("linked_existing", { n: done.incident.affected_count })}</p>
          {done.ai?.category && <span className="pill ai" style={{ marginTop: 10 }}><Sparkles />{t("ai", { c: t(`cat_${done.ai.category}`) })}</span>}
        </div>}
        <button className="btn big-btn" onClick={goTrack}><ListChecks />{t("track_it")}</button>
        <button className="btn ghost big-btn" onClick={reset}>{t("another")}</button>
      </div>
    </>
  );

  return (
    <>
      <Top home={home}><div className="c-big" style={{ marginTop: 16 }}>{t("report_title")}</div></Top>
      <div className="c-body">
        <div className="cats">{CATS.map(([k, Icon]) => <button key={k} className={`cat ${cat === k ? "on" : ""}`} onClick={() => setCat(k)}><span className="e"><Icon /></span>{t(`cat_${k}`)}</button>)}</div>
        <div className="c-card">
          <label className="f" style={{ fontSize: 13 }}>{t("describe")}</label>
          <div className="row" style={{ alignItems: "flex-start" }}>
            <textarea className="input" rows={3} placeholder={t("describe_ph")} value={text} onChange={(e) => setText(e.target.value)} style={{ fontSize: 15 }} />
            <button className={`mic ${rec ? "rec" : ""}`} onClick={listen} aria-label="Speak"><Mic /></button>
          </div>
          {ai?.category && ai.category !== cat && ai.confidence >= 0.45 && (
            <button className="pill ai" style={{ marginTop: 9, border: 0, cursor: "pointer", padding: "5px 11px", fontSize: 12.5 }} onClick={() => setCat(ai.category)}><Sparkles />{t("ai", { c: t(`cat_${ai.category}`) })} · {t("use")}</button>)}
          <div className="row wrap" style={{ marginTop: 12 }}>
            <input ref={file} type="file" accept="image/*" capture="environment" hidden onChange={(e) => pick(e.target.files?.[0] || null)} />
            <button className="btn ghost sm" onClick={() => file.current?.click()}><Camera />{photo ? t("photo_added") : t("add_photo")}</button>
            {preview && <img src={preview} alt="" style={{ width: 44, height: 44, borderRadius: 10, objectFit: "cover" }} />}
            <span className="pill info" style={{ whiteSpace: "normal" }}><MapPin />{geo ? t("loc_gps") : t("loc_tap")}</span>
          </div>
        </div>
        <label className="c-card row sm" style={{ cursor: "pointer", alignItems: "flex-start" }}>
          <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} style={{ width: 20, height: 20, flex: "none", marginTop: 1 }} /><span>{t("consent")}</span></label>
        <button className="btn big-btn" disabled={busy || !consent || (!cat && text.trim().length < 4)} onClick={send}><Send />{busy ? t("sending") : t("submit")}</button>
      </div>
    </>
  );
}

// ------------------------------------------------------------------ track tab
function TrackTab({ home, t, reload }: any) {
  const [open, setOpen] = useState<string | null>(home.complaints[0]?.id || null);
  const [detail, setDetail] = useState<any>(null);
  const [q, setQ] = useState("");
  const fetchOne = useCallback((id: string) => api(`/api/complaints/track/${id}`, { auth: false }).then(setDetail).catch((e) => toast(e.message, true)), []);
  useEffect(() => { if (!open) return; fetchOne(open); const id = setInterval(() => fetchOne(open), 3000); return () => clearInterval(id); }, [open, fetchOne]);
  const confirm = async (id: string, resolved: boolean) => {
    try { await api(`/api/complaints/${id}/confirm`, { body: { resolved, rating: resolved ? 5 : 2 }, auth: false }); toast(resolved ? t("thanks") : t("reopened")); fetchOne(id); reload(); } catch (e: any) { toast(e.message, true); }
  };
  return (
    <>
      <Top home={home}><div className="c-big" style={{ marginTop: 16 }}>{t("track_title")}</div></Top>
      <div className="c-body">
        <div className="c-card row"><Search size={17} className="muted" /><input className="input" style={{ border: 0, padding: 4, boxShadow: "none" }} placeholder={t("find")} value={q} onChange={(e) => setQ(e.target.value.toUpperCase())} />
          <button className="btn sm" disabled={q.length < 6} onClick={() => setOpen(q.trim())}><ChevronRight /></button></div>
        {home.complaints.length === 0 && !detail && <div className="c-card muted">{t("no_reports")}</div>}
        {(detail && !home.complaints.some((c: any) => c.id === detail.id) ? [detail, ...home.complaints] : home.complaints).map((c: any) => {
          const d = open === c.id && detail?.id === c.id ? detail : null;
          const idx = STEPS.indexOf((d || c).status);
          return (
            <div key={c.id} className="c-card" onClick={() => setOpen(c.id)} style={{ cursor: "pointer" }}>
              <div className="row between"><b>{t(`cat_${c.category}`)}</b><span className="mono muted">{c.id}</span></div>
              <div className="muted xs">{hhmm(c.created_at)}{c.description ? ` · "${c.description}"` : ""}</div>
              <div className="steps">{STEPS.map((s, i) => <div key={s} className={`s ${i < idx || (d || c).status === "closed" ? "done" : i === idx ? "cur" : ""}`}><i>{i < idx || (d || c).status === "closed" ? <Check /> : i + 1}</i>{t(`st_${s}`)}</div>)}</div>
              {d?.incident && <div className="xs muted" style={{ marginTop: 8 }}>{d.incident.id} · {d.incident.affected_count} {t("homes")}</div>}
              {d && d.status === "resolved_pending_verification" && d.citizen_confirmed === null && (
                <div style={{ marginTop: 12 }} onClick={(e) => e.stopPropagation()}><b>{t("is_fixed")}</b>
                  <div className="thumbs" style={{ marginTop: 8 }}><button className="y" onClick={() => confirm(c.id, true)}><ThumbsUp size={18} />{t("fixed_yes")}</button><button className="n" onClick={() => confirm(c.id, false)}><ThumbsDown size={18} />{t("fixed_no")}</button></div></div>)}
              {d?.citizen_confirmed === 1 && <div className="pill good" style={{ marginTop: 10 }}><CheckCircle2 />{t("thanks")}</div>}
            </div>
          );
        })}
      </div>
    </>
  );
}

// ---------------------------------------------------------------- village tab
function VillageTab({ home, t }: any) {
  const [v, setV] = useState<any>(null);
  useEffect(() => {
    const load = () => api(`/api/citizen/village/${home.household.village_id}`, { auth: false }).then(setV).catch(() => {});
    load(); const id = setInterval(load, 5000); return () => clearInterval(id);
  }, [home.household.village_id]);
  return (
    <>
      <Top home={home}><div className="c-big" style={{ marginTop: 16 }}>{t("village_title")}</div><div style={{ opacity: 0.9, fontSize: 13 }}>{v?.village} · {v?.admin?.block}</div></Top>
      <div className="c-body">
        {!v ? <div className="c-card muted">…</div> : <>
          <div className="c-card row" style={{ gap: 16 }}>
            <LiquidGauge value={v.score} size={108} />
            <div className="grow"><div className="muted sm">{t("score")}</div>
              <div style={{ marginTop: 8 }} className="sm"><div className="row between"><span>{t("functional")}</span><b className="num">{v.functional ? `${n0(v.functional.pct)}%` : "–"}</b></div><div className="bar" style={{ margin: "5px 0 10px" }}><i style={{ width: `${v.functional?.pct || 0}%` }} /></div>
                <div className="row between"><span>{t("tank")}</span><b className="num">{v.tank_pct != null ? `${n0(v.tank_pct)}%` : "–"}</b></div><div className="bar" style={{ marginTop: 5 }}><i style={{ width: `${v.tank_pct || 0}%` }} /></div></div></div>
          </div>
          <ReportCard household={home.household.id} t={t} />
          <div className="c-card"><div className={`row sm`} style={{ alignItems: "flex-start", color: v.quality.status === "verify" ? "var(--serious)" : "var(--ink)" }}><FlaskConical size={17} style={{ flex: "none", marginTop: 1 }} /><b>{v.quality.status === "verify" ? t("q_verify") : t("q_ok")}</b></div></div>
          <div className="c-card"><b>{t("issues")}</b>
            {v.issues.length === 0 ? <p className="muted sm" style={{ marginTop: 6 }}>{t("none")}</p> : v.issues.map((i: any) => (
              <div key={i.id} className="row between sm" style={{ padding: "9px 0", borderTop: "1px solid var(--line)", marginTop: 8 }}>
                <div><b>{t(`cat_${TYPE_CAT[i.type] || "other"}`)}</b><div className="muted xs">{i.lane || v.village} · {i.affected} {t("homes")}</div></div>
                <span className="pill info">{t(`st_${i.status}`)}</span></div>))}
          </div>
          <div className="c-card"><b>{t("last7")}</b>
            <div className="row" style={{ alignItems: "flex-end", gap: 6, height: 76, marginTop: 10 }}>
              {v.week.map((d: any) => <div key={d.day} style={{ flex: 1, textAlign: "center" }}><div style={{ height: `${Math.max(6, (d.functional_pct / 100) * 56)}px`, width: 22, margin: "0 auto", borderRadius: "4px 4px 0 0", background: d.functional_pct >= 85 ? "var(--flow)" : d.functional_pct >= 70 ? "var(--low)" : "var(--dry)" }} title={`${d.functional_pct}%`} /><div className="xs muted num" style={{ marginTop: 3 }}>{Math.round(d.functional_pct)}</div></div>)}
            </div>
            <div className="xs muted" style={{ marginTop: 4 }}>{t("functional")} (%)</div></div>
          {home.contacts?.length > 0 && <div className="c-card">
            <div className="row" style={{ marginBottom: 6 }}><Phone size={17} color="var(--brand)" style={{ flex: "none" }} /><b>{t("contacts")}</b></div>
            {home.contacts.map((c: any) => <div key={c.role} className="row between sm" style={{ padding: "8px 0", borderTop: "1px solid var(--line)", gap: 10 }}><span>{t(`c_${c.role}`)}</span><span className="mono muted" style={{ flex: "none" }}>{c.phone}</span></div>)}
          </div>}
        </>}
      </div>
    </>
  );
}

/** Link this household's alerts to Telegram or WhatsApp, so they arrive when the app is closed. */
function PhoneAlerts({ household, t, lang }: { household: string; t: any; lang: Lang }) {
  const [st, setSt] = useState<any>(null);
  const [link, setLink] = useState<any>(null);
  const load = useCallback(() => api(`/api/citizen/alerts?household_id=${household}`, { auth: false }).then(setSt).catch(() => {}), [household]);
  useEffect(() => { load(); const id = setInterval(load, 8000); return () => clearInterval(id); }, [load]);
  if (!st) return null;
  const make = async () => {
    try {
      const r = await api("/api/citizen/alerts/link", { body: { household_id: household, lang }, auth: false });
      setLink(r);
      if (r.telegram) window.open(r.telegram.url, "_blank", "noopener");
      else if (r.whatsapp) window.open(r.whatsapp.url, "_blank", "noopener");
    } catch (e: any) { toast(e.message, true); }
  };
  const on = st.linked.map((x: any) => (x.channel === "telegram" ? "Telegram" : x.channel === "whatsapp" ? "WhatsApp" : "SMS")).join(", ");
  return (
    <div className="c-card">
      <div className="row" style={{ marginBottom: 6 }}><Smartphone size={17} color="var(--brand)" style={{ flex: "none" }} /><b>{t("ph_title")}</b></div>
      {on ? <div className="pill good" style={{ whiteSpace: "normal" }}><CheckCircle2 />{t("ph_on", { c: on })}</div> : <p className="sm ink2">{t("ph_body")}</p>}
      {!on && <button className="btn sm" style={{ marginTop: 10 }} onClick={make}><BellRing />{t("ph_btn")}</button>}
      {link && !on && <div className="row wrap" style={{ marginTop: 10, gap: 8 }}>
        {link.telegram && <a className="btn ghost sm" href={link.telegram.url} target="_blank" rel="noreferrer"><Send />{t("ph_open_tg")}</a>}
        {link.whatsapp && <a className="btn ghost sm" href={link.whatsapp.url} target="_blank" rel="noreferrer"><MessageCircle />{t("ph_open_wa")}</a>}
        {!link.live && <span className="xs muted">{t("ph_off", { c: link.code })}</span>}
      </div>}
    </div>
  );
}

/** Offer installation where the browser allows it; an installed app opens without network. */
function InstallCard({ t }: { t: any }) {
  const [can, setCan] = useState<boolean>(() => !!(window as any).__installPrompt);
  useEffect(() => { const h = () => setCan(true); window.addEventListener("jalsakhi:installable", h); return () => window.removeEventListener("jalsakhi:installable", h); }, []);
  if (!can || window.matchMedia("(display-mode: standalone)").matches) return null;
  const install = async () => {
    const e = (window as any).__installPrompt;
    if (!e) return;
    e.prompt();
    await e.userChoice.catch(() => null);
    (window as any).__installPrompt = null;
    setCan(false);
  };
  return (
    <div className="c-card row" style={{ alignItems: "flex-start", gap: 12 }}>
      <img src="/icons/icon-192.png" alt="" width={44} height={44} style={{ borderRadius: 11, flex: "none" }} />
      <div className="grow"><b>{t("inst_title")}</b><p className="sm ink2" style={{ marginTop: 3 }}>{t("inst_body")}</p>
        <button className="btn sm" style={{ marginTop: 9 }} onClick={install}><Download />{t("inst_btn")}</button></div>
    </div>
  );
}

/** What this household owes for water, and its last receipt. */
function Charge({ c, t, lang }: { c: any; t: any; lang: Lang }) {
  if (!c || c.tariff == null) return null;
  const due = c.due > 0;
  const on = (d: string) => new Date(`${d}T00:00:00`).toLocaleDateString(LANGS.find((l) => l.code === lang)!.speech, { day: "numeric", month: "short", year: "numeric" });
  return (
    <div className="c-card">
      <div className="row between"><div className="row"><IndianRupee size={17} color="var(--brand)" style={{ flex: "none" }} /><b>{t("charge_title")}</b></div><span className="muted sm">{t("charge_month", { a: n0(c.tariff) })}</span></div>
      <div className="row sm" style={{ marginTop: 8, fontWeight: 650, color: due ? "var(--serious)" : "var(--good)" }}>{due ? <Receipt size={16} style={{ flex: "none" }} /> : <CheckCircle2 size={16} style={{ flex: "none" }} />}{due ? t("charge_due", { a: n0(c.due), n: c.months_due.length }) : t("charge_clear")}</div>
      {c.last_receipt && <div className="xs muted" style={{ marginTop: 5 }}>{t("charge_receipt", { id: c.last_receipt.id, d: on(c.last_receipt.on) })}</div>}
      {due && <div className="xs muted" style={{ marginTop: 5 }}>{t("charge_note")}</div>}
    </div>
  );
}

/** The Gram Panchayat's assessment once the Gram Sabha has endorsed it: every household may agree or disagree for 30 days. */
function ReportCard({ household, t }: { household: string; t: any }) {
  const [a, setA] = useState<any>(null);
  const [why, setWhy] = useState("");
  const [busy, setBusy] = useState(false);
  const load = useCallback(() => api(`/api/citizen/aankalan?household_id=${household}`, { auth: false }).then(setA).catch(() => {}), [household]);
  useEffect(() => { load(); const id = setInterval(load, 8000); return () => clearInterval(id); }, [load]);
  if (!a || a.stage === "draft") return null;
  const answer = async (agree: boolean) => {
    setBusy(true);
    try { await api("/api/citizen/aankalan", { body: { household_id: household, agree, comment: why }, auth: false }); toast(t("aank_thanks")); setWhy(""); load(); } catch (e: any) { toast(e.message, true); }
    setBusy(false);
  };
  return (
    <div className="c-card">
      <div className="row between"><div className="row"><ScrollText size={17} color="var(--brand)" style={{ flex: "none" }} /><b>{t("aank_title")}</b></div>
        <span className="num" style={{ fontSize: 20, fontWeight: 760 }} title={t("aank_overall")}>{a.overall != null ? `${n0(a.overall)}%` : "–"}</span></div>
      <div className="sm" style={{ marginTop: 10 }}>
        {a.sections.map((x: any) => (
          <div key={x.key} style={{ marginBottom: 9 }}>
            <div className="row between"><span>{t(`sec_${x.key}`)}</span><b className="num">{x.score != null ? `${n0(x.score)}%` : "–"}</b></div>
            <div className="bar" style={{ marginTop: 4 }}><i style={{ width: `${x.score || 0}%` }} /></div>
          </div>))}
      </div>
      {a.stage === "feedback" ? <>
        <p className="sm" style={{ marginTop: 4 }}>{t("aank_intro")}</p>
        <div className="xs muted">{t("aank_days", { n: a.days_left })}</div>
        <input className="input" style={{ marginTop: 9 }} placeholder={t("aank_comment_ph")} value={why} maxLength={300} onChange={(e) => setWhy(e.target.value)} />
        <div className="thumbs" style={{ marginTop: 9 }}>
          <button className={`y ${a.mine === true ? "on" : ""}`} disabled={busy} onClick={() => answer(true)}><ThumbsUp size={18} />{t("aank_agree")}</button>
          <button className={`n ${a.mine === false ? "on" : ""}`} disabled={busy} onClick={() => answer(false)}><ThumbsDown size={18} />{t("aank_disagree")}</button>
        </div>
      </> : <p className="sm muted" style={{ marginTop: 4 }}>{t("aank_closed")}</p>}
      {a.responses > 0 && <div className="xs muted" style={{ marginTop: 9 }}>{t("aank_tally", { n: a.responses, p: n0((a.agree / a.responses) * 100) })}</div>}
    </div>
  );
}

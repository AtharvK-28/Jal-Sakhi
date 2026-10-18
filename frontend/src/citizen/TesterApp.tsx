import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, ArrowLeft, Camera, CheckCircle2, ChevronRight, Clock, FlaskConical, Languages, LogOut, MapPin, Sparkles, TestTubeDiagonal, XCircle } from "lucide-react";
import { api, clearSession, getSession, login, resolveUrl } from "../lib/api";
import { LANGS, Lang, makeT } from "../lib/i18n";
import { shrinkPhoto } from "../lib/offline";
import { Drop, ToastHost, Waves, toast } from "../components/ui";

// The Jal Sakhi's phone: the five women JJM trains in each village to test water with the field test kit.
// The day's list comes from the risk model (where water is most likely to be unsafe); a result is entered by
// tapping the colour the kit shows, and a failure goes to the lab, WQMIS and the households automatically.

const LKEY = "jalsakhi.tester.lang";
const DEMO_USER = "jalsakhi.pimpalwadi";

// Approximate kit-chart colours, one per chart step. The kit's own printed chart is the reference.
const lerp = (a: string, b: string, f: number) => {
  const p = (h: string) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
  const [x, y] = [p(a), p(b)];
  return `rgb(${x.map((v, i) => Math.round(v + (y[i] - v) * f)).join(",")})`;
};
const RAMP: Record<string, [string, string]> = {
  alkalinity_mgl: ["#f6f1c9", "#2f7a5e"], chloride_mgl: ["#f7f7f2", "#b8892e"], hardness_mgl: ["#3b6fd8", "#a1325a"],
  nitrate_mgl: ["#fbf6f8", "#c2185b"], fluoride_mgl: ["#c7364f", "#f3e3b5"], iron_mgl: ["#fbf7f0", "#c0392b"],
};
const FIXED: Record<string, string[]> = {
  ph: ["#e8572a", "#f08a2c", "#f4b63a", "#d8cf3c", "#8cc152", "#3fae7a", "#2f8fa8", "#4b5fae"],
  chlorine_mgl: ["#ffffff", "#fbe1ec", "#f6b8d2", "#e86aa4", "#c2185b", "#8e0e46"],
};
const swatch = (key: string, i: number, n: number) => FIXED[key]?.[i] ?? lerp(RAMP[key][0], RAMP[key][1], n > 1 ? i / (n - 1) : 0);

export function TesterApp() {
  const [session, setSession] = useState(getSession);
  const [lang, setLang] = useState<Lang>(() => (localStorage.getItem(LKEY) as Lang) || "mr");
  const t = useMemo(() => makeT(lang), [lang]);
  useEffect(() => { document.documentElement.setAttribute("data-theme", "light"); document.documentElement.lang = lang; localStorage.setItem(LKEY, lang); }, [lang]);
  const staff = session && session.user.role !== "citizen";
  const signIn = async () => { try { setSession(await login(DEMO_USER, "jal123")); } catch (e: any) { toast(e.message, true); } };

  return (
    <>
      <div className="ribbon"><span>Simulated demo data</span></div>
      {staff ? <Main t={t} lang={lang} setLang={setLang} village={session!.user.villages[0]} name={session!.user.name} onOut={() => { clearSession(); setSession(null); }} />
        : (
          <div className="phone" style={{ background: "linear-gradient(170deg,#0a5b99,#07406e 45%,#052a4b)", color: "#fff" }}>
            <div style={{ padding: "34px 22px", display: "flex", flexDirection: "column", gap: 18, flex: 1 }}>
              <div className="brand" style={{ padding: 0 }}><Drop /><div><b style={{ fontSize: 22 }}>JalSakhi</b><small>{t("ts_title")}</small></div></div>
              <p style={{ color: "#d3ecfd", lineHeight: 1.6 }}>Jal Jeevan Mission trains five women in every village to test drinking water with a field test kit. This is their phone.</p>
              <button className="btn big-btn" style={{ background: "#fff", color: "#0a5b99", marginTop: "auto" }} onClick={signIn}>Sign in as the Pimpalwadi Jal Sakhi (demo)<ChevronRight /></button>
            </div>
          </div>
        )}
      <ToastHost />
    </>
  );
}

function spName(t: any, sp: string) {
  if (sp === "Tank outlet") return t("sp_tank");
  const m = sp.match(/^(.*) tail-end tap$/);
  return m ? t("sp_tail", { lane: m[1] }) : sp;
}

function Main({ t, lang, setLang, village, name, onOut }: { t: any; lang: Lang; setLang: (l: Lang) => void; village: string; name: string; onOut: () => void }) {
  const [plan, setPlan] = useState<any>(null);
  const [tests, setTests] = useState<any[]>([]);
  const [testing, setTesting] = useState<any>(null);
  const [done, setDone] = useState<any>(null);
  const [langs, setLangs] = useState(false);
  const load = useCallback(() => {
    api(`/api/quality/plan?village=${village}`).then(setPlan).catch((e) => toast(e.message, true));
    api(`/api/quality?village=${village}`).then((q) => setTests(q.tests.filter((x: any) => x.kind === "FTK"))).catch(() => {});
  }, [village]);
  useEffect(() => { load(); const id = setInterval(load, 8000); return () => clearInterval(id); }, [load]);
  const h2s = async (id: string, positive: boolean) => {
    try { const r = await api(`/api/quality/tests/${id}/h2s`, { method: "PATCH", body: { positive } }); setDone(r); load(); } catch (e: any) { toast(e.message, true); }
  };

  if (!plan) return <div className="phone"><div className="loader" style={{ flex: 1 }}><Drop className="drop" /></div></div>;
  if (done) return <Result r={done} t={t} onBack={() => { setDone(null); setTesting(null); load(); }} />;
  if (testing) return <TestForm sp={testing} params={plan.params} village={village} t={t} onBack={() => setTesting(null)} onSaved={(r) => setDone(r)} />;
  const today = plan.points.filter((p: any) => p.today);
  const rest = plan.points.filter((p: any) => !p.today);
  const pending = tests.filter((x) => x.result === "pending");

  return (
    <div className="phone">
      <header className="c-top">
        <div className="row between" style={{ fontSize: 12.5 }}>
          <span className="row" style={{ gap: 7 }}><Drop className="mini-drop" /><b style={{ fontSize: 14 }}>{plan.village}</b> · {name}</span>
          <span className="row" style={{ gap: 6 }}>
            <button className="btn sm" style={{ background: "rgba(255,255,255,.2)", boxShadow: "none", padding: "5px 9px" }} onClick={() => setLangs(!langs)} aria-label="Language"><Languages /></button>
            <button className="btn sm" style={{ background: "rgba(255,255,255,.2)", boxShadow: "none", padding: "5px 9px" }} onClick={onOut} aria-label={t("ts_logout")}><LogOut /></button>
          </span>
        </div>
        {langs && <div className="lang-grid" style={{ marginTop: 10 }}>{LANGS.map((l) => <button key={l.code} className={lang === l.code ? "on" : ""} onClick={() => { setLang(l.code); setLangs(false); }}>{l.name}</button>)}</div>}
        <div className="c-big" style={{ marginTop: 14 }}><FlaskConical size={26} style={{ verticalAlign: -4, marginRight: 6 }} />{t("ts_title")}</div>
        <Waves fill="var(--bg-2)" />
      </header>
      <div className="c-body">
        {pending.length > 0 && <div className="c-card" style={{ borderColor: "var(--warn)" }}>
          <div className="row" style={{ marginBottom: 6 }}><Clock size={17} color="var(--warn)" /><b>{t("ts_pending")}</b></div>
          {pending.map((x) => (
            <div key={x.id} style={{ padding: "8px 0", borderTop: "1px solid var(--line)" }}>
              <div className="sm"><b>{spName(t, x.sample_point)}</b> <span className="muted">· {x.id}</span></div>
              <div className="thumbs" style={{ marginTop: 8 }}>
                <button className="y" onClick={() => h2s(x.id, false)}>{t("ts_h2s_clear")}</button>
                <button className="n" onClick={() => h2s(x.id, true)}>{t("ts_h2s_black")}</button>
              </div>
            </div>))}
        </div>}

        <div className="c-card row" style={{ gap: 8, padding: "10px 14px" }}><Sparkles size={17} color="var(--brand)" /><b>{t("ts_today")}</b></div>
        {today.length === 0 && <div className="c-card muted">{t("ts_none")}</div>}
        {today.map((p: any, i: number) => <PointCard key={p.name} p={p} i={i + 1} t={t} onStart={() => setTesting(p)} hot />)}
        <div className="muted sm" style={{ marginTop: 6 }}>{t("ts_others")}</div>
        {rest.map((p: any) => <PointCard key={p.name} p={p} t={t} onStart={() => setTesting(p)} />)}

        {tests.length > 0 && <div className="c-card">
          <b>{t("ts_recent")}</b>
          {tests.slice(0, 6).map((x) => (
            <div key={x.id} className="row between sm" style={{ padding: "8px 0", borderTop: "1px solid var(--line)", marginTop: 6 }}>
              <span>{spName(t, x.sample_point)}<div className="xs muted">{x.id} · {x.ts.slice(11, 16)}</div></span>
              <span className={`pill ${x.result === "pass" ? "good" : x.result === "pending" ? "medium" : "critical"}`}>{x.result === "pass" ? t("ts_pass") : x.result === "pending" ? t("ts_pending") : t("ts_fail")}</span>
            </div>))}
        </div>}
      </div>
    </div>
  );
}

function PointCard({ p, i, t, onStart, hot }: { p: any; i?: number; t: any; onStart: () => void; hot?: boolean }) {
  return (
    <div className="c-card" style={hot ? { borderColor: p.score >= 50 ? "var(--crit)" : "var(--warn)", boxShadow: "inset 4px 0 0 " + (p.score >= 50 ? "var(--crit)" : "var(--warn)") } : undefined}>
      <div className="row between" style={{ alignItems: "flex-start" }}>
        <div className="row" style={{ alignItems: "flex-start", gap: 10 }}>
          {i && <span className="tst-rank">{i}</span>}
          <div><b style={{ fontSize: 15 }}><MapPin size={14} style={{ verticalAlign: -2 }} /> {spName(t, p.name)}</b>
            <div className="xs muted">{t("ts_score")} {p.score}/100</div></div>
        </div>
        <button className="btn sm" onClick={onStart}><TestTubeDiagonal />{t("ts_start")}</button>
      </div>
      <div className="bar" style={{ marginTop: 9, height: 6 }}><i style={{ width: `${p.score}%`, background: p.score >= 50 ? "var(--crit)" : p.score >= 25 ? "var(--warn)" : "var(--flow)" }} /></div>
      {hot && <ul className="tst-why">{p.reasons.slice(0, 3).map((r: any, k: number) => <li key={k}>{t(`rs_${r.code}`, r)}</li>)}</ul>}
    </div>
  );
}

function TestForm({ sp, params, village, t, onBack, onSaved }: { sp: any; params: any[]; village: string; t: any; onBack: () => void; onSaved: (r: any) => void }) {
  const [v, setV] = useState<Record<string, any>>({ h2s_positive: null });
  const [photo, setPhoto] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const file = useRef<HTMLInputElement>(null);
  const focus = new Set(sp.focus || []);
  const demo = async () => {
    try { const r = await api(`/api/quality/ftk-sample?village=${village}&point=${encodeURIComponent(sp.name)}`); setV(r.params); } catch (e: any) { toast(e.message, true); }
  };
  const save = async () => {
    setBusy(true);
    try {
      const r = await api("/api/quality/tests", { body: { village_id: village, sample_point: sp.name, kind: "FTK", params: v } });
      if (photo) {
        const fd = new FormData(); fd.append("photo", await shrinkPhoto(photo), "kit.jpg");
        await api(`/api/quality/tests/${r.id}/photo`, { form: fd }).catch(() => toast("Photo not saved", true));
      }
      onSaved(r);
    } catch (e: any) { toast(e.message, true); }
    setBusy(false);
  };
  const filled = params.filter((p) => v[p.key] != null).length;

  return (
    <div className="phone">
      <header className="c-top">
        <button className="btn sm" style={{ background: "rgba(255,255,255,.2)", boxShadow: "none" }} onClick={onBack}><ArrowLeft />{t("ts_back")}</button>
        <div className="c-big" style={{ marginTop: 12 }}>{spName(t, sp.name)}</div>
        <div style={{ opacity: 0.9, fontSize: 13, marginTop: 4 }}>{t("ts_kit")}</div>
        <Waves fill="var(--bg-2)" />
      </header>
      <div className="c-body">
        <button className="btn soft sm" onClick={demo}><Sparkles />{t("ts_demo")}</button>
        {params.map((p) => (
          <div key={p.key} className="c-card" style={focus.has(p.key) ? { borderColor: "var(--brand)" } : undefined}>
            <div className="row between"><b>{t(`p_${p.key}`)}</b><span className="xs muted">{p.unit}{focus.has(p.key) ? " · ★" : ""}</span></div>
            <div className="kit">{p.steps.map((s: number, i: number) => (
              <button key={s} className={v[p.key] === s ? "on" : ""} onClick={() => setV({ ...v, [p.key]: s })} aria-label={`${s} ${p.unit}`}>
                <i style={{ background: swatch(p.key, i, p.steps.length) }} /><span>{s}</span>
              </button>))}</div>
          </div>
        ))}
        <div className="c-card" style={focus.has("h2s_positive") ? { borderColor: "var(--brand)" } : undefined}>
          <b>{t("ts_h2s")}</b>
          <div className="kit h2s">
            {([[null, t("ts_h2s_set"), "#f2f6f9"], [false, t("ts_h2s_clear"), "#f7f3e6"], [true, t("ts_h2s_black"), "#1d1d1d"]] as [boolean | null, string, string][]).map(([val, label, c]) => (
              <button key={String(val)} className={v.h2s_positive === val ? "on" : ""} onClick={() => setV({ ...v, h2s_positive: val })}><i style={{ background: c }} /><span>{label}</span></button>))}
          </div>
        </div>
        <div className="c-card row wrap">
          <input ref={file} type="file" accept="image/*" capture="environment" hidden onChange={(e) => setPhoto(e.target.files?.[0] || null)} />
          <button className="btn ghost sm" onClick={() => file.current?.click()}><Camera />{photo ? t("ts_photo_added") : t("ts_photo")}</button>
          <span className="xs muted">{t("ts_chart_note")}</span>
        </div>
        <button className="btn big-btn" disabled={busy || filled === 0} onClick={save}><CheckCircle2 />{t("ts_submit")} · {filled}/8</button>
      </div>
    </div>
  );
}

function Result({ r, t, onBack }: { r: any; t: any; onBack: () => void }) {
  const fail = r.result === "fail", pend = r.result === "pending";
  return (
    <div className="phone">
      <header className={`c-top ${fail ? "s-dry" : pend ? "s-low" : "s-ok"}`}>
        <div className="c-big" style={{ marginTop: 16 }}>{fail ? <XCircle size={30} /> : pend ? <Clock size={30} /> : <CheckCircle2 size={30} />}
          <div style={{ marginTop: 6 }}>{fail ? t("ts_fail") : pend ? t("ts_pending") : t("ts_pass")}</div></div>
        <div style={{ opacity: 0.95, marginTop: 6 }}>{spName(t, r.sample_point)} · {r.id}</div>
        <Waves fill="var(--bg-2)" />
      </header>
      <div className="c-body">
        <div className={`note ${fail ? "warn" : ""}`}>{fail ? <AlertTriangle /> : <CheckCircle2 />}<span>{fail ? t("ts_failnext") : pend ? t("ts_pendnext") : t("ts_passnext")}</span></div>
        <div className="c-card">
          {(r.checks || []).map((c: any) => (
            <div key={c.key} className="row between sm" style={{ padding: "7px 0", borderTop: "1px solid var(--line)" }}>
              <span>{c.key === "h2s_positive" ? t("ts_h2s") : t(`p_${c.key}`)}</span>
              <span className={`pill ${c.status === "ok" ? "good" : c.status === "caution" ? "medium" : c.status === "pending" ? "info" : "critical"}`} title={c.note}>
                {c.key === "h2s_positive" ? (c.value === null ? t("ts_h2s_set") : c.value ? t("ts_h2s_black") : t("ts_h2s_clear")) : c.value}
                {c.status === "caution" ? " ⚠" : ""}</span>
            </div>))}
          {r.checks?.some((c: any) => c.status === "caution") && <p className="xs muted" style={{ marginTop: 8 }}>⚠ {t("ts_caution")}</p>}
        </div>
        {r.photo && <img src={resolveUrl(r.photo)} alt="" style={{ width: "100%", borderRadius: 14 }} />}
        <button className="btn big-btn" onClick={onBack}>{t("ts_back")}</button>
      </div>
    </div>
  );
}

import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowLeft, ArrowRight, CheckCircle2, Loader2, PlayCircle, RotateCcw, X } from "lucide-react";
import { api } from "../lib/api";
import { useLive } from "../lib/live";

// The guided tour: one simulated leak followed through the whole system in eight live steps, for judges and
// for the film. Every step acts on the running platform (inject, acknowledge, repair, test, close); nothing is canned.
// Start it with ?tour=1 on any staff page, or from the Demo drawer.

const KEY = "jalsakhi.tour";
const VILLAGE = "VLG-PW";
const LANE = "PW-B2"; // School Road: the lane the leak scenario breaks
const HOME = "PW-HH-029"; // a family on that lane, shown in the phone frame
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

type Ctx = { inc: string | null; setInc: (id: string) => void; say: (s: string) => void };
type Step = { title: string; body: string; route?: (c: Ctx) => string; phone?: boolean; run?: (c: Ctx) => Promise<void> };

async function findIncident(): Promise<string | null> {
  const open = await api("/api/alerts");
  const hit = open.find((i: any) => i.village_id === VILLAGE && i.branch_id === LANE && ["SUSPECTED_LEAK", "LOW_PRESSURE", "ABNORMAL_PATTERN"].includes(i.type));
  return hit?.id || null;
}

const STEPS: Step[] = [
  { title: "One leak, start to finish", route: () => "/app",
    body: "This tour breaks a pipe in the simulated village of Pimpalwadi and follows it through JalSakhi: detection, alerts, the household, the repair, the proof and the sync to JJM platforms. Every step runs live on this server." },
  { title: "A pipe starts leaking", route: () => "/app/twin",
    body: "A leak of about 30 litres a minute has just opened on School Road (simulated). The twin draws all 100 homes from 31 sensors. Watch School Road: flow rises at the lane entry while pressure falls towards the tail.",
    run: async (c) => {
      c.say("Resetting the demo and injecting the leak…");
      await api("/api/demo/reset", { method: "POST" });
      await api("/api/demo/clock", { body: { action: "speed", speed: 2 } });
      await api("/api/demo/scenario/leak", { body: { village_id: VILLAGE } });
      for (let i = 0; i < 40; i++) {
        const id = await findIncident();
        if (id) { c.setInc(id); c.say(`Detected: ${id}`); return; }
        c.say(`Watching the lane… ${i + 1} s`);
        await sleep(1000);
      }
      c.say("Not detected yet: the supply window may have closed. Press Next to continue anyway.");
    } },
  { title: "Detected and placed, before anyone called", route: (c) => (c.inc ? `/app/incidents/${c.inc}` : "/app/incidents"),
    body: "The models raised the incident on their own: what was observed, the suspected cause (not confirmed), the pipe segment between two homes, how many households are affected, a priority score with its reasons, and an SLA clock that escalates to the block if nobody acts." },
  { title: "The right phones buzz", route: () => "/app/alerts",
    body: "At the same moment the operator and the Pani Samiti got the alert, with Acknowledge and Start-work buttons. With a Telegram bot token on the server these are real messages; here the seeded DEMO numbers stay in sandbox, shown but never sent." },
  { title: "The family on that lane is told, in Marathi", route: () => "/app/twin", phone: true,
    body: "Households on School Road see it in their own language without asking: a possible leak in their lane, repair being arranged. They can reply with a photo, their location, or by voice, and the report joins this same incident." },
  { title: "Acknowledged, repaired, not yet closed", route: (c) => (c.inc ? `/app/incidents/${c.inc}` : "/app/incidents"),
    body: "The operator acknowledges, the block crew is assigned and records the repair. Watch the timeline. The incident moves to 'repaired, awaiting proof': JalSakhi does not take a repair note as proof that water is back.",
    run: async (c) => {
      if (!c.inc) return;
      const url = `/api/incidents/${c.inc}`;
      c.say("Operator acknowledging…");
      await api(url, { method: "PATCH", body: { action: "acknowledge", note: "Seen on the phone alert" } }).catch(() => {});
      await api(url, { method: "PATCH", body: { action: "assign", assignee: "Block repair crew" } }).catch(() => {});
      await sleep(900);
      c.say("Crew recording the repair…");
      await api(url, { method: "PATCH", body: { action: "repair", note: "Repair clamp fitted on School Road" } }).catch((e) => c.say(e.message));
      c.say("Repair recorded. Waiting for proof.");
    } },
  { title: "Closed on evidence", route: (c) => (c.inc ? `/app/incidents/${c.inc}` : "/app/incidents"),
    body: "Two proofs close a leak: pressure back on the lane, and a field test downstream that passes, because a broken pipe in a main that stands empty between supplies can draw dirt in. Only with both does the incident close.",
    run: async (c) => {
      if (!c.inc) return;
      const url = `/api/incidents/${c.inc}`;
      await api("/api/demo/clock", { body: { action: "speed", speed: 5 } });
      for (let i = 0; i < 45; i++) {
        const d = await api(url);
        if (d.recovered_at) break;
        c.say(`Waiting for pressure to recover on School Road… ${i + 1} s`);
        await sleep(1000);
      }
      c.say("Pressure is back. The Jal Sakhi tests a tap downstream with the field kit (9 parameters)…");
      await api("/api/quality/tests", { body: { village_id: VILLAGE, sample_point: "School Road tail-end tap", kind: "FTK", incident_id: c.inc,
        params: { ph: 7.5, alkalinity_mgl: 200, chloride_mgl: 100, hardness_mgl: 200, nitrate_mgl: 10, fluoride_mgl: 0.5, iron_mgl: 0.1, chlorine_mgl: 0.5, h2s_positive: false } } }).catch(() => {});
      await sleep(800);
      try { await api(url, { method: "PATCH", body: { action: "close" } }); c.say("Closed: telemetry recovered and the field test passed."); }
      catch (e: any) { c.say(`Not closed yet: ${e.message}`); }
      await api("/api/demo/clock", { body: { action: "speed", speed: 1 } });
    } },
  { title: "Synced to IMIS, Sujal Gaon and WQMIS", route: () => "/app/integration",
    body: "Every state of the incident, the water test and the citizen reports went out through the outbox, keyed by the scheme's Sujal Gaon ID and shaped for each platform. Nobody typed anything twice. (Sandbox: nothing reaches a government system.) That is the whole loop." },
];

function load(): { step: number; inc: string | null } | null {
  try { return JSON.parse(sessionStorage.getItem(KEY) || "null"); } catch { return null; }
}

export function startTour() {
  sessionStorage.setItem(KEY, JSON.stringify({ step: 0, inc: null }));
  window.dispatchEvent(new Event("jalsakhi:tour"));
}

export function Tour() {
  const nav = useNavigate();
  const { setScope } = useLive();
  const [st, setSt] = useState(load);
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const ran = useRef<Set<number>>(new Set());  // each action runs once per tour, even when stepping back

  useEffect(() => {
    const h = () => { ran.current.clear(); setSt(load()); };
    window.addEventListener("jalsakhi:tour", h);
    if (new URLSearchParams(window.location.search).get("tour") === "1") startTour();  // after the listener, or the start is missed
    return () => window.removeEventListener("jalsakhi:tour", h);
  }, []);

  const save = (s: { step: number; inc: string | null } | null) => {
    if (s) sessionStorage.setItem(KEY, JSON.stringify(s)); else sessionStorage.removeItem(KEY);
    setSt(s);
  };

  // entering a step: go to its page, then run its action once
  useEffect(() => {
    if (!st) return;
    const step = STEPS[st.step];
    let inc = st.inc;
    const ctx: Ctx = { inc, setInc: (id) => { inc = id; save({ step: st.step, inc: id }); }, say: setMsg };
    if (step.route) nav(step.route(ctx));
    if (st.step === 0) setScope({ level: "village", id: VILLAGE });
    if (!step.run || ran.current.has(st.step)) return;
    ran.current.add(st.step);
    setBusy(true); setMsg("");
    step.run(ctx).catch((e) => setMsg(e.message)).finally(() => setBusy(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [st?.step]);

  if (!st) return null;
  const step = STEPS[st.step];
  const last = st.step === STEPS.length - 1;
  const go = (n: number) => {
    // the phone frame opens the citizen app as the family on the leaking lane: set that before the frame loads
    if (STEPS[n].phone) localStorage.setItem("jalsakhi.citizen", JSON.stringify({ lang: "mr", household: HOME, village: VILLAGE }));
    setMsg(""); save({ step: n, inc: st.inc });
  };

  return (
    <>
      <div className="tour" role="dialog" aria-label="Guided tour">
        <div className="row between"><span className="tour-k"><PlayCircle />Guided tour · step {st.step + 1} of {STEPS.length}</span>
          <button className="btn ghost icon sm" onClick={() => save(null)} aria-label="End the tour"><X /></button></div>
        <div className="tour-dots">{STEPS.map((_, i) => <i key={i} className={i < st.step ? "done" : i === st.step ? "cur" : ""} />)}</div>
        <h3>{step.title}</h3>
        <p>{step.body}</p>
        {(msg || busy) && <div className="tour-msg">{busy ? <Loader2 className="spin" /> : <CheckCircle2 />}<span>{msg || "Working…"}</span></div>}
        <div className="row between" style={{ marginTop: 12 }}>
          <button className="btn ghost sm" disabled={st.step === 0 || busy} onClick={() => go(st.step - 1)}><ArrowLeft />Back</button>
          {last ? <div className="row"><button className="btn ghost sm" onClick={() => { save(null); startTour(); }}><RotateCcw />Run again</button><button className="btn sm" onClick={() => save(null)}>Finish</button></div>
            : <button className="btn sm" disabled={busy} onClick={() => go(st.step + 1)}>{st.step === 0 ? "Start" : "Next"}<ArrowRight /></button>}
        </div>
      </div>
      {step.phone && (
        <div className="tour-phone"><iframe title="Citizen app" src="/citizen?focus=alerts" /><span>HH-029 · School Road · मराठी</span></div>
      )}
    </>
  );
}

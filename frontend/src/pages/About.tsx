import { BadgeCheck, BookOpen, CheckCircle2, CircleDashed, Fingerprint, Gauge, KeyRound, Layers, ListChecks, Lock, Route, Scale, ShieldCheck, XCircle } from "lucide-react";
import { getSession } from "../lib/api";
import { usePoll } from "../lib/live";
import { Loader } from "../components/ui";
import { dt, n0, n1 } from "../lib/format";
import { CONNECTIVITY_PER_VILLAGE, UPKEEP_SHARE, YEARS_OF_LIFE, villageHardware, yearlyPerHome } from "../lib/costs";

const PS = [
  ["Continuously monitor FHTC functionality at GP and household level using AI/ML", "Per-household tap status every minute, inferred from sparse sensors (state estimation) and scored on the JJM three-test definition. A single tap that stops delivering at a metered home is told apart from a fault on its lane. Head-end and tail-end service are compared. Rolls up to GP, block, district, state.", "Network twin · Households"],
  ["Real-time alerts for supply disruption, quality deterioration, low pressure, leakage, infrastructure failure", "Thirteen incident types raised from live telemetry with persistence filters, de-duplication, severity, SLA clock and citizen notification. A repaired leak cannot be closed until a field water test passes.", "Alerts & incidents"],
  ["Citizens submit feedback, complaints, photographs and geo-tagged observations in local languages", "Mobile app in six languages with voice input, photo, geo-tag, offline queue and tracking; SMS path for feature phones; daily 'did water come?' pulse.", "Citizen app · Citizen voice"],
  ["AI/ML to identify abnormal patterns, predict failures and prioritise maintenance", "Learned lane baselines with a sequential fault detector, a leak-or-obstruction classifier and a leak locator; pump failure risk and remaining life; tank and source forecasts; multilingual complaint classifier; explainable priority score. The upkeep plan brings the pump's service forward when the wear model says so.", "AI insights · Upkeep & accounts"],
  ["Automatic sync with IMIS, Sujal Gaon IDs and other JJM platforms", "Every record keyed to the Sujal Gaon ID and pushed through an outbox with idempotency, retry and reconciliation. The scheme profile carries the fields of a Sujal Gaon ID, the Jal Seva Aankalan is drafted in its five parameters, and the scheme's geometry exports as GeoJSON. Sandbox adapter today.", "IMIS / Sujal Gaon sync · Analytics"],
  ["Interactive dashboards with GIS visualisation and analytics at multiple administrative levels", "GIS map with drill-down from state to household and a tiltable 3D village, live network twin with replay, water balance and a what-if planner, 30-day analytics, scheme ranking.", "GIS map · Analytics"],
  ["Scalability, interoperability, data security, ease of deployment", "Stateless API over a relational store, versioned sync schema, role-scoped access, hash-chained audit log, device keys, one-command start. A load test measures what one process carries, a sensor study shows how few sensors a village needs, and a real ESP32 node joins the twin over Wi-Fi or a USB cable.", "This page · Devices"],
];
const COMPARE = [
  ["JJM IMIS / dashboard", "National coverage and scheme records; the identity backbone.", "Reports that a tap exists, not whether water came today. Periodic manual entry.", "Adds live service status on top of the same identifiers; syncs back automatically."],
  ["Functionality Assessment (FA 2024)", "The right definition: regular, adequate (55 lpcd), prescribed quality.", "A sample survey of about 2.3 lakh homes, run every year or two. Found 76% functional.", "Applies that same three-test definition to every home, every day."],
  ["Jal Seva Aankalan", "Puts the Gram Panchayat and Gram Sabha in charge of assessing service, on five parameters, with 30 days of citizen feedback.", "Self-assessment from recollection; no continuous evidence behind the answers.", "Fills all five parameters from monitoring and the village's registers, records the Gram Sabha's endorsement, and runs the feedback window in the citizen app."],
  ["Sujalam Bharat / Sujal Gaon ID", "One digital profile per scheme: source, infrastructure condition, supply reliability, O&M arrangements, quality tests.", "A profile is as current as its last manual update.", "Fills the same fields from live data, and exports the scheme's lanes, taps and assets as GeoJSON."],
  ["mGramSeva (DIGIT, Punjab)", "Bills, receipts and an expenditure ledger for the village water committee.", "Finance only: it does not know whether water came, or what the pump's electricity ought to have cost.", "The same registers tied to the sensors: electricity from measured pump energy, cost per kilolitre, and the charge at which the scheme breaks even."],
  ["Jal Soochak / JJM Brain (Assam)", "The operator sends a photo of the bulk meter and software reads it; cheap, and it got operators reporting.", "One reading a day for a whole scheme, with nothing to check it against.", "Takes the same daily entry and checks it against the flow sensor, so a drifting sensor or an invented reading shows up."],
  ["IoT pilots (Tata Trusts / TCIT, CSIR-CSIO suite)", "Proved sensors at source, tank and distribution find outages, leaks and low pressure.", "Asset-level view; no household status, no citizen loop, no closure workflow, no prediction.", "Same sensor set, plus household inference, citizen fusion, prediction and verified closure."],
  ["WQMIS + Field Test Kits", "Lab and FTK results in the public domain; trained women testers in every village.", "A few tests a year; audits found contaminated samples with no follow-up action.", "Continuous screening triggers the FTK test, and the flag stays open until a test closes it."],
  ["Grievance portals and state apps (such as UP Jal Sarathi)", "A channel for every citizen to complain; scheme status and the plumber's and officials' numbers in one place.", "Tickets are not linked to network data; duplicates pile up; closure is not verified.", "Reports are evidence: matched to sensor incidents, grouped by lane, closed only on citizen confirmation. The citizen app also shows who to call and the household's own charge."],
];
const STAGES = [
  ["0", "Proof of concept (now)", "Synthetic villages, real software: API, detection, ML, workflows, tests.", "Repeatable demo; 37 automated tests pass.", "done"],
  ["1", "Data discovery", "Confirm IMIS / Sujal Gaon API specs, data rights, scheme topology, stakeholders.", "Data dictionary, API agreement, pilot plan.", "next"],
  ["2", "Controlled pilot", "Instrument 2 to 3 schemes; calibrate sensors; run citizen app with real households.", "Field comparison, uptime, false-alarm rate.", "later"],
  ["3", "Model validation", "Retrain on pilot and historical data; time-split validation against the rule baseline.", "Documented metrics and limits.", "later"],
  ["4", "Scale", "Scheme templates, hardening, operations, approved live integration.", "Deployment readiness review.", "later"],
];
const ROLES = [
  ["Citizen", "Own household status, report, track, confirm. No other household's data.", false, false, false],
  ["Nal Jal Mitra (operator)", "Own village: acknowledge, inspect, record repair, close with evidence; log each supply window and the upkeep done.", true, false, false],
  ["VWSC / Gram Panchayat", "Own village: all operator actions, FTK tests, override closure with reason; payments, expenses and the Gram Sabha's endorsement.", true, true, false],
  ["Block engineer", "All villages in the block: assign crews, escalations, override.", true, true, false],
  ["District / State", "Roll-ups, analytics, sync status across their jurisdiction.", true, true, true],
];

/** What one process carried in the load test on this machine, and what the sensing costs per household. */
function ScaleAndCost() {
  const { data: b } = usePoll<any>("/api/scale", 0);
  const hardware = villageHardware(3);
  return (
    <div className="card" style={{ marginTop: 16 }}>
      <div className="card-h"><h3><Gauge />Scale and cost</h3><span className="pill demo">{b?.measured ? `load test on this machine · ${b.measured_at}` : "load test not run yet"}</span></div>
      <div className="card-b">
        {b?.measured ? (
          <div className="grid g4">
            <div><div className="upper muted">Villages per process</div><b className="num" style={{ fontSize: 22 }}>{n0(b.villages_planned)}</b><div className="xs muted">planning at {Math.round(b.headroom * 100)}% of what was measured</div></div>
            <div><div className="upper muted">What limits it</div><b style={{ fontSize: 16 }}>{b.limit === "ingest" ? "the ingest route" : "computation"}</b><div className="xs muted">ingest carries {n0(b.villages_by_ingest)} villages, computation {n0(b.villages_by_compute)}</div></div>
            <div><div className="upper muted">Readings accepted</div><b className="num" style={{ fontSize: 22 }}>{n0(b.ingest_per_s)}</b><span className="muted sm"> / s</span><div className="xs muted">over HTTP, each one committed by itself</div></div>
            <div><div className="upper muted">Raw readings kept</div><b className="num" style={{ fontSize: 22 }}>{n1(b.gb_per_village_year)}</b><span className="muted sm"> GB</span><div className="xs muted">per village per year if nothing is thinned</div></div>
          </div>
        ) : <p className="sm ink2">Run <span className="mono">python run.py --bench</span> to time the platform on this machine.</p>}
        <div className="grid g4" style={{ marginTop: 14, paddingTop: 14, borderTop: "1px solid var(--line)" }}>
          <div><div className="upper muted">Hardware per village</div><b className="num" style={{ fontSize: 22 }}>₹{n0(hardware)}</b><div className="xs muted">100 homes, 5 lanes, 3 metered taps a lane</div></div>
          <div><div className="upper muted">Hardware per home</div><b className="num" style={{ fontSize: 22 }}>₹{n0(hardware / 100)}</b><div className="xs muted">against ₹{n0(villageHardware("all") / 100)} with a node in every home</div></div>
          <div><div className="upper muted">Per home per year</div><b className="num" style={{ fontSize: 22 }}>₹{n0(yearlyPerHome(hardware))}</b><div className="xs muted">about ₹{n0(yearlyPerHome(hardware) / 12)} a month</div></div>
          <div className="xs muted" style={{ alignSelf: "end" }}>Hardware written off over {YEARS_OF_LIFE} years, {Math.round(UPKEEP_SHARE * 100)}% a year for upkeep, ₹{n0(CONNECTIVITY_PER_VILLAGE)} a year for one gateway SIM. Hosting is left out: one process of the measured size serves tens of thousands of homes, so it is small beside the hardware.</div>
        </div>
        <p className="xs muted" style={{ marginTop: 12 }}>{b?.measured ? <>{b.machine.cpu}, {b.machine.cores} threads. {b.basis} </> : null}These figures size a pilot; they are not a capacity claim for a production stack, and the prices are single-unit prototype prices, not quotations. A deployment would batch writes and thin old readings, which moves both limits.</p>
      </div>
    </div>
  );
}

export function About() {
  const { data: audit } = usePoll<any>("/api/audit?limit=60", 4000);
  const me = getSession()!.user;
  return (
    <div className="page">
      <div className="page-h"><div><h1>Trust & roadmap</h1><p>What this build covers, what is real, how it compares with what exists, how access and audit work, and the path from this proof of concept to a field deployment.</p></div></div>

      <div className="grid g2">
        <div className="card"><div className="card-h"><h3><CheckCircle2 />Real in this build</h3></div>
          <div className="card-b"><ul className="sm" style={{ margin: 0, paddingLeft: 18, lineHeight: 1.8 }}>
            <li>The full software stack: ingestion API, state estimation, detection rules, incident workflow, sync engine, role-scoped access, audit log.</li>
            <li>Seven models and two forecasts, each scored on held-out simulated data against the method it replaced.</li>
            <li>The registers a Pani Samiti keeps: upkeep plan, operator log checked against the flow sensor, user charges and expenses.</li>
            <li>The citizen app, including photo upload, geo-tag, voice and offline queue.</li>
            <li>An automated test suite covering the written test plan (T01 to T14) and more.</li>
            <li>Reference firmware and bill of materials for the sensor node.</li></ul></div></div>
        <div className="card"><div className="card-h"><h3><CircleDashed />Simulated or not yet done</h3></div>
          <div className="card-b"><ul className="sm" style={{ margin: 0, paddingLeft: 18, lineHeight: 1.8 }}>
            <li>All villages, households, sensor readings and most citizen reports are synthetic. Place names and every LGD / IMIS / Sujal Gaon ID are placeholders.</li>
            <li>No field hardware has been deployed; the firmware is a reference build.</li>
            <li>Sync talks to a local sandbox. Nothing reaches any government system.</li>
            <li>Payments, expenses and past operator entries are invented, and tariffs are demo values. Charges are recorded, not collected: there is no payment gateway.</li>
            <li>Models are not field-validated. Reported metrics describe simulation only.</li>
            <li>Sensors screen four quality parameters. This system never certifies water as safe to drink.</li>
            <li>Sign-in is demo-grade (shared demo password, no OTP or MFA).</li></ul></div></div>
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <div className="card-h"><h3><ListChecks />Problem statement 26255: requirement by requirement</h3></div>
        <div className="tbl-wrap"><table className="tbl">
          <thead><tr><th style={{ width: "30%" }}>The statement asks for</th><th>How this build answers it</th><th style={{ width: "17%" }}>Where to see it</th></tr></thead>
          <tbody>{PS.map((r) => <tr key={r[0]}><td><b className="sm">{r[0]}</b></td><td className="sm ink2">{r[1]}</td><td className="sm"><span className="pill info">{r[2]}</span></td></tr>)}</tbody>
        </table></div>
      </div>

      <ScaleAndCost />

      <div className="card" style={{ marginTop: 16 }}>
        <div className="card-h"><h3><Scale />Against what exists today</h3></div>
        <div className="tbl-wrap"><table className="tbl">
          <thead><tr><th style={{ width: "17%" }}>Existing</th><th>What it does well</th><th>Where it stops</th><th>What JalSakhi adds</th></tr></thead>
          <tbody>{COMPARE.map((r) => <tr key={r[0]}><td><b className="sm">{r[0]}</b></td><td className="sm ink2">{r[1]}</td><td className="sm ink2">{r[2]}</td><td className="sm">{r[3]}</td></tr>)}</tbody>
        </table></div>
        <div className="card-b xs muted">Sources: JJM Functionality Assessment 2024 national report (DDWS); Ministry of Jal Shakti announcements on Sujal Gaon ID (March 2026) and Jal Seva Aankalan; press coverage of the TCIT / Tata Trusts IoT pilots; CSIR-CSIO technology note; CAG audit observations on water quality follow-up; DIGIT documentation for mGramSeva; India Water Portal on Jal Soochak; coverage of the Sujalam Bharat and Jal Sarathi apps. None of these systems was used hands-on. Verify exact figures against the primary documents before quoting them.</div>
      </div>

      <div className="grid g2" style={{ marginTop: 16 }}>
        <div className="card">
          <div className="card-h"><h3><KeyRound />Who can see and do what</h3><span className="pill info">you: {me.role_label}</span></div>
          <div className="tbl-wrap"><table className="tbl">
            <thead><tr><th>Role</th><th>Scope</th><th>Act</th><th>Override</th><th>Roll-up</th></tr></thead>
            <tbody>{ROLES.map((r) => <tr key={r[0] as string}><td><b className="sm">{r[0]}</b></td><td className="sm ink2">{r[1]}</td>{[r[2], r[3], r[4]].map((v, i) => <td key={i}>{v ? <CheckCircle2 size={16} color="var(--good)" /> : <XCircle size={16} color="var(--muted)" />}</td>)}</tr>)}</tbody>
          </table></div>
          <div className="card-b sm ink2 stack" style={{ gap: 7 }}>
            <div className="row" style={{ alignItems: "flex-start" }}><Lock size={15} color="var(--brand)" style={{ flex: "none", marginTop: 2 }} /><span>Every staff API call carries a signed, expiring token and is checked against the caller's jurisdiction on the server. An operator asking for another village gets a 403.</span></div>
            <div className="row" style={{ alignItems: "flex-start" }}><ShieldCheck size={15} color="var(--brand)" style={{ flex: "none", marginTop: 2 }} /><span>Field devices authenticate with a device key; payloads are validated and de-duplicated. Passwords are stored as salted PBKDF2 hashes.</span></div>
            <div className="row" style={{ alignItems: "flex-start" }}><BookOpen size={15} color="var(--brand)" style={{ flex: "none", marginTop: 2 }} /><span>Data minimisation: households are identified by tap ID, not by name; the citizen view exposes only the caller's own home and village-level figures.</span></div>
          </div>
        </div>

        <div className="card">
          <div className="card-h"><h3><Fingerprint />Tamper-evident audit trail</h3>
            {audit ? audit.integrity.ok ? <span className="pill good"><BadgeCheck />chain intact · {audit.integrity.records} records</span> : <span className="pill critical"><XCircle />chain broken at #{audit.integrity.broken_at}</span> : null}</div>
          <div className="tbl-wrap" style={{ maxHeight: 330 }}>
            {!audit ? <Loader /> : (
              <table className="tbl">
                <thead><tr><th>When</th><th>Who</th><th>Action</th><th>Change</th><th>Hash</th></tr></thead>
                <tbody>{audit.rows.map((a: any) => (
                  <tr key={a.id}><td className="num xs">{dt(a.ts)}</td><td className="sm">{a.actor}<div className="xs muted">{a.role}</div></td>
                    <td className="sm"><span className="mono">{a.action}</span><div className="xs muted">{a.entity_id}</div></td>
                    <td className="xs">{a.prev || a.new ? `${a.prev || "–"} → ${a.new || "–"}` : ""}<div className="muted ellipsis" style={{ maxWidth: 190 }}>{a.detail}</div></td>
                    <td className="mono muted">{a.hash.slice(0, 8)}</td></tr>))}</tbody>
              </table>)}
          </div>
          <div className="card-b xs muted">Each record stores the hash of the one before it, so editing or deleting any past record breaks every hash after it. The check above recomputes the whole chain.</div>
        </div>
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <div className="card-h"><h3><Route />From proof of concept to deployment</h3></div>
        <div className="card-b grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(190px, 1fr))", gap: 12 }}>
          {STAGES.map((s) => (
            <div key={s[0]} style={{ padding: 14, borderRadius: 15, border: `1px ${s[4] === "done" ? "solid var(--good)" : "dashed var(--line-2)"}`, background: s[4] === "done" ? "var(--good-bg)" : "var(--surface-2)" }}>
              <div className="row between"><span className="upper muted">Stage {s[0]}</span><span className={`pill ${s[4] === "done" ? "good" : s[4] === "next" ? "info" : ""}`}>{s[4] === "done" ? "done" : s[4] === "next" ? "next" : "planned"}</span></div>
              <b style={{ display: "block", margin: "6px 0 4px" }}>{s[1]}</b>
              <p className="sm ink2">{s[2]}</p><p className="xs muted" style={{ marginTop: 6 }}><Layers size={11} style={{ verticalAlign: -1 }} /> Exit: {s[3]}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

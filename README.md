# JalSakhi AI

Household-aware monitoring of rural tap water service for SIH 2026 problem statement **26255**
(Ministry of Jal Shakti, NJJM / DDWS; category: Hardware).

It watches every Functional Household Tap Connection (FHTC) in a village in real time **without a
sensor in every home**, raises alerts with a suspected pipe segment, takes citizen reports in six
languages, predicts failures, and closes an incident only when telemetry and the reporting
households confirm the fix. Everything is keyed to the scheme's Sujal Gaon ID and synced through an
outage-proof outbox. It also keeps the registers a Pani Samiti needs to keep the taps running after
the alert is closed: the upkeep plan, the operator's daily log and the accounts.

> **Status: proof of concept.** The software, detection logic, ML models, workflows and tests are
> real and running. The villages, households, sensor readings and identifiers are simulated, the
> JJM integration talks to a local sandbox, and the models are trained on simulator output. The UI
> says so on every screen.

## Run it

```
start.bat                     (Windows: double-click)
python run.py                 (any OS)
```

Needs Python 3.10+. The built web UI and trained models are in the repo, so nothing else is
required. Node 18+ is needed only to rebuild the UI (`python run.py --rebuild`).

| | |
|---|---|
| Command centre | http://localhost:8000 (one-click demo roles on the landing page) |
| Citizen app | http://localhost:8000/citizen, or scan the QR code in **Demo controls** from a phone on the same Wi-Fi |
| API docs | http://localhost:8000/docs |
| Demo password | `jal123` for every demo account |
| Tests | `python run.py --test` |
| Load test | `python run.py --bench` |
| Play the hardware node | `python firmware/bench_node.py` (no board) or `python firmware/usb_bridge.py` (ESP32 on USB) |

Each start re-seeds the same deterministic demo state. **Demo controls** (yellow button, bottom
right) injects faults, controls the simulation clock and resets.

## Five-minute demo

1. **Landing page.** Say what is simulated. Enter as *State JJM cell*.
2. **State view.** Six villages roll up to block, district, state. Devkund and Amrutgaon already
   have live issues. Open **GIS map**, click Pimpalwadi: the camera flies down into a 3D village
   (drag to pan, right-drag to tilt and rotate, **Orbit** for a slow fly-around).
3. **Network twin.** 100 homes, 15 metered, 85 inferred. Hover a home: measured or estimated, with
   confidence. Under **What if**, close a lane or take the pump out for a day and read the effect.
4. **Demo controls → Pipe leak.** Within about five simulated minutes the detector raises it, the
   classifier calls it a leak, and the locator puts it *near HH-029* (the leak is beside HH-029).
   A citizen then reports "pipe leaking" in Marathi and the range tightens. On the twin, pick
   School Road: the pressure profile shows the gap opening up to that house. Drag **Replay** back
   to watch the fault arrive.
5. **Citizen app on a phone** (QR code). Report low pressure from a School Road home: it attaches
   to the same incident instead of opening a new ticket.
6. **Incident.** Acknowledge, assign, record the repair. *Verify & close* stays locked until
   pressure recovers and a field water test passes (a broken pipe that stands empty between supply
   windows can draw contamination in). Show the audit trail.
7. **The board.** Devices & hardware: plug in the ESP32 (or run `python firmware/bench_node.py`).
   One home in the twin is now that board. Press its button to close the tap: that home turns red,
   a *tap not delivering* alert is raised for one household, and its lane stays healthy.
8. **Demo controls → Pump wearing out.** The risk model raises a predictive alert while the pump
   still runs. Then **Sensors go silent**: homes turn *unknown*, not green.
9. **IMIS / Sujal Gaon sync → simulate outage.** Records queue, retry, then reconcile.
10. **Upkeep & accounts.** Press *DEMO: read the meter* and save: the entry agrees with the flow
    sensor. Type a reading 30 kL higher and save again: it is flagged. Switch to Amrutgaon: upkeep
    is overdue and the charge covers about half the running cost (and once a supply window has
    closed, its operator's own entry is flagged as about 13% high). Then **Analytics → Record Gram
    Sabha endorsement**: the five-part Jal Seva Aankalan appears in the citizen app's Village tab,
    where a household can agree or disagree for 30 days.
11. **Trust & roadmap.** What is real, what is not, the measured scale and cost, and the path to a pilot.

## What was missing from the planning docs, and what was added

The two documents in `docs/` scoped a careful two-day PoC. Measured against the problem statement,
these were the gaps, and each is now built.

| Problem statement asks for | Planning docs | Now in the build |
|---|---|---|
| AI/ML monitoring, abnormal patterns, failure prediction, maintenance prioritisation | "No predictive ML in this release", rules only | Seven models (fault detection, leak-or-obstruction, leak position, pump risk, pump remaining life, complaints, virtual sensing) + two forecasts + an explainable priority score (see below) |
| Household-level functionality | 10 to 20 instrumented homes, others unspecified | State estimation infers every home from sparse sensors, with confidence; scored on the JJM three-test definition (regular, 55 lpcd, quality) |
| Feedback with photos and geo-tags in local languages | "local-language-ready labels", optional photo | Six-language mobile app: voice input, photo, geo-tag, offline queue, tracking, fix confirmation, daily pulse; SMS path for feature phones |
| Automatic sync with IMIS / Sujal Gaon IDs | Mock mapping table | Outbox with idempotency keys, retry/backoff, reconciliation and a sandbox gateway; records keyed to Sujal Gaon ID; Jal Seva Aankalan draft |
| A model of the network, not just a dashboard | Live schematic only | Network twin with replay of the last day, pressure profile along any lane, a daily water balance (supplied against estimated use, with an honest margin) and a what-if planner that runs the calibrated model forward |
| GIS dashboards at multiple administrative levels | One village, schematic map | MapLibre GIS with state → district → block → village → tap drill-down, and a tiltable 3D village (roof colour = live tap status, flowing mains, tank level); six villages; 30-day analytics |
| Data security | "Avoid authentication complexity" | Signed tokens, role and jurisdiction checks on the server, device keys, hash-chained audit log |
| Hardware (the PS category) | Not covered | ESP32 firmware that compiles and puts a real board into the twin as one household's tap (Wi-Fi or USB), wiring, bill of materials, and a study of how many sensors a village needs |
| Leakage, infrastructure failure, source | Leak and offline scenarios | Also pump failure, tank-empty forecast, borewell depletion trend, chlorine dosing failure |
| Prioritising maintenance, and service that lasts after commissioning | Reactive only: incidents and their closure | Upkeep plan with condition-based items, an operator log checked against the sensors, user charges and expenses with cost recovery, and the Jal Seva Aankalan in its five parameters with Gram Sabha endorsement and a 30-day citizen feedback window (see below) |

Everything the docs insisted on is kept: simulated-data labelling on every screen, "suspected" /
"verification required" wording, stale sensors shown as *unknown*, closure needing evidence,
deterministic reset, and the T01 to T14 test plan (now automated).

**One deliberate departure:** the docs said not to claim a trained model. The problem statement's
title requires AI/ML, so models are trained, on simulator output, and labelled as such with their
limits on the **AI insights** page. Do not present their metrics as field accuracy.

## Learning from what exists

| Existing | Keep | Where it stops | What JalSakhi adds |
|---|---|---|---|
| JJM IMIS / dashboard | The identity backbone | Records that a tap exists, not whether water came | Live service status on the same IDs, synced back |
| Functionality Assessment 2024 | The definition: regular, adequate, quality | Sample survey every year or two (found 76% functional) | The same test on every home, every day |
| Jal Seva Aankalan | GP and Gram Sabha own the assessment: five parameters, then 30 days of citizen feedback | Answers from recollection | All five parameters filled from monitoring and the registers; endorsement recorded; the feedback window runs in the citizen app |
| Sujalam Bharat / Sujal Gaon ID | One profile per scheme: source, infrastructure condition, supply reliability, O&M arrangements, quality tests | As current as its last manual update | The same fields filled from live data; the scheme's lanes, taps and assets export as GeoJSON |
| mGramSeva (DIGIT, Punjab) | Bills, receipts and an expenditure ledger for the village water committee | Finance only: it does not know whether water came or what the pump's electricity should have cost | The same registers tied to the sensors: electricity from measured pump energy, cost per kilolitre, the break-even charge |
| Jal Soochak / JJM Brain (Assam) | The operator photographs the bulk meter and software reads it; cheap, and it got operators reporting | One reading a day per scheme, with nothing to check it against | The same daily entry, checked against the flow sensor |
| IoT pilots (TCIT / Tata Trusts, CSIR-CSIO) | Sensors at source, tank, distribution | Asset-level; no household, citizen, closure or prediction | Same sensors plus inference, citizen fusion, prediction, verified closure |
| WQMIS + FTK | Trained village testers, public results | A few tests a year; follow-up gaps | Screening triggers the FTK test; the flag stays open until a test closes it |
| Grievance portals and state apps (UP Jal Sarathi) | A channel for everyone; scheme status and officials' numbers in one place | Tickets unlinked to the network; unverified closure | Reports become evidence, grouped by lane, closed on citizen confirmation; the citizen app also shows who to call and the household's own charge |

India Water Portal's review of the 2024 Functionality Assessment notes that the survey records water
charges but does not analyse whether the tariff is adequate, how much is collected or where the
money goes, and reports a Pani Samiti in 55% of the surveyed villages and skilled O&M staff in 58%.
That is the gap the **Upkeep & accounts** page is aimed at.

## How it works

```
simulator (or ESP32 nodes)         citizen app / SMS
        |  POST /api/telemetry            |  POST /api/complaints
        v                                 v
  validate + de-duplicate          classify (ML) + correlate
        |                                 |
        +--------> state estimation <-----+       every home's status, with confidence
                         |
                rules + ML detection              persistence, hysteresis, de-duplication
                         |
                  incident manager                SLA, escalation, priority, audit
                    /          \
        live stream (SSE)     sync outbox ---> sandbox JJM gateway
              |
        React web UI
```

Detection only ever sees sensor readings and citizen reports. The simulator's ground truth is used
solely to *measure* the system (detection delay, estimator accuracy) and those numbers are marked
as demo metrics.

### Models (trained on simulator output; see `backend/models/model_card.json`)

| Model | Method | Held-out result in simulation | What it replaced, same cases |
|---|---|---|---|
| Lane fault detector | Calibrated head-loss curve + lane demand profile, CUSUM on the pressure residual; Isolation Forest as an unusualness score | 100% of 156 injected leaks / obstructions, median 4 min, 0 false alarms in 93 normal lane-days | 8-readings-in-a-row rule: 80%, median 8 min, none of the smallest faults |
| Leak or obstruction | Gradient-boosted trees on the residual pattern along the lane | 93% of 156 faults; 98% in two villages it never trained on | Flow-threshold rule: 52%, 31% left undetermined |
| Leak locator | Least-squares fit of the leak signature to the metered points; fused with a citizen sighting when there is one | Median error 0.4 homes, worst tenth over 2.1; true position inside the stated range 98% of the time | Sensor-to-sensor segment: 2.2 homes, right segment 57% of the time |
| Pump failure risk | Gradient-boosted trees on current, vibration, discharge | ROC AUC 0.979; 96/96 held-out pumps flagged before failure, median 44 run-hours ahead | unchanged (isotonic calibration tried: no gain, dropped) |
| Pump remaining life | Wear index extrapolated along the pump's own trend; quantile boosting on fleet histories as the fallback | Own trend: median error 1.2 run-hours where the trend is clear (61% of readings); fleet fallback alone: 78 run-hours | nothing: only the 72-hour risk existed |
| Complaint classifier | Character n-gram TF-IDF + logistic regression, 6 languages, 795 seed phrases | 87% with every phrase held out in turn (Tamil 80%, Hindi 88%) | With the first 411 phrases only: 79% on those phrases, now 90%; no gain on the newer phrases |
| Virtual sensing | Interpolation of hydraulic grade between live pressure points | about 100% agreement with simulator truth in normal operation | unchanged |
| Tank forecast | Mass balance + learned demand profile | Predicts the run-dry time when the pump is down | unchanged |

The synthetic leaks have exactly the shape the locator fits, and synthetic pumps wear in a straight line, so both numbers
flatter the method; the model card lists this under limits. Retrain (about two minutes): `cd backend && python -m app.ml.train`.

## Keeping the scheme running

Monitoring says when something breaks. **Upkeep & accounts** holds the other half, in three registers
that each use what the sensors already know:

| Register | What it holds | What the platform adds |
|---|---|---|
| Upkeep plan | Twelve scheduled items per scheme (tank cleaning, valve operation, flushing, chlorinator, borewell check, sensor cleaning, lab and Field Test Kit rounds, Pani Samiti meeting, Jal Utsav, pump service), each with the source of its interval | The pump's service is brought forward by the wear model; a lane with repeated faults or a node with a low battery raises a suggested job; a recorded FTK result counts as that round done |
| Operator log | One entry per supply window: bulk meter, pump hours, chlorine | The meter reading is compared with what the flow sensor counted; more than 6% apart is flagged, which catches a drifting sensor and an invented entry alike |
| Accounts | The charge demanded and collected per household, with receipts; expenses by head | Electricity is worked out from the pump's measured energy, never typed in; cost per kilolitre; the charge at which the scheme would break even |

In the seeded demo, Pimpalwadi collects 86% of a ₹60 charge and covers about two thirds of its running
cost (it would break even at ₹78 if everyone paid). Amrutgaon has four upkeep items overdue, covers
about half its cost, and its operator's entries run about 13% above the flow sensor. A household
sees only its own charge and last receipt, in the citizen app. Payments are recorded, not collected:
there is no payment gateway.

The scheme profile on the same page has the fields of a Sujal Gaon ID profile, filled from live data.
The Jal Seva Aankalan on the Analytics page is drafted in its five parameters, moves from draft to
*endorsed by the Gram Sabha* (recorded by the Pani Samiti or above, not by the operator) and then
stays open for 30 days, during which every household can agree or disagree from the citizen app.

Exports for other systems: the scheme as GeoJSON (GIS map page) and the daily service record as CSV
(Analytics page).

## Guided tour and village board

- **Guided tour** (landing page: *Take the 2-minute tour*, or the Demo drawer, or `?tour=1` on any staff page):
  the tour follows one simulated leak through eight live steps. It resets the demo, injects the leak and
  waits for detection, then opens the incident. It shows the phone alerts and the family on that lane
  reading the alert in Marathi, in a phone frame. Then it acknowledges, records the repair, waits for
  pressure to recover, records a passing field test, closes the incident on that evidence, and ends on the
  IMIS / Sujal Gaon sync. Every step acts on the running server.
- **Village display board** (`/board/VLG-PW`, no sign-in; `?lang=hi` to choose the language): a full-screen
  page for a TV at the Panchayat office, school or health centre, as the DDWS monitoring roadmap (2021)
  asks for. It shows supply on or off and until when, homes getting water now, tank level, timings, water
  quality and the latest test, functional taps over 7 days, open issues, and a QR code to report or get
  alerts. It is written in the village's language with English underneath, and refreshes every 10 seconds.
- **Presentation mode** (Shift+P or `?present=1`): a small demo badge replaces the ribbon, and small text
  grows, for screenshots and projectors.

## Jal Sakhi water testing

JJM trains five women in every village to test water with a field test kit (FTK). The **Jal Sakhi app**
(`/tester`, demo sign-in *jalsakhi.pimpalwadi*) is their phone, in the village's language:

- **Where to test first.** `core/sampling.py` ranks the tank outlet and each lane's last tap by
  contamination risk, from what the platform already sees: an open quality alert, a leak or repair on the
  lane, a pressure loss or supply cut, low chlorine (measured, or estimated along the lane), dirty-water
  reports, a school / anganwadi / health centre on the lane, and the days since the last test. The weights
  are stated, not learned, and every point is shown with its reason.
- **The kit's nine parameters** (pH, alkalinity, chloride, nitrate, total hardness, fluoride, iron, free
  residual chlorine, H2S) are entered by tapping the colour the kit shows, and judged against IS 10500:2012.
  An H2S vial can be read later (24 to 48 hours); the test completes then.
- **A failed test sets everything in motion:** a laboratory referral, a QUALITY_VERIFY incident for that lane
  (if none is open), a boil-water advisory to its households in the app and on their phones, the operator's
  alert, and the WQMIS sync. That incident closes on a passing re-test or a laboratory result.

## Pani Samiti phone and investment planner

- **Pani Samiti phone** (`/samiti`, demo sign-in *vwsc.pimpalwadi*): the VWSC the problem statement names
  as a user, in the village's language. It shows today's water and the functional taps, what needs a decision
  (with Acknowledge and Send the repair crew, and overdue deadlines in red), upkeep that is due, water-charge
  collection and arrears, the Gram Sabha report card, and a link to the village board.
- **Investment planner** (`/app/planner`, state, district or block scope): every household failing the
  JJM test is split by cause, matched to the work that would bring it back, and ranked by homes per lakh.
  The causes are household connection, lane leaks, tail-end pressure, chlorination, pump, source and silent
  sensors. A budget slider fills the list in that order and shows functional taps before and after.
  Pump and source works are counted as homes *protected*, apart from homes *restored*. Unit costs are
  indicative and stated in `core/invest.py`, to be replaced by the state's Schedule of Rates.

## The problems a village actually has

- **A motor on the tap.** Some homes fit an electric suction pump on their tap at the start of supply; they fill
  a drum fast and the homes after them on the lane go dry. A metered tap drawing more than 2.2 times the village's
  typical filling flow (and at least 18 L/min) raises *Suspected suction pump at HH-0xx*, with the downstream homes
  affected. The lane's extra flow and lost pressure are then explained by it, so no leak hunt is raised. It is
  routed to the Pani Samiti, worded as suspected. Demo scenario: *Suction pump on a tap*.
- **First flush.** When a supply cut, pressure loss, leak or suction pump on a lane clears while water is
  flowing, the lane's households are told, in their language, to let the tap run 2 minutes before filling drinking
  water: an empty or depressurised pipe can draw dirt in.
- **Homes left out, and reported against observed** (*Reported vs observed* page; also the households page,
  the Pani Samiti phone, and a count on the village board). One row per household per day (`hh_daily`):
  homes that failed the JJM test on 5 of the last 7 days, homes with no water for 14 days, and for each village
  the connections IMIS would count and its Har Ghar Jal status, against the homes reliably served
  (functional on 24 of the last 30 days). A certified village below 90%, or with dry homes, is flagged
  *certification at risk*. The 30 days before the simulation starts are seeded and labelled simulated.
- **The hours it costs.** Household-days without enough tap water, multiplied by an assumed fetching time that
  the user sets. Replace the assumption with the NSS 76th round (2018) figure before citing it.
- **Proof of repair.** A photo of the work, stamped with the time and the phone's location, is kept with the
  incident and listed in its closure evidence.
- **Families against sensors.** The households page compares the daily "did water come?" answers with what the
  sensors inferred, and lists the disagreements.

## Phone alerts

Every incident also goes to a phone (**Phone alerts** page; `backend/app/core/alerts.py`). Routing follows
the escalation ladder: the operator and Pani Samiti when it opens, the block JE if the village has not
acknowledged within the SLA (at once if critical), the district EE if it is not resolved in time.
Households linked to the citizen app get their lane's alerts in their own language.

Replies work too. Staff can tap **Acknowledge** or **Start work** on the alert, and the incident updates
with the phone named in the audit trail. A household can report in its own words, send a photo and its
location, answer YES or NO to "is it fixed?", or send STATUS.

| Channel | Set on the server | Notes |
|---|---|---|
| Telegram (two-way) | `TELEGRAM_BOT_TOKEN` from @BotFather | Long polling, so it also works from a laptop. Run one copy per bot. |
| WhatsApp Cloud API | `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_ID`, `WHATSAPP_NUMBER`; for replies `WHATSAPP_VERIFY_TOKEN` (+ `WHATSAPP_APP_SECRET`) with the webhook at `/api/whatsapp/webhook` | Business-initiated text needs an open 24-hour window or an approved template. |
| SMS | `SMS_GATEWAY_URL`, `SMS_GATEWAY_AUTH`, `SMS_SENDER_ID`, `SMS_DLT_TEMPLATE_ID` | Any HTTP gateway. In India the sender and template must be DLT-registered. |

With no channel set, every alert is still routed and written, then logged as **sandbox**: it is never
reported as sent. The four seeded recipients use the placeholder DEMO numbers and always stay in sandbox.
To link a phone, open Phone alerts and choose **Make a link code**, or in the citizen app tap
**Get alerts on my phone**. A code links one phone and expires after 30 minutes. Each phone gets at most
15 messages in 10 minutes.

## Interoperability

- **The ministry's device message.** The DDWS roadmap (March 2021) gives a reference gateway payload
  (`gid`, `did`, `dty`, `dt`, `p` with `b` battery and `e` error). `POST /api/telemetry/ddws` accepts it
  and `GET /api/interop/ddws/{village}` publishes each village's latest readings in it. The types
  fm/sl/gl/ca and the keys t/f/b/e come from the report; pt, pm and the other keys are marked as
  JalSakhi extensions.
- **JJM platforms.** Every outbox record carries the body each platform would receive (IMIS, Sujal Gaon /
  Sujalam Bharat, WQMIS, Jal Seva Aankalan). The field-by-field mapping is on the sync page. The JalSakhi
  side of each row is exact. The target field names are drafts until NIC / DDWS issue the API specification.
- **WQMIS inbound.** `POST /api/quality/lab-results` takes laboratory results for samples a failed field
  test referred. Each result closes the referral, joins the incident's closure evidence and tells the
  households: a boil advisory on a fail, an all-clear on a pass. On the quality page,
  **DEMO: lab results from WQMIS** answers open referrals from the simulated water.

## Installable, works offline

The citizen app is a PWA (`frontend/public/manifest.webmanifest`, `sw.js`). It installs to the home
screen and opens without network, showing the last known status. A report made offline waits on the
phone, photo included, in IndexedDB. It is sent by background sync where the browser supports it, or
by the page when the network returns. Photos are shrunk to 1600 px before upload.

## How few sensors, and how far it scales

Two questions a deployment has to answer, both answered from this repository rather than asserted.

**How many sensors does a village need?** The detection benchmark's 156 fault cases were scored again
with different numbers of metered taps per lane (lane entry and tail sensors always present):

| Metered taps per lane | A leak is placed within | Homes on low pressure that are found |
|---|---|---|
| 0 | cannot be placed | 23% |
| 1 | 3.0 homes | 59% |
| 2 | 0.9 homes | 70% |
| 3 (deployed) | 0.3 homes | 70% |
| 5 | 0.2 homes | 71% |
| every home | 0.2 homes | 93% |

Past three taps the extra hardware buys little until every home has one, which costs several times
as much (the Devices page prices each row). The misses are homes whose status has to be inferred
between two sensors a few minutes into a fault: that is the gap citizen reports fill, and it is a
real limit of sparse sensing, not a rounding error.

**How far does one process go?** `python run.py --bench` on the development laptop (16 threads):
computation would carry about 4,766 villages at one reading per device per minute, but the
ingest route, which commits every reading by itself, carries about 560. Planning at half of
that gives 280 villages per process. Raw readings kept in full weigh about 2.13 GB per
village per year. These size a pilot; batching writes and thinning old readings would move both.

## Layout

```
backend/app/sim/        village hydraulics, clock, scenario engine, simulated citizens
backend/app/core/       ingestion, state estimation + detection, incidents, complaints, sync, security, analytics, upkeep and accounts
backend/app/ml/         training, model bundle, complaint corpus
backend/app/main.py     FastAPI routes
backend/tests/          the test plan as code (45 tests)
frontend/src/           React UI (staff pages, citizen app, twin, charts)
firmware/               ESP32 reference node
docs/                   original planning documents
```

## Tests

`python run.py --test` runs 45 tests in about two minutes: T01 to T14 from the planning doc, plus ML
early-warning, pump prediction, role/jurisdiction checks, override rules, sync outage recovery,
FTK-gated quality closure, multi-level roll-up, the village map layout, the stale-server check, fault typing and
placement, pump remaining life, the what-if planner, replay, the water balance, single-tap faults, the hardware
node taking over a home, head-to-tail equity, leak closure, the sensor study, the upkeep plan with the operator log
and accounts, the five-part Aankalan with its feedback window, the scheme exports, phone alerts (routing, linking, acknowledging from a phone, reports with photo and
location, repair confirmation, WhatsApp webhook, rate limits), the ministry device format in and out, platform-shaped
sync payloads, and WQMIS laboratory results closing a quality incident.
The simulator is stepped manually, so results are repeatable.

## Check before you present

- **Statistics.** 76% (FA 2024), the 55% and 58% figures for Pani Samitis and O&M staff, and the Sujal
  Gaon ID facts came from secondary summaries of the official documents. Confirm the exact table and
  page in the DDWS national report before citing.
- **Field test kit limits and colours.** The nine FTK limits are taken from IS 10500:2012 as published. Iron is set to
  0.3 mg/L with no relaxation; check it against the standard's later amendments before citing. The chart colours in
  the Jal Sakhi app are approximations of a typical kit's chart, not the kit's own.
- **Bill of materials.** Prices are indicative single-unit hobby prices, not quotations.
- **Upkeep and accounts.** Tariffs, payments, expenses and past operator entries are invented. The
  electricity rate (₹7 a unit), the operator's honorarium and the chlorine dose are demo assumptions.
  Upkeep intervals follow secondary summaries of the CPHEEO O&M manual and the JJM testing norms;
  confirm them against the manual, and set them per scheme in a deployment.
- **Jal Seva Aankalan.** The five parameters, the Gram Sabha endorsement and the 30-day window follow
  the launch announcement. The official tool's own questions and scoring were not available, so the
  indicators under each parameter and the overall average are ours.
- **Existing systems.** The descriptions of mGramSeva, Jal Soochak / JJM Brain, Sujalam Bharat and
  Jal Sarathi come from their public documentation and press coverage; none was used hands-on.
- **Translations.** Bengali, Tamil and Telugu strings were written without native review.
- **Firmware.** Compiles for ESP32 and ESP32-C3; not yet flashed or run on a board from this repository. With no sensors
  fitted the board generates its own readings and the UI labels them as emulated.
- **Identifiers.** Every LGD / IMIS / Sujal Gaon value is a `DEMO-` placeholder; village names are invented.
- **Sign-in** is demo-grade (shared password, no OTP).
- **Village geometry** (lanes, house footprints, fields, approach road, pond, temple, shadows) is
  procedurally generated per village and placed at invented coordinates over a real background. It is
  not survey data, building heights are exaggerated 1.5x so houses read clearly in the tilted view, and
  the satellite imagery around a village shows whatever really lies at those coordinates.
- **GIS base map** needs internet (Esri satellite imagery by default; OpenStreetMap streets and Esri
  terrain as alternatives). The page tests each source before using it, falls through to the next, and
  drops the background when none serves real tiles. The village itself is drawn from our own data, so
  the 3D map still works offline; *None* forces that mode. These sources are fine for a demo; a
  deployment should use an approved government base map.

# JalSakhi AI: the ML and the hardware

SIH 2026, problem statement 26255 (Ministry of Jal Shakti, category Hardware). Written 18 October 2026.

This document explains two things in full:

1. **The ML and analytics that are built and running**: what each model does, how it was trained, how it was tested, the numbers it achieved, and what those numbers do not prove.
2. **The hardware**: what exists today (firmware, the device link, the ministry's data format) and what the hardware team is building, in what order, and how each piece will be measured.

Every figure in Part 1 comes from `backend/models/model_card.json` (written by the training script) or from the code itself. Every model was trained and tested on **simulated data only**. Part 2 marks what is built, what is planned, and what is still an experiment.

---

## Contents

- [The idea in one paragraph](#the-idea-in-one-paragraph)
- [Part 1: ML and analytics](#part-1-ml-and-analytics)
  - [1.1 Where the data comes from](#11-where-the-data-comes-from)
  - [1.2 The pipeline, reading to alert](#12-the-pipeline-reading-to-alert)
  - [1.3 Virtual sensing: every home's status from 15 meters](#13-virtual-sensing-every-homes-status-from-15-meters)
  - [1.4 Lane fault detector](#14-lane-fault-detector)
  - [1.5 Leak or obstruction classifier](#15-leak-or-obstruction-classifier)
  - [1.6 Leak locator](#16-leak-locator)
  - [1.7 Pump failure risk](#17-pump-failure-risk)
  - [1.8 Pump remaining life](#18-pump-remaining-life)
  - [1.9 Complaint classifier (six languages)](#19-complaint-classifier-six-languages)
  - [1.10 Rules and forecasts around the models](#110-rules-and-forecasts-around-the-models)
  - [1.11 Analytics that use the models' output](#111-analytics-that-use-the-models-output)
  - [1.12 How many sensors a village needs](#112-how-many-sensors-a-village-needs)
  - [1.13 How far one server goes](#113-how-far-one-server-goes)
  - [1.14 What the numbers do not prove](#114-what-the-numbers-do-not-prove)
  - [1.15 From simulation to the field](#115-from-simulation-to-the-field)
- [Part 2: Hardware](#part-2-hardware)
  - [2.1 What the hardware has to prove](#21-what-the-hardware-has-to-prove)
  - [2.2 The sensing design for one village](#22-the-sensing-design-for-one-village)
  - [2.3 What exists today](#23-what-exists-today)
  - [2.4 What is being built: tier M (must have)](#24-what-is-being-built-tier-m-must-have)
  - [2.5 Tier G (good to have)](#25-tier-g-good-to-have)
  - [2.6 Tier T (the innovation)](#26-tier-t-the-innovation)
  - [2.7 Tier A (if time allows)](#27-tier-a-if-time-allows)
  - [2.8 Bill of materials and cost per home](#28-bill-of-materials-and-cost-per-home)
  - [2.9 Evidence the hardware must produce](#29-evidence-the-hardware-must-produce)
  - [2.10 What to claim and what not to](#210-what-to-claim-and-what-not-to)
- [How the two halves meet](#how-the-two-halves-meet)
- [Files to read](#files-to-read)

---

## The idea in one paragraph

A village scheme has a tank, a pump, a borewell and five or six lanes of pipe, each feeding about 20 homes. Metering every home is expensive. JalSakhi puts a pressure sensor at the entry and the tail of each lane and a meter on **3 homes per lane: 15 of 100**. The physics of water in a pipe connects those points: pressure falls along a lane in a predictable way. JalSakhi learns each lane's normal pattern, infers every home's status from it, and spots when the pattern breaks. In the DDWS roadmap's own vocabulary (March 2021), that is **Advanced-tier outcomes (every home's status) on Intermediate-tier hardware** (lane meters and tail-end pressure).

---

# Part 1: ML and analytics

## 1.1 Where the data comes from

| Item | Detail |
|---|---|
| Source | The JalSakhi village simulator (`backend/app/sim/world.py`): hydraulics of tank, pump, borewell, lanes and taps, with realistic household demand, supply windows (06:00 to 09:00 and 17:00 to 20:00), sensor noise and injected faults |
| Villages | 6 simulated villages, 568 household tap connections, 191 devices |
| Faults the simulator can inject | Leaks of any size and position, obstructions, closed valves, a blocked service line at one home, a suction pump on a tap, pump wear and trips, turbidity and chlorine failures, silent sensors, transient dips, falling groundwater |
| Separation | The detectors only ever see sensor readings and citizen reports. The simulator's hidden truth is used **only to score** the system (detection delay, estimator accuracy), and those scores are labelled as demo metrics |
| Training | `cd backend && python -m app.ml.train`: about 2 minutes on a laptop (134 s measured), scikit-learn 1.9 |
| Output | `backend/models/bundle.joblib` (the models) and `backend/models/model_card.json` (every number below) |

## 1.2 The pipeline, reading to alert

```
sensor reading (or citizen report)
   │  validate: known device, timestamp with timezone, metrics in physically plausible ranges
   │  de-duplicate on event_id (a re-sent reading is ignored, never stored twice)
   ▼
state estimation ─── every home: ok / low / dry / unknown, with a confidence
   ▼
detection ───────── rules + ML models, each with a persistence count (no alert on one bad reading)
   ▼
incident manager ── de-duplicate, prioritise, SLA clock, escalation, closure only on evidence
   ▼
phone alerts · citizen app · dashboards · IMIS / Sujal Gaon / WQMIS outbox
```

The simulation advances one tick at a time. Each tick runs, in order: simulate, ingest, estimate, detect, simulated citizens, incident housekeeping, persist, sync.

**Language rule built into every detector:** an alert names what was observed and what to check. It says "suspected", "verification required", "no recent telemetry". It never asserts a confirmed cause and never says water is safe or unsafe.

## 1.3 Virtual sensing: every home's status from 15 meters

**Problem.** 85 of 100 homes have no meter. Their status still has to be known.

**Method** (`VillageMonitor._estimate_branch`):

1. Collect every fresh pressure point on the lane: the entry sensor, the metered taps, the tail sensor. Each is converted to **hydraulic grade** (pressure plus the tap's surveyed elevation), because grade, not pressure, falls smoothly along a pipe.
2. Interpolate the grade at every home's position along the lane, then subtract the home's elevation to get its pressure.
3. **Confidence** falls with distance from the nearest measured point: `0.92 - 1.1 × distance`, between 0.3 and 0.92. It is multiplied by 0.6 for a home outside the measured span. A metered home is 0.98.
4. **Status:** at least 0.5 bar is *receiving water*, 0.15 to 0.5 bar is *low pressure*, below 0.15 bar is *no water*. Confidence below 0.4 is **unknown**, never "fine".
5. If the lane's entry is dry, every home on it is dry (confidence 0.9).
6. **Water volume per home:** metered homes report their own. The lane's remaining inflow, less any suspected leak flow, is shared among the others in proportion to the square root of their pressure, which is how a tap's flow scales.

**Result in simulation:** about 100% agreement with the simulator's true status in normal operation. The households page labels every home *measured* or *estimated · NN%* so nobody mistakes an estimate for a reading.

**The JJM functionality test, per home, per day.** When each supply window closes, every home is scored on the national test:

- **Regular:** received at least 20 L in the window.
- **Quantity:** at least 90% of its share of 55 litres per person per day.
- **Quality:** no open quality concern on its supply.
- **Known:** its status was not unknown for more than half the window.

A home is **functional** only if all four hold. This is the headline number on every dashboard.

## 1.4 Lane fault detector

**Job:** notice that a lane is no longer behaving normally (a leak or an obstruction), early, without false alarms.

| | |
|---|---|
| Algorithm | A calibrated **head-loss curve** and a **demand profile** learned per lane. A one-sided **CUSUM** on the pressure residual raises the alarm. An **Isolation Forest** (140 trees) scores how unusual the lane looks |
| Features | Pressure residual against the learned head-loss curve (z-score); flow against the learned demand profile (z-score); tail/entry pressure ratio |
| Training data | 32,736 samples: 3 simulated normal days × 6 villages (31 lanes). The alarm level was set on 2 further days |
| Alarm rule | CUSUM of the residual, allowance 1.0 σ, at most 3.5 σ added per reading, alarm at 9. That needs at least 4 readings of evidence, so a two-minute dip cannot trip it |
| Test | 156 injected faults (7 leak sizes, 6 obstruction sizes, 12 cases each), plus 93 normal lane-days |

**Results (simulation, held-out cases):**

| Measure | JalSakhi | The rule it replaced (score above threshold for 8 readings in a row) |
|---|---|---|
| Faults detected | **156 / 156 (100%)** | 80.1% |
| Median detection delay | **4 min** | 8 min |
| False incidents on 93 normal lane-days | **0** | 0 |
| False alarms during fault runs | 0 | |
| Smallest leak (2.5 L/min at 1 bar) | 12/12, median 9.5 min | 0/12 |
| Smallest obstruction (3% of head) | 12/12, median 7 min | 0/12 |

The Isolation Forest is scored by a small NumPy walker over all trees at once, so live scoring of every lane in every village is one batched call per tick.

## 1.5 Leak or obstruction classifier

**Job:** both a leak and an obstruction lose pressure. The crew needs to know which.

| | |
|---|---|
| Algorithm | Histogram gradient-boosted trees (70 iterations, depth 3) |
| Features | Tail residual (z); flow against demand (z); excess flow over expected; loss over entry pressure; residual at metered taps 1, 2 and 3, each over the tail residual |
| Why these work | A leak draws **extra flow** and its pressure loss **builds up to the leak**. An obstruction **reduces flow** and its loss appears as **a step at one point** |
| Training | 3,106 samples from 144 simulated faults in 4 villages |
| Test | 156 faults; **two villages (Devkund, Amrutgaon) are never trained on** |

**Results:** accuracy **92.9%** overall and **98.1% on the two unseen villages**. Leak recall 95.2%, obstruction recall 90.3%. The flow-threshold rule it replaced scored 51.9%, and left 31.4% of faults undetermined.

## 1.6 Leak locator

**Job:** tell the crew where to dig.

| | |
|---|---|
| Algorithm | A weighted least-squares fit of the leak's signature (loss ramps up to the leak, flat beyond it) to the mean residual at every measured point on the lane. Obstructions are bracketed between the two measured points they fall between. A citizen's leak sighting, when there is one, is fused in |
| Tested on | 84 leaks and 59 obstructions |

**Results:**

| Measure | JalSakhi | Before (report the segment between two sensors) |
|---|---|---|
| Median position error | **0.4 homes** | 2.2 homes |
| Worst tenth (90th percentile) | 2.1 homes | |
| True position inside the stated range | **97.6%** | 56.9% |
| Width of the stated range (median) | 3.3 homes | 6.0 homes |
| Obstructions inside their bracket | 100% (median bracket 6 homes) | |

A leak before the first metered tap can only be placed "before that tap". The incident says so.

## 1.7 Pump failure risk

**Job:** warn that the pump will fail before it does, so the repair is planned and not an emergency. Pump failure causes 29.6% of non-functioning taps nationally (FA 2024, printed p.2).

| | |
|---|---|
| Algorithm | Histogram gradient-boosted trees (80 iterations, depth 4) |
| Target | Will the pump reach failure condition within the next 72 run-hours? |
| Features | Motor current / nominal; vibration / nominal; discharge / rated; run-hours |
| Split | **By pump:** 80% of synthetic pumps train, 20% are never seen. 66,790 training and 16,459 test samples |
| Alert rule | Risk at least 0.6 for 5 consecutive running samples |

**Results on held-out pumps:** ROC AUC **0.979**, Brier score 0.022, precision 0.914, recall 0.628 per sample. **96 of 96 held-out pumps were flagged before failure**, a median **43.8 run-hours ahead**, and none earlier than 240 hours. Isotonic calibration was tried and gave no gain on held-out pumps, so it was dropped.

## 1.8 Pump remaining life

**Job:** turn "at risk" into "about N run-hours left".

| | |
|---|---|
| Algorithm | A linear **wear index** (0 new, 1 at failure) from current, vibration and discharge. It is extrapolated along **this pump's own trend** when the trend is clearly rising; otherwise **quantile gradient boosting on fleet histories** gives the 10th, 50th and 90th percentile |
| Evaluated on | 4,752 readings in the last 300 run-hours of held-out pumps |

**Results:** wear index R² 0.9999. The own trend was clear for 61% of readings, with median error **1.2 run-hours** and its interval covering the truth 88.8% of the time. The fleet fallback alone gives a median error of 78.3 run-hours. Combined, the median error is 8.7 run-hours.

**Caveat from the model card:** synthetic pumps wear in a straight line, which flatters trend extrapolation. So the own-trend interval is never narrower than −30% / +40%. A jump in the wear index (a serviced or replaced pump) restarts the trend.

## 1.9 Complaint classifier (six languages)

**Job:** a household writes or speaks a complaint in its own words. JalSakhi files it in the right category, so it can be matched to a sensor incident.

| | |
|---|---|
| Algorithm | TF-IDF on character n-grams (1 to 4 characters), then multinomial logistic regression. Character n-grams work across scripts without a tokenizer per language |
| Languages | English, Hindi, Marathi, Bengali, Tamil, Telugu (native script and romanised) |
| Classes | No water, low pressure, dirty water, leakage, bad smell or taste, wrong timing, broken tap, other |
| Data | 795 hand-written seed phrases, expanded to 5,865 training samples |
| Test | 5-fold cross-validation **over whole seed phrases**: every phrase is tested by a model that never saw it or a variant of it |

**Results:** accuracy **86.9%**, macro-F1 0.869.

| Language | Accuracy | Class | Accuracy |
|---|---|---|---|
| English | 89.2% | Leakage | 94.1% |
| Marathi | 89.4% | Bad smell or taste | 97.9% |
| Hindi | 88.2% | Wrong timing | 91.8% |
| Telugu | 87.3% | Broken tap | 88.1% |
| Bengali | 86.3% | Dirty water | 84.8% |
| Tamil | 80.2% | No water | 79.4% |
| | | Low pressure | 76.2% |

Word n-grams, cross-word character n-grams and a linear SVM were tried and gave no gain under the same folds, so the simpler model is kept. If the model is less than 45% sure, the report is filed as "other" and a person decides.

**What a report then does** (`core/complaints.py`): it is linked to a matching open sensor incident on the same lane (it *corroborates* it). Three reports from one lane within 45 minutes become **one community incident**, not three tickets. A sensor incident raised later absorbs the earlier citizen tickets and credits the citizens with reporting first.

## 1.10 Rules and forecasts around the models

Not everything needs ML. These run alongside the models, each with a persistence count (consecutive samples the condition must hold) so that one bad reading never raises an incident.

| Detector | Signal | Persistence |
|---|---|---|
| Supply interruption (lane or whole scheme) | Entry pressure below 0.15 bar while other lanes are pressurised; or main flow under 2 L/min with every lane dry | 4 |
| Low pressure at the tail | Tail pressure below 0.5 bar; clears only above 0.6 bar (hysteresis) | 5 |
| **One tap not delivering** | A metered tap reads well below the pressure the lane holds at its position, and a point further down reads higher. Pressure cannot rise along a pipe, so the fault is in that home's own connection | 4 |
| **Suspected suction pump on a tap** | A metered tap draws more than 2.2 times the village's typical filling flow, and at least 18 L/min, which no tap can do on the lane's pressure. Downstream homes are counted as affected. The lane's extra flow and lost pressure are then **explained by the pump, so no false leak is raised** | 4 |
| Water quality: verification required | Turbidity above 5 NTU, residual chlorine below 0.2 mg/L, or pH outside 6.5 to 8.5 (IS 10500:2012) | 4 |
| Sensor offline | 8 missed reports. Homes that relied on it become **unknown**, never healthy | |
| Pump fault | Pump commanded on but not delivering | 3 |
| **Tank run-dry forecast** | 24-hour mass balance of the tank: pump rate in, the learned demand profile out, pump availability. Gives the time the tank empties | |
| **Source stress** | A linear trend of the borewell's rest level over 14 days, against the margin above the pump intake. Raised when the margin is under 45 days | 3 |
| Community cluster | 3 or more households on one lane report the same group of problem within 45 minutes | |

**First-flush advice.** When a supply cut, pressure loss, leak or suction pump on a lane clears while water is flowing, that lane's households are told in their language to let the tap run 2 minutes before filling drinking water. A pipe that stood empty or depressurised can draw dirt in.

## 1.11 Analytics that use the models' output

| Feature | What it computes | File |
|---|---|---|
| **Maintenance priority** | A transparent 0 to 100 score: severity (up to 40), homes affected (20), citizen reports (10), health risk (15 for quality, 6 for leaks), schools / anganwadis / health centres on the supply (10), and ageing against the SLA (10). The breakdown is shown on every incident | `core/incidents.py` |
| **Where to test first** (Jal Sakhi app) | Ranks the tank outlet and each lane's last tap by contamination risk, with stated weights: open quality alert 30, leak on the lane 30, pressure loss or supply cut 15, low chlorine up to 25 (measured, or estimated along the lane), dirty-water reports up to 20, sensitive sites 5 each, intermittent supply 5, days since the last test up to 15. The top three with at least 20 points are today's list | `core/sampling.py` |
| **Field test verdict** | The nine parameters of the JJM field test kit (pH, alkalinity, chloride, total hardness, nitrate, fluoride, iron, free residual chlorine, H2S) judged against IS 10500:2012 acceptable and permissible limits. The household advice follows from what failed: germs (H2S, coliform, low chlorine) mean **boil**; fluoride, nitrate or arsenic mean **use another source**, because boiling does not remove them; iron, hardness and pH are a maintenance job with **no household advisory** | `core/sampling.py` |
| **Homes left out** | One row per household per day. Homes that failed the JJM test on 5 of the last 7 days; homes with no water on each of the last 14 days | `core/equity.py` |
| **Reported vs observed** | For each village, the connections IMIS would count and its Har Ghar Jal status, against the homes **reliably served** (functional on 24 of the last 30 days). A certified village below 90%, or with dry homes, is flagged *certification at risk* (JalSakhi's own rule) | `core/equity.py` |
| **Investment planner** | Every failing home is split by cause (own connection, lane leaks, tail pressure, chlorination, pump, source, silent sensors). Each cause is matched to a priced work and ranked by **homes brought back per lakh rupees**; a budget is filled in that order. Pump and source works count as homes *protected*, apart from homes *restored*. Unit costs are indicative | `core/invest.py` |
| **Families against sensors** | The daily "did water come?" answers compared with what the sensors inferred for the same home and window; disagreements are listed for a visit | `main.py` (`/pulse`) |
| **Operator log check** | The operator's bulk-meter entry against what the flow sensor counted; more than 6% apart is flagged | `core/om.py` |

## 1.12 How many sensors a village needs

The 156 benchmark faults were re-scored with different numbers of metered taps per lane. Lane entry and tail sensors are present in every option.

| Metered taps per lane | Leaks placed | Leak placed within | Homes on low pressure that are found | Healthy homes wrongly flagged |
|---|---|---|---|---|
| 0 | 0 of 84 | cannot be placed | 23% | 0.04% |
| 1 | 84 | 3.0 homes | 59% | 0.04% |
| 2 | 84 | 0.9 homes | 70% | 0.04% |
| **3 (deployed)** | 84 | **0.3 homes** | 70% | 0.22% |
| 5 | 84 | 0.2 homes | 71% | 0.18% |
| every home | 83 | 0.2 homes | 93% | 0.11% |

Past three taps per lane the extra hardware buys little until every home has one, which costs several times as much. The homes still missed are those whose status has to be inferred between two sensors a few minutes into a fault. Citizen reports and the daily pulse fill that gap. It is a real limit of sparse sensing.

## 1.13 How far one server goes

Measured with `python run.py --bench` on the development laptop (16 threads, Windows 11):

| Measure | Value |
|---|---|
| One tick, all 6 villages (190 readings) | 75.5 ms, 12.6 ms per village |
| Villages by compute alone | about 4,766 |
| Villages by ingest (every reading committed on its own) | about 560 |
| Planned per process, at half of that | **280 villages** |
| Raw storage | about 2.13 GB per village per year, every reading kept |

Batching writes and thinning old readings would raise both limits. This sizes a pilot, not a state.

## 1.14 What the numbers do not prove

From the model card's own list of limits, plus two from the code:

- Everything is **trained and tested on simulator output**. The simulator's physics is simpler than a real network.
- Injected faults are **clean single faults**. Real faults overlap, drift, and coincide with sensor errors.
- The leak locator assumes the shape the simulator gives a leak. Real pipes follow the same physics less tidily; **the field position error will be larger**.
- Pump histories are **synthetic run-to-failure curves**, and synthetic pumps wear in a straight line, which flatters the remaining-life numbers.
- The complaint classifier learned from **a few hundred hand-written phrases**, not real grievance text. The Bengali, Tamil and Telugu phrases need a native speaker's review.
- The suction-pump detector and the contamination-risk weights are **rules with stated thresholds**, not trained models, and have no field validation.

## 1.15 From simulation to the field

What a pilot in one Gram Panchayat would need:

1. **Asset register:** lane lengths, tap positions and elevations. The estimator uses elevations; the scheme's survey or a GPS walk provides them.
2. **Calibration period:** two to three weeks of normal operation, to learn each lane's head-loss curve and demand profile from real readings. The training code already does exactly this from simulated days.
3. **Time-split validation:** train on early weeks, test on later weeks, and compare every alert with what the operator found on site.
4. **A public benchmark first:** the detector can be checked against a published leak-detection dataset before the pilot (for example the BattLeDIM 2020 benchmark), after adapting it to that network's sensor layout.
5. **Authorised historical data** for pumps (maintenance records) and complaints (real grievance text) to retrain those two models.

---

# Part 2: Hardware

The hardware team's full working plan is `docs/JalSakhi_Hardware_Implementation_Plan.md` (wiring, pin map, safety, test protocols, schedule). This part summarises it and states what is built.

## 2.1 What the hardware has to prove

The problem statement's category is **Hardware**. Today every reading in the app is simulated. The hardware turns "simulated" into "measured" for the four clauses:

| Clause of PS 26255 | Software today | What the hardware adds |
|---|---|---|
| AI/ML monitoring at GP **and household** level | Strong, on simulated readings | Real pressure and flow at a tap, and a hardware answer to "household level without a meter in every home" |
| Alerts on **water quality** | Full workflow, no real probe | Real turbidity, TDS and temperature probes, and a way to sense bacteria, which probes cannot see |
| Feedback through mobile devices | Citizen app, SMS, Telegram, WhatsApp | A village board with buttons, for people without a phone |
| Sync with IMIS / Sujal Gaon IDs | Sandbox outbox | Device messages in the format DDWS itself published |

**The angle:** other teams will add more sensors; JalSakhi gets more out of each one. A pressure sensor sampled a thousand times a second, a bacteria test that reports itself, and a risk score computed from readings that already exist.

**Why it matters nationally** (DDWS Functionality Assessment 2024, printed p.2): non-functioning taps were caused by damaged pipelines (31.9%), pump failures (29.6%) and electricity issues (8.5%). Field test kits were available in only 27.2% of villages. The plan puts hardware on each.

## 2.2 The sensing design for one village

The layout the software is built around, for a 100-home, 5-lane scheme:

| Point | Device | Measures | Count |
|---|---|---|---|
| Borewell | Submersible level probe | Depth to water | 1 |
| Pump | Current clamp (or energy meter) + vibration sensor | Current, vibration, discharge | 1 |
| Tank | Ultrasonic level sensor (or a pressure transducer at the outlet) | Level, volume | 1 |
| Main outlet | Bulk flow meter | Flow out of the tank | 1 |
| Tank outlet and one lane tail | Quality node | Turbidity, residual chlorine, pH, TDS | 2 |
| Each lane entry | Pressure + flow | Pressure, flow into the lane | 5 |
| Each lane tail | Pressure | Tail pressure | 5 |
| 3 homes per lane | Smart tap node | Pressure, flow, volume | 15 |
| **Total** | | | **31 sensor points for 100 homes** |

Every node carries an ESP32, an uplink (GSM or LoRa), a solar cell and battery, and an IP65 enclosure.

## 2.3 What exists today

| Item | Status | Detail |
|---|---|---|
| **Tap-node firmware** (`firmware/jalsakhi_node/jalsakhi_node.ino`) | **Built; compiles** for ESP32 Dev Module and ESP32-C3, with and without sensors. **Not yet flashed on a board from this repository** | Reads a 0.5 to 4.5 V pressure transducer on GPIO34 and a YF-S201 flow sensor on GPIO27, both through 10 kΩ / 20 kΩ dividers (the ESP32 is a 3.3 V part); 16-sample averaging; reports every 2 s |
| **Emulation mode** | Built | With no sensors (`SENSORS_FITTED 0`), the BOOT button cycles the tap: open (1.15 bar, 6 L/min), pinched (0.28 bar), closed (0.02 bar). Readings are sent marked `emulated` and the dashboard says so |
| **Bad connectivity handling** | Built | NTP timestamp (nothing sent until the clock is set); a 60-slot ring buffer for unsent readings, oldest dropped first; resend with backoff; a unique `event_id` per reading so a resend is never stored twice |
| **Three ways to connect** | Built | Wi-Fi; USB cable through `firmware/usb_bridge.py` (safest at a venue); or `firmware/bench_node.py`, which plays the board from a laptop |
| **Hardware in the loop** | Built | While the board reports as `HW-NODE-01`, its pressure and flow **replace the simulated readings for one metered home** (HH-011 by default, changeable on the Devices page). The estimator, detectors, alerts and that household's phone all react to the board on the table. Silent for 12 s, and the simulator takes the tap back |
| **Ingest route** | Built and tested | `POST /api/telemetry` with an `X-Device-Key` header. 201 stored, 200 already stored, 422 failed validation, 401 wrong key |
| **Ministry device format** | Built and tested | `POST /api/telemetry/ddws` accepts the DDWS roadmap's reference payload. `GET /api/interop/ddws/{village}` publishes every village's latest readings in it. Details below |
| **Parts list and costs** | In the app | Devices page and `frontend/src/lib/costs.ts`; indicative single-unit prices |

**The DDWS reference payload** (roadmap annexure, March 2021), as JalSakhi reads and writes it:

```json
{"gid": "MH_PUN_MUL_PW", "did": "b1-in", "dty": "fm", "dt": "2026-10-05T06:12:00",
 "p": {"f": "42.5", "pr": "1.21", "b": "88", "e": "00"}}
```

| Field | Meaning | From the report? |
|---|---|---|
| `gid` | Gateway ID: state, district, block, village | yes |
| `did` | Device ID | yes |
| `dty` | Device type: `fm` flow meter, `sl` service reservoir level, `gl` groundwater level, `ca` chlorine analyser | yes |
| `dty` `pt`, `pm` | Pressure transmitter, pump monitor | JalSakhi extension (the report lists these devices without a code) |
| `p.t`, `p.f` | Totaliser (kL), flow rate (L/min) | yes |
| `p.b` | Battery 0 to 100 | yes |
| `p.e` | Error code: `00` none, `01` tamper, `02` other | yes |
| `p.pr`, `p.lv`, `p.cl`, `p.tu` … | Pressure, level, chlorine, turbidity and others | JalSakhi extension |

A timestamp with no timezone is read as IST, since the report's example carries none. An error code `01` marks the reading as tampered.

**Not done yet (field build):** deep sleep, buffer persistence across power loss, GSM / LoRa uplink, per-device keys with signatures, over-the-air updates, enclosure and surge protection.

## 2.4 What is being built: tier M (must have)

The hardware plan builds in four tiers, and no tier starts until the one above it produces numbers. Tier M is what every competing hardware team will also have; it is necessary, and it will not stand out on its own.

| ID | Item | What it proves | Done when |
|---|---|---|---|
| **M1** | Tap node with real pressure and flow | "Measured", not "simulated", for the object the PS is about: a household tap | The Devices page shows the board live; closing the rig's tap turns that home from *receiving water* to *no water*, and a *tap not delivering* alert is raised |
| **M2** | Bench rig: one lane on a table | 20 to 30 m of rigid ½-inch pipe fed from a real tap, with four quarter-turn valves as homes, a leak valve, entry and tail pressure sensors, a reference gauge | Holds pressure 10 minutes with all taps shut |
| **M3** | Calibration | Flow against a weighed bucket (15 runs at 5 rates); pressure against a gauge and a water column (each metre is 0.0981 bar) | An accuracy table from our own measurements: mean and worst error, lowest value that registers |
| **M4** | Real water-quality probes | Turbidity, TDS and water temperature in a flow cell; a real cloudy sample raises a real alert | Soil stirred into the cell raises *verification required* in the app |
| **M5** | Delivery that survives an outage | A real-time clock (DS3231) so the node keeps time without internet; a larger or persistent buffer | Router off for 5 minutes: nothing lost, nothing stored twice |
| **M6** | Enclosure, labelled wiring, power plan | IP65 box with glands, perfboard, screw terminals | The node can be shaken by its box and keeps reporting |

**One purchasing decision that matters most:** buy the **0 to 0.5 MPa (5 bar)** pressure transducer, not the 1.2 MPa one. Rural taps run below about 2 bar, so the 1.2 MPa sensor uses a sixth of its range. The 5 bar part gives 2.4 times the sensitivity at the same price, and it is what makes tier T possible.

**Pitfalls written into the plan:** air pushed out of pipes when supply starts is counted as water by meters, so flow is ignored until pressure is steady. The YF-S201 does not register below about 1 L/min. The turbidity sensor is built for washing-machine ranges, so it catches events (mud after a repair) but cannot certify the 1 and 5 NTU limits, and the app says exactly that.

## 2.5 Tier G (good to have)

| ID | Item | Why |
|---|---|---|
| **G1** | **LoRa link and gateway** | Villages have no Wi-Fi. India's delicensed band is **865 to 867 MHz**, so 868 MHz-class SX1276 modules are used. A walk test reports packet delivery at fixed distances, line of sight and through buildings |
| **G2** | **Low power and solar, battery life measured** | Deep sleep outside supply windows, sensor power switched off by a MOSFET. Battery life is computed from **measured** awake current, sleep current and awake time, not asserted |
| **G3** | **Pump node** | An isolated energy meter (PZEM-004T) gives volts, amps, kW, kWh and power factor; an accelerometer gives vibration. That yields energy per kilolitre, power-cut detection (no water because no electricity), dry running, and real inputs for the two pump models |
| **G4** | **Tank node** | Level by pressure at the outlet or ultrasonic from the top; closes the water balance |
| **G5** | **Tamper flag and self-checks** | A reed switch beside the flow sensor (a magnet can stop a Hall meter) and a lid switch set the roadmap's error code `01`. The node also flags stuck, out-of-range or inconsistent readings |
| **G6** | **Village display board with buttons** | The roadmap asks Panchayats for a display unit. The app's board page already exists (`/board/VLG-PW`); the hardware version adds three big buttons (water came / low pressure / no water) for people without a phone |
| **G7** | **QR / NFC plate on every tap** | A resident scans to report with the home pre-filled; the operator scans as proof of a visit. The Sujal Gaon ID becomes physical |
| **G8** | **A model on the node** | A depth-5 decision tree, exported to C (emlearn or micromlgen, a few kilobytes), labels each window of readings on the ESP32: normal, low pressure, no water, inconsistent. It keeps working when the link is down |

## 2.6 Tier T (the innovation)

This is where the entry stops looking like the others. Each is an experiment with a measurement protocol; none is a claim until the bench produces a number.

**T1. The pressure sensor that listens: which tap opened.** The lane-entry pressure sensor is sampled about 1,000 times a second. Each tap, opening or closing, sends a brief pressure ripple with its own shape, and a classifier names the tap from the ripple. A University of Washington system, HydroSense, identified household fixtures with 97.9% accuracy from one pressure sensor inside houses (literature); nobody has shown it on a village lane. Protocol: 50 openings and 50 closings per tap, at two supply pressures; train on one day, test on another. Result to report: a confusion matrix per tap. If it works, it gives household-level evidence of supply with **one sensor per lane instead of one per home**, which feeds straight into the estimator.

**T2. Burst location from arrival times.** A burst sends a pressure drop both ways along the pipe; two sensors see it at slightly different moments.

```
x = (L + a × (t1 − t2)) / 2
x  distance of the burst from sensor 1     L  distance between the sensors
a  speed of the pressure wave in the pipe  t1, t2  arrival times
```

The wave speed is measured on the rig itself, by snapping the end tap shut and timing the ripple. For uPVC it is roughly 370 m/s (estimate), which gives about 0.19 m per sample at 1 kHz. Protocol: the leak valve at two positions, ten trials each. Damaged pipelines are the largest single cause of failure (31.9%), and the sibling problem statement 26254 asks for indigenous leak detection. Two independent methods agreeing (this one and the software's leak locator) is stronger than either alone.

**T3. Booster-pump detector.** The software already detects a suction pump from flow at a metered tap (section 1.10). The hardware experiment looks for the pump's **ripple signature** in the lane's fast pressure signal (a pressure step plus a steady ripple at the pump's rhythm), which would find pumps at homes **without** a meter. No paper was found showing this, so it is a hypothesis until the bench shows it.

**T4. Contamination-risk index and first flush.** Field research on intermittent supply in Hubli-Dharwad found bacteria often present below 10 psi (0.69 bar), intrusion between 10 and 17 psi, and few coliforms above 17 psi with chlorine (literature, to be read in the original before quoting). The app counts a tap as *receiving water* at 0.5 bar, which is inside the riskiest band, so a home can be served and still at risk. The hardware adds a second quality cell at the lane tail, sampled every second for the first 15 minutes of supply: peak turbidity and time to clear. It feeds the software's "where to test first" list.

**T5. The bacteria test that reports itself.** The H2S vial in every field test kit turns black in 24 to 48 hours if faecal bacteria are likely, but someone has to come back, look and report honestly. The holder keeps the vial at 32 to 35 °C (so the test takes a known 24 hours), watches it with a colour sensor, and posts the result itself into the app's existing H2S workflow. Protocol: boiled water (negative), pond water (positive) and tap water, side by side, twice. Microbiological contamination is first on the national assessment's challenge list, and sensors cannot see it.

**T6. Digital chlorine reader and chlorinator watch.** (a) A green LED and light sensor read the pink colour of the standard DPD chlorine test, turning a by-eye colour match into a number with a timestamp. (b) A load cell under the chlorine drum: weight falling is the dosing rate, so the applied dose, the days of stock left, and a stopped doser (water flowing, weight not falling) are all computed with nothing touching the chlorine.

```
applied dose (mg/L) = solution used (L/h) × available chlorine (g/L) × 1000 ÷ water flow (L/h)
days of stock left  = solution remaining ÷ average daily use
```

**T7. Camera reader for the existing meter.** An ESP32-CAM reads the digits of the scheme's existing mechanical bulk meter. It makes the meter smart without replacing it, and makes the operator-log check three-way.

## 2.7 Tier A (if time allows)

| ID | Item |
|---|---|
| A1 | Tap node powered by the water: a micro turbine powers the node, and its output is the flow reading. The pressure it costs the tap must be measured and reported |
| A2 | Clip-on flow sensing: an accelerometer on the outside of the pipe estimates flow from vibration (5 to 10% error in lab studies, literature); no cut in the pipe |
| A3 | Leak-noise index: 15 to 100 Hz band energy of the fast pressure signal in quiet moments, for leaks too small to shift the steady pressure |
| A4 | Auto-isolation valve that closes on a confirmed burst, only after the operator confirms in the app |
| A5 | GPS on every node: position for the GIS map, and the sub-millisecond time base T2 needs between separate nodes |
| A6 | Custom PCB and printed enclosure (fabrication takes about a week) |
| A7 | Continuous chlorine estimate from an ORP probe, calibrated against T6 |

## 2.8 Bill of materials and cost per home

Indicative single-unit hobby prices from the app's parts list (`frontend/src/lib/costs.ts`); not quotations.

| Part | Use | ≈ ₹ |
|---|---|---|
| ESP32-WROOM-32 board | Every node | 450 |
| Pressure transducer, 0.5 to 4.5 V | Lane entry, tail, tap | 650 |
| YF-S201 / YF-B5 flow sensor | Lane or household flow | 350 |
| Turbidity sensor | Quality nodes | 850 |
| TDS probe and board | Quality nodes | 550 |
| pH probe and board | Quality nodes | 1,400 |
| SIM800L GSM or LoRa module | Uplink | 450 |
| 6 V 3 W solar panel, charger, 18650 cell | Power | 600 |
| IP65 enclosure, glands, fittings, PCB | Every node | 550 |
| Ultrasonic level sensor | Tank | 800 |
| Current clamp + vibration sensor | Pump | 1,500 |
| Submersible level probe | Borewell | 3,500 |
| Bulk flow meter, pulse output | Main outlet | 4,500 |

Every node carries the ESP32, uplink, power and enclosure (₹2,050), plus its sensors. For the 31-point design in section 2.2:

| Layout | Hardware per village (indicative) | Per household per year |
|---|---|---|
| **3 metered taps per lane (deployed)** | **about ₹1 lakh** | **about ₹340 (≈ ₹29 a month)** |
| A meter on every home | several times more | about ₹1,170 |

The per-year figure writes the hardware off over 5 years, adds 12% a year for probes, calibration, replacements and visits, and adds one gateway SIM at ₹1,500 a year, all over 100 homes. These are the assumptions in `costs.ts`, stated so they can be argued with.

The bench build itself (tier M including the rig) is about ₹8,500 to 9,500 (estimate).

## 2.9 Evidence the hardware must produce

A hardware entry with ten measured rows beats one with thirty claimed features. The plan's evidence table, to fill as experiments finish:

| # | Claim | Measured how | Trials |
|---|---|---|---|
| 1 | Flow accuracy | Against a weighed bucket | 15 |
| 2 | Pressure accuracy | Against a gauge and a water column | 5 |
| 3 | Nothing lost or duplicated across an outage | Router off 5 minutes | 3 |
| 4 | A real cloudy sample raises a quality alert | Soil in the quality cell | 5 |
| 5 | Battery life | Measured currents | |
| 6 | Radio range and delivery | Walk test | |
| 7 | On-node classifier accuracy | Bench recordings from another day | |
| 8 | Tap identification accuracy | Confusion matrix | 400 events |
| 9 | Burst position error | Leak valve at two positions | 20 |
| 10 | Pump fault visible in current and vibration | Throttle, block, dry-run | 3 each |
| 11 | Bacteria test alerts by itself | Controls and a sample | 2 runs |
| 12 | Chlorine reader against a comparator | Five concentrations | 5 |
| 13 | Tamper detected | Magnet at the flow sensor | 10 |

Photograph every experiment and record a 20-second clip of each one working.

## 2.10 What to claim and what not to

**Claim, once measured:** "flow within X% and pressure within Y bar of reference instruments on our rig"; "no reading lost or duplicated across a five-minute outage"; "one pressure sensor identified which of four taps opened in Z% of N trials on a 20 m bench pipe"; "the bacteria test reported a positive sample by itself after H hours".

**Do not claim:** field accuracy of any kind (nothing has been in a village); that tap identification works on a real lane; that the turbidity sensor checks drinking-water compliance; that any reading certifies water as safe (sensors screen, tests decide); radio type approval; any result for T3 unless the bench produced one.

---

## How the two halves meet

| Hardware item | Software that already uses it |
|---|---|
| M1 tap node | Replaces one metered home's readings live; drives the estimator, the *tap not delivering* detector, alerts and the household's phone |
| M4 quality probes | Turbidity, TDS and pH are already registered metrics; routing the bench node's readings to the Water quality page is a small change |
| G3 pump node | Current, vibration and discharge already feed the pump risk and remaining-life models |
| G5 tamper and DDWS format | The DDWS ingest route reads the error code; `01` marks a reading as tampered |
| G6 display board | `/board/{village}` is already the screen; the public data route already exists |
| G8 on-node model | Its labels would arrive as ordinary readings |
| T1 tap events | Would become observations for the household estimator: direct evidence at homes with no meter |
| T2 burst position | Would be fused with the leak locator |
| T4 risk index | Feeds the Jal Sakhi "where to test first" ranking |
| T5 / T6 test results | Post into the existing field-test and WQMIS workflow (needs a device sign-in for that route) |

Server changes still needed for some of these are listed in section 14 of the hardware plan.

---

## Files to read

| File | What it holds |
|---|---|
| `backend/models/model_card.json` | Every model's method, data, split, results, what it replaced, and its limits |
| `backend/app/ml/train.py`, `models.py` | Training and live inference |
| `backend/app/core/monitor.py` | Virtual sensing and every detector |
| `backend/app/core/incidents.py`, `complaints.py` | Incident lifecycle, priority, complaint correlation |
| `backend/app/core/sampling.py`, `equity.py`, `invest.py`, `interop.py` | Field testing and risk ranking; homes left out; investment planner; DDWS and platform formats |
| `docs/JalSakhi_Hardware_Implementation_Plan.md` | The hardware team's full plan: wiring, pin map, safety, schedule, shopping list, references |
| `firmware/README.md`, `firmware/jalsakhi_node/jalsakhi_node.ino` | The tap node firmware and how to connect it |
| `frontend/src/lib/costs.ts` | Parts list and cost model |

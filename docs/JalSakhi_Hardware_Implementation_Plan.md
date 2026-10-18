# JalSakhi hardware implementation plan

SIH 2026, problem statement 26255 (Ministry of Jal Shakti, category: Hardware). Written 5 October 2026 for the build window up to the 20 October submission.

This is the hardware team's working document: what to build, in what order, how to wire and test each piece, what number each piece should produce, and what to buy. It starts with what must work and ends with the additions that would set the entry apart.

---

## 0. How to read this

**Tiers.** Build in this order. Do not start a tier until the one above it produces numbers.

| Tier | Meaning | When |
|---|---|---|
| **M: Must have** | Without these there is no hardware entry | Days 1 to 5 |
| **G: Good to have** | Makes the node believable as a field device | Days 4 to 9 |
| **T: Great to have** | The innovation. This is where the entry stops looking like the other 75 | Days 6 to 12 |
| **A: Awesome additions** | Only if the tiers above are measured and photographed | Days 10 to 13 |

**How sure each statement is.** Every technical claim carries one of these marks. Do not quote a number to judges unless it is marked *verified* or you measured it yourself.

| Mark | Meaning |
|---|---|
| `[verified]` | Read directly in the source (the repo, the DDWS reports, a datasheet-level fact checked this week) |
| `[literature]` | Reported by a paper or article; we have not reproduced it |
| `[estimate]` | A calculation or a remembered typical value; measure it before relying on it |
| `[hypothesis]` | Plausible physics, no source found; it is an experiment, not a feature, until the bench shows it |

**Prices.** Prices marked *(app)* are the indicative prices already in the app's parts list (`frontend/src/lib/costs.ts`). All other prices are rough estimates from memory: check them before ordering.

---

## 1. What the hardware has to prove

The problem statement is one sentence with four clauses, and its category is Hardware `[verified]`:

> Development of a solution using AI and ML to monitor the functionality of FHTC in real time at both the Gram Panchayat and household levels. This solution should provide alerts on water quality issues, allow village members to give feedback through mobile devices, and automatically sync data with IMIS/Sujal Gaon IDs.

| Clause | Where the build stands today | What hardware must add |
|---|---|---|
| AI/ML monitoring at GP **and household** level | Strong in software; every reading is simulated | Real measured readings, and a hardware answer to "household level without a meter in every home" |
| Alerts on **water quality** | Workflow exists; no real sensor behind it | Real probes, and something for bacteria, which probes cannot see |
| Feedback through mobile devices | Done in the citizen app | A way in for people without a smartphone |
| Sync with IMIS / Sujal Gaon IDs | Sandbox outbox | Device payloads in the format DDWS itself published |

**What the other hardware teams will most likely show** `[estimate]`: an ESP32, a flow sensor, pH / TDS / turbidity probes, a GSM or Wi-Fi link and a dashboard. Every item in tier M matches that baseline. It is necessary and it will not stand out.

**Our angle, in one line:** other teams add sensors; we get more out of each one. A pressure sensor sampled a thousand times a second, a bacteria test that reports itself, and a risk score computed from readings we already have.

**What the ministry has already said it wants** `[verified]`, from the DDWS expert committee roadmap of March 2021:

- Three designs. *Basic*: flow meter and chlorine sensor at the reservoir, groundwater level. *Intermediate*, recommended "for most villages": adds flow at lane inlets and a pressure sensor at the furthest tail end. *Advanced*: adds a water meter at every consumer; costlier.
- Devices it lists: bulk and consumer flow meters, probe-type chlorine analyser, pressure transmitter, groundwater level sensor, communication module (LoRa, cellular, NB-IoT, Wi-Fi), gateway.
- It asks Gram Panchayats to "establish a display unit at a prominent place of village".
- It publishes a reference device-to-cloud data format (section G5 below).

JalSakhi's position in that vocabulary: **Advanced-tier outcomes (every home's status) on Intermediate-tier hardware.**

**Why the two biggest failure causes matter** `[verified]`, from the DDWS Functionality Assessment national report 2024 (printed p.2): non-functioning taps were caused by damaged pipelines (31.9%), pump failures (29.6%) and electricity issues (8.5%). Field Test Kits were available in only 27.2% of villages. The plan below puts hardware on each of those.

---

## 2. Everything at a glance

Build days assume one or two people on the item. "Server change" says whether the backend needs work before the readings show up in the app.

| ID | Item | Clause served | Extra parts | Days | Server change |
|---|---|---|---|---|---|
| **M1** | Tap node with real pressure and flow | Household monitoring | none beyond the two sensors | 1 | none |
| **M2** | Bench rig: one lane on a table | all | ≈ ₹1,500 to 2,500 | 1 to 2 | none |
| **M3** | Calibration and accuracy numbers | all | reference gauge ≈ ₹250 | 1 | none |
| **M4** | Real water-quality probes | Quality alerts | ≈ ₹1,500 | 1 | small |
| **M5** | Delivery that survives an outage | Sync | ≈ ₹300 | 1 | none |
| **M6** | A box, labelled wiring, a power plan | credibility | ≈ ₹700 | 0.5 | none |
| **G1** | LoRa link and gateway | Sync | ≈ ₹900 to 4,000 | 2 | none |
| **G2** | Low power and solar, battery life measured | credibility | ≈ ₹600 *(app)* | 1 to 2 | none |
| **G3** | Pump node: energy, vibration, discharge | GP-level monitoring | ≈ ₹1,400 | 2 | small |
| **G4** | Tank node: level | GP-level monitoring | ≈ ₹650 to 800 | 1 | small |
| **G5** | Tamper flag, self-checks, ministry data format | Sync | ≈ ₹50 | 1 | small |
| **G6** | Village display board with feedback buttons | Feedback | ≈ ₹1,200 | 2 | small |
| **G7** | QR / NFC plate on every tap | Feedback, IDs | ≈ ₹100 | 0.5 | small |
| **G8** | A model running on the node | AI/ML | none | 2 | none |
| **T1** | The pressure sensor that listens: which tap opened | Household monitoring | none | 4 to 5 | medium |
| **T2** | Burst location from arrival times | Monitoring | one more pressure sensor ≈ ₹650 | 2 | medium |
| **T3** | Booster-pump detector | Monitoring | small pump (shared with G3) | 1 to 2 | small |
| **T4** | Contamination-risk index and first-flush monitor | Quality alerts | none beyond M4 | 2 | medium |
| **T5** | The bacteria test that reports itself | Quality alerts | ≈ ₹950 | 2 + incubation | small |
| **T6** | Digital chlorine reader and chlorinator watch | Quality alerts | ≈ ₹650 to 1,250 | 2 to 3 | small |
| **T7** | Camera reader for the existing mechanical meter | Monitoring | ≈ ₹550 | 1 to 2 | small |
| **A1** | Tap node powered by the water | credibility | ≈ ₹800 | 2 | none |
| **A2** | Clip-on flow sensing, no plumbing | Household monitoring | ≈ ₹250 | 3 | small |
| **A3** | Leak-noise index | Monitoring | none beyond T1 | 2 | small |
| **A4** | Auto-isolation valve | beyond the PS | ≈ ₹1,350 | 2 | medium |
| **A5** | GPS time on every node | Monitoring, IDs | ≈ ₹800 | 1 | small |
| **A6** | Custom PCB and printed enclosure | credibility | ≈ ₹1,500 to 3,000 | 3 + fabrication | none |
| **A7** | Continuous chlorine estimate from ORP | Quality alerts | ≈ ₹3,500 | 3 | small |

**If you can only do five things beyond tier M:** G3, G8, T1, T4, T5. Reasons are in each section.

---

## 3. Ground rules

### Electrical

- **The ESP32 is a 3.3 V part.** Never put 5 V on a pin. Every 5 V sensor output goes through a divider `[verified]` (the firmware already assumes 10 kΩ over 20 kΩ, so the pin sees two thirds of the sensor's volts).
- **Analog inputs: ADC1 only, GPIO32 to GPIO39.** ADC2 does not work while Wi-Fi is on `[verified]`. GPIO34 to 39 are input-only and have no pull-ups.
- **Stay inside the ADC's good range.** At 11 dB attenuation the ESP32 is accurate from about 150 mV to 2450 mV `[verified]`. Below 150 mV it reads badly, so a signal that sits near 0 V needs an offset or a different sensor.
- **Avoid the boot-strapping pins** (GPIO0, 2, 12, 15) for anything that could hold them high or low at reset.
- **Suggested pin map** so two people can work in parallel without collisions:

| Signal | Pin | Note |
|---|---|---|
| Pressure 1 (analog, via divider) | GPIO34 | already in firmware |
| Pressure 2 (analog, via divider) | GPIO35 | for T2 |
| TDS (analog, direct, board powered from 3.3 V) | GPIO32 | |
| Turbidity (analog, via divider) | GPIO33 | |
| Battery voltage (analog, via divider) | GPIO36 | |
| Flow pulses (digital, via divider) | GPIO27 | already in firmware |
| DS18B20 temperature (1-Wire, 4.7 kΩ pull-up to 3.3 V) | GPIO4 | |
| I2C SDA / SCL (RTC, colour sensor, accelerometer, OLED) | GPIO21 / GPIO22 | |
| SPI SCK / MISO / MOSI (LoRa, SD card) | GPIO18 / 19 / 23 | |
| LoRa NSS / RST / DIO0 | GPIO5 / 14 / 26 | |
| SD card CS | GPIO13 | |
| UART2 RX / TX (energy meter, GPS) | GPIO16 / 17 | |
| Sensor power switch (MOSFET gate) | GPIO25 | |
| Tamper input (reed switch and lid switch wired in parallel) | GPIO39 | needs an external pull-up; one pin keeps both off the boot-strapping pins |

- **I2C address clash:** the DS3231 clock and the MPU6050 accelerometer both default to 0x68 `[estimate]`. Tie the MPU6050's AD0 pin high to move it to 0x69.

### Safety

- **Mains (G3).** The energy meter's voltage terminals are live. One person who has done mains wiring builds it, inside an insulated box with a plug and a socket, and nobody opens that box while it is plugged in. Use a residual-current-protected socket near water.
- **Water and electronics.** Sensors on the pipe, electronics above the pipe, drip loops on every cable. Keep the laptop off the table that holds the rig.
- **Pressure.** Do not exceed the transducer's rated pressure. Closing a valve fast creates a pressure spike well above the static pressure; open the outlet before testing with mains pressure.
- **Lithium cells.** Charge only through a protected charger board (TP4056 with protection). Never leave a charging cell unattended on the bench.
- **Bleach and reagents (T6).** Gloves and eye protection. Hypochlorite corrodes metal: keep it off load cells and connectors.
- **Contaminated samples (T5).** A blackened vial is a culture of gut bacteria. Do not open it. Add bleach through the cap or submerge the closed vial in bleach solution for 30 minutes before disposal. Wash hands.

### Honesty

The app already labels readings as measured or emulated, and that discipline is worth more than any single feature. Keep it:

- A reading from a real sensor is sent with `"quality": "good"`. A generated one stays `"emulated"` `[verified]` (that is how the firmware works today).
- Every result table states how many trials, on what rig, against what reference.
- A bench result is a bench result. "Works on four taps on a 20 m pipe" is a strong claim. "Works in a village" is not ours to make yet.

---

## 4. Tier M: must have

### M1. Tap node with real pressure and flow

**What.** The existing firmware (`firmware/jalsakhi_node/jalsakhi_node.ino`) with `SENSORS_FITTED 1`: one pressure transducer and one flow sensor on a real pipe, reporting every 2 seconds, standing in for one home in the network twin.

**Why it scores.** It converts the entry from "simulated" to "measured" for the one object the problem statement is about: a household tap.

**Buy the right pressure sensor.** This matters more than anything else in the order.

- The app's parts list names a 0 to 1.2 MPa (12 bar) transducer. Rural taps run below about 2 bar, so that sensor uses a sixth of its range `[estimate]`.
- **Buy the 0 to 0.5 MPa (5 bar) version of the same 0.5 to 4.5 V transducer**, or the 0 to 30 psi (2 bar) version if you will never connect it to city mains pressure. Same price class, same wiring, 2.4 to 6 times the sensitivity. This is what makes tier T possible.

| Sensor range | Volts per bar at the sensor | Volts per bar at the pin | Pin voltage at 0 bar | at 2 bar |
|---|---|---|---|---|
| 0 to 1.2 MPa | 0.33 | 0.22 | 0.33 V | 0.78 V |
| 0 to 0.5 MPa | 0.80 | 0.53 | 0.33 V | 1.40 V |
| 0 to 30 psi (2.07 bar) | 1.93 | 1.29 | 0.33 V | 2.91 V (above the accurate range) |

All `[estimate]` from the 0.5 to 4.5 V output and the two-thirds divider. With the 5 bar part, everything from 0 to about 4 bar lands inside the ADC's accurate 150 to 2450 mV range.

- **Check the thread before you buy fittings.** These transducers come as G1/4 or 1/8 NPT. The listing says which.

**Wiring** `[verified]` (from the firmware header):

```
Pressure transducer            ESP32
  red    ── 5 V (VIN)
  black  ── GND
  signal ──[10 kΩ]──┬── GPIO34
                    [20 kΩ]
                    │
                   GND          add 100 nF from GPIO34 to GND (noise, and an anti-alias filter for T1)

Flow sensor YF-S201
  red    ── 5 V (VIN)
  black  ── GND
  yellow ──[10 kΩ]──┬── GPIO27
                    [20 kΩ]
                    │
                   GND
```

**Firmware constants to change** `[verified]`:

- Build with `-DSENSORS_FITTED=1` (the compile command is in `firmware/README.md`).
- `PRESSURE_MAX_BAR`: 12.0 for the 1.2 MPa part. Set 5.0 for the 0.5 MPa part.
- `FLOW_PULSES_PER_LITRE`: 450 nominal for the YF-S201. Replace with your calibrated value (M3).
- `WIFI_SSID`, `WIFI_PASSWORD`, `SERVER_URL`: or leave the SSID empty and run `python firmware/usb_bridge.py`.

**How it reaches the app** `[verified]`:

- The node posts to `POST /api/telemetry` with header `X-Device-Key: demo-device-key` as device `HW-NODE-01`.
- While it reports, its pressure and flow replace the simulated ones for one metered home (HH-011 by default; change it on the Devices & hardware page).
- If it is silent for 12 seconds the simulator takes the tap back.

**Pitfalls.**

- **Air.** When supply starts, pipes push air out through the tap. Meters count part of that air as water: one study measured 33 to 63% of the air volume registered as water `[literature]`. Ignore flow until pressure has been steady for a few seconds, and say so.
- **Low flow.** The YF-S201 is rated from about 1 L/min `[estimate]`. A weak tail-end tap may run below that and read zero. Note the lowest flow your sensor registers during M3.
- **ADC noise.** The firmware already averages 16 readings. Keep the 100 nF capacitor on the pin.

**Done when:** the Devices page shows "board is live", the readings are marked as measured, opening and closing the rig's tap moves the home between receiving water and no water in the twin, and a *tap not delivering* alert is raised for that one home.

---

### M2. Bench rig: one lane on a table

**What.** A pipe with taps along it, fed from a real tap, that behaves like one village lane. Everything else in this document is tested on it.

**Why it scores.** A photograph of water running through a rig with sensors on it is the single most persuasive image a hardware entry can show.

**Layout.**

```
                 reference
                  gauge                                                    leak valve L1
                    │                                                           │
 house ─hose─[V0]─[FLOW]─┬─[P1]───── 10 m ─────┬───── 10 m ─────┬───── 10 m ────┴──[P2]──[T4]── drain
 tap                     │                     │                │
                    quality cell             [T1]             [T2]            [T3] sits between T2 and L1
                  (turbidity, TDS,
                   temperature)
```

- **V0**: isolating ball valve. Half-closing it imitates low supply pressure.
- **FLOW**: the YF-S201, at the lane entry.
- **P1, P2**: pressure transducers at the lane entry and tail. P2 arrives with T2; until then P1 alone is enough.
- **T1 to T4**: quarter-turn ball valves standing in for household taps. Quarter-turn valves open fast, which gives sharp pressure ripples for T1.
- **L1**: a small valve on a tee, opened to imitate a burst.

**Use rigid pipe, and make it long.** 20 to 30 m of 1/2 inch CPVC or uPVC, coiled or folded on a board. Rigid pipe carries pressure waves cleanly; a soft garden hose smears them `[estimate]`. Length is what makes arrival-time measurements possible (T2).

**Feed it from a real tap, not a bucket.** A bucket one metre above the rig gives 0.098 bar, which is close to the noise floor of a 5 bar sensor `[estimate]`. A house tap or an overhead tank gives usable pressure. If no tap is near the bench, a 12 V diaphragm pump with a small pressure tank works, but the pump adds its own pressure ripple, which interferes with T1 and T3.

**Fittings list** (all 1/2 inch unless stated; prices `[estimate]`):

| Part | Qty | Note |
|---|---|---|
| CPVC / uPVC pipe, 3 m lengths | 8 to 10 | ≈ ₹600 to 900 total |
| Tees | 8 | taps, sensors, leak valve |
| Quarter-turn ball valves | 6 | V0, T1 to T4, L1 |
| Elbows | 8 to 12 | to fold the run on a board |
| Threaded adapters (plain to threaded) | 6 | flow sensor and transducer mounts |
| Reducing bush, 1/2 inch to the transducer's thread | 2 | G1/4 or 1/8 NPT: match the sensor |
| Hose adapter for the house tap, 3 m hose, clips | 1 set | |
| PTFE tape, solvent cement | | |
| Pressure gauge, 0 to 4 bar | 1 | the reference for M3, ≈ ₹250 |
| 10 L bucket, kitchen scale, stopwatch | | weighing water is more accurate than reading a bucket mark |

**Done when:** the rig holds pressure with all taps closed for 10 minutes without a visible drop on the gauge, and each tap and the leak valve work.

---

### M3. Calibration and accuracy numbers

**What.** Two short experiments that turn "we have sensors" into "our flow reading is within X% of a weighed bucket".

**Why it scores.** Almost no student team reports measurement error. A two-line accuracy table signals engineering.

**Flow.**

1. Set a steady flow with T4. Collect water for a timed interval into the bucket and weigh it (1 kg = 1 L).
2. Record the pulse count for the same interval. Pulses per litre = pulses / litres.
3. Repeat at five flow rates from the lowest that registers to fully open, three times each.
4. Put the mean pulses-per-litre into the firmware. Report the mean absolute error across all runs, and the lowest flow that registers.

The YF-S201's nominal figure is 450 pulses per litre and its uncalibrated accuracy is about ±10% `[estimate]`. A calibrated error of a few percent is a realistic target.

**Pressure.**

1. Zero: with the rig open to air, record the reading. Store it as an offset.
2. Span: at four or five pressures set with V0, record the transducer and the gauge.
3. Low end: a clear tube held vertically is a free reference. Each metre of water column is 0.0981 bar.
4. Fit a straight line. Report the root-mean-square error in bar.

**Template for the table:**

| Quantity | Reference | Points | Mean abs. error | Worst case | Lowest value that registers |
|---|---|---|---|---|---|
| Flow | weighed bucket | 15 | | | |
| Pressure | gauge / water column | 5 | | | |

**Done when:** both rows are filled in from your own measurements.

---

### M4. Real water-quality probes

**What.** Turbidity, dissolved solids and water temperature measured in a small flow cell at the lane entry (later, a second set at the tail for T4).

**Why it scores.** "Alerts on water quality issues" is one of the four clauses. Today nothing real stands behind it.

**Parts.** Analog turbidity sensor ≈ ₹850 *(app)*, TDS probe and board ≈ ₹550 *(app)*, waterproof DS18B20 ≈ ₹120 `[estimate]`. A pH probe (≈ ₹1,400 *(app)*) is optional and needs buffer solutions and regular recalibration.

**Wiring.**

- Turbidity: powered from 5 V, analog output up to about 4.5 V `[estimate]`, through a divider to GPIO33.
- TDS: power the board from 3.3 V so its output stays within range; connect directly to GPIO32.
- DS18B20: data to GPIO4 with a 4.7 kΩ pull-up to 3.3 V.

**Firmware.** The server already accepts `turbidity_ntu`, `tds_mgl` and `ph` from `HW-NODE-01` `[verified]`. Add them to the `metrics` object of the payload. Temperature is not a registered metric yet (section 14).

**Calibration.**

- TDS: one known solution is enough for a demo. Dissolve 0.5 g of table salt in 1 L of clean water for roughly 500 mg/L `[estimate]`, or buy a calibration sachet. Apply temperature compensation, about 2% per °C `[estimate]`.
- Turbidity: record the output in clean water and in two cloudier samples. Do not publish NTU values unless you have a reference standard; report "clear / cloudy / very cloudy" with the raw voltage.

**Be honest about the turbidity sensor.** This class of sensor is built for washing-machine and wastewater ranges, up to thousands of NTU `[estimate]`. It cannot certify the 1 and 5 NTU drinking-water limits. It catches events: mud after a pipe repair, the first flush of a supply window. Say exactly that.

**Pitfall.** A TDS probe and a pH probe in the same water disturb each other through the liquid `[estimate]`. Power the TDS board only while reading it (sensor power switch on GPIO25), or keep them in separate cells.

**Test.** Run clean water, then stir a pinch of soil into the cell, then a pinch of salt. The app's Water quality page should raise *verification required* and start the Field Test Kit workflow.

**Server note.** The readings are stored today, but only pressure and flow from the bench node currently drive the twin. Routing its quality readings into the Water quality page is a small backend change (section 14).

**Done when:** a real cloudy sample raises a real alert in the app, with the reading marked as measured.

---

### M5. Delivery that survives an outage

**What.** Proof that readings are not lost and not duplicated when the link drops.

**Why it scores.** Rural connectivity is the first objection any evaluator from the ministry will raise.

**What exists** `[verified]`: a 60-slot ring buffer, exponential backoff up to one minute, a unique `event_id` per reading, and a server that answers 201 for stored and 200 for a repeat.

**What to add.**

- **A real-time clock** (DS3231, ≈ ₹200 `[estimate]`, I2C). The firmware refuses to send without a timestamp and today gets the time from the internet `[verified]`. A village node has no internet at boot. Set the clock once; it keeps time on a coin cell.
- **A bigger or persistent buffer.** Sixty slots is two minutes at the demo's 2-second rate `[verified]`. For the outage test either report every 10 seconds, or enlarge the buffer, or write unsent readings to the SD card or flash so they survive a power cut. The firmware README lists persistence as not done.

**Test protocol.**

1. Note the server's "readings ingested" and "duplicates ignored" counters on the Devices page.
2. Run the node for 2 minutes. Switch off the Wi-Fi router for 5 minutes. Switch it back on.
3. After the buffer drains, compare: readings generated by the node (its sequence counter) against readings stored.

**Report:** outage length, readings generated, readings stored, duplicates stored (should be zero), time to drain.

**Done when:** that table shows nothing lost and nothing stored twice.

---

### M6. A box, labelled wiring and a power plan

**What.** The node in an enclosure with cable glands, sensors on proper leads, a label on every wire, and a stated power source.

**Why it scores.** Evaluators judge hardware by the photograph first. A breadboard reads as a college lab exercise; a sealed box with glands reads as a device.

**Minimum.** IP65 junction box (≈ ₹550 *(app)* with glands), perfboard instead of breadboard, screw terminals for sensor leads, silica gel sachet, a printed label with the device ID.

**Done when:** you can pick the node up by its box, shake it, and it still reports.

---

## 5. Tier G: good to have

### G1. LoRa link and gateway

**What.** Nodes talk to a gateway by LoRa radio; the gateway forwards to the server. No Wi-Fi in the village is assumed.

**Why it scores.** The roadmap lists LoRa among its communication options `[verified]`. A node that depends on Wi-Fi is not a village device.

**Use the right band.** India's delicensed LoRa band is **865 to 867 MHz** `[literature]`. The app's parts list names the Ra-02, which is a 433 MHz module. 433 MHz is exempt in India only for low-power indoor use `[literature]`, so it is acceptable on the bench but it is the wrong band to propose. Buy 868 MHz-class SX1276 modules (RFM95W or Ra-01H) and set the frequency inside 865 to 867 MHz, for example 865.0625, 865.4025 or 865.985 MHz `[estimate]`.

**Fastest route.** Two integrated boards with ESP32, SX1276, a small display and a battery connector on one PCB (TTGO LoRa32 or Heltec WiFi LoRa 32, 868/915 MHz version, ≈ ₹1,500 to 2,500 each `[estimate]`). One is the node, one is the gateway. This saves about a day of wiring and gives you G6's display for free.

**Settings to start with.** Spreading factor 7 to 9, bandwidth 125 kHz, coding rate 4/5, one message a minute. Add a node ID, a sequence number and a checksum to every packet; the gateway acknowledges and the node retries.

**Gateway.** Receives a packet, adds the time if the node had none, and posts the same JSON to `/api/telemetry`. The pattern is already in `firmware/usb_bridge.py`.

**Test.** A walk test: carry the node away from the gateway and log signal strength and packets received at fixed distances. Report packet delivery at each distance, line of sight and through buildings.

**Done when:** the node reports through the gateway with the Wi-Fi radio off, and the walk-test table exists.

---

### G2. Low power and solar, battery life measured

**What.** The node sleeps between readings, runs from a lithium cell charged by a small panel, and its battery life is measured, not asserted.

**Why it scores.** "About five days without sun" is a claim in the app's parts list. A measured current trace makes it a fact.

**How.**

- Deep sleep between reports outside supply hours; stay awake during the two supply windows (06:00 to 09:00 and 17:00 to 20:00 in the demo), because the flow sensor only counts while powered.
- Switch the sensors' 5 V supply off during sleep with a MOSFET. The pressure transducer draws a few milliamps continuously otherwise `[estimate]`.
- **Board choice matters.** A common ESP32 development board draws several milliamps in deep sleep because of its regulator and USB chip; the bare module draws tens of microamps `[estimate]`. For a battery demonstration use a low-quiescent board, or power the module directly.

**Measure.** Put a multimeter or a USB power meter in series. Record the average current awake, the current asleep, and the seconds awake per report.

**Compute.**

```
average current = (seconds awake × awake current + seconds asleep × sleep current) / period
battery life    = cell capacity / average current
```

Example with placeholder numbers, to be replaced by your measurements: awake 3 s at 80 mA and asleep 57 s at 1 mA gives 4.95 mA average; a 2600 mAh cell lasts about 525 hours, or 22 days `[estimate]`.

**Done when:** the three measured currents and the computed life are in your results table.

---

### G3. Pump node: energy, vibration, discharge

**What.** A second node on a small real pump that measures electrical input, vibration, and the pressure and flow it delivers.

**Why it scores.** Pump failure causes 29.6% of non-functioning taps `[verified]`, and the roadmap's own figures include pump health by current signature `[verified]`. The app has two pump models trained on simulated current and vibration. This gives them real signals.

**Parts.**

- **Energy meter module (PZEM-004T v3, ≈ ₹900 `[estimate]`)**: voltage, current, power, energy, power factor and frequency over a serial link. It is isolated, which is why it is preferred over a home-made current and voltage circuit. Its serial lines are 5 V: use a level shifter or a divider on the line into the ESP32 `[estimate]`.
- **Accelerometer** on the pump body: MPU6050 (≈ ₹150 `[estimate]`) covers up to about 260 Hz; ADXL345 (≈ ₹250 `[estimate]`) covers up to 1600 Hz and is the better choice `[estimate]`.
- **A small pump** as the patient: a cooler pump or a 12 V diaphragm pump (≈ ₹350 `[estimate]`).
- The rig's flow sensor and a pressure transducer at the pump outlet.

**What to compute.**

| Quantity | How | What it tells you |
|---|---|---|
| Specific energy, kWh per kL | energy ÷ volume pumped | Pump efficiency; the app's accounts already use measured pump energy |
| Vibration velocity, mm/s RMS | high-pass the acceleration, integrate, take RMS over 10 to 1000 Hz | Bearing wear, imbalance |
| Operating point | discharge pressure against flow | Drift away from the pump's curve means wear or blockage |
| Power present | voltage above a threshold | Separates "no water because no electricity" (8.5% of causes `[verified]`) from pump failure |
| Dry running | current well below normal while the pump is on | Protects the pump |

For reference, ISO 10816 places the boundaries for small machines at about 0.71, 1.8 and 4.5 mm/s RMS `[literature]`. Treat those as orientation, not as a pass mark for a toy pump.

**Fault experiments** (each a few minutes; photograph the plots):

1. Throttle the outlet valve in steps: current, pressure and flow move along the pump curve.
2. Partly block the inlet: vibration rises.
3. Run dry for a few seconds only: current drops.
4. Pull the plug: voltage disappears, and the app should report a power cut, not a pump fault.

**Server.** `current_a`, `vibration_mms` and `discharge_lpm` already exist as metrics `[verified]`. Power, energy, voltage and power factor need adding (section 14).

**Done when:** one plot shows current and vibration changing as you throttle the pump, and the specific-energy number is computed from real readings.

---

### G4. Tank node: level

**What.** The level of a bucket or drum standing in for the service reservoir.

**Two ways.**

- **Hydrostatic, reusing a pressure transducer** at the tank outlet: level in metres = pressure in bar × 10.2. A 5 bar sensor resolves a 2 m tank poorly `[estimate]`; a 0 to 5 psi part or a 16-bit external converter (ADS1115) fixes that.
- **Ultrasonic from the top** (waterproof JSN-SR04T or A02YYUW, ≈ ₹800 *(app)*). It cannot read the nearest 20 to 25 cm `[estimate]` and condensation on the sensor face causes false readings.

**What it adds.** With flow in and flow out, the tank closes the water balance: inflow − outflow − change in storage = overflow or loss. The app already forecasts when the tank runs dry.

**Server.** `level_pct` and `volume_l` exist `[verified]`, on the simulated tank device; the bench node needs them registered (section 14).

---

### G5. Tamper flag, self-checks and the ministry's data format

**What.** The node reports its own health and any interference, in the payload format DDWS published.

**Why it scores.** The roadmap's sample payload carries a battery level and an error code whose values include "tamper" `[verified]`. Matching it shows you read the document.

**The reference payload** `[verified]` (roadmap annexure, flow meter example):

```json
{"gid": "AP_D01_B01_V01", "did": "fm01", "dty": "fm", "dt": "2020-11-03T00:00:00",
 "p": {"t": "100.22", "f": "21.5", "b": "99", "e": "00"}}
```

| Field | Meaning |
|---|---|
| `gid` | gateway ID, built from state, district, block and village |
| `did` | device ID |
| `dty` | device type: `fm` flow meter, `gl` groundwater level, `sl` reservoir level, `ca` chlorine analyser. Take the code for the pressure sensor from the annexure; it was not extracted for this document |
| `dt` | timestamp |
| `p.t`, `p.f` | total quantity in litres, flow rate in L/min |
| `p.b` | battery level, 0 to 100 |
| `p.e` | error code: `00` none, `01` tamper, `02` other |

**Tamper inputs.**

- A reed switch beside the flow sensor: a magnet held near a Hall-effect meter can stop it counting `[estimate]`; the reed switch closes when one is present.
- A microswitch or light sensor under the enclosure lid.

**Self-checks on the node.** Stuck reading (no change at all for many samples while flow is present), out of range, flow with no pressure, sensor supply low. Any of these sets the error code and marks the reading as suspect.

**Done when:** the node (or gateway) emits the reference format, and holding a magnet to the flow sensor raises a tamper flag in the app.

---

### G6. Village display board with feedback buttons

**What.** A screen at the Panchayat office showing today's supply, quality and open complaints, with three large buttons for people without a phone: water came, low pressure, no water.

**Why it scores.** The roadmap asks Panchayats for a display unit `[verified]`. The buttons extend the feedback clause to people the app cannot reach. It is also the most photogenic object you can build.

**Parts.** An ESP32 with a 2.8 to 3.5 inch colour screen, or the integrated LoRa board's own display for a small version, or a P10 LED matrix for a large one (≈ ₹500 to 800 `[estimate]`); three arcade buttons.

**Data.** `GET /api/citizen/village/{village_id}` is public and returns the service score, the functional percentage, the tank level, the quality status and open issues `[verified]`. Poll it once a minute.

**Pitfall.** Marathi text on a microcontroller display is hard: Devanagari needs shaping that small font libraries do not do well `[estimate]`. Use icons and numbers, or pre-render the Marathi labels as images.

**Buttons.** The existing daily pulse (`POST /api/pulse`) is tied to a household `[verified]`. A public board needs a lane-level or village-level version (section 14).

---

### G7. A QR or NFC plate on every tap

**What.** A printed plate at each tap carrying its household and scheme ID.

**What it does.**

- A resident scans it and the report form opens with the home already filled in.
- The operator scans it when inspecting or repairing: a time-stamped, located proof of the visit, which the closure checklist can require.

**Why it scores.** It makes "sync with Sujal Gaon IDs" physical: the ID is on the wall beside the tap. Cost is a sticker.

**Server.** The citizen app needs to accept a household ID from the link (section 14).

---

### G8. A model running on the node

**What.** A small classifier on the ESP32 that labels each window of readings (normal, low pressure, no water, inconsistent) and sends immediately when the label changes.

**Why it scores.** The problem statement says AI and ML, and the category is hardware. A model on the device puts both in one object, and it keeps working when the link is down.

**How.**

1. Train a decision tree of depth 5 or less in scikit-learn on windowed features: mean and minimum pressure, pressure slope, mean flow, the ratio of flow to pressure.
2. Training data: readings exported from the simulator, plus recordings from the rig. Test on rig recordings from a different day.
3. Export the tree to C with a converter such as emlearn or micromlgen `[estimate]`. A tree this size is a few kilobytes.
4. Show the label on the node's display or LED.

**Report.** Accuracy and a confusion matrix on bench recordings; flash and memory used; inference time.

**Done when:** with the link unplugged, the node still shows the right label when you close the tap, and reports the change when the link returns.

---

## 6. Tier T: great to have (the innovation)

### T1. The pressure sensor that listens: which tap opened

**What.** The lane-entry pressure sensor sampled about 1,000 times a second. Each tap, when opened or closed, produces a brief pressure ripple with its own shape. A classifier names the tap from the ripple.

**Why it scores.** It is a hardware answer to the hardest clause, household-level functionality, with one sensor per lane instead of one per home. A University of Washington system, HydroSense, did this inside houses and identified individual fixtures with 97.9% accuracy from a single pressure sensor `[literature]`. Nobody has shown it on a village lane; that is your experiment.

**No extra parts.** It uses M1's transducer. An SD card helps for recording.

**Sampling.**

- Target 1 kHz. Two ways on the ESP32:
  - A hardware timer at 1 kHz that reads the ADC in its interrupt. Simple.
  - The ADC's continuous mode, whose lowest rate on the ESP32 is 20 kHz `[verified]`: average each block of 20 samples to get 1 kHz with lower noise. Better.
- Keep the 100 nF capacitor on the pin: with the divider it filters above roughly 240 Hz `[estimate]`, which stops higher frequencies folding into the signal.
- **Radio off while capturing.** Wi-Fi transmission disturbs the ADC `[estimate]`. Capture, then send.
- Check your transducer's response time on its listing. A few milliseconds or better is needed `[estimate]`.

**Event capture.**

1. Keep a rolling baseline (the median of the last 2 seconds).
2. Trigger when the rate of change exceeds several times the noise for three samples in a row.
3. Save 0.25 s before the trigger and 1.75 s after: 2,000 samples per event.

**Features to try first.** Direction (opening drops the pressure, closing raises it), peak size, rise time, the shift in steady level, the frequency and decay of the ringing that follows, and the energy in a few frequency bands from 5 to 200 Hz. Start with template matching (cross-correlate against a stored example per tap, pick the nearest). HydroSense's follow-up work reported above 90% with template matching `[literature]`.

**Data collection protocol.**

- For each tap: 50 openings and 50 closings, at two supply pressures (V0 fully open and half open).
- Label each event with a button press or a serial command at the moment you turn the valve.
- **Split by session, not at random**: train on one day's recordings, test on another day's. A random split overstates accuracy.

**Report.** A confusion matrix per tap; accuracy when two taps are opened within a second of each other (expect it to fall); accuracy at the second supply pressure when trained on the first.

**What it feeds into the app.** For each home: whether its tap was used today, how many times, for how long. That is direct evidence of regular supply at a home with no device in it, and an extra observation for the existing estimator.

**Limits to state openly.** Overlapping events confuse it. The shapes change when plumbing changes, so it needs re-learning. Four taps on a bench is not twenty homes on a lane.

**Fallback.** If accuracy is poor, the existing estimator is unchanged and nothing is lost. A modest result honestly reported is still new work.

**Done when:** the node (or the laptop, stated as such) names the tap you just opened, live, and the confusion matrix is in the results table.

---

### T2. Burst location from arrival times

**What.** A burst sends a pressure drop along the pipe in both directions. Two sensors see it at slightly different moments; the difference gives the position.

**Why it scores.** Damaged pipelines are the largest single cause of non-functioning taps, 31.9% `[verified]`. A sibling problem statement this year (26254) asks for indigenous leak detection sensor systems `[verified]`. This is an established pipeline method, quoted at ±1 to 3% of the sensor spacing with sampling of 100 Hz or more `[literature]`, and it uses two ₹650 sensors.

**The arithmetic.**

```
x = (L + a × (t1 − t2)) / 2

x   distance of the burst from sensor 1
L   distance between the sensors
a   speed of the pressure wave in the pipe
t1  arrival time at sensor 1,  t2  arrival time at sensor 2
```

**Wave speed.** It depends on the pipe. A standard estimate (the Korteweg formula) gives about 370 m/s for uPVC and about 270 m/s for HDPE `[estimate]`, far below the 1,000 to 1,400 m/s of steel pipes `[literature]`. Do not trust a calculated value: **measure it on your rig** by snapping the end tap shut and timing the ripple from P2 to P1. Wave speed = L ÷ that time.

**Timing.** At 1 kHz and 370 m/s, one sample is about 0.19 m of position `[estimate]`. On 20 m of rigid pipe the end-to-end time is roughly 40 to 55 ms `[estimate]`, enough to resolve.

**On the bench, put both sensors on one ESP32** (GPIO34 and GPIO35) so they share a clock. In the field two separate nodes need a common time base to better than a millisecond, which is what A5 is for.

**Finding the arrival.** Threshold on the smoothed rate of change for a first estimate; then cross-correlate the two 100 ms windows around it for a finer one.

**Test.** Open L1 sharply, ten times. Then move the leak tee to a second position and repeat.

**Report.** True position, computed position, error in metres, for every trial. A fair target is within a metre or two on a 20 m pipe; report what you get.

**Fusion.** The app already places leaks from the steady pressure profile. Two independent methods agreeing is a stronger statement than either alone.

---

### T3. Booster-pump detector

**What.** Detect an illegal suction pump on a tap from the lane's pressure signal.

**Why it could matter.** Booster pumps attached directly to supply lines starve neighbours of pressure and can pull contamination in through leaks. The problem is documented in Nagpur, Bengaluru and rural Kangra `[literature]`.

**The idea** `[hypothesis]`. A pump should leave two marks: a step down in average pressure, and a steady ripple at the pump's own rhythm (the motor's rotation rate and its multiples for a centrifugal pump; the stroke rate for a diaphragm pump). A one-second window at 1 kHz gives a spectrum with 1 Hz resolution up to 500 Hz. Learn the spectrum with no pump; flag persistent new peaks that appear together with a pressure step.

**Test.** Connect a small pump to draw from one of the rig's tees. Run it on and off twenty times. Report detection rate and false alarms during ordinary tap use.

**Status.** No paper was found showing this. Present it as an experiment. If it works on the bench it is a striking demonstration; if not, leave it out.

---

### T4. Contamination-risk index and first-flush monitor

**What.** A risk score for each lane and each supply window, computed from pressure readings you already have, plus a close look at the first minutes of supply at the tail end.

**Why it scores.** It turns the pressure sensor into a water-quality instrument, backed by field research in an Indian city, and it costs nothing extra.

**The evidence** `[literature]`. A study of intermittent supply in Hubli-Dharwad measured pressure and water quality through supply cycles:

- When supply was first turned on, water with raised turbidity and high indicator bacteria was flushed out.
- Below 10 psi (0.69 bar), indicator bacteria were often found even with a chlorine residual.
- Between 10 and 17 psi (0.69 to 1.17 bar) there was evidence of intermittent intrusion.
- Above 17 psi (1.17 bar) with a chlorine residual, few coliforms and no E. coli were detected.
- E. coli appeared in 31.7% of tap samples under intermittent supply against 0.7% under continuous supply.

Read the original paper before quoting these figures; they reached this document through summaries.

**An insight this gives you.** The app counts a tap as delivering usable pressure at 0.5 bar `[verified]`. That is inside the highest-risk band above. A home can be "receiving water" and still be at a pressure where contamination is likely. Showing that second layer is new.

**Risk index, per lane, per supply window:**

- minutes of flow below 0.69 bar, between 0.69 and 1.17 bar, and above;
- hours the lane stood unpressurised before the window;
- whether a leak is open on the lane (from the detectors);
- the first-flush result, below.

Combine into low, medium or high. Its purpose is to say **where to run the bacteria test today** (T5).

**First-flush monitor.** Put a second quality cell (turbidity, TDS, temperature) at the lane tail. For the first 15 minutes of each window, sample once a second. Compute:

- peak turbidity and the time taken to settle to the steady value;
- the difference in dissolved solids and temperature between tail and lane entry. Water that sat in a leaking pipe, or seeped in from the ground, differs from fresh supply.

**Test.** Let the rig stand drained with a little muddy water left in the tail section. Start supply. The monitor should show a turbidity peak that clears.

---

### T5. The bacteria test that reports itself

**What.** A holder that watches the standard bacteriological test vial and raises the alert when it turns black.

**Why it scores.** The app states that sensors cannot detect bacteria, and the national assessment's challenge list puts microbiological contamination first `[verified]`. The field test for it (the H2S vial in every Field Test Kit) needs a person to return a day or two later, look, and report honestly. Field Test Kits were found in only 27.2% of villages `[verified]`. No existing version of this device was found in a quick search; a proper prior-art check has not been done.

**How the vial works** `[literature]`. Fill to the line, cap, and wait. If the contents turn black, bacteria that produce hydrogen sulphide are present and the water is not fit to drink. Time needed depends on temperature: 24 hours at 30 to 35 °C, up to 48 to 60 hours at 15 to 20 °C.

**Parts.** Colour sensor with its own light (TCS34725, ≈ ₹400 `[estimate]`) or simply an LED and a light sensor; a light-tight holder (a PVC end cap or a 3D print); a small heater (a 5 V heating pad or a power resistor switched by a MOSFET); a DS18B20; a foam box; test vials (≈ ₹20 to 40 each `[estimate]`).

**Build.**

1. The vial sits between the light and the sensor, shielded from room light.
2. The heater holds 32 to 35 °C, controlled by the temperature sensor. That makes the test take a known 24 hours instead of a guess.
3. Every 5 minutes, log brightness. When it falls below a threshold and stays there, the vial has blackened.
4. Report: positive or negative, and the hours it took. A faster result suggests heavier contamination; treat that as qualitative only.

**How it reaches the app.** The app already records Field Test Kit results with an H2S field (`POST /api/quality/tests`, staff sign-in) `[verified]`. The holder posts through the gateway and the result flows into the existing quality workflow and closure checklist.

**Test plan.** Three vials at once: boiled water (negative control), pond or drain water (positive control), and tap water. Start by 14 October at the latest: each run takes a day and you want two.

**Safety.** See section 3. Never open a blackened vial.

**Done when:** a time-lapse plot shows the positive control darkening and the alert firing on its own, with the negative control flat.

---

### T6. Digital chlorine reader and chlorinator watch

Two cheap devices for the parameter the ministry lists first among quality sensors, residual chlorine, without the probe-type analyser, which is the costly part of the roadmap's design.

**(a) Digital reader for the DPD test.**

- **Principle** `[estimate]`. The standard chlorine reagent (DPD) turns pink in proportion to free chlorine. A green LED (about 520 nm) shines through the sample onto a light sensor. Absorbance = log10(reading before reagent ÷ reading after). Concentration is close to proportional to absorbance up to about 2 mg/L.
- **Why.** Kits today rely on matching a colour by eye. This gives a number, a timestamp and a location, and removes the judgement.
- **Parts.** Green LED, light sensor (TSL2591 or BH1750), a test tube, a dark holder, DPD tablets or powder (≈ ₹650 in all `[estimate]`).
- **Procedure.** Insert the sample and read. Add the reagent, mix, wait a minute, read again.
- **Calibration.** Against a pool-water comparator kit, or dilutions of a bleach solution measured with one.
- A software alternative is a phone photo of a test strip; one study reports about 85% accuracy for smartphone reading of DPD colour `[literature]`.

**(b) Weigh the chlorine drum.**

- **Idea.** Put the hypochlorite solution drum on a load cell (50 kg cell and HX711 amplifier, ≈ ₹600 `[estimate]`). Weight falling over time is the dosing rate.
- **What it gives:**

```
applied dose (mg/L) = solution used (L/h) × available chlorine (g/L) × 1000 ÷ water flow (L/h)
days of stock left  = solution remaining ÷ average daily use
dosing failure      = water flowing, weight not falling
```

- **Why it is clever.** Nothing touches the chlorine, so nothing corrodes or needs recalibration. It predicts stock-outs, detects a stopped doser within minutes, and gives an expected residual to compare against the reader in (a). The app already has a chlorine dosing failure scenario and a chlorinator upkeep item for it to feed.
- **Bench version.** A bottle on a small load cell dripping into the rig's inlet.

---

### T7. Camera reader for the existing mechanical meter

**What.** A ₹550 camera module fixed over a scheme's existing mechanical bulk meter (or a pressure gauge), reading the digits every few minutes.

**Why it scores.** Schemes already have mechanical meters. This makes one smart without replacing it. The app already checks the operator's daily meter entry against the flow sensor; a camera reading makes that a three-way check.

**How.** An open-source project, AI-on-the-edge-device, does this on an ESP32-CAM with on-device digit recognition and outputs over a web interface or MQTT `[literature]`. Adapt it; check its licence before reuse.

**Needs.** A fixed mount, a shroud against glare, steady LED lighting.

---

## 7. Tier A: awesome additions

### A1. Tap node powered by the water

**What.** A small inline turbine powers the node, and the turbine's own output measures the flow. A node that stays silent during supply hours means no water reached it.

**Parts.** F50-class micro hydro generator (≈ ₹600 `[estimate]`), a supercapacitor, a regulator.

**Constraints** `[literature]` (seller specifications): it starts at about 0.05 MPa (0.5 bar); the three-phase version is recommended for 3 to 18 L/min at 0.15 to 0.8 MPa. A weak tail-end tap may not turn it, and it takes some pressure from the tap.

**Therefore.** Place it at a lane entry, not at a weak home. **Measure the pressure it costs** at three flow rates and report it. Without that number the idea will be challenged.

**Logic to state.** Silence is ambiguous on its own. The server treats a silent turbine node as "no water" only when the lane's other sensors agree; if the lane has pressure, it raises a tap or node fault for a visit.

### A2. Clip-on flow sensing, no plumbing

**What.** An accelerometer strapped to the outside of the pipe estimates flow from vibration.

**Evidence** `[literature]`. The standard deviation of pipe vibration rises with flow rate; studies with accelerometers and machine learning report errors of 5 to 10% in laboratory conditions.

**How.** Mount an ADXL345 near an elbow or valve. Sample at 1 kHz in one-second windows. Features: the standard deviation of the high-passed signal and the energy in a few bands. Train a regression against your calibrated flow sensor.

**Expect.** Reliable flowing / not flowing; a coarse flow rate. It is sensitive to mounting and to other vibration, such as a nearby pump.

**Why it would matter.** A household node with no cut in the pipe.

### A3. Leak-noise index

**What.** Use the fast pressure signal during quiet moments (no tap events) as a hydrophone.

**Evidence** `[literature]`. In plastic pipes leak noise is low-frequency and fades quickly; on a 150 mm PVC test pipe the useful band was 15 to 100 Hz. One in-pipe study detected leaks as small as 2 L/min with a dynamic pressure transducer.

**How.** Band energy from 15 to 100 Hz, averaged over quiet windows, tracked over time. A sustained rise suggests a leak that is too small to shift the steady pressure.

**Note.** An audio microphone is the wrong sensor for plastic pipe. The pressure transducer you already sample fast is the right one.

### A4. Auto-isolation valve

**What.** A motorised ball valve at the lane entry (≈ ₹1,200 `[estimate]`) that closes when a burst is confirmed.

**Design rules.** The operator confirms in the app before it closes; a manual override on the valve; it stays open if power is lost.

**Honest framing.** The problem statement asks for monitoring. Present this as the next step the monitoring makes possible.

### A5. GPS time on every node

**What.** A GPS module (≈ ₹400 each `[estimate]`) gives each node its position and a timing pulse accurate to well under a millisecond `[estimate]`.

**Why.** It is what T2 needs to work between two separate nodes in the field, and it geotags every asset automatically for the GIS map.

### A6. Custom PCB and printed enclosure

**What.** The tap node as one board: dividers, sensor power switch, protection on the sensor lines, screw terminals, test points; in a printed or moulded case.

**Timing warning.** Board fabrication takes about a week `[estimate]`. Order by day 5 or not at all. The fallback is a neat perfboard build; publish the board design files and a render alongside it.

### A7. Continuous chlorine estimate from ORP

**What.** An oxidation-reduction probe with pH and temperature, calibrated against the reader in T6(a), giving a continuous chlorine estimate between manual tests.

**Limits** `[literature]`. The relationship depends strongly on pH and temperature. Probes drift. Label the output as an estimate.

---

## 8. Sensors that make the data smarter

A sensor earns its place if it lets you compute something the others cannot. This table is ordered by value per rupee.

| Add | ≈ Cost | New variable | What it unlocks |
|---|---|---|---|
| Water temperature (DS18B20) at every wetted node | ₹120 | °C | Corrects dissolved-solids readings; chlorine decays faster in warm water; a temperature difference between head and tail marks stagnant or seeped-in water |
| Real-time clock and SD card | ₹300 | trusted time, raw logs | Timestamps without internet; raw 1 kHz recordings to train on; a black box when something goes wrong |
| A second pressure sensor on the same lane | ₹650 | pressure difference, arrival-time difference | Head loss along the lane (blockage, roughness); a check on the flow sensor; burst position (T2); how long the lane takes to fill each morning |
| Energy meter on the pump | ₹900 | volts, amps, kW, kWh, power factor | Energy per kilolitre; power-cut detection; dry-running; the electricity bill computed, not typed |
| Accelerometer on the pump | ₹150 to 250 | vibration | Bearing wear and imbalance before failure |
| Tank level | ₹650 to 800 | level, volume | Closes the water balance; overflow; time to empty |
| Load cell under the chlorine drum | ₹600 | dosing rate | Applied dose, stock-out forecast, dosing failure, with nothing in contact with chlorine |
| Second quality cell at the tail | ₹1,500 | head-to-tail differences | First-flush index; contamination entering along the lane |
| Reed switch and lid switch | ₹50 | tamper | The roadmap's tamper code; trust in the readings |
| Battery voltage divider | ₹5 | battery % | The roadmap's battery field; maintenance before a node dies |
| GPS | ₹400 | position, precise time | Automatic geotagging; time base for arrival-time methods |

---

## 9. What to compute from the data

These are the derived quantities worth showing. Each uses hardware from the tiers above.

| Quantity | From | Formula or method | Why it matters |
|---|---|---|---|
| **Litres per person per day, per home** | flow at metered taps, estimator for the rest | volume ÷ household size | One of the three JJM functionality tests |
| **Hours of supply per day** | pressure above threshold | count of minutes | The roadmap's "periodicity" indicator |
| **Head loss per metre of lane** | two pressure sensors, flow | (P1 − P2) ÷ length, tracked against flow² | Rising loss at the same flow means a blockage or a narrowing pipe |
| **Lane fill time** | P1 and P2 at the start of a window | time between pressure arriving at entry and at tail | Specific to intermittent supply. A longer fill means more water lost on the way |
| **Equity ratio** | head and tail pressure, or first and last tap volume | tail ÷ head | Tail-end homes are where service fails first |
| **Contamination-risk band** | pressure, T4 | minutes below 0.69 bar and between 0.69 and 1.17 bar | Where to run the bacteria test |
| **First-flush index** | tail quality cell | peak turbidity, time to clear | Evidence of dirt or intrusion while the pipe stood empty |
| **Tap-use events per home** | T1 | classified ripples | Household evidence without household hardware |
| **Surge count** | fast pressure | ripples above a size threshold per day | Repeated surges fatigue joints; they predict the next burst |
| **Specific energy** | pump energy, flow | kWh ÷ kL | Pump efficiency and the true running cost |
| **Pump operating point drift** | discharge pressure, flow | distance from the baseline curve | Wear before failure |
| **Water balance** | tank level, inflow, outflow | inflow − outflow − change in storage | Loss between source and lanes |
| **Applied chlorine dose** | drum weight, flow | see T6(b) | Dosing conformance without a probe |
| **Sensor health** | every node | stuck, out-of-range, inconsistent, low supply | Readings you can trust, and a suspect flag when you cannot |

---

## 10. Evidence to collect

Fill this in as you go. A hardware entry with ten measured rows beats one with thirty claimed features.

| # | Claim | Measured how | Trials | Result |
|---|---|---|---|---|
| 1 | Flow accuracy | against a weighed bucket (M3) | 15 | |
| 2 | Pressure accuracy | against a gauge and a water column (M3) | 5 | |
| 3 | Nothing lost or duplicated across an outage | router off for 5 minutes (M5) | 3 | |
| 4 | A real cloudy sample raises a quality alert | soil in the quality cell (M4) | 5 | |
| 5 | Battery life | measured currents (G2) | | |
| 6 | Radio range and delivery | walk test (G1) | | |
| 7 | On-node classifier accuracy | bench recordings from another day (G8) | | |
| 8 | Tap identification accuracy | confusion matrix (T1) | 400 events | |
| 9 | Burst position error | leak valve at two positions (T2) | 20 | |
| 10 | Pump fault visible in current and vibration | throttle, block, dry-run (G3) | 3 each | |
| 11 | Bacteria test alerts by itself | controls and a sample (T5) | 2 runs | |
| 12 | Chlorine reader against a comparator | five concentrations (T6) | 5 | |
| 13 | Tamper detected | magnet at the flow sensor (G5) | 10 | |

Photograph every experiment. Record a 20-second clip of each one working.

---

## 11. Shopping list

Order tier M and anything with a delivery time on day 1. Prices marked *(app)* are from the app's parts list; the rest are estimates.

**Tier M**

| Item | Qty | ≈ ₹ each |
|---|---|---|
| Pressure transducer, **0 to 0.5 MPa**, 0.5 to 4.5 V output | 2 (the second is for T2) | 650 *(app)* |
| Flow sensor YF-S201 | 1 (2 if doing G3 on a separate loop) | 350 *(app)* |
| ESP32 development boards | 3 | 450 *(app)* |
| Resistors 10 kΩ, 20 kΩ, 4.7 kΩ; 100 nF capacitors; perfboard; screw terminals; jumper wires | assorted | 300 |
| Pipe, valves, tees, fittings (section M2) | | 1,500 to 2,500 |
| Pressure gauge 0 to 4 bar | 1 | 250 |
| Turbidity sensor | 1 (2 for T4) | 850 *(app)* |
| TDS probe and board | 1 (2 for T4) | 550 *(app)* |
| DS18B20 waterproof | 3 | 120 |
| DS3231 clock module | 2 | 200 |
| microSD module and card | 1 | 250 |
| IP65 box with glands | 2 | 550 *(app)* |

**Tier G**

| Item | Qty | ≈ ₹ each |
|---|---|---|
| LoRa: integrated ESP32 + SX1276 boards, 868 MHz class | 2 | 1,500 to 2,500 |
| or SX1276 modules (RFM95W / Ra-01H) with antennas | 2 | 450 *(app)* |
| 18650 cell, TP4056 with protection, 6 V 3 W panel | 1 set | 600 *(app)* |
| Energy meter module PZEM-004T v3, with enclosure, plug and socket | 1 | 900 + 300 |
| Accelerometer ADXL345 (or MPU6050) | 2 | 250 |
| Small pump | 1 | 350 |
| Ultrasonic level sensor (if not using a pressure transducer) | 1 | 800 *(app)* |
| Reed switch, microswitch, magnet | 1 set | 50 |
| Colour display 2.8 inch or larger, three large buttons | 1 set | 750 |
| MOSFET modules for switching sensor power and heater | 3 | 60 |
| QR plates (printed, laminated) | a sheet | 100 |

**Tier T**

| Item | Qty | ≈ ₹ each |
|---|---|---|
| Colour sensor TCS34725 | 1 | 400 |
| Heater pad 5 V, foam box | 1 | 250 |
| H2S test vials | 10 | 20 to 40 |
| Green LED, light sensor (TSL2591 or BH1750), test tubes | 1 set | 350 |
| DPD chlorine tablets or powder, a pool comparator kit | 1 | 300 to 500 |
| Load cell 5 kg (bench) or 50 kg (drum) with HX711 | 1 | 400 to 600 |
| ESP32-CAM with programmer | 1 | 550 |

**Tier A (only if reached)**

| Item | Qty | ≈ ₹ each |
|---|---|---|
| Micro hydro generator, F50 class, 5 V or three-phase | 1 | 600 |
| Supercapacitor 5.5 V | 1 | 200 |
| Motorised ball valve 12 V, driver | 1 | 1,350 |
| GPS module | 2 | 400 |
| ORP probe and board | 1 | 2,000 to 3,000 |

**Rough totals** `[estimate]`: tier M about ₹8,500 to 9,500 including the rig; tier G about ₹5,500 with bare LoRa modules or up to ₹9,500 with integrated boards; tier T about ₹3,000, plus ₹1,500 for the second quality cell that T4 uses.

---

## 12. Fourteen-day schedule

Two tracks run in parallel from day 3: **Track A** is the node and its electronics, **Track B** is the rig and the experiments. Put names against each line.

| Day | Date | Track A: node | Track B: rig and experiments |
|---|---|---|---|
| 1 | 6 Oct | Order everything in section 11. Flash the firmware as it is; confirm the board appears in the app in emulated mode | Buy pipe and fittings locally. Mark out the rig on a board |
| 2 | 7 Oct | Perfboard with dividers and terminals. Clock and SD card working | Build the rig. Leak-test it |
| 3 | 8 Oct | **M1** with real sensors | **M3** calibration, flow |
| 4 | 9 Oct | **M4** quality probes. **M5** outage test | **M3** calibration, pressure. Start recording normal operation for G8 |
| 5 | 10 Oct | **M6** boxed. **G8** classifier trained and on the node. Order a PCB today if doing A6 | 1 kHz capture firmware for **T1**; first recordings |
| 6 | 11 Oct | **G1** LoRa link | **T1** data collection, session 1 |
| 7 | 12 Oct | **G1** gateway and walk test. **G2** current measurements | **G3** pump node built; fault experiments |
| 8 | 13 Oct | **G5** tamper and data format | **T1** data collection, session 2; first classifier |
| 9 | 14 Oct | **T5** holder built; **start vial run 1** | **T2** second sensor in; wave speed measured |
| 10 | 15 Oct | **G6** display board. **T6** chlorine reader | **T2** burst trials. **T4** first-flush test. Read vial run 1 |
| 11 | 16 Oct | **T6** drum load cell. **Start vial run 2** | **T1** final confusion matrix. **T3** pump-detector experiment |
| 12 | 17 Oct | One tier A item, or finish what slipped | Repeat any experiment with a weak result. Read vial run 2 |
| 13 | 18 Oct | **Freeze.** No new features | Fill the evidence table. Photographs and clips of every experiment |
| 14 | 19 Oct | Buffer | Buffer |

**Rules for the schedule.**

- If tier M is not measured by the end of day 5, drop tier A entirely and one tier T item.
- The vial runs cannot be compressed. If the holder is not ready by day 9, run vials in a warm place by eye and photograph them on a timer; the holder then becomes a described design, not a result.
- An experiment that fails still goes in the notes, with what was tried. Do not present it.

---

## 13. What to claim and what not to

**Claim, once measured:**

- "Flow within X% and pressure within Y bar of reference instruments on our rig."
- "No reading lost or duplicated across a five-minute outage."
- "One pressure sensor identified which of four taps opened in Z% of N trials on a 20 m bench pipe."
- "Two pressure sensors placed a simulated burst within W metres on a 20 m pipe."
- "The bacteria test reported a positive sample by itself after H hours."

**Do not claim:**

- Field accuracy of any kind. Nothing here has been in a village.
- That tap identification works on a real lane. It is shown on a bench.
- That the turbidity sensor checks compliance with drinking-water limits.
- That any reading certifies water as safe. Sensors screen; tests decide. The app already says this, and the hardware should not contradict it.
- Radio approval. The band is delicensed; a product still needs type approval.
- A result for T3 unless your bench produced one.

**Say plainly where something is a design, not a build.** If the PCB did not arrive, show the render and call it a render.

---

## 14. Server-side changes these items need

None of this is built. It is listed so the software side can plan.

| For | Change |
|---|---|
| M4, T4 | Register a temperature metric. Route the bench node's quality readings into the Water quality page, as its pressure and flow already drive the twin |
| G3 | Register power, energy, voltage and power-factor metrics; let a bench pump stand in for the simulated pump, as the tap node does for a home |
| G4 | Allow the bench node to report tank level |
| G5 | Accept the roadmap's payload format at the ingest route (or in the gateway), and carry battery and error codes through to the Devices page; emit the same format from the sync adapter |
| G6 | A lane-level or village-level version of the daily pulse for the public buttons |
| G7 | Let the citizen app open with a household chosen from the scanned link; record a scan as proof of a visit on an incident |
| T1 | An event route for classified tap events; use them as observations in the household estimator |
| T2, T3, A3 | An event route for burst position, pump signature and leak-noise index; combine the burst position with the existing leak locator |
| T4 | Compute and show the risk band and first-flush index per lane and window; use them to prioritise test rounds |
| T5, T6 | A device sign-in for posting test results (today the quality-test route needs a staff session) |
| T7 | Accept camera-read meter totals and add them to the operator-log check |

---

## 15. References

Marks in the text point here. Items marked *read* were read directly for this document; the others reached it as summaries, so read the original before quoting a figure from them.

**Read directly**

- Problem statement SIH26255 and its sibling statements, as listed at https://sih2026-ps-viewer.vercel.app/ (a third-party viewer; confirm against sih.gov.in).
- DDWS, *Roadmap for the measurement & monitoring of water service delivery in rural areas*, Technical / Expert Committee Report, March 2021. https://jaljeevanmission.gov.in/sites/default/files/guideline/technical-expert-committee-report-on-measuring-and-monitoring.pdf
- DDWS, *Functionality Assessment of Household Tap Connection, National Report 2024*. https://jaljeevanmission.gov.in/sites/default/files/2025-12/FHTC_National%20Report%202024.pdf
- This repository: `firmware/jalsakhi_node/jalsakhi_node.ino`, `firmware/README.md`, `backend/app/core/telemetry.py`, `backend/app/sim/engine.py`, `backend/app/sim/world.py`, `frontend/src/lib/costs.ts`.

**Summaries and search results**

- HydroSense: single-point pressure sensing of household water use, University of Washington. https://ubicomplab.cs.washington.edu/publications/hydrosense
- Locating leaks by negative pressure wave. https://pipeline.rossma.ru/en/blog/negative-pressure-wave
- Intermittent supply and water quality in Hubli-Dharwad (Kumpel and Nelson), as summarised at https://thesourcemagazine.org/closing-the-sdg-access-gap-the-challenge-of-intermittent-supply/
- Booster ("tullu") pumps and low pressure: https://www.nagpurtoday.in/illegal-use-of-tullu-pump-creating-artificial-low-pressure-water-supply/05181356 and https://www.tribuneindia.com/news/himachal/tullu-pump-misuse-creates-water-crisis-in-kangra-dist
- H2S strip test for bacteriological contamination. https://www.indiawaterportal.org/articles/h2s-strip-test-water-quality-testing-kit-bacteriological-contamination
- Smartphone reading of chlorine test colour. https://diposit.ub.edu/dspace/handle/2445/221298
- Flow rate from pipe vibration: Evans, Blotter and Stephens (2004), https://scholarsarchive.byu.edu/facpub/435 ; and https://teknomekanik.ppj.unp.ac.id/index.php/teknomekanik/article/view/530
- Leak signals in plastic pipes (Hunaidi and Chu; Gao, Brennan and Joseph). https://www.ioa.org.uk/system/files/proceedings/y_gao_mj_brennan_pf_joseph_cross-correlation_for_leak_detection_in_buried_plastic_water_pipes.pdf
- Air in pipes and meter over-reading under intermittent supply. https://link.springer.com/article/10.1007/s11269-025-04160-3
- LoRa frequency bands in India. https://zbotic.in/lora-technology-guide-india-long-range-iot-without-wifi/
- ESP32 ADC ranges and continuous mode. https://docs.espressif.com/projects/esp-idf/en/latest/esp32s2/api-reference/peripherals/adc/adc_continuous.html
- ISO 10816 vibration zones, as summarised at https://support.monnit.com/article/288-iso-10816-and-monnit-standard-vibration-sensors
- AI-on-the-edge-device, ESP32-CAM meter reader. https://cdn.jsdelivr.net/gh/jomjol/ai-on-the-edge-device@main/README.md
- F50 micro hydro generator, seller specifications. https://www.fruugo.us/f50-80v-micro-hydro-generator-with-transparent-housing-multivoltage-output-for-off-grid-power/p-466836770
- ORP-based chlorine estimation. https://pure.ups.edu.ec/en/publications/an-iot-device-for-determining-the-level-of-chlorine-present-in-wa/

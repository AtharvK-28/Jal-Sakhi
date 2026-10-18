import { useState } from "react";
import { Link } from "react-router-dom";
import { BatteryMedium, CircuitBoard, Cpu, PlugZap, Radio, Ruler, Signal, SunMedium, Terminal, Usb, Wifi } from "lucide-react";
import { api } from "../lib/api";
import { useLive, usePoll } from "../lib/live";
import { Kpi, Loader, toast } from "../components/ui";
import { VillagePicker } from "../components/Shell";
import { hhmm, n0, n1 } from "../lib/format";
import { BOM, PART, villageHardware, yearlyPerHome } from "../lib/costs";

export function Devices() {
  const { village, focus, meta, setVillage, snap } = useLive();
  const { data } = usePoll<any>(`/api/devices?village=${village}`, 2500);
  const benchAt = meta?.focus_village;  // the one village the bench node belongs to
  const { data: card } = usePoll<any>("/api/ai/models", 0);
  const [kind, setKind] = useState("");
  if (!data) return <div className="page"><Loader /></div>;
  const all: any[] = data.devices;
  const sim = all.filter((d) => d.kind !== "bench");
  const rows = sim.filter((d) => !kind || (kind === "problem" ? d.status !== "online" : d.kind === kind));
  const online = sim.filter((d) => d.status === "online").length;
  const total = PART.mcu + PART.pressure + PART.flow + PART.turbidity + PART.tds + PART.ph + PART.uplink + PART.power + PART.enclosure;

  return (
    <div className="page">
      <div className="page-h"><div><h1>Devices & hardware · {focus?.name}</h1><p>The sensing layer: where the nodes sit, whether they are alive, how a real board joins the network twin, and how many sensors a village actually needs.</p></div><VillagePicker /></div>

      <div className="grid kpis" style={{ marginBottom: 16 }}>
        <Kpi icon={<Radio />} label="Devices reporting" value={online} unit={`/ ${sim.length}`} tone={online === sim.length ? "good" : "warn"} sub="a silent device makes its area 'unknown'" />
        <Kpi icon={<Cpu />} label="Readings ingested" value={n0(data.ingest.ingested)} sub={`${data.ingest.rejected} rejected · ${data.ingest.duplicates} duplicates ignored`} />
        <Kpi icon={<CircuitBoard />} label="Sensors per 100 homes" value={Math.round((sim.length / (focus?.kpis?.households || 100)) * 100)} sub="15 metered homes, not 100" />
        <Kpi icon={<BatteryMedium />} label="Lowest battery" value={n0(Math.min(...sim.map((d) => d.battery_pct)))} unit="%" sub="solar + Li-ion on asset nodes" />
      </div>

      <div className="grid g-main">
        <div className="card">
          <div className="card-h"><h3><Radio />Device registry</h3>
            <div className="seg">{[["", "All"], ["problem", "Problems"], ["branch_in", "Lane entry"], ["branch_end", "Lane tail"], ["tap", "Smart taps"], ["quality", "Quality"]].map(([k, l]) => <button key={k} className={kind === k ? "on" : ""} onClick={() => setKind(k)}>{l}</button>)}</div></div>
          <div className="tbl-wrap" style={{ maxHeight: 560 }}>
            <table className="tbl">
              <thead><tr><th>Device</th><th>Status</th><th>Last reading</th><th>Latest values</th><th>Battery</th><th>Signal</th></tr></thead>
              <tbody>
                {rows.map((d) => (
                  <tr key={d.id}>
                    <td><b className="mono">{d.id}</b>{d.source === "hardware" && <span className="pill ai" style={{ marginLeft: 6 }}>real board</span>}<div className="xs muted">{d.name}</div></td>
                    <td><span className={`pill ${d.status === "online" ? "good" : d.status === "stale" ? "medium" : "critical"}`}><span className="d" />{d.status}</span>{d.missed > 0 && <div className="xs muted">{d.missed} missed</div>}</td>
                    <td className="num sm">{hhmm(d.last_seen) || "–"}</td>
                    <td className="xs num" style={{ maxWidth: 250 }}>{Object.entries(d.metrics).map(([k, v]: any) => `${k.replace(/_(bar|lpm|pct|l|a|mms|m|ntu|mgl)$/, "")} ${v}`).join(" · ") || "–"}</td>
                    <td className="num sm"><span className="row" style={{ gap: 5 }}><BatteryMedium size={14} color={d.battery_pct < 25 ? "var(--crit)" : "var(--good)"} />{n0(d.battery_pct)}%</span></td>
                    <td className="num sm"><span className="row" style={{ gap: 5 }}><Signal size={14} className="muted" />{d.rssi_dbm} dBm</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
        {village === benchAt ? <BenchNode /> : (
          <div className="card" style={{ alignSelf: "start" }}>
            <div className="card-h"><h3><PlugZap />Hardware in the loop</h3></div>
            <div className="card-b stack sm" style={{ gap: 10 }}>
              <span className="ink2">The bench node stands in for a metered home in {(snap?.summary || []).find((v: any) => v.id === benchAt)?.name || "the pilot village"}, so its controls are shown there. {focus?.name} runs on simulated devices only.</span>
              {(snap?.summary || []).some((v: any) => v.id === benchAt) && <button className="btn ghost sm" style={{ alignSelf: "flex-start" }} onClick={() => setVillage(benchAt)}>Open that village</button>}
            </div>
          </div>
        )}
      </div>

      <SensorBudget study={card?.sensor_study} />

      <div className="grid g2" style={{ marginTop: 16 }}>
        <div className="card">
          <div className="card-h"><h3><CircuitBoard />Parts and indicative prices</h3><span className="pill demo">prototype prices</span></div>
          <div className="tbl-wrap">
            <table className="tbl">
              <thead><tr><th>Part</th><th>Role</th><th style={{ textAlign: "right" }}>Approx. ₹</th></tr></thead>
              <tbody>
                {BOM.map((b) => <tr key={b[0]}><td><b className="sm">{b[0]}</b></td><td className="sm ink2">{b[1]}</td><td className="num" style={{ textAlign: "right" }}>{n0(b[2])}</td></tr>)}
                <tr><td colSpan={2}><b>Full quality node (first nine parts)</b><div className="xs muted">A pressure-only tail node needs about one third of this</div></td><td className="num" style={{ textAlign: "right" }}><b>≈ {n0(total)}</b></td></tr>
              </tbody>
            </table>
          </div>
          <div className="card-b xs muted">Single-unit hobby-market prices for a prototype; not a tender estimate. Recurring costs (probe cleaning and replacement, calibration, SIM data, field visits) usually exceed the purchase price over the life of a node and must be budgeted.</div>
        </div>
        <div className="card">
          <div className="card-h"><h3><SunMedium />Where nodes go, and why not everywhere</h3></div>
          <div className="card-b stack sm" style={{ gap: 11 }}>
            {[
              ["Source and storage (always)", "Borewell level, pump controller (current, vibration, run state), tank level, main outlet flow, one quality node at the tank outlet."],
              ["Every lane: entry and tail", "Pressure and flow at the lane entry, pressure at the tail. The pair gives the lane's head-loss curve, which is what leak and blockage detection needs."],
              ["Three smart taps per lane", "At roughly 20%, 55% and 90% along the lane. They anchor the pressure estimate for every home in between and let a leak be placed between them."],
              ["One tail-end quality node", "On the longest lane, where residual chlorine is lowest and ingress is most likely to show."],
              ["Everyone else: the phone", "Homes without a device are covered by estimation plus their own reports and the daily pulse. Their confidence is shown, never hidden."],
            ].map(([t, d]) => <div key={t}><b>{t}</b><div className="ink2">{d}</div></div>)}
            <div className="note"><Cpu /><span>Edge behaviour in the firmware: a ring buffer of unsent readings, exponential backoff, and idempotent event IDs so a village with patchy signal loses nothing.</span></div>
          </div>
        </div>
      </div>
    </div>
  );
}

/** A real ESP32 (or the script that plays one) standing in for one metered home of the twin. */
function BenchNode() {
  const { data: hw, reload } = usePoll<any>("/api/hardware", 1500);
  const [way, setWay] = useState<"usb" | "wifi" | "script">("usb");
  const host = typeof window !== "undefined" ? window.location.host : "server:8000";
  if (!hw) return <div className="card"><div className="card-b"><Loader /></div></div>;
  const bind = async (id: string) => {
    try { await api("/api/hardware/bind", { body: { household_id: id || null } }); reload(); } catch (e: any) { toast(e.message, true); }
  };
  const m = hw.metrics || {};
  const state = m.pressure_bar == null ? null : m.pressure_bar < 0.15 ? "tap closed" : m.pressure_bar < 0.5 ? "pipe pinched" : "tap open";
  return (
    <div className="stack">
      <div className="card">
        <div className="card-h"><h3><PlugZap />Hardware in the loop</h3><span className={`pill ${hw.live ? "good" : ""}`}><span className="d" />{hw.live ? "board is live" : hw.packets ? "board silent" : "waiting for a board"}</span></div>
        <div className="card-b">
          <p className="sm ink2">A real ESP32 takes the place of one metered home. While it reports, its readings replace the simulated ones for that tap, so the twin, the fault detectors and the household's alerts react to the board on the table.</p>
          <div className="row wrap" style={{ gap: 8, margin: "10px 0" }}>
            <span className="sm" style={{ fontWeight: 600 }}>Stands in for</span>
            <select className="select" style={{ width: "auto", fontWeight: 650 }} value={hw.bound?.household_id || ""} onChange={(e) => bind(e.target.value)}>
              <option value="">no home (readings shown here only)</option>
              {hw.candidates.map((c: any) => <option key={c.household_id} value={c.household_id}>{c.label} · {c.lane}</option>)}
            </select>
            {hw.bound && <Link className="btn ghost sm" to="/app/twin">See it in the twin</Link>}
          </div>
          {hw.packets > 0 ? (
            <div className="grid g3">
              <div><div className="upper muted">Pressure</div><b className="num" style={{ fontSize: 18 }}>{n1(m.pressure_bar, 2)} bar</b></div>
              <div><div className="upper muted">Flow</div><b className="num" style={{ fontSize: 18 }}>{n1(m.flow_lpm, 1)} L/min</b></div>
              <div><div className="upper muted">Reads as</div><b style={{ fontSize: 15 }}>{state}</b><div className="xs muted">{hw.packets} readings · {hw.age_s != null ? `${Math.round(hw.age_s)} s ago` : ""}</div></div>
            </div>
          ) : <div className="note"><Wifi /><span>No board has reported yet. Pick one of the three ways below.</span></div>}
          {hw.packets > 0 && hw.quality === "emulated" && <div className="note demo" style={{ marginTop: 10 }}><Cpu /><span><b>No sensors fitted:</b> the board is generating these values itself (BOOT button: open, pinched, closed). The board, its firmware, the link and everything downstream are real; the pressure and flow are not measurements.</span></div>}
        </div>
      </div>
      <div className="card">
        <div className="card-h"><h3><Terminal />Connect a board</h3>
          <div className="seg">{([["usb", "USB cable"], ["wifi", "Wi-Fi"], ["script", "No board"]] as const).map(([k, l]) => <button key={k} className={way === k ? "on" : ""} onClick={() => setWay(k)}>{l}</button>)}</div></div>
        <div className="card-b">
          {way === "usb" && <><p className="sm ink2"><Usb size={14} style={{ verticalAlign: -2 }} /> Works with no network at all, which is the safe choice in a hall with crowded Wi-Fi. Flash <span className="mono">firmware/jalsakhi_node</span> from the Arduino IDE as it is, close the serial monitor, then run:</p>
            <pre className="code">python firmware/usb_bridge.py</pre></>}
          {way === "wifi" && <><p className="sm ink2">In the sketch set <span className="mono">WIFI_SSID</span>, <span className="mono">WIFI_PASSWORD</span> and the server address, then flash. The laptop and the board must be on the same network and able to see each other.</p>
            <pre className="code">{`SERVER_URL = "http://${host}/api/telemetry"`}</pre></>}
          {way === "script" && <><p className="sm ink2">Plays the board from this computer, posting to the same endpoint. Press <b>o</b>, <b>p</b> or <b>c</b> to open, pinch or close the tap.</p>
            <pre className="code">python firmware/bench_node.py</pre></>}
          <p className="xs muted" style={{ marginTop: 8 }}>The board is silent after {hw.silent_after_s} s without a reading, and the simulator takes the tap back. Readings are validated (known device, registered metrics, plausible ranges) and a repeated event ID is ignored, so a node can resend its buffer safely. Pressure and flow sensors plug into GPIO34 and GPIO27; set <span className="mono">SENSORS_FITTED 1</span>.</p>
        </div>
      </div>
    </div>
  );
}

/** How much do metered taps buy? From the sensor study run with the models (same fault cases, different sensor counts). */
function SensorBudget({ study }: { study: any }) {
  if (!study) return null;
  const rows = study.options.map((o: any) => {
    const hardware = villageHardware(o.taps_per_lane);
    return { ...o, hardware, perHome: hardware / 100, perYear: yearlyPerHome(hardware) };
  });
  const ours = rows.find((r: any) => r.taps_per_lane === study.deployed);
  const every = rows.find((r: any) => r.taps_per_lane === "all");
  const none = rows.find((r: any) => r.taps_per_lane === 0);
  return (
    <div className="card" style={{ marginTop: 16 }}>
      <div className="card-h"><h3><Ruler />How many sensors does a village need?</h3><span className="pill demo">simulated study · indicative prices</span></div>
      <div className="card-b">
        <p className="sm ink2" style={{ maxWidth: 980 }}>The same {study.cases} injected faults, scored again with different numbers of metered taps on each lane. Lane entry and tail sensors are present in every row. Costs are for a village of 100 homes on 5 lanes.</p>
      </div>
      <div className="tbl-wrap">
        <table className="tbl">
          <thead><tr><th>Metered taps per lane</th><th>A leak is placed within</th><th style={{ minWidth: 220 }}>Homes on low pressure that are found</th><th>Hardware per home</th><th>Per home per year</th></tr></thead>
          <tbody>
            {rows.map((r: any) => (
              <tr key={String(r.taps_per_lane)} style={r.taps_per_lane === study.deployed ? { background: "var(--info-bg)" } : undefined}>
                <td><b>{r.taps_per_lane === "all" ? "every home" : r.taps_per_lane}</b>{r.taps_per_lane === study.deployed && <span className="pill info" style={{ marginLeft: 8 }}>what we deploy</span>}</td>
                <td className="num">{r.leak_error_homes == null ? <span className="muted">cannot be placed</span> : `${n1(r.leak_error_homes)} homes`}</td>
                <td><div className="row"><b className="num" style={{ width: 42 }}>{Math.round(r.affected_found * 100)}%</b><div className="bar grow"><i style={{ width: `${r.affected_found * 100}%` }} /></div></div></td>
                <td className="num">₹{n0(r.perHome)}</td>
                <td className="num">₹{n0(r.perYear)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="card-b sm ink2">
        {ours && every && none && <>Three taps per lane place a leak within <b>{n1(ours.leak_error_homes)} homes</b> and find <b>{Math.round(ours.affected_found * 100)}%</b> of the homes on low pressure a few minutes into a fault, against {Math.round(none.affected_found * 100)}% with lane sensors alone.
          Metering every home finds {Math.round(every.affected_found * 100)}% and costs <b>{n1(every.hardware / ours.hardware, 1)} times</b> as much. Past three taps, the extra money buys little until every home has one. The misses are homes whose status has to be inferred between two sensors; a report from one of them settles it.</>}
        <div className="xs muted" style={{ marginTop: 8 }}>{study.note} Yearly cost assumes hardware written off over 5 years, 12% a year for upkeep and one gateway SIM per village. Prices are single-unit prototype prices, not quotations.</div>
      </div>
    </div>
  );
}

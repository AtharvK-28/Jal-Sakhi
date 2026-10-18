import { useEffect, useState } from "react";
import QRCode from "qrcode";
import {
  Activity, Ban, Check, Droplets, FastForward, FlaskConical, Gauge, Minus, Pause, Play, RotateCcw, SkipForward, SlidersHorizontal,
  Smartphone, Sparkles, Users, WifiOff, ZapOff,
} from "lucide-react";
import { api } from "../lib/api";
import { useLive } from "../lib/live";
import { Drawer, toast } from "./ui";

const ICONS: Record<string, any> = { check: Check, ban: Ban, gauge: Gauge, droplets: Droplets, sparkles: Sparkles, activity: Activity, "zap-off": ZapOff, flask: FlaskConical, "wifi-off": WifiOff, minus: Minus, users: Users };
const GROUPS: [string, string][] = [["supply", "Supply & pressure"], ["ai", "AI catches it first"], ["infrastructure", "Infrastructure"], ["quality", "Water quality"], ["community", "Community"], ["data", "Data quality"], ["control", "Recover"]];

/** Floating demo controls: scenario injection, simulation clock, reset, and the phone QR code. Clearly marked DEMO. */
export function DemoPanel() {
  const { clock, village, snap, meta, refresh } = useLive();
  const [open, setOpen] = useState(false);
  const [data, setData] = useState<any>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [qr, setQr] = useState<string>("");
  const name = (snap?.summary || []).find((v: any) => v.id === village)?.name || "village";
  const url = `${meta?.lan_urls?.[0] || window.location.origin}/citizen`;

  useEffect(() => {
    if (!open) return;
    QRCode.toDataURL(url, { margin: 1, width: 220, color: { dark: "#062a4a", light: "#ffffff" } }).then(setQr).catch(() => {});
    const load = () => api("/api/demo/scenarios").then(setData).catch(() => {});
    load();
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
  }, [open, url]);

  const run = async (scn: any) => {
    setBusy(scn.name);
    try {
      const r = await api(`/api/demo/scenario/${scn.name}`, { body: { village_id: village } });
      toast(`${scn.label}: ${r.detail}${r.skipped_ticks ? ` (clock moved to ${r.clock.time})` : ""}`);
      refresh();
    } catch (e: any) { toast(e.message, true); }
    setBusy(null);
  };
  const clk = async (body: any, msg?: string) => {
    setBusy("clock");
    try { await api("/api/demo/clock", { body }); if (msg) toast(msg); refresh(); } catch (e: any) { toast(e.message, true); }
    setBusy(null);
  };
  const reset = async () => {
    setBusy("reset");
    try { await api("/api/demo/reset", { method: "POST" }); toast("Demo reset to the seeded state"); refresh(); } catch (e: any) { toast(e.message, true); }
    setBusy(null);
  };

  return (
    <>
      <button className="fab" onClick={() => setOpen(true)}><SlidersHorizontal />Demo controls</button>
      {open && (
        <Drawer title={<span className="row"><span className="pill demo">DEMO</span>Scenario & clock controls</span>} sub={`Faults are injected into the simulated scheme at ${name}. Detection sees only the resulting sensor readings and citizen reports.`} onClose={() => setOpen(false)}>
          <div className="card pad">
            <div className="row between wrap">
              <div><div className="upper muted">Simulation clock</div>
                <div style={{ fontSize: 24, fontWeight: 750 }} className="num">{clock?.time} <span className="muted sm" style={{ fontWeight: 600 }}>{clock?.date}</span></div>
                <div className="muted sm">{clock?.in_window ? `${clock.window_label} supply window · minute ${clock.min_in_window} of ${clock.window_len}` : `Supply off · next window ${clock?.next_window} (idle time runs 10 min per tick)`}</div>
              </div>
              <div className="row wrap">
                {clock?.running ? <button className="btn ghost sm" disabled={!!busy} onClick={() => clk({ action: "pause" })}><Pause />Pause</button>
                  : <button className="btn sm" disabled={!!busy} onClick={() => clk({ action: "resume" })}><Play />Resume</button>}
                <button className="btn ghost sm" disabled={!!busy} onClick={() => clk({ action: "skip" }, "Jumped to the next supply window")}><SkipForward />Next window</button>
                <button className="btn ghost sm" disabled={!!busy} onClick={reset}><RotateCcw />Reset demo</button>
              </div>
            </div>
            <div className="row" style={{ marginTop: 12 }}>
              <FastForward size={15} className="muted" /><span className="sm muted">Speed</span>
              <div className="seg">{(data?.speeds || [1, 2, 5, 10]).map((s: number) => <button key={s} className={clock?.speed === s ? "on" : ""} onClick={() => clk({ action: "speed", speed: s })}>{s}×</button>)}</div>
              <span className="xs muted">1× = one simulated minute per second</span>
            </div>
          </div>

          {data?.active?.[village]?.length > 0 && (
            <div className="note demo"><Activity /><div><b>Active simulated faults at {name}:</b> {data.active[village].join(" · ")}. Use "Normal operation" below, or record the repair on the incident, to clear them.</div></div>
          )}

          {GROUPS.map(([g, label]) => {
            const items = (data?.scenarios || []).filter((s: any) => s.group === g);
            if (!items.length) return null;
            return (
              <div key={g}>
                <div className="upper muted" style={{ marginBottom: 7 }}>{label}</div>
                <div className="stack" style={{ gap: 8 }}>
                  {items.map((s: any) => {
                    const Icon = ICONS[s.icon] || Activity;
                    return (
                      <button key={s.name} className={`scn ${s.group}`} disabled={!!busy} onClick={() => run(s)}>
                        <span className="ic">{busy === s.name ? <RotateCcw className="spin" /> : <Icon />}</span>
                        <span><b>{s.label}</b><span className="desc">{s.desc}</span></span>
                        <Play size={15} className="muted" />
                      </button>
                    );
                  })}
                </div>
              </div>
            );
          })}

          <div className="card pad">
            <div className="row" style={{ alignItems: "flex-start", gap: 16 }}>
              {qr && <img src={qr} width={128} height={128} alt="QR code for the citizen app" style={{ borderRadius: 12, border: "1px solid var(--line)" }} />}
              <div className="grow">
                <h3 className="row"><Smartphone size={16} color="var(--brand)" />Citizen app on a phone</h3>
                <p className="sm ink2" style={{ marginTop: 5 }}>Scan from a phone on the same Wi-Fi and submit a report. It appears here live, linked to any matching incident.</p>
                <p className="mono" style={{ marginTop: 8, wordBreak: "break-all" }}>{url}</p>
                <a className="btn soft sm" style={{ marginTop: 9 }} href="/citizen" target="_blank" rel="noreferrer">Open in a new tab</a>
              </div>
            </div>
          </div>

          {data?.log?.length > 0 && (
            <div>
              <div className="upper muted" style={{ marginBottom: 7 }}>Scenario log (this session)</div>
              <div className="card pad sm">{[...data.log].reverse().slice(0, 8).map((l: any, i: number) => <div key={i} className="row" style={{ padding: "3px 0" }}><span className="muted num">{l.at}</span><b>{l.label}</b><span className="muted ellipsis">{l.detail}</span></div>)}</div>
            </div>
          )}
        </Drawer>
      )}
    </>
  );
}

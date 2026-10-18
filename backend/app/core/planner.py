"""What-if planner: run the calibrated model of a village forward under a hypothetical change.

Nothing here touches the live scheme or the simulator's hidden state. It uses only what the platform has
learned from telemetry: the tank-head and main-loss fit, each lane's head-loss curve at its measured
points, the demand profile, and the pump's recent discharge. The same model is run twice from the
present tank level, once as things are and once with the change, so the comparison is like for like.

First-order estimate: demand is taken as given (a home at low pressure still asks for its usual water),
so the pressure drop under heavy demand is, if anything, overstated.
"""
from __future__ import annotations

from datetime import timedelta

import numpy as np

from .. import config as C

STEP_MIN = 10
HORIZON_STEPS = 144  # 24 hours


def _run(p, vid: str, demand: float, pump_out_h: float, closed: set[int], start_pct: float | None) -> dict:
    mon, m = p.monitors[vid], p.models
    main = m.main[vid]
    cap, dead = mon.cap, mon.dead_frac * mon.cap
    lvl = start_pct if start_pct is not None else (mon.tank.get("level_pct") if mon.tank.get("level_pct") is not None else 60.0)
    vol = lvl / 100.0 * cap
    rate = mon.pump_rate
    if mon.pump_on_samples:
        rate = float(np.mean([s[2] for s in list(mon.pump_on_samples)[-10:]])) or rate
    pump_ok_now = not p.incidents.is_open(f"{vid}:pump")
    pumping = bool(mon.pump.get("on"))
    t = p.now
    lanes = [{"idx": b, "name": mon.branch_names[b], "n": mon.sizes[b], "closed": b in closed, "min_tail": None, "low_peak": 0}
             for b in range(mon.nb)]
    curve = [[t.strftime("%H:%M"), round(lvl, 1)]]
    empty_at, low_peak, low_at, asked, given = None, 0, None, 0.0, 0.0
    for k in range(HORIZON_STEPS):
        t += timedelta(minutes=STEP_MIN)
        w, mi = C.window_at(t.hour * 60 + t.minute)
        available = pump_ok_now and (k + 1) * STEP_MIN > pump_out_h * 60
        pumping = available and (vol / cap < (0.96 if pumping else 0.60))
        if pumping:
            vol += rate * STEP_MIN
        if w is not None:
            per_home = m.demand_per_home(w, mi) * demand
            q = np.array([per_home * mon.sizes[b] * mon.trackers[b].scale for b in range(mon.nb)])
            asked += float(q.sum()) * STEP_MIN
            open_q = np.array([0.0 if b in closed else q[b] for b in range(mon.nb)])
            if vol > dead + 1:
                given += float(open_q.sum()) * STEP_MIN
                vol -= float(open_q.sum()) * STEP_MIN
                p_in = main["h0"] + main["h1"] * (vol / cap) - main["r"] * (float(open_q.sum()) / main["q_nom"]) ** 2
                low_now = 0
                for b in range(mon.nb):
                    if b in closed:
                        continue
                    tr = mon.trackers[b]
                    u = (open_q[b] / tr.q_nom) ** 2
                    idx = mon.branch_idx[b]
                    press = p_in - np.interp(mon.x[idx], [0.0] + [pt["x"] for pt in tr.pts], [0.0] + [pt["a"] + pt["c"] * u for pt in tr.pts]) - mon.elev[idx]
                    tail = float(p_in - (tr.a + tr.c * u))
                    n_low = int((press < C.P_OK).sum())
                    lane = lanes[b]
                    lane["min_tail"] = tail if lane["min_tail"] is None else min(lane["min_tail"], tail)
                    lane["low_peak"] = max(lane["low_peak"], n_low)
                    low_now += n_low
                if low_now > low_peak:
                    low_peak, low_at = low_now, t
            elif empty_at is None:
                empty_at = t
        vol = min(cap, max(dead, vol))
        if k % 3 == 2:
            curve.append([t.strftime("%H:%M"), round(vol / cap * 100, 1)])
    for lane in lanes:
        lane["min_tail"] = None if lane["min_tail"] is None else round(lane["min_tail"], 2)
    return {"curve": curve, "empty_at": empty_at.isoformat(timespec="minutes") if empty_at else None,
            "hours_to_empty": round((empty_at - p.now).total_seconds() / 3600, 1) if empty_at else None,
            "homes_low_peak": low_peak, "low_peak_at": low_at.strftime("%H:%M") if low_at else None,
            "homes_cut_off": sum(mon.sizes[b] for b in closed),
            "demand_met_pct": round(given / asked * 100, 1) if asked else None, "lanes": lanes}


def what_if(p, vid: str, demand_pct: float = 0.0, pump_out_h: float = 0.0, closed: list[int] | None = None,
            tank_pct: float | None = None) -> dict:
    mon = p.monitors[vid]
    shut = {int(b) for b in (closed or []) if 0 <= int(b) < mon.nb}
    with p.lock:
        base = _run(p, vid, 1.0, 0.0, set(), None)
        case = _run(p, vid, 1.0 + demand_pct / 100.0, max(0.0, pump_out_h), shut, tank_pct)
        # how well the model matches what the sensors say right now: the reason to trust the two runs above
        # (lanes with an open fault are left out: there the model is right and the pipe is wrong)
        check = []
        if p.clock.in_window:
            for b, br in enumerate(mon.branch):
                f = br.get("feats")
                if f and f.get("r") is not None and br.get("p_end") is not None and not p.incidents.is_open(f"{vid}:hyd:{br['id']}"):
                    check.append({"name": br["name"], "predicted_tail": round(br["p_in"] - f["exp_dp"], 2), "measured_tail": round(br["p_end"], 2)})
    return {"village_id": vid, "now": p.now.isoformat(timespec="minutes"), "horizon_h": HORIZON_STEPS * STEP_MIN // 60,
            "inputs": {"demand_pct": demand_pct, "pump_out_h": pump_out_h, "closed": sorted(shut), "tank_pct": tank_pct},
            "baseline": base, "scenario": case, "check": check,
            "basis": "calibrated head-loss curves + learned demand profile + tank mass balance (model run, not a measurement)"}

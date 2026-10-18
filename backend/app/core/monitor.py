"""Per-village monitoring: state estimation ("virtual sensing") and fault detection.

Everything in this module works from sensor telemetry and citizen reports
only. It never reads the simulator's hidden truth; the simulator object is
used solely for static survey metadata (pipe layout, tap elevations, nameplate
ratings) that a real deployment would hold in its asset register.

Language rule: an alert names what was observed and what to check. It says
"suspected", "verification required", "no recent telemetry"; it never asserts
a confirmed root cause or a potability verdict.
"""
from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime, timedelta

import numpy as np

from .. import config as C
from ..ml import models as ML

OK, LOW, DRY, UNKNOWN, IDLE = 0, 1, 2, 3, 4
STATUS_NAME = ["ok", "low", "dry", "unknown", "idle"]


class VillageMonitor:
    def __init__(self, ctx, sim):
        self.ctx = ctx
        self.id, self.code, self.name = sim.id, sim.code, sim.name
        # ---- static asset-register data
        self.nb, self.n, self.sizes = sim.nb, sim.n, list(sim.sizes)
        self.b_of, self.x, self.elev = sim.b_of.copy(), sim.x.copy(), sim.elev.copy()
        self.members = sim.members.copy()
        self.instrumented = sim.instrumented.copy()
        self.slope, self.q_nom = sim.slope.copy(), sim.q_nom.copy()
        self.hh_ids, self.branch_ids, self.branch_names = sim.hh_ids, sim.branch_ids, sim.branch_names
        self.cap, self.dead_frac = sim.cap, sim.dead / sim.cap
        self.i_nom, self.v_nom, self.pump_rate = sim.i_nom, sim.v_nom, sim.pump_rate
        self.dd_max, self.intake = sim.dd_max, sim.pump_intake_depth
        self.wq2_branch = sim.wq2_branch
        self.device_ids = list(sim.devices.keys())
        self.branch_idx = [np.flatnonzero(self.b_of == b) for b in range(self.nb)]
        self.inst_idx = [idx[self.instrumented[idx]] for idx in self.branch_idx]
        self.labels = [f"HH-{i + 1:03d}" for i in range(self.n)]

        m = ctx.models
        self.trackers = [m.tracker(self.branch_ids[b], self.sizes[b], float(self.q_nom[b]),
                                   [float(self.elev[i]) for i in self.inst_idx[b]] + [float(self.slope[b])]) for b in range(self.nb)]
        self.p_leak: list = [None] * self.nb  # smoothed leak probability per lane while an alarm is up
        self.loc: list = [None] * self.nb  # last fault position per lane
        self.wear_hist: deque = deque(maxlen=120)  # (run-hours, wear index) while the pump runs
        self.bal = {"supplied": 0.0, "pumped": 0.0, "kwh": 0.0, "lane": [0.0] * self.nb, "win0": 0.0}  # today's water and energy
        self.meter_l = 0.0  # litres the main flow sensor has counted since monitoring began
        self.pump_min = 0.0  # minutes the pump controller has reported running
        self.tap_out: list[set] = [set() for _ in range(self.nb)]  # metered taps reading below the lane around them
        self.lane_at: dict[int, float] = {}  # for such a tap: the pressure its neighbours imply at its position
        self.ok_min = np.zeros(self.n)  # minutes of usable pressure today, per home
        self.known_min = np.zeros(self.n)  # minutes of supply today in which the home's status was known
        # ---- estimated state
        self.status = np.full(self.n, IDLE)
        self.p_est = np.zeros(self.n)
        self.conf = np.zeros(self.n)
        self.vol = np.zeros(self.n)  # litres received today (measured or estimated)
        self.win_start_vol = np.zeros(self.n)
        self.unk_ticks = np.zeros(self.n)
        self.win_ticks = 0
        self.qual_bad = np.zeros(self.n, dtype=bool)
        self.served = [None, None]  # per window: bool array once the window has closed
        self.qty_ok = [None, None]
        self.qual_ok = [None, None]
        self.known = [None, None]
        self.branch: list[dict] = [
            {"id": self.branch_ids[b], "idx": b, "name": self.branch_names[b], "n": self.sizes[b], "p_in": None,
             "p_end": None, "flow": None, "fresh_in": False, "fresh_end": False, "feats": None, "score": 0.0}
            for b in range(self.nb)]
        self._rows: list = []
        self._row_b: list = []
        self.zq_hist = [deque(maxlen=8) for _ in range(self.nb)]
        self.anom_s = np.zeros(self.nb)
        self.low_latched = [False] * self.nb
        self.count: dict[str, int] = defaultdict(int)
        self.clear_n: dict[str, int] = defaultdict(int)
        self.pump_on_samples: deque = deque(maxlen=20)
        self.pump: dict = {"risk": None, "health": None, "run_h": float(sim.spec.get("pump_age_h", 900.0))}
        self.tank: dict = {}
        self.forecast: dict = {"curve": [], "empty_at": None}
        self.quality: list[dict] = []
        self.source: dict = {}
        self.pump_off_min = 0.0
        self.supply_min = 0.0  # minutes of delivered supply today
        self.sched_min = 0.0  # scheduled minutes elapsed today
        self.kpis: dict = {}
        self.truth_agree = [0, 0]  # demo-only validation of the estimator against simulator truth
        self.gw_hist = [(r["day"], r["gw_depth_m"]) for r in ctx.history.get(self.id, []) if r.get("gw_depth_m") is not None]
        if self.gw_hist:
            self.source["rest_m"] = self.gw_hist[-1][1]

    # ============================================================ estimation
    def update(self, clk):
        T = self.ctx.telemetry
        c = self.code
        if clk.new_day:
            self.vol[:] = 0
            self.served, self.qty_ok, self.qual_ok, self.known = [None, None], [None, None], [None, None], [None, None]
            self.supply_min = self.sched_min = 0.0
            self.bal = {"supplied": 0.0, "pumped": 0.0, "kwh": 0.0, "lane": [0.0] * self.nb, "win0": 0.0}
            self.ok_min[:] = 0
            self.known_min[:] = 0
        if clk.new_window:
            self.bal["win0"] = self.bal["supplied"]
            self.win_start_vol = self.vol.copy()
            self.unk_ticks[:] = 0
            self.win_ticks = 0
            self.qual_bad[:] = False
            for zq in self.zq_hist:
                zq.clear()

        in_win = clk.win_idx is not None
        rows, row_b = [], []
        for b in range(self.nb):
            bid = self.branch_ids[b]
            f_in, f_end = T.fresh(f"{bid}-IN"), T.fresh(f"{bid}-END")
            p_in = T.value(f"{bid}-IN", "pressure_bar") if f_in else None
            q = T.value(f"{bid}-IN", "flow_lpm") if f_in else None
            p_end = T.value(f"{bid}-END", "pressure_bar") if f_end else None
            br = {"id": bid, "idx": b, "name": self.branch_names[b], "n": self.sizes[b], "p_in": p_in, "p_end": p_end,
                  "flow": q, "fresh_in": f_in, "fresh_end": f_end, "feats": None, "score": 0.0}
            self.tap_out[b] = set()
            if in_win and f_in and p_in is not None and q is not None and p_in >= C.P_DRY:
                taps = [T.value(f"{self.hh_ids[i]}-TAP", "pressure_bar") if T.fresh(f"{self.hh_ids[i]}-TAP") else None
                        for i in self.inst_idx[b]]
                self.tap_out[b] = self._local_drops(b, taps, p_end)
                taps = [None if int(i) in self.tap_out[b] else p for i, p in zip(self.inst_idx[b], taps)]  # they say nothing about the lane
                feats = self.trackers[b].update(clk.win_idx, clk.min_in_win, p_in, p_end, q, taps)
                br["feats"] = feats
                if feats["x"] is not None:  # the anomaly model needs the tail sensor
                    rows.append(feats["x"])
                    row_b.append(b)
                    self.zq_hist[b].append(feats["z_q"])
                self.bal["lane"][b] += q * clk.dt
            self.branch[b] = br
        self._rows, self._row_b = rows, row_b
        if not in_win:
            self.anom_s *= 0.5

        if in_win:
            self.win_ticks += 1
            self.sched_min += clk.dt
            for b in range(self.nb):
                self._estimate_branch(b, clk.dt)
            self.unk_ticks += self.status == UNKNOWN
            self.ok_min += (self.status == OK) * clk.dt
            self.known_min += (self.status != UNKNOWN) * clk.dt
            if any(br["fresh_in"] and (br["p_in"] or 0) >= C.P_DRY for br in self.branch):
                self.supply_min += clk.dt
            self.qual_bad |= self._quality_affected()
        else:
            self.status[:] = IDLE
            self.p_est[:] = 0
        if clk.closed_idx is not None:
            self._close_window(clk.closed_idx)

        # ---- tank, pump, source, quality
        lvl_fresh = T.fresh(f"{c}-TANK")
        self.tank = {"level_pct": T.value(f"{c}-TANK", "level_pct"), "volume_l": T.value(f"{c}-TANK", "volume_l"),
                     "capacity_l": self.cap, "fresh": lvl_fresh}
        self._update_pump(clk)
        if in_win and T.fresh(f"{c}-MAIN"):
            self.bal["supplied"] += T.value(f"{c}-MAIN", "flow_lpm", 0.0) * clk.dt
            self.meter_l += T.value(f"{c}-MAIN", "flow_lpm", 0.0) * clk.dt
        self._update_source(clk)
        self.quality = []
        for i, dev in enumerate((f"{c}-WQ1", f"{c}-WQ2")):
            rec = T.latest.get(dev)
            fresh = T.fresh(dev)
            mvals = rec["m"] if rec else {}
            self.quality.append({"id": dev, "name": "Tank outlet" if i == 0 else f"{self.branch_names[self.wq2_branch]} tail",
                                 "fresh": fresh, **{k: mvals.get(k) for k in ("turbidity_ntu", "chlorine_mgl", "ph", "tds_mgl")},
                                 "status": self._quality_status(mvals) if fresh else "unknown"})
        if self.ctx.tick % 5 == 0 or not self.forecast["curve"]:
            self._forecast(clk)

    def apply_scores(self, scores):
        """Receive this tick's anomaly scores (the platform scores all villages in one batch)."""
        for b, s in zip(self._row_b, scores):
            self.branch[b]["score"] = float(s)
            self.anom_s[b] = 0.3 * s + 0.7 * self.anom_s[b]

    def _local_drops(self, b: int, taps: list, p_end: float | None) -> set[int]:
        """Metered taps whose hydraulic grade is clearly below a measured point further down the lane.

        Grade never rises along a pipe, so this cannot be a fault in the lane itself: it is in that home's own
        connection (stopcock, ferrule, service pipe) or its sensor. Such a tap is still the truth about its own
        home, but it says nothing about its neighbours and is left out of the lane's estimate and models."""
        idx = self.inst_idx[b]
        grades = [None if p is None else p + float(self.elev[i]) for i, p in zip(idx, taps)]
        grades.append(None if p_end is None else p_end + float(self.slope[b]))
        out = set()
        for j, g in enumerate(grades[:-1]):
            below = [d for d in grades[j + 1:] if d is not None]
            if g is not None and below and max(below) - g >= C.TAP_DROP_BAR:
                out.add(int(idx[j]))
        return out

    def _estimate_branch(self, b: int, dt: float):
        """Interpolate the hydraulic grade between whatever pressure points are fresh."""
        T = self.ctx.telemetry
        bid = self.branch_ids[b]
        idx = self.branch_idx[b]
        br = self.branch[b]
        pts = []
        if br["fresh_in"]:
            pts.append((0.0, br["p_in"]))
        measured = {}
        for i in self.inst_idx[b]:
            dev = f"{self.hh_ids[i]}-TAP"
            if T.fresh(dev):
                p = T.value(dev, "pressure_bar")
                measured[i] = p
                if int(i) not in self.tap_out[b]:
                    pts.append((float(self.x[i]), p + float(self.elev[i])))
        if br["fresh_end"]:
            pts.append((1.0, br["p_end"] + float(self.slope[b])))
        if not pts:
            self.status[idx], self.conf[idx], self.p_est[idx] = UNKNOWN, 0.0, 0.0
            return
        pts.sort()
        xs = np.array([p[0] for p in pts])
        gs = np.array([p[1] for p in pts])
        xi = self.x[idx]
        p = np.maximum(np.interp(xi, xs, gs) - self.elev[idx], 0.0)
        dist = np.abs(xi[:, None] - xs[None, :]).min(axis=1)
        inside = (xi >= xs[0] - 1e-9) & (xi <= xs[-1] + 1e-9)
        conf = np.clip(0.92 - 1.1 * dist, 0.3, 0.92) * np.where(inside, 1.0, 0.6)
        if br["fresh_in"] and br["p_in"] < C.P_DRY:  # entry is dry: nothing downstream can have water
            p[:] = 0.0
            conf[:] = 0.9
        for j, i in enumerate(idx):
            if i in measured:
                if int(i) in self.tap_out[b]:
                    self.lane_at[int(i)] = float(p[j])  # what the lane holds here, before the home's own reading replaces it
                p[j], conf[j] = measured[i], 0.98
        st = np.where(p >= C.P_OK, OK, np.where(p >= C.P_DRY, LOW, DRY))
        st[conf < 0.4] = UNKNOWN
        self.status[idx], self.conf[idx], self.p_est[idx] = st, conf, p

        # ---- volume: measured taps report their own; the rest share the remaining branch inflow
        meas_flow = 0.0
        for i in measured:
            self.vol[i] = T.value(f"{self.hh_ids[i]}-TAP", "volume_l", self.vol[i])
            meas_flow += T.value(f"{self.hh_ids[i]}-TAP", "flow_lpm", 0.0)
        if br["fresh_in"] and br["flow"] is not None:
            rest = [j for j, i in enumerate(idx) if i not in measured]
            if rest:
                loss = 0.0
                inc = self.ctx.incidents.get_by_key(f"{self.id}:hyd:{bid}")
                if inc is not None and inc["type"] == "SUSPECTED_LEAK" and br["feats"]:
                    loss = max(0.0, br["flow"] - br["feats"]["exp_q"])
                avail = max(0.0, br["flow"] - meas_flow - loss)
                w = np.sqrt(p[rest])
                if w.sum() > 0:
                    self.vol[idx[rest]] += avail * dt * w / w.sum()

    def _quality_affected(self) -> np.ndarray:
        mask = np.zeros(self.n, dtype=bool)
        for inc in self.ctx.incidents.items.values():
            if inc["village_id"] != self.id or inc["category"] not in ("quality",) and not (
                    inc["type"] == "COMMUNITY_CLUSTER" and "quality" in inc["cond_key"]):
                continue
            if inc["scope_type"] == "scheme":
                mask[:] = True
            elif inc["branch_id"] in self.branch_ids:
                mask[self.branch_idx[self.branch_ids.index(inc["branch_id"])]] = True
        return mask

    def _close_window(self, w: int):
        """Score the window that just ended against the JJM functionality tests."""
        got = self.vol - self.win_start_vol
        target = C.LPCD_NORM * self.members * C.WINDOW_SHARE[w]
        self.known[w] = self.unk_ticks <= 0.5 * max(1, self.win_ticks)
        self.served[w] = got >= 20.0
        self.qty_ok[w] = got >= 0.9 * target
        self.qual_ok[w] = ~self.qual_bad

    def day_flags(self) -> dict | None:
        """Per-household regularity / quantity / quality over the windows completed today."""
        done = [w for w in range(len(C.SUPPLY_WINDOWS)) if self.served[w] is not None]
        if not done:
            return None
        reg = np.all([self.served[w] for w in done], axis=0)
        qty = np.all([self.qty_ok[w] for w in done], axis=0)
        qual = np.all([self.qual_ok[w] for w in done], axis=0)
        known = np.all([self.known[w] for w in done], axis=0)
        return {"regular": reg, "quantity": qty, "quality": qual, "known": known, "functional": reg & qty & qual & known,
                "windows": len(done)}

    @staticmethod
    def _quality_status(m: dict) -> str:
        if not m:
            return "unknown"
        L = C.QUALITY_LIMITS
        bad = (m.get("turbidity_ntu", 0) > L["turbidity_ntu"]["permissible"] or m.get("chlorine_mgl", 1) < L["chlorine_mgl"]["min"]
               or not L["ph"]["min"] <= m.get("ph", 7) <= L["ph"]["max"] or m.get("tds_mgl", 0) > L["tds_mgl"]["permissible"])
        if bad:
            return "verify"
        watch = m.get("turbidity_ntu", 0) > L["turbidity_ntu"]["acceptable"] or m.get("tds_mgl", 0) > L["tds_mgl"]["acceptable"]
        return "watch" if watch else "ok"

    def _update_pump(self, clk):
        T = self.ctx.telemetry
        dev = f"{self.code}-PUMP"
        rec = T.latest.get(dev)
        fresh = T.fresh(dev)
        m = rec["m"] if rec else {}
        on = bool(m.get("state"))
        if fresh and on:
            self.pump_on_samples.append((m["current_a"], m["vibration_mms"], m["discharge_lpm"]))
            self.pump["run_h"] += clk.dt / 60.0
            self.pump_min += clk.dt
            self.pump_off_min = 0.0
            self.bal["pumped"] += m["discharge_lpm"] * clk.dt
            self.bal["kwh"] += 1.732 * 415 * m["current_a"] * 0.85 / 1000 * clk.dt / 60  # three-phase estimate from motor current
            if len(self.pump_on_samples) >= 5:
                recent = np.array(list(self.pump_on_samples)[-6:])
                cur, vib, dis = recent.mean(axis=0)
                feats = ML.pump_features(cur, vib, dis, self.i_nom, self.v_nom, self.pump_rate, self.pump["run_h"])
                models = self.ctx.models
                self.pump["risk"] = models.pump_risk(feats)
                wear = models.wear_index(feats)
                self.pump["health"] = round(float(np.clip(1.0 - wear, 0, 1)) * 100, 1)
                if self.wear_hist and abs(wear - self.wear_hist[-1][1]) > 0.04:
                    self.wear_hist.clear()  # a jump is a changed pump or a serviced one, not wear: start the trend again
                self.wear_hist.append((self.pump["run_h"], wear))
                own = ML.trend_rul([w[0] for w in self.wear_hist], [w[1] for w in self.wear_hist]) if len(self.wear_hist) >= 12 else None
                if own:  # this pump's own wear trend, when it is clearly rising
                    self.pump["life"] = {"h": round(own["h"], 1), "lo": round(own["lo"], 1), "hi": round(own["hi"], 1), "basis": "own trend"}
                elif self.ctx.tick % 10 == 0 or "life" not in self.pump:  # otherwise what pumps in this condition usually have left
                    fleet = models.pump_life(feats)
                    self.pump["life"] = {"h": round(fleet["h"]), "lo": round(fleet["lo"]), "hi": round(fleet["hi"]), "basis": "fleet histories",
                                         "capped": fleet["h"] >= ML.RUL_CAP_H - 25}
        elif fresh:
            self.pump_off_min += clk.dt
        self.pump.update(fresh=fresh, on=on, cmd=bool(m.get("cmd")), current_a=m.get("current_a"),
                         vibration_mms=m.get("vibration_mms"), discharge_lpm=m.get("discharge_lpm"))

    def _update_source(self, clk):
        T = self.ctx.telemetry
        dev = f"{self.code}-SRC"
        fresh = T.fresh(dev)
        depth = T.value(dev, "depth_m")
        src = self.source
        src.update(fresh=fresh, depth_m=depth, intake_m=self.intake)
        if fresh and depth is not None and self.pump_off_min >= 90:  # drawdown has recovered: this is the rest level
            src["rest_m"] = depth
        rest = src.get("rest_m")
        pts = [d for _day, d in self.gw_hist[-14:]]
        if rest is not None and len(pts) >= 5:
            ys = np.array(pts + [rest])
            slope = float(np.polyfit(np.arange(len(ys)), ys, 1)[0])  # metres per day, positive = falling water table
            margin = self.intake - 1.0 - self.dd_max - rest
            src.update(trend_m_per_day=round(slope, 3), margin_m=round(margin, 2),
                       days_to_limit=round(margin / slope, 1) if slope > 0.02 else None,
                       history=[round(v, 2) for v in ys[-15:]])

    def _forecast(self, clk):
        """Project the tank level 24 h ahead: mass balance + learned demand profile + pump availability."""
        lvl = self.tank.get("level_pct")
        if lvl is None or not self.tank.get("fresh"):
            self.forecast = {"curve": [], "empty_at": None, "basis": "no fresh tank level"}
            return
        m = self.ctx.models
        pump_ok = not self.ctx.incidents.is_open(f"{self.id}:pump")
        rate = self.pump_rate
        if self.pump_on_samples:
            rate = float(np.mean([s[2] for s in list(self.pump_on_samples)[-10:]])) or rate
        vol = lvl / 100.0 * self.cap
        t = clk.now
        pumping = self.pump.get("on", False)
        step = 10
        curve, empty_at = [[t.strftime("%H:%M"), round(lvl, 1)]], None
        for _ in range(144):
            t += timedelta(minutes=step)
            w, mi = C.window_at(t.hour * 60 + t.minute)
            frac = vol / self.cap
            pumping = pump_ok and (frac < (0.96 if pumping else 0.60))
            if pumping:
                vol += rate * step
            if w is not None and vol > self.dead_frac * self.cap:
                vol -= m.expected_demand_lpm(w, mi, self.n) * step
            vol = min(self.cap, max(self.dead_frac * self.cap, vol))
            if empty_at is None and vol <= self.dead_frac * self.cap + 1 and w is not None:
                empty_at = t
            curve.append([t.strftime("%H:%M"), round(vol / self.cap * 100, 1)])
        self.forecast = {"curve": curve[::3], "empty_at": empty_at.isoformat(timespec="minutes") if empty_at else None,
                         "hours_to_empty": round((empty_at - clk.now).total_seconds() / 3600, 1) if empty_at else None,
                         "pump_available": pump_ok,
                         "basis": "mass balance + learned demand profile" + ("" if pump_ok else " (pump unavailable)")}

    # ============================================================= detection
    def _persist(self, key: str, cond: bool, need: int, label: str | None = None) -> bool:
        if cond:
            self.count[key] += 1
        else:
            n = self.count[key]
            if label and 1 <= n < need and not self.ctx.quiet:
                self.ctx.feed("transient", "muted", f"{label}: {n} sample(s) only, rule needs {need}. No alert raised.", self.id)
            self.count[key] = 0
        return self.count[key] >= need

    def _settle(self, key: str, active: bool, pending: bool = False, note: str | None = None):
        """Track how long a condition has been clear and report recovery to the incident manager."""
        if active or pending:
            self.clear_n[key] = 0
            return
        self.clear_n[key] += 1
        if self.clear_n[key] == C.CLEAR_SAMPLES and self.ctx.incidents.is_open(key):
            self.ctx.incidents.clear(key, note or "Telemetry indicates the condition has cleared")

    def detect(self, clk):
        inc = self.ctx.incidents
        T = self.ctx.telemetry
        vid, c = self.id, self.code
        self._detect_offline()
        self._detect_pump()
        self._detect_quality()
        self._detect_source()

        in_rules = clk.win_idx is not None and clk.min_in_win >= C.WINDOW_GRACE_MIN
        scheme_key = f"{vid}:scheme"
        if in_rules:
            fresh_b = [b for b in self.branch if b["fresh_in"]]
            main_fresh = T.fresh(f"{c}-MAIN")
            dead = bool(fresh_b) and all(b["p_in"] < C.P_DRY for b in fresh_b)
            cond = main_fresh and T.value(f"{c}-MAIN", "flow_lpm", 0) < 2.0 and dead
            hit = self._persist(scheme_key, cond, C.PERSIST["interruption"])
            if hit:
                lvl = self.tank.get("level_pct")
                if lvl is not None and lvl < 6:
                    cause = f"Tank is empty (level {lvl:.0f}%)."
                    if inc.is_open(f"{vid}:pump"):
                        cause += " The pump is not delivering, so the tank was not refilled."
                    action = "Restore pumping; arrange tanker supply if restoration will take more than a few hours."
                else:
                    cause = (f"Tank holds water (level {lvl:.0f}%) but nothing is leaving it: "
                             "main outlet valve closed or a failure on the main line.") if lvl is not None else \
                        "No flow on the main and no pressure on any branch."
                    action = "Check the main outlet valve at the tank and walk the main line for a break."
                inc.raise_(scheme_key, vid, "SUPPLY_INTERRUPTION", "critical", scope_type="scheme", scope_id=vid,
                           affected_ids=list(self.hh_ids),
                           title=f"No water supply across {self.name} during the scheduled window",
                           summary=f"Main flow is zero and no branch is pressurised {int(clk.min_in_win)} min into the "
                                   f"{C.SUPPLY_WINDOWS[clk.win_idx][2].lower()} supply window. All {self.n} households are affected.",
                           cause="Suspected: " + cause, action=action, confidence=0.9,
                           evidence={"main_flow_lpm": T.value(f"{c}-MAIN", "flow_lpm"), "tank_level_pct": lvl,
                                     "branches_pressurised": 0, "devices": [f"{c}-MAIN"] + [f"{b['id']}-IN" for b in fresh_b]})
                if inc.is_open(f"{vid}:forecast"):
                    inc.clear(f"{vid}:forecast", "The predicted shortfall has occurred; see the scheme interruption incident")
            self._settle(scheme_key, hit, cond, "Main flow and branch pressure have returned")
            scheme_down = hit or cond
            for b in range(self.nb):
                self._detect_branch(clk, b, scheme_down)
                if not scheme_down:
                    self._detect_taps(b)
                    self._detect_boosters(b)
        self._detect_forecast(clk)

    def _detect_taps(self, b: int):
        """One home's tap not delivering while its lane is: the household-level fault a lane alarm cannot see.

        Only metered homes can be judged from telemetry. The others rely on the household's own report and
        the daily pulse."""
        inc, T = self.ctx.incidents, self.ctx.telemetry
        br = self.branch[b]
        if not br["fresh_in"] or (br["p_in"] or 0.0) < C.P_DRY:
            return  # the lane itself has no water: nothing can be said about one tap
        bid, lane = br["id"], br["name"]
        for i in self.inst_idx[b]:
            i = int(i)
            dev = f"{self.hh_ids[i]}-TAP"
            if not T.fresh(dev):
                continue
            p = T.value(dev, "pressure_bar")
            key = f"{self.id}:tap:{self.hh_ids[i]}"
            cond = i in self.tap_out[b] and p < C.P_OK
            hit = self._persist(key, cond, C.PERSIST["tap"])
            if hit:
                label, here = self.labels[i], self.lane_at.get(i, br["p_in"])
                real = (T.latest.get(dev) or {}).get("source") == "hardware"
                dry = p < C.P_DRY
                inc.raise_(key, self.id, "TAP_FAULT", "medium", scope_type="household", scope_id=self.hh_ids[i], branch_id=bid,
                           affected_ids=[self.hh_ids[i]], confidence=0.85,
                           title=(f"Tap at {label} is not delivering while {lane} is" if dry else
                                  f"Low pressure at {label} only: the rest of {lane} is fine"),
                           summary=f"The tap node at {label} reads {p:.2f} bar while the lane around it holds about {here:.2f} bar, "
                                   "and a measured point further down the lane reads higher than this tap. Pressure cannot rise "
                                   "along a pipe, so the fault is in this home's own connection, not in the lane. One household is affected."
                                   + (" The reading comes from the hardware bench node." if real else ""),
                           cause="Suspected: a closed or blocked stopcock or ferrule, a kinked or broken service pipe, or a failed tap sensor.",
                           action=f"Visit {label}: check the stopcock and the service pipe, then run a bucket test at the tap. "
                                  "If water flows normally, the tap node needs replacing.",
                           evidence={"tap_bar": round(p, 3), "lane_bar_here": round(here, 3), "source": "hardware" if real else "simulation",
                                     "devices": [dev]})
            self._settle(key, hit, cond, f"The tap at {self.labels[i]} is delivering again")

    def _booster_explains(self, b: int) -> bool:
        """Is a metered tap on this lane pumping right now (seen, or an open suction-pump incident not yet recovered)?"""
        for i in self.inst_idx[b]:
            key = f"{self.id}:boost:{self.hh_ids[int(i)]}"
            open_ = self.ctx.incidents.get_by_key(key)
            if self.count[key] > 0 or (open_ is not None and not open_["recovered_at"]):
                return True
        return False

    def _detect_boosters(self, b: int):
        """A household pumping straight from the lane: its metered tap draws several times what any tap can at that
        pressure, while the homes after it on the lane lose pressure. Common in intermittent supply; it starves the tail."""
        inc, T = self.ctx.incidents, self.ctx.telemetry
        br = self.branch[b]
        if not br["fresh_in"] or (br["p_in"] or 0.0) < C.P_DRY:
            return
        flows = {}
        for b2 in range(self.nb):
            for i in self.inst_idx[b2]:
                dev = f"{self.hh_ids[int(i)]}-TAP"
                if T.fresh(dev):
                    flows[int(i)] = T.value(dev, "flow_lpm", 0.0)
        bid, lane = br["id"], br["name"]
        for i in self.inst_idx[b]:
            i = int(i)
            q = flows.get(i)
            others = [v for j, v in flows.items() if j != i and v > 2.0]  # taps that are filling
            typical = float(np.median(others)) if len(others) >= 3 else 9.0
            key = f"{self.id}:boost:{self.hh_ids[i]}"
            cond = q is not None and q > max(18.0, 2.2 * typical)
            hit = self._persist(key, cond, C.PERSIST["tap"])
            if hit:
                down = [int(j) for j in self.branch_idx[b] if self.x[j] > self.x[i]]
                starved = int(np.isin(self.status[down], [LOW, DRY]).sum()) if down else 0
                label = self.labels[i]
                tail = br["p_end"] if br["fresh_end"] else None
                inc.raise_(key, self.id, "SUSPECTED_BOOSTER", "medium" if starved else "low", scope_type="household",
                           scope_id=self.hh_ids[i], branch_id=bid, affected_ids=[self.hh_ids[j] for j in down], confidence=0.8,
                           title=f"Suspected suction pump at {label}: homes after it on {lane} lose pressure",
                           summary=f"The tap at {label} draws {q:.0f} L/min, {q / typical:.1f} times a typical filling tap in this "
                                   f"village ({typical:.0f} L/min), which no tap can do on the lane's pressure alone. "
                                   f"{len(down)} homes are downstream of it; {starved} are on low pressure or dry right now"
                                   + (f", and the tail of the lane reads {tail:.2f} bar." if tail is not None else "."),
                           cause="Suspected: an electric pump fitted on the household tap, filling a drum or overhead tank at the "
                                 "start of supply (or a broken service pipe running free).",
                           action=f"Pani Samiti or operator to visit {label} in the first half hour of supply. If a pump is fitted, "
                                  "explain what it does to the homes after it and agree its removal; the committee can make this a "
                                  "condition of the connection. If there is none, check the service pipe for a break.",
                           evidence={"tap_flow_lpm": round(q, 1), "typical_lpm": round(typical, 1), "ratio": round(q / typical, 1),
                                     "downstream_homes": len(down), "starved_now": starved, "tail_bar": None if tail is None else round(tail, 3),
                                     "devices": [f"{self.hh_ids[i]}-TAP"]})
            self._settle(key, hit, cond, f"The tap at {self.labels[i]} is drawing a normal flow again")

    def _detect_branch(self, clk, b: int, scheme_down: bool):
        inc = self.ctx.incidents
        T = self.ctx.telemetry
        br = self.branch[b]
        bid, lane = br["id"], br["name"]
        key = f"{self.id}:hyd:{bid}"
        if scheme_down or not br["fresh_in"]:
            for sfx in (":int", ":low", ":anom"):
                self.count[key + sfx] = 0
            return
        p_in, q, feats = br["p_in"], br["flow"], br["feats"]
        tail_p = br["p_end"] if br["fresh_end"] else None
        if tail_p is None:  # tail sensor silent: fall back to the furthest fresh smart tap
            taps = [(self.x[i], T.value(f"{self.hh_ids[i]}-TAP", "pressure_bar")) for i in self.inst_idx[b]
                    if T.fresh(f"{self.hh_ids[i]}-TAP")]
            if taps:
                tail_p = max(taps)[1]
        tr = self.trackers[b]
        measured = feats is not None and feats["x"] is not None
        cond_int = p_in < C.P_DRY
        limit = C.P_LOW_CLEAR if self.low_latched[b] else C.P_LOW_TRIGGER
        cond_low = (not cond_int) and tail_p is not None and tail_p < limit
        cond_anom = (not cond_int) and measured and br["score"] >= C.ANOMALY_SCORE and abs(feats["z_r"]) >= 3.0
        # sequential test: enough accumulated evidence, and the residual is still up (so it lets go after a repair)
        cond_seq = (not cond_int) and measured and tr.cusum >= tr.h and float(np.mean([h["z_r"] for h in list(tr.hist)[-3:]])) >= 0.8
        hit_int = self._persist(key + ":int", cond_int, C.PERSIST["interruption"])
        hit_low = self._persist(key + ":low", cond_low, C.PERSIST["low_pressure"], f"Brief pressure dip on {lane}")
        hit_anom = self._persist(key + ":anom", cond_anom, C.PERSIST["anomaly"]) or cond_seq
        self.low_latched[b] = hit_low
        idx = self.branch_idx[b]
        if hit_int:
            inc.raise_(key, self.id, "SUPPLY_INTERRUPTION", "high", scope_type="branch", scope_id=bid, branch_id=bid,
                       affected_ids=[self.hh_ids[i] for i in idx], confidence=0.88,
                       title=f"No water on {lane} while the rest of the village is being supplied",
                       summary=f"Entry pressure on {lane} is {p_in:.2f} bar and flow is {q:.0f} L/min; other branches are "
                               f"pressurised. All {len(idx)} households on this lane are without water.",
                       cause="Suspected: branch isolation valve closed or failed, or a complete blockage/break at the head of the lane.",
                       action=f"Inspect the isolation valve at the head of {lane}, then the first pipe segment downstream.",
                       evidence={"p_in_bar": p_in, "flow_lpm": q, "devices": [f"{bid}-IN", f"{bid}-END"]})
        elif (hit_low or hit_anom) and self._booster_explains(b):
            pass  # one tap pumping explains the extra flow and the lost pressure: no leak hunt; the pump incident says why
        elif hit_low or hit_anom:
            wm = ML.window_means(tr.hist)
            zq = wm["z_q"] if wm else (float(np.mean(self.zq_hist[b])) if self.zq_hist[b] else 0.0)
            z_r = feats["z_r"] if feats else 0.0
            # Leak or obstruction? Both lose pressure. The classifier reads the pattern along the lane (a leak's loss
            # builds up to the leak and draws extra flow; an obstruction's loss appears at one point). A citizen who
            # reports seeing the leak lowers the bar, and a lane already called a leak stays one unless the evidence turns.
            prior = inc.get_by_key(key)
            seen = bool(prior and (prior["evidence"] or {}).get("citizen_leak_reports"))
            if wm and wm["rb"][-1] is not None and wm["z_r"] >= 1.5 and (self.p_leak[b] is None or self.ctx.tick % 3 == 0):
                now_p = self.ctx.models.fault_type(wm)  # re-read every third reading: the pattern does not change faster
                self.p_leak[b] = now_p if self.p_leak[b] is None else 0.5 * now_p + 0.5 * self.p_leak[b]
            p_leak = self.p_leak[b]
            sticky = seen or bool(prior and prior["type"] == "SUSPECTED_LEAK")
            leak_like = p_leak is not None and p_leak >= (0.45 if sticky else 0.7)
            obstruction_like = p_leak is not None and p_leak <= 0.3
            seg = self._localise(b, wm, leak_like, prior)
            affected = [self.hh_ids[i] for i in idx if self.status[i] in (LOW, DRY)]
            ev = {"p_in_bar": round(p_in, 3), "p_tail_bar": None if tail_p is None else round(tail_p, 3),
                  "flow_lpm": q, "expected_flow_lpm": round(feats["exp_q"], 1) if feats else None,
                  "flow_z": round(zq, 2), "pressure_residual_bar": round(feats["r"], 3) if measured else None,
                  "pressure_residual_z": round(z_r, 1), "anomaly_score": round(br["score"], 2),
                  "evidence_sum": round(tr.cusum, 1), "alarm_level": tr.h,
                  "leak_probability": None if p_leak is None else round(p_leak, 2), "segment": seg,
                  "devices": [f"{bid}-IN", f"{bid}-END"] + [f"{self.hh_ids[i]}-TAP" for i in self.inst_idx[b]]}
            if seg and seg["kind"] == "leak":
                where = f" Most likely near {seg['near']} (between {seg['from']} and {seg['to']})."
                if seg.get("citizen"):
                    where += f" The position uses the citizen sighting near {seg['citizen']}."
                spot = f"near {seg['near']}, between {seg['from']} and {seg['to']}"
            else:
                where = f" Largest pressure loss is between {seg['from']} and {seg['to']}." if seg else ""
                spot = f"between {seg['from']} and {seg['to']}" if seg else f"along {lane}"
            if leak_like:
                excess = max(0.0, q - feats["exp_q"])
                peak = max(len(affected), prior["affected_count"] if prior else 0)  # impact wording stays once homes were hit
                if peak:
                    sev = "high" if peak >= 5 else "medium"
                    title = f"Suspected leakage on {lane}: excess flow with low pressure downstream"
                    impact = (f"{len(affected)} households downstream are estimated to have low pressure." if affected else
                              f"Up to {peak} households downstream had low pressure at peak demand; pressure is adequate right now.")
                else:
                    sev, title = "medium", f"Suspected leakage on {lane} (early warning)"
                    impact = "Pressure at the taps is still adequate, so households are not yet affected."
                if seen:
                    impact += " A citizen report of visible leakage on this lane supports this."
                inc.raise_(key, self.id, "SUSPECTED_LEAK", sev, scope_type="branch", scope_id=bid, branch_id=bid,
                           affected_ids=affected, confidence=min(0.95, 0.45 + 0.4 * p_leak + (0.1 if seen else 0.0)), origin="sensor" if hit_low else "ml",
                           title=title,
                           summary=(f"Flow into {lane} is about {excess:.0f} L/min above the learned demand profile while " if excess >= 3 else
                                    f"Flow into {lane} is within its usual range, but ")
                                   + f"pressure loss along the lane is {z_r:.0f} sigma above its learned head-loss curve"
                                   + (". " if excess >= 3 else " and builds up along the lane the way a leak's does. ")
                                   + f"The fault classifier reads the pattern as a leak ({p_leak * 100:.0f}%). {impact}{where}",
                           cause="Suspected leakage (not confirmed): more water enters the lane than households normally draw, "
                                 "and pressure falls more than that flow explains.",
                           action=(f"Inspect the pipe {spot} for a leak or burst; isolate and repair. Leaks under low pressure "
                                   "can draw in contamination, so test water quality after the repair."),
                           evidence=ev)
            elif hit_low:
                sev = "high" if len(affected) >= 8 else "medium"
                cause = (f"Suspected obstruction or throttled valve: pressure is lost at one point along the lane without excess flow "
                         f"(fault classifier: {(1 - p_leak) * 100:.0f}% obstruction)." if obstruction_like else
                         "Cause undetermined: a leak, an obstruction or a throttled valve are all consistent with the readings so far.")
                inc.raise_(key, self.id, "LOW_PRESSURE", sev, scope_type="branch", scope_id=bid, branch_id=bid,
                           affected_ids=affected, confidence=0.75 if obstruction_like else 0.6, title=f"Low pressure at the tail of {lane}",
                           summary=f"Tail pressure on {lane} has stayed at {tail_p:.2f} bar (entry {p_in:.2f} bar) for "
                                   f"{self.count[key + ':low']} consecutive readings. {len(affected)} households are estimated "
                                   f"to have low pressure.{where}",
                           cause=cause,
                           action=f"Check valves and the pipe {spot}; confirm pressure at a tail-end tap.",
                           evidence=ev)
            else:
                inc.raise_(key, self.id, "ABNORMAL_PATTERN", "low", scope_type="branch", scope_id=bid, branch_id=bid,
                           affected_ids=[], confidence=0.6, origin="ml", title=f"Abnormal pressure pattern on {lane} (early warning)",
                           summary=f"Pressure loss along {lane} is {z_r:.0f} sigma above its learned head-loss curve "
                                   f"(evidence {tr.cusum:.0f} against an alarm level of {tr.h:.0f}). Households are still receiving adequate pressure.{where}",
                           cause=(f"Pattern matches an early-stage obstruction or a part-closed valve (fault classifier: {(1 - p_leak) * 100:.0f}% obstruction)."
                                  if obstruction_like else
                                  "Unusual head loss for the measured flow: a small leak or an early-stage obstruction is possible."),
                           action=f"Schedule an inspection of {lane} {spot if seg else ''} at the next maintenance round.".replace("  ", " "), evidence=ev)
        elif not inc.is_open(key):
            self.p_leak[b], self.loc[b] = None, None
        self._settle(key, hit_int or hit_low or hit_anom, cond_int or cond_low or cond_anom,
                     f"Pressure and flow on {lane} are back within the expected range")

    def _localise(self, b: int, wm: dict | None, leak: bool, prior: dict | None = None) -> dict | None:
        """Where on the lane the unexplained loss of pressure is.

        A leak is fitted to the residuals at every measured point, which places it between sensors; a citizen
        who reported seeing it pulls the estimate towards their house. An obstruction can only be bracketed
        by the two measured points it lies between. Positions are smoothed while the alarm stays up."""
        if wm is None:
            return self.loc[b]
        tr = self.trackers[b]
        xs, sig = [pt["x"] for pt in tr.pts], [pt["sigma"] for pt in tr.pts]
        idx = self.branch_idx[b]
        n = len(idx)
        if leak:
            fit = ML.locate_leak(xs, wm["rb"], sig, wm["n"])
            if fit is None:
                return self.loc[b]
            x, x0, x1, citizen = fit["x"], fit["x0"], fit["x1"], None
            seen = [l for l in ((prior or {}).get("evidence") or {}).get("citizen_leak_reports", []) if l in self.labels]
            on_lane = [i for i in (self.labels.index(l) for l in seen) if self.b_of[i] == b]
            if on_lane:  # two independent position estimates, weighted by how sure each is (a sighting: about 1.5 homes)
                xc, sm, sc = float(np.mean(self.x[on_lane])), max((x1 - x0) / 3.29, 0.02), 1.5 / n
                wsum = 1 / sm ** 2 + 1 / sc ** 2
                x = (x / sm ** 2 + xc / sc ** 2) / wsum
                half = 1.64 / np.sqrt(wsum)
                x0, x1, citizen = max(min(x0, x), x - half), min(max(x1, x), x + half), self.labels[on_lane[0]]
            prev = self.loc[b]
            if prev and prev["kind"] == "leak":
                x, x0, x1 = (0.6 * prev[k] + 0.4 * v for k, v in (("x", x), ("x0", x0), ("x1", x1)))
            lo, hi = int(np.floor(x0 * n + 1e-6)), int(np.ceil(x1 * n - 1e-6))
            seg = {"kind": "leak", "x": round(float(x), 3), "x0": round(float(x0), 3), "x1": round(float(x1), 3),
                   "from": self.labels[idx[lo - 1]] if lo >= 1 else "branch entry",
                   "to": self.labels[idx[hi - 1]] if hi <= n else "tail end",
                   "near": self.labels[idx[int(np.clip(round(x * n), 1, n)) - 1]],
                   "loss_bar": round(fit["drop_bar"], 2), "citizen": citizen}
        else:
            fit = ML.bracket_step(xs, wm["rb"])
            if fit is None:
                return self.loc[b]
            names = {0.0: "branch entry", **{pt["x"]: pt["label"] for pt in tr.pts}}
            seg = {"kind": "step", "x": round(fit["x"], 3), "x0": round(fit["x0"], 3), "x1": round(fit["x1"], 3),
                   "from": names[fit["x0"]], "to": names[fit["x1"]], "near": None, "loss_bar": round(fit["drop_bar"], 2), "citizen": None}
        self.loc[b] = seg
        return seg

    def _detect_offline(self):
        T = self.ctx.telemetry
        inc = self.ctx.incidents
        groups: dict[str, list] = defaultdict(list)
        for dev_id in self.device_ids:
            if T.missed[dev_id] >= C.OFFLINE_MISSED:
                meta = T.devices[dev_id]
                if meta["entity_type"] == "branch":
                    grp = meta["entity_id"]
                elif meta["entity_type"] == "household":
                    grp = self.branch_ids[int(self.b_of[self.hh_ids.index(meta["entity_id"])])]
                else:
                    grp = "scheme"
                groups[grp].append(dev_id)
        for grp in set(groups) | {k.split(":offline:")[1] for k in inc.by_key if k.startswith(f"{self.id}:offline:")}:
            key = f"{self.id}:offline:{grp}"
            devs = groups.get(grp, [])
            if not devs:
                self._settle(key, False, False, "All devices in this group are reporting again")
                continue
            self.clear_n[key] = 0
            kinds = {T.devices[d]["kind"] for d in devs}
            sev = "high" if kinds & {"level", "pump"} else "medium" if kinds & {"branch_in", "branch_end", "flow", "quality"} else "low"
            if grp == "scheme":
                where, scope_type, scope_id, branch_id, unknown = "the scheme assets", "scheme", self.id, None, []
            else:
                b = self.branch_ids.index(grp)
                where, scope_type, scope_id, branch_id = self.branch_names[b], "branch", grp, grp
                unknown = [self.hh_ids[i] for i in self.branch_idx[b] if self.status[i] == UNKNOWN]
            names = ", ".join(devs)
            inc.raise_(key, self.id, "SENSOR_OFFLINE", sev, scope_type=scope_type, scope_id=scope_id, branch_id=branch_id,
                       affected_ids=unknown, confidence=0.95,
                       title=f"{len(devs)} sensor{'s' if len(devs) > 1 else ''} offline on {where}",
                       summary=f"No telemetry from {names} for {C.OFFLINE_MISSED}+ expected reports. "
                               + (f"Service status for {len(unknown)} households cannot be estimated and is shown as unknown, not as healthy."
                                  if unknown else "Estimates that relied on these devices are shown with reduced confidence."),
                       cause="Suspected: device power, connectivity or gateway failure. This is a monitoring gap, not a confirmed supply fault.",
                       action="Check device power and signal; replace the battery or reboot the gateway. Verify supply by phone with a household meanwhile.",
                       evidence={"devices": devs, "last_seen": {d: (T.latest.get(d) or {}).get("ts") for d in devs}})

    def _detect_pump(self):
        inc = self.ctx.incidents
        key = f"{self.id}:pump"
        p = self.pump
        cond = bool(p.get("fresh") and p.get("cmd") and not p.get("on"))
        hit = self._persist(key, cond, C.PERSIST["pump"])
        if hit:
            near_dry = self.source.get("depth_m") is not None and self.source["depth_m"] > self.intake - 2.5
            predicted = inc.get_by_key(f"{self.id}:pumprisk")
            if predicted is not None and not inc.is_open(key):
                inc.add_event(predicted, "materialised", "Prediction materialised: the pump has now stopped (see the pump failure incident)")
            inc.raise_(key, self.id, "PUMP_FAULT", "critical", scope_type="scheme", scope_id=self.id,
                       affected_ids=list(self.hh_ids), confidence=0.9,
                       title=f"Pump not running when commanded at {self.name}",
                       summary=f"The controller is calling for the pump (tank {self.tank.get('level_pct') or 0:.0f}%) but motor current "
                               "and discharge are zero. The tank will not refill until this is fixed.",
                       cause=("Suspected dry-run protection: borewell level is close to the pump intake." if near_dry else
                              "Suspected: motor trip, power supply fault or starter failure."),
                       action="Check power supply, starter and overload relay; inspect the motor. Plan tanker supply if the forecast shows a shortfall.",
                       evidence={"cmd": 1, "state": 0, "current_a": p.get("current_a"), "tank_level_pct": self.tank.get("level_pct"),
                                 "devices": [f"{self.code}-PUMP"]})
        self._settle(key, hit, cond, "Pump is running again when commanded")

        rkey = f"{self.id}:pumprisk"
        risk = p.get("risk")
        if p.get("on") and risk is not None:
            rhit = self._persist(rkey, risk >= C.PUMP_RISK_ALERT, C.PERSIST["pump_risk"])
            if rhit and not inc.is_open(key):
                cur, vib, dis = np.array(list(self.pump_on_samples)[-10:]).mean(axis=0)
                life = p.get("life") or {}
                fmt = (lambda v: f"{v:.1f}") if life.get("h", 99) < 10 else (lambda v: f"{v:.0f}")
                left = (f" Estimated remaining life: about {fmt(life['h'])} run-hours ({fmt(life['lo'])} to {fmt(life['hi'])}), "
                        f"{'from its own wear trend' if life.get('basis') == 'own trend' else 'from fleet histories'}.") if life and not life.get("capped") else ""
                inc.raise_(rkey, self.id, "PUMP_RISK", "high" if risk >= 0.8 else "medium", scope_type="scheme",
                           scope_id=self.id, affected_ids=list(self.hh_ids), confidence=round(risk, 2), origin="ml",
                           title=f"Pump at {self.name} is likely to fail soon (risk {risk * 100:.0f}%)",
                           summary=f"Predictive model estimates a {risk * 100:.0f}% chance of failure within about 72 run-hours. "
                                   f"Motor current is {cur / self.i_nom * 100 - 100:+.0f}% and vibration {vib / self.v_nom * 100 - 100:+.0f}% "
                                   f"against nameplate; discharge is {dis / self.pump_rate * 100:.0f}% of rated. The pump is still working.{left}",
                           cause="Pattern consistent with bearing or impeller wear (model output, not a diagnosis).",
                           action="Schedule preventive maintenance before the next supply cycle: inspect bearings, impeller and alignment.",
                           evidence={"risk": round(risk, 3), "health_index": p.get("health"), "remaining_life": life or None, "current_ratio": round(cur / self.i_nom, 3),
                                     "vibration_ratio": round(vib / self.v_nom, 3), "discharge_ratio": round(dis / self.pump_rate, 3),
                                     "devices": [f"{self.code}-PUMP"]})
            self.clear_n[rkey] = self.clear_n[rkey] + 1 if risk < 0.4 else 0
            if self.clear_n[rkey] == C.CLEAR_SAMPLES and inc.is_open(rkey):
                inc.clear(rkey, "Pump signature is back within the healthy range")

    def _detect_quality(self):
        inc = self.ctx.incidents
        L = C.QUALITY_LIMITS
        fresh = [q for q in self.quality if q["fresh"]]
        checks = {
            "turbidity": (lambda q: q["turbidity_ntu"] > L["turbidity_ntu"]["permissible"], lambda q: q["turbidity_ntu"] < 4.0,
                          "turbidity_ntu", "Turbidity above 5 NTU", "NTU"),
            "chlorine": (lambda q: q["chlorine_mgl"] < L["chlorine_mgl"]["min"], lambda q: q["chlorine_mgl"] >= 0.25,
                         "chlorine_mgl", "Residual chlorine below 0.2 mg/L", "mg/L"),
            "ph": (lambda q: not L["ph"]["min"] <= q["ph"] <= L["ph"]["max"], lambda q: 6.6 <= q["ph"] <= 8.4,
                   "ph", "pH outside 6.5 to 8.5", ""),
        }
        for name, (bad_fn, clear_fn, metric, label, unit) in checks.items():
            key = f"{self.id}:wq:{name}"
            bad = [q for q in fresh if q[metric] is not None and bad_fn(q)]
            hit = self._persist(key, bool(bad), C.PERSIST["quality"])
            if hit:
                scheme = any(q["id"].endswith("WQ1") for q in bad)
                b = self.wq2_branch
                readings = "; ".join(f"{q['name']}: {q[metric]} {unit}".strip() for q in fresh)
                affected = list(self.hh_ids) if scheme else [self.hh_ids[i] for i in self.branch_idx[b]]
                if name == "chlorine":
                    cause = "Suspected: chlorine dosing stopped or under-dosing at the tank. Low residual means disinfection cannot be assumed."
                    action = "Check the chlorinator and dosing stock. Verification required: FTK residual-chlorine and H2S (bacteriological) test at the tank and a tail-end tap."
                elif name == "turbidity":
                    cause = "Suspected: turbid source water, a disturbed tank, or ingress through a pipe break."
                    action = "Verification required: FTK test at the tank outlet and a tail-end tap; send a lab sample if the FTK result fails. Check the source and tank; flush the line."
                else:
                    cause = "Suspected: source water chemistry change or dosing error."
                    action = "Verification required: FTK pH test and laboratory confirmation."
                inc.raise_(key, self.id, "QUALITY_VERIFY", "high", scope_type="scheme" if scheme else "branch",
                           scope_id=self.id if scheme else self.branch_ids[b], branch_id=None if scheme else self.branch_ids[b],
                           affected_ids=affected, confidence=0.8,
                           title=f"Water quality check needed at {self.name}: {label.lower()}",
                           summary=f"{label} on screening sensors ({readings}). This is a trigger to test, not a finding that the water "
                                   "is unsafe: online sensors cannot detect microbiological or chemical contamination.",
                           cause=cause, action=action,
                           evidence={"parameter": metric, "readings": {q["id"]: q[metric] for q in fresh},
                                     "reference": "IS 10500:2012", "limit": L.get(metric), "devices": [q["id"] for q in fresh]})
            pending = bool(bad) or any(q[metric] is not None and not clear_fn(q) for q in fresh)
            self._settle(key, hit, pending, f"{label.split(' ')[0]} readings are back within the reference range on all sensors")

    def _detect_source(self):
        inc = self.ctx.incidents
        key = f"{self.id}:source"
        days = self.source.get("days_to_limit")
        cond = days is not None and days < 45
        hit = self._persist(key, cond, 3)
        if hit:
            s = self.source
            inc.raise_(key, self.id, "SOURCE_STRESS", "medium", scope_type="scheme", scope_id=self.id,
                       affected_ids=list(self.hh_ids), confidence=0.6, origin="forecast",
                       title=f"Borewell level at {self.name} is falling: about {days:.0f} days of margin",
                       summary=f"Rest water level is {s.get('rest_m', s.get('depth_m')):.1f} m below ground and falling about "
                               f"{s['trend_m_per_day']:.2f} m/day over the last two weeks. At this rate the pumping level reaches the "
                               f"intake ({self.intake:.0f} m) in roughly {days:.0f} days.",
                       cause="Trend projection from daily rest levels (linear; seasonal recharge is not modelled).",
                       action="Review pumping hours, plan source strengthening / recharge works, and identify a backup source.",
                       evidence={"rest_level_m": s.get("rest_m"), "trend_m_per_day": s["trend_m_per_day"], "margin_m": s["margin_m"],
                                 "days_to_limit": days, "devices": [f"{self.code}-SRC"]})
        self._settle(key, hit, cond)

    def _detect_forecast(self, clk):
        if self.ctx.tick % 5:
            return
        inc = self.ctx.incidents
        key = f"{self.id}:forecast"
        f = self.forecast
        cond = f.get("empty_at") is not None and not inc.is_open(f"{self.id}:scheme")
        hit = self._persist(key, cond, 2)
        if hit:
            eta = datetime.fromisoformat(f["empty_at"])
            hrs = f["hours_to_empty"]
            inc.raise_(key, self.id, "SHORTFALL_PREDICTED", "high" if hrs < 6 else "medium", scope_type="scheme",
                       scope_id=self.id, affected_ids=list(self.hh_ids), confidence=0.7, origin="forecast",
                       title=f"Tank at {self.name} is forecast to run dry at {eta.strftime('%H:%M')} ({hrs:.0f} h from now)",
                       summary=f"Tank is at {self.tank.get('level_pct') or 0:.0f}% and " +
                               ("the pump is not available. " if not f["pump_available"] else "inflow will not keep up. ") +
                               f"With the learned demand profile it empties at {eta.strftime('%H:%M on %d %b')}, during a supply window.",
                       cause="Projection from tank mass balance and learned demand (assumes demand follows the usual pattern).",
                       action="Restore pumping before the forecast time, or arrange tanker supply and inform households of the delay.",
                       evidence={"empty_at": f["empty_at"], "hours_to_empty": hrs, "tank_level_pct": self.tank.get("level_pct"),
                                 "pump_available": f["pump_available"], "devices": [f"{self.code}-TANK", f"{self.code}-PUMP"]})
        if not cond:
            self.clear_n[key] += 1
            if self.clear_n[key] >= 3 and inc.is_open(key):
                inc.clear(key, "Forecast no longer shows the tank running dry")
        else:
            self.clear_n[key] = 0

    # ================================================================ output
    def water_balance(self) -> dict:
        """Today's water balance (IWA style, as far as a village scheme can measure it).

        System input is the main meter. Consumption is not metered at every home, so it is estimated from the
        metered homes: their litres per person, applied to everyone. What is left is unaccounted-for water.

        Homes fill their storage at different times, so early in a window the metered few are a poor guide to
        the rest and the gap swings widely before settling. The margin says how far it swings on a normal day
        (fitted to normal simulated days): wide while the current window's water is still arriving, 6% once
        it has."""
        bal = self.bal
        met = np.flatnonzero(self.instrumented)
        per_person = float(self.vol[met].sum() / max(1, self.members[met].sum()))
        people = int(self.members.sum())
        used = per_person * people
        supplied = bal["supplied"]
        gap = supplied - used
        clock = self.ctx.clock
        fresh = (supplied - bal["win0"]) / supplied if (clock.in_window and supplied > 0) else 0.0  # share of today's water from the window still running
        margin = 6.0 + (80.0 * float(np.exp(-clock.min_in_win / 40.0)) * fresh if clock.in_window else 0.0)
        lanes = []
        for b, idx in enumerate(self.branch_idx):
            lane_people = int(self.members[idx].sum())
            est = per_person * lane_people
            lanes.append({"idx": b, "name": self.branch_names[b], "in_l": round(bal["lane"][b]), "people": lane_people,
                          "est_l": round(est), "gap_pct": round((bal["lane"][b] - est) / bal["lane"][b] * 100, 1) if bal["lane"][b] > 200 else None})
        return {"supplied_l": round(supplied), "pumped_l": round(bal["pumped"]), "kwh": round(bal["kwh"], 2),
                "kwh_per_kl": round(bal["kwh"] / (bal["pumped"] / 1000), 3) if bal["pumped"] > 500 else None,
                "per_person_l": round(per_person, 1), "people": people, "metered_homes": int(len(met)),
                "consumed_est_l": round(used), "unaccounted_l": round(gap),
                "unaccounted_pct": round(gap / supplied * 100, 1) if supplied > 500 else None,
                "uncertainty_pct": round(margin, 1), "lane_margin_pct": round(2 * margin, 1), "settling": bool(clock.in_window and margin > 9), "lanes": lanes}

    def equity(self) -> dict:
        """Does the tail of each lane get the service the head gets?

        Two measures, both for today. Estimated for every home: the share of supply time it had usable
        pressure, by thirds of the lane. Measured at the metered homes: litres per person at the first and
        the last metered tap of each lane. (Litres at unmetered homes are not used: the estimator shares a
        lane's inflow by pressure, which would build the answer into the question.)"""
        share = np.divide(self.ok_min, self.known_min, out=np.full(self.n, np.nan), where=self.known_min > 0)

        def band(lo: float, hi: float, idx=None) -> float | None:
            m = (self.x > lo) & (self.x <= hi)
            if idx is not None:
                m &= np.isin(np.arange(self.n), idx)
            vals = share[m]
            vals = vals[~np.isnan(vals)]
            return round(float(vals.mean()) * 100, 1) if len(vals) else None

        head, mid, tail = band(0.0, 1 / 3), band(1 / 3, 2 / 3), band(2 / 3, 1.0)
        first = [int(idx[0]) for idx in self.inst_idx if len(idx) > 1]
        last = [int(idx[-1]) for idx in self.inst_idx if len(idx) > 1]
        lpcd = lambda homes: round(float((self.vol[homes] / self.members[homes]).mean()), 1) if homes else None  # noqa: E731
        return {"head_pct": head, "mid_pct": mid, "tail_pct": tail,
                "ratio": round(tail / head, 2) if head and tail is not None else None,
                "head_lpcd": lpcd(first), "tail_lpcd": lpcd(last), "metered_pairs": len(first),
                "supply_min": round(float(self.sched_min)),
                "lanes": [{"idx": b, "name": self.branch_names[b], "head_pct": band(0.0, 1 / 3, idx), "tail_pct": band(2 / 3, 1.0, idx)}
                          for b, idx in enumerate(self.branch_idx)]}

    def frame(self, clk, branches: list, reported: frozenset) -> dict:
        """Compact record of this instant for the replay timeline (arrays, not per-home dicts)."""
        return {"t": clk.now.isoformat(timespec="minutes"), "win": clk.win_idx is not None,
                "st": self.status.astype(np.uint8).copy(), "p": self.p_est.astype(np.float32).copy(),
                "c": (self.conf * 100).astype(np.uint8), "v": (self.vol / self.members).astype(np.float32),
                "q": self.qual_bad.copy(), "rep": reported, "branches": branches, "tank": dict(self.tank),
                "pump": {k: self.pump.get(k) for k in ("fresh", "on", "cmd", "current_a", "vibration_mms", "discharge_lpm", "risk", "health")},
                "main": self.ctx.telemetry.value(f"{self.code}-MAIN", "flow_lpm"), "quality": [dict(x) for x in self.quality]}

    def counts(self) -> dict:
        s = self.status
        return {"ok": int((s == OK).sum()), "low": int((s == LOW).sum()), "dry": int((s == DRY).sum()),
                "unknown": int((s == UNKNOWN).sum()), "idle": int((s == IDLE).sum())}

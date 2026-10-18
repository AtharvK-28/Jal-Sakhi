"""Synthetic village water-supply model.

One VillageSim is a small, correlated hydraulic model of a single-village piped
scheme: borewell -> pump -> elevated tank -> main -> branches -> household taps.
It produces (a) the hidden ground truth and (b) the sensor readings a real
deployment would see. Detection code is only ever given (b).

All physics is deliberately simple and every constant is a demo assumption.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from .. import config as C
from ..seed import INSTITUTIONS
from .layout import build_layout, to_geo

# Hydraulic constants (bar, L/min)
H0 = 1.20  # static head at the tank outlet with the tank empty
H1 = 0.30  # extra head from a full tank
R_MAIN = 0.08  # main head loss at nominal total flow
R_BRANCH = 0.22  # branch friction loss at nominal branch flow
Q_NOM_PER_HH = 3.0  # nominal design flow per household
LEAK_DROP = 0.012  # bar lost downstream per L/min of leak flow
BRANCH_NAMES = ["Mandir Lane", "School Road", "Bazaar Peth", "Tekdi Wasti", "Talav Ali", "Station Road"]

# Sensor noise (1 sigma)
N_P, N_Q_REL, N_Q_ABS = 0.012, 0.012, 0.35


@dataclass
class Faults:
    pump_trip: bool = False
    wear_rate: float = 0.0  # extra pump wear per run-minute (degradation scenario)
    main_closed: bool = False
    branch_closed: set = field(default_factory=set)  # branch indices
    blockage: dict = field(default_factory=dict)  # branch idx -> (x, severity 0..1)
    leak: dict = field(default_factory=dict)  # branch idx -> (x, coeff L/min at 1 bar)
    tap_block: dict = field(default_factory=dict)  # household idx -> share of pressure lost in that home's own service line
    booster: dict = field(default_factory=dict)  # household idx -> L/min an electric pump on that tap draws while it fills
    transient: dict = field(default_factory=dict)  # branch idx -> minutes remaining
    turbidity: float = 0.0  # added source turbidity (NTU)
    chlorine_fail: bool = False
    offline: set = field(default_factory=set)  # device ids
    gw_decline: float = 0.0  # metres per day of extra static-level decline
    injected: dict = field(default_factory=dict)  # fault key -> sim time injected

    def any_active(self) -> bool:
        return bool(
            self.pump_trip or self.wear_rate or self.main_closed or self.branch_closed or self.blockage
            or self.leak or self.tap_block or self.booster or self.turbidity or self.chlorine_fail or self.offline or self.gw_decline
        )


class VillageSim:
    def __init__(self, spec: dict, seed_offset: int = 0, run_seed: int | None = None):
        """seed_offset varies the village itself (household sizes, tap elevations). run_seed keeps the
        village and varies only what happens in it (who draws water when, sensor noise): other days of
        the same village, which is what calibration and evaluation need."""
        self.spec = spec
        self.id: str = spec["id"]
        self.code: str = spec["code"]
        self.name: str = spec["name"]
        rng = np.random.default_rng(spec["seed"] * 1000 + seed_offset)
        self.rng = rng
        self.noise = np.random.default_rng(spec["seed"] * 7919 + seed_offset + 1)

        sizes = list(spec["branches"])
        self.sizes = sizes
        self.nb = len(sizes)
        self.n = sum(sizes)
        nb, n = self.nb, self.n
        self.b_of = np.concatenate([np.full(s, i) for i, s in enumerate(sizes)])
        self.pos = np.concatenate([np.arange(1, s + 1) for s in sizes])
        self.x = self.pos / np.array(sizes)[self.b_of]
        self.slope = np.array(spec.get("uphill", [0.0] * nb), dtype=float)
        self.elev = self.slope[self.b_of] * self.x + rng.normal(0, 0.02, n)
        self.members = rng.choice([3, 4, 4, 5, 5, 5, 6, 7], n)
        self.k = rng.uniform(7.6, 9.4, n)

        inst = np.zeros(n, dtype=bool)
        start = 0
        for s in sizes:
            for frac in (0.2, 0.55, 0.9):
                inst[start + max(0, min(s - 1, round(frac * s) - 1))] = True
            start += s
        self.instrumented = inst

        # Node arrays = households + one endpoint sensor node per branch (x = 1, no draw).
        self._nx = np.concatenate([self.x, np.ones(nb)])
        self._nb_of = np.concatenate([self.b_of, np.arange(nb)])
        self._nelev = np.concatenate([self.elev, self.slope])
        self._prof = 1.0 - (1.0 - self._nx) ** 3

        self.q_nom = np.array(sizes, dtype=float) * Q_NOM_PER_HH
        self.q_main_nom = float(self.q_nom.sum())

        self.cap = spec["tank_kl"] * 1000.0
        self.dead = 0.03 * self.cap
        self.pump_rate = float(spec["pump_lpm"])
        self.i_nom, self.v_nom = 11.5, 2.2  # motor current (A), vibration (mm/s RMS)
        self.gw_static0 = float(spec.get("gw_static", 28.0))
        self.dd_max = 4.5
        self.pump_intake_depth = float(spec.get("pump_intake", 52.0))
        self.fail_at = 0.92  # wear level at which the pump trips

        self.hh_ids = [f"{self.code}-HH-{i + 1:03d}" for i in range(n)]
        self.branch_ids = [f"{self.code}-B{b + 1}" for b in range(nb)]
        self.branch_names = [BRANCH_NAMES[b % len(BRANCH_NAMES)] for b in range(nb)]
        self.wq2_branch = nb - 1  # tail-end quality point sits on the last branch
        if run_seed is not None:
            self.rng = np.random.default_rng([spec["seed"], seed_offset, run_seed, 1])
            self.noise = np.random.default_rng([spec["seed"], seed_offset, run_seed, 2])
        self._layout = None
        self._geo = None
        self.reset_state()
        self._build_devices()

    # ------------------------------------------------------------------ state
    def reset_state(self):
        n, nb = self.n, self.nb
        self.tank = 0.9 * self.cap
        self.pump_cmd = False
        self.pump_on = False
        self.pump_wear = float(self.spec.get("pump_wear", 0.04))
        self.pump_run_min = 0.0
        self.discharge = 0.0
        self.drawdown = 0.0
        self.gw_static = self.gw_static0
        self.gw_ok = True
        self.need = np.zeros(n)
        self.delay = np.zeros(n)
        self.bg_left = np.zeros(n)
        self.got_today = np.zeros(n)
        self.got_window = np.zeros(n)
        self.q_prev = np.zeros(nb)
        self.p = np.zeros(n)  # true pressure at each tap
        self.q = np.zeros(n)  # true flow at each tap
        self.qb = np.zeros(nb)  # true branch entry flow
        self.p_in = np.zeros(nb)
        self.p_end = np.zeros(nb)
        self.leak_q = np.zeros(nb)
        self.meter_l = 0.0  # litres through the bulk meter at the tank outlet since the start
        self.flowing = False
        self.turb = 0.55
        self.cl = 0.55
        self.faults = Faults()
        self.events: list[dict] = []  # physical events this tick (e.g. pump auto-trip)

    def _build_devices(self):
        c = self.code
        self.devices: dict[str, dict] = {}

        def add(dev_id, kind, entity_type, entity_id, name, metrics):
            self.devices[dev_id] = {
                "id": dev_id, "village_id": self.id, "kind": kind, "entity_type": entity_type,
                "entity_id": entity_id, "name": name, "metrics": metrics,
                "battery": float(self.noise.uniform(64, 100)), "rssi": float(self.noise.uniform(-92, -58)),
                "fw": "1.3.2", "power": "solar+LiFePO4" if kind != "tap" else "battery",
            }

        add(f"{c}-TANK", "level", "tank", f"{c}-TANK", "Tank level (ultrasonic)", ["level_pct", "volume_l"])
        add(f"{c}-PUMP", "pump", "pump", f"{c}-PUMP", "Pump controller", ["cmd", "state", "current_a", "vibration_mms", "discharge_lpm"])
        add(f"{c}-SRC", "gwl", "source", f"{c}-SRC", "Borewell water level", ["depth_m"])
        add(f"{c}-MAIN", "flow", "main", f"{c}-MAIN", "Main outlet flow", ["flow_lpm"])
        for b in range(self.nb):
            bid = self.branch_ids[b]
            add(f"{bid}-IN", "branch_in", "branch", bid, f"{self.branch_names[b]} entry (pressure + flow)", ["pressure_bar", "flow_lpm"])
            add(f"{bid}-END", "branch_end", "branch", bid, f"{self.branch_names[b]} tail-end pressure", ["pressure_bar"])
        add(f"{c}-WQ1", "quality", "quality", f"{c}-WQ1", "Water quality: tank outlet", ["turbidity_ntu", "chlorine_mgl", "ph", "tds_mgl"])
        add(f"{c}-WQ2", "quality", "quality", f"{c}-WQ2", f"Water quality: {self.branch_names[self.wq2_branch]} tail", ["turbidity_ntu", "chlorine_mgl", "ph", "tds_mgl"])
        for i in np.flatnonzero(self.instrumented):
            hid = self.hh_ids[i]
            add(f"{hid}-TAP", "tap", "household", hid, f"Smart tap node {hid}", ["pressure_bar", "flow_lpm", "volume_l"])

    # ------------------------------------------------------------- hydraulics
    def _grades(self, head: float, qb: np.ndarray):
        """Hydraulic grade at every node for the given branch flows."""
        f = self.faults
        p_main = head - R_MAIN * (qb.sum() / self.q_main_nom) ** 2
        p_in = np.full(self.nb, max(p_main, 0.0))
        for b in f.branch_closed:
            p_in[b] = 0.0
        hl = R_BRANCH * (qb / self.q_nom) ** 2
        g = p_in[self._nb_of] - hl[self._nb_of] * self._prof
        for b, (xb, sev) in f.blockage.items():
            m = (self._nb_of == b) & (self._nx >= xb)
            g[m] *= 1.0 - sev
        leak_q = np.zeros(self.nb)
        for b, (xl, coeff) in f.leak.items():
            if p_in[b] <= 0:
                continue
            g_at = p_in[b] - hl[b] * (1.0 - (1.0 - xl) ** 3)
            ql = coeff * math.sqrt(max(g_at, 0.0))
            leak_q[b] = ql
            m = self._nb_of == b
            g[m] -= LEAK_DROP * ql * np.minimum(self._nx[m] / xl, 1.0)
        for b, xl, qx in getattr(self, "_draws", ()):  # a pump on a tap pulls the lane down like a leak at that home
            if p_in[b] > 0:
                m = self._nb_of == b
                g[m] -= LEAK_DROP * qx * np.minimum(self._nx[m] / max(xl, 1e-3), 1.0)
        for b, left in f.transient.items():
            if left > 0:
                g[self._nb_of == b] *= 0.25
        g[p_in[self._nb_of] <= 0] = -9.0  # an unpressurised branch delivers nothing, whatever the tap elevation
        return p_in, g, leak_q

    def _at_tap(self, p: np.ndarray) -> np.ndarray:
        """Pressure at the tap itself: the pipe's pressure less whatever a blocked service line takes."""
        if not self.faults.tap_block:
            return p
        p = p.copy()
        for i, sev in self.faults.tap_block.items():
            p[i] *= 1.0 - sev
        return p

    def step(self, clk) -> list[tuple]:
        """Advance the model by clk.dt minutes and return sensor readings.

        clk has: now (datetime), dt (minutes), win_idx (int | None), min_in_win,
        new_window (bool), new_day (bool).
        """
        dt = float(clk.dt)
        n, nb = self.n, self.nb
        f = self.faults
        self.events = []
        if clk.new_day:
            self.got_today[:] = 0
        if clk.new_window:
            share = C.WINDOW_SHARE[clk.win_idx]
            self.need = self.members * C.FILL_LPCD * share * self.rng.uniform(0.96, 1.18, n)
            self.delay = self.rng.uniform(0, 55, n)
            late = self.rng.random(n) < 0.12
            self.delay[late] += self.rng.uniform(20, 60, int(late.sum()))
            self.got_window[:] = 0
            self.bg_left[:] = 0
            for i in f.booster:  # the pump fills a large drum or overhead tank, and starts with the supply
                self.need[i] *= 6
                self.delay[i] = self.rng.uniform(0, 3)

        # ---- source and pump (float-switch control with hysteresis)
        frac = self.tank / self.cap
        self.pump_cmd = frac < (0.96 if self.pump_cmd else 0.60)
        can_run = (not f.pump_trip) and self.gw_ok
        self.pump_on = self.pump_cmd and can_run
        if self.pump_on:
            self.discharge = self.pump_rate * (1.0 - 0.45 * self.pump_wear)
            self.pump_run_min += dt
            if f.wear_rate:
                self.pump_wear = min(1.0, self.pump_wear + f.wear_rate * dt)
                if self.pump_wear >= self.fail_at:
                    f.pump_trip = True
                    f.injected.setdefault("pump_trip", clk.now)
                    self.events.append({"kind": "pump_auto_trip"})
        else:
            self.discharge = 0.0
        a = 1.0 - math.exp(-dt / 25.0)
        self.drawdown += ((self.dd_max if self.pump_on else 0.0) - self.drawdown) * a
        self.gw_static += f.gw_decline * dt / 1440.0
        gw_depth = self.gw_static + self.drawdown
        self.gw_ok = gw_depth < self.pump_intake_depth - 1.0
        inflow = self.discharge * dt

        # ---- distribution
        self.flowing = clk.win_idx is not None and self.tank > self.dead + 1 and not f.main_closed
        if self.flowing:
            head = H0 + H1 * frac
            filling = (self.need > 0) & (clk.min_in_win >= self.delay)
            start_bg = (~filling) & (self.bg_left <= 0) & (self.rng.random(n) < C.BG_RATE * self.members * dt)
            self.bg_left[start_bg] = self.rng.integers(2, 5, int(start_bg.sum()))
            bg = (~filling) & (self.bg_left > 0)
            throttle = np.where(filling, 1.0, np.where(bg, 0.42, 0.0))
            pumping = [i for i in f.booster if filling[i]]
            self._draws = [(int(self.b_of[i]), float(self.x[i]), f.booster[i]) for i in pumping]
            qb = self.q_prev.copy()
            for _ in range(4):
                p_in, g, leak_q = self._grades(head, qb)
                pn = np.maximum(g - self._nelev, 0.0)
                q = throttle * self.k * np.sqrt(self._at_tap(pn[:n]))
                for i in pumping:  # a pump draws its own rate whatever the pressure, while the lane has water
                    q[i] = f.booster[i] if p_in[self.b_of[i]] > 0 else 0.0
                q_new = np.bincount(self.b_of, weights=q, minlength=nb) + leak_q
                qb = 0.5 * qb + 0.5 * q_new
            p_in, g, leak_q = self._grades(head, qb)
            pn = np.maximum(g - self._nelev, 0.0)
            q = throttle * self.k * np.sqrt(self._at_tap(pn[:n]))
            for i in pumping:
                q[i] = f.booster[i] if p_in[self.b_of[i]] > 0 else 0.0
            vol = q * dt
            vol = np.where(filling, np.minimum(vol, self.need), vol)
            out = float(vol.sum() + leak_q.sum() * dt)
            avail = self.tank - self.dead
            if out > avail > 0:
                scale = avail / out
                vol *= scale
                q *= scale
                leak_q = leak_q * scale
                out = avail
            self.need = np.where(filling, self.need - vol, self.need)
            self.bg_left = np.maximum(self.bg_left - dt, 0)
            self.got_today += vol
            self.got_window += vol
            self.p, self.q = self._at_tap(pn[:n]), q
            self.p_in, self.p_end = p_in, pn[n:]
            self.leak_q = leak_q
            self.qb = np.bincount(self.b_of, weights=q, minlength=nb) + leak_q
            self.q_prev = self.qb.copy()
            self.tank -= out
            self.meter_l += out
            for b in list(f.transient):
                f.transient[b] -= dt
                if f.transient[b] <= 0:
                    del f.transient[b]
        else:
            self.p = np.zeros(n)
            self.q = np.zeros(n)
            self.qb = np.zeros(nb)
            self.p_in = np.zeros(nb)
            self.p_end = np.zeros(nb)
            self.leak_q = np.zeros(nb)
            self.q_prev = np.zeros(nb)
        self.tank = min(self.cap, self.tank + inflow)

        # ---- water quality (first-order response to dosing / source changes)
        self.turb += ((0.55 + f.turbidity) - self.turb) * (1.0 - math.exp(-dt / 6.0))
        self.cl += ((0.03 if f.chlorine_fail else 0.55) - self.cl) * (1.0 - math.exp(-dt / 12.0))
        return self._readings(gw_depth)

    # ---------------------------------------------------------------- sensors
    def _readings(self, gw_depth: float) -> list[tuple]:
        """Return [(device_id, metrics)] for every device that is online."""
        nz = self.noise
        off = self.faults.offline
        out = []

        def emit(dev_id, metrics):
            if dev_id not in off:
                d = self.devices[dev_id]
                d["battery"] = max(5.0, d["battery"] - 0.0004)
                out.append((dev_id, metrics))

        c = self.code
        frac = self.tank / self.cap
        lvl = min(100.0, max(0.0, frac * 100 + nz.normal(0, 0.15)))
        emit(f"{c}-TANK", {"level_pct": round(lvl, 2), "volume_l": round(lvl / 100 * self.cap)})
        on = self.pump_on
        w = self.pump_wear
        emit(f"{c}-PUMP", {
            "cmd": 1.0 if self.pump_cmd else 0.0,
            "state": 1.0 if on else 0.0,
            "current_a": round(max(0.0, self.i_nom * (1 + 0.38 * w) + nz.normal(0, 0.12)) if on else 0.0, 2),
            "vibration_mms": round(max(0.0, self.v_nom * (1 + 2.6 * w) + nz.normal(0, 0.07)) if on else 0.0, 2),
            "discharge_lpm": round(max(0.0, self.discharge * (1 + nz.normal(0, 0.008))) if on else 0.0, 1),
        })
        emit(f"{c}-SRC", {"depth_m": round(gw_depth + nz.normal(0, 0.03), 2)})
        total = float(self.qb.sum())
        emit(f"{c}-MAIN", {"flow_lpm": round(max(0.0, total * (1 + nz.normal(0, N_Q_REL)) + (nz.normal(0, N_Q_ABS) if total > 0 else 0)), 1)})
        for b in range(self.nb):
            bid = self.branch_ids[b]
            live = self.flowing and b not in self.faults.branch_closed
            qv = self.qb[b]
            emit(f"{bid}-IN", {
                "pressure_bar": round(max(0.0, self.p_in[b] + (nz.normal(0, N_P) if live else 0)), 3),
                "flow_lpm": round(max(0.0, qv * (1 + nz.normal(0, N_Q_REL)) + (nz.normal(0, N_Q_ABS) if live else 0)), 1),
            })
            emit(f"{bid}-END", {"pressure_bar": round(max(0.0, self.p_end[b] + (nz.normal(0, N_P) if live else 0)), 3)})
        turb2 = self.turb * 1.08 + 0.15
        cl2 = self.cl * 0.62
        for dev, t, cl, dtds in ((f"{c}-WQ1", self.turb, self.cl, 0.0), (f"{c}-WQ2", turb2, cl2, 8.0)):
            emit(dev, {
                "turbidity_ntu": round(max(0.05, t + nz.normal(0, 0.05)), 2),
                "chlorine_mgl": round(max(0.0, cl + nz.normal(0, 0.012)), 3),
                "ph": round(7.25 + nz.normal(0, 0.03), 2),
                "tds_mgl": round(345 + dtds + nz.normal(0, 4)),
            })
        for i in np.flatnonzero(self.instrumented):
            hid = self.hh_ids[i]
            live = self.flowing
            emit(f"{hid}-TAP", {
                "pressure_bar": round(max(0.0, self.p[i] + (nz.normal(0, N_P) if live else 0)), 3),
                "flow_lpm": round(max(0.0, self.q[i] * (1 + nz.normal(0, 0.015))), 2),
                "volume_l": round(float(self.got_today[i]), 1),
            })
        return out

    # ------------------------------------------------------------ ground truth
    def true_status(self) -> np.ndarray:
        """0 ok, 1 low, 2 dry for every household (meaningful inside a window)."""
        return np.where(self.p >= C.P_OK, 0, np.where(self.p >= C.P_DRY, 1, 2))

    def institutions(self) -> list[dict]:
        """Institutional tap connections (school, anganwadi, health sub-centre) and where they sit on the network."""
        out = []
        for inst in INSTITUTIONS:
            b = inst["branch"] % self.nb
            pos = min(inst["pos"], self.sizes[b])
            out.append({"id": f"{self.code}-{inst['suffix']}", "name": inst["name"], "kind": inst["kind"], "branch_idx": b,
                        "branch_id": self.branch_ids[b], "pos": pos, "x": round(pos / self.sizes[b], 3)})
        return out

    @property
    def layout(self) -> dict:
        """Ground layout of the village (lanes, house footprints, fields); built once, on first use."""
        if self._layout is None:
            self._layout = build_layout(self.spec, self.sizes, self.branch_ids, self.branch_names, self.hh_ids,
                                        [bool(v) for v in self.instrumented], self.institutions())
        return self._layout

    def geo(self) -> dict:
        if self._geo is None:
            self._geo = to_geo(self.layout, self.spec["lat"], self.spec["lon"])
        return self._geo

    def households_meta(self) -> list[dict]:
        geo = self.geo()
        rows = []
        for i, home in enumerate(geo["homes"]):
            b = int(self.b_of[i])
            rows.append({
                "id": self.hh_ids[i], "village_id": self.id, "branch_id": self.branch_ids[b], "branch_idx": b,
                "label": f"HH-{i + 1:03d}", "position": int(self.pos[i]), "x": round(float(self.x[i]), 4),
                "members": int(self.members[i]), "instrumented": bool(self.instrumented[i]),
                "elev_bar": round(float(self.elev[i]), 4), "lane": self.branch_names[b],
                "lat": home["c"][1], "lon": home["c"][0],
            })
        return rows

    def branch_geometry(self) -> list[dict]:
        return [{"id": ln["id"], "idx": ln["idx"], "name": ln["name"], "n": ln["n"], "path": [[p[1], p[0]] for p in ln["path"]]}
                for ln in self.geo()["lanes"]]

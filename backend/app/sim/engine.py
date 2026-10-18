"""Platform: owns the clock, the simulated villages and every service, and runs the tick loop.

Tick order:  simulate -> ingest telemetry -> estimate state -> detect -> simulated
citizens -> incident housekeeping -> persist -> sync.
"""
from __future__ import annotations

import logging
import random
import shutil
import threading
import time
from collections import deque
from datetime import datetime, timedelta

import numpy as np

from .. import config as C
from .. import seed as S
from ..core import analytics, equity
from ..core.alerts import AlertDispatcher
from ..core.complaints import ComplaintService
from ..core.incidents import IncidentManager
from ..core.monitor import DRY, IDLE, LOW, OK, STATUS_NAME, UNKNOWN, VillageMonitor
from ..core.om import Upkeep
from ..core.security import Audit, hash_pw, new_salt
from ..core.sync import SyncService
from ..core.telemetry import TelemetryStore
from ..db import DB
from ..ml.models import get_models
from ..ml.nlp_corpus import PHRASES
from .clock import SimClock
from .world import VillageSim

HW_DEVICE = "HW-NODE-01"  # the bench node: a real ESP32, or the script that stands in for one
HW_HOME = "PW-HH-011"  # the metered home it stands in for until someone picks another
HW_LIVE_S = 12.0  # a board silent for this long hands the tap back to the simulator

log = logging.getLogger("jalsakhi.engine")

SCENARIOS = {
    "normal": {"label": "Normal operation", "group": "control", "icon": "check",
               "desc": "Clear every injected fault and let the system recover."},
    "branch_interruption": {"label": "Supply interruption", "group": "supply", "icon": "ban", "branch": 2,
                            "desc": "A branch valve fails closed: one lane loses supply while the rest of the village is served."},
    "low_pressure": {"label": "Low pressure", "group": "supply", "icon": "gauge", "branch": 3,
                     "desc": "Partial obstruction on a lane: tail-end households drop below usable pressure."},
    "tap_fault": {"label": "One tap stops working", "group": "supply", "icon": "ban", "home": 50,
                  "desc": "A stopcock fails at one metered home. Its tap reads no pressure while the lane is fine: one FHTC is not functional."},
    "leak": {"label": "Pipe leak", "group": "supply", "icon": "droplets", "branch": 1,
             "desc": "A burst on a lane: flow rises, pressure falls downstream, citizens start reporting."},
    "small_leak": {"label": "Small leak (ML early warning)", "group": "ai", "icon": "sparkles", "branch": 0,
                   "desc": "A minor leak below every rule threshold. The anomaly model flags it before households are affected."},
    "pump_degradation": {"label": "Pump wearing out (predictive)", "group": "ai", "icon": "activity",
                         "desc": "Bearing wear raises current and vibration. The risk model predicts failure before it happens."},
    "pump_trip": {"label": "Pump failure", "group": "infrastructure", "icon": "zap-off",
                  "desc": "The pump trips. The tank stops refilling and the forecast shows when supply will run out."},
    "quality_turbidity": {"label": "Turbidity spike", "group": "quality", "icon": "flask",
                          "desc": "Turbid water reaches the tank: quality sensors cross the reference limit and a verification workflow starts."},
    "quality_chlorine": {"label": "Chlorine dosing failure", "group": "quality", "icon": "flask",
                         "desc": "Dosing stops and residual chlorine decays below 0.2 mg/L."},
    "sensor_offline": {"label": "Sensors go silent", "group": "data", "icon": "wifi-off", "branch": 4,
                       "desc": "A gateway fails: three devices on a lane stop reporting. Affected households become 'unknown', never 'healthy'."},
    "transient": {"label": "Transient dip (must be ignored)", "group": "data", "icon": "minus", "branch": 0,
                  "desc": "A two-minute pressure dip. The persistence rule suppresses it: no incident."},
    "suction_pump": {"label": "Suction pump on a tap", "group": "supply", "icon": "gauge", "branch": 3,
                     "desc": "A household fits an electric pump on its tap at the start of supply. It fills a large drum fast and the homes after it on the lane lose pressure."},
    "citizen_cluster": {"label": "Clustered complaints", "group": "community", "icon": "users", "branch": 2,
                        "desc": "Four households on one lane report dirty water where no quality sensor exists."},
}


class Platform:
    def __init__(self, db_path=None):
        self.lock = threading.RLock()
        self.db = DB(db_path or C.DB_PATH)
        self.models = get_models()
        self.running = True
        self.speed = 1
        self.version = 0
        self.started_wall = time.time()
        self.hw_home: str | None = HW_HOME
        self.alerts = AlertDispatcher(self)  # outlives resets: a linked phone stays linked
        self.reset()

    # ------------------------------------------------------------------ reset
    def reset(self, ambient: bool = True):
        with self.lock:
            self.db.wipe()
            self.alerts.new_epoch()
            self.__dict__.pop("_memo", None)
            if C.UPLOAD_DIR.exists():
                shutil.rmtree(C.UPLOAD_DIR, ignore_errors=True)
            C.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
            self.clock = SimClock(C.SIM_START)
            self.tick = 0
            self.quiet = False
            self._feed: deque = deque(maxlen=120)
            self._feed_seq = 0
            self.sims = {v["id"]: VillageSim(v) for v in S.VILLAGES}
            self.households: dict[str, dict] = {}
            self.institutions: dict[str, list] = {}
            self.history: dict[str, list] = {}
            devices: dict[str, dict] = {}
            with self.db.tx():
                self._seed_static(devices)
            self.audit = Audit(self.db)
            self.telemetry = TelemetryStore(self.db, devices)
            self.sync = SyncService(self)
            self.incidents = IncidentManager(self)
            self.complaints = ComplaintService(self)
            self.monitors = {vid: VillageMonitor(self, sim) for vid, sim in self.sims.items()}
            self.om = Upkeep(self)
            self.sim_device_ids = [d for sim in self.sims.values() for d in sim.devices]
            self.cit_rng = random.Random(2026)
            self._cit = {vid: {"bad": np.zeros(sim.n), "reported": set(), "count": 0, "leak": set(), "turb": 0}
                         for vid, sim in self.sims.items()}
            self.scenario_log: list[dict] = []
            self.metrics = {"detections": []}
            self.hw = {"rx": 0.0, "count": 0, "metrics": {}, "quality": "good", "volume": 0.0, "on": False}
            self.frames = {vid: deque(maxlen=720) for vid in self.sims}  # replay timeline: about a day and a half of ticks
            self._reported = {vid: frozenset() for vid in self.sims}
            if ambient:
                for v in S.VILLAGES:
                    amb, f = v.get("ambient") or {}, self.sims[v["id"]].faults
                    f.blockage.update(amb.get("blockage", {}))
                    f.offline.update(amb.get("offline", []))
                    f.gw_decline = amb.get("gw_decline", 0.0)
            self.audit.log(self.now, "system", "system", "demo.reset", "platform", "jalsakhi", None, None,
                           "Seeded 6 simulated villages")
            self.feed("system", "info", "Demo reset: 6 simulated villages seeded. All telemetry is synthetic.")
            self.step()  # prime: first readings arrive as the morning supply window opens
            self.version += 1

    def _seed_static(self, devices: dict):
        db = self.db
        for unit in [S.STATE] + S.DISTRICTS + S.BLOCKS:
            db.insert("admin_units", unit)
        hh_rows, dev_rows, asset_rows, map_rows, hist_rows = [], [], [], [], []
        for v in S.VILLAGES:
            sim = self.sims[v["id"]]
            path = S.admin_path(v)
            ext = S.external_ids(v)
            db.insert("admin_units", {"id": path["gp_id"], "level": "gp", "name": path["gp"], "parent_id": v["block_id"],
                                      "lat": v["lat"], "lon": v["lon"]})
            scheme = {"scheme_id": f"SCH-{v['code']}", "name": f"{v['name']} single-village piped water scheme",
                      "source": "Borewell + submersible pump", "tank_kl": v["tank_kl"], "pump_lpm": v["pump_lpm"],
                      "supply_windows": [[f"{s // 60:02d}:{s % 60:02d}", f"{e // 60:02d}:{e % 60:02d}", lbl] for s, e, lbl in C.SUPPLY_WINDOWS],
                      "timezone": "Asia/Kolkata", "branches": sim.branch_geometry()}
            db.insert("villages", {"id": v["id"], "code": v["code"], "name": v["name"], "gp_id": path["gp_id"],
                                   "block_id": path["block_id"], "district_id": path["district_id"], "state_id": path["state_id"],
                                   "lat": v["lat"], "lon": v["lon"], "households": sim.n, "branches": sim.nb, "lang": v["lang"],
                                   "scheme": scheme, "external_ids": ext, "demo": 1})
            for field, value in ext.items():
                system = "LGD" if field.startswith("lgd") else "IMIS" if field.startswith("imis") else \
                    "Sujal Gaon" if field.startswith("sujal_gaon") else "Sujalam Bharat"
                map_rows.append((("scheme" if "scheme" in field or "sujal" in field else "village"), v["id"], system, field, value, "placeholder"))
            for h in sim.households_meta():
                h["fhtc_ext_id"] = f"DEMO-FHTC-{v['code']}-{h['position'] + h['branch_idx'] * 100:04d}"
                self.households[h["id"]] = h
                hh_rows.append((h["id"], h["village_id"], h["branch_id"], h["branch_idx"], h["label"], h["position"], h["x"],
                                h["members"], int(h["instrumented"]), h["lane"], h["lat"], h["lon"], h["fhtc_ext_id"], 1))
            for d in sim.devices.values():
                devices[d["id"]] = d
                dev_rows.append((d["id"], d["village_id"], d["kind"], d["entity_type"], d["entity_id"], d["name"],
                                 S.dumps(d["metrics"]), d["fw"], d["power"], "simulation"))
            asset_rows += [(f"{v['code']}-TANK", v["id"], "tank", "Elevated service reservoir", None, v["lat"], v["lon"], 1, S.dumps({"capacity_kl": v["tank_kl"]})),
                           (f"{v['code']}-PUMP", v["id"], "pump", "Submersible pump", f"{v['code']}-SRC", v["lat"], v["lon"], 1, S.dumps({"rated_lpm": v["pump_lpm"]})),
                           (f"{v['code']}-SRC", v["id"], "source", "Borewell", None, v["lat"], v["lon"], 1, S.dumps({}))]
            for b, geo in enumerate(scheme["branches"]):
                asset_rows.append((geo["id"], v["id"], "branch", geo["name"], f"{v['code']}-TANK", geo["path"][1][0], geo["path"][1][1], 1,
                                   S.dumps({"households": geo["n"]})))
            sites = sim.institutions()
            for site in sites:
                asset_rows.append((site["id"], v["id"], "institution", site["name"], site["branch_id"], v["lat"], v["lon"], 1, S.dumps(site)))
            self.institutions[v["id"]] = sites
            hist = S.seed_history(v)
            self.history[v["id"]] = hist
            db.executemany("INSERT INTO hh_daily VALUES (?,?,?,?,?,?,?,?,?,?)", equity.seed_rows(v, sim, hist))
            for r in hist:
                hist_rows.append(tuple(r[k] for k in ("village_id", "day", "functional_pct", "regularity_pct", "quantity_pct",
                                                      "quality_pct", "avg_lpcd", "supply_hours", "incidents", "complaints",
                                                      "mttr_h", "nrw_pct", "energy_kwh", "gw_depth_m", "source")))
            for n, p in enumerate(S.seed_past_incidents(v)):
                db.insert("incidents", {"id": f"INC-H{v['code']}{n:02d}", "seq": 0, "village_id": v["id"], "type": p["type"],
                                        "category": p["category"], "severity": p["severity"], "status": "closed", "origin": "history",
                                        "title": f"(history) {p['type'].replace('_', ' ').title()}", "branch_id": p["branch_id"],
                                        "scope_type": "branch" if p["branch_id"] else "scheme", "scope_id": p["branch_id"] or v["id"],
                                        "report_count": p["reports"], "first_seen": p["first_seen"], "last_seen": p["closed_at"],
                                        "closed_at": p["closed_at"], "resolved_at": p["closed_at"], "is_seed": 1,
                                        "evidence": {"hours": p["hours"]}, "affected_ids": [], "priority_breakdown": {}})
        devices[HW_DEVICE] = {"id": HW_DEVICE, "village_id": S.FOCUS_VILLAGE, "kind": "bench", "entity_type": "bench",
                              "entity_id": HW_DEVICE, "name": "Hardware bench node (ESP32 reference build)",
                                 "metrics": ["pressure_bar", "flow_lpm", "turbidity_ntu", "tds_mgl", "ph"], "battery": 100.0,
                                 "rssi": -60.0, "fw": "1.3.2", "power": "USB / solar"}
        dev_rows.append((HW_DEVICE, S.FOCUS_VILLAGE, "bench", "bench", HW_DEVICE, devices[HW_DEVICE]["name"],
                         S.dumps(devices[HW_DEVICE]["metrics"]), "1.3.2", "USB / solar", "hardware"))
        db.executemany("INSERT INTO households VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", hh_rows)
        db.executemany("INSERT INTO devices VALUES (?,?,?,?,?,?,?,?,?,?)", dev_rows)
        db.executemany("INSERT INTO assets VALUES (?,?,?,?,?,?,?,?,?)", asset_rows)
        db.executemany("INSERT INTO id_mappings (internal_type, internal_id, system, field, external_id, status) VALUES (?,?,?,?,?,?)", map_rows)
        db.executemany("INSERT INTO daily_history VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", hist_rows)
        for u in S.USERS:
            salt = new_salt()
            db.insert("users", {**u, "salt": salt, "pw_hash": hash_pw(C.DEMO_PASSWORD, salt)})

    # ------------------------------------------------------------- utilities
    @property
    def now(self) -> datetime:
        return self.clock.now

    def feed(self, kind: str, level: str, text: str, village_id: str | None = None, ref: str | None = None):
        if self.quiet and kind in ("transient",):
            return
        self._feed_seq += 1
        self._feed.appendleft({"id": self._feed_seq, "ts": self.now.strftime("%H:%M"), "iso": self.now.isoformat(timespec="seconds"),
                               "kind": kind, "level": level, "text": text, "village_id": village_id, "ref": ref})

    def feed_list(self, village_ids: set[str] | None = None, limit: int = 40) -> list[dict]:
        out = [f for f in self._feed if village_ids is None or f["village_id"] is None or f["village_id"] in village_ids]
        return out[:limit]

    def notify(self, village_id: str, kind: str, params: dict, *, branch_id=None, household_id=None, incident_id=None,
               channel: str = "app", phone: bool = True):
        """A message for households in the citizen app; `phone` also sends it to those who linked a phone."""
        nid = self.db.insert("notifications", {"village_id": village_id, "branch_id": branch_id, "household_id": household_id,
                                               "kind": kind, "params": params, "ts": self.now.isoformat(timespec="seconds"),
                                               "channel": channel, "incident_id": incident_id})
        if phone:
            self.alerts.notified(nid, village_id, kind, params, branch_id=branch_id, household_id=household_id,
                                 incident_id=incident_id)

    def notify_incident(self, inc: dict, kind: str):
        """Tell affected households, in plain terms, when something that touches their water is detected."""
        if inc["category"] not in ("supply", "pressure", "leak", "quality", "infrastructure") or inc["severity"] == "low":
            return
        self.notify(inc["village_id"], f"{kind}_{inc['category']}", {"incident": inc["id"], "affected": inc["affected_count"]},
                    branch_id=inc["branch_id"] if inc["scope_type"] == "branch" else None,
                    household_id=inc["scope_id"] if inc["scope_type"] == "household" else None, incident_id=inc["id"],
                    channel="app+sms")

    def first_flush(self, inc: dict):
        """Water is back after a break or a pressure loss: tell the households it reaches to run the tap before drinking."""
        if not self.clock.in_window:
            return
        lane = inc["branch_id"] if inc["scope_type"] in ("branch", "household") else None
        self.notify(inc["village_id"], "first_flush", {"incident": inc["id"]}, branch_id=lane, incident_id=inc["id"], channel="app+sms")
        self.incidents.add_event(inc, "advisory", "First-flush advice sent to the households on this supply: run the tap "
                                 "for 2 minutes before filling drinking water.")

    def on_incident_status(self, inc: dict, prev: str, to: str):
        self.complaints.on_incident_status(inc, to)
        if to in ("in_progress", "resolved_pending_verification", "closed") and inc["category"] != "sensor":
            self.notify(inc["village_id"], f"status_{to}", {"incident": inc["id"]},
                        branch_id=inc["branch_id"] if inc["scope_type"] != "scheme" else None, incident_id=inc["id"])
        self.sync.enqueue("incident", inc["id"], inc["village_id"], "update", self.incidents.public(inc))

    def sensitive_sites(self, inc: dict) -> list[dict]:
        sites = self.institutions.get(inc["village_id"], [])
        if inc["scope_type"] == "scheme":
            return sites
        return [s for s in sites if s["branch_id"] == inc.get("branch_id")]

    def detection_delay(self, village_id: str, type_: str, branch_id: str | None) -> float | None:
        """Demo metric: sim-minutes between fault injection and incident creation."""
        sim = self.sims[village_id]
        inj = sim.faults.injected
        b = sim.branch_ids.index(branch_id) if branch_id in sim.branch_ids else None
        keys = {"SUPPLY_INTERRUPTION": [f"closed:{b}", "main_closed", "pump_trip"],
                "LOW_PRESSURE": [f"blockage:{b}", f"leak:{b}"], "SUSPECTED_LEAK": [f"leak:{b}", f"blockage:{b}"],
                "ABNORMAL_PATTERN": [f"leak:{b}", f"blockage:{b}"], "PUMP_FAULT": ["pump_trip"], "PUMP_RISK": ["wear"],
                "QUALITY_VERIFY": ["turbidity", "chlorine"], "SENSOR_OFFLINE": [f"offline:{b}", "offline"],
                "SHORTFALL_PREDICTED": ["pump_trip"], "SUSPECTED_BOOSTER": [f"booster:{b}"]}.get(type_, [])
        for k in keys:
            if k in inj:
                delay = round((self.now - inj[k]).total_seconds() / 60, 1)
                self.metrics["detections"].append({"village_id": village_id, "type": type_, "delay_min": delay,
                                                   "at": self.now.strftime("%H:%M")})
                return delay
        return None

    def on_repair(self, inc: dict):
        """DEMO hook: recording a repair also clears the matching simulated fault, standing in for the field fix."""
        sim = self.sims[inc["village_id"]]
        f = sim.faults
        b = sim.branch_ids.index(inc["branch_id"]) if inc.get("branch_id") in sim.branch_ids else None
        t = inc["type"]
        if t in ("SUPPLY_INTERRUPTION", "LOW_PRESSURE", "SUSPECTED_LEAK", "ABNORMAL_PATTERN"):
            if b is None:
                f.main_closed = False
            else:
                f.leak.pop(b, None)
                f.blockage.pop(b, None)
                f.branch_closed.discard(b)
        elif t == "TAP_FAULT":
            f.tap_block.pop(sim.hh_ids.index(inc["scope_id"]), None)
        elif t == "SUSPECTED_BOOSTER":
            f.booster.pop(sim.hh_ids.index(inc["scope_id"]), None)
        elif t in ("PUMP_FAULT", "PUMP_RISK"):
            f.pump_trip, f.wear_rate, sim.pump_wear = False, 0.0, 0.05
            mon = self.monitors[sim.id]
            mon.pump_on_samples.clear()
            mon.wear_hist.clear()
            mon.pump.pop("life", None)
            mon.pump["risk"] = None
        elif t == "QUALITY_VERIFY":
            f.turbidity, f.chlorine_fail = 0.0, False
        elif t == "SENSOR_OFFLINE":
            for dev in (inc.get("evidence") or {}).get("devices", []):
                f.offline.discard(dev)
        elif t == "COMMUNITY_CLUSTER":
            self._cit[sim.id]["cluster_fixed"] = True
        for k in list(f.injected):
            if b is None or k.endswith(f":{b}") or ":" not in k:
                f.injected.pop(k, None)
        self.feed("demo", "muted", f"DEMO: simulated fault behind {inc['id']} cleared to represent the field repair", sim.id, inc["id"])

    # ------------------------------------------------------------------- tick
    def step(self):
        with self.lock, self.db.tx():  # one SQLite transaction per tick
            clk = self.clock.advance(idle_dt=30 if self.quiet else None)
            self.tick += 1
            T = self.telemetry
            hw_tap = self._hw_tick()
            for sim in self.sims.values():
                for dev_id, metrics in sim.step(clk):
                    if dev_id == hw_tap:  # a real board is standing in for this tap: its reading, on the sim's clock
                        T.accept(dev_id, clk.now, self._hw_reading(clk), event_id=f"{dev_id}:{self.tick}", tick=self.tick,
                                 source="hardware", quality=self.hw["quality"])
                    else:
                        T.accept(dev_id, clk.now, metrics, event_id=f"{dev_id}:{self.tick}", tick=self.tick)
                for ev in sim.events:
                    if ev["kind"] == "pump_auto_trip":
                        self.feed("demo", "muted", f"DEMO: worn pump at {sim.name} has now failed", sim.id)
            T.end_tick(self.sim_device_ids)
            mons = list(self.monitors.values())
            for mon in mons:
                mon.update(clk)
            rows = [r for mon in mons for r in mon._rows]
            if rows:
                scores = self.models.anomaly(rows)
                at = 0
                for mon in mons:
                    mon.apply_scores(scores[at:at + len(mon._rows)])
                    at += len(mon._rows)
            for mon in mons:
                mon.detect(clk)
            self._sim_citizens(clk)
            self._validate_estimator(clk)
            if clk.closed_idx is not None:
                self._window_closed(clk)
            self.incidents.housekeeping()
            self._record(clk)
            T.flush(persist=not self.quiet)
            if not self.quiet:
                self.sync.process()
            self.version += 1

    def fast_forward(self, until=None, max_ticks: int = 400) -> int:
        """Run ticks back-to-back (no sleeping) until `until(platform)` is true."""
        with self.lock:
            self.quiet = True
            n = 0
            try:
                while n < max_ticks and not (until and until(self)):
                    self.step()
                    n += 1
            finally:
                self.quiet = False
            return n

    def skip_to_window(self, minute: int = 0):
        """Jump to `minute` minutes into the next (or current) supply window."""
        if self.clock.in_window and self.clock.min_in_win >= minute and \
                C.SUPPLY_WINDOWS[self.clock.win_idx][1] - C.SUPPLY_WINDOWS[self.clock.win_idx][0] - self.clock.min_in_win > 40:
            return 0
        if self.clock.in_window and self.clock.min_in_win < minute:
            return self.fast_forward(lambda p: p.clock.min_in_win >= minute)
        n = self.fast_forward(lambda p: not p.clock.in_window)
        return n + self.fast_forward(lambda p: p.clock.in_window and p.clock.min_in_win >= minute)

    # ----------------------------------------------------- simulated citizens
    def _sim_citizens(self, clk):
        if clk.win_idx is None:
            return
        rng = self.cit_rng
        for vid, sim in self.sims.items():
            st = self._cit[vid]
            if clk.new_window:
                st.update(bad=np.zeros(sim.n), reported=set(), count=0, leak=set(), turb=0)
            truth = sim.true_status()
            st["bad"] = np.where(truth > 0, st["bad"] + clk.dt, 0)
            lang = sim.spec["lang"]
            if st["count"] < 6:
                for i in np.flatnonzero(st["bad"] >= 6):
                    if i in st["reported"] or rng.random() > 0.022 * clk.dt:
                        continue
                    cat = "no_water" if truth[i] == 2 else "low_pressure"
                    self._sim_report(sim, int(i), cat, lang)
                    st["reported"].add(i)
                    st["count"] += 1
                    if st["count"] >= 6:
                        break
            for b, (xl, coeff) in sim.faults.leak.items():
                started = sim.faults.injected.get(f"leak:{b}")
                if coeff >= 20 and b not in st["leak"] and started and (clk.now - started).total_seconds() >= 480 and rng.random() < 0.15:
                    idx = np.flatnonzero(sim.b_of == b)
                    near = int(idx[np.argmin(np.abs(sim.x[idx] - xl))])
                    self._sim_report(sim, near, "leakage", lang)
                    st["leak"].add(b)
            if sim.turb > 4.0 and st["turb"] < 4 and rng.random() < 0.06 * clk.dt:
                self._sim_report(sim, rng.randrange(sim.n), "dirty_water", lang)
                st["turb"] += 1
        # households that reported answer "is it fixed?" once a repair is recorded
        for inc in list(self.incidents.items.values()):
            if inc["status"] != "resolved_pending_verification" or inc["report_count"] == 0:
                continue
            rows = self.db.query("SELECT id, household_id FROM complaints WHERE incident_id=? AND citizen_confirmed IS NULL"
                                 " AND source='simulated-citizen'", (inc["id"],))
            sim = self.sims[inc["village_id"]]
            for r in rows:
                if rng.random() < 0.18:
                    i = sim.hh_ids.index(r["household_id"])
                    if inc["category"] in ("quality",) or "quality" in (inc["cond_key"] or ""):
                        fixed = sim.turb < 2.0 and sim.cl > 0.3 and self._cit[sim.id].get("cluster_fixed", True)
                    else:
                        fixed = bool(sim.p[i] >= C.P_OK)
                    self.complaints.confirm(r["id"], fixed, 5 if fixed else 2, actor="simulated-citizen")

    def _sim_report(self, sim: VillageSim, i: int, category: str, lang: str):
        use = lang if self.cit_rng.random() < 0.8 else "en"
        text = self.cit_rng.choice(PHRASES[use][category])
        try:
            self.complaints.create({"household_id": sim.hh_ids[i], "category": category, "description": text,
                                    "language": use, "channel": self.cit_rng.choice(["app", "app", "sms", "ivr"]),
                                    "source": "simulated-citizen"})
        except Exception:  # a simulated report must never break the tick
            log.exception("simulated complaint failed")

    def _validate_estimator(self, clk):
        """DEMO-only: compare inferred household status with simulator truth for un-instrumented homes."""
        if clk.win_idx is None or clk.min_in_win < C.WINDOW_GRACE_MIN:
            return
        for vid, sim in self.sims.items():
            mon = self.monitors[vid]
            mask = (~sim.instrumented) & (mon.status != UNKNOWN)
            mon.truth_agree[0] += int((mon.status[mask] == sim.true_status()[mask]).sum())
            mon.truth_agree[1] += int(mask.sum())

    def _window_closed(self, clk):
        w = clk.closed_idx
        rng = self.cit_rng
        day = clk.now.date().isoformat()
        last = w == len(C.SUPPLY_WINDOWS) - 1
        for vid, sim in self.sims.items():
            mon = self.monitors[vid]
            rows = []
            for i in rng.sample(range(sim.n), max(4, sim.n // 8)):  # daily "did water come today?" pulse
                got = bool(sim.got_window[i] >= 20.0)
                if rng.random() < 0.04:
                    got = not got
                inferred = None if not mon.known[w][i] else int(mon.served[w][i])
                rows.append((vid, sim.hh_ids[i], day, w, int(got), inferred, "simulated-citizen", clk.now.isoformat(timespec="seconds")))
            self.db.executemany("INSERT INTO pulse (village_id, household_id, day, window_idx, got_water, inferred, source, ts)"
                                " VALUES (?,?,?,?,?,?,?,?)", rows)
            cmp = [r for r in rows if r[5] is not None]
            mon.pulse = {"responses": len(rows), "got_water": sum(r[4] for r in rows),
                         "agreement_pct": round(100 * sum(r[4] == r[5] for r in cmp) / len(cmp), 1) if cmp else None,
                         "window": C.SUPPLY_WINDOWS[w][2]}
            k = analytics.village_kpis(self, vid)
            record = {"day": day, "window": C.SUPPLY_WINDOWS[w][2], "ts": clk.now.isoformat(timespec="seconds"),
                      "fhtc_total": sim.n, "households_served": int(mon.served[w].sum()),
                      "households_adequate_quantity": int(mon.qty_ok[w].sum()), "households_unknown": int((~mon.known[w]).sum()),
                      "avg_lpcd_so_far": k["lpcd_avg"], "supply_minutes": round(mon.supply_min),
                      "quality_status": k["quality_status"], "functional_pct": (k["functional"] or {}).get("pct"),
                      "basis": "sensor telemetry + state estimation (simulated)"}
            self.sync.enqueue("service_delivery", f"{vid}:{day}:{w}", vid, "upsert", record)
            if last:
                flags = mon.day_flags()
                row = {"village_id": vid, "day": day, "functional_pct": round(float(flags["functional"].mean()) * 100, 1),
                       "regularity_pct": round(float(flags["regular"].mean()) * 100, 1),
                       "quantity_pct": round(float(flags["quantity"].mean()) * 100, 1),
                       "quality_pct": round(float(flags["quality"].mean()) * 100, 1), "avg_lpcd": k["lpcd_avg"],
                       "supply_hours": round(mon.supply_min / 60, 2),
                       "incidents": self.db.scalar("SELECT COUNT(*) FROM incidents WHERE village_id=? AND is_seed=0 AND first_seen LIKE ?", (vid, day + "%")),
                       "complaints": self.db.scalar("SELECT COUNT(*) FROM complaints WHERE village_id=? AND created_at LIKE ?", (vid, day + "%")),
                       "mttr_h": None, "nrw_pct": max(0.0, mon.water_balance()["unaccounted_pct"] or 0.0),
                       "energy_kwh": round(mon.bal["kwh"], 1),
                       "gw_depth_m": mon.source.get("rest_m") or mon.source.get("depth_m"), "source": "simulation-live"}
                equity.record_day(self, vid, day)
                self.db.execute("DELETE FROM daily_history WHERE village_id=? AND day=?", (vid, day))
                self.db.insert("daily_history", row)
                self.history[vid] = [r for r in self.history[vid] if r["day"] != day] + [row]
        self.om.window_closed(clk, {vid: analytics.village_kpis(self, vid)["score"] for vid in self.sims})

    # -------------------------------------------------------------- scenarios
    def scenario(self, name: str, village_id: str | None = None, branch: int | None = None, actor: str = "demo") -> dict:
        if name not in SCENARIOS:
            raise KeyError(name)
        with self.lock:
            vid = village_id or S.FOCUS_VILLAGE
            sim = self.sims[vid]
            f = sim.faults
            spec = SCENARIOS[name]
            b = (branch if branch is not None else spec.get("branch", 0)) % sim.nb
            lane = sim.branch_names[b]
            skipped = 0
            if name not in ("normal", "pump_trip"):
                skipped = self.skip_to_window(14)
            if name == "pump_degradation":
                skipped += self.fast_forward(lambda p: p.sims[vid].pump_on or not p.clock.in_window, 200)
                if not sim.pump_on:
                    skipped += self.skip_to_window(14)
                    skipped += self.fast_forward(lambda p: p.sims[vid].pump_on or not p.clock.in_window, 200)
            now = self.now
            detail = spec["desc"]
            if name == "normal":
                keep_offline = set((sim.spec.get("ambient") or {}).get("offline", []))
                sim.faults = type(f)(offline=keep_offline, gw_decline=f.gw_decline,
                                     blockage=dict((sim.spec.get("ambient") or {}).get("blockage", {})))
                sim.pump_wear = float(sim.spec.get("pump_wear", 0.04))
                self.monitors[vid].pump_on_samples.clear()
                self.monitors[vid].wear_hist.clear()
                self.monitors[vid].pump.pop("life", None)
                detail = "All injected faults cleared."
            elif name == "branch_interruption":
                f.branch_closed.add(b)
                f.injected[f"closed:{b}"] = now
                detail = f"Branch valve closed on {lane}."
            elif name == "low_pressure":
                f.blockage[b] = (0.4, 0.65)
                f.injected[f"blockage:{b}"] = now
                detail = f"Partial obstruction at 40% along {lane}."
            elif name == "tap_fault":
                metered = np.flatnonzero(sim.instrumented)
                i = int(metered[np.argmin(np.abs(metered - spec["home"] % sim.n))])
                if self.hw["on"] and sim.hh_ids[i] == self.hw_home:  # that tap is a real board right now: take the next one
                    i = int(metered[(list(metered).index(i) + 1) % len(metered)])
                f.tap_block[i] = 0.97
                f.injected[f"tap:{i}"] = now
                detail = f"Service line blocked at HH-{i + 1:03d} on {sim.branch_names[int(sim.b_of[i])]}."
            elif name == "leak":
                f.leak[b] = (0.45, 30.0)
                f.injected[f"leak:{b}"] = now
                detail = f"Leak of roughly 30 L/min at 45% along {lane}."
            elif name == "small_leak":
                f.leak[b] = (0.5, 11.0)
                f.injected[f"leak:{b}"] = now
                detail = f"Leak of roughly 11 L/min on {lane}: below every rule threshold."
            elif name == "pump_degradation":
                sim.pump_wear = max(sim.pump_wear, 0.77)
                f.wear_rate = 0.0012
                f.injected["wear"] = now
                detail = "Pump wear set to an advanced stage and still progressing; it will fail if not serviced."
            elif name == "pump_trip":
                f.pump_trip = True
                f.injected["pump_trip"] = now
                sim.tank = min(sim.tank, 0.42 * sim.cap)
                detail = "Pump tripped with the tank at 42% or lower."
            elif name == "quality_turbidity":
                f.turbidity = 9.0
                f.injected["turbidity"] = now
            elif name == "quality_chlorine":
                f.chlorine_fail = True
                f.injected["chlorine"] = now
            elif name == "sensor_offline":
                idx = np.flatnonzero((sim.b_of == b) & sim.instrumented)
                devs = [f"{sim.branch_ids[b]}-END"] + [f"{sim.hh_ids[int(i)]}-TAP" for i in idx[-2:]]
                f.offline.update(devs)
                f.injected[f"offline:{b}"] = now
                detail = f"{', '.join(devs)} stopped reporting."
            elif name == "transient":
                f.transient[b] = 2
                detail = f"Two-minute pressure dip on {lane}."
            elif name == "suction_pump":
                idx = np.flatnonzero((sim.b_of == b) & sim.instrumented)
                i = int(idx[np.argmin(np.abs(sim.x[idx] - 0.35))])
                f.booster[i] = 28.0
                f.injected[f"booster:{b}"] = now
                sim.need[i] = sim.members[i] * C.FILL_LPCD * C.WINDOW_SHARE[self.clock.win_idx or 0] * 6
                sim.delay[i] = 0.0
                detail = f"An electric pump on the tap at HH-{i + 1:03d} ({lane}) draws about 28 L/min while it fills a large drum."
            elif name == "citizen_cluster":
                idx = [int(i) for i in np.flatnonzero(sim.b_of == b)]
                self._cit[vid]["cluster_fixed"] = False
                for i in self.cit_rng.sample(idx, 4):
                    self._sim_report(sim, i, self.cit_rng.choice(["dirty_water", "dirty_water", "smell_taste"]), sim.spec["lang"])
                detail = f"Four households on {lane} reported a water quality concern."
            entry = {"name": name, "label": spec["label"], "village_id": vid, "at": now.strftime("%H:%M"),
                     "detail": detail, "skipped_ticks": skipped}
            self.scenario_log.append(entry)
            self.audit.log(now, actor, "demo", "demo.scenario", "village", vid, None, name, detail)
            self.feed("demo", "demo", f"DEMO scenario injected at {sim.name}: {spec['label']}. {detail}", vid)
            self.version += 1
            return entry

    def active_faults(self, vid: str) -> list[str]:
        sim, f = self.sims[vid], self.sims[vid].faults
        out = [f"valve closed on {sim.branch_names[b]}" for b in f.branch_closed]
        out += [f"obstruction on {sim.branch_names[b]}" for b in f.blockage]
        out += [f"leak on {sim.branch_names[b]}" for b in f.leak]
        out += [f"tap blocked at HH-{i + 1:03d}" for i in f.tap_block]
        out += [f"suction pump at HH-{i + 1:03d}" for i in f.booster]
        out += ["pump tripped"] if f.pump_trip else []
        out += ["pump wearing"] if f.wear_rate else []
        out += ["turbidity spike"] if f.turbidity else []
        out += ["chlorine dosing off"] if f.chlorine_fail else []
        out += [f"{len(f.offline)} device(s) offline"] if f.offline else []
        return out

    # ---------------------------------------------------------------- outputs
    def clock_state(self) -> dict:
        d = self.clock.describe()
        d.update(running=self.running, speed=self.speed, tick=self.tick)
        return d

    def twin(self, vid: str) -> dict:
        """Live state of one village as the platform believes it to be (sensor-derived)."""
        sim, mon = self.sims[vid], self.monitors[vid]
        reported = {r["household_id"] for r in self.db.query(
            "SELECT household_id FROM complaints WHERE village_id=? AND status!='closed'", (vid,))}
        qual = mon._quality_affected()
        branches = self._branch_view(vid)
        hh = []
        for i in range(sim.n):
            b = int(sim.b_of[i])
            f = mon.branch[b].get("feats")
            # what this tap would read if the lane were healthy at the present flow: the learned profile
            exp = round(float(mon.branch[b]["p_in"] - mon.trackers[b].expected_loss(float(sim.x[i]), f["u"]) - mon.elev[i]), 2) if f else None
            hh.append({"id": sim.hh_ids[i], "l": mon.labels[i], "b": b, "pos": int(sim.pos[i]),
                       "s": STATUS_NAME[int(mon.status[i])], "p": round(float(mon.p_est[i]), 2), "c": round(float(mon.conf[i]), 2),
                       "m": bool(sim.instrumented[i]), "v": round(float(mon.vol[i] / mon.members[i]), 1),
                       "r": sim.hh_ids[i] in reported, "q": bool(qual[i]), "e": exp,
                       "hw": self.hw["on"] and sim.hh_ids[i] == self.hw_home})
        return self._twin_out(vid, branches, hh)

    def _branch_view(self, vid: str) -> list[dict]:
        mon = self.monitors[vid]
        open_inc = {i["cond_key"]: i for i in self.incidents.items.values() if i["village_id"] == vid}
        branches = []
        for b, br in enumerate(mon.branch):
            inc = open_inc.get(f"{vid}:hyd:{br.get('id')}")
            feats = br.get("feats") or {}
            st = "idle" if not self.clock.in_window else "unknown" if not br.get("fresh_in") else "ok"
            if inc is not None:
                st = {"SUPPLY_INTERRUPTION": "interrupted", "SUSPECTED_LEAK": "leak", "LOW_PRESSURE": "low",
                      "ABNORMAL_PATTERN": "anomaly"}[inc["type"]]
            if f"{vid}:scheme" in open_inc:
                st = "interrupted"
            idx = mon.branch_idx[b]
            branches.append({
                "id": br.get("id"), "idx": b, "name": br.get("name"), "n": br.get("n"), "p_in": br.get("p_in"),
                "p_end": br.get("p_end"), "flow": br.get("flow"), "fresh_in": br.get("fresh_in"), "fresh_end": br.get("fresh_end"),
                "anomaly": round(float(mon.anom_s[b]), 2), "z_r": round(feats.get("z_r", 0.0), 1), "z_q": round(feats.get("z_q", 0.0), 1),
                "exp_flow": round(feats["exp_q"], 1) if feats else None, "status": st, "incident": inc["id"] if inc else None,
                "evidence": round(float(mon.trackers[b].cusum / mon.trackers[b].h), 2) if self.clock.in_window else 0.0,
                "p_leak": None if mon.p_leak[b] is None else round(float(mon.p_leak[b]), 2),
                "segment": (inc["evidence"] or {}).get("segment") if inc else None,
                "lpcd": round(float((mon.vol[idx] / mon.members[idx]).mean()), 1),
                "counts": {STATUS_NAME[k]: int((mon.status[idx] == k).sum()) for k in (OK, LOW, DRY, UNKNOWN)}})
        return branches

    def _twin_out(self, vid: str, branches: list, hh: list) -> dict:
        sim, mon, T = self.sims[vid], self.monitors[vid], self.telemetry
        v = S.village_by_id(vid)
        dev_status = {"online": 0, "stale": 0, "offline": 0, "never": 0}
        problem = []
        for d in mon.device_ids:
            s = T.status(d)
            dev_status[s] += 1
            if s in ("stale", "offline"):
                problem.append({"id": d, "status": s, "last": (T.latest.get(d) or {}).get("ts")})
        c = sim.code
        return {
            "id": vid, "code": sim.code, "name": sim.name, "lang": v["lang"], "admin": S.admin_path(v),
            "ext": S.external_ids(v), "lat": v["lat"], "lon": v["lon"],
            "tank": mon.tank, "pump": mon.pump, "source": mon.source,
            "main": {"flow": T.value(f"{c}-MAIN", "flow_lpm"), "fresh": T.fresh(f"{c}-MAIN")},
            "branches": branches, "households": hh, "quality": mon.quality, "forecast": mon.forecast,
            "kpis": analytics.village_kpis(self, vid), "sites": self.institutions[vid],
            "devices": {**dev_status, "total": len(mon.device_ids), "problem": problem},
            "balance": mon.water_balance(), "equity": mon.equity(), "demo_faults": self.active_faults(vid),
        }

    # ------------------------------------------------------- hardware in the loop
    # A real sensor node (or the script that plays one) posts to /api/telemetry as HW-NODE-01. While it is
    # live, its readings replace the simulated ones for one metered home, so the estimator, the detectors
    # and the twin all react to it exactly as they would to any tap node.
    @property
    def hw_live(self) -> bool:
        return bool(self.hw_home) and time.time() - self.hw["rx"] < HW_LIVE_S

    def hw_seen(self, metrics: dict, quality: str):
        with self.lock:
            self.hw.update(rx=time.time(), metrics=dict(metrics), quality=quality or "good")
            self.hw["count"] += 1

    def _hw_tick(self) -> str | None:
        """Device id of the tap the board is standing in for this tick, announcing when it joins or leaves."""
        live = self.hw_live
        if live != self.hw["on"]:
            self.hw["on"] = live
            hh = self.households[self.hw_home]
            if live:  # carry on from what the home has had today, so its litres do not jump
                mon = self.monitors[hh["village_id"]]
                self.hw["volume"] = float(mon.vol[mon.hh_ids.index(hh["id"])])
            self.feed("system", "info", (f"Bench node is live: its readings now stand in for the tap at {hh['label']}" if live else
                                         f"Bench node went silent: the simulator has taken back the tap at {hh['label']}"), hh["village_id"])
        return f"{self.hw_home}-TAP" if live else None

    def _hw_reading(self, clk) -> dict:
        m = self.hw["metrics"]
        flow = float(m.get("flow_lpm", 0.0))
        if clk.new_day:
            self.hw["volume"] = 0.0
        if clk.win_idx is not None:
            self.hw["volume"] += flow * clk.dt
        return {"pressure_bar": round(float(m.get("pressure_bar", 0.0)), 3), "flow_lpm": round(flow, 2),
                "volume_l": round(self.hw["volume"], 1)}

    def hw_bind(self, household_id: str | None, actor: str, role: str) -> dict:
        with self.lock:
            if household_id is not None:
                hh = self.households.get(household_id)
                if hh is None or hh["village_id"] != S.FOCUS_VILLAGE or not hh["instrumented"]:
                    raise ValueError("the bench node can stand in for a metered home in the focus village only")
            self.hw_home, self.hw["on"] = household_id, False  # announced again on the next tick
            self.audit.log(self.now, actor, role, "hardware.bind", "device", HW_DEVICE, None, household_id or "unbound", "")
            self.version += 1
            return self.hw_status()

    def hw_status(self) -> dict:
        hh = self.households.get(self.hw_home or "")
        return {"device": HW_DEVICE, "village_id": S.FOCUS_VILLAGE, "live": self.hw_live,
                "age_s": round(time.time() - self.hw["rx"], 1) if self.hw["rx"] else None, "packets": self.hw["count"],
                "metrics": self.hw["metrics"], "quality": self.hw["quality"], "silent_after_s": HW_LIVE_S,
                "bound": {"household_id": hh["id"], "label": hh["label"], "lane": hh["lane"]} if hh else None,
                "candidates": [{"household_id": h["id"], "label": h["label"], "lane": h["lane"]}
                               for h in self.households.values() if h["village_id"] == S.FOCUS_VILLAGE and h["instrumented"]]}

    # ----------------------------------------------------------------- replay
    def _record(self, clk):
        """Keep a compact frame of every village each tick, so the twin can be wound back."""
        if self.tick % 3 == 0:
            rows = self.db.query("SELECT village_id, household_id FROM complaints WHERE status!='closed'")
            for vid in self.sims:
                self._reported[vid] = frozenset(r["household_id"] for r in rows if r["village_id"] == vid)
        for vid, mon in self.monitors.items():
            f = mon.frame(clk, self._branch_view(vid), self._reported[vid])
            f["k"] = self.tick
            self.frames[vid].append(f)

    def timeline(self, vid: str) -> dict:
        with self.lock:
            rows = []
            for f in self.frames[vid]:
                st = f["st"]
                rows.append([f["k"], f["t"][11:16], int(f["win"]), int((st == 1).sum()), int((st == 2).sum()), int((st == 3).sum()),
                             int(any(b["status"] in ("leak", "low", "interrupted", "anomaly") for b in f["branches"]))])
            return {"village_id": vid, "frames": rows, "live": self.tick}

    def replay(self, vid: str, k: int) -> dict | None:
        """The twin as it stood at tick k: same shape as twin(), built from the recorded frame."""
        with self.lock:
            frames = self.frames[vid]
            if not frames or not frames[0]["k"] <= k <= frames[-1]["k"]:
                return None
            f = frames[k - frames[0]["k"]]
            sim, mon = self.sims[vid], self.monitors[vid]
            hh = [{"id": sim.hh_ids[i], "l": mon.labels[i], "b": int(sim.b_of[i]), "pos": int(sim.pos[i]),
                   "s": STATUS_NAME[int(f["st"][i])], "p": round(float(f["p"][i]), 2), "c": round(float(f["c"][i]) / 100, 2),
                   "m": bool(sim.instrumented[i]), "v": round(float(f["v"][i]), 1), "r": sim.hh_ids[i] in f["rep"],
                   "q": bool(f["q"][i]), "e": None, "hw": False} for i in range(sim.n)]
            out = self._twin_out(vid, f["branches"], hh)
            st = f["st"]
            out.update(tank=f["tank"], pump=f["pump"], main={"flow": f["main"], "fresh": f["main"] is not None}, quality=f["quality"],
                       forecast={"curve": [], "empty_at": None}, demo_faults=[],
                       kpis={**out["kpis"], "counts": {STATUS_NAME[c]: int((st == c).sum()) for c in (OK, LOW, DRY, UNKNOWN, IDLE)}})
            return {"focus": out, "clock": {"in_window": f["win"], "time": f["t"][11:16], "iso": f["t"], "running": False, "replay": True},
                    "k": k, "t": f["t"]}

    def snapshot(self, vid: str | None = None) -> dict:
        with self.lock:
            return {"v": self.version, "clock": self.clock_state(),
                    "summary": [analytics.village_summary(self, v) for v in self.sims],
                    "focus": self.twin(vid) if vid in self.sims else None,
                    "incidents": self.incidents.open_list(), "feed": self.feed_list(limit=40),
                    "sync": self.sync.summary(), "telemetry": {"ingested": self.telemetry.total,
                                                               "rejected": self.telemetry.rejected,
                                                               "duplicates": self.telemetry.duplicates}}

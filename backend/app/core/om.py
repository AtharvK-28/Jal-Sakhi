"""Operations and upkeep: the side of running a village scheme that sensors do not see.

Three registers a Pani Samiti keeps, and what the platform adds to each:

  upkeep plan    scheduled preventive work per asset. Some items are condition-based, raised from what the
                 monitoring already knows: pump wear, a lane that keeps failing, a battery running down.
  operator log   the Nal Jal Mitra's entry for each supply window: meter reading, pump hours, chlorine.
                 Every entry is checked against the sensors, which catches a drifting sensor and a careless
                 or invented entry alike.
  accounts       user charges demanded and collected per household, running costs by head, and whether the
                 charge covers the cost. Electricity comes from the pump's measured energy, not an estimate.

It also keeps the Jal Seva Aankalan's stage (draft, endorsed by the Gram Sabha, open for 30 days of citizen
feedback) and the feedback itself.

Everything seeded here is SIMULATED demo data: payments, expenses and past log entries are invented. Upkeep
intervals are typical practice (CPHEEO O&M manual, JJM water-quality norms); a deployment sets them per scheme.
"""
from __future__ import annotations

import calendar
import random
from collections import defaultdict
from datetime import date, timedelta

from .. import config as C
from .. import seed as S

RATE_PER_KWH = 7.0  # demo electricity tariff, rupees
OPERATOR_PAY = 3000.0  # demo monthly honorarium, rupees
BLEACH_G_PER_KL = 4.0  # bleaching powder at about 25% available chlorine, for roughly 1 mg/L
TOLERANCE = 0.06  # an operator's meter reading within 6% of the flow sensor counts as agreement
FEEDBACK_DAYS = 30  # citizen feedback window after the Gram Sabha endorses the assessment
HEADS = ["electricity", "operator", "chlorine", "repairs", "other"]

# key, asset, task, days between, where the interval comes from
TASKS = [
    ("tank", "Elevated tank", "Clean and disinfect the tank", 365, "CPHEEO O&M manual: at least once a year"),
    ("valves", "Lane valves", "Operate and inspect every valve", 180, "CPHEEO O&M manual: every 6 to 12 months"),
    ("flush", "Distribution lines", "Flush the lanes from the tail end", 180, "CPHEEO O&M manual: every 3 to 12 months"),
    ("chlor", "Chlorinator", "Check the chlorinator and the dosing stock", 7, "village routine"),
    ("source", "Borewell", "Check the borewell head, cable and recharge structure", 90, "village routine"),
    ("sensors", "Sensor nodes", "Clean the probes and check sensors against a reference", 90, "practice for low-cost probes"),
    ("wq_bact", "Water quality", "Bacteriological test at a laboratory", 182, "JJM norm: twice a year"),
    ("wq_chem", "Water quality", "Chemical test at a laboratory", 365, "JJM norm: once a year"),
    ("wq_ftk", "Water quality", "Field Test Kit round by the trained women's group", 30, "village routine"),
    ("vwsc", "Pani Samiti", "Monthly meeting: read out the accounts and the open complaints", 30, "village routine"),
    ("utsav", "Pani Samiti", "Jal Utsav: yearly community review of the scheme", 365, "JJM 2.0"),
    ("pump", "Pump", "Service the pump: bearings, impeller, alignment", 365, "brought forward by the wear model when the pump shows it"),
]


def month_of(d: date, back: int = 0) -> str:
    y, m = d.year, d.month - back
    while m <= 0:
        y, m = y - 1, m + 12
    return f"{y:04d}-{m:02d}"


def days_in(month: str) -> int:
    return calendar.monthrange(int(month[:4]), int(month[5:]))[1]


def nice(day: str) -> str:
    """An ISO date as people write it: 18 Feb 2026."""
    return date.fromisoformat(day).strftime("%d %b %Y").lstrip("0")


class Upkeep:
    def __init__(self, ctx):
        self.ctx, self.db = ctx, ctx.db
        self.meter_base: dict[str, float] = {}  # the bulk meter's reading when this session began, kL
        self._marks: dict[str, tuple] = {}  # at the last window close: pump minutes (true, sensed) and litres through the meter
        self._receipts: dict[str, int] = defaultdict(int)
        self._memo: dict[str, dict] = {}
        self._rng = random.Random(4242)
        with self.db.tx():
            for v in S.VILLAGES:
                self._seed(v)

    # ------------------------------------------------------------------ seed
    def _seed(self, v: dict):
        vid, q = v["id"], v["quality"]
        rnd = random.Random(v["seed"] * 53 + 11)
        today = C.SIM_START.date()
        homes = [h for h in self.ctx.households.values() if h["village_id"] == vid]
        hist = self.ctx.history[vid]

        # upkeep: a well-run scheme is mostly up to date, a struggling one has let things slide
        rows = []
        for key, asset, title, every, basis in TASKS:
            late = rnd.random() < (1 - q) * 1.7
            ago = int(every * (rnd.uniform(1.08, 1.6) if late else rnd.uniform(0.15, 0.85)))
            rows.append((f"{vid}:{key}", vid, key, asset, title, every, basis, (today - timedelta(days=ago)).isoformat(), S.ASSIGNEES["operator"], None))
        self.db.executemany("INSERT INTO om_tasks VALUES (?,?,?,?,?,?,?,?,?,?)", rows)

        # operator log: two weeks of entries, one per supply window, with the gaps a real register has
        people = sum(h["members"] for h in homes)
        meter, keep, rows = 9000.0 + v["seed"] * 37.0, 0.55 + 0.45 * q, []
        for r in hist[-14:]:
            for w, share in enumerate(C.WINDOW_SHARE):
                kl = r["avg_lpcd"] * people / 1000 * share * rnd.uniform(0.97, 1.03)
                meter += kl
                if rnd.random() > keep:
                    continue
                end = C.SUPPLY_WINDOWS[w][1]
                rows.append((vid, r["day"], w, round(meter, 1), round(kl * 1000 / v["pump_lpm"] / 60, 2), round(kl * BLEACH_G_PER_KL, -1), "",
                             None, S.ASSIGNEES["operator"], "simulated-operator", f"{r['day']}T{end // 60:02d}:{end % 60:02d}:00+05:30", None, None, "unchecked", None))
        self.db.executemany("INSERT INTO operator_log (village_id, day, window_idx, meter_kl, pump_hours, chlorine_g, remarks, photo, entered_by,"
                            " source, ts, sensor_kl, sensor_pump_hours, verdict, diff_pct) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        self.meter_base[vid] = meter

        # user charges: three full months and the one that has just begun
        tariff, months, rows = float(v["tariff"]), [month_of(today, k) for k in (3, 2, 1, 0)], []
        for h in sorted(homes, key=lambda x: x["id"]):
            lean = rnd.uniform(-0.22, 0.14) - (0.55 if rnd.random() < 0.07 else 0.0)  # a few households never pay
            for k, month in enumerate(months):
                p = (0.52 + 0.46 * q + lean) * (0.42 if k == 3 else 1.0)
                if rnd.random() < p:
                    self._receipts[vid] += 1
                    on = f"{month}-{rnd.randint(2, min(26, today.day - 1 if k == 3 else 26)):02d}"
                    rows.append((h["id"], vid, month, tariff, tariff, on, f"RC-{v['code']}-{self._receipts[vid]:05d}", "VWSC collector"))
                else:
                    rows.append((h["id"], vid, month, tariff, 0.0, None, None, None))
        self.db.executemany("INSERT INTO charges VALUES (?,?,?,?,?,?,?,?)", rows)

        # running costs other than electricity, which is worked out from the pump's energy
        rows = []
        for k, month in enumerate(months):
            if k < 3:
                rows.append((vid, month, f"{month}-28", "operator", OPERATOR_PAY, "Nal Jal Mitra honorarium", "simulated-ledger", "VWSC"))
            rows.append((vid, month, f"{month}-0{rnd.randint(2, 4)}", "chlorine", float(rnd.randrange(250, 460, 10)) * (0.3 if k == 3 else 1.0),
                         "Bleaching powder", "simulated-ledger", "VWSC"))
            if k < 3 and rnd.random() < 0.3 + (1 - q) * 1.5:
                rows.append((vid, month, f"{month}-{rnd.randint(5, 25):02d}", "repairs", float(rnd.randrange(600, 3300, 50)),
                             rnd.choice(["Pipe repair and fittings", "Valve replaced", "Starter and cable repair", "Leak clamp and labour"]),
                             "simulated-ledger", "VWSC"))
        self.db.executemany("INSERT INTO expenses (village_id, month, day, head, amount, note, source, entered_by) VALUES (?,?,?,?,?,?,?,?)", rows)

    def touch(self, vid: str):
        self._memo.pop(vid, None)

    # ---------------------------------------------------------------- upkeep
    def tasks(self, vid: str) -> dict:
        today = self.ctx.now.date()
        mon = self.ctx.monitors[vid]
        ftk = self.db.scalar("SELECT MAX(ts) FROM wq_tests WHERE village_id=? AND kind='FTK'", (vid,))
        out = []
        for t in self.db.query("SELECT * FROM om_tasks WHERE village_id=? ORDER BY rowid", (vid,)):
            last = date.fromisoformat(t["last_done"])
            if t["slug"] == "wq_ftk" and ftk and ftk[:10] > t["last_done"]:  # a test recorded on the quality page counts
                last = date.fromisoformat(ftk[:10])
            due = last + timedelta(days=t["every_days"])
            left = (due - today).days
            status = "overdue" if left < 0 else "due" if left <= max(3, t["every_days"] // 10) else "ok"
            why = None
            if t["slug"] == "pump":  # condition before calendar: the wear model can bring the service forward
                life, risk = mon.pump.get("life") or {}, mon.pump.get("risk")
                if self.ctx.incidents.is_open(f"{vid}:pumprisk") or self.ctx.incidents.is_open(f"{vid}:pump") or (risk or 0) >= C.PUMP_RISK_ALERT:
                    status, left, why = "overdue", min(left, 0), "the wear model says the pump is close to failing"
                elif mon.pump.get("health") is not None and mon.pump["health"] < 70:
                    status = "due" if status == "ok" else status
                    why = f"pump health is {mon.pump['health']:.0f}%" + (f", about {life['h']:.0f} run-hours left" if life and not life.get("capped") else "")
            out.append({"id": t["id"], "key": t["slug"], "asset": t["asset"], "title": t["title"], "every_days": t["every_days"], "basis": t["basis"],
                        "last_done": last.isoformat(), "next_due": due.isoformat(), "days_left": left, "status": status, "why": why,
                        "done_by": t["done_by"], "note": t["note"]})
        # work the monitoring itself suggests
        since = (self.ctx.now - timedelta(days=30)).isoformat()
        suggested = []
        for r in self.db.query("SELECT branch_id, COUNT(*) AS n FROM incidents WHERE village_id=? AND branch_id IS NOT NULL AND category != 'sensor'"
                               " AND type NOT IN ('TAP_FAULT','CITIZEN_REPORT') AND first_seen >= ? GROUP BY branch_id HAVING n >= 2 ORDER BY n DESC", (vid, since)):
            if r["branch_id"] in mon.branch_ids:
                lane = mon.branch_names[mon.branch_ids.index(r["branch_id"])]
                suggested.append({"title": f"Walk {lane} end to end", "why": f"{r['n']} faults on this lane in the last 30 days", "asset": lane})
        for dev_id in mon.device_ids:
            battery = self.ctx.telemetry.devices[dev_id]["battery"]
            if battery < 25:
                suggested.append({"title": f"Replace the battery at {dev_id}", "why": f"battery at {battery:.0f}%", "asset": "Sensor nodes"})
        ok = sum(t["status"] != "overdue" for t in out)
        return {"tasks": sorted(out, key=lambda t: t["days_left"]), "suggested": suggested,
                "on_time": ok, "total": len(out), "overdue": len(out) - ok}

    def task_done(self, task_id: str, actor: str, role: str, note: str | None) -> dict:
        t = self.db.one("SELECT * FROM om_tasks WHERE id=?", (task_id,))
        if t is None:
            raise KeyError(task_id)
        today = self.ctx.now.date().isoformat()
        late = date.fromisoformat(t["last_done"]) + timedelta(days=t["every_days"]) < self.ctx.now.date()
        self.db.execute("UPDATE om_tasks SET last_done=?, done_by=?, note=? WHERE id=?", (today, actor, note, task_id))
        self.db.insert("om_task_log", {"task_id": task_id, "village_id": t["village_id"], "done_at": today, "done_by": actor, "note": note,
                                       "on_time": 0 if late else 1})
        self.ctx.audit.log(self.ctx.now, actor, role, "upkeep.done", "task", task_id, t["last_done"], today, (note or t["title"])[:200])
        self.touch(t["village_id"])
        return {"id": task_id, "last_done": today}

    # ---------------------------------------------------------- operator log
    def meter_now(self, vid: str) -> dict:
        """DEMO helper: what the bulk meter and the pump's hour counter would show right now."""
        sim = self.ctx.sims[vid]
        pump0, _, litres0 = self._marks.get(vid, (0.0, 0.0, 0.0))
        return {"meter_kl": round(self.meter_base[vid] + sim.meter_l / 1000, 1), "pump_hours": round((sim.pump_run_min - pump0) / 60, 2),
                "chlorine_g": round((sim.meter_l - litres0) / 1000 * BLEACH_G_PER_KL, -1)}

    def log(self, vid: str, window_idx: int, meter_kl: float, pump_hours: float | None, chlorine_g: float | None, remarks: str,
            by: str, source: str) -> dict:
        """Record an entry and check its meter reading against what the flow sensor has counted since this session began."""
        mon = self.ctx.monitors[vid]
        _, sensed0, _ = self._marks.get(vid, (0.0, 0.0, 0.0))
        said, sensed = meter_kl - self.meter_base[vid], mon.meter_l / 1000
        if said < -0.05:
            raise ValueError(f"a bulk meter only counts up: the last reading was {self.meter_base[vid]:.1f} kL")
        diff = (said - sensed) / max(sensed, 0.5)
        verdict = "match" if abs(said - sensed) <= max(0.3, TOLERANCE * sensed) else "differs"
        row = {"village_id": vid, "day": self.ctx.now.date().isoformat(), "window_idx": window_idx, "meter_kl": round(meter_kl, 1),
               "pump_hours": None if pump_hours is None else round(pump_hours, 2), "chlorine_g": chlorine_g, "remarks": remarks or "",
               "photo": None, "entered_by": by, "source": source, "ts": self.ctx.now.isoformat(timespec="seconds"),
               "sensor_kl": round(self.meter_base[vid] + sensed, 1), "sensor_pump_hours": round((mon.pump_min - sensed0) / 60, 2),
               "verdict": verdict, "diff_pct": round(diff * 100, 1)}
        row["id"] = self.db.insert("operator_log", row)
        self.touch(vid)
        return row

    def logs(self, vid: str, limit: int = 24) -> dict:
        rows = self.db.query("SELECT * FROM operator_log WHERE village_id=? ORDER BY id DESC LIMIT ?", (vid, limit))
        today = self.ctx.now.date()
        start = (today - timedelta(days=14)).isoformat()
        got = self.db.scalar("SELECT COUNT(*) FROM (SELECT DISTINCT day, window_idx FROM operator_log WHERE village_id=? AND day>=? AND day<?)",
                             (vid, start, today.isoformat())) or 0
        return {"rows": rows, "kept": int(got), "expected": 14 * len(C.SUPPLY_WINDOWS), "kept_pct": round(got / (14 * len(C.SUPPLY_WINDOWS)) * 100, 1),
                "differs": sum(r["verdict"] == "differs" for r in rows), "tolerance_pct": TOLERANCE * 100}

    # -------------------------------------------------------------- accounts
    def _electricity(self, vid: str, month: str) -> float:
        hist = [r for r in self.ctx.history[vid] if r["day"].startswith(month) and r.get("energy_kwh") is not None]
        kwh = sum(r["energy_kwh"] for r in hist)
        if month == month_of(self.ctx.now.date()):
            if not any(r["day"] == self.ctx.now.date().isoformat() for r in hist):
                kwh += self.ctx.monitors[vid].bal["kwh"]  # today so far, from the pump's measured current
        elif len(hist) < days_in(month):  # the record does not reach that far back: fill at the average day
            every = [r["energy_kwh"] for r in self.ctx.history[vid] if r.get("energy_kwh") is not None]
            kwh += sum(every) / max(1, len(every)) * (days_in(month) - len(hist))
        return kwh * RATE_PER_KWH

    def finance(self, vid: str) -> dict:
        today = self.ctx.now.date()
        cur = month_of(today)
        homes = [h for h in self.ctx.households.values() if h["village_id"] == vid]
        people = sum(h["members"] for h in homes)
        tariff = float(S.village_by_id(vid)["tariff"])
        charged = {r["month"]: r for r in self.db.query(
            "SELECT month, SUM(amount) AS demand, SUM(paid) AS collected, SUM(paid >= amount) AS paid_homes FROM charges WHERE village_id=? GROUP BY month", (vid,))}
        spent = defaultdict(dict)
        for r in self.db.query("SELECT month, head, SUM(amount) AS amt FROM expenses WHERE village_id=? GROUP BY month, head", (vid,)):
            spent[r["month"]][r["head"]] = r["amt"]
        months = []
        for m in (month_of(today, k) for k in (3, 2, 1, 0)):
            costs = {h: round(spent[m].get(h, 0.0)) for h in HEADS}
            costs["electricity"] = round(self._electricity(vid, m))
            c = charged.get(m) or {"demand": 0.0, "collected": 0.0, "paid_homes": 0}
            total = sum(costs.values())
            months.append({"month": m, "partial": m == cur, "demand": round(c["demand"]), "collected": round(c["collected"]), "paid_homes": int(c["paid_homes"] or 0),
                           "collection_pct": round(c["collected"] / c["demand"] * 100, 1) if c["demand"] else None, "costs": costs, "spent": total,
                           "recovery_pct": round(c["collected"] / total * 100, 1) if total else None})
        full = [m for m in months if not m["partial"]]
        demand, collected, cost = (sum(m[k] for m in full) for k in ("demand", "collected", "spent"))
        monthly_cost = cost / max(1, len(full))
        rate = collected / demand if demand else 0.0
        daily = [r["avg_lpcd"] * people / 1000 for r in self.ctx.history[vid] if r.get("avg_lpcd")]
        kl_month = sum(daily) / max(1, len(daily)) * 30
        lanes = self.db.query("SELECT h.lane AS name, h.branch_idx AS idx, SUM(c.paid) AS collected, SUM(c.amount) AS demand FROM charges c"
                              " JOIN households h ON h.id = c.household_id WHERE c.village_id=? AND c.month < ? GROUP BY h.branch_idx ORDER BY h.branch_idx", (vid, cur))
        dues = self.db.query("SELECT c.household_id AS id, h.label, h.lane, SUM(c.amount - c.paid) AS due, SUM(c.paid < c.amount) AS months FROM charges c"
                             " JOIN households h ON h.id = c.household_id WHERE c.village_id=? GROUP BY c.household_id HAVING due > 0"
                             " ORDER BY due DESC, h.label LIMIT 12", (vid,))
        owing = self.db.one("SELECT COUNT(*) AS n, SUM(due) AS total FROM (SELECT SUM(amount - paid) AS due FROM charges WHERE village_id=? AND month < ?"
                            " GROUP BY household_id HAVING due > 0)", (vid, cur))
        return {"tariff": tariff, "homes": len(homes), "months": months, "collection_pct": round(rate * 100, 1),
                "recovery_pct": round(collected / cost * 100, 1) if cost else None, "monthly_cost": round(monthly_cost),
                "monthly_collected": round(collected / max(1, len(full))), "arrears": round(owing["total"] or 0), "homes_in_arrears": int(owing["n"] or 0),
                "break_even_if_all_pay": round(monthly_cost / max(1, len(homes))), "break_even_at_this_rate": round(monthly_cost / max(1, len(homes)) / rate) if rate else None,
                "cost_per_kl": round(monthly_cost / kl_month, 1) if kl_month else None,
                "lanes": [{"name": ln["name"], "collection_pct": round(ln["collected"] / ln["demand"] * 100, 1)} for ln in lanes if ln["demand"]],
                "dues": dues, "rate_per_kwh": RATE_PER_KWH,
                "expenses": self.db.query("SELECT id, day, head, amount, note, entered_by FROM expenses WHERE village_id=? ORDER BY day DESC, id DESC LIMIT 8", (vid,))}

    def pay(self, household_id: str, actor: str, role: str) -> dict:
        """Record that a household has paid everything it owes; issues one receipt."""
        hh = self.ctx.households.get(household_id)
        if hh is None:
            raise KeyError(household_id)
        owed = self.db.query("SELECT month, amount - paid AS due FROM charges WHERE household_id=? AND paid < amount ORDER BY month", (household_id,))
        if not owed:
            raise ValueError(f"{hh['label']} owes nothing")
        vid = hh["village_id"]
        self._receipts[vid] += 1
        receipt = f"RC-{S.village_by_id(vid)['code']}-{self._receipts[vid]:05d}"
        today = self.ctx.now.date().isoformat()
        self.db.execute("UPDATE charges SET paid=amount, paid_on=?, receipt=?, collected_by=? WHERE household_id=? AND paid < amount",
                        (today, receipt, actor, household_id))
        total = sum(r["due"] for r in owed)
        self.ctx.audit.log(self.ctx.now, actor, role, "charges.collect", "household", household_id, None, receipt, f"Rs {total:.0f} for {len(owed)} month(s)")
        self.touch(vid)
        return {"receipt": receipt, "amount": total, "months": [r["month"] for r in owed], "household": hh["label"], "paid_on": today}

    def spend(self, vid: str, head: str, amount: float, note: str, actor: str, role: str) -> dict:
        if head not in HEADS or head == "electricity":
            raise ValueError("head must be operator, chlorine, repairs or other (electricity is worked out from the pump's energy)")
        today = self.ctx.now.date()
        row = {"village_id": vid, "month": month_of(today), "day": today.isoformat(), "head": head, "amount": float(amount), "note": note,
               "source": "entered", "entered_by": actor}
        row["id"] = self.db.insert("expenses", row)
        self.ctx.audit.log(self.ctx.now, actor, role, "expense.add", "village", vid, None, f"{head}: Rs {amount:.0f}", note[:200])
        self.touch(vid)
        return row

    def dues(self, household_id: str) -> dict:
        """What one household sees about its own charge."""
        rows = self.db.query("SELECT month, amount, paid, paid_on, receipt FROM charges WHERE household_id=? ORDER BY month", (household_id,))
        owed = [r for r in rows if r["paid"] < r["amount"]]
        last = max((r for r in rows if r["receipt"]), key=lambda r: r["paid_on"], default=None)
        return {"tariff": rows[-1]["amount"] if rows else None, "due": sum(r["amount"] - r["paid"] for r in owed), "months_due": [r["month"] for r in owed],
                "last_receipt": {"id": last["receipt"], "on": last["paid_on"]} if last else None}

    # ----------------------------------------------------------- one summary
    def summary(self, vid: str) -> dict:
        """The handful of numbers other screens need. Cached until something in the registers changes."""
        if vid not in self._memo:
            t, lg, f = self.tasks(vid), self.logs(vid, 1), self.finance(vid)
            self._memo[vid] = {"upkeep_on_time": t["on_time"], "upkeep_total": t["total"], "upkeep_pct": round(t["on_time"] / t["total"] * 100, 1),
                               "log_pct": lg["kept_pct"], "collection_pct": f["collection_pct"], "recovery_pct": f["recovery_pct"],
                               "arrears": f["arrears"], "tariff": f["tariff"]}
        return self._memo[vid]

    def profile(self, vid: str, kpis: dict) -> dict:
        """The scheme at a glance, in the shape of a Sujal Gaon profile: source, infrastructure, reliability, O&M, quality."""
        v, mon, sim = S.village_by_id(vid), self.ctx.monitors[vid], self.ctx.sims[vid]
        tasks = {t["key"]: t for t in self.tasks(vid)["tasks"]}
        src, pump = mon.source, mon.pump
        hist = self.ctx.history[vid][-30:]
        faults = sum(1 for i in self.ctx.incidents.items.values() if i["village_id"] == vid and i["category"] in ("supply", "pressure", "leak", "anomaly"))
        days = src.get("days_to_limit")
        health = pump.get("health")
        tests = self.db.query("SELECT kind, result, ts, sample_point FROM wq_tests WHERE village_id=? ORDER BY ts DESC LIMIT 3", (vid,))
        s = self.summary(vid)
        return {
            "ids": S.external_ids(v), "scheme": f"{sim.name} single-village piped water scheme", "gp": S.admin_path(v)["gp"],
            "homes": sim.n, "lanes": sim.nb, "people": int(mon.members.sum()),
            "assets": [
                {"name": "Borewell and source", "state": "poor" if days is not None and days < 45 else "watch" if days is not None else "good",
                 "detail": f"rest level {src.get('rest_m') or src.get('depth_m') or 0:.1f} m below ground" + (f", about {days:.0f} days of margin" if days is not None else ", stable")},
                {"name": "Pump", "state": "good" if health is None or health >= 70 else "watch" if health >= 40 else "poor",
                 "detail": (f"health {health:.0f}%" if health is not None else "has not run yet in this session") + f", {v['pump_lpm']} L/min rated"},
                {"name": "Elevated tank", "state": "good" if tasks["tank"]["status"] != "overdue" else "watch",
                 "detail": f"{v['tank_kl']} kL, last cleaned {nice(tasks['tank']['last_done'])}"},
                {"name": "Distribution", "state": "good" if not faults else "watch", "detail": f"{sim.nb} lanes, {sim.n} tap connections, {faults} open fault(s)"},
                {"name": "Sensor nodes", "state": "good" if kpis["devices_online_pct"] >= 95 else "watch", "detail": f"{kpis['devices_online_pct']:.0f}% reporting"},
            ],
            "reliability": {"regular_pct": round(sum(r["regularity_pct"] for r in hist) / max(1, len(hist)), 1),
                            "lpcd": round(sum(r["avg_lpcd"] for r in hist) / max(1, len(hist)), 1)},
            "om": {"operator": S.ASSIGNEES["operator"], "tariff": s["tariff"], "collection_pct": s["collection_pct"], "recovery_pct": s["recovery_pct"],
                   "upkeep": f"{s['upkeep_on_time']} of {s['upkeep_total']} items up to date"},
            "tests": tests,
        }

    # ------------------------------------------------- Jal Seva Aankalan stage
    def assessment(self, vid: str) -> dict:
        st = self.db.one("SELECT * FROM aankalan_state WHERE village_id=?", (vid,))
        tally = self.db.one("SELECT COUNT(*) AS n, SUM(agree) AS yes FROM aankalan_feedback WHERE village_id=?", (vid,))
        out = {"stage": "draft", "endorsed_on": None, "endorsed_by": None, "open_until": None, "days_left": None,
               "responses": int(tally["n"] or 0), "agree": int(tally["yes"] or 0),
               "comments": self.db.query("SELECT comment, agree, ts FROM aankalan_feedback WHERE village_id=? AND comment != '' ORDER BY id DESC LIMIT 5", (vid,))}
        if st:
            until = date.fromisoformat(st["endorsed_on"]) + timedelta(days=FEEDBACK_DAYS)
            left = (until - self.ctx.now.date()).days
            out.update(stage="feedback" if left >= 0 else "final", endorsed_on=st["endorsed_on"], endorsed_by=st["endorsed_by"],
                       open_until=until.isoformat(), days_left=max(0, left), note=st["note"])
        return out

    def endorse(self, vid: str, actor: str, role: str, note: str) -> dict:
        today = self.ctx.now.date().isoformat()
        self.db.execute("INSERT OR REPLACE INTO aankalan_state (village_id, stage, endorsed_on, endorsed_by, note) VALUES (?,?,?,?,?)",
                        (vid, "feedback", today, actor, note))
        self.ctx.audit.log(self.ctx.now, actor, role, "aankalan.endorse", "village", vid, "draft", "endorsed", note[:200])
        return self.assessment(vid)

    def feedback(self, vid: str, household_id: str, agree: bool, comment: str, source: str = "portal"):
        if self.assessment(vid)["stage"] != "feedback":
            raise ValueError("the assessment is not open for feedback")
        self.db.execute("INSERT OR REPLACE INTO aankalan_feedback (village_id, household_id, agree, comment, ts, source) VALUES (?,?,?,?,?,?)",
                        (vid, household_id, int(agree), (comment or "")[:300], self.ctx.now.isoformat(timespec="seconds"), source))

    # ------------------------------------------------------------ simulation
    def window_closed(self, clk, overall: dict):
        """End of a supply window: the simulated operators write their entries, and a few households answer an open assessment."""
        for v in S.VILLAGES:
            vid = v["id"]
            sim, mon = self.ctx.sims[vid], self.ctx.monitors[vid]
            pump0, _, litres0 = self._marks.get(vid, (0.0, 0.0, 0.0))
            if self._rng.random() <= 0.55 + 0.45 * v["quality"]:
                high = 1.0 + v.get("log_bias", 0.0)  # demo: one operator's entries run high, for the check to catch
                meter = self.meter_base[vid] + sim.meter_l / 1000 * high * (1 + self._rng.uniform(-0.004, 0.004))
                self.log(vid, clk.closed_idx, meter, (sim.pump_run_min - pump0) / 60 * high, round((sim.meter_l - litres0) / 1000 * BLEACH_G_PER_KL, -1), "",
                         S.ASSIGNEES["operator"], "simulated-operator")
            self._marks[vid] = (sim.pump_run_min, mon.pump_min, sim.meter_l)
            if self.assessment(vid)["stage"] == "feedback":
                asked = {r["household_id"] for r in self.db.query("SELECT household_id FROM aankalan_feedback WHERE village_id=?", (vid,))}
                pool = [h for h in sim.hh_ids if h not in asked]
                for hid in self._rng.sample(pool, min(3, len(pool))):
                    self.feedback(vid, hid, self._rng.random() < (overall.get(vid) or 70) / 100, "", "simulated-citizen")
            self.touch(vid)

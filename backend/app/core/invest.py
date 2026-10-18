"""Investment planner: where the next rupee buys the most functional household taps.

For every village in a jurisdiction, the households failing the JJM functionality test are split by what
fails them (supply on a lane with a fault history, tail-end pressure, quality, a pump close to failing, a
falling source, silent sensors). Each cause maps to one intervention with an indicative cost and the
households it would bring back. Ranking is by households per lakh; a budget is filled greedily.

Costs are indicative unit costs for comparison, stated below so they can be argued with. A real plan
replaces them with the state's Schedule of Rates and an engineer's estimate.
"""
from __future__ import annotations

from datetime import timedelta

import numpy as np

from .. import seed as S

COST = {  # rupees, indicative
    "lane_repair": 45_000,  # locate and repair leaks on one distribution lane, valves serviced
    "pressure": 60_000,  # tail-end pressure: valve rebalancing, a pressure-sustaining valve or small booster
    "chlorination": 30_000,  # chlorinator repair or replacement, three months of dosing stock, operator training
    "pump": 1_20_000,  # pump overhaul or replacement and starter
    "source": 3_50_000,  # source strengthening: recharge structure or a new borewell
    "sensor": 3_000,  # per silent sensor node: battery, probe or modem
    "connection": 2_500,  # per home: ferrule, stopcock or service pipe, when the lane itself is fine
}
PROTECTS = {"pump", "source"}  # these keep homes functional that would fail; they do not restore homes failing today
WHAT = {
    "lane_repair": "Repair leaks and service valves on {lane}",
    "pressure": "Raise tail-end pressure on {lane} (valve rebalancing / booster)",
    "chlorination": "Restore chlorination at the tank (chlorinator, dosing stock, training)",
    "pump": "Overhaul or replace the pump before it fails",
    "source": "Strengthen the source (recharge structure or new borewell)",
    "sensor": "Repair {n} silent sensor node(s)",
    "connection": "Repair the service connections at {n} home(s) ({lanes})",
}


def _failing(p, vid: str):
    """Per-household (regular, quantity, quality, known) as boolean arrays, from today or the last week."""
    mon, sim = p.monitors[vid], p.sims[vid]
    flags = mon.day_flags()
    if flags is not None:
        return flags["regular"], flags["quantity"], flags["quality"], flags["known"], "today's supply windows"
    # before the first window closes: the last week's shares, laid on the tail end of each lane (worst served first)
    hist = (p.history.get(vid) or [])[-7:]
    n = sim.n
    share = {k: 1 - float(np.mean([r[k] for r in hist])) / 100 if hist else 0.0 for k in ("regularity_pct", "quantity_pct", "quality_pct")}
    order = np.argsort(-sim.x)  # furthest along their lane first
    def mask(frac):
        m = np.ones(n, bool)
        m[order[:int(round(frac * n))]] = False
        return m
    return mask(share["regularity_pct"]), mask(share["quantity_pct"]), mask(share["quality_pct"]), np.ones(n, bool), "the last 7 days"


def options(p, vid: str) -> tuple[list[dict], dict]:
    sim, mon = p.sims[vid], p.monitors[vid]
    reg, qty, qual, known, basis = _failing(p, vid)
    func = reg & qty & qual & known
    since = (p.now - timedelta(days=30)).isoformat()
    faults = {r["branch_id"]: r["n"] for r in p.db.query(
        "SELECT branch_id, COUNT(*) n FROM incidents WHERE village_id=? AND branch_id IS NOT NULL AND first_seen>=?"
        " AND type IN ('SUSPECTED_LEAK','LOW_PRESSURE','SUPPLY_INTERRUPTION','ABNORMAL_PATTERN') GROUP BY branch_id", (vid, since))}
    for i in p.incidents.items.values():
        if i["village_id"] == vid and i["type"] == "SUSPECTED_LEAK" and i["branch_id"]:
            faults[i["branch_id"]] = faults.get(i["branch_id"], 0) + 2
    out = []

    def add(kind, gain, why, **kw):
        if gain <= 0:
            return
        cost = COST[kind] * kw.pop("units", 1)
        out.append({"village_id": vid, "village": sim.name, "kind": kind, "action": WHAT[kind].format(**kw), "cost": cost,
                    "homes": int(gain), "per_lakh": round(gain / (cost / 1e5), 1), "why": why,
                    "effect": "protects" if kind in PROTECTS else "measures" if kind == "sensor" else "restores"})

    supply_fail = ~(reg & qty) & known
    single: list[tuple[str, int]] = []  # homes failing alone on a healthy lane: one connection job for the village
    for b, bid in enumerate(sim.branch_ids):
        on_lane = sim.b_of == b
        n_fail = int((supply_fail & on_lane).sum())
        if not n_fail:
            continue
        if n_fail <= 2 and faults.get(bid, 0) < 2:  # one or two homes on a healthy lane: their own connection
            single.append((sim.branch_names[b], n_fail))
        elif faults.get(bid, 0) >= 2:
            add("lane_repair", n_fail, f"{faults[bid]} supply / pressure faults on this lane in 30 days; {n_fail} homes short of water", lane=sim.branch_names[b])
        else:
            add("pressure", n_fail, f"{n_fail} homes short of water or pressure, mostly towards the tail", lane=sim.branch_names[b])
    if single:
        n = sum(k for _l, k in single)
        add("connection", n, f"{n} home(s) short of water on lanes that are otherwise served", n=n,
            lanes=", ".join(f"{l} {k}" for l, k in single), units=n)
    q_fail = int((~qual & reg & qty & known).sum())
    add("chlorination", q_fail, f"{q_fail} homes fail only the quality test")
    risk = mon.pump.get("risk")
    if (risk or 0) >= 0.4 or (mon.pump.get("health") is not None and mon.pump["health"] < 60):
        r = max(risk or 0.0, 0.5)
        add("pump", round(r * int(func.sum())), f"failure risk {round(100 * (risk or r))}%: every functional home loses supply if it fails; counted at that risk")
    days = mon.source.get("days_to_limit")
    if days is not None and days < 120:
        frac = min(1.0, (120 - days) / 120)
        add("source", round(frac * sim.n), f"about {days:.0f} days of margin above the pump intake; counted by how soon it runs out")
    silent = [d for d in mon.device_ids if p.telemetry.status(d) in ("stale", "offline")]
    add("sensor", int((~known).sum()), f"{int((~known).sum())} homes cannot be assessed while these sensors are silent "
        "(they become measurable, not necessarily functional)", n=len(silent), units=max(1, len(silent)))
    return out, {"village_id": vid, "village": sim.name, "households": sim.n, "functional": int(func.sum()), "basis": basis}


def plan(p, villages: list[str], budget: float) -> dict:
    opts, base = [], []
    for vid in villages:
        o, b = options(p, vid)
        opts += o
        base.append(b)
    opts.sort(key=lambda o: (-o["per_lakh"], o["cost"]))
    left, gained, protected = budget, 0, 0
    for o in opts:
        o["chosen"] = o["cost"] <= left
        if o["chosen"]:
            left -= o["cost"]
            if o["effect"] == "restores":
                gained += o["homes"]
            elif o["effect"] == "protects":
                protected += o["homes"]
    homes = sum(b["households"] for b in base)
    now = sum(b["functional"] for b in base)
    after = min(homes, now + gained)
    for b in base:
        g = sum(o["homes"] for o in opts if o["chosen"] and o["village_id"] == b["village_id"] and o["effect"] == "restores")
        b["after"] = min(b["households"], b["functional"] + g)
    return {"budget": budget, "spent": budget - left, "households": homes, "functional_now": now, "functional_after": after,
            "pct_now": round(100 * now / homes, 1) if homes else None, "pct_after": round(100 * after / homes, 1) if homes else None,
            "gained": after - now, "protected": protected, "options": opts, "villages": sorted(base, key=lambda b: b["functional"] / b["households"]),
            "unit_costs": COST, "method": "Households failing the JJM test are split by cause; each cause maps to one intervention "
            "with an indicative cost; ranked by households brought back per lakh; the budget is filled in that order. "
            "Pump and source work protects homes from a likely failure (households at risk times the chance) and is counted separately "
            "from homes restored; sensor repair makes homes measurable. Replace the unit costs with "
            "the state's Schedule of Rates for a real plan.", "admin": S.STATE["name"]}

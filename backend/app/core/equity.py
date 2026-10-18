"""Who is left out, and how that compares with what is reported.

A village's functional percentage hides the injustice that matters: the same few homes falling short day
after day, usually at the tail of a lane or up a slope. This module keeps one row per household per day
(hh_daily) and answers three questions from it:

  chronic      homes that failed the JJM test on most of the last 7 days
  dry          homes that received no water at all on any of the last 14 days
  reconcile    what IMIS would report for the village (every connection counted, Har Ghar Jal certified)
               against what the platform observes (homes served reliably over 30 days)

The 30 days before the simulation starts are seeded (simulated history, labelled as such) so the views
have something to show at once; every live day replaces its seeded row.
"""
from __future__ import annotations

import random
from datetime import date, timedelta

import numpy as np

from .. import config as C

CHRONIC_DAYS, CHRONIC_OF = 5, 7  # failed the test on at least 5 of the last 7 days
DRY_DAYS = 14
RELIABLE_OF, RELIABLE_MIN = 30, 24  # "reliably served": functional on at least 24 of the last 30 days
# Har Ghar Jal declarations (DEMO: invented dates; the real ones are in the JJM IMIS village reports)
CERTIFIED = {"VLG-PW": "2024-03-12", "VLG-ST": "2023-11-05", "VLG-NG": "2024-01-20", "VLG-KW": "2024-06-02", "VLG-DK": "2023-08-15"}


def seed_rows(village: dict, sim, hist: list[dict]) -> list[tuple]:
    """Household-level days consistent with the village's seeded daily shares: a few chronically short homes
    (tail ends, uphill) fail most days; the rest of each day's shortfall falls on random homes, tail-biased."""
    rnd = random.Random(village["seed"] * 13 + 5)
    n = sim.n
    tail = np.argsort(-(sim.x + sim.elev * 2))  # furthest and highest first
    k = max(0, round(n * (1 - village["quality"]) * 0.45))
    chronic = set(int(i) for i in tail[:max(k, 0)])
    dry = set(list(chronic)[:max(0, k // 3)]) if village["quality"] < 0.85 else set()
    rows = []
    for r in hist:
        fails = round(n * (1 - r["functional_pct"] / 100))
        bad = set(i for i in chronic if rnd.random() < 0.85) | set(dry)
        pool = [int(i) for i in tail if int(i) not in bad]
        while len(bad) < fails and pool:
            j = min(len(pool) - 1, int(abs(rnd.gauss(0, len(pool) / 3))))
            bad.add(pool.pop(j))
        for i in range(n):
            failed = i in bad
            no_water = i in dry or (failed and rnd.random() < 0.25)
            lpcd = 0.0 if no_water else round(rnd.uniform(14, 40) if failed else r["avg_lpcd"] * rnd.uniform(0.85, 1.2), 1)
            # columns: regular (any water), quantity (enough of it), quality, known, functional (all of them), lpcd
            rows.append((village["id"], sim.hh_ids[i], r["day"], int(not no_water), int(not failed), 1, 1, int(not failed), lpcd,
                         "simulated-history"))
    return rows


def record_day(p, vid: str, day: str):
    """At the close of the last supply window: today's household verdicts replace the seeded or partial row."""
    mon = p.monitors[vid]
    flags = mon.day_flags()
    if flags is None:
        return
    lpcd = mon.vol / mon.members
    p.db.execute("DELETE FROM hh_daily WHERE village_id=? AND day=?", (vid, day))
    p.db.executemany("INSERT INTO hh_daily VALUES (?,?,?,?,?,?,?,?,?,?)", [
        (vid, hid, day, int(flags["regular"][i]), int(flags["quantity"][i]), int(flags["quality"][i]), int(flags["known"][i]),
         int(flags["functional"][i]), round(float(lpcd[i]), 1), "live") for i, hid in enumerate(mon.hh_ids)])


def _days(p, vid: str, n: int) -> list[str]:
    rows = p.db.query("SELECT DISTINCT day FROM hh_daily WHERE village_id=? ORDER BY day DESC LIMIT ?", (vid, n))
    return [r["day"] for r in rows]


def view(p, vid: str) -> dict:
    sim = p.sims[vid]
    hh = {h["id"]: h for h in p.households.values() if h["village_id"] == vid}
    d7, d14, d30 = _days(p, vid, CHRONIC_OF), _days(p, vid, DRY_DAYS), _days(p, vid, RELIABLE_OF)
    def tally(days):
        if not days:
            return {}
        marks = ",".join("?" for _ in days)
        return {r["household_id"]: r for r in p.db.query(
            f"SELECT household_id, SUM(functional) f, SUM(regular) w, AVG(lpcd) l, COUNT(*) n FROM hh_daily WHERE village_id=?"
            f" AND day IN ({marks}) GROUP BY household_id", (vid, *days))}
    t7, t14, t30 = tally(d7), tally(d14), tally(d30)
    chronic = sorted(([hh[h], r] for h, r in t7.items() if r["n"] - r["f"] >= CHRONIC_DAYS), key=lambda x: (x[1]["f"], x[0]["id"]))
    dry = [hh[h] for h, r in t14.items() if r["w"] == 0 and r["n"] >= DRY_DAYS]
    reliable = sum(1 for r in t30.values() if r["f"] >= RELIABLE_MIN)
    lanes: dict[str, int] = {}
    for h, _r in chronic:
        lanes[h["lane"]] = lanes.get(h["lane"], 0) + 1
    certified = CERTIFIED.get(vid)
    pct = round(100 * reliable / sim.n, 1)
    return {
        "village_id": vid, "village": sim.name, "households": sim.n,
        "chronic": [{"id": h["id"], "label": h["label"], "lane": h["lane"], "position": h["position"], "members": h["members"],
                     "days_failed": r["n"] - r["f"], "of": r["n"], "avg_lpcd": round(r["l"] or 0, 1), "metered": h["instrumented"]}
                    for h, r in chronic],
        "chronic_by_lane": [{"lane": k, "n": v} for k, v in sorted(lanes.items(), key=lambda x: -x[1])],
        "dry": [{"id": h["id"], "label": h["label"], "lane": h["lane"]} for h in sorted(dry, key=lambda h: h["id"])],
        "reported": {"fhtc": sim.n, "har_ghar_jal": certified, "source": "as IMIS would carry it: every connection counted (DEMO)"},
        "observed": {"reliable": reliable, "reliable_pct": pct, "days": len(d30), "rule": f"functional on at least {RELIABLE_MIN} of the last {RELIABLE_OF} days"},
        "gap": sim.n - reliable,
        "certification_at_risk": bool(certified) and (pct < 90 or bool(dry)),
        "basis": "seeded simulated history, replaced day by day by live observation",
        "rules": {"chronic": f"failed the JJM test on at least {CHRONIC_DAYS} of the last {CHRONIC_OF} days",
                  "dry": f"no water at all on each of the last {DRY_DAYS} days"},
    }


def summary(p, villages: list[str]) -> list[dict]:
    out = []
    for vid in villages:
        v = view(p, vid)
        out.append({k: v[k] for k in ("village_id", "village", "households", "reported", "observed", "gap", "certification_at_risk")}
                   | {"chronic": len(v["chronic"]), "dry": len(v["dry"])})
    return out


def fetching(p, villages: list[str], minutes: float, days: int = 30) -> dict:
    """Household-days without tap water, times an assumed fetching time. The assumption is the caller's."""
    rows = []
    for vid in villages:
        ds = _days(p, vid, days)
        if not ds:
            continue
        marks = ",".join("?" for _ in ds)
        missing = p.db.scalar(f"SELECT COUNT(*) FROM hh_daily WHERE village_id=? AND day IN ({marks}) AND (regular=0 OR quantity=0)", (vid, *ds)) or 0
        rows.append({"village_id": vid, "village": p.sims[vid].name, "household_days": int(missing), "days": len(ds),
                     "hours": round(missing * minutes / 60)})
    return {"minutes_per_household_day": minutes, "villages": rows, "hours": sum(r["hours"] for r in rows),
            "household_days": sum(r["household_days"] for r in rows),
            "assumption": "Minutes spent fetching water on a day the tap fails (or gives less than 55 litres a person) is an "
                          "assumption you set; replace it with the NSS 76th round (2018) figure for your state before citing."}

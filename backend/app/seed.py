"""Demo world definition: administrative hierarchy, villages and seeded history.

Place names are invented for the demo. External identifiers (LGD, IMIS,
Sujal Gaon, Sujalam Bharat) are placeholders prefixed DEMO- and never claim to
be real government codes.
"""
from __future__ import annotations

import json
import random
from datetime import timedelta

from . import config as C

STATE = {"id": "ST-MH", "level": "state", "name": "Maharashtra", "parent_id": None, "lat": 18.6, "lon": 73.7}
DISTRICTS = [
    {"id": "DT-PUN", "level": "district", "name": "Pune", "parent_id": "ST-MH", "lat": 18.60, "lon": 73.56},
    {"id": "DT-SAT", "level": "district", "name": "Satara", "parent_id": "ST-MH", "lat": 17.95, "lon": 73.89},
]
BLOCKS = [
    {"id": "BK-MUL", "level": "block", "name": "Mulshi", "parent_id": "DT-PUN", "lat": 18.51, "lon": 73.52},
    {"id": "BK-MAV", "level": "block", "name": "Maval", "parent_id": "DT-PUN", "lat": 18.73, "lon": 73.60},
    {"id": "BK-WAI", "level": "block", "name": "Wai", "parent_id": "DT-SAT", "lat": 17.95, "lon": 73.89},
]

# quality: long-run service quality used only to shape the seeded 30-day history.
# tariff: the Pani Samiti's user charge, rupees per household per month. log_bias: how far that village's
# simulated operator over-states the meter (one village does, so the cross-check has something to catch).
# ambient: standing faults injected at reset so higher-level dashboards are not uniformly green.
VILLAGES = [
    {"id": "VLG-PW", "code": "PW", "name": "Pimpalwadi", "block_id": "BK-MUL", "lat": 18.5045, "lon": 73.5180,
     "branches": [20, 20, 20, 20, 20], "uphill": [0.0, 0.02, 0.05, 0.14, 0.04], "tank_kl": 45, "pump_lpm": 350,
     "seed": 11, "lang": "mr", "bearing": 15, "quality": 0.95, "tariff": 60, "ambient": {}},
    {"id": "VLG-ST", "code": "ST", "name": "Shivtara", "block_id": "BK-MUL", "lat": 18.4180, "lon": 73.3420,
     "branches": [18, 16, 20, 14, 16], "uphill": [0.03, 0.0, 0.08, 0.05, 0.0], "tank_kl": 40, "pump_lpm": 320,
     "seed": 23, "lang": "mr", "bearing": 40, "quality": 0.90, "tariff": 50, "ambient": {}},
    {"id": "VLG-NG", "code": "NG", "name": "Nimgiri", "block_id": "BK-MAV", "lat": 18.7420, "lon": 73.6110,
     "branches": [22, 20, 18, 20, 20, 20], "uphill": [0.0, 0.06, 0.02, 0.10, 0.0, 0.04], "tank_kl": 55, "pump_lpm": 420,
     "seed": 37, "lang": "mr", "bearing": 5, "quality": 0.92, "tariff": 60, "ambient": {}},
    {"id": "VLG-DK", "code": "DK", "name": "Devkund", "block_id": "BK-MAV", "lat": 18.8640, "lon": 73.4350,
     "branches": [16, 18, 14, 24], "uphill": [0.02, 0.0, 0.06, 0.12], "tank_kl": 34, "pump_lpm": 280,
     "seed": 41, "lang": "hi", "bearing": 60, "quality": 0.81, "tariff": 40, "ambient": {"blockage": {3: (0.45, 0.62)}}},
    {"id": "VLG-KW", "code": "KW", "name": "Kusumwadi", "block_id": "BK-WAI", "lat": 17.9620, "lon": 73.8810,
     "branches": [20, 20, 16, 20, 20], "uphill": [0.0, 0.04, 0.0, 0.09, 0.03], "tank_kl": 44, "pump_lpm": 340,
     "seed": 53, "lang": "mr", "bearing": 25, "quality": 0.93, "tariff": 60, "ambient": {}},
    {"id": "VLG-AG", "code": "AG", "name": "Amrutgaon", "block_id": "BK-WAI", "lat": 17.8050, "lon": 74.0620,
     "branches": [14, 18, 18, 22, 12, 12], "uphill": [0.0, 0.03, 0.07, 0.11, 0.0, 0.05], "tank_kl": 44, "pump_lpm": 330,
     "seed": 67, "lang": "hi", "bearing": 75, "quality": 0.74, "pump_wear": 0.22, "gw_static": 41.5, "tariff": 50, "log_bias": 0.15,
     "ambient": {"offline": ["AG-B3-END"], "gw_decline": 0.22}},
]
FOCUS_VILLAGE = "VLG-PW"

INSTITUTIONS = [  # institutional tap connections (JJM also covers schools / anganwadis / health centres)
    {"suffix": "SCHOOL", "name": "ZP Primary School", "kind": "school", "branch": 1, "pos": 6},
    {"suffix": "AWC", "name": "Anganwadi Centre", "kind": "anganwadi", "branch": 2, "pos": 12},
    {"suffix": "PHSC", "name": "Health Sub-Centre", "kind": "health", "branch": 0, "pos": 14},
]

USERS = [
    {"username": "naljal.mitra", "name": "Nal Jal Mitra (Operator)", "role": "operator", "scope_level": "village", "scope_id": "VLG-PW"},
    {"username": "jalsakhi.pimpalwadi", "name": "Jal Sakhi FTK team, Pimpalwadi", "role": "tester", "scope_level": "village", "scope_id": "VLG-PW"},
    {"username": "vwsc.pimpalwadi", "name": "VWSC / Pani Samiti, Pimpalwadi", "role": "vwsc", "scope_level": "village", "scope_id": "VLG-PW"},
    {"username": "je.mulshi", "name": "Junior Engineer, Mulshi Block", "role": "block", "scope_level": "block", "scope_id": "BK-MUL"},
    {"username": "ee.pune", "name": "Executive Engineer, Pune District", "role": "district", "scope_level": "district", "scope_id": "DT-PUN"},
    {"username": "state.mh", "name": "State JJM Cell, Maharashtra", "role": "state", "scope_level": "state", "scope_id": "ST-MH"},
    {"username": "demo.admin", "name": "Demo Administrator", "role": "admin", "scope_level": "state", "scope_id": "ST-MH"},
]

ASSIGNEES = {
    "operator": "Nal Jal Mitra (village operator)",
    "crew": "Block repair crew",
    "ftk": "Jal Sakhi FTK testing team",
    "je": "Junior Engineer (Block)",
    "device": "Device maintenance vendor",
}


# Who a household can turn to. Numbers are placeholders: a deployment loads the GP's own directory.
CONTACTS = [
    {"role": "operator", "name": "Nal Jal Mitra (operator)", "phone": "DEMO 90000 00001"},
    {"role": "vwsc", "name": "Pani Samiti chairperson", "phone": "DEMO 90000 00002"},
    {"role": "je", "name": "Junior Engineer, block office", "phone": "DEMO 90000 00003"},
    {"role": "helpline", "name": "State water helpline", "phone": "DEMO 1800 000 000"},
]


def village_by_id(vid: str) -> dict:
    for v in VILLAGES:
        if v["id"] == vid:
            return v
    raise KeyError(vid)


def block_by_id(bid: str) -> dict:
    return next(b for b in BLOCKS if b["id"] == bid)


def admin_path(village: dict) -> dict:
    blk = block_by_id(village["block_id"])
    dist = next(d for d in DISTRICTS if d["id"] == blk["parent_id"])
    return {"gp_id": f"GP-{village['code']}", "gp": f"{village['name']} GP", "block_id": blk["id"], "block": blk["name"],
            "district_id": dist["id"], "district": dist["name"], "state_id": STATE["id"], "state": STATE["name"]}


def external_ids(village: dict) -> dict:
    """Placeholder identifiers showing how internal IDs map to JJM platforms."""
    n = 500 + village["seed"]
    return {
        "lgd_village_code": f"DEMO-LGD-{560000 + n}",
        "imis_habitation_id": f"DEMO-IMIS-HAB-27{n:05d}",
        "imis_scheme_id": f"DEMO-IMIS-SCH-27{n:05d}",
        "sujal_gaon_id": f"DEMO-SG-27-{n:06d}",
        "sujalam_bharat_id": f"DEMO-SB-27-{n:06d}",
        "sujalam_infrastructure_id": f"DEMO-SBI-{n:06d}",
        "sujalam_service_area_id": f"DEMO-SBA-{n:06d}",
    }


def seed_history(village: dict, days: int = 30) -> list[dict]:
    """Deterministic 30-day daily service history (simulated; shapes analytics only)."""
    rnd = random.Random(village["seed"] * 31 + 7)
    q = village["quality"]
    rows = []
    day0 = C.SIM_START.date()
    bad_until = -1
    for d in range(days, 0, -1):
        day = day0 - timedelta(days=d)
        if d > bad_until and rnd.random() < (1 - q) * 0.55:
            bad_until = d - rnd.randint(0, 2)  # an outage that lingers a day or two
        hit = 0.14 + rnd.random() * 0.2 if d >= bad_until >= 0 and d - bad_until <= 2 else 0.0
        reg = max(0.3, min(1.0, q + 0.04 + rnd.uniform(-0.04, 0.03) - hit))
        qty = max(0.3, min(1.0, q + 0.01 + rnd.uniform(-0.05, 0.04) - hit * 0.8))
        qual = max(0.4, min(1.0, q + 0.05 + rnd.uniform(-0.05, 0.02) - (0.25 if rnd.random() < (1 - q) * 0.25 else 0)))
        func = max(0.2, min(reg, qty, qual) - rnd.uniform(0.0, 0.03))
        incidents = (1 if hit else 0) + (1 if rnd.random() < (1 - q) * 0.8 else 0)
        rows.append({
            "village_id": village["id"], "day": day.isoformat(),
            "functional_pct": round(func * 100, 1), "regularity_pct": round(reg * 100, 1),
            "quantity_pct": round(qty * 100, 1), "quality_pct": round(qual * 100, 1),
            "avg_lpcd": round(55 * (0.72 + 0.5 * qty) + rnd.uniform(-2, 2), 1),
            "supply_hours": round(6 * (0.55 + 0.45 * reg), 2),
            "incidents": incidents, "complaints": incidents * rnd.randint(1, 4) + (1 if rnd.random() < 0.2 else 0),
            "mttr_h": round(rnd.uniform(2, 9) / q, 1) if incidents else None,
            "nrw_pct": round(8 + (1 - q) * 45 + rnd.uniform(-2, 3), 1),
            "energy_kwh": round(village["tank_kl"] * 0.42 + rnd.uniform(-1.5, 2.5), 1),
            "gw_depth_m": round(village.get("gw_static", 28.0) - (village["ambient"].get("gw_decline", 0.008)) * d
                                + rnd.uniform(-0.04, 0.04), 2),
            "source": "simulated-history",
        })
    return rows


def seed_past_incidents(village: dict) -> list[dict]:
    """A few closed incidents per village so ageing / MTTR / recurrence charts have substance."""
    rnd = random.Random(village["seed"] * 17 + 3)
    kinds = [("LOW_PRESSURE", "pressure", "medium"), ("SUSPECTED_LEAK", "leak", "high"),
             ("SUPPLY_INTERRUPTION", "supply", "high"), ("QUALITY_VERIFY", "quality", "high"),
             ("SENSOR_OFFLINE", "sensor", "low"), ("PUMP_FAULT", "infrastructure", "critical")]
    out = []
    count = 2 + int((1 - village["quality"]) * 22)
    nb = len(village["branches"])
    for _ in range(count):
        typ, cat, sev = rnd.choice(kinds)
        ago = rnd.randint(1, 29)
        opened = C.SIM_START - timedelta(days=ago, hours=rnd.randint(0, 10))
        hours = rnd.uniform(1.5, 14) / village["quality"]
        b = rnd.randrange(nb) + 1 if typ not in ("PUMP_FAULT", "QUALITY_VERIFY") else None
        out.append({
            "village_id": village["id"], "type": typ, "category": cat, "severity": sev,
            "branch_id": f"{village['code']}-B{b}" if b else None,
            "first_seen": opened.isoformat(), "closed_at": (opened + timedelta(hours=hours)).isoformat(),
            "hours": round(hours, 1), "reports": rnd.randint(0, 5),
        })
    return out


def dumps(obj) -> str:
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)

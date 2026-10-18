"""Water testing by the village's Jal Sakhis: the field test kit, its verdict, and where to test first.

Jal Jeevan Mission trains five women in every village to test drinking water with a field test kit (FTK)
and hands the kits to the Panchayat. The kit reads nine parameters by colour against a printed chart:
pH, alkalinity, chloride, nitrate, total hardness, fluoride, iron, free residual chlorine and H2S (a vial
that turns black in 24 to 48 hours when faecal bacteria are likely). A failed result is confirmed in a
laboratory.

judge() scores a result against IS 10500:2012 (acceptable limit, and the permissible limit in the absence
of an alternate source). plan() ranks the village's sample points by contamination risk from what the
platform already sees, so the testers go first where water is most likely to be unsafe. Every part of the
score is listed with its reason; the weights are stated here, not learned, so they can be argued with.
"""
from __future__ import annotations

from datetime import datetime, timedelta

# key, label, unit, the colour-chart steps a kit reads, and the IS 10500:2012 limits
FTK_PARAMS = [
    {"key": "ph", "label": "pH", "unit": "", "steps": [5.5, 6.0, 6.5, 7.0, 7.5, 8.0, 8.5, 9.0], "min": 6.5, "max": 8.5},
    {"key": "alkalinity_mgl", "label": "Total alkalinity", "unit": "mg/L", "steps": [0, 100, 200, 300, 400, 600, 800], "acceptable": 200, "permissible": 600},
    {"key": "chloride_mgl", "label": "Chloride", "unit": "mg/L", "steps": [0, 100, 250, 500, 1000, 1500], "acceptable": 250, "permissible": 1000},
    {"key": "hardness_mgl", "label": "Total hardness", "unit": "mg/L", "steps": [0, 100, 200, 300, 400, 600, 800], "acceptable": 200, "permissible": 600},
    {"key": "nitrate_mgl", "label": "Nitrate", "unit": "mg/L", "steps": [0, 10, 20, 45, 100], "acceptable": 45, "permissible": 45},
    {"key": "fluoride_mgl", "label": "Fluoride", "unit": "mg/L", "steps": [0, 0.5, 1.0, 1.5, 2.0, 3.0], "acceptable": 1.0, "permissible": 1.5},
    {"key": "iron_mgl", "label": "Iron", "unit": "mg/L", "steps": [0, 0.1, 0.3, 0.5, 1.0, 2.0], "acceptable": 0.3, "permissible": 0.3},
    {"key": "chlorine_mgl", "label": "Free residual chlorine", "unit": "mg/L", "steps": [0, 0.1, 0.2, 0.5, 1.0, 2.0], "min": 0.2},
]
FTK_KEYS = [p["key"] for p in FTK_PARAMS] + ["h2s_positive"]
# parameters a laboratory or an online sensor may add (the kit does not read these)
EXTRA_LIMITS = {"turbidity_ntu": ("Turbidity", "NTU", 1.0, 5.0), "tds_mgl": ("TDS", "mg/L", 500, 2000),
                "arsenic_mgl": ("Arsenic", "mg/L", 0.01, 0.01)}


def judge(params: dict) -> tuple[str, list[str], list[dict]]:
    """('pass' | 'fail' | 'pending', failed checks, one row per parameter with ok / caution / fail / pending)."""
    rows, fails = [], []

    def add(key, label, value, status, note):
        rows.append({"key": key, "label": label, "value": value, "status": status, "note": note})
        if status == "fail":
            fails.append(note)

    for p in FTK_PARAMS:
        v = params.get(p["key"])
        if v is None:
            continue
        unit = f" {p['unit']}" if p["unit"] else ""
        if "max" in p:  # pH: a range, no relaxation
            ok = p["min"] <= v <= p["max"]
            add(p["key"], p["label"], v, "ok" if ok else "fail", f"{p['label']} {v} {'within' if ok else 'outside'} {p['min']} to {p['max']}")
        elif "min" in p and "acceptable" not in p:  # free residual chlorine: a floor
            ok = v >= p["min"]
            add(p["key"], p["label"], v, "ok" if ok else "fail",
                f"residual chlorine {v}{unit} {'at or above' if ok else 'below'} {p['min']}{unit}")
        elif v > p["permissible"]:
            add(p["key"], p["label"], v, "fail", f"{p['label'].lower()} {v}{unit} above {p['permissible']}{unit}")
        elif v > p["acceptable"]:
            add(p["key"], p["label"], v, "caution", f"{p['label'].lower()} {v}{unit} above the acceptable {p['acceptable']}{unit}, within the permissible limit")
        else:
            add(p["key"], p["label"], v, "ok", f"{p['label'].lower()} {v}{unit} within limits")
    for key, (label, unit, acceptable, permissible) in EXTRA_LIMITS.items():
        v = params.get(key)
        if v is None:
            continue
        st = "fail" if v > permissible else "caution" if v > acceptable else "ok"
        add(key, label, v, st, f"{label.lower()} {v} {unit} {'above ' + str(permissible) + ' ' + unit if st == 'fail' else 'within limits' if st == 'ok' else 'above the acceptable ' + str(acceptable) + ' ' + unit}")
    if params.get("e_coli_present") or params.get("total_coliform_present"):
        add("coliform", "Coliform bacteria", True, "fail", "coliform bacteria detected (must be absent)")
    if "h2s_positive" in params:
        h = params["h2s_positive"]
        if h is None:
            add("h2s_positive", "H2S vial", None, "pending", "H2S vial set up: result in 24 to 48 hours")
        else:
            add("h2s_positive", "H2S vial", bool(h), "fail" if h else "ok",
                "H2S vial positive (possible bacteriological contamination)" if h else "H2S vial negative")
    pending = any(r["status"] == "pending" for r in rows)
    return ("fail" if fails else "pending" if pending else "pass"), fails, rows


# What a failure means for the household. Germs: boil the water. Chemicals boiling cannot remove (it concentrates
# them): drink from another safe source. Everything else (iron, hardness, pH ...) is not an immediate health risk:
# it is the operator's job, with no household advisory.
MICROBIAL = {"h2s_positive", "coliform", "chlorine_mgl"}
CHEMICAL = {"fluoride_mgl", "nitrate_mgl", "arsenic_mgl"}


def advisory_for(checks: list[dict]) -> str | None:
    failed = {c["key"] for c in checks if c["status"] == "fail"}
    if failed & MICROBIAL:
        return "boil"
    if failed & CHEMICAL:
        return "alternate_source"
    return None


def sample_points(sim) -> list[dict]:
    """Where a tester can draw water: the tank outlet, and the last tap on each lane (the worst-served water)."""
    return [{"name": "Tank outlet", "scope": "scheme", "branch_id": None, "lane": None}] + [
        {"name": f"{lane} tail-end tap", "scope": "branch", "branch_id": sim.branch_ids[b], "lane": lane} for b, lane in enumerate(sim.branch_names)]


def point_branch(sim, sample_point: str) -> str | None:
    """The lane a sample point belongs to, from its name; None for the tank or anything unrecognised."""
    for b, lane in enumerate(sim.branch_names):
        if sample_point.startswith(lane):
            return sim.branch_ids[b]
    return None


def plan(p, vid: str) -> dict:
    """Sample points ranked by contamination risk, each with the reasons behind its score."""
    sim, mon = p.sims[vid], p.monitors[vid]
    now = p.now
    q = {x["id"].rsplit("-", 1)[-1]: x for x in mon.quality}
    wq1, wq2 = q.get("WQ1") or {}, q.get("WQ2") or {}
    cl_tank = wq1.get("chlorine_mgl") if wq1.get("fresh") else None
    turb = wq1.get("turbidity_ntu") if wq1.get("fresh") else None
    since48 = (now - timedelta(hours=48)).isoformat(timespec="seconds")
    since72 = (now - timedelta(hours=72)).isoformat(timespec="seconds")
    recent = [i for i in p.incidents.items.values() if i["village_id"] == vid] + p.db.query(
        "SELECT * FROM incidents WHERE village_id=? AND status='closed' AND is_seed=0 AND closed_at>=?", (vid, since48))
    reports: dict[str, int] = {}
    for r in p.db.query("SELECT branch_id, COUNT(DISTINCT household_id) n FROM complaints WHERE village_id=? AND created_at>=?"
                        " AND category IN ('dirty_water','smell_taste') GROUP BY branch_id", (vid, since72)):
        reports[r["branch_id"]] = r["n"]
    last_test = {r["sample_point"]: r["ts"] for r in p.db.query(
        "SELECT sample_point, MAX(ts) ts FROM wq_tests WHERE village_id=? GROUP BY sample_point", (vid,))}
    sites = p.institutions.get(vid, [])
    out = []
    for sp in sample_points(sim):
        parts, reasons, focus = {}, [], []
        bid = sp["branch_id"]

        def give(part, pts, code, **kw):
            parts[part] = round(parts.get(part, 0) + pts, 1)
            reasons.append({"code": code, "points": round(pts), **kw})

        open_quality = [i for i in recent if i["status"] != "closed" and i["category"] == "quality"
                        and (i["scope_type"] == "scheme" or i["branch_id"] == bid)]
        if open_quality:
            give("quality_alert", 30, "alert", incident=open_quality[0]["id"])
            focus += ["h2s_positive", "chlorine_mgl"]
        if bid:
            lane = [i for i in recent if i["branch_id"] == bid]
            if any(i["type"] == "SUSPECTED_LEAK" for i in lane):  # a break in a main that stands empty between supplies
                give("pipe_break", 30, "leak")
                focus += ["h2s_positive", "chlorine_mgl"]
            if any(i["type"] in ("LOW_PRESSURE", "SUPPLY_INTERRUPTION", "ABNORMAL_PATTERN") for i in lane):
                give("low_pressure", 15, "pressure")
                focus += ["h2s_positive"]
            measured = bid == sim.branch_ids[mon.wq2_branch] and wq2.get("fresh")
            cl_tail = wq2.get("chlorine_mgl") if measured else (round(cl_tank * 0.7, 2) if cl_tank is not None else None)
            if cl_tail is not None and cl_tail < 0.3:  # residual decays along the lane; below 0.2 disinfection cannot be assumed
                give("low_chlorine", min(25.0, (0.3 - cl_tail) / 0.2 * 20 + (5 if cl_tail < 0.2 else 0)), "chlorine",
                     v=cl_tail, basis="measured" if measured else "estimated")
                focus += ["chlorine_mgl"]
            if reports.get(bid):
                give("reports", min(20, 7 * reports[bid]), "reports", n=reports[bid])
                focus += ["h2s_positive"]
            here = [s["name"] for s in sites if s["branch_id"] == bid]
            if here:
                give("sensitive_sites", 5 * len(here), "sites", s=", ".join(here))
            give("intermittent", 5, "intermittent")
        else:
            if turb is not None and turb > 1.0:
                give("turbidity", min(25.0, (turb - 1.0) * 6), "turbidity", v=round(turb, 1))
            if cl_tank is not None and cl_tank < 0.2:
                give("low_chlorine", 25, "chlorine", v=round(cl_tank, 2), basis="measured")
                focus += ["chlorine_mgl"]
        last = last_test.get(sp["name"])
        if last is None:
            give("routine", 12, "never")
        else:
            days = (now - datetime.fromisoformat(last)).total_seconds() / 86400
            if days >= 1:
                give("routine", min(15.0, days * 2), "stale", n=int(days))
        score = min(100.0, sum(parts.values()))
        out.append({**sp, "score": round(score), "parts": parts, "reasons": sorted(reasons, key=lambda r: -r["points"]),
                    "focus": list(dict.fromkeys(focus)) or FTK_KEYS, "last_tested": last})
    out.sort(key=lambda r: -r["score"])
    for i, r in enumerate(out):
        r["today"] = i < 3 and r["score"] >= 20
    return {"village_id": vid, "village": sim.name, "generated_at": now.isoformat(timespec="seconds"), "points": out,
            "params": FTK_PARAMS, "method": "Stated weights, not learned: open quality alert 30, leak on the lane 30, low "
            "pressure or supply cut 15, low chlorine up to 25, dirty-water reports up to 20, school / anganwadi / health "
            "centre 5 each, intermittent supply 5, routine up to 15 by days since the last test. The top three with 20 or "
            "more points are today's list."}


def demo_reading(p, vid: str, point: str, rnd) -> dict:
    """DEMO: what a kit would show for water drawn at `point` now, read off the simulated scheme and snapped to chart steps."""
    sim = p.sims[vid]
    bid = point_branch(sim, point)
    b = sim.branch_ids.index(bid) if bid else None
    broken = b is not None and b in sim.faults.leak
    dirty = sim.turb > 4 or not p._cit[vid].get("cluster_fixed", True)
    cl = sim.cl * (0.7 if b is not None else 1.0) * (0.35 if broken or dirty else 1.0)

    def snap(key, v):
        steps = next(x["steps"] for x in FTK_PARAMS if x["key"] == key)
        return min(steps, key=lambda s: abs(s - v))

    return {"ph": snap("ph", 7.3 + rnd.uniform(-0.3, 0.3)), "alkalinity_mgl": snap("alkalinity_mgl", 180 + rnd.uniform(-40, 40)),
            "chloride_mgl": snap("chloride_mgl", 120 + rnd.uniform(-30, 60)), "hardness_mgl": snap("hardness_mgl", 210 + rnd.uniform(-60, 60)),
            "nitrate_mgl": snap("nitrate_mgl", 12 + rnd.uniform(-5, 8)), "fluoride_mgl": snap("fluoride_mgl", 0.5 + rnd.uniform(-0.2, 0.3)),
            "iron_mgl": snap("iron_mgl", 0.1 + (0.4 if broken else 0) + rnd.uniform(-0.05, 0.05)), "chlorine_mgl": snap("chlorine_mgl", cl),
            "h2s_positive": bool(broken or dirty)}


# What to do about a parameter that fails (or is above the acceptable level). Cautious by design: it says what
# is likely and what to check; the laboratory result and the engineer decide.
ADVICE = {
    "chlorine_mgl": ("Residual chlorine too low: disinfection cannot be assumed", [
        "Check the chlorinator is working and the dosing stock is not finished.",
        "Restore dosing so a tail-end tap reads 0.2 to 0.5 mg/L, then re-test free residual chlorine about 30 minutes later.",
        "Until it reads 0.2 mg/L or more, households should boil drinking water."]),
    "h2s_positive": ("H2S vial turned black: possible faecal contamination", [
        "Households on this supply should boil drinking water until a laboratory clears it.",
        "Send a sample for a laboratory bacteriological test (E. coli / total coliform).",
        "Look for where dirt gets in: leaks, low-pressure areas, a damaged tap or an open tank lid; shock-chlorinate the tank and flush the line.",
        "Re-test with a new H2S vial after the fix."]),
    "iron_mgl": ("Iron above the limit", [
        "Often from rusting GI pipes or fittings, or from the source rock; it stains, tastes metallic and makes chlorine work less well.",
        "Flush the line from the tail end, check old GI pipes on this lane, and re-test after flushing.",
        "If it stays high, ask for a laboratory test of the source and plan aeration and filtration at the source."]),
    "fluoride_mgl": ("Fluoride above 1.5 mg/L", [
        "Long-term drinking causes dental and skeletal fluorosis; children are most at risk.",
        "Confirm in the laboratory, then arrange a safe drinking source (another source, blending, or a community defluoridation unit).",
        "Boiling does not remove fluoride."]),
    "nitrate_mgl": ("Nitrate above 45 mg/L", [
        "Usually sewage, soak pits or fertiliser reaching the source; dangerous for infants under six months.",
        "Check the source's surroundings, confirm in the laboratory, and give infants water from another safe source.",
        "Boiling does not remove nitrate."]),
    "ph": ("pH outside 6.5 to 8.5", [
        "Check the source and any dosing; very low pH corrodes pipes, very high pH weakens chlorination.",
        "Confirm in the laboratory before changing treatment."]),
    "hardness_mgl": ("Total hardness high", [
        "Mostly a scaling and taste problem; above 600 mg/L consider blending with a softer source.",
        "Note it on the source record and re-test monthly."]),
    "alkalinity_mgl": ("Alkalinity high", ["Usually from the source rock; it affects taste and treatment. Confirm in the laboratory and re-test monthly."]),
    "chloride_mgl": ("Chloride high", ["A salty taste; a sudden rise can mean sewage or saline intrusion. Check the source's surroundings and confirm in the laboratory."]),
    "turbidity_ntu": ("Water is cloudy", ["Check the source, the tank and for pipe breaks, and flush the line. Cloudy water also shields germs from chlorine."]),
    "tds_mgl": ("Dissolved solids high", ["From the source; confirm in the laboratory and consider blending with a better source."]),
    "coliform": ("Bacteria found", ["The boil-water advisory stays until a laboratory re-test is clear; disinfect the tank and lines and find where dirt gets in."]),
}


def advice(checks: list[dict]) -> list[dict]:
    """Guidance for every parameter that failed, then any above its acceptable level."""
    out = []
    for status in ("fail", "caution"):
        for c in checks:
            if c["status"] == status and c["key"] in ADVICE:
                title, steps = ADVICE[c["key"]]
                out.append({"key": c["key"], "status": status,
                            "title": title if status == "fail" else f"{title} (above the acceptable level, within the permissible limit)",
                            "steps": steps if status == "fail" else steps[-1:]})
    return out

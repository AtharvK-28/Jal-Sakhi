"""KPIs, multi-level roll-ups, analytics, the spoken situation brief and the Jal Seva Aankalan draft."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime

import numpy as np

from .. import config as C
from .. import seed as S
from .monitor import DRY, LOW, OK, UNKNOWN
from .om import nice

LEVELS = ["state", "district", "block", "village"]


# ------------------------------------------------------------------ helpers
def _memo(p, name: str, build):
    cache = p.__dict__.setdefault("_memo", {})
    hit = cache.get(name)
    if hit and hit[0] == p.version:
        return hit[1]
    value = build()
    cache[name] = (p.version, value)
    return value


def _open_complaints(p) -> dict:
    return _memo(p, "open_complaints", lambda: {r["village_id"]: r["n"] for r in p.db.query(
        "SELECT village_id, COUNT(*) n FROM complaints WHERE status!='closed' GROUP BY village_id")})


def villages_under(level: str, unit_id: str) -> list[dict]:
    if level == "village":
        return [S.village_by_id(unit_id)]
    if level == "block":
        return [v for v in S.VILLAGES if v["block_id"] == unit_id]
    if level == "district":
        blocks = {b["id"] for b in S.BLOCKS if b["parent_id"] == unit_id}
        return [v for v in S.VILLAGES if v["block_id"] in blocks]
    return list(S.VILLAGES)


def scope_villages(user: dict) -> set[str]:
    """Village IDs a staff user may see, from their role scope."""
    return {v["id"] for v in villages_under(user.get("scope_level", "state"), user.get("scope_id", "ST-MH"))}


# --------------------------------------------------------------- village KPIs
def village_kpis(p, vid: str) -> dict:
    sim, mon = p.sims[vid], p.monitors[vid]
    n = sim.n
    counts = mon.counts()
    flags = mon.day_flags()
    hist = p.history.get(vid) or []
    last = hist[-1] if hist else {}
    if flags is not None:
        functional = {"pct": round(float(flags["functional"].mean()) * 100, 1), "n": int(flags["functional"].sum()), "of": n,
                      "regular_pct": round(float(flags["regular"].mean()) * 100, 1),
                      "quantity_pct": round(float(flags["quantity"].mean()) * 100, 1),
                      "quality_pct": round(float(flags["quality"].mean()) * 100, 1),
                      "unknown": int((~flags["known"]).sum()), "windows": flags["windows"], "basis": "today"}
    elif last:
        functional = {"pct": last["functional_pct"], "n": round(last["functional_pct"] * n / 100), "of": n,
                      "regular_pct": last["regularity_pct"], "quantity_pct": last["quantity_pct"],
                      "quality_pct": last["quality_pct"], "unknown": 0, "windows": 0, "basis": "previous day"}
    else:
        functional = None
    open_inc = [i for i in p.incidents.items.values() if i["village_id"] == vid]
    T = p.telemetry
    online = sum(1 for d in mon.device_ids if T.status(d) == "online")
    q_status = "ok"
    for q in mon.quality:
        if q["status"] in ("verify", "unknown") or (q["status"] == "watch" and q_status == "ok"):
            q_status = q["status"] if q_status != "verify" else q_status
    quality_open = [i for i in open_inc if i["category"] == "quality" or (i["type"] == "COMMUNITY_CLUSTER" and "quality" in i["cond_key"])]
    if quality_open:
        q_status = "verify"
    in_win = p.clock.in_window
    if in_win:
        s_now = (counts["ok"] + 0.5 * counts["low"] + 0.4 * counts["unknown"]) / n
    elif flags is not None:
        s_now = float(np.mean([mon.served[w] for w in range(len(C.SUPPLY_WINDOWS)) if mon.served[w] is not None]))
    else:
        s_now = last.get("regularity_pct", 100) / 100
    qty = functional["quantity_pct"] / 100 if functional else 1.0
    w_q = {"ok": 1.0, "watch": 0.75, "verify": 0.3, "unknown": 0.6}[q_status]
    data = online / max(1, len(mon.device_ids))
    score = round(100 * (0.45 * s_now + 0.25 * qty + 0.20 * w_q + 0.10 * data), 1)
    agree = mon.truth_agree
    return {
        "households": n, "counts": counts, "in_window": in_win,
        "receiving_pct": round(100 * counts["ok"] / n, 1) if in_win else None,
        "functional": functional, "lpcd_avg": round(float((mon.vol / mon.members).mean()), 1),
        "lpcd_norm": C.LPCD_NORM, "supply_min": round(mon.supply_min), "sched_min": round(mon.sched_min),
        "open_incidents": len(open_inc), "critical": sum(1 for i in open_inc if i["severity"] == "critical"),
        "high": sum(1 for i in open_inc if i["severity"] == "high"),
        "complaints_open": _open_complaints(p).get(vid, 0), "devices_online_pct": round(100 * data, 1),
        "devices_total": len(mon.device_ids), "devices_problem": len(mon.device_ids) - online,
        "quality_status": q_status, "score": score,
        "score_parts": {"supply": round(s_now * 100), "quantity": round(qty * 100), "quality": round(w_q * 100), "data": round(data * 100)},
        "estimator_agreement_pct": round(100 * agree[0] / agree[1], 1) if agree[1] else None,
        "estimator_samples": agree[1], "pulse": getattr(mon, "pulse", None),
    }


def village_summary(p, vid: str) -> dict:
    def build():
        sim, mon = p.sims[vid], p.monitors[vid]
        v = S.village_by_id(vid)
        k = village_kpis(p, vid)
        path = S.admin_path(v)
        worst = max((i["severity"] for i in p.incidents.items.values() if i["village_id"] == vid),
                    key=lambda s: C.SEVERITY_RANK[s], default=None)
        return {"id": vid, "code": sim.code, "name": sim.name, "gp": path["gp"], "block_id": path["block_id"],
                "block": path["block"], "district_id": path["district_id"], "district": path["district"],
                "lat": v["lat"], "lon": v["lon"], "households": sim.n, "score": k["score"], "counts": k["counts"],
                "open": k["open_incidents"], "critical": k["critical"], "worst": worst,
                "tank_pct": mon.tank.get("level_pct"), "pump_on": mon.pump.get("on"), "quality": k["quality_status"],
                "functional_pct": k["functional"]["pct"] if k["functional"] else None, "lpcd": k["lpcd_avg"],
                "complaints_open": k["complaints_open"], "devices_problem": k["devices_problem"],
                "ext": S.external_ids(v), "om": p.om.summary(vid)}
    return _memo(p, f"summary:{vid}", build)


# ------------------------------------------------------------------ roll-ups
def _aggregate(p, vids: list[str]) -> dict:
    rows = [village_summary(p, v) for v in vids]
    hh = sum(r["households"] for r in rows) or 1
    counts = Counter()
    for r in rows:
        counts.update(r["counts"])
    fn = [(r["functional_pct"], r["households"]) for r in rows if r["functional_pct"] is not None]
    return {"villages": len(rows), "households": hh, "score": round(sum(r["score"] * r["households"] for r in rows) / hh, 1),
            "functional_pct": round(sum(a * b for a, b in fn) / sum(b for _a, b in fn), 1) if fn else None,
            "lpcd": round(sum(r["lpcd"] * r["households"] for r in rows) / hh, 1), "counts": dict(counts),
            "open": sum(r["open"] for r in rows), "critical": sum(r["critical"] for r in rows),
            "complaints_open": sum(r["complaints_open"] for r in rows),
            "devices_problem": sum(r["devices_problem"] for r in rows),
            "quality_flags": sum(1 for r in rows if r["quality"] == "verify")}


def overview(p, level: str, unit_id: str) -> dict:
    with p.lock:
        vs = villages_under(level, unit_id)
        vids = [v["id"] for v in vs]
        if level == "state":
            children = [{"level": "district", **d, **_aggregate(p, [v["id"] for v in villages_under("district", d["id"])])} for d in S.DISTRICTS]
            name = S.STATE["name"]
        elif level == "district":
            children = [{"level": "block", **b, **_aggregate(p, [v["id"] for v in villages_under("block", b["id"])])}
                        for b in S.BLOCKS if b["parent_id"] == unit_id]
            name = next(d["name"] for d in S.DISTRICTS if d["id"] == unit_id)
        elif level == "block":
            children = [{"level": "village", "id": v["id"], "name": v["name"], "lat": v["lat"], "lon": v["lon"],
                         **_aggregate(p, [v["id"]])} for v in vs]
            name = S.block_by_id(unit_id)["name"]
        else:
            children, name = [], vs[0]["name"]
        return {"level": level, "id": unit_id, "name": name, "totals": _aggregate(p, vids), "children": children,
                "villages": [village_summary(p, v) for v in vids], "trend": history(p, vids),
                "incidents": [i for i in p.incidents.open_list(set(vids))][:12]}


def hierarchy(p) -> dict:
    with p.lock:
        tree = {"id": S.STATE["id"], "level": "state", "name": S.STATE["name"], "children": []}
        for d in S.DISTRICTS:
            dn = {"id": d["id"], "level": "district", "name": d["name"], "children": []}
            for b in (b for b in S.BLOCKS if b["parent_id"] == d["id"]):
                dn["children"].append({"id": b["id"], "level": "block", "name": b["name"], "children": [
                    {"id": v["id"], "level": "village", "name": v["name"], "households": sum(v["branches"])}
                    for v in S.VILLAGES if v["block_id"] == b["id"]]})
            tree["children"].append(dn)
        return tree


def history(p, vids: list[str]) -> list[dict]:
    """Household-weighted daily history across the given villages."""
    by_day = defaultdict(list)
    for vid in vids:
        n = p.sims[vid].n
        for r in p.history.get(vid, []):
            by_day[r["day"]].append((r, n))
    out = []
    for day in sorted(by_day):
        rows = by_day[day]
        tot = sum(n for _r, n in rows)

        def w(key):
            vals = [(r[key], n) for r, n in rows if r.get(key) is not None]
            return round(sum(a * b for a, b in vals) / sum(b for _a, b in vals), 1) if vals else None

        out.append({"day": day, "functional_pct": w("functional_pct"), "regularity_pct": w("regularity_pct"),
                    "quantity_pct": w("quantity_pct"), "quality_pct": w("quality_pct"), "avg_lpcd": w("avg_lpcd"),
                    "supply_hours": w("supply_hours"), "nrw_pct": w("nrw_pct"),
                    "incidents": sum(r["incidents"] or 0 for r, _n in rows), "complaints": sum(r["complaints"] or 0 for r, _n in rows),
                    "households": tot, "live": any(r["source"] == "simulation-live" for r, _n in rows)})
    return out


# ----------------------------------------------------------------- analytics
def analytics(p, vids: list[str]) -> dict:
    with p.lock:
        marks = ",".join("?" for _ in vids)
        inc = p.db.query(f"SELECT id, village_id, type, category, severity, status, branch_id, first_seen, acknowledged_at,"
                         f" closed_at, sla_ack_due, sla_resolve_due, is_seed, evidence, report_count, detection_delay_min, origin"
                         f" FROM incidents WHERE village_id IN ({marks})", tuple(vids))
        now = p.now
        by_type, by_branch, mttr = Counter(), Counter(), defaultdict(list)
        ack_ok = ack_n = res_ok = res_n = 0
        recur = Counter()
        for i in inc:
            live = p.incidents.items.get(i["id"], i)
            by_type[live["type"]] += 1
            if live["branch_id"]:
                by_branch[live["branch_id"]] += 1
                recur[(live["branch_id"], live["type"])] += 1
            if i["is_seed"]:
                mttr[live["type"]].append((i["evidence"] or {}).get("hours", 0))
                continue
            if live["closed_at"]:
                hrs = (datetime.fromisoformat(live["closed_at"]) - datetime.fromisoformat(live["first_seen"])).total_seconds() / 3600
                mttr[live["type"]].append(hrs)
                res_n += 1
                res_ok += live["closed_at"] <= live["sla_resolve_due"]
            if live["acknowledged_at"]:
                ack_n += 1
                ack_ok += live["acknowledged_at"] <= live["sla_ack_due"]
            elif live["status"] == "open" and now.isoformat() > live["sla_ack_due"]:
                ack_n += 1
        ageing = {"under_1h": 0, "1_to_4h": 0, "4_to_24h": 0, "over_24h": 0}
        cats = Counter()
        channels = Counter()
        for c in p.db.query(f"SELECT category, created_at, status, channel FROM complaints WHERE village_id IN ({marks})", tuple(vids)):
            cats[c["category"]] += 1
            channels[c["channel"]] += 1
            if c["status"] != "closed":
                h = (now - datetime.fromisoformat(c["created_at"])).total_seconds() / 3600
                ageing["under_1h" if h < 1 else "1_to_4h" if h < 4 else "4_to_24h" if h < 24 else "over_24h"] += 1
        delays = [d for d in p.metrics["detections"] if d["village_id"] in vids]
        agree = [p.monitors[v].truth_agree for v in vids]
        tot = sum(a[1] for a in agree)
        pulse = p.db.one(f"SELECT COUNT(*) n, SUM(got_water) yes, SUM(CASE WHEN inferred IS NOT NULL THEN 1 ELSE 0 END) cmp,"
                         f" SUM(CASE WHEN inferred = got_water THEN 1 ELSE 0 END) agree FROM pulse WHERE village_id IN ({marks})", tuple(vids))
        return {
            "trend": history(p, vids),
            "incidents_by_type": [{"type": t, "n": n} for t, n in by_type.most_common()],
            "incidents_by_branch": [{"branch": b, "n": n} for b, n in by_branch.most_common(10)],
            "mttr_hours": [{"type": t, "hours": round(float(np.mean(v)), 1), "n": len(v)} for t, v in sorted(mttr.items())],
            "recurring": [{"branch": b, "type": t, "n": n} for (b, t), n in recur.most_common(6) if n >= 2],
            "sla": {"ack_within_pct": round(100 * ack_ok / ack_n, 1) if ack_n else None, "ack_n": ack_n,
                    "resolve_within_pct": round(100 * res_ok / res_n, 1) if res_n else None, "resolve_n": res_n},
            "complaint_ageing": ageing, "complaints_by_category": [{"category": c, "n": n} for c, n in cats.most_common()],
            "complaints_by_channel": [{"channel": c, "n": n} for c, n in channels.most_common()],
            "detection_delays": delays[-30:],
            "median_detection_delay_min": float(np.median([d["delay_min"] for d in delays])) if delays else None,
            "scenario_log": p.scenario_log[-20:],
            "estimator": {"agreement_pct": round(100 * sum(a[0] for a in agree) / tot, 1) if tot else None, "samples": tot,
                          "note": "Inferred status of un-instrumented households vs simulator ground truth. Only measurable in simulation."},
            "pulse": {"responses": pulse["n"] or 0, "got_water_pct": round(100 * (pulse["yes"] or 0) / pulse["n"], 1) if pulse["n"] else None,
                      "agreement_pct": round(100 * (pulse["agree"] or 0) / pulse["cmp"], 1) if pulse["cmp"] else None},
            "ranking": sorted([village_summary(p, v) for v in vids], key=lambda r: -r["score"]),
        }


# ---------------------------------------------------------------- AI insights
def insights(p, vid: str) -> dict:
    with p.lock:
        mon = p.monitors[vid]
        branches = []
        for b, br in enumerate(mon.branch):
            f = br.get("feats") or {}
            branches.append({"id": br.get("id"), "name": br.get("name"), "anomaly": round(float(mon.anom_s[b]), 2),
                             "score_now": round(br.get("score", 0.0), 2), "z_r": round(f.get("z_r", 0.0), 1),
                             "z_q": round(f.get("z_q", 0.0), 1), "flow": br.get("flow"),
                             "exp_flow": round(f["exp_q"], 1) if f else None,
                             "residual_bar": round(f["r"], 3) if f and f.get("r") is not None else None,
                             "evidence": round(float(mon.trackers[b].cusum), 1) if p.clock.in_window else 0.0,
                             "p_leak": None if mon.p_leak[b] is None else round(float(mon.p_leak[b]), 2),
                             "location": mon.loc[b],
                             "nrw_est_pct": round(max(0.0, (br["flow"] - f["exp_q"]) / br["flow"] * 100), 1)
                             if f and br.get("flow") and br["flow"] > 5 and f["z_q"] > 1.2 and f["z_r"] > 3 else 0.0,
                             "curve": p.models.curves.get(br.get("id"))})
        queue = []
        for i in sorted((i for i in p.incidents.items.values() if i["village_id"] == vid), key=lambda i: -i["priority"]):
            queue.append({"id": i["id"], "title": i["title"], "type": i["type"], "severity": i["severity"], "status": i["status"],
                          "priority": i["priority"], "breakdown": i["priority_breakdown"], "affected": i["affected_count"],
                          "reports": i["report_count"], "action": i["suggested_action"], "origin": i["origin"]})
        k = village_kpis(p, vid)
        return {"village_id": vid, "branches": branches, "pump": mon.pump, "forecast": mon.forecast, "source": mon.source,
                "tank": mon.tank, "priority_queue": queue,
                "estimator": {"agreement_pct": k["estimator_agreement_pct"], "samples": k["estimator_samples"],
                              "instrumented": int(mon.instrumented.sum()), "households": mon.n,
                              "confidence_avg": round(float(mon.conf.mean()), 2) if p.clock.in_window else None},
                "balance": mon.water_balance(),
                "thresholds": {"anomaly_score": C.ANOMALY_SCORE, "pump_risk": C.PUMP_RISK_ALERT, "persist": C.PERSIST,
                               "alarm_level": p.models.det["h"]}}


# ---------------------------------------------------------- situation brief
_BRIEF = {
    "en": {
        "open": "{name}, {time}. ", "supply_on": "{label} supply is on. {ok} of {n} households are receiving water",
        "low": ", {low} have low pressure", "dry": ", {dry} have no water", "unknown": ", {unknown} cannot be confirmed",
        "supply_off": "Supply is off as scheduled. Next supply at {next}. ",
        "tank": "Tank is at {tank} percent{pump}. ", "pump_on": " and the pump is running", "pump_off": "",
        "none": "No open incidents. ", "incidents": "{k} open incidents. Top priority: {title}. ",
        "quality_ok": "Water quality sensors are within reference limits. ",
        "quality_verify": "Water quality needs verification. An F T K test is required. ",
        "complaints": "{c} citizen reports are open. ", "functional": "{pct} percent of tap connections are functional today. ",
    },
    "hi": {
        "open": "{name}, समय {time}. ", "supply_on": "{label} की जल आपूर्ति चालू है। {n} में से {ok} घरों को पानी मिल रहा है",
        "low": ", {low} घरों में दबाव कम है", "dry": ", {dry} घरों में पानी नहीं है", "unknown": ", {unknown} घरों की स्थिति अज्ञात है",
        "supply_off": "निर्धारित समय के अनुसार आपूर्ति बंद है। अगली आपूर्ति {next} बजे। ",
        "tank": "टंकी {tank} प्रतिशत भरी है{pump}। ", "pump_on": " और पंप चालू है", "pump_off": "",
        "none": "कोई खुली शिकायत या घटना नहीं है। ", "incidents": "{k} घटनाएँ खुली हैं। सबसे ज़रूरी: {title}। ",
        "quality_ok": "पानी की गुणवत्ता के सेंसर सामान्य सीमा में हैं। ",
        "quality_verify": "पानी की गुणवत्ता की जाँच ज़रूरी है। एफ़ टी के परीक्षण करें। ",
        "complaints": "{c} नागरिक शिकायतें खुली हैं। ", "functional": "आज {pct} प्रतिशत नल कनेक्शन कार्यशील हैं। ",
    },
    "mr": {
        "open": "{name}, वेळ {time}. ", "supply_on": "{label} पाणीपुरवठा सुरू आहे. {n} पैकी {ok} घरांना पाणी मिळत आहे",
        "low": ", {low} घरांमध्ये दाब कमी आहे", "dry": ", {dry} घरांमध्ये पाणी नाही", "unknown": ", {unknown} घरांची स्थिती अज्ञात आहे",
        "supply_off": "वेळापत्रकानुसार पुरवठा बंद आहे. पुढील पुरवठा {next} वाजता. ",
        "tank": "टाकी {tank} टक्के भरली आहे{pump}. ", "pump_on": " आणि पंप सुरू आहे", "pump_off": "",
        "none": "कोणतीही उघडी घटना नाही. ", "incidents": "{k} घटना उघड्या आहेत. सर्वात महत्त्वाची: {title}. ",
        "quality_ok": "पाण्याच्या गुणवत्तेचे सेन्सर सामान्य मर्यादेत आहेत. ",
        "quality_verify": "पाण्याच्या गुणवत्तेची तपासणी आवश्यक आहे. एफ टी के चाचणी करा. ",
        "complaints": "{c} नागरिक तक्रारी उघड्या आहेत. ", "functional": "आज {pct} टक्के नळ जोडण्या कार्यरत आहेत. ",
    },
}
_WINDOW_LABEL = {"en": {"Morning": "Morning", "Evening": "Evening"}, "hi": {"Morning": "सुबह", "Evening": "शाम"},
                 "mr": {"Morning": "सकाळचा", "Evening": "संध्याकाळचा"}}


def brief(p, vid: str, lang: str = "en") -> dict:
    """A short spoken-style status summary built from live state (template NLG, no LLM)."""
    with p.lock:
        t = _BRIEF.get(lang, _BRIEF["en"])
        lang = lang if lang in _BRIEF else "en"
        sim, mon = p.sims[vid], p.monitors[vid]
        k = village_kpis(p, vid)
        clk = p.clock_state()
        c = k["counts"]
        text = t["open"].format(name=sim.name, time=clk["time"])
        if clk["in_window"]:
            text += t["supply_on"].format(label=_WINDOW_LABEL[lang][clk["window_label"]], ok=c["ok"], n=sim.n)
            for key in ("low", "dry", "unknown"):
                if c[key]:
                    text += t[key].format(**c)
            text += "। " if lang == "hi" else ". "
        else:
            text += t["supply_off"].format(next=clk["next_window"])
        if mon.tank.get("level_pct") is not None:
            text += t["tank"].format(tank=round(mon.tank["level_pct"]), pump=t["pump_on"] if mon.pump.get("on") else t["pump_off"])
        mine = sorted((i for i in p.incidents.items.values() if i["village_id"] == vid), key=lambda i: -i["priority"])
        text += t["incidents"].format(k=len(mine), title=mine[0]["title"]) if mine else t["none"]
        text += t["quality_verify"] if k["quality_status"] == "verify" else t["quality_ok"]
        if k["complaints_open"]:
            text += t["complaints"].format(c=k["complaints_open"])
        if k["functional"] and k["functional"]["basis"] == "today":
            text += t["functional"].format(pct=round(k["functional"]["pct"]))
        return {"lang": lang, "text": text.strip(), "generated_at": clk["iso"]}


# ------------------------------------------------- Jal Seva Aankalan draft
def aankalan(p, vid: str) -> dict:
    """Evidence-backed draft of the GP's Jal Seva Aankalan self-assessment.

    The assessment has five parameters: regularity and adequacy of supply, water quality, operation and
    maintenance, source sustainability, and institutional and management arrangements. The Pani Samiti
    discusses it, the Gram Sabha endorses it, and it then stays open for 30 days of citizen feedback.
    This fills the draft from continuous data and the O&M registers so the Gram Sabha reviews evidence
    rather than recollection. It is a draft for human review, never an automatic submission.
    """
    with p.lock:
        sim, mon = p.sims[vid], p.monitors[vid]
        hist = p.history.get(vid, [])[-30:]
        k = village_kpis(p, vid)
        om, stage = p.om.summary(vid), p.om.assessment(vid)
        tasks = {t["key"]: t for t in p.om.tasks(vid)["tasks"]}

        def avg(key):
            vals = [r[key] for r in hist if r.get(key) is not None]
            return round(float(np.mean(vals)), 1) if vals else None

        def mean(vals):
            vals = [v for v in vals if v is not None]
            return round(float(np.mean(vals)), 1) if vals else None

        tests = p.db.query("SELECT result FROM wq_tests WHERE village_id=?", (vid,))
        closed = p.db.query("SELECT first_seen, closed_at, sla_resolve_due FROM incidents WHERE village_id=? AND is_seed=0 AND status='closed'", (vid,))
        in_sla = sum(1 for r in closed if r["closed_at"] <= r["sla_resolve_due"])
        src = mon.source
        days = src.get("days_to_limit")
        days_supplied = sum(1 for r in hist if (r.get("supply_hours") or 0) >= 4.5)
        sections = [
            {"key": "service", "title": "Regularity and adequacy", "question": "Does water come on every scheduled day, and does every household get at least 55 litres per person?",
             "indicators": [{"label": "Days with supply close to schedule (last 30)", "value": f"{days_supplied} / {len(hist)}"},
                            {"label": "Households served in scheduled windows (30-day average)", "value": f"{avg('regularity_pct')}%"},
                            {"label": "Households at or above 55 lpcd (30-day average)", "value": f"{avg('quantity_pct')}%"},
                            {"label": "Average supply (30-day)", "value": f"{avg('avg_lpcd')} lpcd"}],
             "score": mean([avg("regularity_pct"), avg("quantity_pct")])},
            {"key": "quality", "title": "Drinking water quality", "question": "Is the water tested and within prescribed limits?",
             "indicators": [{"label": "Households without an open quality concern (30-day average)", "value": f"{avg('quality_pct')}%"},
                            {"label": "FTK / lab tests recorded in this system", "value": f"{len(tests)} ({sum(1 for t in tests if t['result'] == 'pass')} passed)"},
                            {"label": "Laboratory tests on schedule (bacteriological twice a year, chemical once)",
                             "value": "yes" if tasks["wq_bact"]["status"] != "overdue" and tasks["wq_chem"]["status"] != "overdue" else "overdue"},
                            {"label": "Current sensor screening status", "value": k["quality_status"]}],
             "score": avg("quality_pct"),
             "caveat": "Sensor screening does not replace FTK and laboratory testing under the JJM water quality framework."},
            {"key": "om", "title": "Operation and maintenance", "question": "Is the system looked after before it breaks, and fixed quickly when it does?",
             "indicators": [{"label": "Upkeep items up to date", "value": f"{om['upkeep_on_time']} of {om['upkeep_total']}"},
                            {"label": "Operator log kept (last 14 days)", "value": f"{om['log_pct']}% of supply windows"},
                            {"label": "Incidents closed within the time allowed (this session)", "value": f"{in_sla} / {len(closed)}"},
                            {"label": "Monitoring devices online", "value": f"{k['devices_online_pct']}%"}],
             "score": mean([om["upkeep_pct"], om["log_pct"], in_sla / len(closed) * 100 if closed else None])},
            {"key": "source", "title": "Source sustainability", "question": "Will the source keep up?",
             "indicators": [{"label": "Borewell rest level", "value": f"{src.get('rest_m') or src.get('depth_m')} m below ground"},
                            {"label": "Rest-level trend (14 days)", "value": f"{src.get('trend_m_per_day')} m/day"},
                            {"label": "Margin before the pumping level reaches the intake", "value": f"about {days:.0f} days" if days is not None else "no decline that matters"}],
             "score": None if src.get("trend_m_per_day") is None else 100.0 if days is None else 85.0 if days > 180 else 60.0 if days >= 45 else 30.0,
             "caveat": "Scored by a stated rule: stable 100, more than 180 days of margin 85, 45 to 180 days 60, under 45 days 30."},
            {"key": "institution", "title": "Institutional and management arrangements", "question": "Is the Pani Samiti functioning, and can the scheme pay its way?",
             "indicators": [{"label": "User charge", "value": f"₹{om['tariff']:.0f} per household per month"},
                            {"label": "User charges collected (last 3 months)", "value": f"{om['collection_pct']}%"},
                            {"label": "Running cost covered by collections (last 3 months)", "value": f"{om['recovery_pct']}%"},
                            {"label": "Arrears", "value": f"₹{om['arrears']:,}"},
                            {"label": "Pani Samiti monthly meeting", "value": "held on schedule" if tasks["vwsc"]["status"] != "overdue" else "overdue"}],
             "score": mean([om["collection_pct"], min(100.0, om["recovery_pct"]) if om["recovery_pct"] is not None else None]),
             "caveat": "Accounts in this demo are simulated."},
        ]
        scores = [s["score"] for s in sections if s["score"] is not None]
        status = {"draft": "DRAFT for Gram Sabha review", "feedback": f"Endorsed by the Gram Sabha: open for citizen feedback, {stage['days_left']} days left",
                  "final": "Final: feedback window closed"}[stage["stage"]]
        return {"village_id": vid, "village": sim.name, "gp": S.admin_path(S.village_by_id(vid))["gp"],
                "ids": S.external_ids(S.village_by_id(vid)), "period": f"{nice(hist[0]['day'])} to {nice(hist[-1]['day'])}" if hist else None,
                "sections": sections, "overall": round(float(np.mean(scores)), 1) if scores else None,
                "status": status, "stage": stage,
                "note": "Auto-filled from simulated monitoring data and simulated O&M registers. In deployment the Pani Samiti reviews and corrects this "
                        "draft, the Gram Sabha endorses it, and it is uploaded to the JJM Panchayat Dashboard with a 30-day citizen feedback window.",
                "generated_at": p.now.isoformat(timespec="seconds")}

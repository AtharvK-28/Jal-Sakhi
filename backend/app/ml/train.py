"""Train every model on simulator output and write the bundle plus a model card.

Run directly:  python -m app.ml.train

Everything here learns from SYNTHETIC data produced by app.sim.world. The
reported metrics describe how well the models recover injected faults in that
simulator. They say nothing about field performance, which needs authorised
real telemetry and maintenance records.

Evaluation rules used throughout:
  * calibration days, validation days and test days of a village never overlap (different run seeds);
  * the detector's alarm level is set on validation days and scored on test days;
  * the fault classifier never trains on a fault from the two held-out villages;
  * pumps and complaint phrases are held out whole, never sample by sample;
  * every improved model is scored next to the method it replaces, on the same cases ("was" in the card).
"""
from __future__ import annotations

import json
import math
import random
import time
from datetime import timedelta

import joblib
import numpy as np
import sklearn
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor, IsolationForest
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LinearRegression, LogisticRegression
from sklearn.metrics import accuracy_score, brier_score_loss, f1_score, precision_score, recall_score, roc_auc_score
from sklearn.pipeline import make_pipeline

from .. import config as C
from ..seed import VILLAGES
from ..sim.clock import SimClock
from ..sim.world import N_P, VillageSim
from . import models as M
from .nlp_corpus import AFFIXES, CATEGORIES, KEYWORDS, PHRASES
from .nlp_corpus_extra import EXTRA

CAL_SEEDS, VALID_SEEDS, TEST_SEEDS = (101, 102, 103), (201, 202), (301, 302, 303)
HELD_OUT = ("VLG-DK", "VLG-AG")  # the fault classifier never sees a fault from these villages
LEAKS, BLOCKS = [2.5, 4, 6, 9, 14, 22, 32], [0.03, 0.06, 0.12, 0.25, 0.45, 0.65]  # L/min at 1 bar; share of head lost
DET_K, DET_CAP = 1.0, 3.5  # CUSUM allowance and per-reading cap, in residual sigmas
V1_PERSIST = 8  # the detector this replaces: score and residual over threshold for 8 readings in a row
# metered taps per lane to compare, and where along the lane they sit (None: every home)
STUDY = [(0, []), (1, [0.55]), (2, [0.33, 0.75]), (3, [0.2, 0.55, 0.9]), (5, [0.12, 0.3, 0.5, 0.7, 0.9]), ("all", None)]


# ------------------------------------------------------------------ simulation
def tap_idx(v: VillageSim, b: int) -> list[int]:
    return [int(i) for i in np.flatnonzero((v.b_of == b) & v.instrumented)]


def elevs(v: VillageSim, b: int) -> list[float]:
    return [float(v.elev[i]) for i in tap_idx(v, b)] + [float(v.slope[b])]


def run_village(spec: dict, run_seed: int, days: float, fault: dict | None = None):
    """One stretch of a village's life from its sensors.

    Returns (sim, {branch: [(w, m, p_in, p_end, q, label, tap pressures)]}, [(tank level, main flow, mean entry pressure)],
    {branch: [true pressure at every home]}). The last is the simulator's hidden truth: used to score, never to detect.
    fault = {"b": branch, "win": window index, "onset": minute in window, "apply": fn(sim)}
    """
    v = VillageSim(spec, 0, run_seed=run_seed)
    clock = SimClock(C.SIM_START)
    end = C.SIM_START + timedelta(days=days)
    taps = [tap_idx(v, b) for b in range(v.nb)]
    homes = [np.flatnonzero(v.b_of == b) for b in range(v.nb)]
    rec = {b: [] for b in range(v.nb)}
    truth = {b: [] for b in range(v.nb)}
    main = []
    active = False
    while clock.now < end:
        clk = clock.advance()
        if fault and not active and clk.win_idx == fault["win"] and clk.min_in_win >= fault["onset"]:
            fault["apply"](v)
            active = True
        readings = dict(v.step(clk))
        if clk.win_idx is None or clk.min_in_win < C.WINDOW_GRACE_MIN:
            continue
        p_ins = []
        for b in range(v.nb):
            bid = v.branch_ids[b]
            r_in, r_end = readings[f"{bid}-IN"], readings[f"{bid}-END"]
            tp = tuple(readings[f"{v.hh_ids[i]}-TAP"]["pressure_bar"] for i in taps[b])
            rec[b].append((clk.win_idx, clk.min_in_win, r_in["pressure_bar"], r_end["pressure_bar"], r_in["flow_lpm"],
                           1 if (active and fault["b"] == b) else 0, tp))
            truth[b].append(v.p[homes[b]].copy())
            p_ins.append(r_in["pressure_bar"])
        main.append((readings[f"{v.code}-TANK"]["level_pct"] / 100.0, readings[f"{v.code}-MAIN"]["flow_lpm"], float(np.mean(p_ins))))
    return v, rec, main, truth


def replay(v: VillageSim, rec: dict, curves: dict, profile: dict, det: dict) -> list[list]:
    """Recorded samples through BranchTracker, exactly as the live monitor feeds it. Per branch: [tracker output | None]."""
    out = []
    for b, rows in rec.items():
        tr = M.BranchTracker(v.sizes[b], float(v.q_nom[b]), curves[v.branch_ids[b]], profile, det, elevs(v, b))
        out.append([tr.update(w, m, p_in, p_end, q, list(tp)) if p_in >= C.P_DRY else None  # a dry lane is the interruption rule's job
                    for w, m, p_in, p_end, q, _label, tp in rows])
    return out


def _fit(u: np.ndarray, loss: np.ndarray) -> dict:
    c, a = np.polyfit(u, loss, 1)
    return {"a": float(a), "c": float(c), "sigma": max(float((loss - (a + c * u)).std()), 0.012)}


def first_run(flags, n: int):
    run = 0
    for i, f in enumerate(flags):
        run = run + 1 if f else 0
        if run >= n:
            return i
    return None


def segment_v1(c_tail: float, q: float, q_nom: float, p_in: float, pts: list[tuple]) -> tuple | None:
    """The localisation this replaces: latest reading against an assumed cubic friction profile, last big step wins."""
    hl = c_tail * (q / q_nom) ** 2
    resid = [p_in - hl * (1 - (1 - x) ** 3) - g for x, g in pts]
    peak = max(resid)
    if peak < 0.08:
        return None
    last = None
    for k in range(1, len(pts)):
        if resid[k] - resid[k - 1] > max(0.05, 0.25 * peak):
            last = k
    return None if last is None else (pts[last - 1][0], pts[last][0])


# ------------------------------------------------- hydraulic model, detector, classifier, locator
def train_branch_models(report):
    t0 = time.time()
    cal = [run_village(spec, s, 1.0) for spec in VILLAGES for s in CAL_SEEDS]

    # 1. calibrated hydraulic model: loss of grade from the lane entry to every measured point, and the main
    curves, main = {}, {}
    for spec in VILLAGES:
        runs = [r for r in cal if r[0].id == spec["id"]]
        v0 = runs[0][0]
        for b in range(v0.nb):
            rows = [r for _v, rec, _m, _t in runs for r in rec[b] if r[2] > 0.3]
            p_in, p_end, q = (np.array([r[k] for r in rows]) for k in (2, 3, 4))
            u = (q / v0.q_nom[b]) ** 2
            el, pts = elevs(v0, b), []
            for j, i in enumerate(tap_idx(v0, b)):
                tap = np.array([r[6][j] for r in rows])
                pts.append({"x": float(v0.x[i]), "i": i, "label": f"HH-{i + 1:03d}", **_fit(u, p_in - (tap + el[j]))})
            pts.append({"x": 1.0, "i": None, "label": "tail end", **_fit(u, p_in - (p_end + el[-1]))})
            curves[v0.branch_ids[b]] = {**_fit(u, p_in - p_end), "pts": pts}
        rows = np.array([m for _v, _rec, ms, _t in runs for m in ms if m[2] > 0.3])
        A = np.column_stack([np.ones(len(rows)), rows[:, 0], -(rows[:, 1] / v0.q_main_nom) ** 2])
        coef, *_ = np.linalg.lstsq(A, rows[:, 2], rcond=None)
        main[spec["id"]] = {"h0": float(coef[0]), "h1": float(coef[1]), "r": float(coef[2]),
                            "sigma": float((rows[:, 2] - A @ coef).std()), "q_nom": float(v0.q_main_nom)}

    # 2. demand profile: smoothed per-household flow by (window, 5-minute bucket), then each lane's own scale
    acc = [[[] for _ in range(M.N_BUCKETS)] for _ in C.SUPPLY_WINDOWS]
    for v, rec, _m, _t in cal:
        for b, rows in rec.items():
            ewma, win = 0.0, None
            for w, m, _pi, _pe, q, _l, _tp in rows:
                ewma = q if w != win else M.BranchTracker.ALPHA * q + (1 - M.BranchTracker.ALPHA) * ewma
                win = w
                acc[w][min(M.N_BUCKETS - 1, int(m // M.BUCKET_MIN))].append(ewma / v.sizes[b])
    profile = {"mu": [[float(np.mean(c)) if c else 0.0 for c in w] for w in acc],
               "sd": [[float(np.std(c)) if c else 0.3 for c in w] for w in acc]}
    got, want = {}, {}
    for v, rec, _m, _t in cal:
        for b, rows in rec.items():
            bid = v.branch_ids[b]
            got[bid] = got.get(bid, 0.0) + sum(r[4] for r in rows)
            want[bid] = want.get(bid, 0.0) + sum(profile["mu"][r[0]][min(M.N_BUCKETS - 1, int(r[1] // M.BUCKET_MIN))] * v.sizes[b] for r in rows)
    for bid in curves:
        curves[bid]["q_scale"] = round(got[bid] / want[bid], 4)

    # 3. IsolationForest on the tracker features of normal operation
    det = {"k": DET_K, "cap": DET_CAP, "h": 1e9}  # alarm level not known yet
    X_train = np.asarray([o["x"] for v, rec, _m, _t in cal for seq in replay(v, rec, curves, profile, det) for o in seq if o])
    forest = IsolationForest(n_estimators=140, max_samples=512, contamination="auto", random_state=7)
    forest.fit(X_train)
    # Scale raw forest scores to 0..1. Isolation scores saturate outside the training range, so
    # 0 = a typical normal sample and 1 = the saturation level reached by clear hydraulic
    # anomalies (normal samples with the pressure residual pushed 8 sigma out).
    raw = -forest.score_samples(X_train)
    ref = X_train[:: max(1, len(X_train) // 4000)].copy()
    ref[:, 0] += 8.0
    if_scale = (float(np.median(raw)), float(np.quantile(-forest.score_samples(ref), 0.9)))

    def score(X):
        return np.clip((-forest.score_samples(np.asarray(X)) - if_scale[0]) / (if_scale[1] - if_scale[0]), 0, 1)

    def v1_flags(seq):
        idx = [i for i, o in enumerate(seq) if o]
        s = dict(zip(idx, score([seq[i]["x"] for i in idx]))) if idx else {}
        return [bool(o and s[i] >= C.ANOMALY_SCORE and abs(o["z_r"]) >= 3.0) for i, o in enumerate(seq)]

    # 4. alarm level for the sequential detector: clear of everything seen on validation days, with headroom
    peak = 0.0
    for spec in VILLAGES:
        for s in VALID_SEEDS:
            v, rec, _m, _t = run_village(spec, s, 1.0)
            peak = max([peak] + [o["cusum"] for seq in replay(v, rec, curves, profile, det) for o in seq if o])
    det = {"k": DET_K, "cap": DET_CAP, "h": float(max(8.0, math.ceil(1.6 * peak)))}
    H = det["h"]

    # 5a. false alarms on test days no model has seen
    lane_days = false_v1 = false_v2 = n_samples = n_flag = 0
    for spec in VILLAGES:
        for s in TEST_SEEDS:
            v, rec, _m, _t = run_village(spec, s, 1.0)
            for seq in replay(v, rec, curves, profile, det):
                fl = v1_flags(seq)
                lane_days += 1
                n_samples += len(fl)
                n_flag += sum(fl)
                false_v1 += first_run(fl, V1_PERSIST) is not None
                false_v2 += any(o and o["cusum"] >= H for o in seq)

    # 5b. injected faults: detection, type, position. Same cases for the old and the new method.
    rnd = random.Random(99)
    cases = []
    for spec in VILLAGES:
        nb = len(spec["branches"])
        for kind, mags in (("leak", LEAKS), ("blockage", BLOCKS)):
            for mag in mags:
                for _rep in range(2):
                    cases.append({"spec": spec, "kind": kind, "mag": mag, "b": rnd.randrange(nb), "x": rnd.uniform(0.15, 0.9),
                                  "onset": rnd.randint(12, 110), "win": 1 if rnd.random() < 0.2 else 0, "seed": 500 + len(cases)})

    def simulate(case):
        def apply(v, c=case):
            (v.faults.leak if c["kind"] == "leak" else v.faults.blockage)[c["b"]] = (c["x"], c["mag"])
        days = 0.14 if case["win"] == 0 else 0.6  # long enough to finish the window the fault is in
        v, rec, _m, truth = run_village(case["spec"], case["seed"], days, fault={"b": case["b"], "win": case["win"], "onset": case["onset"], "apply": apply})
        return v, rec, replay(v, rec, curves, profile, det), truth

    def window_at(seq, e):
        return M.window_means([o for o in seq[: e + 1] if o][-M.WINDOW:])

    # the classifier's training faults: other seeds, random sizes, and only the villages that are not held out
    Xf, yf, n_sim = [], [], 0
    for spec in [s for s in VILLAGES if s["id"] not in HELD_OUT]:
        for n in range(36):
            kind = "leak" if n % 2 == 0 else "blockage"
            case = {"spec": spec, "kind": kind, "b": rnd.randrange(len(spec["branches"])), "x": rnd.uniform(0.12, 0.92),
                    "mag": math.exp(rnd.uniform(math.log(2.0), math.log(40.0))) if kind == "leak" else math.exp(rnd.uniform(math.log(0.025), math.log(0.7))),
                    "onset": rnd.randint(12, 120),
                    "win": 1 if n % 5 == 4 else 0, "seed": 700 + n_sim}
            n_sim += 1
            _v, rec, seqs, _t = simulate(case)
            seq, rows = seqs[case["b"]], rec[case["b"]]
            start = next(i for i, r in enumerate(rows) if r[5])
            for e in range(start + 3, min(len(seq), start + 46), 2):
                wm = window_at(seq, e)
                if wm and wm["z_r"] >= 1.5:  # only windows in which something is visibly wrong
                    Xf.append(M.fault_features(wm))
                    yf.append(int(kind == "leak"))
    fault_clf = HistGradientBoostingClassifier(max_iter=70, max_depth=3, learning_rate=0.15, random_state=7)
    fault_clf.fit(np.asarray(Xf), np.asarray(yf))

    res, shots = [], []
    for case in cases:
        v, rec, seqs, truth = simulate(case)
        b = case["b"]
        seq, rows = seqs[b], rec[b]
        start = next((i for i, r in enumerate(rows) if r[5]), None)
        if start is None:
            continue
        d1 = first_run(v1_flags(seq)[start:], V1_PERSIST)
        d2 = next((i for i, o in enumerate(seq[start:]) if o and o["cusum"] >= H), None)
        r = {"kind": case["kind"], "mag": case["mag"], "village": case["spec"]["id"], "d1": None if d1 is None else d1 + 1,
             "d2": None if d2 is None else d2 + 1,
             "early": any(o and o["cusum"] >= H for o in seq[:start]) or any(o and o["cusum"] >= H for k, s in enumerate(seqs) if k != b for o in s)}
        if d2 is not None:
            e = min(len(seq) - 1, start + d2 + 6)  # a few readings after the alarm, as the incident would be read
            wm = window_at(seq, e)
            cv = curves[v.branch_ids[b]]
            xs, sig = [p["x"] for p in cv["pts"]], [p["sigma"] for p in cv["pts"]]
            if wm:
                keep = [i for i in range(e + 1) if seq[i]][-M.WINDOW:]  # the same readings the window above is made of
                lane = np.flatnonzero(v.b_of == b)
                shots.append({"bid": v.branch_ids[b], "kind": case["kind"], "x_true": case["x"], "n": v.sizes[b], "xh": v.x[lane],
                              "elev": v.elev[lane], "slope": float(v.slope[b]), "q_nom": float(v.q_nom[b]), "rows": [rows[i] for i in keep],
                              "truth": np.array([truth[b][i] for i in keep]), "tail_rb": wm["rb"][-1], "tail_sigma": sig[-1]})
                r["p_leak"] = float(fault_clf.predict_proba(np.asarray([M.fault_features(wm)]))[0, 1])
                r["rule"] = "leak" if wm["z_q"] >= C.LEAK_Z_FLOW else "obstruction" if wm["z_q"] <= 0.5 else "undetermined"
                n_hh = v.sizes[b]
                if case["kind"] == "leak":
                    loc = M.locate_leak(xs, wm["rb"], sig, wm["n"])
                    if loc:
                        r.update(err=abs(loc["x"] - case["x"]) * n_hh, inside=loc["x0"] - 1e-9 <= case["x"] <= loc["x1"] + 1e-9,
                                 width=(loc["x1"] - loc["x0"]) * n_hh)
                    row = rows[e]
                    el = elevs(v, b)
                    old = segment_v1(cv["c"], row[4], float(v.q_nom[b]), row[2],
                                     [(0.0, row[2])] + [(xs[j], row[6][j] + el[j]) for j in range(len(row[6]))] + [(1.0, row[3] + el[-1])])
                    if old:
                        r.update(err1=abs((old[0] + old[1]) / 2 - case["x"]) * n_hh, inside1=old[0] <= case["x"] <= old[1],
                                 width1=(old[1] - old[0]) * n_hh)
                else:
                    br = M.bracket_step(xs, wm["rb"])
                    if br:
                        r.update(inside=br["x0"] - 1e-9 <= case["x"] <= br["x1"] + 1e-9, width=(br["x1"] - br["x0"]) * n_hh)
        res.append(r)

    def med(vals):
        vals = [x for x in vals if x is not None]
        return round(float(np.median(vals)), 1) if vals else None

    def rate(flags):
        flags = list(flags)
        return round(sum(bool(f) for f in flags) / len(flags), 3) if flags else None

    by_fault = {}
    for kind, mags, unit in (("leak", LEAKS, "L/min at 1 bar"), ("blockage", BLOCKS, "of head lost")):
        for mag in mags:
            rs = [r for r in res if r["kind"] == kind and r["mag"] == mag]
            by_fault[f"{kind} {mag}"] = {"unit": unit, "of": len(rs), "detected": sum(r["d2"] is not None for r in rs),
                                        "median_delay_min": med(r["d2"] for r in rs), "was_detected": sum(r["d1"] is not None for r in rs),
                                        "was_median_delay_min": med(r["d1"] for r in rs)}
    typed = [r for r in res if "p_leak" in r]
    unseen = [r for r in typed if r["village"] in HELD_OUT]
    right = lambda r: (r["p_leak"] >= 0.5) == (r["kind"] == "leak")  # noqa: E731
    rule_right = lambda r: r["rule"] == ("leak" if r["kind"] == "leak" else "obstruction")  # noqa: E731
    leaks = [r for r in res if r["kind"] == "leak" and "err" in r]
    blocks = [r for r in res if r["kind"] == "blockage" and "inside" in r]
    report["branch_anomaly"] = {
        "algorithm": "Calibrated head-loss curve + lane demand profile; CUSUM on the pressure residual raises the alarm, "
                     "Isolation Forest (140 trees) scores how unusual the lane looks",
        "features": ["pressure residual vs learned head-loss curve (z)", "flow vs learned demand profile (z)", "tail/entry pressure ratio"],
        "train_samples": int(len(X_train)),
        "train_scope": f"{len(CAL_SEEDS)} simulated normal days x 6 villages ({len(curves)} lanes); alarm level set on {len(VALID_SEEDS)} further days",
        "alarm_level": H, "peak_on_validation_days": round(peak, 2),
        "events_tested": len(res),
        "event_detection_rate": rate(r["d2"] is not None for r in res),
        "median_detection_delay_min": med(r["d2"] for r in res),
        "false_events_normal_branch_days": int(false_v2), "normal_branch_days_tested": lane_days,
        "false_alarms_in_fault_runs": sum(r["early"] for r in res),
        "false_alert_rate_normal": round(n_flag / max(1, n_samples), 5),
        "was": {"method": f"Isolation Forest score and residual over threshold for {V1_PERSIST} readings in a row",
                "event_detection_rate": rate(r["d1"] is not None for r in res), "median_detection_delay_min": med(r["d1"] for r in res),
                "false_events_normal_branch_days": int(false_v1)},
        "by_fault": by_fault,
        "alert_rule": f"CUSUM of the residual (allowance {DET_K} sigma, at most {DET_CAP} sigma per reading) reaches {H:.0f}: "
                      f"at least {math.ceil(H / (DET_CAP - DET_K))} readings of evidence, so a short transient cannot trip it",
        "seconds": round(time.time() - t0, 1),
    }
    report["fault_classifier"] = {
        "algorithm": "Histogram gradient-boosted trees (70 iterations, depth 3) on the residual pattern along the lane",
        "features": M.FAULT_FEATURES, "classes": ["leak", "obstruction"],
        "train_samples": len(yf), "train_scope": f"{36 * (len(VILLAGES) - len(HELD_OUT))} simulated faults in {len(VILLAGES) - len(HELD_OUT)} villages",
        "test_events": len(typed), "accuracy": rate(right(r) for r in typed),
        "unseen_village_events": len(unseen), "accuracy_unseen_villages": rate(right(r) for r in unseen),
        "leak_recall": rate(right(r) for r in typed if r["kind"] == "leak"),
        "obstruction_recall": rate(right(r) for r in typed if r["kind"] == "blockage"),
        "was": {"method": f"rule: flow {C.LEAK_Z_FLOW} sigma above demand = leak, within 0.5 sigma = obstruction, else undetermined",
                "accuracy": rate(rule_right(r) for r in typed), "undetermined": rate(r["rule"] == "undetermined" for r in typed)},
        "split": f"faults in {', '.join(HELD_OUT)} are never trained on; test faults use other days and sizes everywhere",
    }
    report["leak_locator"] = {
        "algorithm": "Weighted least-squares fit of the leak signature (loss ramps up to the leak, flat beyond) to the "
                     "mean residual at every measured point; obstructions are bracketed between two points",
        "leaks_located": len(leaks), "median_error_homes": med(r["err"] for r in leaks),
        "p90_error_homes": round(float(np.quantile([r["err"] for r in leaks], 0.9)), 1) if leaks else None,
        "true_position_inside_interval": rate(r["inside"] for r in leaks), "median_interval_homes": med(r["width"] for r in leaks),
        "obstructions_bracketed": len(blocks), "obstruction_inside_bracket": rate(r["inside"] for r in blocks),
        "obstruction_median_bracket_homes": med(r["width"] for r in blocks),
        "was": {"method": "latest reading against an assumed friction profile; reports the segment between two sensors",
                "leaks_located": sum("err1" in r for r in leaks), "median_error_homes": med(r.get("err1") for r in leaks),
                "true_position_inside_interval": rate(r["inside1"] for r in leaks if "inside1" in r),
                "median_interval_homes": med(r.get("width1") for r in leaks)},
        "note": "A leak before the first metered tap can only be placed 'before that tap'.",
    }
    return curves, main, profile, forest, if_scale, det, fault_clf, cal, shots


def sensor_study(cal: list, shots: list) -> dict:
    """How much do metered taps buy? The benchmark's fault cases again, with 0, 1, 2, 3, 5 or every home metered.

    The lane's entry and tail sensors stay in every option. A metered tap is taken to read the true pressure
    at that home plus sensor noise, and its healthy curve is learned from the calibration days, as the
    deployed taps' curves are. Scored at the moment the benchmark scores: a few readings after the alarm."""
    rng = np.random.default_rng(11)
    curve = {}  # lane -> healthy loss of grade at every home: intercept, slope, scatter
    for v0 in {r[0].id: r[0] for r in cal}.values():
        runs = [r for r in cal if r[0].id == v0.id]
        for b in range(v0.nb):
            keep = [(row, tr) for _v, rec, _m, truth in runs for row, tr in zip(rec[b], truth[b]) if row[2] > 0.3]
            p_in = np.array([row[2] for row, _t in keep])
            u = (np.array([row[4] for row, _t in keep]) / v0.q_nom[b]) ** 2
            lane = np.flatnonzero(v0.b_of == b)
            read = np.array([t for _r, t in keep]) + rng.normal(0, N_P, (len(keep), len(lane)))
            loss = p_in[:, None] - (read + v0.elev[lane][None, :])
            c, a = np.polyfit(u, loss, 1)  # one straight-line fit per home
            curve[v0.branch_ids[b]] = (a, c, np.maximum((loss - (a[None, :] + np.outer(u, c))).std(axis=0), 0.012))

    options = []
    for taps, fracs in STUDY:
        errs, leaks, found, affected, flagged, fine = [], 0, 0, 0, 0, 0
        for s in shots:
            n = s["n"]
            chosen = np.arange(n) if fracs is None else np.unique(np.clip(np.round(np.array(fracs) * n).astype(int) - 1, 0, n - 1)).astype(int)
            a, c, sigma = curve[s["bid"]]
            p_in = np.array([r[2] for r in s["rows"]])
            u = (np.array([r[4] for r in s["rows"]]) / s["q_nom"]) ** 2
            read = s["truth"][:, chosen] + rng.normal(0, N_P, (len(p_in), len(chosen)))
            resid = ((p_in[:, None] - (read + s["elev"][chosen][None, :])) - (a[chosen][None, :] + np.outer(u, c[chosen]))).mean(axis=0)
            if s["kind"] == "leak":
                leaks += 1
                loc = M.locate_leak(list(s["xh"][chosen]) + [1.0], list(resid) + [s["tail_rb"]], list(sigma[chosen]) + [s["tail_sigma"]], len(p_in))
                if loc is not None:  # with no tap there is one point and nothing to fit
                    errs.append(abs(loc["x"] - s["x_true"]) * n)
            # every home's status at the last of those readings, from whatever points are measured
            last = s["rows"][-1]
            gx = np.concatenate([[0.0], s["xh"][chosen], [1.0]])
            gy = np.concatenate([[last[2]], read[-1] + s["elev"][chosen], [last[3] + s["slope"]]])
            order = np.argsort(gx, kind="stable")
            est = np.maximum(np.interp(s["xh"], gx[order], gy[order]) - s["elev"], 0.0)
            est[chosen] = read[-1]
            low = s["truth"][-1] < C.P_OK  # every home counts, metered or inferred: the same homes in every option
            affected += int(low.sum())
            found += int((low & (est < C.P_OK)).sum())
            fine += int((~low).sum())
            flagged += int((~low & (est < C.P_OK)).sum())
        options.append({"taps_per_lane": taps, "leaks": leaks, "leaks_placed": len(errs),
                        "leak_error_homes": round(float(np.median(errs)), 1) if errs else None,
                        "affected_homes": affected, "affected_found": round(found / affected, 3) if affected else None,
                        "unaffected_homes": fine, "wrongly_flagged": round(flagged / fine, 4) if fine else None})
    return {"cases": len(shots), "deployed": 3, "options": options,
            "method": "the detection benchmark's fault cases, re-scored with different numbers of metered taps per lane; "
                      "lane entry and tail sensors are present in every option",
            "note": "Simulated. 'Affected' means a home truly below usable pressure at that moment, a few minutes into the fault. "
                    "Every home on the lane is counted in every option, whether its status is measured or inferred."}


# ------------------------------------------------------------- pump models
def _pump_rows(rng, n_pumps: int, horizon_h: float = 72.0):
    """Synthetic run-to-failure histories -> (features, label, pump id, hours to failure, wear)."""
    X, y, g, ttf, wear = [], [], [], [], []
    i_nom, v_nom, rate_nom = 11.5, 2.2, 350.0
    k = math.sqrt(20)  # features are means over ~20 samples
    for p in range(n_pumps):
        w0 = rng.uniform(0.02, 0.15)
        onset = rng.uniform(100, 1500)
        rate = rng.lognormal(math.log(0.004), 0.7)  # wear per run-hour once degradation starts
        t_fail = onset + (0.92 - w0) / rate
        t = np.arange(0, min(t_fail, 3000), 6.0)
        w = w0 + np.clip(t - onset, 0, None) * rate
        cur = i_nom * (1 + 0.38 * w) + rng.normal(0, 0.12 / k, len(t))
        vib = v_nom * (1 + 2.6 * w) + rng.normal(0, 0.07 / k, len(t))
        dis = rate_nom * (1 - 0.45 * w) * (1 + rng.normal(0, 0.008 / k, len(t)))
        for j in range(len(t)):
            X.append(M.pump_features(cur[j], vib[j], dis[j], i_nom, v_nom, rate_nom, t[j]))
            y.append(int(t_fail - t[j] <= horizon_h and t_fail < 3000))
            g.append(p)
            ttf.append(t_fail - t[j] if t_fail < 3000 else 1e6)
            wear.append(w[j] / 0.92)
    return np.asarray(X), np.asarray(y), np.asarray(g), np.asarray(ttf), np.asarray(wear)


def train_pump_model(report):
    t0 = time.time()
    rng = np.random.default_rng(42)
    X, y, g, ttf, wear = _pump_rows(rng, 480)
    test, conf = g % 5 == 0, g % 5 == 1  # whole pumps: 20% held out, 20% to size the life intervals, 60% train
    train = ~(test | conf)

    def make():
        return HistGradientBoostingClassifier(max_iter=80, max_depth=4, learning_rate=0.15, random_state=7)  # half the trees: scored every tick

    clf = make().fit(X[~test], y[~test])
    proba = clf.predict_proba(X[test])[:, 1]
    pred = (proba >= C.PUMP_RISK_ALERT).astype(int)
    gt, tt = g[test], ttf[test]
    leads, early, failing = [], 0, [q for q in np.unique(gt) if tt[gt == q].min() < 1e5]
    for q in failing:
        hits = np.flatnonzero(proba[gt == q] >= C.PUMP_RISK_ALERT)
        if len(hits):
            leads.append(tt[gt == q][hits[0]])
            early += int(leads[-1] > 240)

    # wear index: how much of the wear life is used, read off the three condition signals
    lin = LinearRegression().fit(X[train][:, :3], wear[train])
    wear_model = {"w": [float(c) for c in lin.coef_], "b": float(lin.intercept_)}
    idx = np.clip(lin.predict(X[:, :3]), 0, 1.2)

    # remaining life, fleet prior: quantile regression on run-to-failure histories, then the interval is
    # widened until it holds 80% of the truth on pumps the regression never saw (conformal calibration)
    life = np.minimum(ttf, M.RUL_CAP_H)
    rul = [HistGradientBoostingRegressor(loss="quantile", quantile=q, max_iter=60, max_depth=4, learning_rate=0.15, random_state=7)
           .fit(X[train], life[train]) for q in (0.1, 0.5, 0.9)]
    near_c = conf & (ttf <= 300)
    lo_c, hi_c = rul[0].predict(X[near_c]), rul[2].predict(X[near_c])
    raw_cover = float(np.mean((lo_c <= life[near_c]) & (life[near_c] <= hi_c)))
    widen = float(max(0.0, np.quantile(np.maximum(lo_c - life[near_c], life[near_c] - hi_c), 0.8)))
    near = test & (ttf <= 300)  # the stretch that matters: the last 300 run-hours
    q10, q50, q90 = rul[0].predict(X[near]) - widen, rul[1].predict(X[near]), rul[2].predict(X[near]) + widen
    fleet_of = dict(zip(np.flatnonzero(near), q50))
    # remaining life from each pump's own trend over its last ten readings (60 run-hours)
    t_err, t_in, f_err, b_err = [], [], [], []
    for q in np.unique(g[test]):
        rows = np.flatnonzero(g == q)
        for j in range(10, len(rows)):
            r = rows[j]
            if ttf[r] > 300:
                continue
            tr = M.trend_rul(X[rows[j - 9:j + 1], 3], idx[rows[j - 9:j + 1]])
            f_err.append(abs(fleet_of[r] - ttf[r]))
            b_err.append(abs((tr["h"] if tr else fleet_of[r]) - ttf[r]))
            if tr:
                t_err.append(abs(tr["h"] - ttf[r]))
                t_in.append(tr["lo"] <= ttf[r] <= tr["hi"])
    report["pump_failure_risk"] = {
        "algorithm": "Histogram gradient-boosted trees (80 iterations, depth 4)",
        "target": "pump reaches failure condition within the next 72 run-hours",
        "features": ["motor current / nominal", "vibration / nominal", "discharge / rated", "run-hours"],
        "train_samples": int((~test).sum()), "test_samples": int(test.sum()),
        "split": "by pump: 80% of synthetic pumps train, 20% held out",
        "roc_auc": round(roc_auc_score(y[test], proba), 3),
        "brier": round(brier_score_loss(y[test], proba), 4),
        "precision": round(precision_score(y[test], pred, zero_division=0), 3),
        "recall": round(recall_score(y[test], pred, zero_division=0), 3),
        "pumps_flagged_before_failure": f"{len(leads)}/{len(failing)}",
        "median_lead_time_run_hours": round(float(np.median(leads)), 1) if leads else None,
        "flagged_more_than_240h_early": early,
        "tried_and_dropped": "isotonic calibration of the probability: no gain on held-out pumps (Brier score unchanged), so it is not used",
        "alert_rule": f"risk >= {C.PUMP_RISK_ALERT} for {C.PERSIST['pump_risk']} consecutive running samples",
        "seconds": round(time.time() - t0, 1),
    }
    report["pump_remaining_life"] = {
        "algorithm": "Wear index (linear, from current, vibration and discharge) extrapolated along the pump's own trend; "
                     "quantile gradient boosting on fleet histories when the trend is not yet clear",
        "evaluated_on": f"{len(f_err)} readings in the last 300 run-hours of held-out pumps",
        "wear_index_r2": round(float(lin.score(X[test][:, :3], wear[test])), 4),
        "own_trend_available": round(len(t_err) / max(1, len(f_err)), 3),
        "own_trend_median_error_h": round(float(np.median(t_err)), 1) if t_err else None,
        "own_trend_interval_coverage": round(float(np.mean(t_in)), 3) if t_in else None,
        "combined_median_error_h": round(float(np.median(b_err)), 1),
        "fleet_prior_median_error_h": round(float(np.median(f_err)), 1),
        "fleet_prior_interval_coverage": round(float(np.mean((q10 <= life[near]) & (life[near] <= q90))), 3),
        "fleet_prior_interval_coverage_before_widening": round(raw_cover, 3),
        "was": {"method": "no remaining-life estimate: only the 72-hour risk"},
        "note": "Synthetic pumps wear in a straight line, which flatters trend extrapolation; the own-trend interval is never "
                "narrower than -30% / +40% for that reason. The demo's 'pump wearing out' scenario wears the pump far faster "
                "than the fleet histories, which is why the estimate follows the pump's own trend first.",
    }
    return make().fit(X, y), {"models": rul, "widen": widen}, wear_model


# ------------------------------------------------------- complaint classifier
def _augment(lang: str, phrase: str) -> list[str]:
    aff = AFFIXES[lang]
    out = [phrase] + [f"{phrase} {s}" for s in aff["post"]] + [f"{p} {phrase}" for p in aff["pre"]]
    return [o.lower() for o in out]


def _nlp_model():
    return make_pipeline(TfidfVectorizer(analyzer="char_wb", ngram_range=(1, 4), sublinear_tf=True),
                         LogisticRegression(C=12.0, max_iter=600))


def train_nlp(report):
    t0 = time.time()
    rnd = random.Random(5)
    items = [(lang, cat, ph) for lang, cats in PHRASES.items() for cat in CATEGORIES for ph in cats[cat]]
    rnd.shuffle(items)
    newer = {it for it in items if it[2] in EXTRA[it[0]][it[1]]}  # the second batch of phrases
    folds = 5
    fold_of, per = {}, {}
    for it in items:  # stratified: every fold gets its share of each language and class
        k = per.get(it[:2], 0)
        fold_of[it] = k % folds
        per[it[:2]] = k + 1
    keywords = [(kw.lower(), cat) for lang in PHRASES for cat in CATEGORIES for kw in KEYWORDS[lang][cat]]

    def fit(train_items):
        tx = [v for it in train_items for v in _augment(it[0], it[2])] + [k for k, _c in keywords]
        ty = [it[1] for it in train_items for _v in _augment(it[0], it[2])] + [c for _k, c in keywords]
        return _nlp_model().fit(tx, ty), len(tx)

    pred = {}
    for f in range(folds):  # whole phrases are held out: the test never sees a variant of a training line
        clf, _n = fit([it for it in items if fold_of[it] != f])
        held = [it for it in items if fold_of[it] == f]
        pred.update(zip(held, clf.predict([it[2].lower() for it in held])))
    acc = lambda sub: round(accuracy_score([it[1] for it in sub], [pred[it] for it in sub]), 3)  # noqa: E731
    # what the first batch alone could do with wordings it had never seen: train on it, test on the second batch
    old, _n = fit([it for it in items if it not in newer])
    new_list = sorted(newer)
    old_acc = round(accuracy_score([it[1] for it in new_list], old.predict([it[2].lower() for it in new_list])), 3)
    full, n_train = fit(items)
    # and the fair before / after: the first batch of phrases, each held out, with and without the second batch in training
    first = [it for it in items if it not in newer]
    hits = 0
    for f in range(folds):
        clf, _n = fit([it for it in first if fold_of[it] != f])
        held = [it for it in first if fold_of[it] == f]
        hits += sum(p == it[1] for it, p in zip(held, clf.predict([it[2].lower() for it in held])))
    report["complaint_classifier"] = {
        "algorithm": "TF-IDF character n-grams (1-4) + multinomial logistic regression",
        "languages": list(PHRASES.keys()), "classes": CATEGORIES,
        "seed_phrases": len(items), "train_samples": n_train, "test_samples": len(items),
        "split": f"{folds}-fold cross-validation over whole seed phrases: every phrase is tested once by a model that never saw it or a variant of it",
        "accuracy": acc(items), "macro_f1": round(f1_score([it[1] for it in items], [pred[it] for it in items], average="macro"), 3),
        "accuracy_by_language": {lang: acc([it for it in items if it[0] == lang]) for lang in PHRASES},
        "accuracy_by_class": {cat: acc([it for it in items if it[1] == cat]) for cat in CATEGORIES},
        "accuracy_on_first_batch": acc(first), "accuracy_on_newer_phrases": acc(new_list),
        "was": {"method": f"same model with only the first {len(first)} phrases to learn from",
                "accuracy_on_first_batch": round(hits / len(first), 3), "accuracy_on_newer_phrases": old_acc},
        "reading": "More phrases helped on the first batch (each phrase held out in turn) and not on the newer batch, which the "
                   "earlier model already handled about as well without having seen it.",
        "tried_and_dropped": "adding word n-grams and cross-word character n-grams, and a linear SVM: within one point of "
                             "this model under the same folds, so the simpler one is kept. The gain came from more varied phrases.",
        "seconds": round(time.time() - t0, 1),
    }
    return full


# ----------------------------------------------------------------------- main
def train_all(verbose: bool = False) -> dict:
    t0 = time.time()
    report: dict = {}
    curves, main, profile, forest, if_scale, det, fault_clf, cal, shots = train_branch_models(report)
    pump, rul, wear = train_pump_model(report)
    nlp = train_nlp(report)
    card = {
        "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "data": "100% synthetic, generated by the JalSakhi village simulator",
        "status": "Proof of concept. Not validated on field data.",
        "scikit_learn": sklearn.__version__,
        "models": report,
        "sensor_study": sensor_study(cal, shots),
        "limits": [
            "Trained and evaluated only on simulator output; the simulator's physics is simpler than a real network.",
            "Injected faults are clean single faults; real faults overlap, drift and coincide with sensor errors.",
            "The leak locator assumes the shape the simulator gives a leak (loss ramps up to it, flat beyond). Real pipes follow "
            "the same physics less tidily, and the position error will be larger.",
            "Pump histories are synthetic run-to-failure curves, not real maintenance records.",
            "Complaint classifier is trained on a few hundred hand-written phrases, not real grievance text.",
            "Field use needs authorised historical data, time-split validation and a pilot calibration period.",
        ],
        "train_seconds": round(time.time() - t0, 1),
    }
    bundle = {"format": M.FORMAT, "spec_hash": M.spec_hash(), "curves": curves, "main": main, "profile": profile, "det": det,
              "iforest": forest, "if_scale": if_scale, "fault": fault_clf, "pump": pump, "rul": rul,
              "wear": wear, "nlp": nlp, "card": card}
    C.MODEL_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, M.BUNDLE_PATH, compress=3)
    M.CARD_PATH.write_text(json.dumps(card, indent=2, ensure_ascii=False), encoding="utf-8")
    if verbose:
        print(json.dumps(card, indent=2, ensure_ascii=False))
    return bundle


if __name__ == "__main__":
    train_all(verbose=True)

"""Runtime side of the ML layer: feature construction, model loading, inference.

Models (all trained on simulator output; see train.py and the model card):
  * calibrated hydraulic model      least-squares head-loss curve at every measured point of a lane, and tank
                                    head / main loss per village; gives pressure residuals and drives the what-if planner
  * demand profile                  mean / sd of per-household flow by minute of window, scaled per lane
  * sequential change detector      CUSUM on the tail pressure residual: raises on accumulated evidence
  * IsolationForest                 multivariate anomaly score over the lane features
  * fault classifier                gradient-boosted trees: leak or obstruction, from the residual pattern
  * leak locator                    fits "loss ramps up to the leak, then stays flat" to the residuals along the lane
  * pump failure risk               gradient-boosted trees
  * pump remaining life             quantile gradient boosting (fleet prior) + the pump's own wear trend
  * complaint classifier            character n-gram TF-IDF, logistic regression, six languages
"""
from __future__ import annotations

import hashlib
import json
import logging
from collections import deque

import joblib
import numpy as np

from .. import config as C
from ..seed import VILLAGES
from ..sim import world
from .nlp_corpus import URGENCY_TERMS

log = logging.getLogger("jalsakhi.ml")

BUCKET_MIN = 5
N_BUCKETS = 36
BUNDLE_PATH = C.MODEL_DIR / "bundle.joblib"
CARD_PATH = C.MODEL_DIR / "model_card.json"
FORMAT = 5
WINDOW = 8  # samples of recent lane history the classifier and the locator look at
RUL_CAP_H = 500.0  # the fleet model does not try to tell 500 run-hours from 5000
FAULT_FEATURES = ["tail residual (z)", "flow vs demand (z)", "excess flow / expected", "loss / entry pressure",
                  "residual at tap 1 / tail", "residual at tap 2 / tail", "residual at tap 3 / tail"]


def spec_hash() -> str:
    """Models are specific to the simulated network; retrain when it changes."""
    key = json.dumps([[v["id"], v["branches"], v["uphill"], v["tank_kl"], v["pump_lpm"], v["seed"]] for v in VILLAGES]
                     + [world.H0, world.H1, world.R_MAIN, world.R_BRANCH, world.LEAK_DROP, C.FILL_LPCD, C.BG_RATE,
                        C.SUPPLY_WINDOWS, FORMAT])
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def cusum_step(s: float, z: float, k: float, cap: float, top: float) -> float:
    """One step of a one-sided CUSUM. `cap` limits what a single reading can add, so a two-minute
    transient cannot raise an alarm by itself; `top` stops the sum running away during a long fault,
    so it comes back down within a few readings of the repair."""
    return min(top, max(0.0, s + min(z, cap) - k))


class BranchTracker:
    """Rolling feature state for one branch; identical code path in training and live scoring."""

    ALPHA = 0.35

    def __init__(self, n_hh: int, q_nom: float, curve: dict, profile: dict, det: dict, elevs: list[float]):
        """elevs: surveyed elevation (bar of head) of each calibrated point, from the asset register."""
        self.n, self.q_nom = n_hh, q_nom
        self.elevs = elevs
        self.a, self.c = curve["a"], curve["c"]
        self.sigma = max(curve["sigma"], 0.012)
        self.scale = curve.get("q_scale", 1.0)
        self.pts = curve["pts"]  # calibrated points along the lane: metered taps in order, then the tail
        self.mu, self.sd = profile["mu"], profile["sd"]
        self.k, self.h, self.cap = det["k"], det["h"], det["cap"]
        self.ewma = 0.0
        self.win = None
        self.cusum = 0.0
        self.hist: deque = deque(maxlen=WINDOW)

    def update(self, w: int, m: float, p_in: float, p_end: float | None, q: float, taps: list | None = None) -> dict:
        """taps: pressure at each metered tap in lane order (None where silent)."""
        if w != self.win:
            self.win, self.ewma, self.cusum = w, q, 0.0
            self.hist.clear()
        else:
            self.ewma = self.ALPHA * q + (1 - self.ALPHA) * self.ewma
        bucket = min(N_BUCKETS - 1, int(m // BUCKET_MIN))
        u = (q / self.q_nom) ** 2
        exp_dp = self.a + self.c * u
        q_hh = self.ewma / self.n
        mu, sd = self.mu[w][bucket] * self.scale, max(self.sd[w][bucket] * self.scale, 0.25)
        z_q = float(np.clip((q_hh - mu) / sd, -10, 10))
        # loss of hydraulic grade from the lane entry to each calibrated point, against its learned curve
        rb: list = []
        for pt, el, p in zip(self.pts, self.elevs, list(taps or [None] * (len(self.pts) - 1)) + [p_end]):
            rb.append(None if p is None else (p_in - (p + el)) - (pt["a"] + pt["c"] * u))
        if p_end is None:
            out = {"r": None, "z_r": 0.0, "z_q": z_q, "ratio": None, "q_hh": q_hh, "exp_dp": exp_dp, "exp_q": mu * self.n,
                   "x": None, "rb": rb, "cusum": self.cusum, "q": q, "p_in": p_in, "u": u}
            return out
        r = (p_in - p_end) - exp_dp
        z_r = float(np.clip(r / self.sigma, -25, 25))
        ratio = p_end / max(p_in, 0.05)
        self.cusum = cusum_step(self.cusum, z_r, self.k, self.cap, self.h + 4 * self.k)
        out = {"r": r, "z_r": z_r, "z_q": z_q, "ratio": ratio, "q_hh": q_hh, "exp_dp": exp_dp, "exp_q": mu * self.n,
               "x": [z_r, z_q, ratio], "rb": rb, "cusum": self.cusum, "q": q, "p_in": p_in, "u": u}
        self.hist.append(out)
        return out

    def expected_loss(self, x: float, u: float) -> float:
        """Learned healthy loss of grade from the entry to a point x (0..1) along the lane at flow ratio u."""
        xs = [0.0] + [pt["x"] for pt in self.pts]
        ys = [0.0] + [pt["a"] + pt["c"] * u for pt in self.pts]
        return float(np.interp(x, xs, ys))


def window_means(hist) -> dict | None:
    """Mean residual at every calibrated point over the recent window (bar), plus what the classifier needs."""
    h = [s for s in hist if s.get("r") is not None]
    if len(h) < 3:
        return None
    n_pts = len(h[-1]["rb"])
    rb = []
    for j in range(n_pts):
        vals = [s["rb"][j] for s in h if s["rb"][j] is not None]
        rb.append(float(np.mean(vals)) if len(vals) >= 2 else None)
    return {"n": len(h), "rb": rb, "z_r": float(np.mean([s["z_r"] for s in h])), "z_q": float(np.mean([s["z_q"] for s in h])),
            "excess": float(np.mean([(s["q"] - s["exp_q"]) / max(s["exp_q"], 1.0) for s in h])),
            "p_in": float(np.mean([s["p_in"] for s in h]))}


def fault_features(wm: dict) -> list[float]:
    """Feature row for the leak / obstruction classifier (see FAULT_FEATURES). NaN where a tap is silent."""
    tail = wm["rb"][-1]
    taps = (wm["rb"][:-1] + [None, None, None])[:3]
    shape = [float(np.clip(t / tail, -0.5, 1.5)) if (t is not None and tail is not None and tail > 0.015) else np.nan for t in taps]
    return [wm["z_r"], wm["z_q"], wm["excess"], (tail or 0.0) / max(wm["p_in"], 0.05), *shape]


GRID = np.linspace(0.04, 1.0, 97)


def locate_leak(xs: list[float], rb: list, sigmas: list[float], n: int) -> dict | None:
    """Where along the lane is the leak?

    Extra flow runs through the pipe only upstream of a leak, so the unexplained loss of grade climbs
    to the leak and is flat beyond it. Fit that shape (position x, size D) to the mean residuals at the
    measured points by weighted least squares; the range of x that fits nearly as well is the uncertainty.
    """
    pts = [(x, r, s) for x, r, s in zip(xs, rb, sigmas) if r is not None]
    if len(pts) < 2:
        return None
    X, R = np.array([p[0] for p in pts]), np.array([p[1] for p in pts])
    S = np.array([p[2] for p in pts]) / np.sqrt(max(1.0, n / 2.0))  # neighbouring readings share model error: count half
    M = np.minimum(X[None, :] / GRID[:, None], 1.0)
    W = 1.0 / S ** 2
    D = np.maximum((M * R * W).sum(1) / (M * M * W).sum(1), 0.0)
    chi = (((R[None, :] - D[:, None] * M) ** 2) * W).sum(1)
    k = int(np.argmin(chi))
    if D[k] < 0.03:
        return None
    ok = chi <= chi[k] + 2.71  # about a 90% interval for one fitted parameter
    return {"x": float(GRID[k]), "x0": float(GRID[ok].min()), "x1": float(GRID[ok].max()), "drop_bar": float(D[k])}


def bracket_step(xs: list[float], rb: list) -> dict | None:
    """An obstruction is a step in the loss: it can only be placed between the two measured points it falls between."""
    pts = [(0.0, 0.0)] + [(x, r) for x, r in zip(xs, rb) if r is not None]
    if len(pts) < 3:
        return None
    peak = max(r for _x, r in pts)
    if peak < 0.06:
        return None
    jumps = [(pts[k][1] - pts[k - 1][1], k) for k in range(1, len(pts))]
    jump, k = max(jumps)
    if jump < max(0.04, 0.3 * peak):
        return None
    return {"x": (pts[k - 1][0] + pts[k][0]) / 2, "x0": pts[k - 1][0], "x1": pts[k][0], "drop_bar": float(peak)}


def pump_features(current_a: float, vibration: float, discharge: float, i_nom: float, v_nom: float, rate: float,
                  age_h: float) -> list[float]:
    return [current_a / i_nom, vibration / v_nom, discharge / rate, age_h]


def trend_rul(run_h, wear) -> dict | None:
    """Remaining life from this pump's own wear trend: straight-line fit of the wear index against run-hours,
    extrapolated to the failure level (index 1.0). None unless the slope is clearly upward."""
    t, w = np.asarray(run_h, dtype=float), np.asarray(wear, dtype=float)
    if len(t) < 8 or t[-1] - t[0] <= 0:
        return None
    tc = t - t.mean()
    sxx = float((tc ** 2).sum())
    slope = float((tc * (w - w.mean())).sum() / sxx)
    resid = w - (w.mean() + slope * tc)
    se = float(np.sqrt((resid ** 2).sum() / max(1, len(t) - 2) / sxx))
    if slope <= 0 or slope < 3.0 * se:
        return None
    now = float(w.mean() + slope * tc[-1])
    left = max(0.0, 1.0 - now)
    h = left / slope  # the interval is never tighter than -30% / +40%: real wear is not a straight line
    return {"h": h, "lo": min(left / (slope + 1.64 * se), 0.7 * h), "hi": max(left / max(slope - 1.64 * se, slope * 0.25), 1.4 * h),
            "rate_per_h": slope, "wear": now}


def _avg_path(n: np.ndarray) -> np.ndarray:
    """Average path length of an unsuccessful BST search (the isolation-forest normaliser c(n))."""
    n = n.astype(float)
    out = np.zeros_like(n)
    big = n > 2
    out[n == 2] = 1.0
    out[big] = 2.0 * (np.log(n[big] - 1.0) + np.euler_gamma) - 2.0 * (n[big] - 1.0) / n[big]
    return out


class FastForest:
    """Scores a fitted scikit-learn IsolationForest by walking all trees at once in numpy.

    Same maths as IsolationForest.score_samples, without the per-call joblib overhead (about 30 ms
    per call, which matters when scoring every branch every tick).
    """

    def __init__(self, forest):
        trees = [e.tree_ for e in forest.estimators_]
        feats = forest.estimators_features_
        width = max(t.node_count for t in trees)
        n = len(trees)
        self.left = np.full((n, width), -1, dtype=np.int64)
        self.right = np.full((n, width), -1, dtype=np.int64)
        self.feat = np.zeros((n, width), dtype=np.int64)
        self.thr = np.zeros((n, width), dtype=np.float64)
        self.leaf = np.zeros((n, width), dtype=np.float64)
        self.depth = 0
        for k, t in enumerate(trees):
            m = t.node_count
            self.left[k, :m], self.right[k, :m] = t.children_left, t.children_right
            inner = t.children_left >= 0
            self.feat[k, :m][inner] = np.asarray(feats[k])[t.feature[inner]]
            self.thr[k, :m] = t.threshold
            depth = np.zeros(m)
            for node in range(m):  # children always have a larger index than their parent
                if inner[node]:
                    depth[t.children_left[node]] = depth[t.children_right[node]] = depth[node] + 1
            self.leaf[k, :m] = depth + _avg_path(t.n_node_samples)
            self.depth = max(self.depth, int(depth.max()))
        self.norm = float(_avg_path(np.array([forest.max_samples_]))[0])
        self.rows = np.arange(n)[:, None]

    def raw(self, X: np.ndarray) -> np.ndarray:
        """Anomaly score in (0, 1]; equals -IsolationForest.score_samples(X)."""
        X = np.asarray(X, dtype=np.float32).astype(np.float64)  # scikit-learn trees compare in float32
        cols = np.arange(X.shape[0])[None, :]
        node = np.zeros((self.left.shape[0], X.shape[0]), dtype=np.int64)
        for _ in range(self.depth + 1):
            nxt_left = self.left[self.rows, node]
            at_leaf = nxt_left < 0
            if at_leaf.all():
                break
            go_left = X[cols, self.feat[self.rows, node]] <= self.thr[self.rows, node]
            node = np.where(at_leaf, node, np.where(go_left, nxt_left, self.right[self.rows, node]))
        return 2.0 ** (-self.leaf[self.rows, node].mean(axis=0) / self.norm)


class Models:
    """Loaded model bundle with small inference helpers."""

    def __init__(self, bundle: dict):
        self.b = bundle
        self.curves = bundle["curves"]
        self.main = bundle["main"]
        self.profile = bundle["profile"]
        self.det = bundle["det"]
        self.iforest = bundle["iforest"]
        self.fast = FastForest(self.iforest)
        self.if_lo, self.if_hi = bundle["if_scale"]
        self.fault = bundle["fault"]
        self.pump = bundle["pump"]
        self.rul = bundle["rul"]
        self.wear = bundle["wear"]
        self.nlp = bundle["nlp"]
        self.card = bundle["card"]
        self.pump_risk([1.0, 1.0, 1.0, 900.0])  # warm up: the first predict call does one-off setup work
        self.pump_life([1.0, 1.0, 1.0, 900.0])

    def tracker(self, branch_id: str, n_hh: int, q_nom: float, elevs: list[float]) -> BranchTracker:
        return BranchTracker(n_hh, q_nom, self.curves[branch_id], self.profile, self.det, elevs)

    def anomaly(self, rows: list[list[float]]) -> np.ndarray:
        """0..1 anomaly score; the alert threshold sits well outside the normal training range."""
        if not rows:
            return np.zeros(0)
        raw = self.fast.raw(np.asarray(rows, dtype=float))
        return np.clip((raw - self.if_lo) / (self.if_hi - self.if_lo), 0.0, 1.0)

    def fault_type(self, wm: dict) -> float:
        """Probability that an abnormal loss of pressure on a lane is a leak (rather than an obstruction)."""
        return float(self.fault.predict_proba(np.asarray([fault_features(wm)], dtype=float))[0, 1])

    def pump_risk(self, feats: list[float]) -> float:
        return float(self.pump.predict_proba(np.asarray([feats], dtype=float))[0, 1])

    def wear_index(self, feats: list[float]) -> float:
        """Share of the pump's wear life used (0 new, 1 failure level), learned from run-to-failure histories."""
        return float(np.clip(self.wear["b"] + float(np.dot(self.wear["w"], feats[:3])), 0.0, 1.2))

    def pump_life(self, feats: list[float]) -> dict:
        """Fleet prior for remaining run-hours: 10th, 50th and 90th percentile, capped at RUL_CAP_H."""
        X = np.asarray([feats], dtype=float)
        lo, mid, hi = sorted(float(m.predict(X)[0]) for m in self.rul["models"])
        return {"h": max(0.0, mid), "lo": max(0.0, lo - self.rul["widen"]), "hi": min(RUL_CAP_H, hi + self.rul["widen"])}

    def classify(self, text: str) -> dict:
        text = (text or "").strip()
        if len(text) < 3:
            return {"category": None, "confidence": 0.0, "urgency": "normal", "top": []}
        proba = self.nlp.predict_proba([text.lower()])[0]
        classes = list(self.nlp.classes_)
        order = np.argsort(proba)[::-1]
        low = text.lower()
        urgent = any(term in low for term in URGENCY_TERMS)
        return {"category": classes[order[0]], "confidence": round(float(proba[order[0]]), 3),
                "urgency": "high" if urgent else "normal",
                "top": [{"category": classes[i], "p": round(float(proba[i]), 3)} for i in order[:3]]}

    def demand_per_home(self, w: int, m: float) -> float:
        return float(self.profile["mu"][w][min(N_BUCKETS - 1, int(m // BUCKET_MIN))])

    def expected_demand_lpm(self, w: int, m: float, n_hh: int) -> float:
        return self.demand_per_home(w, m) * n_hh


_models: Models | None = None


def get_models(force_train: bool = False) -> Models:
    global _models
    if _models is not None and not force_train:
        return _models
    bundle = None
    if BUNDLE_PATH.exists() and not force_train:
        try:
            bundle = joblib.load(BUNDLE_PATH)
            if bundle.get("spec_hash") != spec_hash():
                log.info("model bundle is for a different network spec; retraining")
                bundle = None
        except Exception as exc:  # e.g. scikit-learn version mismatch
            log.warning("could not load model bundle (%s); retraining", exc)
            bundle = None
    if bundle is None:
        from .train import train_all
        log.info("training models on simulator output (first run only, about two minutes)...")
        bundle = train_all()
    _models = Models(bundle)
    return _models

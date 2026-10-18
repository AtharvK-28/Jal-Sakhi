"""Telemetry ingestion: validation, idempotency, latest values, short history, freshness."""
from __future__ import annotations

import json
from collections import OrderedDict, defaultdict, deque
from datetime import datetime

from .. import config as C

SERIES_LEN = 420
KEEP_ROWS = 120_000  # telemetry rows retained in SQLite before pruning the oldest
UNITS = {
    "pressure_bar": "bar", "flow_lpm": "L/min", "level_pct": "%", "volume_l": "L", "current_a": "A",
    "vibration_mms": "mm/s", "discharge_lpm": "L/min", "depth_m": "m", "turbidity_ntu": "NTU",
    "chlorine_mgl": "mg/L", "ph": "", "tds_mgl": "mg/L", "cmd": "", "state": "",
}
LIMITS = {  # physically plausible ranges; values outside are rejected as corrupt
    "pressure_bar": (0, 16), "flow_lpm": (0, 5000), "level_pct": (0, 100), "volume_l": (0, 1e7),
    "current_a": (0, 200), "vibration_mms": (0, 100), "discharge_lpm": (0, 5000), "depth_m": (0, 500),
    "turbidity_ntu": (0, 4000), "chlorine_mgl": (0, 20), "ph": (0, 14), "tds_mgl": (0, 50000),
    "cmd": (0, 1), "state": (0, 1),
}


class TelemetryStore:
    def __init__(self, db, devices: dict[str, dict]):
        self.db = db
        self.devices = devices
        self.latest: dict[str, dict] = {}
        self.series: dict[tuple, deque] = defaultdict(lambda: deque(maxlen=SERIES_LEN))
        self.missed: dict[str, int] = defaultdict(int)
        self._reported: set[str] = set()
        self._pending: list[tuple] = []
        self._seen: OrderedDict[str, None] = OrderedDict()
        self.total = self.rejected = self.duplicates = 0
        self._since_prune = 0

    # ------------------------------------------------------------- ingestion
    def validate(self, ev: dict) -> str | None:
        """Return an error string for a bad external payload, else None."""
        dev = self.devices.get(ev.get("device_id"))
        if dev is None:
            return "unknown device_id"
        if not ev.get("event_id"):
            return "event_id is required"
        try:
            ts = datetime.fromisoformat(str(ev.get("ts")))
        except ValueError:
            return "ts must be an ISO-8601 timestamp"
        if ts.tzinfo is None:
            return "ts must include a timezone offset"
        metrics = ev.get("metrics")
        if not isinstance(metrics, dict) or not metrics:
            return "metrics must be a non-empty object"
        for name, value in metrics.items():
            if name not in dev["metrics"]:
                return f"metric '{name}' is not registered for this device"
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return f"metric '{name}' must be a number"
            lo, hi = LIMITS.get(name, (-1e12, 1e12))
            if not lo <= value <= hi:
                return f"metric '{name}'={value} outside plausible range {lo}..{hi}"
        return None

    def accept(self, device_id: str, ts: datetime, metrics: dict, *, event_id: str, source: str = "simulation",
               quality: str = "good", received: datetime | None = None, tick: int = 0) -> bool:
        """Store one reading. Returns False if event_id was already ingested (idempotent retry)."""
        if event_id in self._seen:
            self.duplicates += 1
            return False
        self._seen[event_id] = None
        if len(self._seen) > 20_000:
            self._seen.popitem(last=False)
        dev = self.devices[device_id]
        iso = ts.isoformat(timespec="seconds")
        self.latest[device_id] = {"ts": iso, "m": metrics, "source": source, "quality": quality, "tick": tick}
        minute = int(ts.timestamp() // 60)
        for name, value in metrics.items():
            self.series[(device_id, name)].append((minute, value))
        self._reported.add(device_id)
        self.missed[device_id] = 0
        self._pending.append((event_id, device_id, dev["village_id"], dev["entity_type"], dev["entity_id"], iso,
                              json.dumps(metrics, separators=(",", ":")), source, quality,
                              (received or ts).isoformat(timespec="seconds")))
        self.total += 1
        return True

    def end_tick(self, expected: list[str]):
        """Count a missed report for every expected device that stayed silent this tick."""
        for dev_id in expected:
            if dev_id not in self._reported:
                self.missed[dev_id] += 1
        self._reported.clear()

    def flush(self, persist: bool = True):
        if not self._pending:
            return
        rows, self._pending = self._pending, []
        if not persist:  # fast-forwarded ticks keep readings in memory only
            return
        self.db.executemany(
            "INSERT OR IGNORE INTO telemetry (event_id, device_id, village_id, entity_type, entity_id, ts, metrics,"
            " source, quality, received_at) VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
        self._since_prune += len(rows)
        if self._since_prune > 20_000:
            self._since_prune = 0
            top = self.db.scalar("SELECT MAX(id) FROM telemetry") or 0
            self.db.execute("DELETE FROM telemetry WHERE id < ?", (top - KEEP_ROWS,))

    # --------------------------------------------------------------- reading
    def status(self, device_id: str) -> str:
        if device_id not in self.latest:
            return "never" if self.missed[device_id] < C.OFFLINE_MISSED else "offline"
        m = self.missed[device_id]
        return "offline" if m >= C.OFFLINE_MISSED else "stale" if m >= C.STALE_MISSED else "online"

    def fresh(self, device_id: str) -> bool:
        return device_id in self.latest and self.missed[device_id] < C.STALE_MISSED

    def value(self, device_id: str, metric: str, default=None):
        rec = self.latest.get(device_id)
        return rec["m"].get(metric, default) if rec else default

    def history(self, device_id: str, metric: str, limit: int = 180) -> list[list]:
        return [[m, v] for m, v in list(self.series.get((device_id, metric), ()))[-limit:]]

    def recent_mean(self, device_id: str, metric: str, n: int) -> float | None:
        s = self.series.get((device_id, metric))
        if not s:
            return None
        vals = [v for _m, v in list(s)[-n:]]
        return sum(vals) / len(vals)

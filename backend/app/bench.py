"""Load test: how much can one process carry, and what does a year of readings weigh?

    python run.py --bench        (or, from backend/:  python -m app.bench)

Runs the whole platform (simulator, ingestion, estimation, detection, storage) in a throwaway data
folder and times it, then posts readings through the HTTP ingest route. The result is written to
models/scale_bench.json and shown on the Trust & roadmap page.

What the numbers mean, and do not: they are for this machine, one process, SQLite, with the village
simulator running alongside the monitoring it feeds (a deployment would not pay for the simulator).
They size a pilot. They are not a capacity claim for a production stack.
"""
from __future__ import annotations

import json
import os
import platform
import tempfile
import time

_tmp = tempfile.mkdtemp(prefix="jalsakhi-bench-")  # must be set before the app reads its configuration
os.environ["JALSAKHI_DATA"] = _tmp
os.environ["JALSAKHI_PAUSED"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

from . import config as C  # noqa: E402
from . import main  # noqa: E402

TICKS, POSTS = 150, 1500
HEADROOM = 0.5  # plan to use half of what was measured


def run() -> dict:
    with TestClient(main.app) as client:
        P = main.P
        villages, homes, devices = len(P.sims), len(P.households), len(P.sim_device_ids)
        for _ in range(20):  # settle into the supply window
            P.step()
        before = P.telemetry.total
        t0 = time.perf_counter()
        for _ in range(TICKS):
            P.step()
        tick_ms = (time.perf_counter() - t0) / TICKS * 1000
        readings_per_tick = (P.telemetry.total - before) / TICKS

        t0 = time.perf_counter()
        for n in range(POSTS):
            r = client.post("/api/telemetry", headers={"X-Device-Key": C.DEVICE_KEY}, json={
                "event_id": f"bench-{n}", "device_id": main.HW_DEVICE, "ts": P.now.isoformat(timespec="seconds"),
                "metrics": {"pressure_bar": 1.1, "flow_lpm": 6.0}, "source": "hardware"})
            assert r.status_code == 201, r.text
        ingest_per_s = POSTS / (time.perf_counter() - t0)

        rows = P.db.scalar("SELECT COUNT(*) FROM telemetry") or 1
        size = sum(f.stat().st_size for f in C.DATA_DIR.glob("jalsakhi.db*"))
        bytes_per_reading = size / rows
        day_ticks = sum(e - s for s, e, _l in C.SUPPLY_WINDOWS) + (1440 - sum(e - s for s, e, _l in C.SUPPLY_WINDOWS)) / C.IDLE_DT_MIN
        per_village_ms = tick_ms / villages
        by_compute = int(60_000 / per_village_ms)  # villages whose minute of readings fits in a minute of one core
        by_ingest = int(ingest_per_s * 60 / (devices / villages))  # villages whose devices can all post once a minute
        return {
            "measured": True, "measured_at": time.strftime("%Y-%m-%d %H:%M"),
            "machine": {"cpu": platform.processor() or platform.machine(), "cores": os.cpu_count(), "os": f"{platform.system()} {platform.release()}",
                        "python": platform.python_version()},
            "villages": villages, "households": homes, "devices": devices,
            "tick_ms": round(tick_ms, 1), "per_village_ms": round(per_village_ms, 2), "readings_per_tick": round(readings_per_tick),
            "villages_by_compute": by_compute, "villages_by_ingest": by_ingest,
            "limit": "ingest" if by_ingest < by_compute else "compute",
            "villages_planned": int(min(by_compute, by_ingest) * HEADROOM), "headroom": HEADROOM,
            "ingest_per_s": round(ingest_per_s), "bytes_per_reading": round(bytes_per_reading),
            "gb_per_village_year": round(readings_per_tick / villages * day_ticks * 365 * bytes_per_reading / 1e9, 2),
            "basis": "one process, SQLite, one reading per device per minute while water is being supplied; the village simulator "
                     "runs inside the measured loop. The ingest route commits every reading by itself, which is what limits it.",
        }


if __name__ == "__main__":
    result = run()
    C.MODEL_DIR.mkdir(parents=True, exist_ok=True)
    (C.MODEL_DIR / "scale_bench.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))

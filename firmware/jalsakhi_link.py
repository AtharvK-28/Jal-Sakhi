"""Shared by the bench tools: build a telemetry event and post it to the JalSakhi ingest API."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))
DEVICE_ID = "HW-NODE-01"
SERVER = "http://127.0.0.1:8000"
KEY = "demo-device-key"

# what a tap on a healthy lane reads in each state: (pressure in bar, flow in L/min). Same table as the firmware.
STATES = {"open": (1.15, 6.0), "pinched": (0.28, 1.6), "closed": (0.02, 0.0)}


def post(server: str, key: str, event_id: str, metrics: dict, quality: str = "good") -> str:
    """Send one reading. Returns 'stored', 'duplicate', or a short description of what went wrong."""
    body = json.dumps({"event_id": event_id, "device_id": DEVICE_ID, "ts": datetime.now(IST).isoformat(timespec="seconds"),
                       "metrics": metrics, "source": "hardware", "quality": quality}).encode()
    req = urllib.request.Request(server.rstrip("/") + "/api/telemetry", data=body,
                                 headers={"Content-Type": "application/json", "X-Device-Key": key})
    try:
        with urllib.request.urlopen(req, timeout=4) as r:
            return "stored" if r.status == 201 else "duplicate"
    except urllib.error.HTTPError as exc:
        return f"rejected ({exc.code}: {exc.read().decode(errors='replace')[:120]})"
    except OSError as exc:
        return f"server not reachable ({exc})"

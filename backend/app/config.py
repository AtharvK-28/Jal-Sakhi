"""Central configuration for the JalSakhi AI proof of concept.

Every number here is a simulation/demo parameter. Where a public reference
value exists (JJM 55 lpcd service level, IS 10500:2012 drinking-water limits)
it is named as a reference; it is never presented as a field-validated setting.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

APP_NAME = "JalSakhi AI"
APP_VERSION = "1.0.0-poc"

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("JALSAKHI_DATA", BASE_DIR / "data"))
DB_PATH = Path(os.environ.get("JALSAKHI_DB", DATA_DIR / "jalsakhi.db"))
UPLOAD_DIR = DATA_DIR / "uploads"
MODEL_DIR = Path(os.environ.get("JALSAKHI_MODELS", BASE_DIR / "models"))
FRONTEND_DIST = BASE_DIR.parent / "frontend" / "dist"

# --------------------------------------------------------------------------
# Simulation clock
# --------------------------------------------------------------------------
IST = timezone(timedelta(hours=5, minutes=30))
SIM_START = datetime(2026, 10, 5, 5, 54, tzinfo=IST)

# (start minute-of-day, end minute-of-day, label). Demo supply schedule.
SUPPLY_WINDOWS = [(6 * 60, 9 * 60, "Morning"), (17 * 60, 20 * 60, "Evening")]
WINDOW_SHARE = [0.56, 0.44]  # share of the daily fill demand per window
WINDOW_GRACE_MIN = 4  # pipes pressurise; rules wait this long after a window opens

TICK_SECONDS = 1.0  # wall-clock seconds per tick at 1x speed
IDLE_DT_MIN = 10  # sim-minutes per tick outside supply windows
SPEEDS = [1, 2, 5, 10]  # ticks per wall-clock second

# --------------------------------------------------------------------------
# Service norms and reference values
# --------------------------------------------------------------------------
LPCD_NORM = 55  # JJM service level: litres per capita per day
FILL_LPCD = 50  # storage-filling demand used by the household demand model
BG_RATE = 0.0045  # background tap-use start probability per member per minute

# IS 10500:2012 reference limits. Sensors here are screening instruments:
# crossing a limit triggers verification (FTK / lab), never a potability verdict.
QUALITY_LIMITS = {
    "turbidity_ntu": {"acceptable": 1.0, "permissible": 5.0, "unit": "NTU"},
    "chlorine_mgl": {"min": 0.2, "max": 1.0, "unit": "mg/L"},
    "ph": {"min": 6.5, "max": 8.5, "unit": ""},
    "tds_mgl": {"acceptable": 500.0, "permissible": 2000.0, "unit": "mg/L"},
}

# --------------------------------------------------------------------------
# Detection thresholds (pressures in bar, flows in L/min)
# --------------------------------------------------------------------------
P_OK = 0.50  # at or above: tap delivers usable pressure
P_DRY = 0.15  # below: effectively no water
P_LOW_TRIGGER = 0.50
P_LOW_CLEAR = 0.60
PERSIST = {  # consecutive samples a condition must hold before an incident is raised
    "interruption": 4,
    "low_pressure": 5,
    "leak": 5,
    "quality": 4,
    "pump": 3,
    "anomaly": 8,
    "pump_risk": 5,
    "tank_low": 3,
    "tap": 4,
}
CLEAR_SAMPLES = 5  # consecutive clear samples before recovery is recorded
STALE_MISSED = 3  # missed reports before a device is shown as stale
OFFLINE_MISSED = 8  # missed reports before a sensor-offline incident is raised
COOLDOWN_MIN = 10  # sim-minutes before a closed condition may re-raise
TAP_DROP_BAR = 0.25  # a metered tap this far below the next measured point downstream has a fault of its own
LEAK_Z_FLOW = 2.0  # mean flow-vs-profile z needed to call a pressure loss "suspected leakage"
ANOMALY_SCORE = 0.72
PUMP_RISK_ALERT = 0.60
CLUSTER_MIN_REPORTS = 3
CLUSTER_WINDOW_MIN = 45

# SLA in sim-minutes: (acknowledge within, resolve within)
SLA = {
    "critical": (15, 240),
    "high": (30, 480),
    "medium": (60, 1440),
    "low": (120, 2880),
}
SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3, "critical": 4}

# --------------------------------------------------------------------------
# Security (demo-grade: clearly labelled as such in the UI)
# --------------------------------------------------------------------------
SECRET_KEY = os.environ.get("JALSAKHI_SECRET", "jalsakhi-demo-secret-change-me")
DEVICE_KEY = os.environ.get("JALSAKHI_DEVICE_KEY", "demo-device-key")
TOKEN_TTL_HOURS = 12
DEMO_PASSWORD = "jal123"
MAX_UPLOAD_BYTES = 5 * 1024 * 1024

LANGUAGES = {
    "en": "English",
    "hi": "हिन्दी",
    "mr": "मराठी",
    "bn": "বাংলা",
    "ta": "தமிழ்",
    "te": "తెలుగు",
}


def window_at(minute_of_day: float):
    """Return (index, minutes into window) if a supply window is active."""
    for i, (start, end, _label) in enumerate(SUPPLY_WINDOWS):
        if start <= minute_of_day < end:
            return i, minute_of_day - start
    return None, 0.0


def next_window_start(now: datetime) -> datetime:
    mod = now.hour * 60 + now.minute
    for start, _end, _label in SUPPLY_WINDOWS:
        if mod < start:
            return now.replace(hour=start // 60, minute=start % 60, second=0, microsecond=0)
    first = SUPPLY_WINDOWS[0][0]
    tomorrow = now + timedelta(days=1)
    return tomorrow.replace(hour=first // 60, minute=first % 60, second=0, microsecond=0)

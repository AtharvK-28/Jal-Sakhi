"""SQLite persistence. One connection guarded by a lock; repositories sit on top.

SQLite keeps the PoC to a single file with zero setup. Queries are plain SQL
with no SQLite-only features in the hot paths, so moving to PostgreSQL/PostGIS
means swapping this module, not the services that call it.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS admin_units (
  id TEXT PRIMARY KEY, level TEXT NOT NULL, name TEXT NOT NULL, parent_id TEXT, lat REAL, lon REAL);

CREATE TABLE IF NOT EXISTS villages (
  id TEXT PRIMARY KEY, code TEXT, name TEXT, gp_id TEXT, block_id TEXT, district_id TEXT, state_id TEXT,
  lat REAL, lon REAL, households INTEGER, branches INTEGER, lang TEXT, scheme JSON, external_ids JSON, demo INTEGER DEFAULT 1);

CREATE TABLE IF NOT EXISTS households (
  id TEXT PRIMARY KEY, village_id TEXT NOT NULL, branch_id TEXT NOT NULL, branch_idx INTEGER, label TEXT,
  position INTEGER, x REAL, members INTEGER, instrumented INTEGER, lane TEXT, lat REAL, lon REAL,
  fhtc_ext_id TEXT, demo INTEGER DEFAULT 1);
CREATE INDEX IF NOT EXISTS ix_hh_village ON households(village_id, branch_id);

CREATE TABLE IF NOT EXISTS assets (
  id TEXT PRIMARY KEY, village_id TEXT NOT NULL, type TEXT NOT NULL, name TEXT, parent_id TEXT,
  lat REAL, lon REAL, active INTEGER DEFAULT 1, meta JSON);

CREATE TABLE IF NOT EXISTS devices (
  id TEXT PRIMARY KEY, village_id TEXT NOT NULL, kind TEXT, entity_type TEXT, entity_id TEXT, name TEXT,
  metrics JSON, fw TEXT, power TEXT, source TEXT DEFAULT 'simulation');

CREATE TABLE IF NOT EXISTS telemetry (
  id INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT UNIQUE, device_id TEXT NOT NULL, village_id TEXT,
  entity_type TEXT, entity_id TEXT, ts TEXT NOT NULL, metrics JSON NOT NULL, source TEXT NOT NULL,
  quality TEXT DEFAULT 'good', received_at TEXT);
CREATE INDEX IF NOT EXISTS ix_tel_device ON telemetry(device_id, id);

CREATE TABLE IF NOT EXISTS complaints (
  id TEXT PRIMARY KEY, seq INTEGER, village_id TEXT NOT NULL, household_id TEXT, branch_id TEXT,
  category TEXT NOT NULL, description TEXT, language TEXT, photo TEXT, lat REAL, lon REAL, geo_source TEXT,
  channel TEXT, source TEXT, created_at TEXT, wall_created TEXT, status TEXT, incident_id TEXT,
  ai_category TEXT, ai_confidence REAL, urgency TEXT, consent INTEGER, citizen_confirmed INTEGER, rating INTEGER,
  closed_at TEXT);
CREATE INDEX IF NOT EXISTS ix_cmp_village ON complaints(village_id, created_at);

CREATE TABLE IF NOT EXISTS incidents (
  id TEXT PRIMARY KEY, seq INTEGER, cond_key TEXT, village_id TEXT NOT NULL, type TEXT NOT NULL, category TEXT,
  severity TEXT, status TEXT, origin TEXT, title TEXT, summary TEXT, scope_type TEXT, scope_id TEXT, branch_id TEXT,
  affected_count INTEGER DEFAULT 0, affected_ids JSON, suspected_cause TEXT, suggested_action TEXT, evidence JSON,
  confidence REAL, report_count INTEGER DEFAULT 0, priority REAL DEFAULT 0, priority_breakdown JSON,
  assigned_to TEXT, escalation_level INTEGER DEFAULT 1, sla_ack_due TEXT, sla_resolve_due TEXT,
  first_seen TEXT, last_seen TEXT, acknowledged_at TEXT, in_progress_at TEXT, resolved_at TEXT, closed_at TEXT,
  recovered_at TEXT, repair_note TEXT, closure_reason TEXT, detection_delay_min REAL, is_seed INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS ix_inc_status ON incidents(status, village_id);

CREATE TABLE IF NOT EXISTS incident_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, incident_id TEXT NOT NULL, ts TEXT, wall_ts TEXT, actor TEXT, role TEXT,
  kind TEXT, from_status TEXT, to_status TEXT, note TEXT, data JSON);
CREATE INDEX IF NOT EXISTS ix_ie_inc ON incident_events(incident_id, id);

CREATE TABLE IF NOT EXISTS audit_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, wall_ts TEXT, actor TEXT, role TEXT, action TEXT,
  entity_type TEXT, entity_id TEXT, prev TEXT, new TEXT, detail TEXT, prev_hash TEXT, hash TEXT);

CREATE TABLE IF NOT EXISTS sync_outbox (
  id INTEGER PRIMARY KEY AUTOINCREMENT, idem_key TEXT UNIQUE, record_type TEXT, entity_id TEXT, village_id TEXT,
  op TEXT, payload JSON, status TEXT, attempts INTEGER DEFAULT 0, last_error TEXT, next_attempt REAL,
  created_ts TEXT, wall_created REAL, acked_wall REAL, external_ref TEXT);
CREATE INDEX IF NOT EXISTS ix_sync_status ON sync_outbox(status, id);

CREATE TABLE IF NOT EXISTS gov_received (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ref TEXT, idem_key TEXT UNIQUE, record_type TEXT, sujal_gaon_id TEXT,
  payload JSON, received_wall REAL);

CREATE TABLE IF NOT EXISTS id_mappings (
  id INTEGER PRIMARY KEY AUTOINCREMENT, internal_type TEXT, internal_id TEXT, system TEXT, field TEXT,
  external_id TEXT, status TEXT);

CREATE TABLE IF NOT EXISTS wq_tests (
  id TEXT PRIMARY KEY, village_id TEXT, sample_point TEXT, kind TEXT, params JSON, result TEXT, tested_by TEXT,
  ts TEXT, incident_id TEXT, lab_status TEXT, note TEXT);

CREATE TABLE IF NOT EXISTS notifications (
  id INTEGER PRIMARY KEY AUTOINCREMENT, village_id TEXT, branch_id TEXT, household_id TEXT, kind TEXT,
  params JSON, ts TEXT, channel TEXT, incident_id TEXT);
CREATE INDEX IF NOT EXISTS ix_notif_village ON notifications(village_id, id);

CREATE TABLE IF NOT EXISTS pulse (
  id INTEGER PRIMARY KEY AUTOINCREMENT, village_id TEXT, household_id TEXT, day TEXT, window_idx INTEGER,
  got_water INTEGER, inferred INTEGER, source TEXT, ts TEXT);

CREATE TABLE IF NOT EXISTS daily_history (
  village_id TEXT, day TEXT, functional_pct REAL, regularity_pct REAL, quantity_pct REAL, quality_pct REAL,
  avg_lpcd REAL, supply_hours REAL, incidents INTEGER, complaints INTEGER, mttr_h REAL, nrw_pct REAL,
  energy_kwh REAL, gw_depth_m REAL, source TEXT, PRIMARY KEY (village_id, day));

CREATE TABLE IF NOT EXISTS om_tasks (
  id TEXT PRIMARY KEY, village_id TEXT NOT NULL, slug TEXT, asset TEXT, title TEXT, every_days INTEGER, basis TEXT,
  last_done TEXT, done_by TEXT, note TEXT);

CREATE TABLE IF NOT EXISTS om_task_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT, village_id TEXT, done_at TEXT, done_by TEXT, note TEXT, on_time INTEGER);

CREATE TABLE IF NOT EXISTS operator_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT, village_id TEXT NOT NULL, day TEXT, window_idx INTEGER, meter_kl REAL, pump_hours REAL,
  chlorine_g REAL, remarks TEXT, photo TEXT, entered_by TEXT, source TEXT, ts TEXT, sensor_kl REAL, sensor_pump_hours REAL,
  verdict TEXT, diff_pct REAL);
CREATE INDEX IF NOT EXISTS ix_oplog_village ON operator_log(village_id, id);

CREATE TABLE IF NOT EXISTS charges (
  household_id TEXT NOT NULL, village_id TEXT NOT NULL, month TEXT NOT NULL, amount REAL, paid REAL DEFAULT 0, paid_on TEXT,
  receipt TEXT, collected_by TEXT, PRIMARY KEY (household_id, month));
CREATE INDEX IF NOT EXISTS ix_charges_village ON charges(village_id, month);

CREATE TABLE IF NOT EXISTS expenses (
  id INTEGER PRIMARY KEY AUTOINCREMENT, village_id TEXT NOT NULL, month TEXT, day TEXT, head TEXT, amount REAL, note TEXT,
  source TEXT, entered_by TEXT);

CREATE TABLE IF NOT EXISTS aankalan_state (
  village_id TEXT PRIMARY KEY, stage TEXT, endorsed_on TEXT, endorsed_by TEXT, note TEXT);

CREATE TABLE IF NOT EXISTS aankalan_feedback (
  id INTEGER PRIMARY KEY AUTOINCREMENT, village_id TEXT NOT NULL, household_id TEXT NOT NULL, agree INTEGER, comment TEXT, ts TEXT,
  source TEXT, UNIQUE (village_id, household_id));

CREATE TABLE IF NOT EXISTS users (
  username TEXT PRIMARY KEY, name TEXT, role TEXT, scope_level TEXT, scope_id TEXT, salt TEXT, pw_hash TEXT);
"""


class DB:
    def __init__(self, path: Path | str):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self._depth = 0  # nesting level of open tx() blocks; only the outermost one commits
        self.conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.execute("PRAGMA foreign_keys=OFF")

    def create(self):
        with self.lock:
            self.conn.executescript(SCHEMA)

    def wipe(self):
        """Drop every table (demo reset)."""
        with self.lock:
            names = [r[0] for r in self.conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
            for n in names:
                self.conn.execute(f"DROP TABLE IF EXISTS {n}")
            self.conn.executescript(SCHEMA)
            self._depth = 0

    def execute(self, sql: str, params: tuple | dict = ()):
        with self.lock:
            return self.conn.execute(sql, params)

    def executemany(self, sql: str, rows):
        with self.tx():
            self.conn.executemany(sql, rows)

    def query(self, sql: str, params: tuple | dict = ()) -> list[dict]:
        with self.lock:
            return [_row(r) for r in self.conn.execute(sql, params).fetchall()]

    def one(self, sql: str, params: tuple | dict = ()) -> dict | None:
        with self.lock:
            r = self.conn.execute(sql, params).fetchone()
            return _row(r) if r else None

    def scalar(self, sql: str, params: tuple | dict = ()):
        with self.lock:
            r = self.conn.execute(sql, params).fetchone()
            return r[0] if r else None

    def insert(self, table: str, row: dict):
        cols = ",".join(row.keys())
        marks = ",".join("?" for _ in row)
        vals = tuple(_enc(v) for v in row.values())
        with self.lock:
            return self.conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", vals).lastrowid

    def update(self, table: str, key: str, key_val, fields: dict):
        sets = ",".join(f"{k}=?" for k in fields)
        vals = tuple(_enc(v) for v in fields.values()) + (key_val,)
        with self.lock:
            self.conn.execute(f"UPDATE {table} SET {sets} WHERE {key}=?", vals)

    def tx(self):
        return _Tx(self)

    def close(self):
        with self.lock:
            self.conn.close()


class _Tx:
    def __init__(self, db: DB):
        self.db = db

    def __enter__(self):
        self.db.lock.acquire()
        if self.db._depth == 0:
            self.db.conn.execute("BEGIN")
        self.db._depth += 1
        return self.db

    def __exit__(self, exc_type, exc, tb):
        try:
            self.db._depth -= 1
            if self.db._depth == 0:
                self.db.conn.execute("ROLLBACK" if exc_type else "COMMIT")
        finally:
            self.db.lock.release()


_JSON_COLS = {"scheme", "external_ids", "meta", "metrics", "affected_ids", "evidence", "priority_breakdown", "data",
              "payload", "params"}


def _enc(v):
    if isinstance(v, (dict, list)):
        return json.dumps(v, separators=(",", ":"), ensure_ascii=False)
    if isinstance(v, bool):
        return int(v)
    return v


def _row(r: sqlite3.Row) -> dict:
    d = dict(r)
    for k in _JSON_COLS & d.keys():
        if isinstance(d[k], str):
            try:
                d[k] = json.loads(d[k])
            except ValueError:
                pass
    return d

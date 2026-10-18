"""Outbound synchronisation with JJM platforms (IMIS / Sujal Gaon / Sujalam Bharat).

Design: transactional outbox -> adapter -> acknowledgement, with idempotency
keys, exponential backoff and reconciliation. The only adapter that exists is
MockJJMGateway, an in-process sandbox. No request ever leaves this machine and
nothing is written to a government system. A live adapter needs the official
API specification, credentials and departmental approval.
"""
from __future__ import annotations

import random
import time

from ..seed import external_ids, village_by_id
from .interop import target_payloads

SCHEMA_VERSION = "jalsakhi.sync/0.3"
MAX_PER_PASS = 6
BACKOFF = [2, 4, 8, 15, 30]


class GatewayError(Exception):
    pass


class MockJJMGateway:
    """Stands in for the government endpoint. Stores what it 'received' so both sides can be reconciled."""

    name = "Sandbox gateway (mock IMIS / Sujal Gaon endpoint)"
    live = False

    def __init__(self, db, seed: int = 4):
        self.db = db
        self.outage = False
        self.rnd = random.Random(seed)
        self.transient_rate = 0.06  # occasional timeouts so retries are visible
        self.n = 0

    def push(self, idem_key: str, record_type: str, envelope: dict) -> str:
        if self.outage:
            raise GatewayError("503 Service Unavailable (simulated outage)")
        if self.rnd.random() < self.transient_rate:
            raise GatewayError("timeout after 10 s (simulated transient failure)")
        existing = self.db.one("SELECT ref FROM gov_received WHERE idem_key=?", (idem_key,))
        if existing:  # a retried request must not create a second record
            return existing["ref"]
        self.n += 1
        ref = f"SBX-ACK-{self.n:06d}"
        self.db.insert("gov_received", {"ref": ref, "idem_key": idem_key, "record_type": record_type,
                                        "sujal_gaon_id": envelope["ids"].get("sujal_gaon_id"), "payload": envelope,
                                        "received_wall": time.time()})
        return ref


class SyncService:
    def __init__(self, ctx):
        self.ctx = ctx
        self.db = ctx.db
        self.gateway = MockJJMGateway(ctx.db)
        self.stats = {"queued": 0, "acked": 0, "failed_attempts": 0}

    def enqueue(self, record_type: str, entity_id: str, village_id: str, op: str, payload: dict):
        """Queue one record. The idempotency key makes a re-send of the same state a no-op downstream."""
        marker = payload.get("status") or payload.get("day") or payload.get("ts") or ""
        idem = f"{record_type}:{entity_id}:{op}:{marker}"
        if self.db.scalar("SELECT 1 FROM sync_outbox WHERE idem_key=?", (idem,)):
            return
        envelope = {"schema": SCHEMA_VERSION, "record_type": record_type, "operation": op,
                    "ids": external_ids(village_by_id(village_id)), "internal_id": entity_id,
                    "generated_at": self.ctx.now.isoformat(timespec="seconds"),
                    "source_system": "JalSakhi AI (PoC, simulated data)", "data": payload}
        envelope["targets"] = target_payloads(record_type, envelope)  # the body each JJM platform would receive
        self.db.insert("sync_outbox", {"idem_key": idem, "record_type": record_type, "entity_id": entity_id,
                                       "village_id": village_id, "op": op, "payload": envelope, "status": "queued",
                                       "attempts": 0, "next_attempt": 0.0,
                                       "created_ts": self.ctx.now.isoformat(timespec="seconds"),
                                       "wall_created": time.time()})
        self.stats["queued"] += 1

    def process(self, force: bool = False) -> int:
        """Send due records. Called every tick; `force` ignores backoff timers (used by 'Sync now')."""
        now = time.time()
        sql = "SELECT * FROM sync_outbox WHERE status IN ('queued','retry')"
        if not force:
            sql += f" AND next_attempt <= {now}"
        rows = self.db.query(sql + " ORDER BY id LIMIT ?", (50 if force else MAX_PER_PASS,))
        sent = 0
        for r in rows:
            attempts = r["attempts"] + 1
            try:
                ref = self.gateway.push(r["idem_key"], r["record_type"], r["payload"])
            except GatewayError as exc:
                delay = BACKOFF[min(attempts - 1, len(BACKOFF) - 1)]
                self.db.update("sync_outbox", "id", r["id"], {"status": "retry", "attempts": attempts,
                                                              "last_error": str(exc), "next_attempt": now + delay})
                self.stats["failed_attempts"] += 1
                if self.gateway.outage:
                    break  # endpoint is down; no point hammering it with the rest of the queue
                continue
            self.db.update("sync_outbox", "id", r["id"], {"status": "acked", "attempts": attempts, "last_error": None,
                                                          "acked_wall": time.time(), "external_ref": ref})
            self.stats["acked"] += 1
            sent += 1
        return sent

    def set_outage(self, on: bool):
        self.gateway.outage = on
        if not on:  # endpoint is back: retry everything immediately
            self.db.execute("UPDATE sync_outbox SET next_attempt=0 WHERE status='retry'")

    def summary(self) -> dict:
        counts = {r["status"]: r["n"] for r in self.db.query("SELECT status, COUNT(*) n FROM sync_outbox GROUP BY status")}
        received = self.db.scalar("SELECT COUNT(*) FROM gov_received") or 0
        acked = counts.get("acked", 0)
        oldest = self.db.scalar("SELECT MIN(wall_created) FROM sync_outbox WHERE status!='acked'")
        return {"adapter": self.gateway.name, "live": self.gateway.live, "outage": self.gateway.outage,
                "queued": counts.get("queued", 0), "retry": counts.get("retry", 0), "acked": acked,
                "total": sum(counts.values()), "received_by_gateway": received, "reconciled": received == acked,
                "failed_attempts": self.stats["failed_attempts"],
                "oldest_pending_s": round(time.time() - oldest, 1) if oldest else 0, "schema": SCHEMA_VERSION}

    def outbox(self, limit: int = 60) -> list[dict]:
        return self.db.query("SELECT id, idem_key, record_type, entity_id, village_id, op, status, attempts, last_error,"
                             " created_ts, wall_created, acked_wall, external_ref, payload FROM sync_outbox"
                             " ORDER BY id DESC LIMIT ?", (limit,))

    def received(self, limit: int = 40) -> list[dict]:
        return self.db.query("SELECT * FROM gov_received ORDER BY id DESC LIMIT ?", (limit,))

    def by_type(self) -> list[dict]:
        return self.db.query("SELECT record_type, status, COUNT(*) n FROM sync_outbox GROUP BY record_type, status")

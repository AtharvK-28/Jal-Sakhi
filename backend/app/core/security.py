"""Demo-grade authentication, role checks and a tamper-evident audit trail.

This is deliberately small: salted PBKDF2 password hashes, HMAC-signed bearer
tokens and a hash-chained audit log. It demonstrates the access model; it is
not a hardened production identity system (no MFA, rotation, lockout, ...).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from datetime import datetime

from .. import config as C

STAFF_ROLES = {"operator", "vwsc", "tester", "block", "district", "state", "admin"}
OVERRIDE_ROLES = {"vwsc", "block", "district", "state", "admin"}  # may close without recovery evidence
ROLE_LABEL = {
    "citizen": "Citizen", "operator": "Nal Jal Mitra (operator)", "tester": "Jal Sakhi (water tester)", "vwsc": "VWSC / Gram Panchayat",
    "block": "Block engineer", "district": "District engineer", "state": "State JJM cell", "admin": "Demo admin",
}


def hash_pw(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 60_000).hex()


def new_salt() -> str:
    return os.urandom(16).hex()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def make_token(claims: dict) -> str:
    body = dict(claims, exp=int(time.time()) + C.TOKEN_TTL_HOURS * 3600)
    raw = _b64(json.dumps(body, separators=(",", ":")).encode())
    sig = _b64(hmac.new(C.SECRET_KEY.encode(), raw.encode(), hashlib.sha256).digest())
    return f"{raw}.{sig}"


def read_token(token: str | None) -> dict | None:
    if not token or "." not in token:
        return None
    raw, sig = token.rsplit(".", 1)
    good = _b64(hmac.new(C.SECRET_KEY.encode(), raw.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, good):
        return None
    try:
        claims = json.loads(_unb64(raw))
    except ValueError:
        return None
    return claims if claims.get("exp", 0) > time.time() else None


def device_signature(device_id: str, event_id: str) -> str:
    """HMAC a field device sends as X-Device-Signature (see firmware/)."""
    return hmac.new(C.DEVICE_KEY.encode(), f"{device_id}.{event_id}".encode(), hashlib.sha256).hexdigest()


class Audit:
    """Append-only audit log; each row carries the hash of the previous one."""

    def __init__(self, db):
        self.db = db
        self.last = "GENESIS"

    def log(self, sim_ts: datetime, actor: str, role: str, action: str, entity_type: str, entity_id: str,
            prev: str | None = None, new: str | None = None, detail: str | None = None):
        wall = datetime.now().isoformat(timespec="seconds")
        ts = sim_ts.isoformat(timespec="seconds")
        body = "|".join(str(x or "") for x in (self.last, ts, actor, role, action, entity_type, entity_id, prev, new, detail))
        digest = hashlib.sha256(body.encode()).hexdigest()
        self.db.insert("audit_log", {"ts": ts, "wall_ts": wall, "actor": actor, "role": role, "action": action,
                                     "entity_type": entity_type, "entity_id": entity_id, "prev": prev, "new": new,
                                     "detail": detail, "prev_hash": self.last, "hash": digest})
        self.last = digest

    def verify(self) -> dict:
        last = "GENESIS"
        rows = self.db.query("SELECT * FROM audit_log ORDER BY id")
        for r in rows:
            body = "|".join(str(x or "") for x in (last, r["ts"], r["actor"], r["role"], r["action"], r["entity_type"],
                                                   r["entity_id"], r["prev"], r["new"], r["detail"]))
            if r["prev_hash"] != last or hashlib.sha256(body.encode()).hexdigest() != r["hash"]:
                return {"ok": False, "records": len(rows), "broken_at": r["id"]}
            last = r["hash"]
        return {"ok": True, "records": len(rows), "head": last[:16]}

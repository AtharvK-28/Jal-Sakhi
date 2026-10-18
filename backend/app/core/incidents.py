"""Incident lifecycle: raise / deduplicate, assign, repair, verify, close, escalate, prioritise.

One condition key maps to at most one open incident, so a fault that keeps
tripping its rule updates the same record instead of spamming new ones.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from .. import config as C
from ..seed import ASSIGNEES
from .security import OVERRIDE_ROLES

TYPES = {
    "SUPPLY_INTERRUPTION": {"category": "supply", "label": "Supply interruption", "assign": "operator"},
    "LOW_PRESSURE": {"category": "pressure", "label": "Low pressure", "assign": "operator"},
    "TAP_FAULT": {"category": "supply", "label": "Household tap not delivering", "assign": "operator"},
    "SUSPECTED_LEAK": {"category": "leak", "label": "Suspected leakage", "assign": "crew"},
    "ABNORMAL_PATTERN": {"category": "anomaly", "label": "Abnormal service pattern", "assign": "operator"},
    "QUALITY_VERIFY": {"category": "quality", "label": "Water quality: verification required", "assign": "ftk"},
    "SENSOR_OFFLINE": {"category": "sensor", "label": "Sensor offline", "assign": "device"},
    "PUMP_FAULT": {"category": "infrastructure", "label": "Pump failure", "assign": "crew"},
    "PUMP_RISK": {"category": "predictive", "label": "Pump failure risk", "assign": "crew"},
    "SHORTFALL_PREDICTED": {"category": "predictive", "label": "Supply shortfall predicted", "assign": "je"},
    "SOURCE_STRESS": {"category": "sustainability", "label": "Source under stress", "assign": "je"},
    "COMMUNITY_CLUSTER": {"category": "community", "label": "Community-reported issue", "assign": "operator"},
    "CITIZEN_REPORT": {"category": "community", "label": "Citizen report", "assign": "operator"},
}
STATUSES = ["open", "acknowledged", "in_progress", "resolved_pending_verification", "closed"]
OPEN_STATUSES = STATUSES[:-1]
AUTO_CLOSE = {"SENSOR_OFFLINE", "SHORTFALL_PREDICTED"}  # close themselves once the condition is gone
TYPE_RANK = {"ABNORMAL_PATTERN": 1, "LOW_PRESSURE": 2, "SUSPECTED_LEAK": 3, "SUPPLY_INTERRUPTION": 4,
             "COMMUNITY_CLUSTER": 1}  # an incident may be reclassified upwards, never silently downgraded


class IncidentError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


class IncidentManager:
    def __init__(self, ctx):
        self.ctx = ctx
        self.db = ctx.db
        self.seq = 0
        self.items: dict[str, dict] = {}  # open incidents, authoritative in-memory copy
        self.by_key: dict[str, str] = {}
        self.cooldown: dict[str, datetime] = {}
        self._dirty: set[str] = set()

    # ------------------------------------------------------------------ raise
    def raise_(self, key: str, village_id: str, type_: str, severity: str, *, scope_type: str, scope_id: str,
               title: str, summary: str, cause: str, action: str, evidence: dict, branch_id: str | None = None,
               affected_ids: list | None = None, confidence: float = 0.8, origin: str = "sensor") -> tuple[dict | None, bool]:
        now = self.ctx.now
        affected_ids = affected_ids or []
        if key in self.by_key:
            inc = self.items[self.by_key[key]]
            inc["last_seen"] = now.isoformat(timespec="seconds")
            inc["evidence"] = {**(inc["evidence"] or {}), **evidence}
            if len(affected_ids) > inc["affected_count"]:
                inc["affected_ids"], inc["affected_count"] = affected_ids, len(affected_ids)
            if C.SEVERITY_RANK[severity] > C.SEVERITY_RANK[inc["severity"]]:
                self._event(inc, "severity", note=f"Severity raised from {inc['severity']} to {severity}")
                inc["severity"] = severity
                self._set_sla(inc, datetime.fromisoformat(inc["first_seen"]))
            if type_ != inc["type"] and TYPE_RANK.get(type_, 0) > TYPE_RANK.get(inc["type"], 0):
                self._event(inc, "reclassified", note=f"Reclassified: {TYPES[inc['type']]['label']} -> {TYPES[type_]['label']}")
                inc.update(type=type_, category=TYPES[type_]["category"], title=title, summary=summary,
                           suspected_cause=cause, suggested_action=action, confidence=confidence,
                           scope_type=scope_type, scope_id=scope_id)
            elif type_ == inc["type"]:
                inc.update(title=title, summary=summary, suspected_cause=cause, suggested_action=action, confidence=confidence)
            if inc["recovered_at"]:
                inc["recovered_at"] = None
                if inc["status"] == "resolved_pending_verification":
                    self._move(inc, "in_progress", "system", "system", "Condition returned after it had cleared; reopened")
            elif inc["status"] == "resolved_pending_verification" and inc["resolved_at"]:
                waited = (now - datetime.fromisoformat(inc["resolved_at"])).total_seconds() / 60
                if waited > 20:
                    self._move(inc, "in_progress", "system", "system",
                               "Repair recorded but telemetry still shows the condition; reopened")
            self._score(inc)
            self._dirty.add(inc["id"])
            return inc, False

        until = self.cooldown.get(key)
        if until and now < until:
            return None, False
        self.seq += 1
        meta = TYPES[type_]
        inc = {
            "id": f"INC-{self.seq:04d}", "seq": self.seq, "cond_key": key, "village_id": village_id, "type": type_,
            "category": meta["category"], "severity": severity, "status": "open", "origin": origin, "title": title,
            "summary": summary, "scope_type": scope_type, "scope_id": scope_id, "branch_id": branch_id,
            "affected_count": len(affected_ids), "affected_ids": affected_ids, "suspected_cause": cause,
            "suggested_action": action, "evidence": evidence, "confidence": confidence, "report_count": 0,
            "priority": 0.0, "priority_breakdown": {}, "assigned_to": None, "escalation_level": 1,
            "sla_ack_due": None, "sla_resolve_due": None, "first_seen": now.isoformat(timespec="seconds"),
            "last_seen": now.isoformat(timespec="seconds"), "acknowledged_at": None, "in_progress_at": None,
            "resolved_at": None, "closed_at": None, "recovered_at": None, "repair_note": None, "closure_reason": None,
            "detection_delay_min": self.ctx.detection_delay(village_id, type_, branch_id), "is_seed": 0,
        }
        self._set_sla(inc, now)
        self._score(inc)
        self.items[inc["id"]] = inc
        self.by_key[key] = inc["id"]
        self.db.insert("incidents", inc)
        self._event(inc, "created", to_status="open", note=summary, data={"origin": origin, "confidence": confidence})
        self.ctx.audit.log(now, "system", "system", "incident.create", "incident", inc["id"], None, "open", title)
        self.ctx.feed("incident", severity, f"{inc['id']} {title}", village_id, inc["id"])
        self.ctx.notify_incident(inc, "alert")
        self.ctx.sync.enqueue("incident", inc["id"], village_id, "create", self.public(inc))
        if origin != "citizen":
            self.ctx.complaints.absorb(inc)
        return inc, True

    def clear(self, key: str, note: str = "Telemetry indicates the condition has cleared"):
        """The detector reports the condition has stayed clear long enough."""
        inc_id = self.by_key.get(key)
        if not inc_id:
            return
        inc = self.items[inc_id]
        if inc["recovered_at"]:
            return
        inc["recovered_at"] = self.ctx.now.isoformat(timespec="seconds")
        self._event(inc, "recovery", note=note)
        if inc["type"] in AUTO_CLOSE:
            self._close(inc, "system", "system", "Self-resolved: condition cleared")
        elif inc["status"] in ("open", "acknowledged", "in_progress"):
            self._move(inc, "resolved_pending_verification", "system", "system",
                       "Condition cleared without a recorded repair; review and close")
        self._dirty.add(inc["id"])

    def is_open(self, key: str) -> bool:
        return key in self.by_key

    def get_by_key(self, key: str) -> dict | None:
        inc_id = self.by_key.get(key)
        return self.items.get(inc_id) if inc_id else None

    # ---------------------------------------------------------------- actions
    def act(self, incident_id: str, action: str, user: dict, payload: dict | None = None) -> dict:
        payload = payload or {}
        inc = self.items.get(incident_id)
        if inc is None:
            row = self.db.one("SELECT * FROM incidents WHERE id=?", (incident_id,))
            if row is None:
                raise IncidentError("incident not found", 404)
            if action != "reopen":
                raise IncidentError("incident is closed; only 'reopen' is allowed", 409)
            inc = row
        actor, role = user["name"], user["role"]
        note = (payload.get("note") or "").strip()
        st = inc["status"]
        if action == "acknowledge":
            if st != "open":
                raise IncidentError(f"cannot acknowledge an incident that is {st}", 409)
            self._move(inc, "acknowledged", actor, role, note or "Acknowledged")
        elif action == "assign":
            who = (payload.get("assignee") or "").strip()
            if not who:
                raise IncidentError("assignee is required")
            prev = inc["assigned_to"]
            inc["assigned_to"] = who
            self._event(inc, "assign", actor=actor, role=role, note=f"Assigned to {who}" + (f": {note}" if note else ""))
            self.ctx.audit.log(self.ctx.now, actor, role, "incident.assign", "incident", inc["id"], prev, who)
            if st == "open":
                self._move(inc, "acknowledged", actor, role, "Acknowledged on assignment")
        elif action == "start":
            if st not in ("open", "acknowledged"):
                raise IncidentError(f"cannot start work on an incident that is {st}", 409)
            self._move(inc, "in_progress", actor, role, note or "Field work started")
        elif action == "note":
            if not note:
                raise IncidentError("note text is required")
            self._event(inc, "note", actor=actor, role=role, note=note)
            self.ctx.audit.log(self.ctx.now, actor, role, "incident.note", "incident", inc["id"], None, None, note[:200])
        elif action == "repair":
            if st not in ("open", "acknowledged", "in_progress"):
                raise IncidentError(f"cannot record a repair on an incident that is {st}", 409)
            if not note:
                raise IncidentError("describe the repair / action taken")
            inc["repair_note"] = note
            self._move(inc, "resolved_pending_verification", actor, role, f"Repair recorded: {note}")
            self.ctx.on_repair(inc)
        elif action == "close":
            if st == "closed":
                raise IncidentError("incident is already closed", 409)
            override = bool(payload.get("override"))
            proof = self.closure_evidence(inc)
            if st != "resolved_pending_verification" and not override:
                raise IncidentError("record the repair first, or close with an authorised override", 409)
            if not proof["ok"] and not override:
                raise IncidentError("closure needs post-repair evidence: " + proof["missing"], 409)
            if override:
                if role not in OVERRIDE_ROLES:
                    raise IncidentError("your role cannot override the verification requirement", 403)
                if not note:
                    raise IncidentError("an override needs a written reason")
            self._close(inc, actor, role, (f"OVERRIDE: {note}" if override else note or "Verified: " + proof["summary"]))
        elif action == "reopen":
            if st not in ("resolved_pending_verification", "closed"):
                raise IncidentError(f"cannot reopen an incident that is {st}", 409)
            if st == "closed":
                inc.update(closed_at=None, closure_reason=None)
                self.items[inc["id"]] = inc
                if inc.get("cond_key"):
                    self.by_key[inc["cond_key"]] = inc["id"]
            inc["recovered_at"] = None
            self._move(inc, "in_progress", actor, role, note or "Reopened")
        elif action == "escalate":
            if inc["escalation_level"] >= 3:
                raise IncidentError("already at the highest escalation level", 409)
            inc["escalation_level"] += 1
            self._event(inc, "escalation", actor=actor, role=role,
                        note=f"Escalated to level {inc['escalation_level']}" + (f": {note}" if note else ""))
            self.ctx.audit.log(self.ctx.now, actor, role, "incident.escalate", "incident", inc["id"],
                               str(inc["escalation_level"] - 1), str(inc["escalation_level"]))
        else:
            raise IncidentError(f"unknown action '{action}'")
        self._score(inc)
        self._persist(inc)
        return self.detail(inc["id"])

    def closure_evidence(self, inc: dict) -> dict:
        """What proves the fix worked: telemetry recovery, citizen confirmation, or a passing FTK test.

        A leak needs two proofs. Supply here is intermittent, so the pipe stands empty between windows and a
        break can draw dirty water in; pressure coming back says the pipe holds, not that the water is clean.
        So a leak closes only on recovered pressure AND a passing field test taken after the repair."""
        ev = inc.get("evidence") or {}
        got = []
        if inc.get("recovered_at"):
            got.append("telemetry shows the condition cleared")
        if ev.get("citizen_confirmed", 0) > 0:
            got.append(f"{ev['citizen_confirmed']} citizen confirmation(s)")
        if ev.get("ftk_pass"):
            got.append("FTK re-test passed")
        if inc["category"] == "quality":
            ok = bool(inc.get("recovered_at")) and bool(ev.get("ftk_pass"))
            missing = "sensor readings back within limits AND a passing FTK re-test"
        elif inc["type"] == "SUSPECTED_LEAK":
            tested = bool(ev.get("ftk_pass")) and (ev.get("ftk_at") or "") >= (inc.get("resolved_at") or "")
            ok = bool(inc.get("recovered_at")) and tested
            missing = ("pressure back to normal AND a passing FTK test at a tap downstream, taken after the repair "
                       "(an empty pipe with a break in it can draw contamination in)")
        elif inc["origin"] == "citizen":
            ok = ev.get("citizen_confirmed", 0) > 0
            missing = "at least one citizen confirming the issue is fixed"
        else:
            ok = bool(inc.get("recovered_at"))
            missing = "telemetry showing the condition has cleared"
        return {"ok": ok, "summary": "; ".join(got) or "none yet", "missing": missing, "have": got}

    # ---------------------------------------------------------------- helpers
    def _move(self, inc: dict, to: str, actor: str, role: str, note: str):
        prev = inc["status"]
        now = self.ctx.now.isoformat(timespec="seconds")
        inc["status"] = to
        if to == "acknowledged":
            inc["acknowledged_at"] = now
        elif to == "in_progress":
            inc["in_progress_at"] = now
            inc["acknowledged_at"] = inc["acknowledged_at"] or now
            inc["resolved_at"] = None
        elif to == "resolved_pending_verification":
            inc["resolved_at"] = now
            inc["acknowledged_at"] = inc["acknowledged_at"] or now
        self._event(inc, "status", actor=actor, role=role, from_status=prev, to_status=to, note=note)
        self.ctx.audit.log(self.ctx.now, actor, role, "incident.status", "incident", inc["id"], prev, to, note[:200])
        self.ctx.on_incident_status(inc, prev, to)
        self._dirty.add(inc["id"])

    def merge_into(self, old: dict, target: dict):
        """Close a citizen-only ticket whose reports now belong to a sensor-detected incident."""
        self._event(target, "merged", note=f"Absorbed {old['report_count']} earlier citizen report(s) from {old['id']}: "
                                           "citizens reported this before the sensors confirmed it")
        target["report_count"] += old["report_count"]
        self._score(target)
        self._persist(target)
        self._close(old, "system", "system", f"Merged into {target['id']} (same issue, now sensor-detected)")
        self.cooldown.pop(old.get("cond_key"), None)

    def _close(self, inc: dict, actor: str, role: str, reason: str):
        prev = inc["status"]
        now = self.ctx.now
        inc.update(status="closed", closed_at=now.isoformat(timespec="seconds"), closure_reason=reason)
        inc["resolved_at"] = inc["resolved_at"] or inc["closed_at"]
        self._event(inc, "status", actor=actor, role=role, from_status=prev, to_status="closed", note=reason)
        self.ctx.audit.log(now, actor, role, "incident.close", "incident", inc["id"], prev, "closed", reason[:200])
        self.ctx.on_incident_status(inc, prev, "closed")
        self._persist(inc)
        self.items.pop(inc["id"], None)
        if inc.get("cond_key"):
            self.by_key.pop(inc["cond_key"], None)
            self.cooldown[inc["cond_key"]] = now + timedelta(minutes=C.COOLDOWN_MIN)
        self._dirty.discard(inc["id"])
        self.ctx.feed("resolved", "ok", f"{inc['id']} closed: {inc['title']}", inc["village_id"], inc["id"])

    def _event(self, inc: dict, kind: str, *, actor: str = "system", role: str = "system", from_status=None,
               to_status=None, note: str | None = None, data: dict | None = None):
        self.db.insert("incident_events", {
            "incident_id": inc["id"], "ts": self.ctx.now.isoformat(timespec="seconds"),
            "wall_ts": datetime.now().isoformat(timespec="seconds"), "actor": actor, "role": role, "kind": kind,
            "from_status": from_status, "to_status": to_status, "note": note, "data": data or {}})

    def add_event(self, inc: dict, kind: str, note: str, actor: str = "system", role: str = "system", data=None):
        self._event(inc, kind, actor=actor, role=role, note=note, data=data)
        self._dirty.add(inc["id"])

    def _set_sla(self, inc: dict, start: datetime):
        ack, resolve = C.SLA[inc["severity"]]
        inc["sla_ack_due"] = (start + timedelta(minutes=ack)).isoformat(timespec="seconds")
        inc["sla_resolve_due"] = (start + timedelta(minutes=resolve)).isoformat(timespec="seconds")

    def _score(self, inc: dict):
        """Transparent maintenance-priority score (0-100) with its breakdown."""
        now = self.ctx.now
        sev = {"low": 10, "medium": 20, "high": 30, "critical": 40}[inc["severity"]]
        reach = min(1.0, inc["affected_count"] / 40) * 20
        voice = min(1.0, inc["report_count"] / 5) * 10
        health = 15 if inc["category"] == "quality" else 6 if inc["category"] == "leak" else 0
        sites = min(10, 5 * len(self.ctx.sensitive_sites(inc)))
        age = (now - datetime.fromisoformat(inc["first_seen"])).total_seconds() / 60
        resolve_due = datetime.fromisoformat(inc["sla_resolve_due"])
        overdue = now > resolve_due and inc["status"] != "closed"
        ageing = min(1.0, age / max(1, C.SLA[inc["severity"]][1])) * 5 + (5 if overdue else 0)
        parts = {"severity": sev, "households_affected": round(reach, 1), "citizen_reports": round(voice, 1),
                 "health_risk": health, "sensitive_sites": sites, "ageing_sla": round(ageing, 1)}
        inc["priority_breakdown"] = parts
        inc["priority"] = round(min(100.0, sum(parts.values())), 1)

    def _persist(self, inc: dict):
        fields = {k: v for k, v in inc.items() if k not in ("id",)}
        self.db.update("incidents", "id", inc["id"], fields)

    def housekeeping(self):
        """Per tick: SLA-driven escalation, priority refresh, write-through of changed incidents."""
        now = self.ctx.now
        for inc in list(self.items.values()):
            if inc["status"] == "open" and inc["escalation_level"] == 1 and now > datetime.fromisoformat(inc["sla_ack_due"]):
                inc["escalation_level"] = 2
                self._event(inc, "escalation", note="Not acknowledged within SLA; escalated to Block (level 2)")
                self.ctx.feed("escalation", "warn", f"{inc['id']} escalated to Block: acknowledgement SLA missed",
                              inc["village_id"], inc["id"])
                self._dirty.add(inc["id"])
            if inc["escalation_level"] < 3 and now > datetime.fromisoformat(inc["sla_resolve_due"]):
                inc["escalation_level"] = 3
                self._event(inc, "escalation", note="Resolution SLA missed; escalated to District (level 3)")
                self.ctx.feed("escalation", "warn", f"{inc['id']} escalated to District: resolution SLA missed",
                              inc["village_id"], inc["id"])
                self._dirty.add(inc["id"])
        if self.ctx.tick % 10 == 0:
            for inc in self.items.values():
                before = inc["priority"]
                self._score(inc)
                if inc["priority"] != before:
                    self._dirty.add(inc["id"])
            for inc_id in list(self._dirty):
                if inc_id in self.items:
                    self._persist(self.items[inc_id])
            self._dirty.clear()

    # ---------------------------------------------------------------- queries
    def link_complaint(self, inc: dict, complaint: dict):
        inc["report_count"] += 1
        self._event(inc, "complaint_linked", actor="citizen", role="citizen",
                    note=f"Citizen report {complaint['id']} from {complaint['household_id']}: {complaint['category']}",
                    data={"complaint_id": complaint["id"]})
        self._score(inc)
        self._persist(inc)

    def public(self, inc: dict) -> dict:
        """Compact view used in lists, the live stream and sync payloads."""
        keys = ("id", "village_id", "type", "category", "severity", "status", "origin", "title", "scope_type",
                "scope_id", "branch_id", "affected_count", "report_count", "priority", "assigned_to",
                "escalation_level", "first_seen", "last_seen", "sla_ack_due", "sla_resolve_due", "confidence",
                "recovered_at", "detection_delay_min")
        out = {k: inc.get(k) for k in keys}
        out["label"] = TYPES[inc["type"]]["label"]
        return out

    def open_list(self, village_ids: set[str] | None = None) -> list[dict]:
        rows = [self.public(i) for i in self.items.values() if village_ids is None or i["village_id"] in village_ids]
        return sorted(rows, key=lambda r: -r["priority"])

    def list(self, *, village_ids: set[str] | None = None, status: str | None = None, include_seed: bool = False,
             limit: int = 200) -> list[dict]:
        sql = "SELECT * FROM incidents WHERE 1=1"
        params: list = []
        if not include_seed:
            sql += " AND is_seed=0"
        if status == "open":
            sql += " AND status!='closed'"
        elif status:
            sql += " AND status=?"
            params.append(status)
        sql += " ORDER BY (status='closed'), priority DESC, first_seen DESC LIMIT ?"
        params.append(limit)
        rows = self.db.query(sql, tuple(params))
        out = []
        for r in rows:
            live = self.items.get(r["id"], r)
            if village_ids is None or live["village_id"] in village_ids:
                out.append(self.public(live))
        return out

    def detail(self, incident_id: str) -> dict:
        inc = self.items.get(incident_id) or self.db.one("SELECT * FROM incidents WHERE id=?", (incident_id,))
        if inc is None:
            raise IncidentError("incident not found", 404)
        out = dict(inc)
        out["label"] = TYPES[inc["type"]]["label"]
        out["events"] = self.db.query("SELECT * FROM incident_events WHERE incident_id=? ORDER BY id", (incident_id,))
        out["complaints"] = self.db.query(
            "SELECT id, household_id, category, description, language, created_at, status, photo, citizen_confirmed,"
            " channel, source, urgency FROM complaints WHERE incident_id=? ORDER BY created_at", (incident_id,))
        out["closure"] = self.closure_evidence(inc)
        out["sites"] = self.ctx.sensitive_sites(inc)
        out["assignee_options"] = list(ASSIGNEES.values())
        out["suggested_assignee"] = ASSIGNEES[TYPES[inc["type"]]["assign"]]
        return out

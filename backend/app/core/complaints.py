"""Citizen reports: intake, AI categorisation, correlation with incidents, tracking, confirmation.

A report is evidence, not just a ticket. It is linked to a matching sensor
incident when one exists; otherwise reports from the same lane are grouped so
three neighbours reporting the same thing become one community incident, not
three unrelated tickets.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from .. import config as C
from ..ml.nlp_corpus import CATEGORIES

GROUP = {"no_water": "supply", "irregular": "supply", "low_pressure": "pressure", "dirty_water": "quality",
         "smell_taste": "quality", "leakage": "leak", "tap_damage": "asset", "other": "other"}
COMPATIBLE = {  # complaint group -> sensor incident types it corroborates
    "supply": {"SUPPLY_INTERRUPTION", "LOW_PRESSURE", "SUSPECTED_LEAK"},
    "pressure": {"LOW_PRESSURE", "SUSPECTED_LEAK", "SUPPLY_INTERRUPTION", "ABNORMAL_PATTERN"},
    "quality": {"QUALITY_VERIFY"},
    "leak": {"SUSPECTED_LEAK", "ABNORMAL_PATTERN", "LOW_PRESSURE"},
}
LABEL = {"no_water": "no water", "low_pressure": "low pressure", "dirty_water": "dirty water", "leakage": "leakage",
         "smell_taste": "bad smell / taste", "irregular": "irregular supply", "tap_damage": "damaged tap",
         "other": "other issue"}
ACTION = {
    "supply": "Check the branch valve and upstream supply; confirm with the reporting household.",
    "pressure": "Inspect the lane for a throttled valve, obstruction or leak; measure pressure at the reporting tap.",
    "quality": "Verification required: run an FTK test at a tap on this lane; send a lab sample if the FTK result fails.",
    "leak": "Send the repair crew to the reported location; isolate the segment if water is being lost.",
    "asset": "Visit the household and repair or replace the tap fitting.",
    "other": "Review and respond to the household.",
}


class ComplaintError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


class ComplaintService:
    def __init__(self, ctx):
        self.ctx = ctx
        self.db = ctx.db
        self.seq = 0

    def create(self, data: dict) -> dict:
        ctx = self.ctx
        hh = ctx.households.get(data.get("household_id") or "")
        if hh is None:
            raise ComplaintError("unknown household_id", 404)
        description = (data.get("description") or "").strip()[:1000]
        ai = ctx.models.classify(description) if description else {"category": None, "confidence": 0.0, "urgency": "normal", "top": []}
        category = data.get("category")
        if category and category not in CATEGORIES:
            raise ComplaintError(f"category must be one of {CATEGORIES}")
        if not category:
            if not description:
                raise ComplaintError("choose a category or describe the problem")
            category = ai["category"] if ai["confidence"] >= 0.45 else "other"
        self.seq += 1
        village = ctx.sims[hh["village_id"]]
        now = ctx.now
        c = {
            "id": f"JS-{village.code}-{self.seq:04d}", "seq": self.seq, "village_id": hh["village_id"],
            "household_id": hh["id"], "branch_id": hh["branch_id"], "category": category, "description": description,
            "language": data.get("language") or "en", "photo": data.get("photo"),
            "lat": data.get("lat") if data.get("lat") is not None else hh["lat"],
            "lon": data.get("lon") if data.get("lon") is not None else hh["lon"],
            "geo_source": data.get("geo_source") or "registered-tap-location",
            "channel": data.get("channel") or "app", "source": data.get("source") or "portal",
            "created_at": now.isoformat(timespec="seconds"), "wall_created": datetime.now().isoformat(timespec="seconds"),
            "status": "open", "incident_id": None, "ai_category": ai["category"], "ai_confidence": ai["confidence"],
            "urgency": ai["urgency"], "consent": 1 if data.get("consent", True) else 0, "citizen_confirmed": None,
            "rating": None, "closed_at": None,
        }
        inc, how = self._correlate(c, hh)
        c["incident_id"] = inc["id"]
        c["status"] = inc["status"]
        self.db.insert("complaints", c)
        ctx.incidents.link_complaint(inc, c)
        if GROUP[category] == "leak":
            ev = inc["evidence"].setdefault("citizen_leak_reports", [])
            if hh["label"] not in ev:
                ev.append(hh["label"])
        ctx.audit.log(now, c["source"], "citizen", "complaint.create", "complaint", c["id"], None, "open",
                      f"{category} @ {hh['id']} via {c['channel']}")
        ctx.feed("complaint", "info", f"{c['id']} {LABEL[category]} reported by {hh['label']} ({how} {inc['id']})",
                 hh["village_id"], inc["id"])
        ctx.notify(hh["village_id"], "complaint_received", {"id": c["id"], "category": category},
                   household_id=hh["id"], incident_id=inc["id"])
        ctx.sync.enqueue("grievance", c["id"], hh["village_id"], "create", {
            "tracking_id": c["id"], "category": category, "status": c["status"], "channel": c["channel"],
            "fhtc_id": hh["fhtc_ext_id"], "linked_incident": inc["id"], "created_at": c["created_at"],
            "geo": {"lat": c["lat"], "lon": c["lon"], "source": c["geo_source"]}})
        return {**c, "ai": ai, "linked": how, "incident": self._public_incident(inc)}

    def _correlate(self, c: dict, hh: dict) -> tuple[dict, str]:
        ctx = self.ctx
        group = GROUP[c["category"]]
        vid, branch = c["village_id"], c["branch_id"]
        best = None
        for inc in ctx.incidents.items.values():
            if inc["village_id"] != vid or inc["origin"] == "citizen" or inc["type"] not in COMPATIBLE.get(group, ()):
                continue
            if inc["scope_type"] == "scheme" or inc["branch_id"] == branch:
                if best is None or C.SEVERITY_RANK[inc["severity"]] > C.SEVERITY_RANK[best["severity"]]:
                    best = inc
        if best is not None:
            return best, "corroborates"

        village = ctx.sims[vid]
        lane = hh["lane"]
        if group in ("asset", "other"):
            key = f"{vid}:cit:{hh['id']}:{c['category']}"
            inc, _ = ctx.incidents.raise_(
                key, vid, "CITIZEN_REPORT", "low", scope_type="household", scope_id=hh["id"], branch_id=branch,
                affected_ids=[hh["id"]], title=f"Citizen report: {LABEL[c['category']]} at {hh['label']}",
                summary=f"{hh['label']} ({lane}) reported {LABEL[c['category']]}.", cause="Reported by the household",
                action=ACTION[group], evidence={"reports": 1}, confidence=0.6, origin="citizen")
            return inc, "opened"

        key = f"{vid}:cit:{branch}:{group}"
        existing = ctx.incidents.get_by_key(key)
        since = (ctx.now - timedelta(minutes=C.CLUSTER_WINDOW_MIN)).isoformat(timespec="seconds")
        recent = {r["household_id"] for r in self.db.query(
            "SELECT household_id FROM complaints WHERE incident_id=? AND created_at>=?",
            (existing["id"] if existing else "", since))}
        recent.add(hh["id"])
        if len(recent) >= C.CLUSTER_MIN_REPORTS:
            b_idx = hh["branch_idx"]
            affected = [h for h, m in ctx.households.items() if m["village_id"] == vid and m["branch_idx"] == b_idx]
            severity = "high" if group == "quality" else "medium"
            summary = (f"{len(recent)} households on {lane} reported {LABEL[c['category']]} within "
                       f"{C.CLUSTER_WINDOW_MIN} minutes. ")
            summary += ("No quality sensor covers this lane, so the community reports are the only signal. "
                        "This is a concern to verify, not a confirmed contamination."
                        if group == "quality" else "Sensors on this lane have not flagged a matching fault.")
            inc, created = ctx.incidents.raise_(
                key, vid, "COMMUNITY_CLUSTER", severity, scope_type="branch", scope_id=branch, branch_id=branch,
                affected_ids=affected, title=f"{len(recent)} households on {lane} report {LABEL[c['category']]}",
                summary=summary, cause="Community-reported; cause not yet determined", action=ACTION[group],
                evidence={"reports": len(recent), "reporting_households": sorted(recent)}, confidence=0.7, origin="citizen")
            return inc, "opened" if created else "grouped into"
        severity = "medium" if (group == "quality" or c["urgency"] == "high") else "low"
        inc, created = ctx.incidents.raise_(
            key, vid, "CITIZEN_REPORT", severity, scope_type="household", scope_id=hh["id"], branch_id=branch,
            affected_ids=[hh["id"]], title=f"Citizen report: {LABEL[c['category']]} on {lane}",
            summary=f"{hh['label']} ({lane}) reported {LABEL[c['category']]}. No matching sensor alert on this lane.",
            cause="Reported by the household", action=ACTION[group], evidence={"reports": len(recent)}, confidence=0.55,
            origin="citizen")
        if inc is None:  # condition key is cooling down after a recent closure: open an individual ticket instead
            inc, created = ctx.incidents.raise_(
                f"{vid}:cit:{hh['id']}:{c['category']}:{self.seq}", vid, "CITIZEN_REPORT", severity,
                scope_type="household", scope_id=hh["id"], branch_id=branch, affected_ids=[hh["id"]],
                title=f"Citizen report: {LABEL[c['category']]} on {lane}",
                summary=f"{hh['label']} ({lane}) reported {LABEL[c['category']]} shortly after a similar issue was closed.",
                cause="Reported by the household", action=ACTION[group], evidence={"reports": 1}, confidence=0.55,
                origin="citizen")
        return inc, "opened" if created else "grouped into"

    def absorb(self, target: dict):
        """Move reports from open citizen-only tickets into a newly raised sensor incident on the same scope."""
        ctx = self.ctx
        for old in list(ctx.incidents.items.values()):
            if old["origin"] != "citizen" or old["village_id"] != target["village_id"] or old["id"] == target["id"]:
                continue
            parts = (old["cond_key"] or "").split(":")
            group = parts[3] if len(parts) > 3 else ""
            if target["type"] not in COMPATIBLE.get(group, ()):
                continue
            if target["scope_type"] != "scheme" and old["branch_id"] != target["branch_id"]:
                continue
            self.db.execute("UPDATE complaints SET incident_id=?, status=? WHERE incident_id=?",
                            (target["id"], target["status"], old["id"]))
            ctx.incidents.merge_into(old, target)

    # ------------------------------------------------------------ follow-up
    def on_incident_status(self, inc: dict, status: str):
        """Linked complaints follow the incident's lifecycle."""
        closed_at = self.ctx.now.isoformat(timespec="seconds") if status == "closed" else None
        self.db.execute("UPDATE complaints SET status=?, closed_at=? WHERE incident_id=?", (status, closed_at, inc["id"]))

    def confirm(self, tracking_id: str, resolved: bool, rating: int | None = None, actor: str = "citizen") -> dict:
        c = self.db.one("SELECT * FROM complaints WHERE id=?", (tracking_id,))
        if c is None:
            raise ComplaintError("tracking ID not found", 404)
        ctx = self.ctx
        self.db.update("complaints", "id", tracking_id, {"citizen_confirmed": 1 if resolved else 0, "rating": rating})
        inc = ctx.incidents.items.get(c["incident_id"])
        if inc is not None:
            ev = inc["evidence"]
            if resolved:
                ev["citizen_confirmed"] = ev.get("citizen_confirmed", 0) + 1
                ctx.incidents.add_event(inc, "citizen_confirm", f"{c['household_id']} confirmed the issue is fixed",
                                        actor=actor, role="citizen", data={"complaint_id": tracking_id, "rating": rating})
            else:
                ev["citizen_disputed"] = ev.get("citizen_disputed", 0) + 1
                ctx.incidents.add_event(inc, "citizen_dispute", f"{c['household_id']} says the issue is NOT fixed",
                                        actor=actor, role="citizen", data={"complaint_id": tracking_id})
                if inc["status"] == "resolved_pending_verification":
                    ctx.incidents.act(inc["id"], "reopen", {"name": "citizen feedback", "role": "citizen"},
                                      {"note": f"Reopened: {c['household_id']} reports the problem persists"})
            ctx.incidents._persist(inc)
        elif not resolved and c["incident_id"]:
            ctx.incidents.act(c["incident_id"], "reopen", {"name": "citizen feedback", "role": "citizen"},
                              {"note": f"Reopened after closure: {c['household_id']} reports the problem persists"})
        ctx.audit.log(ctx.now, actor, "citizen", "complaint.confirm", "complaint", tracking_id, None,
                      "fixed" if resolved else "not fixed")
        return self.track(tracking_id)

    def track(self, tracking_id: str) -> dict:
        c = self.db.one("SELECT * FROM complaints WHERE id=?", (tracking_id.strip().upper(),))
        if c is None:
            raise ComplaintError("tracking ID not found", 404)
        events = self.db.query(
            "SELECT ts, kind, to_status, note FROM incident_events WHERE incident_id=? AND kind IN ('created','status','assign')"
            " ORDER BY id", (c["incident_id"],))
        inc = self.ctx.incidents.items.get(c["incident_id"]) or self.db.one("SELECT * FROM incidents WHERE id=?", (c["incident_id"],))
        hh = self.ctx.households[c["household_id"]]
        return {"id": c["id"], "category": c["category"], "description": c["description"], "status": c["status"],
                "created_at": c["created_at"], "closed_at": c["closed_at"], "household": hh["label"], "lane": hh["lane"],
                "photo": c["photo"], "citizen_confirmed": c["citizen_confirmed"], "rating": c["rating"],
                "language": c["language"], "incident": self._public_incident(inc) if inc else None,
                "timeline": [{"ts": e["ts"], "status": e["to_status"], "kind": e["kind"]} for e in events
                             if e["kind"] != "assign" or True]}

    def _public_incident(self, inc: dict) -> dict:
        """What a citizen may see about the linked incident: no internal notes, no other households."""
        return {"id": inc["id"], "type": inc["type"], "status": inc["status"], "severity": inc["severity"],
                "affected_count": inc["affected_count"], "report_count": inc["report_count"],
                "assigned": bool(inc["assigned_to"]), "sla_resolve_due": inc["sla_resolve_due"]}

    def list(self, village_ids: set[str] | None = None, status: str | None = None, limit: int = 200) -> list[dict]:
        sql = "SELECT * FROM complaints WHERE 1=1"
        params: list = []
        if status == "open":
            sql += " AND status!='closed'"
        elif status:
            sql += " AND status=?"
            params.append(status)
        sql += " ORDER BY seq DESC LIMIT ?"
        params.append(limit)
        rows = self.db.query(sql, tuple(params))
        return [r for r in rows if village_ids is None or r["village_id"] in village_ids]

    def for_household(self, household_id: str) -> list[dict]:
        return self.db.query("SELECT id, category, status, created_at, closed_at, incident_id, citizen_confirmed,"
                             " description, photo FROM complaints WHERE household_id=? ORDER BY seq DESC LIMIT 20",
                             (household_id,))

"""Phone alerts: who must hear about an incident, and the message that reaches their phone.

Detection raises incidents inside the platform. This module routes each one along the escalation ladder,
delivers it over a real messaging channel, and takes the replies back in:

  level 1  village    Nal Jal Mitra (operator) and the Pani Samiti, as soon as an incident opens
  level 2  block      the Junior Engineer, when the village has not acknowledged within the SLA (or at once if critical)
  level 3  district   the Executive Engineer, when the resolution SLA is missed
  households          what the citizen app shows the household, in its language, for its own lane

Channels, each off until its credentials are set (see config):
  telegram  Telegram Bot API. Two-way over long polling, so it also works from a laptop behind NAT.
  whatsapp  WhatsApp Business Cloud API. Outbound text and reply buttons; inbound at /api/whatsapp/webhook.
  sms       any HTTP SMS gateway, one JSON POST per message. Commercial SMS in India needs a DLT-registered
            sender and template, so the gateway is the deploying department's own.
A message for a channel that is not configured, or for a placeholder DEMO number, is written to the delivery
log as 'sandbox' and is never reported as sent.

Replies: a household can report a problem in its own words, with a photo and its location, confirm a repair
(YES / NO), or ask for its tap's status. Staff can acknowledge an incident or start work from the alert itself.

Recipients and the delivery log live in their own SQLite file, so a demo reset does not unlink a phone.
"""
from __future__ import annotations

import json
import logging
import re
import secrets
import threading
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field

from .. import config as C
from .. import seed as S
from ..db import DB
from . import alert_text as L
from .complaints import ComplaintError, LABEL as CAT_LABEL
from .incidents import IncidentError, TYPES

log = logging.getLogger("jalsakhi.alerts")

SCHEMA = """
CREATE TABLE IF NOT EXISTS recipients (
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, role TEXT, scope_id TEXT, channel TEXT, address TEXT, lang TEXT,
  acting JSON, demo INTEGER DEFAULT 0, active INTEGER DEFAULT 1, linked_via TEXT, created_wall REAL,
  UNIQUE (channel, address, role, scope_id));
CREATE TABLE IF NOT EXISTS deliveries (
  id INTEGER PRIMARY KEY AUTOINCREMENT, epoch TEXT, direction TEXT, recipient_id INTEGER, channel TEXT, address TEXT,
  name TEXT, role TEXT, kind TEXT, incident_id TEXT, village_id TEXT, dedupe TEXT UNIQUE, text TEXT, buttons JSON,
  status TEXT, attempts INTEGER DEFAULT 0, last_error TEXT, provider_ref TEXT, created_wall REAL, sent_wall REAL,
  next_attempt REAL DEFAULT 0);
CREATE INDEX IF NOT EXISTS ix_dlv_status ON deliveries(status, next_attempt);
CREATE TABLE IF NOT EXISTS link_codes (
  code TEXT PRIMARY KEY, role TEXT, scope_id TEXT, name TEXT, lang TEXT, acting JSON, expires_wall REAL, used INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT);
"""

STAFF_ROLES = ("operator", "vwsc", "block", "district")
ROLE_TITLE = {"operator": "Nal Jal Mitra (operator)", "vwsc": "Pani Samiti / VWSC", "block": "Junior Engineer (block)",
              "district": "Executive Engineer (district)", "household": "Household"}
LEVEL_OF = {"operator": 1, "vwsc": 1, "block": 2, "district": 3}
SEV_MARK = {"critical": "🔴 CRITICAL", "high": "🟠 HIGH", "medium": "🟡 MEDIUM", "low": "⚪ LOW"}
BACKOFF = [3, 10, 30, 90]
MAX_ATTEMPTS = 5
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CATS = ("no_water", "low_pressure", "dirty_water", "leakage", "smell_taste", "irregular", "tap_damage", "other")
DRAFT_TTL_S = 900

# Phone numbers seeded as recipients so the routing is visible before any phone is linked. They are the
# placeholder directory of seed.CONTACTS: always sandbox, never sent anywhere.
DEMO_RECIPIENTS = [
    ("Nal Jal Mitra (operator), Pimpalwadi", "operator", "VLG-PW", "DEMO 90000 00001"),
    ("Pani Samiti chairperson, Pimpalwadi", "vwsc", "VLG-PW", "DEMO 90000 00002"),
    ("Junior Engineer, Mulshi block", "block", "BK-MUL", "DEMO 90000 00003"),
    ("Executive Engineer, Pune district", "district", "DT-PUN", "DEMO 90000 00004"),
]


class ChannelError(Exception):
    pass


def _http(method: str, url: str, *, body: dict | None = None, headers: dict | None = None, timeout: float = 15.0,
          secret: str = "") -> tuple[int, bytes]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={**({"Content-Type": "application/json"} if data else {}), **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        msg = str(getattr(e, "reason", e))
        raise ChannelError(f"network error: {msg.replace(secret, '***') if secret else msg}") from None


def _json(raw: bytes) -> dict:
    try:
        return json.loads(raw or b"{}")
    except ValueError:
        return {}


def _digits(address: str) -> str:
    d = re.sub(r"\D", "", address or "")
    return "91" + d if len(d) == 10 else d  # a bare 10-digit number is Indian


def mask(channel: str, address: str) -> str:
    if address.startswith("DEMO"):
        return address
    d = re.sub(r"\D", "", address)
    if channel == "telegram":
        return f"chat ••{d[-4:]}"
    return f"+{d[:2]} ••••• {d[-4:]}" if len(d) > 6 else address


# --------------------------------------------------------------------------------------------- channels
class Telegram:
    id, label = "telegram", "Telegram"

    def __init__(self, token: str):
        self.token = token
        self.username: str | None = None
        self.error: str | None = None
        self.polling = False
        self.last_poll = 0.0

    @property
    def configured(self) -> bool:
        return bool(self.token)

    def call(self, method: str, payload: dict | None = None, timeout: float = 15.0) -> dict:
        status, raw = _http("POST", f"https://api.telegram.org/bot{self.token}/{method}", body=payload or {},
                            timeout=timeout, secret=self.token)
        out = _json(raw)
        if not out.get("ok"):
            raise ChannelError(f"Telegram {status}: {out.get('description') or raw[:120].decode(errors='replace')}")
        return out["result"]

    def send(self, address: str, text: str, buttons: list | None) -> str:
        payload = {"chat_id": address, "text": text[:4000], "disable_web_page_preview": True}
        if buttons:
            payload["reply_markup"] = {"inline_keyboard": [[{"text": lbl, "callback_data": data} for lbl, data in row]
                                                           for row in buttons]}
        return str(self.call("sendMessage", payload)["message_id"])

    def file_bytes(self, file_id: str) -> bytes:
        f = self.call("getFile", {"file_id": file_id})
        if f.get("file_size", 0) > C.MAX_UPLOAD_BYTES:
            raise ChannelError("photo is larger than 5 MB")
        status, raw = _http("GET", f"https://api.telegram.org/file/bot{self.token}/{f['file_path']}", secret=self.token)
        if status != 200:
            raise ChannelError(f"Telegram file download failed ({status})")
        return raw

    def status(self) -> dict:
        live = self.configured and self.polling and time.time() - self.last_poll < 90
        return {"id": self.id, "label": self.label, "configured": self.configured, "live": live,
                "identity": f"@{self.username}" if self.username else None, "error": self.error,
                "two_way": True, "setup": "Create a bot with @BotFather and set TELEGRAM_BOT_TOKEN."}


class WhatsApp:
    id, label = "whatsapp", "WhatsApp"

    def __init__(self):
        self.token, self.phone_id, self.number = C.WHATSAPP_TOKEN, C.WHATSAPP_PHONE_ID, C.WHATSAPP_NUMBER
        self.base = f"https://graph.facebook.com/{C.WHATSAPP_API_VERSION}"
        self.error: str | None = None
        self.last_inbound = 0.0

    @property
    def configured(self) -> bool:
        return bool(self.token and self.phone_id)

    def send(self, address: str, text: str, buttons: list | None) -> str:
        flat = [b for row in (buttons or []) for b in row]
        msg = {"messaging_product": "whatsapp", "recipient_type": "individual", "to": _digits(address)}
        if flat and len(flat) <= 3:  # reply buttons: at most three, titles of at most 20 characters
            msg.update(type="interactive", interactive={"type": "button", "body": {"text": text[:1024]}, "action": {
                "buttons": [{"type": "reply", "reply": {"id": data, "title": lbl[:20]}} for lbl, data in flat]}})
        else:
            msg.update(type="text", text={"body": text[:4096], "preview_url": False})
        status, raw = _http("POST", f"{self.base}/{self.phone_id}/messages", body=msg,
                            headers={"Authorization": f"Bearer {self.token}"}, secret=self.token)
        out = _json(raw)
        if status >= 300 or "messages" not in out:
            err = out.get("error") or {}
            hint = " (the person must message this number first: business-initiated text needs an open 24-hour window or an approved template)" \
                if err.get("code") in (131047, 470) else ""
            raise ChannelError(f"WhatsApp {status}: {err.get('message') or raw[:120].decode(errors='replace')}{hint}")
        return out["messages"][0]["id"]

    def media_bytes(self, media_id: str) -> bytes:
        auth = {"Authorization": f"Bearer {self.token}"}
        status, raw = _http("GET", f"{self.base}/{media_id}", headers=auth, secret=self.token)
        meta = _json(raw)
        if status != 200 or "url" not in meta:
            raise ChannelError(f"WhatsApp media lookup failed ({status})")
        if int(meta.get("file_size") or 0) > C.MAX_UPLOAD_BYTES:
            raise ChannelError("photo is larger than 5 MB")
        status, raw = _http("GET", meta["url"], headers=auth, secret=self.token)
        if status != 200:
            raise ChannelError(f"WhatsApp media download failed ({status})")
        return raw

    def status(self) -> dict:
        return {"id": self.id, "label": self.label, "configured": self.configured, "live": self.configured,
                "identity": self.number or (f"phone ID {self.phone_id}" if self.phone_id else None), "error": self.error,
                "two_way": bool(C.WHATSAPP_VERIFY_TOKEN), "setup": "Set WHATSAPP_TOKEN and WHATSAPP_PHONE_ID from a Meta "
                "WhatsApp Business app; point its webhook at /api/whatsapp/webhook with WHATSAPP_VERIFY_TOKEN for replies."}


class SmsGateway:
    id, label = "sms", "SMS"

    def __init__(self):
        self.url, self.auth = C.SMS_GATEWAY_URL, C.SMS_GATEWAY_AUTH
        self.error: str | None = None

    @property
    def configured(self) -> bool:
        return bool(self.url)

    def send(self, address: str, text: str, buttons: list | None) -> str:
        body = {"to": "+" + _digits(address), "text": text[:900], "sender": C.SMS_SENDER_ID or None,
                "dlt_template_id": C.SMS_DLT_TEMPLATE_ID or None}
        status, raw = _http("POST", self.url, body=body, headers={"Authorization": self.auth} if self.auth else {},
                            secret=self.auth)
        if status >= 300:
            raise ChannelError(f"SMS gateway {status}: {raw[:160].decode(errors='replace')}")
        out = _json(raw)
        return str(out.get("id") or out.get("message_id") or out.get("request_id") or f"http-{status}")

    def status(self) -> dict:
        return {"id": self.id, "label": self.label, "configured": self.configured, "live": self.configured,
                "identity": C.SMS_SENDER_ID or None, "error": self.error, "two_way": False,
                "setup": "Set SMS_GATEWAY_URL (and SMS_GATEWAY_AUTH) for a DLT-registered gateway such as MSG91 or Gupshup."}


@dataclass
class Inbound:
    """One message from a phone, whatever channel it came on."""
    channel: str
    address: str
    name: str = ""
    text: str = ""
    button: str | None = None
    lat: float | None = None
    lon: float | None = None
    photo: object = None  # callable returning the image bytes, fetched only when needed
    meta: dict = field(default_factory=dict)


# ------------------------------------------------------------------------------------------- dispatcher
class AlertDispatcher:
    def __init__(self, ctx, db_path=None):
        self.ctx = ctx
        self.db = DB(db_path or C.ALERTS_DB)
        with self.db.lock:
            self.db.conn.executescript(SCHEMA)
        self.channels = {"telegram": Telegram(C.TELEGRAM_BOT_TOKEN), "whatsapp": WhatsApp(), "sms": SmsGateway()}
        self.epoch = uuid.uuid4().hex[:8]
        self.drafts: dict[tuple[str, str], dict] = {}
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        if not self.db.scalar("SELECT COUNT(*) FROM recipients"):
            for name, role, scope, phone in DEMO_RECIPIENTS:
                self._upsert_recipient(name=name, role=role, scope_id=scope, channel="sms", address=phone,
                                       lang="en", demo=1, linked_via="demo directory")

    # ------------------------------------------------------------------ lifecycle
    def start(self):
        if self._threads:
            return
        self._stop.clear()
        self._threads = [threading.Thread(target=self._deliver_loop, name="alerts-deliver", daemon=True)]
        if self.channels["telegram"].configured:
            self._threads.append(threading.Thread(target=self._telegram_loop, name="alerts-telegram", daemon=True))
        for th in self._threads:
            th.start()

    def stop(self):
        self._stop.set()
        self._wake.set()
        for th in self._threads:
            if th.name == "alerts-deliver":  # the Telegram reader may sit in a 25 s long poll; it is a daemon
                th.join(timeout=5)
        self._threads = []

    @property
    def live(self) -> bool:
        """Whether any channel can reach a real phone from this server."""
        return any(c.configured for c in self.channels.values())

    def new_epoch(self):
        """A demo reset starts incident numbering again; keep old deliveries from deduplicating new ones."""
        self.epoch = uuid.uuid4().hex[:8]
        self.drafts.clear()

    # ----------------------------------------------------------------- recipients
    def _upsert_recipient(self, *, name, role, scope_id, channel, address, lang, acting=None, demo=0, linked_via="") -> dict:
        row = self.db.one("SELECT id FROM recipients WHERE channel=? AND address=? AND role=? AND scope_id=?",
                          (channel, address, role, scope_id))
        fields = {"name": name, "lang": lang, "acting": acting or {}, "demo": demo, "active": 1, "linked_via": linked_via}
        if row:
            self.db.update("recipients", "id", row["id"], fields)
            rid = row["id"]
        else:
            rid = self.db.insert("recipients", {"role": role, "scope_id": scope_id, "channel": channel, "address": address,
                                                "created_wall": time.time(), **fields})
        return self.db.one("SELECT * FROM recipients WHERE id=?", (rid,))

    def add_recipient(self, *, name: str, role: str, scope_id: str, channel: str, address: str, lang: str = "en",
                      acting: dict | None = None) -> dict:
        if channel not in self.channels:
            raise ValueError(f"channel must be one of {list(self.channels)}")
        if role not in STAFF_ROLES + ("household",):
            raise ValueError("role must be operator, vwsc, block, district or household")
        address = address.strip()
        if channel in ("whatsapp", "sms") and not 11 <= len(_digits(address)) <= 15:
            raise ValueError("give the mobile number with country code, e.g. +91 98xxxxxxxx")
        if channel == "telegram" and not re.fullmatch(r"-?\d{5,16}", address):
            raise ValueError("a Telegram chat ID is a number; linking with a code fills it in for you")
        if channel in ("whatsapp", "sms"):
            address = "+" + _digits(address)
        return self._public_recipient(self._upsert_recipient(name=name.strip()[:80] or ROLE_TITLE[role], role=role,
                                                             scope_id=scope_id, channel=channel, address=address,
                                                             lang=lang, acting=acting, linked_via="added on the dashboard"))

    def remove_recipient(self, rid: int):
        self.db.update("recipients", "id", rid, {"active": 0})

    def recipient(self, rid: int) -> dict | None:
        return self.db.one("SELECT * FROM recipients WHERE id=?", (rid,))

    def _public_recipient(self, r: dict) -> dict:
        return {"id": r["id"], "name": r["name"], "role": r["role"], "role_title": ROLE_TITLE.get(r["role"], r["role"]),
                "scope_id": r["scope_id"], "channel": r["channel"], "address": mask(r["channel"], r["address"]),
                "lang": r["lang"], "demo": bool(r["demo"]), "linked_via": r["linked_via"], "level": LEVEL_OF.get(r["role"]),
                "villages": self.villages_of(r["scope_id"])}

    @staticmethod
    def villages_of(scope_id: str) -> list[str]:
        out = []
        for v in S.VILLAGES:
            p = S.admin_path(v)
            if scope_id in (v["id"], p["block_id"], p["district_id"], p["state_id"]):
                out.append(v["id"])
        return out

    def villages_for(self, r: dict) -> list[str]:
        if r["role"] == "household":
            hh = self.ctx.households.get(r["scope_id"])
            return [hh["village_id"]] if hh else []
        return self.villages_of(r["scope_id"])

    # ------------------------------------------------------------------ link codes
    def issue_link(self, *, role: str, scope_id: str, name: str, lang: str = "en", acting: dict | None = None) -> dict:
        now = time.time()
        self.db.execute("DELETE FROM link_codes WHERE expires_wall < ?", (now,))
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(6))
        self.db.insert("link_codes", {"code": code, "role": role, "scope_id": scope_id, "name": name, "lang": lang,
                                      "acting": acting or {}, "expires_wall": now + C.LINK_CODE_TTL_S, "used": 0})
        tg, wa = self.channels["telegram"], self.channels["whatsapp"]
        return {"code": code, "expires_in_s": C.LINK_CODE_TTL_S,
                "telegram": {"url": f"https://t.me/{tg.username}?start={code}", "bot": f"@{tg.username}"} if tg.username else None,
                "whatsapp": {"number": wa.number, "text": f"LINK {code}",
                             "url": f"https://wa.me/{_digits(wa.number)}?text=LINK%20{code}"} if wa.configured and wa.number else None,
                "live": bool(tg.username or (wa.configured and wa.number))}

    def _redeem(self, inb: Inbound, code: str):
        row = self.db.one("SELECT * FROM link_codes WHERE code=?", (code.strip().upper(),))
        if row is None or row["used"] or row["expires_wall"] < time.time():
            self._reply(inb, "This link has expired or was already used. Open JalSakhi and tap 'Get alerts on my phone' "
                             "again for a fresh one.\nयह लिंक पुराना हो गया है। जलसखी ऐप में फिर से लिंक बनाएँ।")
            return
        self.db.update("link_codes", "code", row["code"], {"used": 1})
        r = self._upsert_recipient(name=row["name"], role=row["role"], scope_id=row["scope_id"], channel=inb.channel,
                                   address=inb.address, lang=row["lang"], acting=row["acting"],
                                   linked_via=f"link code ({inb.name or inb.channel})")
        with self.ctx.lock:
            self.ctx.feed("system", "info", f"Phone linked for alerts: {r['name']} on {self.channels[inb.channel].label}",
                          (self.villages_for(r) or [None])[0])
            self.ctx.version += 1
        if r["role"] == "household":
            hh = self.ctx.households.get(r["scope_id"])
            village = self.ctx.sims[hh["village_id"]].name if hh else ""
            self._reply(inb, f"💧 {L.t(r['lang'], 'welcome', home=hh['label'] if hh else r['scope_id'], village=village)}", r)
        else:
            where = ", ".join(self.ctx.sims[v].name for v in self.villages_of(r["scope_id"])) or r["scope_id"]
            self._reply(inb, f"✅ JalSakhi: linked as {ROLE_TITLE[r['role']]} for {where}.\n"
                             f"You will get level {LEVEL_OF[r['role']]} alerts here. Tap Acknowledge on an alert, "
                             "or send /status for the open incidents.", r)

    # --------------------------------------------------------------------- routing
    def _staff_for(self, village_id: str, level: int, roles: tuple[str, ...] | None = None) -> list[dict]:
        p = S.admin_path(S.village_by_id(village_id))
        want = {1: [("operator", village_id), ("vwsc", village_id)], 2: [("block", p["block_id"])],
                3: [("district", p["district_id"])]}[level]
        out = []
        for role, scope in want:
            if roles is not None and role not in roles:
                continue
            out += self.db.query("SELECT * FROM recipients WHERE active=1 AND role=? AND scope_id=?", (role, scope))
        return out

    def incident_opened(self, inc: dict):
        """A new incident: level 1 hears at once; a critical one goes to the block as well."""
        if inc.get("is_seed"):
            return
        roles = ("operator",) if inc["category"] == "sensor" or inc["severity"] == "low" else None
        for r in self._staff_for(inc["village_id"], 1, roles):
            self._send(r, "incident", self._staff_text(inc, r), incident=inc, buttons=self._staff_buttons(inc))
        if inc["severity"] == "critical":
            for r in self._staff_for(inc["village_id"], 2):
                self._send(r, "incident", self._staff_text(inc, r), incident=inc, buttons=self._staff_buttons(inc))

    def escalated(self, inc: dict, level: int, why: str):
        for r in self._staff_for(inc["village_id"], level):
            head = f"⏫ ESCALATED to you (level {level}) · {self._vname(inc)}\n{why}\n\n"
            self._send(r, f"escalation{level}", head + self._staff_text(inc, r, header=False), incident=inc,
                       buttons=self._staff_buttons(inc))

    def reopened(self, inc: dict, household_label: str):
        for r in self._staff_for(inc["village_id"], 1):
            self._send(r, f"reopened:{household_label}", f"↩️ REOPENED · {self._vname(inc)}\n{inc['id']} {inc['title']}\n"
                       f"{household_label} says the problem is NOT fixed. The incident is back in progress.", incident=inc)

    def notified(self, note_id: int, village_id: str, kind: str, params: dict, branch_id=None, household_id=None,
                 incident_id=None):
        """Mirror a citizen-app notification to the phones linked to the households it is addressed to."""
        for r in self.db.query("SELECT * FROM recipients WHERE active=1 AND role='household'"):
            hh = self.ctx.households.get(r["scope_id"])
            if hh is None or hh["village_id"] != village_id:
                continue
            if household_id and hh["id"] != household_id or branch_id and hh["branch_id"] != branch_id:
                continue
            text = f"💧 JalSakhi · {hh['label']}\n{L.t(r['lang'], 'n_' + kind, **(params or {}))}"
            buttons = None
            if kind == "status_resolved_pending_verification":
                text += f"\n\n{L.t(r['lang'], 'is_fixed')} {L.t(r['lang'], 'reply_yn')}"
                buttons = [[(L.t(r["lang"], "fixed_yes"), "fix:yes"), (L.t(r["lang"], "fixed_no"), "fix:no")]]
            inc = self.ctx.incidents.items.get(incident_id or "")
            self._send(r, f"n{note_id}", text, incident=inc, village_id=village_id, buttons=buttons)

    # ------------------------------------------------------------------- messages
    def _vname(self, inc: dict) -> str:
        return self.ctx.sims[inc["village_id"]].name

    def _where(self, inc: dict) -> str:
        sim = self.ctx.sims[inc["village_id"]]
        if inc["scope_type"] == "household":
            hh = self.ctx.households.get(inc["scope_id"])
            return f"{hh['label']}, {hh['lane']}" if hh else inc["scope_id"]
        if inc.get("branch_id") in sim.branch_ids:
            return sim.branch_names[sim.branch_ids.index(inc["branch_id"])]
        return "whole scheme"

    def _staff_text(self, inc: dict, r: dict, header: bool = True) -> str:
        lines = []
        if header:
            lines.append(f"{SEV_MARK.get(inc['severity'], inc['severity'])} · {self._vname(inc)} (demo data)")
        lines += [f"{inc['id']} · {TYPES[inc['type']]['label']} · {self._where(inc)}",
                  f"{inc['affected_count']} home(s) affected · priority {round(inc['priority'])}/100"
                  + (f" · {inc['report_count']} citizen report(s)" if inc.get("report_count") else "")]
        if inc.get("suspected_cause"):
            lines.append(f"Cause: {inc['suspected_cause']}")
        if inc.get("suggested_action"):
            lines.append(f"Do: {inc['suggested_action']}")
        if inc["status"] == "open" and inc.get("sla_ack_due"):
            lines.append(f"Acknowledge by {inc['sla_ack_due'][11:16]} (simulation time), or it escalates.")
        if r["channel"] != "telegram":
            lines.append(f"Reply ACK {inc['id']} to acknowledge, WORK {inc['id']} when work starts.")
        return "\n".join(lines)

    @staticmethod
    def _staff_buttons(inc: dict) -> list:
        return [[("✅ Acknowledge", f"ack:{inc['id']}"), ("🛠 Start work", f"work:{inc['id']}")]]

    def _send(self, r: dict, kind: str, text: str, *, incident: dict | None = None, village_id: str | None = None,
              buttons: list | None = None, dedupe: bool = True) -> int | None:
        """Queue one message to one recipient. Returns the delivery id, or None when it is a duplicate."""
        key = f"{self.epoch}:{r['id']}:{kind}:{incident['id'] if incident else ''}" if dedupe else None
        if key and self.db.scalar("SELECT 1 FROM deliveries WHERE dedupe=?", (key,)):
            return None
        ch = self.channels[r["channel"]]
        now = time.time()
        recent = self.db.scalar("SELECT COUNT(*) FROM deliveries WHERE recipient_id=? AND direction='out' AND created_wall>?"
                                " AND status IN ('queued','retry','sending','sent','sandbox')", (r["id"], now - C.ALERT_RATE[1]))
        if r["demo"]:
            status, err = "sandbox", "placeholder DEMO number: shown here, never sent"
        elif not ch.configured:
            status, err = "sandbox", f"{ch.label} is not configured on this server"
        elif recent >= C.ALERT_RATE[0]:
            status, err = "held", f"rate limit: more than {C.ALERT_RATE[0]} messages to this phone in {C.ALERT_RATE[1] // 60} minutes"
        else:
            status, err = "queued", None
        did = self.db.insert("deliveries", {
            "epoch": self.epoch, "direction": "out", "recipient_id": r["id"], "channel": r["channel"], "address": r["address"],
            "name": r["name"], "role": r["role"], "kind": kind.split(":")[0], "incident_id": incident["id"] if incident else None,
            "village_id": incident["village_id"] if incident else village_id, "dedupe": key, "text": text, "buttons": buttons,
            "status": status, "last_error": err, "created_wall": now, "next_attempt": 0})
        if status == "queued":
            self._wake.set()
        return did

    def _reply(self, inb: Inbound, text: str, r: dict | None = None, buttons: list | None = None):
        r = r or {"id": None, "name": inb.name or inb.address, "role": None, "channel": inb.channel,
                  "address": inb.address, "demo": 0}
        self._send(r, "reply", text, buttons=buttons, dedupe=False,
                   village_id=(self.villages_for(r) or [None])[0] if r.get("role") else None)

    def test(self, r: dict) -> int | None:
        where = ", ".join(self.ctx.sims[v].name for v in self.villages_for(r)) or r["scope_id"]
        text = (f"✅ JalSakhi test message for {r['name']}.\nThis phone gets "
                + (f"level {LEVEL_OF[r['role']]} alerts for {where}." if r["role"] in LEVEL_OF else f"household alerts for {where}.")
                + f"\nSent {time.strftime('%H:%M:%S')}.")
        return self._send(r, "test", text, dedupe=False)

    # -------------------------------------------------------------------- delivery
    def deliver_due(self, limit: int = 20) -> int:
        """Send what is due. Network calls happen outside every lock."""
        now = time.time()
        rows = self.db.query("SELECT * FROM deliveries WHERE status IN ('queued','retry') AND next_attempt<=? ORDER BY id"
                             " LIMIT ?", (now, limit))
        sent = 0
        for d in rows:
            claimed = self.db.execute("UPDATE deliveries SET status='sending' WHERE id=? AND status IN ('queued','retry')",
                                      (d["id"],)).rowcount
            if not claimed:  # another pass took it
                continue
            ch = self.channels[d["channel"]]
            attempts = d["attempts"] + 1
            if not ch.configured:  # credentials were removed while it waited
                self.db.update("deliveries", "id", d["id"], {"status": "sandbox", "last_error": f"{ch.label} is not configured on this server"})
                continue
            try:
                ref = ch.send(d["address"], d["text"], d["buttons"] or None)
            except Exception as exc:  # a provider's failure, whatever its shape, is a failed attempt, never a lost row
                exc = exc if isinstance(exc, ChannelError) else ChannelError(f"{type(exc).__name__}: {exc}")
                ch.error = str(exc)
                give_up = attempts >= MAX_ATTEMPTS
                self.db.update("deliveries", "id", d["id"], {
                    "status": "failed" if give_up else "retry", "attempts": attempts, "last_error": str(exc)[:300],
                    "next_attempt": now + BACKOFF[min(attempts - 1, len(BACKOFF) - 1)]})
                log.warning("alert %s to %s via %s failed: %s", d["id"], mask(d["channel"], d["address"]), d["channel"], exc)
                continue
            ch.error = None
            self.db.update("deliveries", "id", d["id"], {"status": "sent", "attempts": attempts, "last_error": None,
                                                         "provider_ref": ref, "sent_wall": time.time()})
            sent += 1
        return sent

    def _deliver_loop(self):
        while not self._stop.is_set():
            self._wake.wait(2.0)
            self._wake.clear()
            try:
                self.deliver_due()
            except Exception:  # the loop must survive anything a provider throws at it
                log.exception("alert delivery pass failed")

    # -------------------------------------------------------------------- telegram
    def _telegram_loop(self):
        tg: Telegram = self.channels["telegram"]
        offset = int(self.db.scalar("SELECT value FROM kv WHERE key='tg_offset'") or 0)
        while not self._stop.is_set():
            try:
                if tg.username is None:
                    me = tg.call("getMe")
                    tg.username = me.get("username")
                    tg.call("deleteWebhook", {"drop_pending_updates": False})  # getUpdates refuses to run while a webhook is set
                    log.info("Telegram bot @%s connected", tg.username)
                tg.polling = True
                updates = tg.call("getUpdates", {"offset": offset, "timeout": 25,
                                                 "allowed_updates": ["message", "callback_query"]}, timeout=40)
                tg.last_poll, tg.error = time.time(), None
                for u in updates:
                    offset = max(offset, u["update_id"] + 1)
                    self.db.execute("INSERT OR REPLACE INTO kv (key, value) VALUES ('tg_offset', ?)", (str(offset),))
                    try:
                        inb = self._from_telegram(u)
                        if inb is not None:
                            self.handle(inb)
                    except Exception:
                        log.exception("Telegram update %s could not be handled", u.get("update_id"))
            except ChannelError as exc:
                tg.polling, tg.error = False, str(exc)
                if "409" in str(exc):
                    tg.error = "another copy of JalSakhi is reading this bot's messages; stop it, or give each copy its own bot"
                log.warning("Telegram: %s", tg.error)
                self._stop.wait(30 if "409" in str(exc) or "401" in str(exc) else 5)

    def _from_telegram(self, u: dict) -> Inbound | None:
        tg: Telegram = self.channels["telegram"]
        if "callback_query" in u:
            q = u["callback_query"]
            try:
                tg.call("answerCallbackQuery", {"callback_query_id": q["id"]})
            except ChannelError:
                pass
            msg = q.get("message") or {}
            return Inbound("telegram", str(msg.get("chat", {}).get("id")), (q.get("from") or {}).get("first_name", ""),
                           button=q.get("data"))
        m = u.get("message")
        if not m:
            return None
        inb = Inbound("telegram", str(m["chat"]["id"]), (m.get("from") or {}).get("first_name", ""),
                      text=m.get("text") or m.get("caption") or "")
        if m.get("location"):
            inb.lat, inb.lon = m["location"]["latitude"], m["location"]["longitude"]
        if m.get("photo"):
            fid = m["photo"][-1]["file_id"]  # the largest size Telegram kept
            inb.photo = lambda: tg.file_bytes(fid)
        return inb

    # ------------------------------------------------------------- whatsapp inbound
    def whatsapp_webhook(self, payload: dict) -> int:
        wa: WhatsApp = self.channels["whatsapp"]
        n = 0
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value") or {}
                names = {c.get("wa_id"): (c.get("profile") or {}).get("name", "") for c in value.get("contacts", [])}
                for m in value.get("messages", []):
                    inb = Inbound("whatsapp", "+" + _digits(m.get("from", "")), names.get(m.get("from"), ""))
                    kind = m.get("type")
                    if kind == "text":
                        inb.text = (m.get("text") or {}).get("body", "")
                    elif kind == "interactive":
                        inb.button = ((m.get("interactive") or {}).get("button_reply") or {}).get("id")
                    elif kind == "button":
                        inb.text = (m.get("button") or {}).get("text", "")
                    elif kind == "location":
                        inb.lat, inb.lon = m["location"].get("latitude"), m["location"].get("longitude")
                    elif kind == "image":
                        mid = m["image"]["id"]
                        inb.text = m["image"].get("caption", "")
                        inb.photo = lambda mid=mid: wa.media_bytes(mid)
                    wa.last_inbound = time.time()
                    self.handle(inb)
                    n += 1
        return n

    # ---------------------------------------------------------------- conversation
    def handle(self, inb: Inbound):
        """Everything a phone can say to JalSakhi, on any channel."""
        text = (inb.text or "").strip()
        up = text.upper()
        rs = self.db.query("SELECT * FROM recipients WHERE active=1 AND channel=? AND address=?", (inb.channel, inb.address))
        hh_r = next((r for r in rs if r["role"] == "household"), None)
        staff_r = next((r for r in rs if r["role"] in STAFF_ROLES), None)
        self.db.insert("deliveries", {
            "epoch": self.epoch, "direction": "in", "recipient_id": (hh_r or staff_r or {}).get("id"), "channel": inb.channel,
            "address": inb.address, "name": (hh_r or staff_r or {}).get("name") or inb.name or "unlinked phone",
            "role": (hh_r or staff_r or {}).get("role"), "kind": "inbound",
            "village_id": ((self.villages_for(hh_r or staff_r)) or [None])[0] if (hh_r or staff_r) else None,
            "text": text or (f"[button {inb.button}]" if inb.button else "[photo]" if inb.photo else
                             f"[location {inb.lat:.5f}, {inb.lon:.5f}]" if inb.lat is not None else "[message]"),
            "status": "received", "created_wall": time.time()})

        m = re.match(r"^/?(START|LINK)\s+([A-Z0-9]{6})$", up)
        if m:
            return self._redeem(inb, m.group(2))
        if up.startswith("JAL "):
            return self._report_by_code(inb, text)
        if not rs:
            return self._reply(inb, "💧 Welcome to JalSakhi. To get water alerts here, open the JalSakhi app and tap "
                                    "'Get alerts on my phone'. Or report straight away: JAL <HOUSEHOLD-ID> <problem>.\n"
                                    "जलसखी में आपका स्वागत है। अलर्ट पाने के लिए जलसखी ऐप में 'मेरे फ़ोन पर अलर्ट' दबाएँ।")
        if up in ("STOP", "/STOP"):
            for r in rs:
                self.remove_recipient(r["id"])
            return self._reply(inb, L.t((hh_r or {}).get("lang", "en"), "stopped"), hh_r or staff_r)
        if staff_r and ((inb.button or "").split(":")[0] in ("ack", "work") or re.match(r"^/?(ACK|WORK|STATUS)\b", up)):
            return self._staff_command(inb, staff_r, up)
        if hh_r:
            return self._household(inb, hh_r, text)
        return self._reply(inb, "Commands: /status for open incidents, ACK <INC-ID> to acknowledge, WORK <INC-ID> when work "
                                "starts, STOP to unlink.", staff_r)

    def _staff_command(self, inb: Inbound, r: dict, up: str):
        if inb.button:
            verb, inc_id = inb.button.split(":", 1)
        else:
            m = re.match(r"^/?(ACK|WORK|STATUS)\s*(INC-\d+)?", up)
            verb, inc_id = m.group(1).lower(), m.group(2)
        villages = set(self.villages_of(r["scope_id"]))
        ctx = self.ctx
        if verb == "status":
            with ctx.lock:
                rows = sorted([i for i in ctx.incidents.items.values() if i["village_id"] in villages], key=lambda i: -i["priority"])
                lines = [f"{SEV_MARK.get(i['severity'], '')} {i['id']} · {TYPES[i['type']]['label']} · {ctx.sims[i['village_id']].name}"
                         f" · {i['status'].replace('_', ' ')}" for i in rows[:8]]
            return self._reply(inb, ("Open incidents:\n" + "\n".join(lines)) if lines else "No open incidents in your area.", r)
        if not inc_id:
            return self._reply(inb, f"Which incident? For example: {verb.upper()} INC-0004", r)
        actor = r["acting"] or {}
        who = {"name": f"{actor.get('name') or r['name']} (via {self.channels[inb.channel].label})",
               "role": actor.get("role") or r["role"]}
        with ctx.lock:
            inc = ctx.incidents.items.get(inc_id)
            if inc is None or inc["village_id"] not in villages:
                return self._reply(inb, f"{inc_id} is not an open incident in your area.", r)
            try:
                if verb == "ack" and inc["status"] == "open":
                    ctx.incidents.act(inc_id, "acknowledge", who, {"note": "Acknowledged from the phone alert"})
                    done = "acknowledged"
                elif verb == "work" or verb == "ack":
                    if inc["status"] in ("open", "acknowledged"):
                        ctx.incidents.act(inc_id, "start", who, {"note": "Work started (reported from the phone)"})
                        done = "marked as work started"
                    else:
                        done = f"already {inc['status'].replace('_', ' ')}"
                ctx.version += 1
            except IncidentError as exc:
                return self._reply(inb, f"{inc_id}: {exc}", r)
        return self._reply(inb, f"👍 {inc_id} {done} by {who['name']}. The dashboard shows it now.", r)

    def _household(self, inb: Inbound, r: dict, text: str):
        lang, ctx = r["lang"], self.ctx
        key = (inb.channel, inb.address)
        if key in self.drafts and time.time() - self.drafts[key]["at"] > DRAFT_TTL_S:
            self.drafts.pop(key)  # a photo sent a quarter of an hour ago belongs to some other problem
        draft = self.drafts.get(key)
        word = text.lower().strip(" \t\r\n!?.,;:'\"()।॥…")  # not \w: it drops Indic vowel signs, so होय would read हय
        if inb.button and inb.button.startswith("fix:") or word in L.YES or word in L.NO:
            return self._confirm(inb, r, inb.button == "fix:yes" if inb.button else word in L.YES)
        if word in ("status", "/status"):
            return self._status(inb, r)
        if word in ("help", "/help", "start", "/start"):
            return self._reply(inb, L.t(lang, "help"), r)
        if inb.photo is not None or inb.lat is not None:
            draft = draft or {"at": time.time(), "photo": None, "lat": None, "lon": None}
            got = []
            if inb.lat is not None:
                draft.update(lat=inb.lat, lon=inb.lon)
                got.append(L.t(lang, "loc_ok"))
            if inb.photo is not None:
                try:
                    draft["photo"] = self._save_photo(inb.photo())
                    got.append(L.t(lang, "photo_ok"))
                except ChannelError as exc:
                    log.warning("photo from %s not saved: %s", mask(inb.channel, inb.address), exc)
            draft["at"] = time.time()
            self.drafts[key] = draft
            if not text:
                return self._reply(inb, " ".join(got + [L.t(lang, "ask_cat")]), r, buttons=self._cat_buttons(lang))
        category = inb.button.split(":", 1)[1] if inb.button and inb.button.startswith("cat:") else None
        if category not in CATS:
            category = None
        if not category and len(text) < 3:
            return self._reply(inb, L.t(lang, "ask_cat"), r, buttons=self._cat_buttons(lang))
        draft = self.drafts.pop(key, None) or {}
        geo = draft.get("lat") is not None
        with ctx.lock:
            try:
                c = ctx.complaints.create({"household_id": r["scope_id"], "category": category, "description": text,
                                           "language": lang, "channel": inb.channel, "source": "portal",
                                           "photo": draft.get("photo"), "lat": draft.get("lat"), "lon": draft.get("lon"),
                                           "geo_source": f"{inb.channel}-location" if geo else None})
            except ComplaintError as exc:
                return self._reply(inb, str(exc), r)
            ctx.version += 1
        linked = L.t(lang, "linked_new") if c["linked"] == "opened" else L.t(lang, "linked_existing", n=c["incident"]["affected_count"])
        return self._reply(inb, f"✅ {L.t(lang, 'report_ok', id=c['id'], cat=L.t(lang, 'cat_' + c['category']))}\n{linked}", r)

    def _cat_buttons(self, lang: str) -> list:
        return [[(L.t(lang, f"cat_{a}"), f"cat:{a}"), (L.t(lang, f"cat_{b}"), f"cat:{b}")] for a, b in zip(CATS[::2], CATS[1::2])]

    def _confirm(self, inb: Inbound, r: dict, fixed: bool):
        ctx, lang = self.ctx, r["lang"]
        with ctx.lock:
            c = ctx.db.one("SELECT id FROM complaints WHERE household_id=? AND status='resolved_pending_verification'"
                           " AND citizen_confirmed IS NULL ORDER BY seq DESC", (r["scope_id"],))
            if c is None:
                return self._reply(inb, L.t(lang, "none_pending"), r)
            ctx.complaints.confirm(c["id"], fixed, 5 if fixed else 2, actor=f"citizen ({self.channels[inb.channel].label})")
            ctx.version += 1
        return self._reply(inb, L.t(lang, "thanks" if fixed else "reopened"), r)

    def _status(self, inb: Inbound, r: dict):
        from .monitor import STATUS_NAME
        ctx, lang = self.ctx, r["lang"]
        with ctx.lock:
            hh = ctx.households[r["scope_id"]]
            mon = ctx.monitors[hh["village_id"]]
            i = mon.hh_ids.index(hh["id"])
            st = STATUS_NAME[int(mon.status[i])]
            lpcd = round(float(mon.vol[i] / mon.members[i]))
            quality = bool(mon._quality_affected()[i])
        return self._reply(inb, f"💧 {hh['label']}: {L.t(lang, st + '_t')}\n{L.t(lang, 'today')}: {lpcd} {L.t(lang, 'per_person')}\n"
                                f"{L.t(lang, 'q_verify' if quality else 'q_ok')}", r)

    def _report_by_code(self, inb: Inbound, text: str):
        parts = text.split(None, 2)
        hid = parts[1].upper() if len(parts) > 1 else ""
        ctx = self.ctx
        with ctx.lock:
            if hid not in ctx.households:
                return self._reply(inb, "Format: JAL <HOUSEHOLD-ID> <problem>, e.g. JAL PW-HH-014 pani nahi aa raha")
            try:
                c = ctx.complaints.create({"household_id": hid, "description": parts[2] if len(parts) > 2 else "",
                                           "category": None if len(parts) > 2 else "other", "language": "hi",
                                           "channel": inb.channel, "source": "portal"})
            except ComplaintError as exc:
                return self._reply(inb, str(exc))
            ctx.version += 1
        return self._reply(inb, f"JalSakhi: report {c['id']} registered ({CAT_LABEL[c['category']]}). Track with this ID.")

    @staticmethod
    def _save_photo(data: bytes) -> str:
        if len(data) > C.MAX_UPLOAD_BYTES:
            raise ChannelError("photo is larger than 5 MB")
        ext = ".png" if data[:8] == b"\x89PNG\r\n\x1a\n" else ".webp" if data[8:12] == b"WEBP" else ".jpg"
        name = f"{uuid.uuid4().hex}{ext}"
        C.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        (C.UPLOAD_DIR / name).write_bytes(data)
        return f"/uploads/{name}"

    # ---------------------------------------------------------------------- views
    def state(self, villages: set[str]) -> dict:
        rs = [self._public_recipient(r) for r in self.db.query("SELECT * FROM recipients WHERE active=1 ORDER BY id")]
        rs = [r for r in rs if r["role"] == "household" and self._hh_village(r["scope_id"]) in villages
              or r["role"] != "household" and set(r["villages"]) & villages]
        rows = self.db.query("SELECT id, direction, recipient_id, channel, address, name, role, kind, incident_id, village_id,"
                             " text, buttons, status, attempts, last_error, provider_ref, created_wall, sent_wall FROM deliveries"
                             " WHERE epoch=? ORDER BY id DESC LIMIT 400", (self.epoch,))
        rows = [d for d in rows if d["village_id"] is None or d["village_id"] in villages][:150]
        for d in rows:
            d["address"] = mask(d["channel"], d["address"])
        counts = {r["status"]: r["n"] for r in self.db.query(
            "SELECT status, COUNT(*) n FROM deliveries WHERE epoch=? GROUP BY status", (self.epoch,))}
        return {"channels": [c.status() for c in self.channels.values()], "recipients": rs, "log": rows, "counts": counts,
                "live": self.live, "rate": {"max": C.ALERT_RATE[0], "per_s": C.ALERT_RATE[1]}}

    def _hh_village(self, hid: str) -> str | None:
        hh = self.ctx.households.get(hid)
        return hh["village_id"] if hh else None

    def for_incident(self, incident_id: str) -> list[dict]:
        rows = self.db.query("SELECT id, channel, address, name, role, kind, status, last_error, created_wall, sent_wall FROM"
                             " deliveries WHERE epoch=? AND incident_id=? AND direction='out' ORDER BY id", (self.epoch, incident_id))
        for d in rows:
            d["address"] = mask(d["channel"], d["address"])
        return rows

    def household_links(self, household_id: str) -> list[dict]:
        return [{"channel": r["channel"], "address": mask(r["channel"], r["address"])} for r in self.db.query(
            "SELECT channel, address FROM recipients WHERE active=1 AND role='household' AND scope_id=?", (household_id,))]

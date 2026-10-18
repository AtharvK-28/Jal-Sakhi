"""JalSakhi AI HTTP API (FastAPI).

Public endpoints serve citizens and field devices; everything else needs a
staff bearer token. The simulator, detection engine and sync worker run in a
background task started with the app.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import socket
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import Body, Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import config as C
from . import seed as S
from .core import analytics, planner
from .core import interop, invest, sampling
from .core.alerts import ROLE_TITLE as ALERT_ROLE_TITLE
from .core.complaints import ComplaintError, LABEL as COMPLAINT_LABEL
from .core.incidents import IncidentError, TYPES as INCIDENT_TYPES
from .core.monitor import STATUS_NAME
from .core.security import ROLE_LABEL, STAFF_ROLES, hash_pw, make_token, read_token
from .core.telemetry import UNITS
from .ml.nlp_corpus import CATEGORIES
from .sim.engine import HW_DEVICE, SCENARIOS, Platform

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("jalsakhi.api")

P: Platform | None = None


class CodeWatch:
    """Notices when the backend source on disk is no longer the code this process loaded.

    A server left running across an update keeps answering with its old routes and payloads, which a freshly
    built UI cannot draw. /api/health reports it so the UI can ask for a restart instead of showing nothing."""

    def __init__(self, root: Path):
        self.root = root
        self._seen = self._mtimes()
        self._loaded = self._digest()
        self._checked = time.monotonic()
        self.stale = False

    def _files(self) -> list[Path]:
        return sorted(self.root.rglob("*.py"))

    def _mtimes(self) -> tuple:
        return tuple((str(p), p.stat().st_mtime_ns) for p in self._files())

    def _digest(self) -> str:
        h = hashlib.sha1()
        for p in self._files():
            h.update(p.relative_to(self.root).as_posix().encode())
            h.update(p.read_bytes())
        return h.hexdigest()

    def check(self, every: float = 3.0) -> bool:
        if time.monotonic() - self._checked >= every:  # a few stat calls, and a re-hash only when one changed
            self._checked = time.monotonic()
            try:
                seen = self._mtimes()
                if seen != self._seen:
                    self._seen, self.stale = seen, self._digest() != self._loaded
            except OSError:
                pass  # a file caught mid-save: look again next time
        return self.stale


code = CodeWatch(C.BASE_DIR / "app")


class Hub:
    """Fan-out of live snapshots to Server-Sent-Event subscribers."""

    def __init__(self):
        self.subs: dict[int, tuple[asyncio.Queue, str | None, frozenset | None]] = {}
        self._n = 0

    def add(self, village: str | None, scope: frozenset | None):
        self._n += 1
        q: asyncio.Queue = asyncio.Queue(maxsize=2)
        self.subs[self._n] = (q, village, scope)
        return self._n, q

    def remove(self, sid: int):
        self.subs.pop(sid, None)

    def broadcast(self):
        cache: dict = {}
        for q, village, scope in list(self.subs.values()):
            key = (village, scope)
            if key not in cache:
                cache[key] = json.dumps(scoped_snapshot(village, scope), separators=(",", ":"), default=_json_default)
            if q.full():
                q.get_nowait()  # a slow client only ever needs the newest snapshot
            q.put_nowait(cache[key])


hub = Hub()


def _json_default(o):
    if hasattr(o, "item"):
        return o.item()
    if isinstance(o, (set, frozenset)):
        return sorted(o)
    raise TypeError(f"not serialisable: {type(o)}")


def scoped_snapshot(village: str | None, scope: frozenset | None) -> dict:
    snap = P.snapshot(village)
    if scope is not None:
        snap["summary"] = [s for s in snap["summary"] if s["id"] in scope]
        snap["incidents"] = [i for i in snap["incidents"] if i["village_id"] in scope]
        snap["feed"] = [f for f in snap["feed"] if f["village_id"] is None or f["village_id"] in scope]
    return snap


async def ticker():
    last_push = 0.0
    last_version = -1
    while True:
        await asyncio.sleep(C.TICK_SECONDS / max(1, P.speed))
        try:
            if P.running:
                await asyncio.to_thread(P.step)
            now = time.monotonic()
            if hub.subs and P.version != last_version and now - last_push >= 0.3:
                hub.broadcast()
                last_push, last_version = now, P.version
        except Exception:  # the loop must survive a bad tick
            log.exception("tick failed")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global P
    P = Platform()
    if os.environ.get("JALSAKHI_PAUSED"):  # tests step the clock themselves
        P.running = False
    task = asyncio.create_task(ticker())
    P.alerts.start()
    log.info("JalSakhi AI ready: %d villages, %d households (simulated)", len(P.sims), len(P.households))
    yield
    P.alerts.stop()
    task.cancel()


app = FastAPI(
    title=C.APP_NAME,
    version=C.APP_VERSION,
    lifespan=lifespan,
    description="Rural water service monitoring PoC. All telemetry is simulated; integrations are sandboxed.",
)

cors_env = os.environ.get("CORS_ORIGINS", "*")
cors_origins = [o.strip() for o in cors_env.split(",") if o.strip()] if cors_env != "*" else ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True if "*" not in cors_origins else False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    # Cross-origin requests carry the origin only (never the path). Map tile servers require a Referer:
    # "no-referrer" here gets every OpenStreetMap tile replaced by an "Access blocked" image.
    resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    if request.url.path.startswith("/api/"):
        resp.headers.setdefault("Cache-Control", "no-store")
    return resp


@app.exception_handler(IncidentError)
async def _incident_error(_r, exc: IncidentError):
    return JSONResponse({"detail": str(exc)}, status_code=exc.status)


@app.exception_handler(ComplaintError)
async def _complaint_error(_r, exc: ComplaintError):
    return JSONResponse({"detail": str(exc)}, status_code=exc.status)


# ------------------------------------------------------------------- security
def current_user(request: Request, authorization: str | None = Header(default=None), token: str | None = Query(default=None)):
    raw = authorization[7:] if authorization and authorization.lower().startswith("bearer ") else token
    return read_token(raw)


def staff(user=Depends(current_user)) -> dict:
    if user is None:
        raise HTTPException(401, "sign in required")
    if user.get("role") not in STAFF_ROLES:
        raise HTTPException(403, "staff access only")
    return user


def scope_of(user: dict) -> set[str]:
    return analytics.scope_villages(user)


def need_village(user: dict, village_id: str):
    if village_id not in P.sims:
        raise HTTPException(404, "unknown village")
    if village_id not in scope_of(user):
        raise HTTPException(403, "this village is outside your jurisdiction")


def lan_urls(port: int) -> list[str]:
    urls = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        urls.append(f"http://{s.getsockname()[0]}:{port}")
        s.close()
    except OSError:
        pass
    return urls


# --------------------------------------------------------------------- public
@app.get("/api/health")
def health():
    return {"status": "ok", "app": C.APP_NAME, "version": C.APP_VERSION, "sim_time": P.now.isoformat(), "tick": P.tick,
            "running": P.running, "models_loaded": True, "data": "simulated", "uptime_s": round(time.time() - P.started_wall),
            "stale": code.check()}  # true: the code on disk changed after this process started, restart it


@app.get("/api/meta")
def meta(request: Request):
    port = request.url.port or 8000
    return {
        "app": C.APP_NAME, "version": C.APP_VERSION, "languages": C.LANGUAGES, "categories": CATEGORIES,
        "category_labels": COMPLAINT_LABEL, "focus_village": S.FOCUS_VILLAGE, "lpcd_norm": C.LPCD_NORM,
        "villages": [{"id": v["id"], "name": v["name"], **S.admin_path(v), "households": sum(v["branches"]), "lang": v["lang"],
                      "lat": v["lat"], "lon": v["lon"]} for v in S.VILLAGES],
        "accounts": [{"username": u["username"], "name": u["name"], "role": u["role"], "role_label": ROLE_LABEL[u["role"]],
                      "scope": u["scope_id"]} for u in S.USERS],
        "demo_password": C.DEMO_PASSWORD, "lan_urls": lan_urls(port),
        "supply_windows": [{"start": f"{s // 60:02d}:{s % 60:02d}", "end": f"{e // 60:02d}:{e % 60:02d}", "label": lbl}
                           for s, e, lbl in C.SUPPLY_WINDOWS],
        "quality_limits": C.QUALITY_LIMITS, "incident_types": INCIDENT_TYPES, "units": UNITS,
        "notice": "Proof of concept. All households, telemetry and identifiers are simulated. No live government integration.",
    }


class LoginBody(BaseModel):
    username: str
    password: str


@app.post("/api/auth/login")
def login(body: LoginBody):
    u = P.db.one("SELECT * FROM users WHERE username=?", (body.username.strip().lower(),))
    if u is None or hash_pw(body.password, u["salt"]) != u["pw_hash"]:
        P.audit.log(P.now, body.username[:40], "unknown", "auth.failed", "user", body.username[:40])
        raise HTTPException(401, "invalid username or password")
    claims = {k: u[k] for k in ("username", "name", "role", "scope_level", "scope_id")}
    P.audit.log(P.now, u["name"], u["role"], "auth.login", "user", u["username"])
    return {"token": make_token(claims), "user": {**claims, "role_label": ROLE_LABEL[u["role"]],
                                                  "villages": sorted(analytics.scope_villages(claims))}}


class CitizenLogin(BaseModel):
    household_id: str


@app.post("/api/auth/citizen")
def citizen_login(body: CitizenLogin):
    hh = P.households.get(body.household_id.strip().upper())
    if hh is None:
        raise HTTPException(404, "household not found")
    claims = {"username": hh["id"], "name": hh["label"], "role": "citizen", "scope_level": "household", "scope_id": hh["id"]}
    return {"token": make_token(claims), "household": _hh_public(hh)}


def _hh_public(hh: dict) -> dict:
    v = S.village_by_id(hh["village_id"])
    return {"id": hh["id"], "label": hh["label"], "lane": hh["lane"], "village_id": hh["village_id"], "village": v["name"],
            "members": hh["members"], "lang": v["lang"], "fhtc_id": hh["fhtc_ext_id"], "instrumented": hh["instrumented"]}


@app.get("/api/public/households")
def public_households(village: str = S.FOCUS_VILLAGE):
    if village not in P.sims:
        raise HTTPException(404, "unknown village")
    return [{"id": h["id"], "label": h["label"], "lane": h["lane"]} for h in P.households.values() if h["village_id"] == village]


def _hh_live(hh: dict) -> dict:
    mon = P.monitors[hh["village_id"]]
    i = mon.hh_ids.index(hh["id"])
    measured = bool(mon.instrumented[i]) and P.telemetry.fresh(f"{hh['id']}-TAP")
    st = STATUS_NAME[int(mon.status[i])]
    flags = mon.day_flags()
    return {"state": st, "pressure_bar": round(float(mon.p_est[i]), 2), "confidence": round(float(mon.conf[i]), 2),
            "basis": "idle" if st == "idle" else "unknown" if st == "unknown" else "measured" if measured else "estimated",
            "litres_today": round(float(mon.vol[i])), "lpcd_today": round(float(mon.vol[i] / mon.members[i]), 1),
            "flags": None if flags is None else {k: bool(flags[k][i]) for k in ("regular", "quantity", "quality", "known", "functional")},
            "quality_flag": bool(mon._quality_affected()[i])}


@app.get("/api/citizen/home")
def citizen_home(household_id: str):
    hh = P.households.get(household_id.upper())
    if hh is None:
        raise HTTPException(404, "household not found")
    with P.lock:
        vid = hh["village_id"]
        k = analytics.village_kpis(P, vid)
        notes = P.db.query(
            "SELECT id, kind, params, ts, incident_id FROM notifications WHERE village_id=? AND (household_id IS NULL OR household_id=?)"
            " AND (branch_id IS NULL OR branch_id=?) ORDER BY id DESC LIMIT 12", (vid, hh["id"], hh["branch_id"]))
        asked = P.db.one("SELECT got_water FROM pulse WHERE household_id=? AND day=? AND source='portal' ORDER BY id DESC",
                         (hh["id"], P.now.date().isoformat()))
        return {"household": _hh_public(hh), "clock": P.clock_state(), "supply": _hh_live(hh),
                "quality": {"status": k["quality_status"]}, "village": {"score": k["score"], "name": P.sims[vid].name},
                "alerts": notes, "complaints": P.complaints.for_household(hh["id"]),
                "charges": P.om.dues(hh["id"]), "contacts": S.CONTACTS,
                "pulse_today": None if asked is None else bool(asked["got_water"]), "lpcd_norm": C.LPCD_NORM}


@app.get("/api/citizen/village/{village_id}")
def citizen_village(village_id: str):
    """Public village water report card: no household-level data."""
    if village_id not in P.sims:
        raise HTTPException(404, "unknown village")
    with P.lock:
        k = analytics.village_kpis(P, village_id)
        mon = P.monitors[village_id]
        issues = [{"id": i["id"], "type": i["type"], "status": i["status"], "severity": i["severity"], "since": i["first_seen"],
                   "lane": next((b["name"] for b in mon.branch if b.get("id") == i["branch_id"]), None),
                   "affected": i["affected_count"]}
                  for i in P.incidents.items.values() if i["village_id"] == village_id and i["category"] != "sensor"]
        tests = P.db.query("SELECT kind, result, ts, sample_point FROM wq_tests WHERE village_id=? ORDER BY ts DESC LIMIT 5", (village_id,))
        hist = P.history.get(village_id, [])[-7:]
        return {"village": S.village_by_id(village_id)["name"], "admin": S.admin_path(S.village_by_id(village_id)),
                "score": k["score"], "functional": k["functional"], "counts": k["counts"], "lpcd_avg": k["lpcd_avg"],
                "quality": {"status": k["quality_status"], "sensors": [{k2: q[k2] for k2 in ("name", "turbidity_ntu", "chlorine_mgl", "ph", "status")} for q in mon.quality]},
                "tank_pct": mon.tank.get("level_pct"), "issues": issues, "tests": tests, "clock": P.clock_state(),
                "week": [{"day": r["day"], "functional_pct": r["functional_pct"]} for r in hist],
                "households": k["households"], "pulse": k["pulse"]}


@app.get("/api/citizen/notifications")
def citizen_notifications(household_id: str):
    hh = P.households.get(household_id.upper())
    if hh is None:
        raise HTTPException(404, "household not found")
    return P.db.query(
        "SELECT id, kind, params, ts, incident_id, channel FROM notifications WHERE village_id=? AND (household_id IS NULL OR household_id=?)"
        " AND (branch_id IS NULL OR branch_id=?) ORDER BY id DESC LIMIT 30", (hh["village_id"], hh["id"], hh["branch_id"]))


@app.post("/api/complaints", status_code=201)
async def create_complaint(household_id: str = Form(...), category: str | None = Form(None), description: str = Form(""),
                           language: str = Form("en"), lat: float | None = Form(None), lon: float | None = Form(None),
                           geo_source: str | None = Form(None), channel: str = Form("app"), consent: bool = Form(True),
                           photo: UploadFile | None = File(None)):
    if not consent:
        raise HTTPException(400, "consent is required to record a report")
    photo_url = None
    if photo is not None and photo.filename:
        if not (photo.content_type or "").startswith("image/"):
            raise HTTPException(415, "photo must be an image")
        data = await photo.read()
        if len(data) > C.MAX_UPLOAD_BYTES:
            raise HTTPException(413, "photo is larger than 5 MB")
        ext = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}.get(photo.content_type, ".img")
        name = f"{uuid.uuid4().hex}{ext}"
        C.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        (C.UPLOAD_DIR / name).write_bytes(data)
        photo_url = f"/uploads/{name}"
    with P.lock:
        return P.complaints.create({"household_id": household_id.strip().upper(), "category": category or None,
                                    "description": description, "language": language, "lat": lat, "lon": lon,
                                    "geo_source": geo_source, "channel": channel, "consent": consent, "photo": photo_url,
                                    "source": "portal"})


@app.get("/api/complaints/track/{tracking_id}")
def track(tracking_id: str):
    return P.complaints.track(tracking_id)


class ConfirmBody(BaseModel):
    resolved: bool
    rating: int | None = Field(default=None, ge=1, le=5)


@app.post("/api/complaints/{tracking_id}/confirm")
def confirm(tracking_id: str, body: ConfirmBody):
    with P.lock:
        return P.complaints.confirm(tracking_id.upper(), body.resolved, body.rating)


class PulseBody(BaseModel):
    household_id: str
    got_water: bool


@app.post("/api/pulse", status_code=201)
def pulse(body: PulseBody):
    hh = P.households.get(body.household_id.upper())
    if hh is None:
        raise HTTPException(404, "household not found")
    with P.lock:
        mon = P.monitors[hh["village_id"]]
        i = mon.hh_ids.index(hh["id"])
        inferred = int(mon.status[i] == 0) if P.clock.in_window else None
        P.db.insert("pulse", {"village_id": hh["village_id"], "household_id": hh["id"], "day": P.now.date().isoformat(),
                              "window_idx": P.clock.win_idx, "got_water": int(body.got_water), "inferred": inferred,
                              "source": "portal", "ts": P.now.isoformat(timespec="seconds")})
    return {"recorded": True, "matches_monitoring": None if inferred is None else bool(inferred) == body.got_water}


class TextBody(BaseModel):
    text: str = Field(max_length=1000)


@app.post("/api/nlp/classify")
def classify(body: TextBody):
    return P.models.classify(body.text)


class SmsBody(BaseModel):
    sender: str = "demo"
    text: str = Field(max_length=400)


@app.post("/api/sms/inbound", status_code=201)
def sms_inbound(body: SmsBody):
    """Simulated SMS gateway webhook: 'JAL <HOUSEHOLD-ID> <free text or keyword>' for feature phones."""
    parts = body.text.strip().split(None, 2)
    if len(parts) < 2 or parts[0].upper() != "JAL":
        raise HTTPException(400, "format: JAL <HOUSEHOLD-ID> <problem>, e.g. JAL PW-HH-014 pani nahi aa raha")
    text = parts[2] if len(parts) > 2 else ""
    keyword = {"NOWATER": "no_water", "LOW": "low_pressure", "DIRTY": "dirty_water", "LEAK": "leakage", "SMELL": "smell_taste",
               "TAP": "tap_damage"}.get(text.strip().upper())
    with P.lock:
        c = P.complaints.create({"household_id": parts[1].upper(), "category": keyword, "description": "" if keyword else text,
                                 "language": "hi", "channel": "sms", "source": "portal"})
    return {"tracking_id": c["id"], "category": c["category"], "reply_sms": f"JalSakhi: report {c['id']} registered ({c['category']}). Track with this ID."}


class TelemetryEvent(BaseModel):
    event_id: str
    device_id: str
    ts: str
    metrics: dict
    source: str = "hardware"
    quality: str = "good"


@app.post("/api/telemetry", status_code=201)
def post_telemetry(ev: TelemetryEvent, x_device_key: str | None = Header(default=None)):
    if x_device_key != C.DEVICE_KEY:
        raise HTTPException(401, "missing or invalid X-Device-Key")
    if ev.source not in ("hardware", "simulation", "manual"):
        raise HTTPException(422, "source must be hardware, simulation or manual")
    with P.lock:
        T = P.telemetry
        err = T.validate(ev.model_dump())
        if err:
            T.rejected += 1
            raise HTTPException(422, err)
        stored = T.accept(ev.device_id, datetime.fromisoformat(ev.ts), ev.metrics, event_id=ev.event_id, source=ev.source,
                          quality=ev.quality, received=P.now, tick=P.tick)
        T.flush()
        if stored and ev.device_id == HW_DEVICE:
            P.hw_seen(ev.metrics, ev.quality)
    if not stored:
        return JSONResponse({"stored": False, "duplicate": True, "event_id": ev.event_id}, status_code=200)
    return {"stored": True, "event_id": ev.event_id, "device_id": ev.device_id, "source": ev.source}


class AlertLinkBody(BaseModel):
    household_id: str
    lang: str = "en"


@app.post("/api/citizen/alerts/link")
def citizen_alert_link(body: AlertLinkBody):
    """A one-time code that links the phone it is opened on to this household's alerts."""
    hh = P.households.get(body.household_id.strip().upper())
    if hh is None:
        raise HTTPException(404, "household not found")
    lang = body.lang if body.lang in C.LANGUAGES else S.village_by_id(hh["village_id"])["lang"]
    return {**P.alerts.issue_link(role="household", scope_id=hh["id"], name=hh["label"], lang=lang),
            "linked": P.alerts.household_links(hh["id"])}


@app.get("/api/citizen/alerts")
def citizen_alerts(household_id: str):
    hh = P.households.get(household_id.strip().upper())
    if hh is None:
        raise HTTPException(404, "household not found")
    return {"linked": P.alerts.household_links(hh["id"]), "live": P.alerts.live}


@app.get("/api/whatsapp/webhook", include_in_schema=False)
def whatsapp_verify(request: Request):
    """Meta calls this once with the verify token you chose, to confirm the webhook is yours."""
    q = request.query_params
    if C.WHATSAPP_VERIFY_TOKEN and q.get("hub.mode") == "subscribe" and hmac.compare_digest(
            q.get("hub.verify_token") or "", C.WHATSAPP_VERIFY_TOKEN):
        return PlainTextResponse(q.get("hub.challenge") or "")
    raise HTTPException(403, "verification failed")


@app.post("/api/whatsapp/webhook", include_in_schema=False)
async def whatsapp_inbound(request: Request):
    raw = await request.body()
    if C.WHATSAPP_APP_SECRET:
        want = "sha256=" + hmac.new(C.WHATSAPP_APP_SECRET.encode(), raw, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(request.headers.get("X-Hub-Signature-256", ""), want):
            raise HTTPException(401, "bad signature")
    try:
        payload = json.loads(raw or b"{}")
    except ValueError:
        raise HTTPException(400, "not JSON")
    n = await asyncio.to_thread(P.alerts.whatsapp_webhook, payload)
    return {"received": n}


@app.post("/api/telemetry/ddws", status_code=201)
def post_telemetry_ddws(body: object = Body(...), x_device_key: str | None = Header(default=None)):
    """Readings in the ministry's reference device format (DDWS roadmap, March 2021): one message, a list, or
    {"messages": [...]}. Each is translated and then validated exactly like /api/telemetry."""
    if x_device_key != C.DEVICE_KEY:
        raise HTTPException(401, "missing or invalid X-Device-Key")
    msgs = body.get("messages", [body]) if isinstance(body, dict) else body
    if not isinstance(msgs, list) or not msgs or len(msgs) > 200:
        raise HTTPException(422, "send one message, a list, or {\"messages\": [...]} with at most 200 messages")
    out = []
    with P.lock:
        T = P.telemetry
        for m in msgs:
            try:
                ev = interop.ddws_in(m if isinstance(m, dict) else {}, T.devices, P.now)
                err = T.validate(ev)
            except ValueError as exc:
                err, ev = str(exc), None
            if err:
                T.rejected += 1
                out.append({"did": m.get("did") if isinstance(m, dict) else None, "stored": False, "error": err})
                continue
            stored = T.accept(ev["device_id"], datetime.fromisoformat(ev["ts"]), ev["metrics"], event_id=ev["event_id"],
                              source="hardware", quality=ev["quality"], received=P.now, tick=P.tick)
            if "battery" in ev:
                T.devices[ev["device_id"]]["battery"] = ev["battery"]
            if stored and ev["device_id"] == HW_DEVICE:
                P.hw_seen(ev["metrics"], ev["quality"])
            out.append({"did": m["did"], "device_id": ev["device_id"], "stored": stored, "duplicate": not stored,
                        "metrics": ev["metrics"], "quality": ev["quality"], "ignored": ev["ignored"]})
        T.flush()
    return {"accepted": sum(1 for r in out if r["stored"]), "results": out, "format": interop.DDWS_SOURCE}


# ---------------------------------------------------------------------- staff
@app.get("/api/stream")
async def stream(request: Request, village: str | None = None, user=Depends(staff)):
    scope = frozenset(scope_of(user))
    if village and village not in scope:
        village = None
    sid, q = hub.add(village, scope)

    async def gen():
        try:
            yield "retry: 1500\n\n"
            yield f"data: {json.dumps(scoped_snapshot(village, scope), separators=(',', ':'), default=_json_default)}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=10)
                    yield f"data: {msg}\n\n"
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            hub.remove(sid)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/snapshot")
def snapshot(village: str | None = None, user=Depends(staff)):
    return JSONResponse(json.loads(json.dumps(scoped_snapshot(village, frozenset(scope_of(user))), default=_json_default)))


@app.get("/api/overview")
def overview(level: str = "state", id: str = "ST-MH", user=Depends(staff)):
    if level not in analytics.LEVELS:
        raise HTTPException(400, f"level must be one of {analytics.LEVELS}")
    vids = {v["id"] for v in analytics.villages_under(level, id)}
    if not vids or not vids <= scope_of(user):
        raise HTTPException(403, "this unit is outside your jurisdiction")
    return _plain(analytics.overview(P, level, id))


@app.get("/api/hierarchy")
def hierarchy(user=Depends(staff)):
    return {"tree": analytics.hierarchy(P), "scope": sorted(scope_of(user)),
            "home": {"level": user["scope_level"], "id": user["scope_id"]}}


@app.get("/api/villages/{village_id}")
def village(village_id: str, user=Depends(staff)):
    need_village(user, village_id)
    with P.lock:
        v = P.db.one("SELECT * FROM villages WHERE id=?", (village_id,))
        return _plain({**P.twin(village_id), "scheme": v["scheme"]})


@app.get("/api/villages/{village_id}/geo")
def village_geo(village_id: str, user=Depends(staff)):
    """Ground layout for the GIS view: lanes, house footprints, fields, tank. Demo geometry, [lon, lat] coordinates."""
    need_village(user, village_id)
    return P.sims[village_id].geo()


class WhatIfBody(BaseModel):
    demand_pct: float = Field(default=0.0, ge=-50, le=100)
    pump_out_h: float = Field(default=0.0, ge=0, le=24)
    closed: list[int] = Field(default_factory=list)
    tank_pct: float | None = Field(default=None, ge=3, le=100)


@app.post("/api/villages/{village_id}/whatif")
def village_whatif(village_id: str, body: WhatIfBody, user=Depends(staff)):
    """Run the calibrated model of the village forward 24 h under a hypothetical change. Nothing live is touched."""
    need_village(user, village_id)
    return _plain(planner.what_if(P, village_id, body.demand_pct, body.pump_out_h, body.closed, body.tank_pct))


@app.get("/api/villages/{village_id}/timeline")
def village_timeline(village_id: str, user=Depends(staff)):
    """One row per recorded tick: [tick, HH:MM, in supply window, homes low, homes dry, homes unknown, lane alert]."""
    need_village(user, village_id)
    return P.timeline(village_id)


@app.get("/api/villages/{village_id}/replay")
def village_replay(village_id: str, k: int, user=Depends(staff)):
    """The twin as it stood at recorded tick k."""
    need_village(user, village_id)
    frame = P.replay(village_id, k)
    if frame is None:
        raise HTTPException(404, "that moment is no longer in the replay buffer")
    return _plain(frame)


@app.get("/api/villages/{village_id}/trends")
def trends(village_id: str, limit: int = 180, user=Depends(staff)):
    need_village(user, village_id)
    with P.lock:
        T, sim = P.telemetry, P.sims[village_id]
        c = sim.code
        return _plain({
            "tank": T.history(f"{c}-TANK", "level_pct", limit), "main_flow": T.history(f"{c}-MAIN", "flow_lpm", limit),
            "gw": T.history(f"{c}-SRC", "depth_m", limit),
            "pump_current": T.history(f"{c}-PUMP", "current_a", limit), "pump_vibration": T.history(f"{c}-PUMP", "vibration_mms", limit),
            "turbidity": T.history(f"{c}-WQ1", "turbidity_ntu", limit), "chlorine": T.history(f"{c}-WQ1", "chlorine_mgl", limit),
            "chlorine_tail": T.history(f"{c}-WQ2", "chlorine_mgl", limit), "turbidity_tail": T.history(f"{c}-WQ2", "turbidity_ntu", limit),
            "branches": [{"id": bid, "name": sim.branch_names[b], "p_in": T.history(f"{bid}-IN", "pressure_bar", limit),
                          "p_end": T.history(f"{bid}-END", "pressure_bar", limit), "flow": T.history(f"{bid}-IN", "flow_lpm", limit)}
                         for b, bid in enumerate(sim.branch_ids)]})


@app.get("/api/households")
def households(village: str, q: str = "", status: str = "", branch: str = "", user=Depends(staff)):
    need_village(user, village)
    with P.lock:
        mon = P.monitors[village]
        flags = mon.day_flags()
        reported = {r["household_id"]: r["n"] for r in P.db.query(
            "SELECT household_id, COUNT(*) n FROM complaints WHERE village_id=? AND status!='closed' GROUP BY household_id", (village,))}
        out = []
        for i, hid in enumerate(mon.hh_ids):
            hh = P.households[hid]
            st = STATUS_NAME[int(mon.status[i])]
            if q and q.lower() not in f"{hid} {hh['label']} {hh['lane']}".lower():
                continue
            if status and st != status:
                continue
            if branch and hh["branch_id"] != branch:
                continue
            out.append({"id": hid, "label": hh["label"], "lane": hh["lane"], "branch_id": hh["branch_id"], "position": hh["position"],
                        "members": hh["members"], "instrumented": hh["instrumented"], "status": st,
                        "pressure_bar": round(float(mon.p_est[i]), 2), "confidence": round(float(mon.conf[i]), 2),
                        "lpcd_today": round(float(mon.vol[i] / mon.members[i]), 1), "open_reports": reported.get(hid, 0),
                        "functional": None if flags is None else bool(flags["functional"][i])})
        return _plain(out)


@app.get("/api/households/{household_id}")
def household(household_id: str, user=Depends(staff)):
    hh = P.households.get(household_id.upper())
    if hh is None:
        raise HTTPException(404, "household not found")
    need_village(user, hh["village_id"])
    with P.lock:
        mon, T = P.monitors[hh["village_id"]], P.telemetry
        b = hh["branch_idx"]
        dev = f"{hh['id']}-TAP"
        sources = [{"device": f"{hh['branch_id']}-IN", "x": 0.0, "status": T.status(f"{hh['branch_id']}-IN")}]
        sources += [{"device": f"{mon.hh_ids[i]}-TAP", "x": round(float(mon.x[i]), 2), "status": T.status(f"{mon.hh_ids[i]}-TAP")} for i in mon.inst_idx[b]]
        sources += [{"device": f"{hh['branch_id']}-END", "x": 1.0, "status": T.status(f"{hh['branch_id']}-END")}]
        incidents = [P.incidents.public(i) for i in P.incidents.items.values()
                     if i["village_id"] == hh["village_id"] and (i["scope_type"] == "scheme" or i["branch_id"] == hh["branch_id"])]
        events = P.db.query("SELECT ts, metrics, source FROM telemetry WHERE device_id=? ORDER BY id DESC LIMIT 12", (dev,)) if hh["instrumented"] else []
        return _plain({"household": {**_hh_public(hh), "position": hh["position"], "x": hh["x"], "lat": hh["lat"], "lon": hh["lon"],
                                     "branch_id": hh["branch_id"], "demo": True},
                       "live": _hh_live(hh), "evidence_sources": sources,
                       "note": None if hh["instrumented"] else "This home has no meter. Its status is estimated from the nearest pressure points on the lane and is labelled as an estimate.",
                       "pressure_series": T.history(dev, "pressure_bar", 120) if hh["instrumented"] else [],
                       "flow_series": T.history(dev, "flow_lpm", 120) if hh["instrumented"] else [],
                       "recent_events": events, "complaints": P.complaints.for_household(hh["id"]), "incidents": incidents})


@app.get("/api/telemetry/latest")
def telemetry_latest(village: str, user=Depends(staff)):
    need_village(user, village)
    with P.lock:
        T = P.telemetry
        return _plain([{"device_id": d, "name": T.devices[d]["name"], "kind": T.devices[d]["kind"], "status": T.status(d),
                        **(T.latest.get(d) or {"ts": None, "m": {}, "source": None})} for d in P.monitors[village].device_ids])


@app.get("/api/telemetry/events")
def telemetry_events(device: str, limit: int = Query(20, le=200), user=Depends(staff)):
    return P.db.query("SELECT event_id, device_id, ts, metrics, source, quality, received_at FROM telemetry WHERE device_id=?"
                      " ORDER BY id DESC LIMIT ?", (device, limit))


@app.get("/api/telemetry/history")
def telemetry_history(device: str, metric: str, limit: int = Query(180, le=420), user=Depends(staff)):
    return _plain({"device": device, "metric": metric, "unit": UNITS.get(metric, ""), "points": P.telemetry.history(device, metric, limit)})


@app.get("/api/alerts")
def alerts(user=Depends(staff)):
    with P.lock:
        return _plain(P.incidents.open_list(scope_of(user)))


@app.get("/api/incidents")
def incidents(status: str | None = None, village: str | None = None, user=Depends(staff)):
    scope = scope_of(user)
    if village:
        need_village(user, village)
        scope = {village}
    with P.lock:
        return _plain(P.incidents.list(village_ids=scope, status=status))


@app.get("/api/incidents/{incident_id}")
def incident(incident_id: str, user=Depends(staff)):
    with P.lock:
        d = P.incidents.detail(incident_id.upper())
    need_village(user, d["village_id"])
    d["deliveries"] = P.alerts.for_incident(d["id"])
    return _plain(d)


class IncidentAction(BaseModel):
    action: str
    note: str | None = None
    assignee: str | None = None
    override: bool = False


@app.patch("/api/incidents/{incident_id}")
def incident_act(incident_id: str, body: IncidentAction, user=Depends(staff)):
    with P.lock:
        d = P.incidents.detail(incident_id.upper())
        need_village(user, d["village_id"])
        out = P.incidents.act(incident_id.upper(), body.action, user, body.model_dump())
        P.version += 1
        return _plain(out)


@app.get("/api/complaints")
def complaints(status: str | None = None, village: str | None = None, user=Depends(staff)):
    scope = scope_of(user)
    if village:
        need_village(user, village)
        scope = {village}
    rows = P.complaints.list(scope, status)
    for r in rows:
        r["household"] = P.households[r["household_id"]]["label"]
        r["lane"] = P.households[r["household_id"]]["lane"]
    return rows


@app.get("/api/analytics")
def analytics_api(level: str = "state", id: str = "ST-MH", user=Depends(staff)):
    vids = [v["id"] for v in analytics.villages_under(level, id)]
    if not vids or not set(vids) <= scope_of(user):
        raise HTTPException(403, "this unit is outside your jurisdiction")
    return _plain(analytics.analytics(P, vids))


@app.get("/api/invest")
def invest_plan(level: str = "state", id: str = "ST-MH", budget: float = Query(10_00_000, ge=10_000, le=10_00_00_000), user=Depends(staff)):
    """Where a budget buys the most functional household taps across a jurisdiction (indicative unit costs)."""
    vids = [v["id"] for v in analytics.villages_under(level, id)]
    if not vids or not set(vids) <= scope_of(user):
        raise HTTPException(403, "this unit is outside your jurisdiction")
    with P.lock:
        return _plain(invest.plan(P, vids, budget))


@app.get("/api/ai/insights")
def ai_insights(village: str, user=Depends(staff)):
    need_village(user, village)
    return _plain(analytics.insights(P, village))


@app.get("/api/ai/models")
def ai_models(user=Depends(staff)):
    return P.models.card


# --------------------------------------------------------------- phone alerts
def _alert_options(user: dict) -> list[dict]:
    """Which alert streams this user may put on a phone: every village, block and district in their jurisdiction."""
    vids = scope_of(user)
    out = []
    for v in S.VILLAGES:
        if v["id"] in vids:
            out += [{"role": r, "scope_id": v["id"], "label": f"{ALERT_ROLE_TITLE[r]} · {v['name']}", "level": 1}
                    for r in ("operator", "vwsc")]
    paths = [S.admin_path(v) for v in S.VILLAGES]
    for key, level in (("block", 2), ("district", 3)):
        for uid, name in sorted({(p[f"{key}_id"], p[key]) for p in paths}):
            if set(P.alerts.villages_of(uid)) <= vids:
                out.append({"role": key, "scope_id": uid, "label": f"{ALERT_ROLE_TITLE[key]} · {name}", "level": level})
    return out


def _need_alert_option(user: dict, role: str, scope_id: str) -> dict:
    opt = next((o for o in _alert_options(user) if o["role"] == role and o["scope_id"] == scope_id), None)
    if opt is None:
        raise HTTPException(403, "that alert stream is outside your jurisdiction")
    return opt


@app.get("/api/alerts/delivery")
def alert_delivery(user=Depends(staff)):
    return _plain({**P.alerts.state(scope_of(user)), "options": _alert_options(user), "languages": C.LANGUAGES})


class StaffLinkBody(BaseModel):
    role: str
    scope_id: str


@app.post("/api/alerts/link")
def alert_link(body: StaffLinkBody, user=Depends(staff)):
    """A one-time code that links a phone to an alert stream. Replies from that phone act as this user."""
    opt = _need_alert_option(user, body.role, body.scope_id)
    acting = {k: user[k] for k in ("username", "name", "role", "scope_level", "scope_id")}
    P.audit.log(P.now, user["name"], user["role"], "alerts.link_code", "alert_stream", f"{body.role}:{body.scope_id}")
    return P.alerts.issue_link(role=body.role, scope_id=body.scope_id, name=f"{user['name']} ({opt['label']})",
                               lang="en", acting=acting)


class RecipientBody(BaseModel):
    name: str = Field(default="", max_length=80)
    role: str
    scope_id: str
    channel: str
    address: str = Field(max_length=40)
    lang: str = "en"


@app.post("/api/alerts/recipients", status_code=201)
def alert_recipient_add(body: RecipientBody, user=Depends(staff)):
    scope_id = body.scope_id
    if body.role == "household":
        hh = P.households.get(scope_id.strip().upper())
        if hh is None:
            raise HTTPException(404, "household not found")
        need_village(user, hh["village_id"])
        scope_id = hh["id"]
    else:
        _need_alert_option(user, body.role, scope_id)
    try:
        r = P.alerts.add_recipient(name=body.name, role=body.role, scope_id=scope_id, channel=body.channel,
                                   address=body.address, lang=body.lang if body.lang in C.LANGUAGES else "en")
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    P.audit.log(P.now, user["name"], user["role"], "alerts.recipient_add", "recipient", str(r["id"]), None, body.channel, r["name"])
    return r


def _own_recipient(user: dict, rid: int) -> dict:
    r = P.alerts.recipient(rid)
    if r is None or not r["active"]:
        raise HTTPException(404, "recipient not found")
    villages = P.alerts.villages_for(r)
    if not villages or not set(villages) <= scope_of(user):
        raise HTTPException(403, "that recipient is outside your jurisdiction")
    return r


@app.delete("/api/alerts/recipients/{rid}")
def alert_recipient_remove(rid: int, user=Depends(staff)):
    r = _own_recipient(user, rid)
    P.alerts.remove_recipient(rid)
    P.audit.log(P.now, user["name"], user["role"], "alerts.recipient_remove", "recipient", str(rid), None, None, r["name"])
    return {"removed": rid}


@app.post("/api/alerts/recipients/{rid}/test")
def alert_recipient_test(rid: int, user=Depends(staff)):
    r = _own_recipient(user, rid)
    did = P.alerts.test(r)
    return {"queued": did, "status": P.alerts.db.scalar("SELECT status FROM deliveries WHERE id=?", (did,))}


# ------------------------------------------------------------- water quality
def _judge_test(params: dict) -> tuple[str, list[str]]:
    result, fails, _rows = sampling.judge(params)
    return result, fails


class WqTest(BaseModel):
    village_id: str
    sample_point: str
    kind: str = "FTK"
    params: dict
    incident_id: str | None = None
    note: str | None = None


def _test_outcome(row: dict, fails: list[str], user: dict, kind: str, checks: list[dict]) -> dict:
    """What a result sets in motion: evidence on its incident, and for a failed field test a laboratory referral,
    an incident for that lane if none is open, and a boil-water advisory to the households it serves.
    Returns what was done, so the person who entered the result can be told."""
    vid, result = row["village_id"], row["result"]
    advisory = sampling.advisory_for(checks) if result == "fail" else None
    did = {"lab_referral": row.get("lab_status") == "requested", "incident": row["incident_id"], "incident_opened": False,
           "advisory": advisory, "advised": None, "advised_households": 0, "wqmis": "queued",
           "failed": [c["label"] for c in checks if c["status"] == "fail"]}
    inc = P.incidents.items.get(row["incident_id"] or "")
    if result == "fail" and kind == "FTK" and inc is None:
        sim = P.sims[vid]
        bid = sampling.point_branch(sim, row["sample_point"])
        b = sim.branch_ids.index(bid) if bid else None
        affected = [h for h, m in P.households.items() if m["village_id"] == vid and (b is None or m["branch_idx"] == b)]
        where = sim.branch_names[b] if b is not None else f"the {sim.name} scheme"
        severity = "high" if advisory else "low"  # iron, hardness, pH: maintenance for the operator, not a health alert
        meanwhile = {"boil": "Households on the affected supply are advised to boil drinking water meanwhile.",
                     "alternate_source": "Households on the affected supply are advised to drink from another safe source "
                                         "meanwhile: boiling does not remove this."}.get(advisory, "Not an immediate health risk: no household advisory.")
        inc, _new = P.incidents.raise_(
            f"{vid}:ftk:{bid or 'scheme'}", vid, "QUALITY_VERIFY", severity, scope_type="branch" if bid else "scheme",
            scope_id=bid or vid, branch_id=bid, affected_ids=affected, confidence=0.9, origin="ftk",
            title=f"Field test failed at {row['sample_point']}",
            summary=f"The Jal Sakhi field test at {row['sample_point']} failed: {'; '.join(fails)}. A field kit screens; "
                    f"the laboratory confirms. {meanwhile}",
            cause="Not yet known: contamination at the source, in the tank, or ingress through the pipes serving " + where + ".",
            action="Laboratory confirmation of the sample; check chlorination; flush the line; re-test after the fix.",
            evidence={"tests": [], "ftk_pass": False, "reference": "IS 10500:2012", "failed_checks": fails})
        if inc is not None:
            row["incident_id"] = inc["id"]
            P.db.update("wq_tests", "id", row["id"], {"incident_id": inc["id"]})
            did.update(incident=inc["id"], incident_opened=True, scope=where)
    if inc is None:
        return did
    if result != "pending":
        if kind == "LAB":
            inc["evidence"]["lab_pass"] = result == "pass"
        else:
            inc["evidence"]["ftk_pass"] = result == "pass"
            inc["evidence"]["ftk_at"] = row["ts"]
    if row["id"] not in inc["evidence"].setdefault("tests", []):
        inc["evidence"]["tests"].append(row["id"])
    msg = (f"{kind} test {row['id']} at {row['sample_point']}: PASS" if result == "pass"
           else f"{kind} test {row['id']} at {row['sample_point']}: H2S vial set, other parameters recorded" if result == "pending"
           else f"{kind} test {row['id']} at {row['sample_point']}: FAIL ({'; '.join(fails)}). Laboratory confirmation requested.")
    P.incidents.add_event(inc, "wq_test", msg, actor=user["name"], role=user["role"], data={"test_id": row["id"], "result": result})
    P.incidents._persist(inc)
    if advisory:
        lane = inc["branch_id"] if inc["scope_type"] == "branch" else None
        P.notify(row["village_id"], "advisory_quality" if advisory == "boil" else "advisory_chemical", {"incident": inc["id"]},
                 incident_id=inc["id"], channel="app+sms", branch_id=lane)
        sim = P.sims[vid]
        did.update(advised=sim.branch_names[sim.branch_ids.index(lane)] if lane in sim.branch_ids else f"all of {sim.name}",
                   advised_households=sum(1 for h in P.households.values() if h["village_id"] == vid and (lane is None or h["branch_id"] == lane)))
    return did


def _sync_test(row: dict, op: str):
    P.sync.enqueue("water_quality_test", row["id"], row["village_id"], op,
                   {**{k: row[k] for k in ("id", "sample_point", "kind", "params", "result", "ts", "lab_status")}, "target": "WQMIS (sandbox)"})


@app.post("/api/quality/tests", status_code=201)
def add_wq_test(body: WqTest, user=Depends(staff)):
    need_village(user, body.village_id)
    if body.kind not in ("FTK", "LAB"):
        raise HTTPException(422, "kind must be FTK or LAB")
    result, fails, checks = sampling.judge(body.params)
    with P.lock:
        n = (P.db.scalar("SELECT COUNT(*) FROM wq_tests") or 0) + 1
        row = {"id": f"WQ-{n:04d}", "village_id": body.village_id, "sample_point": body.sample_point, "kind": body.kind,
               "params": body.params, "result": result, "tested_by": user["name"], "ts": P.now.isoformat(timespec="seconds"),
               "incident_id": body.incident_id, "lab_status": "requested" if (result == "fail" and body.kind == "FTK") else None,
               "note": body.note}
        P.db.insert("wq_tests", row)
        did = _test_outcome(row, fails, user, body.kind, checks)
        P.audit.log(P.now, user["name"], user["role"], "quality.test", "wq_test", row["id"], None, result, body.sample_point)
        _sync_test(row, "create")
        P.version += 1
        return {**row, "failed_checks": fails, "checks": checks, "follow_up": did, "advice": sampling.advice(checks)}


class H2sBody(BaseModel):
    positive: bool


@app.patch("/api/quality/tests/{test_id}/h2s")
def wq_test_h2s(test_id: str, body: H2sBody, user=Depends(staff)):
    """The H2S vial a tester set up a day or two ago has been read: complete the test with it."""
    with P.lock:
        row = P.db.one("SELECT * FROM wq_tests WHERE id=?", (test_id.upper(),))
        if row is None:
            raise HTTPException(404, "test not found")
        need_village(user, row["village_id"])
        if row["result"] != "pending":
            raise HTTPException(409, "this test is not waiting for an H2S result")
        params = {**row["params"], "h2s_positive": body.positive}
        result, fails, checks = sampling.judge(params)
        row.update(params=params, result=result, lab_status="requested" if result == "fail" and row["kind"] == "FTK" else row["lab_status"])
        P.db.update("wq_tests", "id", row["id"], {"params": params, "result": result, "lab_status": row["lab_status"]})
        did = _test_outcome(row, fails, user, row["kind"], checks)
        P.audit.log(P.now, user["name"], user["role"], "quality.h2s", "wq_test", row["id"], "pending", result, "positive" if body.positive else "negative")
        _sync_test(row, "update")
        P.version += 1
        return {**row, "failed_checks": fails, "checks": checks, "follow_up": did, "advice": sampling.advice(checks)}


@app.post("/api/quality/tests/{test_id}/photo", status_code=201)
async def wq_test_photo(test_id: str, photo: UploadFile = File(...), user=Depends(staff)):
    """A photo of the kit beside the colour chart, kept with the result as evidence."""
    if not (photo.content_type or "").startswith("image/"):
        raise HTTPException(415, "photo must be an image")
    data = await photo.read()
    if len(data) > C.MAX_UPLOAD_BYTES:
        raise HTTPException(413, "photo is larger than 5 MB")
    with P.lock:
        row = P.db.one("SELECT village_id FROM wq_tests WHERE id=?", (test_id.upper(),))
        if row is None:
            raise HTTPException(404, "test not found")
        need_village(user, row["village_id"])
        name = f"{uuid.uuid4().hex}{ {'image/png': '.png', 'image/webp': '.webp'}.get(photo.content_type, '.jpg') }"
        C.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        (C.UPLOAD_DIR / name).write_bytes(data)
        P.db.update("wq_tests", "id", test_id.upper(), {"photo": f"/uploads/{name}"})
        P.version += 1
    return {"photo": f"/uploads/{name}"}


@app.get("/api/quality/plan")
def quality_plan(village: str, user=Depends(staff)):
    """Where the village's testers should draw water first today, and why (contamination risk)."""
    need_village(user, village)
    with P.lock:
        return _plain(sampling.plan(P, village))


class LabResult(BaseModel):
    sample_id: str  # the JalSakhi test whose failure sent the sample to the laboratory
    lab: str = Field(default="District water testing laboratory", max_length=120)
    tested_on: str | None = None
    params: dict
    remarks: str = Field(default="", max_length=300)


class LabResults(BaseModel):
    results: list[LabResult] = Field(min_length=1, max_length=100)


def _lab_import(results: list[LabResult], user: dict, source: str) -> list[dict]:
    """Laboratory results arriving from WQMIS: each closes the referral its FTK test opened."""
    out = []
    for res in results:
        ref = P.db.one("SELECT * FROM wq_tests WHERE id=?", (res.sample_id.strip().upper(),))
        if ref is None:
            out.append({"sample_id": res.sample_id, "error": "no JalSakhi test with this sample_id"})
            continue
        need_village(user, ref["village_id"])
        verdict, fails = interop.lab_verdict(res.params)
        n = (P.db.scalar("SELECT COUNT(*) FROM wq_tests") or 0) + 1
        row = {"id": f"WQ-{n:04d}", "village_id": ref["village_id"], "sample_point": ref["sample_point"], "kind": "LAB",
               "params": res.params, "result": verdict, "tested_by": f"{res.lab} (via WQMIS)", "ts": res.tested_on or P.now.isoformat(timespec="seconds"),
               "incident_id": ref["incident_id"], "lab_status": f"result for {ref['id']}", "note": res.remarks or None}
        P.db.insert("wq_tests", row)
        P.db.update("wq_tests", "id", ref["id"], {"lab_status": f"lab {verdict}: {row['id']}"})
        inc = P.incidents.items.get(ref["incident_id"] or "")
        if inc is not None:
            inc["evidence"]["lab_pass"] = verdict == "pass"
            inc["evidence"].setdefault("tests", []).append(row["id"])
            P.incidents.add_event(inc, "wq_test", f"Laboratory result {row['id']} for sample {ref['id']} ({res.lab}): "
                                  + ("within limits" if verdict == "pass" else "FAIL: " + "; ".join(fails)),
                                  actor=f"{res.lab} via WQMIS", role="lab", data={"test_id": row["id"], "result": verdict})
            P.incidents._persist(inc)
        P.notify(ref["village_id"], "advisory_cleared" if verdict == "pass" else "advisory_quality",
                 {"incident": ref["incident_id"]}, incident_id=ref["incident_id"], channel="app+sms")
        P.audit.log(P.now, user["name"], user["role"], f"quality.lab_result.{source}", "wq_test", row["id"], ref["id"], verdict, res.lab)
        P.feed("quality", "ok" if verdict == "pass" else "warn",
               f"Lab result for {ref['id']} at {ref['sample_point']}: {'within limits' if verdict == 'pass' else 'FAIL'} ({source})",
               ref["village_id"], ref["incident_id"])
        out.append({**row, "failed_checks": fails, "referral": ref["id"]})
    P.version += 1
    return out


@app.post("/api/quality/lab-results", status_code=201)
def quality_lab_results(body: LabResults, user=Depends(staff)):
    """WQMIS inbound: laboratory results for samples JalSakhi referred. Field names follow the draft WQMIS mapping."""
    with P.lock:
        return {"imported": _lab_import(body.results, user, "WQMIS import")}


@app.post("/api/quality/wqmis/pull")
def quality_wqmis_pull(village: str, user=Depends(staff)):
    """DEMO: the sandbox laboratory answers every open referral in a village from the simulated water."""
    need_village(user, village)
    with P.lock:
        pending = P.db.query("SELECT id FROM wq_tests WHERE village_id=? AND lab_status='requested' ORDER BY id", (village,))
        if not pending:
            return {"imported": [], "note": "no laboratory referrals are waiting in this village"}
        sim, rnd = P.sims[village], P.cit_rng
        dirty = sim.turb > 4 or sim.cl < 0.1 or not P._cit[village].get("cluster_fixed", True)
        results = [LabResult(sample_id=r["id"], lab="District water testing laboratory (sandbox)", params={
            "turbidity_ntu": round(max(0.1, sim.turb + rnd.uniform(-0.2, 0.2)), 1), "ph": round(7.2 + rnd.uniform(-0.2, 0.2), 1),
            "tds_mgl": round(340 + rnd.uniform(-20, 20)), "chlorine_mgl": round(max(0.0, sim.cl), 2),
            "e_coli_present": bool(dirty), "total_coliform_present": bool(dirty)},
            remarks="DEMO: generated from the simulated water") for r in pending]
        return {"imported": _lab_import(results, user, "WQMIS sandbox"), "demo": True}


@app.get("/api/quality")
def quality(village: str, user=Depends(staff)):
    need_village(user, village)
    with P.lock:
        mon = P.monitors[village]
        return _plain({"sensors": mon.quality, "limits": C.QUALITY_LIMITS, "reference": "IS 10500:2012",
                       "tests": P.db.query("SELECT * FROM wq_tests WHERE village_id=? ORDER BY ts DESC LIMIT 30", (village,)),
                       "open": [P.incidents.public(i) for i in P.incidents.items.values()
                                if i["village_id"] == village and (i["category"] == "quality" or "quality" in (i["cond_key"] or ""))],
                       "sample_points": [sp["name"] for sp in sampling.sample_points(P.sims[village])], "ftk_params": sampling.FTK_PARAMS,
                       "caveat": "Online sensors measure turbidity, residual chlorine, pH and TDS only. They cannot detect bacteria, "
                                 "arsenic, fluoride, nitrate or iron. A sensor alert means 'test now', never 'water is unsafe' or 'water is safe'."})


@app.get("/api/quality/ftk-sample")
def ftk_sample(village: str, point: str = "Tank outlet", user=Depends(staff)):
    """DEMO only: what the field test kit would show for water drawn at `point` now, read off the simulated scheme."""
    need_village(user, village)
    return {"demo": True, "point": point, "params": sampling.demo_reading(P, village, point, P.cit_rng)}


# ------------------------------------------------------- integration / sync
@app.get("/api/sync")
def sync_state(user=Depends(staff)):
    with P.lock:
        return _plain({"summary": P.sync.summary(), "outbox": P.sync.outbox(), "received": P.sync.received(),
                       "by_type": P.sync.by_type(),
                       "mappings": P.db.query("SELECT internal_type, internal_id, system, field, external_id, status FROM id_mappings"),
                       "targets": [
                           {"system": "JJM IMIS", "what": "scheme, habitation and FHTC records; service delivery status", "state": "sandbox"},
                           {"system": "Sujal Gaon ID / Sujalam Bharat", "what": "every record is keyed by the scheme's Sujal Gaon ID (infrastructure ID + service-area ID)", "state": "sandbox"},
                           {"system": "WQMIS", "what": "FTK and laboratory test results", "state": "sandbox"},
                           {"system": "Jal Seva Aankalan (JJM Panchayat Dashboard)", "what": "evidence-backed draft of the GP self-assessment", "state": "sandbox"},
                           {"system": "eGramSwaraj / Meri Panchayat", "what": "the endorsed assessment, published for 30 days of citizen feedback", "state": "planned"},
                           {"system": "PM Gati Shakti GIS", "what": "scheme geometry: lanes, tap connections and assets as GeoJSON", "state": "export"},
                           {"system": "Grievance channels (CPGRAMS / state helpline / Meri Panchayat)", "what": "citizen reports and closure status", "state": "planned"}],
                       "notice": "SANDBOX: records go to an in-process mock gateway. Nothing is sent to any government system. "
                                 "Identifiers shown are DEMO placeholders. A live adapter needs official API specifications, credentials and approval."})


class OutageBody(BaseModel):
    on: bool


@app.get("/api/sync/mapping")
def sync_mapping(user=Depends(staff)):
    """Field-by-field mapping to each JJM platform, and the ministry's device message format."""
    return {"platforms": interop.mapping_table(), "draft_note": interop.DRAFT,
            "ddws": {"source": interop.DDWS_SOURCE, "types": [{"dty": k, "what": w, "basis": b} for k, (w, b) in interop.TYPE_DOC.items()],
                     "keys": [{"key": k, "what": w, "unit": u, "basis": b} for k, (w, u, b) in interop.KEY_DOC.items()]}}


@app.get("/api/interop/ddws/{village_id}")
def interop_ddws(village_id: str, user=Depends(staff)):
    """The village's latest readings as its gateway would forward them, in the ministry's reference format."""
    need_village(user, village_id)
    with P.lock:
        T = P.telemetry
        ids = P.monitors[village_id].device_ids + ([HW_DEVICE] if village_id == S.FOCUS_VILLAGE else [])
        return _plain(interop.ddws_out(village_id, ids, T.devices, T.latest))


@app.post("/api/sync/outage")
def sync_outage(body: OutageBody, user=Depends(staff)):
    with P.lock:
        P.sync.set_outage(body.on)
        P.audit.log(P.now, user["name"], user["role"], "demo.sync_outage", "sync", "gateway", None, "on" if body.on else "off")
        P.feed("demo", "demo", f"DEMO: sandbox gateway {'taken offline' if body.on else 'restored'}; "
                               f"{'records will queue and retry' if body.on else 'queued records are being delivered'}")
        P.version += 1
    return P.sync.summary()


@app.post("/api/sync/flush")
def sync_flush(user=Depends(staff)):
    with P.lock:
        sent = P.sync.process(force=True)
        P.version += 1
    return {"sent": sent, **P.sync.summary()}


@app.get("/api/devices")
def devices(village: str, user=Depends(staff)):
    need_village(user, village)
    with P.lock:
        T = P.telemetry
        ids = P.monitors[village].device_ids + ([HW_DEVICE] if village == S.FOCUS_VILLAGE else [])
        out = []
        for d in ids:
            meta_, rec = T.devices[d], T.latest.get(d)
            status = T.status(d)
            if d == HW_DEVICE:  # a real board reports on wall-clock time, not sim ticks
                status = "never" if rec is None else "online" if P.hw_live else "stale"
            out.append({"id": d, "name": meta_["name"], "kind": meta_["kind"], "entity_type": meta_["entity_type"],
                        "entity_id": meta_["entity_id"], "status": status, "last_seen": rec["ts"] if rec else None,
                        "source": rec["source"] if rec else ("hardware" if d == HW_DEVICE else "simulation"),
                        "metrics": rec["m"] if rec else {}, "battery_pct": round(meta_["battery"], 1), "rssi_dbm": round(meta_["rssi"]),
                        "fw": meta_["fw"], "power": meta_["power"], "missed": T.missed[d]})
        return _plain({"devices": out, "device_key_hint": "X-Device-Key header (demo key in README)",
                       "ingest": {"ingested": T.total, "rejected": T.rejected, "duplicates": T.duplicates}})


class HwBind(BaseModel):
    household_id: str | None = None


@app.get("/api/hardware")
def hardware(user=Depends(staff)):
    """The bench node: whether it is live, what it last said, and which home it stands in for."""
    need_village(user, S.FOCUS_VILLAGE)
    return P.hw_status()


@app.post("/api/hardware/bind")
def hardware_bind(body: HwBind, user=Depends(staff)):
    need_village(user, S.FOCUS_VILLAGE)
    try:
        return P.hw_bind(body.household_id.upper() if body.household_id else None, user["name"], user["role"])
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@app.get("/api/scale")
def scale(user=Depends(staff)):
    """Result of the last load test (python run.py --bench), measured on whichever machine ran it."""
    path = C.MODEL_DIR / "scale_bench.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"measured": False}


@app.get("/api/audit")
def audit(limit: int = Query(80, le=500), user=Depends(staff)):
    return {"rows": P.db.query("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)), "integrity": P.audit.verify()}


@app.get("/api/aankalan/{village_id}")
def aankalan(village_id: str, user=Depends(staff)):
    need_village(user, village_id)
    return _plain(analytics.aankalan(P, village_id))


@app.post("/api/aankalan/{village_id}/submit")
def aankalan_submit(village_id: str, user=Depends(staff)):
    need_village(user, village_id)
    with P.lock:
        draft = analytics.aankalan(P, village_id)
        P.sync.enqueue("jal_seva_aankalan_draft", f"{village_id}:{P.now.date().isoformat()}", village_id, "upsert",
                       {"day": P.now.date().isoformat(), "overall": draft["overall"], "status": "draft-for-gram-sabha",
                        "sections": [{"key": s["key"], "score": s["score"], "indicators": s["indicators"]} for s in draft["sections"]]})
        P.audit.log(P.now, user["name"], user["role"], "aankalan.queue", "village", village_id, None, "queued")
        P.version += 1
    return {"queued": True, "target": "Jal Seva Aankalan (sandbox)"}


class EndorseBody(BaseModel):
    note: str = ""


@app.post("/api/aankalan/{village_id}/endorse")
def aankalan_endorse(village_id: str, body: EndorseBody, user=Depends(staff)):
    """Record that the Gram Sabha has endorsed the assessment; this opens the 30-day citizen feedback window."""
    need_village(user, village_id)
    if user["role"] == "operator":
        raise HTTPException(403, "the Pani Samiti records the Gram Sabha's endorsement, not the operator")
    with P.lock:
        stage = P.om.endorse(village_id, user["name"], user["role"], body.note)
        draft = analytics.aankalan(P, village_id)
        P.sync.enqueue("jal_seva_aankalan", f"{village_id}:endorsed:{stage['endorsed_on']}", village_id, "upsert",
                       {"overall": draft["overall"], "status": "endorsed-by-gram-sabha", "endorsed_on": stage["endorsed_on"],
                        "feedback_open_until": stage["open_until"],
                        "sections": [{"key": x["key"], "score": x["score"], "indicators": x["indicators"]} for x in draft["sections"]]})
        P.version += 1
        return stage


class FeedbackBody(BaseModel):
    household_id: str
    agree: bool
    comment: str = ""


@app.get("/api/citizen/aankalan")
def citizen_aankalan(household_id: str):
    """The Gram Panchayat's published self-assessment, as a household sees it, with its own answer if it gave one."""
    hh = P.households.get(household_id.upper())
    if hh is None:
        raise HTTPException(404, "household not found")
    with P.lock:
        d = analytics.aankalan(P, hh["village_id"])
        mine = P.db.one("SELECT agree FROM aankalan_feedback WHERE village_id=? AND household_id=?", (hh["village_id"], hh["id"]))
        st = d["stage"]
        return _plain({"village": d["village"], "stage": st["stage"], "days_left": st["days_left"], "open_until": st["open_until"],
                       "overall": d["overall"], "sections": [{"key": x["key"], "score": x["score"]} for x in d["sections"]],
                       "responses": st["responses"], "agree": st["agree"], "mine": None if mine is None else bool(mine["agree"])})


@app.post("/api/citizen/aankalan", status_code=201)
def citizen_aankalan_feedback(body: FeedbackBody):
    hh = P.households.get(body.household_id.upper())
    if hh is None:
        raise HTTPException(404, "household not found")
    with P.lock:
        try:
            P.om.feedback(hh["village_id"], hh["id"], body.agree, body.comment)
        except ValueError as exc:
            raise HTTPException(409, str(exc))
        P.version += 1
    return {"recorded": True}


# ------------------------------------------------------ operations and upkeep
class TaskDone(BaseModel):
    note: str | None = None


class LogBody(BaseModel):
    village_id: str
    meter_kl: float = Field(ge=0, le=1e7)
    pump_hours: float | None = Field(default=None, ge=0, le=24)
    chlorine_g: float | None = Field(default=None, ge=0, le=100000)
    remarks: str = ""


class PayBody(BaseModel):
    household_id: str


class ExpenseBody(BaseModel):
    village_id: str
    head: str
    amount: float = Field(gt=0, le=1e7)
    note: str = ""


def _log_window() -> int:
    """The supply window an entry made now belongs to: the one running, or the last one that closed."""
    if P.clock.in_window:
        return P.clock.win_idx
    minute = P.now.hour * 60 + P.now.minute
    done = [i for i, (_start, end, _label) in enumerate(C.SUPPLY_WINDOWS) if minute >= end]
    return done[-1] if done else len(C.SUPPLY_WINDOWS) - 1


@app.get("/api/om")
def om(village: str, user=Depends(staff)):
    """Upkeep plan, operator log and accounts of one scheme, with its profile."""
    need_village(user, village)
    with P.lock:
        return _plain({"profile": P.om.profile(village, analytics.village_kpis(P, village)), "upkeep": P.om.tasks(village),
                       "log": P.om.logs(village), "accounts": P.om.finance(village)})


@app.post("/api/om/tasks/{task_id}/done")
def om_task_done(task_id: str, body: TaskDone, user=Depends(staff)):
    need_village(user, task_id.split(":")[0])
    with P.lock:
        try:
            out = P.om.task_done(task_id, user["name"], user["role"], body.note)
        except KeyError:
            raise HTTPException(404, "unknown task")
        P.version += 1
        return out


@app.get("/api/om/meter")
def om_meter(village: str, user=Depends(staff)):
    """DEMO helper: what the bulk meter and the pump's hour counter show right now (from the simulator)."""
    need_village(user, village)
    with P.lock:
        return P.om.meter_now(village)


@app.post("/api/om/log", status_code=201)
def om_log(body: LogBody, user=Depends(staff)):
    need_village(user, body.village_id)
    with P.lock:
        try:
            row = P.om.log(body.village_id, _log_window(), body.meter_kl, body.pump_hours, body.chlorine_g, body.remarks, user["name"], "entered")
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        P.audit.log(P.now, user["name"], user["role"], "operator.log", "village", body.village_id, None, row["verdict"], f"meter {row['meter_kl']} kL")
        P.version += 1
        return _plain(row)


@app.post("/api/om/payments", status_code=201)
def om_pay(body: PayBody, user=Depends(staff)):
    hh = P.households.get(body.household_id.upper())
    if hh is None:
        raise HTTPException(404, "household not found")
    need_village(user, hh["village_id"])
    with P.lock:
        try:
            out = P.om.pay(hh["id"], user["name"], user["role"])
        except ValueError as exc:
            raise HTTPException(409, str(exc))
        P.version += 1
        return out


@app.post("/api/om/expenses", status_code=201)
def om_expense(body: ExpenseBody, user=Depends(staff)):
    need_village(user, body.village_id)
    with P.lock:
        try:
            out = P.om.spend(body.village_id, body.head, body.amount, body.note, user["name"], user["role"])
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        P.version += 1
        return out


# ------------------------------------------------------------------- exports
@app.get("/api/villages/{village_id}/export.geojson")
def export_geojson(village_id: str, user=Depends(staff)):
    """The scheme as standard GeoJSON (RFC 7946), for a GIS such as QGIS or the PM Gati Shakti layers.

    Lanes, tap connections and the main assets, each carrying the scheme's Sujal Gaon ID. Demo geometry."""
    need_village(user, village_id)
    with P.lock:
        g, v, sim = P.sims[village_id].geo(), S.village_by_id(village_id), P.sims[village_id]
        ids = S.external_ids(v)
        common = {"village": sim.name, "sujal_gaon_id": ids["sujal_gaon_id"], "demo": True}
        feats = [{"type": "Feature", "geometry": {"type": "LineString", "coordinates": ln["path"]},
                  "properties": {**common, "kind": "distribution_lane", "id": ln["id"], "name": ln["name"], "tap_connections": ln["n"]}} for ln in g["lanes"]]
        feats += [{"type": "Feature", "geometry": {"type": "Point", "coordinates": h["c"]},
                   "properties": {**common, "kind": "tap_connection", "id": h["id"], "label": h["label"], "lane": h["lane"], "metered": h["metered"]}} for h in g["homes"]]
        feats += [{"type": "Feature", "geometry": {"type": "Point", "coordinates": at}, "properties": {**common, "kind": kind, "name": name}}
                  for kind, name, at in (("elevated_tank", f"{v['tank_kl']} kL tank", g["tank"]["c"]), ("pump_house", "Pump house", g["pump"]["c"]),
                                         ("borewell", "Borewell", g["pump"]["bore"]))]
        feats += [{"type": "Feature", "geometry": {"type": "Point", "coordinates": x["c"]},
                   "properties": {**common, "kind": "institution", "id": x["id"], "name": x["name"]}} for x in g["sites"]]
        body = json.dumps({"type": "FeatureCollection", "name": f"{sim.name} piped water scheme", "scheme": ids, "features": feats})
    return Response(body, media_type="application/geo+json",
                    headers={"Content-Disposition": f'attachment; filename="{sim.code.lower()}-scheme.geojson"'})


@app.get("/api/villages/{village_id}/service.csv")
def export_service_csv(village_id: str, user=Depends(staff)):
    """Daily service record of the scheme as CSV: one row per day."""
    need_village(user, village_id)
    cols = ["day", "functional_pct", "regularity_pct", "quantity_pct", "quality_pct", "avg_lpcd", "supply_hours", "incidents",
            "complaints", "nrw_pct", "energy_kwh", "gw_depth_m", "source"]
    with P.lock:
        rows = P.history.get(village_id, [])
        lines = [",".join(cols)] + [",".join("" if r.get(c) is None else str(r[c]) for c in cols) for r in rows]
    return Response("\n".join(lines) + "\n", media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{P.sims[village_id].code.lower()}-daily-service.csv"'})


@app.get("/api/brief")
def brief(village: str, lang: str = "en", user=Depends(staff)):
    need_village(user, village)
    return analytics.brief(P, village, lang)


# ----------------------------------------------------------------------- demo
@app.get("/api/demo/scenarios")
def demo_scenarios(user=Depends(staff)):
    return {"scenarios": [{"name": k, **v} for k, v in SCENARIOS.items()], "log": P.scenario_log[-20:],
            "active": {vid: P.active_faults(vid) for vid in P.sims}, "speeds": C.SPEEDS}


class ScenarioBody(BaseModel):
    village_id: str | None = None
    branch: int | None = None


@app.post("/api/demo/scenario/{name}")
async def demo_scenario(name: str, body: ScenarioBody | None = None, user=Depends(staff)):
    if name not in SCENARIOS:
        raise HTTPException(404, f"unknown scenario; choose one of {list(SCENARIOS)}")
    body = body or ScenarioBody()
    if body.village_id:
        need_village(user, body.village_id)
    entry = await asyncio.to_thread(P.scenario, name, body.village_id, body.branch, user["name"])
    hub.broadcast()
    return _plain({"ok": True, "demo": True, **entry, "clock": P.clock_state()})


@app.post("/api/demo/reset")
async def demo_reset(user=Depends(staff)):
    await asyncio.to_thread(P.reset)
    P.audit.log(P.now, user["name"], user["role"], "demo.reset.request", "platform", "jalsakhi")
    hub.broadcast()
    return {"ok": True, "households": len(P.households), "villages": len(P.sims), "clock": P.clock_state()}


class ClockBody(BaseModel):
    action: str
    speed: int | None = None


@app.post("/api/demo/clock")
async def demo_clock(body: ClockBody, user=Depends(staff)):
    if body.action == "pause":
        P.running = False
    elif body.action == "resume":
        P.running = True
    elif body.action == "speed":
        if body.speed not in C.SPEEDS:
            raise HTTPException(422, f"speed must be one of {C.SPEEDS}")
        P.speed = body.speed
    elif body.action == "step":
        await asyncio.to_thread(P.step)
    elif body.action == "skip":
        await asyncio.to_thread(P.skip_to_window, 0)
    else:
        raise HTTPException(422, "action must be pause, resume, speed, step or skip")
    P.version += 1
    hub.broadcast()
    return P.clock_state()


def _plain(obj):
    """Round-trip through json to strip numpy scalars before FastAPI encodes the response."""
    return json.loads(json.dumps(obj, default=_json_default))


# --------------------------------------------------------------------- static
C.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(C.UPLOAD_DIR)), name="uploads")

if C.FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=str(C.FRONTEND_DIST / "assets")), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404, "not found")
        target = (C.FRONTEND_DIST / path).resolve()
        if path and target.is_file() and Path(C.FRONTEND_DIST).resolve() in target.parents:
            if path == "sw.js":  # a stale worker would keep serving an old app: always revalidate it
                return FileResponse(target, media_type="text/javascript", headers={"Cache-Control": "no-cache"})
            if path.endswith(".webmanifest"):
                return FileResponse(target, media_type="application/manifest+json")
            return FileResponse(target)
        return FileResponse(C.FRONTEND_DIST / "index.html")
else:
    @app.get("/", include_in_schema=False)
    def no_frontend():
        return {"app": C.APP_NAME, "note": "Frontend not built. Run `npm install && npm run build` in frontend/, or use `npm run dev`.",
                "api_docs": "/docs"}

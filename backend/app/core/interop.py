"""Interoperability: the formats JalSakhi speaks besides its own.

1. The ministry's device message. The DDWS expert committee report "Roadmap for the measurement & monitoring
   of water service delivery in rural areas" (March 2021, annexure) gives a reference payload from a village
   gateway to the cloud:
       {"gid": "AP_D01_B01_V01", "did": "fm01", "dty": "fm", "dt": "2020-11-03T00:00:00",
        "p": {"t": "100.22", "f": "21.5", "b": "99", "e": "00"}}
   gateway ID, device ID, device type (fm flow meter, gl groundwater level, sl service-reservoir level,
   ca chlorine analyser), parameters, battery 0-100 and error code (00 none, 01 tamper, 02 other).
   ddws_in() turns such a message into JalSakhi telemetry; ddws_out() publishes a village's latest readings in it.
   The report names the four device types and the t / f / b / e keys. Every other type and parameter key below
   is a JalSakhi extension in the same style, marked as such, for the sensors the report lists without a code.

2. Field mappings to the JJM platforms. No API specification for IMIS, Sujal Gaon / Sujalam Bharat or WQMIS
   is public. The JalSakhi side of every row is exact. Each target field name is a draft, written from what the
   platforms publish, until the official specification from NIC / DDWS replaces it. target_payloads()
   shapes every outbox record for each platform it belongs to, so the gateway receives what a live adapter
   would send.
"""
from __future__ import annotations

from datetime import datetime

from .. import config as C
from .. import seed as S

# ---------------------------------------------------------------------------- 1. ministry device message
DDWS_SOURCE = ("DDWS Technical / Expert Committee, 'Roadmap for the measurement & monitoring of water service "
               "delivery in rural areas', March 2021, annexure: device-to-cloud payload")

# JalSakhi device kind -> (ministry device type, {parameter key: (JalSakhi metric, scale to the key's unit)})
# Scale converts a JalSakhi value into the key's unit; ingest divides by it.
DTY = {
    "flow": ("fm", {"f": ("flow_lpm", 1.0)}),
    "branch_in": ("fm", {"f": ("flow_lpm", 1.0), "pr": ("pressure_bar", 1.0)}),
    "tap": ("fm", {"f": ("flow_lpm", 1.0), "t": ("volume_l", 0.001), "pr": ("pressure_bar", 1.0)}),
    "level": ("sl", {"lv": ("level_pct", 1.0), "vl": ("volume_l", 0.001)}),
    "gwl": ("gl", {"dp": ("depth_m", 1.0)}),
    "quality": ("ca", {"cl": ("chlorine_mgl", 1.0), "tu": ("turbidity_ntu", 1.0), "ph": ("ph", 1.0), "td": ("tds_mgl", 1.0)}),
    "branch_end": ("pt", {"pr": ("pressure_bar", 1.0)}),
    "pump": ("pm", {"i": ("current_a", 1.0), "vb": ("vibration_mms", 1.0), "q": ("discharge_lpm", 1.0), "st": ("state", 1.0)}),
    "bench": ("fm", {"f": ("flow_lpm", 1.0), "pr": ("pressure_bar", 1.0), "tu": ("turbidity_ntu", 1.0), "td": ("tds_mgl", 1.0), "ph": ("ph", 1.0)}),
}
FROM_REPORT = {"fm", "gl", "sl", "ca", "t", "f", "b", "e"}  # codes the report itself defines
KEY_DOC = {
    "t": ("totaliser", "kL", "report"), "f": ("flow rate", "L/min", "report: unit to confirm with the device registration"),
    "b": ("battery", "%", "report"), "e": ("error code: 00 none, 01 tamper, 02 other", "", "report"),
    "pr": ("pressure", "bar", "JalSakhi extension"), "lv": ("reservoir level", "%", "JalSakhi extension"),
    "vl": ("stored volume", "kL", "JalSakhi extension"), "dp": ("depth to water", "m below ground", "JalSakhi extension"),
    "cl": ("residual chlorine", "mg/L", "JalSakhi extension (the report's ca analyser measures it)"),
    "tu": ("turbidity", "NTU", "JalSakhi extension"), "ph": ("pH", "", "JalSakhi extension"), "td": ("TDS", "mg/L", "JalSakhi extension"),
    "i": ("pump current", "A", "JalSakhi extension"), "vb": ("pump vibration", "mm/s", "JalSakhi extension"),
    "q": ("pump discharge", "L/min", "JalSakhi extension"), "st": ("pump running (1/0)", "", "JalSakhi extension"),
}
TYPE_DOC = {"fm": ("flow meter (bulk, lane or consumer)", "report"), "sl": ("service-reservoir level", "report"),
            "gl": ("groundwater level", "report"), "ca": ("chlorine analyser (here with turbidity, pH, TDS)", "report"),
            "pt": ("pressure transmitter", "JalSakhi extension: the report lists the device without a code"),
            "pm": ("pump monitor", "JalSakhi extension: the report lists pump energy and current signature")}
QUALITY_OF_ERROR = {"00": "good", "01": "tamper", "02": "fault"}


def gateway_id(village_id: str) -> str:
    """The report's pattern is state_district_block_village; built from this deployment's own codes."""
    v = S.village_by_id(village_id)
    p = S.admin_path(v)
    return f"MH_{p['district_id'][3:]}_{p['block_id'][3:]}_{v['code']}"


def village_of_gateway(gid: str) -> str | None:
    return next((v["id"] for v in S.VILLAGES if gateway_id(v["id"]) == gid), None)


def device_did(device_id: str, village_code: str) -> str:
    return device_id[len(village_code) + 1:].lower() if device_id.startswith(f"{village_code}-") else device_id.lower()


def _num(x):
    if isinstance(x, bool):
        raise ValueError("not a number")
    return float(x)  # the report sends values as strings; numbers are accepted too


def ddws_in(msg: dict, devices: dict, now: datetime) -> dict:
    """One ministry-format message -> a JalSakhi telemetry event (validated afterwards like any other)."""
    for k in ("gid", "did", "dty", "p"):
        if k not in msg:
            raise ValueError(f"'{k}' is required")
    vid = village_of_gateway(str(msg["gid"]))
    if vid is None:
        raise ValueError(f"unknown gateway '{msg['gid']}'")
    code = S.village_by_id(vid)["code"]
    did = str(msg["did"]).lower()
    dev_id = next((d for d in (f"{code}-{did.upper()}", did.upper()) if d in devices), None)
    if dev_id is None:
        raise ValueError(f"unknown device '{msg['did']}' on gateway {msg['gid']}")
    dev = devices[dev_id]
    dty, keys = DTY[dev["kind"]]
    if msg["dty"] != dty:
        raise ValueError(f"device {msg['did']} is registered as type '{dty}', not '{msg['dty']}'")
    p = msg["p"] if isinstance(msg["p"], dict) else {}
    metrics, ignored = {}, []
    for key, raw in p.items():
        if key in ("b", "e"):
            continue
        if key not in keys or keys[key][0] not in dev["metrics"]:
            ignored.append(key)
            continue
        metric, scale = keys[key]
        try:
            metrics[metric] = round(_num(raw) / scale, 4)
        except (TypeError, ValueError):
            raise ValueError(f"parameter '{key}' must be a number") from None
    if not metrics:
        raise ValueError("no parameter this device reports was found in 'p'")
    ts = str(msg.get("dt") or now.isoformat(timespec="seconds"))
    if datetime.fromisoformat(ts).tzinfo is None:
        ts += "+05:30"  # the report's example carries no offset; gateways in India report IST
    err = str(p.get("e", "00")).zfill(2)
    out = {"event_id": f"ddws:{msg['gid']}:{did}:{ts}", "device_id": dev_id, "ts": ts, "metrics": metrics,
           "source": "hardware", "quality": QUALITY_OF_ERROR.get(err, "fault"), "ignored": ignored}
    if "b" in p:
        try:
            out["battery"] = max(0.0, min(100.0, _num(p["b"])))
        except (TypeError, ValueError):
            raise ValueError("parameter 'b' (battery) must be a number") from None
    return out


def ddws_out(village_id: str, device_ids: list[str], devices: dict, latest: dict) -> dict:
    """A village's latest readings as the gateway would forward them, one message per device."""
    gid, code = gateway_id(village_id), S.village_by_id(village_id)["code"]
    msgs = []
    for d in device_ids:
        rec, dev = latest.get(d), devices[d]
        if rec is None:
            continue
        dty, keys = DTY[dev["kind"]]
        p = {key: f"{rec['m'][metric] * scale:.3f}".rstrip("0").rstrip(".") for key, (metric, scale) in keys.items()
             if metric in rec["m"]}
        p["b"] = f"{dev['battery']:.0f}"
        p["e"] = {"good": "00", "tamper": "01"}.get(rec.get("quality", "good"), "02")
        msgs.append({"gid": gid, "did": device_did(d, code), "dty": dty, "dt": rec["ts"][:19], "p": p})
    return {"gid": gid, "messages": msgs, "source": DDWS_SOURCE,
            "types": [{"dty": k, "what": w, "basis": b} for k, (w, b) in TYPE_DOC.items()],
            "keys": [{"key": k, "what": w, "unit": u, "basis": b} for k, (w, u, b) in KEY_DOC.items()]}


# ------------------------------------------------------------------------- 2. JJM platform field mappings
DRAFT = "draft: replace with the official API field"
# system -> record types it takes -> [(target field, JalSakhi source path, note)]
MAPPINGS: dict[str, dict] = {
    "JJM IMIS": {
        "about": "Scheme, habitation and household tap connection records; service delivery reported by the scheme.",
        "records": {
            "service_delivery": [
                ("scheme_id", "ids.imis_scheme_id", "IMIS scheme code, from the scheme's registration"),
                ("habitation_id", "ids.imis_habitation_id", "IMIS habitation code"),
                ("village_lgd_code", "ids.lgd_village_code", "Local Government Directory code"),
                ("report_date", "data.day", "date of supply"),
                ("supply_session", "data.window", "morning / evening"),
                ("total_fhtc", "data.fhtc_total", "household tap connections on the scheme"),
                ("fhtc_receiving_water", "data.households_served", "measured or estimated, per household"),
                ("fhtc_adequate_quantity", "data.households_adequate_quantity", "at least the 55 lpcd norm"),
                ("fhtc_status_unknown", "data.households_unknown", "a silent sensor makes a home unknown, never 'functional'"),
                ("functional_fhtc_pct", "data.functional_pct", "regular + adequate + potable, per household"),
                ("avg_lpcd", "data.avg_lpcd_so_far", "litres per person per day"),
                ("supply_duration_min", "data.supply_minutes", "minutes the lanes were pressurised"),
                ("water_quality_status", "data.quality_status", "screening status, not a potability verdict"),
                ("data_source", "data.basis", "how the numbers were obtained"),
            ],
        },
    },
    "Sujal Gaon ID / Sujalam Bharat": {
        "about": "Every service event keyed to the scheme's Sujal Gaon ID and its infrastructure and service-area IDs.",
        "records": {
            "incident": [
                ("sujal_gaon_id", "ids.sujal_gaon_id", "the scheme's Sujal Gaon ID"),
                ("infrastructure_id", "ids.sujalam_infrastructure_id", "Sujalam Bharat infrastructure ID"),
                ("service_area_id", "ids.sujalam_service_area_id", "Sujalam Bharat service-area ID"),
                ("event_ref", "data.id", "JalSakhi incident ID"),
                ("event_type", "data.type", "SUPPLY_INTERRUPTION, LOW_PRESSURE, SUSPECTED_LEAK, QUALITY_VERIFY, ..."),
                ("severity", "data.severity", "low / medium / high / critical"),
                ("status", "data.status", "open / acknowledged / in_progress / resolved_pending_verification / closed"),
                ("households_affected", "data.affected_count", "FHTCs inside the affected scope"),
                ("citizen_reports", "data.report_count", "linked community reports"),
                ("escalation_level", "data.escalation_level", "1 village, 2 block, 3 district"),
                ("first_detected", "data.first_seen", "IST timestamp"),
                ("detection_basis", "data.origin", "sensor / model / citizen"),
            ],
            "grievance": [
                ("sujal_gaon_id", "ids.sujal_gaon_id", "the scheme's Sujal Gaon ID"),
                ("grievance_ref", "data.tracking_id", "the tracking ID the household was given"),
                ("fhtc_id", "data.fhtc_id", "the household's tap connection ID"),
                ("category", "data.category", "no_water, low_pressure, dirty_water, leakage, ..."),
                ("channel", "data.channel", "app, SMS, IVR, Telegram, WhatsApp"),
                ("status", "data.status", "follows the linked incident"),
                ("linked_event_ref", "data.linked_incident", "incident it corroborates or opened"),
                ("lat", "data.geo.lat", "device GPS, chat location, or the registered tap"),
                ("lon", "data.geo.lon", ""),
                ("geo_source", "data.geo.source", ""),
                ("reported_at", "data.created_at", "IST timestamp"),
            ],
        },
    },
    "WQMIS": {
        "about": "Field test kit and laboratory results, with the laboratory referral for every failed field test.",
        "records": {
            "water_quality_test": [
                ("village_lgd_code", "ids.lgd_village_code", "Local Government Directory code"),
                ("scheme_id", "ids.imis_scheme_id", "IMIS scheme code"),
                ("sample_id", "data.id", "JalSakhi test ID"),
                ("sample_location", "data.sample_point", "tank outlet, lane tail-end tap, ..."),
                ("test_type", "data.kind", "FTK (field test kit) or LAB"),
                ("tested_on", "data.ts", "IST timestamp"),
                ("ph", "data.params.ph", ""),
                ("turbidity_ntu", "data.params.turbidity_ntu", ""),
                ("tds_mg_l", "data.params.tds_mgl", ""),
                ("residual_chlorine_mg_l", "data.params.chlorine_mgl", ""),
                ("h2s_bacteriological_positive", "data.params.h2s_positive", "H2S vial screening"),
                ("result", "data.result", "pass / fail against IS 10500:2012"),
                ("lab_referral", "data.lab_status", "'requested' when an FTK test fails"),
            ],
        },
    },
    "Jal Seva Aankalan (JJM Panchayat Dashboard)": {
        "about": "The Gram Panchayat's self-assessment, drafted from evidence and endorsed by the Gram Sabha.",
        "records": {
            "jal_seva_aankalan_draft": [
                ("sujal_gaon_id", "ids.sujal_gaon_id", ""), ("assessment_date", "data.day", ""),
                ("overall_score", "data.overall", "0 to 100"), ("stage", "data.status", "draft for the Gram Sabha"),
                ("sections", "data.sections", "five parts with their indicators"),
            ],
            "jal_seva_aankalan": [
                ("sujal_gaon_id", "ids.sujal_gaon_id", ""), ("endorsed_on", "data.endorsed_on", "Gram Sabha date"),
                ("overall_score", "data.overall", "0 to 100"), ("stage", "data.status", "endorsed by the Gram Sabha"),
                ("feedback_open_until", "data.feedback_open_until", "30-day citizen feedback window"),
                ("sections", "data.sections", "five parts with their indicators"),
            ],
        },
    },
}


def _get(obj, path: str):
    for part in path.split("."):
        if not isinstance(obj, dict):
            return None
        obj = obj.get(part)
    return obj


def target_payloads(record_type: str, envelope: dict) -> list[dict]:
    """The body each JJM platform would receive for this record, built from the mapping tables."""
    out = []
    for system, m in MAPPINGS.items():
        rows = m["records"].get(record_type)
        if rows:
            out.append({"system": system, "body": {field: _get(envelope, src) for field, src, _note in rows},
                        "field_names": DRAFT})
    return out


def mapping_table() -> list[dict]:
    return [{"system": system, "about": m["about"], "records": [
        {"record_type": rt, "fields": [{"target": f, "source": src, "note": note, "basis": DRAFT} for f, src, note in rows]}
        for rt, rows in m["records"].items()]} for system, m in MAPPINGS.items()]


# ------------------------------------------------------------------------------ 3. WQMIS laboratory results
def lab_verdict(params: dict) -> tuple[str, list[str]]:
    """A laboratory result against IS 10500:2012 for the parameters the lab reports (bacteriology included)."""
    L = C.QUALITY_LIMITS
    fails = []
    if params.get("e_coli_present") or params.get("total_coliform_present"):
        fails.append("coliform bacteria detected (IS 10500: must be absent)")
    if params.get("turbidity_ntu") is not None and params["turbidity_ntu"] > L["turbidity_ntu"]["permissible"]:
        fails.append("turbidity above 5 NTU")
    if params.get("ph") is not None and not L["ph"]["min"] <= params["ph"] <= L["ph"]["max"]:
        fails.append("pH outside 6.5 to 8.5")
    if params.get("tds_mgl") is not None and params["tds_mgl"] > L["tds_mgl"]["permissible"]:
        fails.append("TDS above 2000 mg/L")
    for k, limit, label in (("fluoride_mgl", 1.5, "fluoride above 1.5 mg/L"), ("arsenic_mgl", 0.01, "arsenic above 0.01 mg/L"),
                            ("nitrate_mgl", 45, "nitrate above 45 mg/L")):
        if params.get(k) is not None and params[k] > limit:
            fails.append(label)
    return ("fail" if fails else "pass"), fails

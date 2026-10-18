"""Executable version of the test plan in docs/ (T01-T14) plus security, sync and ML checks.

Run from backend/:  python -m pytest -q
The simulator is stepped manually (no wall-clock waiting), so runs are deterministic.
"""
import os
import tempfile

import pytest

_tmp = tempfile.mkdtemp(prefix="jalsakhi-test-")
os.environ["JALSAKHI_DATA"] = _tmp
os.environ["JALSAKHI_PAUSED"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

from app import config as C  # noqa: E402
from app import main  # noqa: E402

PW = "VLG-PW"


@pytest.fixture(scope="module")
def client():
    with TestClient(main.app) as c:
        yield c


def login(client, username="demo.admin"):
    r = client.post("/api/auth/login", json={"username": username, "password": C.DEMO_PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture()
def admin(client):
    h = login(client)
    assert client.post("/api/demo/reset", headers=h).status_code == 200
    return h


def steps(n):
    for _ in range(n):
        main.P.step()


def pw_incidents(client, h, type_=None):
    rows = [i for i in client.get("/api/alerts", headers=h).json() if i["village_id"] == PW]
    return [i for i in rows if type_ is None or i["type"] == type_]


def scenario(client, h, name):
    r = client.post(f"/api/demo/scenario/{name}", headers=h, json={})
    assert r.status_code == 200, r.text
    return r.json()


# ------------------------------------------------------------------ T01-T04
def test_t01_seed_integrity(client, admin):
    hh = client.get(f"/api/households?village={PW}", headers=admin).json()
    assert len(hh) == 100
    assert len({h["branch_id"] for h in hh}) == 5
    assert all(h["branch_id"].startswith("PW-B") for h in hh)
    v = client.get(f"/api/villages/{PW}", headers=admin).json()
    assert v["kpis"]["households"] == 100 == len(v["households"])
    assert sum(b["n"] for b in v["branches"]) == 100


def test_t02_telemetry_ingest(client, admin):
    ev = {"event_id": "t02-evt-1", "device_id": "PW-B1-IN", "ts": "2026-10-05T06:10:00+05:30",
          "metrics": {"pressure_bar": 1.21, "flow_lpm": 42.5}, "source": "simulation"}
    r = client.post("/api/telemetry", json=ev, headers={"X-Device-Key": C.DEVICE_KEY})
    assert r.status_code == 201 and r.json()["stored"] is True
    rows = client.get("/api/telemetry/events?device=PW-B1-IN", headers=admin).json()
    hit = next(x for x in rows if x["event_id"] == "t02-evt-1")
    assert hit["source"] == "simulation" and hit["metrics"]["pressure_bar"] == 1.21
    again = client.post("/api/telemetry", json=ev, headers={"X-Device-Key": C.DEVICE_KEY})
    assert again.status_code == 200 and again.json()["duplicate"] is True  # idempotent retry


def test_t03_invalid_payload_rejected(client, admin):
    key = {"X-Device-Key": C.DEVICE_KEY}
    before = main.P.db.scalar("SELECT COUNT(*) FROM telemetry")
    base = {"event_id": "t03", "device_id": "PW-B1-IN", "ts": "2026-10-05T06:10:00+05:30", "metrics": {"pressure_bar": 1.0}}
    assert client.post("/api/telemetry", json={k: v for k, v in base.items() if k != "ts"}, headers=key).status_code == 422
    assert client.post("/api/telemetry", json={k: v for k, v in base.items() if k != "device_id"}, headers=key).status_code == 422
    assert client.post("/api/telemetry", json={**base, "metrics": {"pressure_bar": "high"}}, headers=key).status_code == 422
    assert client.post("/api/telemetry", json={**base, "metrics": {"pressure_bar": 999}}, headers=key).status_code == 422
    assert client.post("/api/telemetry", json={**base, "device_id": "NOPE"}, headers=key).status_code == 422
    assert client.post("/api/telemetry", json={**base, "ts": "2026-10-05T06:10:00"}, headers=key).status_code == 422  # no timezone
    assert client.post("/api/telemetry", json=base).status_code == 401  # no device key
    assert main.P.db.scalar("SELECT COUNT(*) FROM telemetry") == before


def test_t04_normal_baseline(client, admin):
    steps(190)  # the whole morning supply window
    assert not pw_incidents(client, admin), "normal operation must not raise incidents in the focus village"
    v = client.get(f"/api/villages/{PW}", headers=admin).json()
    assert v["devices"]["online"] == v["devices"]["total"]
    assert v["kpis"]["functional"]["basis"] == "today" and v["kpis"]["functional"]["pct"] >= 95
    assert v["kpis"]["estimator_agreement_pct"] >= 97


# ------------------------------------------------------------------ T05-T08
def test_t05_supply_fault(client, admin):
    scenario(client, admin, "branch_interruption")
    steps(10)
    inc = pw_incidents(client, admin, "SUPPLY_INTERRUPTION")
    assert len(inc) == 1
    d = client.get(f"/api/incidents/{inc[0]['id']}", headers=admin).json()
    assert d["branch_id"] == "PW-B3" and d["affected_count"] == 20
    assert all(a.startswith("PW-HH-") for a in d["affected_ids"])
    assert d["suspected_cause"].startswith("Suspected")
    assert d["detection_delay_min"] <= 6


def test_t06_transient_is_ignored(client, admin):
    scenario(client, admin, "transient")
    steps(15)
    assert not pw_incidents(client, admin)
    feed = client.get(f"/api/snapshot?village={PW}", headers=admin).json()["feed"]
    assert any(f["kind"] == "transient" for f in feed)


def test_t07_quality_alert_uses_cautious_language(client, admin):
    scenario(client, admin, "quality_turbidity")
    steps(14)
    inc = pw_incidents(client, admin, "QUALITY_VERIFY")
    assert len(inc) == 1
    d = client.get(f"/api/incidents/{inc[0]['id']}", headers=admin).json()
    assert "not a finding that the water is unsafe" in d["summary"]
    assert "Verification required" in d["suggested_action"]
    assert d["suspected_cause"].startswith("Suspected")


def test_t08_sensor_offline_is_unknown_not_healthy(client, admin):
    scenario(client, admin, "sensor_offline")
    steps(12)
    inc = pw_incidents(client, admin, "SENSOR_OFFLINE")
    assert len(inc) == 1
    v = client.get(f"/api/villages/{PW}", headers=admin).json()
    unknown = [h for h in v["households"] if h["s"] == "unknown"]
    assert len(unknown) >= 5
    assert v["kpis"]["counts"]["ok"] + len(unknown) == 100
    assert v["devices"]["offline"] == 3


# ------------------------------------------------------------------ T09-T12
def test_t09_complaint(client, admin):
    steps(8)
    r = client.post("/api/complaints", data={"household_id": "PW-HH-014", "category": "tap_damage",
                                             "description": "nal toot gaya hai", "language": "hi"})
    assert r.status_code == 201, r.text
    c = r.json()
    assert c["id"].startswith("JS-PW-") and c["household_id"] == "PW-HH-014" and c["status"] == "open"
    assert c["ai_category"] == "tap_damage"
    t = client.get(f"/api/complaints/track/{c['id']}").json()
    assert t["household"] == "HH-014" and t["incident"]["id"].startswith("INC-")
    listed = client.get(f"/api/complaints?village={PW}", headers=admin).json()
    assert any(x["id"] == c["id"] for x in listed)


def test_t10_same_lane_reports_are_grouped(client, admin):
    steps(8)
    ids = []
    for hh in ("PW-HH-003", "PW-HH-007", "PW-HH-012"):
        r = client.post("/api/complaints", data={"household_id": hh, "category": "dirty_water", "description": "ganda pani"})
        assert r.status_code == 201
        ids.append(r.json()["incident"]["id"])
    assert len(set(ids)) == 1, "three reports from one lane must share one incident"
    d = client.get(f"/api/incidents/{ids[0]}", headers=admin).json()
    assert d["type"] == "COMMUNITY_CLUSTER" and d["report_count"] == 3 and len(d["complaints"]) == 3
    assert "not a confirmed contamination" in d["summary"]
    assert len(pw_incidents(client, admin)) == 1


def test_t10b_report_corroborates_sensor_incident(client, admin):
    scenario(client, admin, "branch_interruption")
    steps(8)
    inc = pw_incidents(client, admin, "SUPPLY_INTERRUPTION")[0]
    r = client.post("/api/complaints", data={"household_id": "PW-HH-045", "category": "no_water"})
    assert r.json()["incident"]["id"] == inc["id"] and r.json()["linked"] == "corroborates"


def test_t11_resolution_lifecycle_and_audit(client, admin):
    scenario(client, admin, "low_pressure")
    steps(10)
    inc = pw_incidents(client, admin, "LOW_PRESSURE")[0]
    url = f"/api/incidents/{inc['id']}"

    def act(action, **kw):
        return client.patch(url, headers=admin, json={"action": action, **kw})

    assert act("close").status_code == 409  # cannot close before a repair is recorded
    assert act("acknowledge").json()["status"] == "acknowledged"
    assert act("assign", assignee="Block repair crew").json()["assigned_to"] == "Block repair crew"
    assert act("start").json()["status"] == "in_progress"
    assert act("note", note="Valve at chainage 40% found half closed").status_code == 200
    assert act("repair", note="Valve reopened and flushed").json()["status"] == "resolved_pending_verification"
    r = act("close")
    assert r.status_code == 409 and "evidence" in r.json()["detail"]  # no telemetry recovery yet
    steps(8)
    d = client.get(url, headers=admin).json()
    assert d["recovered_at"] and d["closure"]["ok"]
    assert act("close").json()["status"] == "closed"
    d = client.get(url, headers=admin).json()
    kinds = [e["kind"] for e in d["events"]]
    assert kinds[0] == "created" and "recovery" in kinds
    assert [e["to_status"] for e in d["events"] if e["kind"] == "status"] == \
        ["acknowledged", "in_progress", "resolved_pending_verification", "closed"]
    audit = client.get("/api/audit", headers=admin).json()
    assert audit["integrity"]["ok"] is True
    assert any(a["action"] == "incident.close" and a["entity_id"] == inc["id"] for a in audit["rows"])


def test_t11b_override_needs_role_and_reason(client, admin):
    scenario(client, admin, "low_pressure")
    steps(10)
    inc = pw_incidents(client, admin, "LOW_PRESSURE")[0]
    operator = login(client, "naljal.mitra")
    url = f"/api/incidents/{inc['id']}"
    assert client.patch(url, headers=operator, json={"action": "close", "override": True, "note": "x"}).status_code == 403
    vwsc = login(client, "vwsc.pimpalwadi")
    assert client.patch(url, headers=vwsc, json={"action": "close", "override": True}).status_code == 400  # reason required
    r = client.patch(url, headers=vwsc, json={"action": "close", "override": True, "note": "Duplicate of a paper work order"})
    assert r.status_code == 200 and r.json()["closure_reason"].startswith("OVERRIDE")


def test_t12_reset_and_replay_are_deterministic(client, admin):
    runs = []
    for _ in range(2):
        client.post("/api/demo/reset", headers=admin)
        scenario(client, admin, "leak")
        steps(20)
        inc = pw_incidents(client, admin)
        runs.append([(i["type"], i["title"], i["affected_count"], i["detection_delay_min"]) for i in inc])
    assert runs[0] and runs[0] == runs[1]


def test_t14_integration_is_labelled_sandbox(client, admin):
    steps(5)
    s = client.get("/api/sync", headers=admin).json()
    assert s["summary"]["live"] is False and "SANDBOX" in s["notice"]
    assert all(m["external_id"].startswith("DEMO-") for m in s["mappings"])
    assert all(t["state"] in ("sandbox", "planned", "export") for t in s["targets"])  # nothing is live


# ------------------------------------------------------- beyond the doc plan
def test_ml_small_leak_caught_before_households_are_affected(client, admin):
    scenario(client, admin, "small_leak")
    steps(14)
    inc = pw_incidents(client, admin)
    assert len(inc) == 1 and inc[0]["type"] in ("ABNORMAL_PATTERN", "SUSPECTED_LEAK") and inc[0]["origin"] == "ml"
    v = client.get(f"/api/villages/{PW}", headers=admin).json()
    assert v["kpis"]["counts"]["low"] == 0 and v["kpis"]["counts"]["dry"] == 0


def test_ml_pump_failure_predicted_then_forecast(client, admin):
    scenario(client, admin, "pump_degradation")
    steps(16)
    risk = pw_incidents(client, admin, "PUMP_RISK")
    assert len(risk) == 1 and risk[0]["origin"] == "ml"
    assert not pw_incidents(client, admin, "PUMP_FAULT"), "the pump must still be running when the risk is raised"
    scenario(client, admin, "pump_trip")
    steps(16)
    assert pw_incidents(client, admin, "PUMP_FAULT")
    assert pw_incidents(client, admin, "SHORTFALL_PREDICTED")


def test_complaint_classifier_multilingual(client):
    for text, want in [("pani nahi aa raha hai", "no_water"), ("पाईप फुटला आहे", "leakage"), ("water smells bad", "smell_taste")]:
        r = client.post("/api/nlp/classify", json={"text": text}).json()
        assert r["category"] == want, (text, r)


def test_auth_and_jurisdiction(client, admin):
    assert client.get("/api/alerts").status_code == 401
    assert client.post("/api/auth/login", json={"username": "demo.admin", "password": "wrong"}).status_code == 401
    operator = login(client, "naljal.mitra")
    assert client.get("/api/villages/VLG-DK", headers=operator).status_code == 403
    assert client.get(f"/api/villages/{PW}", headers=operator).status_code == 200
    assert client.get("/api/overview?level=state&id=ST-MH", headers=operator).status_code == 403
    citizen = client.post("/api/auth/citizen", json={"household_id": "PW-HH-014"}).json()["token"]
    assert client.get("/api/alerts", headers={"Authorization": f"Bearer {citizen}"}).status_code == 403


def test_sync_outage_retries_and_reconciles(client, admin):
    client.post("/api/sync/outage", headers=admin, json={"on": True})
    scenario(client, admin, "branch_interruption")
    steps(10)
    main.P.sync.process(force=True)
    s = client.get("/api/sync", headers=admin).json()["summary"]
    assert s["outage"] and s["queued"] + s["retry"] > 0
    client.post("/api/sync/outage", headers=admin, json={"on": False})
    for _ in range(12):  # the sandbox also injects occasional timeouts; retries must drain the queue
        client.post("/api/sync/flush", headers=admin)
    s = client.get("/api/sync", headers=admin).json()["summary"]
    assert s["queued"] + s["retry"] == 0 and s["reconciled"] is True


def test_quality_closure_needs_passing_ftk(client, admin):
    scenario(client, admin, "quality_turbidity")
    steps(14)
    inc = pw_incidents(client, admin, "QUALITY_VERIFY")[0]
    url = f"/api/incidents/{inc['id']}"
    client.patch(url, headers=admin, json={"action": "repair", "note": "Tank cleaned and line flushed"})
    steps(40)
    r = client.patch(url, headers=admin, json={"action": "close"})
    assert r.status_code == 409 and "FTK" in r.json()["detail"]
    t = client.post("/api/quality/tests", headers=admin, json={
        "village_id": PW, "sample_point": "Tank outlet", "kind": "FTK", "incident_id": inc["id"],
        "params": {"turbidity_ntu": 0.8, "chlorine_mgl": 0.5, "ph": 7.2, "h2s_positive": False}})
    assert t.status_code == 201 and t.json()["result"] == "pass"
    assert client.patch(url, headers=admin, json={"action": "close"}).json()["status"] == "closed"


def test_multi_level_rollup(client, admin):
    steps(20)
    st = client.get("/api/overview?level=state&id=ST-MH", headers=admin).json()
    assert st["totals"]["villages"] == 6 and st["totals"]["households"] == 568
    assert {c["name"] for c in st["children"]} == {"Pune", "Satara"}
    blk = client.get("/api/overview?level=block&id=BK-MUL", headers=admin).json()
    assert blk["totals"]["households"] == 184 and len(blk["children"]) == 2
    assert len(st["trend"]) >= 30


def test_village_layout_matches_the_network(client, admin):
    """The GIS page draws straight from this payload: every home and lane must be in it, in [lon, lat]."""
    hh = {h["id"] for h in client.get(f"/api/households?village={PW}", headers=admin).json()}
    g = client.get(f"/api/villages/{PW}/geo", headers=admin).json()
    assert {h["id"] for h in g["homes"]} == hh and [h["i"] for h in g["homes"]] == list(range(100))
    assert [l["idx"] for l in g["lanes"]] == list(range(5)) and sum(l["n"] for l in g["lanes"]) == 100
    assert all(len(h["ring"]) >= 4 and h["ring"][0] == h["ring"][-1] for h in g["homes"])
    (w, s), (e, n) = g["view"]
    assert 73 < w < e < 74 and 18 < s < n < 19  # Pimpalwadi is near 73.52 E, 18.50 N
    assert all(w - 0.01 < h["c"][0] < e + 0.01 and s - 0.01 < h["c"][1] < n + 0.01 for h in g["homes"])
    assert g["tank"]["legs"] and g["pump"]["pipe"] and g["land"] and g["fields"] and g["trees"]
    # the approach road starts in the square by the tank and stays clear of every house; each building casts a shadow
    assert g["road"][0] == g["tank"]["c"] and len(g["road"]) > 20 and len(g["plaza"]) > 8
    metres = lambda a, b: ((a[0] - b[0]) * 105_500) ** 2 + ((a[1] - b[1]) * 111_320) ** 2  # squared, near 18.5 N
    assert min(metres(h["c"], q) for h in g["homes"] for q in g["road"][4:]) > 15 ** 2
    assert len(g["shadows"]) > len(g["homes"]) + len(g["trees"])


def test_health_flags_a_server_older_than_its_code(client, tmp_path):
    assert client.get("/api/health").json()["stale"] is False
    src = tmp_path / "mod.py"

    def save(text, at):  # explicit timestamps: two quick writes can share one on a coarse filesystem clock
        src.write_text(text)
        os.utime(src, ns=(at, at))

    save("A = 1\n", 1_000_000_000)
    watch = main.CodeWatch(tmp_path)
    assert watch.check(every=0) is False
    save("A = 2\n", 2_000_000_000)  # the code on disk moved on while the process kept running
    assert watch.check(every=0) is True
    save("A = 1\n", 3_000_000_000)
    assert watch.check(every=0) is False


def test_models_type_and_place_a_fault(client, admin):
    scenario(client, admin, "leak")  # 30 L/min at 45% along School Road (20 homes): beside HH-029
    steps(12)
    leak = pw_incidents(client, admin, "SUSPECTED_LEAK")
    assert len(leak) == 1
    ev = client.get(f"/api/incidents/{leak[0]['id']}", headers=admin).json()["evidence"]
    seg = ev["segment"]
    assert ev["leak_probability"] >= 0.7 and seg["kind"] == "leak"
    assert seg["x0"] <= 0.45 <= seg["x1"] and abs(seg["x"] - 0.45) <= 0.1  # within two homes
    assert seg["near"] in ("HH-027", "HH-028", "HH-029", "HH-030", "HH-031")
    client.post("/api/demo/reset", headers=admin)
    scenario(client, admin, "low_pressure")  # obstruction at 40% along Tekdi Wasti
    steps(10)
    ev = client.get(f"/api/incidents/{pw_incidents(client, admin, 'LOW_PRESSURE')[0]['id']}", headers=admin).json()["evidence"]
    assert ev["leak_probability"] <= 0.3 and ev["segment"]["kind"] == "step" and ev["segment"]["x0"] <= 0.4 <= ev["segment"]["x1"]


def test_pump_life_follows_its_own_wear_trend(client, admin):
    scenario(client, admin, "pump_degradation")
    steps(30)
    life = client.get(f"/api/villages/{PW}", headers=admin).json()["pump"]["life"]
    assert life["basis"] == "own trend" and 0.3 < life["h"] < 4 and life["lo"] <= life["h"] <= life["hi"]


def test_what_if_runs_the_calibrated_model(client, admin):
    steps(20)
    post = lambda **body: client.post(f"/api/villages/{PW}/whatif", headers=admin, json=body).json()  # noqa: E731
    same = post()
    assert same["baseline"] == same["scenario"] and same["scenario"]["demand_met_pct"] == 100.0 and same["scenario"]["empty_at"] is None
    assert same["check"] and all(abs(c["predicted_tail"] - c["measured_tail"]) < 0.08 for c in same["check"])  # the model matches the sensors
    shut = post(closed=[1])
    assert shut["scenario"]["homes_cut_off"] == 20 and shut["scenario"]["demand_met_pct"] < 90
    assert shut["scenario"]["lanes"][0]["min_tail"] > same["scenario"]["lanes"][0]["min_tail"]  # less flow in the main, more pressure elsewhere
    hard = post(demand_pct=60, pump_out_h=24)
    assert hard["scenario"]["empty_at"] and hard["scenario"]["demand_met_pct"] < 80
    assert hard["scenario"]["lanes"][0]["min_tail"] < same["scenario"]["lanes"][0]["min_tail"]
    assert client.post("/api/villages/VLG-DK/whatif", headers=login(client, "naljal.mitra"), json={}).status_code == 403


def test_replay_winds_the_twin_back(client, admin):
    scenario(client, admin, "branch_interruption")
    steps(10)
    rows = client.get(f"/api/villages/{PW}/timeline", headers=admin).json()["frames"]
    assert len(rows) >= 16 and rows[0][4] == 0 and rows[-1][4] > 0  # no home without water at the start, some now
    then = client.get(f"/api/villages/{PW}/replay?k={rows[0][0]}", headers=admin).json()
    assert len(then["focus"]["households"]) == 100 and then["focus"]["kpis"]["counts"]["dry"] == 0 and then["clock"]["replay"]
    now = client.get(f"/api/villages/{PW}/replay?k={rows[-1][0]}", headers=admin).json()
    assert now["focus"]["kpis"]["counts"]["dry"] == rows[-1][4]
    assert client.get(f"/api/villages/{PW}/replay?k=999999", headers=admin).status_code == 404


def test_water_balance_margin_narrows_and_a_leak_shows(client, admin):
    steps(20)
    early = client.get(f"/api/villages/{PW}", headers=admin).json()["balance"]
    assert early["settling"] and early["uncertainty_pct"] > 25  # homes are still starting to fill: no verdict yet
    scenario(client, admin, "leak")
    steps(150)
    bal = client.get(f"/api/villages/{PW}", headers=admin).json()["balance"]
    assert bal["uncertainty_pct"] < 12 and bal["unaccounted_pct"] > bal["uncertainty_pct"]
    gaps = [lane["gap_pct"] for lane in bal["lanes"]]
    assert gaps[1] == max(gaps) and gaps[1] > bal["lane_margin_pct"]  # School Road, where the leak is


def test_one_dead_tap_is_told_apart_from_a_lane_fault(client, admin):
    scenario(client, admin, "tap_fault")  # a blocked service line at one metered home
    steps(8)
    inc = pw_incidents(client, admin)
    assert [i["type"] for i in inc] == ["TAP_FAULT"]  # and no alarm on the lane itself
    d = client.get(f"/api/incidents/{inc[0]['id']}", headers=admin).json()
    home_id = d["scope_id"]
    assert d["scope_type"] == "household" and d["affected_count"] == 1 and d["evidence"]["lane_bar_here"] > 0.8 > d["evidence"]["tap_bar"]
    v = client.get(f"/api/villages/{PW}", headers=admin).json()
    home = next(h for h in v["households"] if h["id"] == home_id)
    assert home["s"] == "dry" and home["m"] and v["kpis"]["counts"]["dry"] == 1 and v["kpis"]["counts"]["low"] == 0  # the neighbours are untouched
    told = lambda hh: [n for n in client.get(f"/api/citizen/notifications?household_id={hh}").json() if n["incident_id"] == d["id"]]  # noqa: E731
    assert told(home_id) and not told("PW-HH-001")  # only that household is alerted
    client.patch(f"/api/incidents/{d['id']}", headers=admin, json={"action": "repair", "note": "Stopcock replaced"})
    steps(8)
    assert client.get(f"/api/incidents/{d['id']}", headers=admin).json()["recovered_at"]


def test_bench_node_takes_over_one_home(client, admin):
    steps(20)

    def node(n, bar, lpm):
        return client.post("/api/telemetry", headers={"X-Device-Key": C.DEVICE_KEY}, json={
            "event_id": f"hil-{n}", "device_id": "HW-NODE-01", "ts": "2026-10-05T06:30:00+05:30",
            "metrics": {"pressure_bar": bar, "flow_lpm": lpm}, "source": "hardware", "quality": "emulated"})

    home = lambda: next(h for h in client.get(f"/api/villages/{PW}", headers=admin).json()["households"] if h["id"] == "PW-HH-011")  # noqa: E731
    assert not home()["hw"]
    assert node(1, 1.15, 6.0).status_code == 201
    steps(2)
    hw = client.get("/api/hardware", headers=admin).json()
    assert hw["live"] and hw["bound"]["household_id"] == "PW-HH-011" and hw["quality"] == "emulated" and hw["packets"] == 1
    assert home()["hw"] and home()["s"] == "ok" and abs(home()["p"] - 1.15) < 0.01  # the twin shows the board's reading
    node(2, 0.02, 0.0)  # someone closes the tap on the bench
    steps(6)
    assert home()["s"] == "dry"
    fault = pw_incidents(client, admin, "TAP_FAULT")
    assert len(fault) == 1 and len(pw_incidents(client, admin)) == 1
    assert client.get(f"/api/incidents/{fault[0]['id']}", headers=admin).json()["evidence"]["source"] == "hardware"
    assert client.post("/api/hardware/bind", headers=admin, json={"household_id": "PW-HH-001"}).status_code == 422  # not a metered home
    assert client.post("/api/hardware/bind", headers=admin, json={"household_id": "PW-HH-004"}).json()["bound"]["label"] == "HH-004"
    assert client.post("/api/hardware/bind", headers=admin, json={"household_id": "PW-HH-011"}).status_code == 200


def test_tail_end_service_is_measured_against_head_end(client, admin):
    steps(40)
    eq = client.get(f"/api/villages/{PW}", headers=admin).json()["equity"]
    assert eq["head_pct"] > 95 and eq["tail_pct"] > 95 and eq["ratio"] > 0.95  # a healthy village serves both ends alike
    dk = client.get("/api/villages/VLG-DK", headers=admin).json()["equity"]  # Devkund has a standing obstruction on Tekdi Wasti
    lane = next(ln for ln in dk["lanes"] if ln["name"] == "Tekdi Wasti")
    assert lane["head_pct"] > 80 and lane["tail_pct"] < 20 and dk["ratio"] < 0.9


def test_a_leak_closes_only_after_a_clean_water_test(client, admin):
    scenario(client, admin, "leak")
    steps(12)
    url = f"/api/incidents/{pw_incidents(client, admin, 'SUSPECTED_LEAK')[0]['id']}"
    client.patch(url, headers=admin, json={"action": "repair", "note": "Repair clamp fitted"})
    steps(10)
    r = client.patch(url, headers=admin, json={"action": "close"})
    assert r.status_code == 409 and "FTK" in r.json()["detail"]  # pressure is back, which does not prove the water is clean
    t = client.post("/api/quality/tests", headers=admin, json={
        "village_id": PW, "sample_point": "Tap downstream of the repair", "kind": "FTK", "incident_id": url.rsplit("/", 1)[1],
        "params": {"turbidity_ntu": 0.8, "chlorine_mgl": 0.5, "ph": 7.2, "h2s_positive": False}})
    assert t.status_code == 201 and t.json()["result"] == "pass"
    assert client.patch(url, headers=admin, json={"action": "close"}).json()["status"] == "closed"


def test_sensor_study_and_scale_are_published(client, admin):
    study = client.get("/api/ai/models", headers=admin).json()["sensor_study"]
    opt = {o["taps_per_lane"]: o for o in study["options"]}
    assert opt[0]["leaks_placed"] == 0 and opt[3]["leak_error_homes"] < opt[1]["leak_error_homes"]  # more taps place a leak better
    assert opt[0]["affected_found"] < opt[3]["affected_found"] <= opt["all"]["affected_found"]
    assert "measured" in client.get("/api/scale", headers=admin).json()


def test_upkeep_plan_operator_log_and_accounts(client, admin):
    om = client.get(f"/api/om?village={PW}", headers=admin).json()
    assert om["profile"]["ids"]["sujal_gaon_id"].startswith("DEMO-") and len(om["profile"]["assets"]) == 5
    assert om["upkeep"]["total"] == 12 and len(om["accounts"]["months"]) == 4 and om["accounts"]["months"][-1]["partial"]
    acc = om["accounts"]
    assert 50 < acc["collection_pct"] < 100 and acc["recovery_pct"] < 100 and acc["break_even_at_this_rate"] > acc["tariff"]  # the charge does not cover the cost
    assert all(m["costs"]["electricity"] > 0 for m in acc["months"])  # worked out from the pump's energy, never typed in

    # upkeep: an overdue item, done, is no longer overdue (Devkund has let things slide)
    late = next(t for t in client.get("/api/om?village=VLG-DK", headers=admin).json()["upkeep"]["tasks"] if t["status"] == "overdue")
    assert client.post(f"/api/om/tasks/{late['id']}/done", headers=admin, json={"note": "done at the Jal Utsav"}).status_code == 200
    after = next(t for t in client.get("/api/om?village=VLG-DK", headers=admin).json()["upkeep"]["tasks"] if t["id"] == late["id"])
    assert after["status"] == "ok" and after["days_left"] > 0
    assert client.post("/api/om/tasks/VLG-DK:nothing/done", headers=admin, json={}).status_code == 404

    # operator log: a true reading agrees with the flow sensor, an inflated one is caught
    steps(60)
    meter = client.get(f"/api/om/meter?village={PW}", headers=admin).json()["meter_kl"]
    base = om["log"]["rows"][0]["meter_kl"]  # the last reading before this session
    ok = client.post("/api/om/log", headers=admin, json={"village_id": PW, "meter_kl": meter, "pump_hours": 0.5, "chlorine_g": 40})
    assert ok.status_code == 201 and ok.json()["verdict"] == "match"
    high = client.post("/api/om/log", headers=admin, json={"village_id": PW, "meter_kl": base + (meter - base) * 1.25})
    assert high.json()["verdict"] == "differs" and high.json()["diff_pct"] > 15
    assert client.post("/api/om/log", headers=admin, json={"village_id": PW, "meter_kl": base - 5}).status_code == 422  # a meter only counts up

    # accounts: a payment clears the household's dues once, with a receipt it can see
    owing = acc["dues"][0]
    paid = client.post("/api/om/payments", headers=admin, json={"household_id": owing["id"]})
    assert paid.status_code == 201 and paid.json()["amount"] == owing["due"] and paid.json()["receipt"].startswith("RC-PW-")
    mine = client.get(f"/api/citizen/home?household_id={owing['id']}").json()
    assert mine["charges"]["due"] == 0 and mine["charges"]["last_receipt"]["id"] == paid.json()["receipt"] and len(mine["contacts"]) == 4
    assert client.post("/api/om/payments", headers=admin, json={"household_id": owing["id"]}).status_code == 409
    assert client.post("/api/om/expenses", headers=admin, json={"village_id": PW, "head": "repairs", "amount": 850, "note": "Valve gland"}).status_code == 201
    assert client.post("/api/om/expenses", headers=admin, json={"village_id": PW, "head": "electricity", "amount": 100}).status_code == 422
    now = client.get(f"/api/om?village={PW}", headers=admin).json()["accounts"]
    assert now["months"][-1]["costs"]["repairs"] == 850 and now["months"][-1]["collected"] > acc["months"][-1]["collected"]
    assert client.get("/api/om?village=VLG-DK", headers=login(client, "naljal.mitra")).status_code == 403


def test_aankalan_has_five_parts_and_a_feedback_window(client, admin):
    draft = client.get(f"/api/aankalan/{PW}", headers=admin).json()
    assert [x["key"] for x in draft["sections"]] == ["service", "quality", "om", "source", "institution"]
    assert all(x["score"] is not None for x in draft["sections"]) and draft["stage"]["stage"] == "draft"
    answer = {"household_id": "PW-HH-014", "agree": True, "comment": "Water comes on time"}
    assert client.post("/api/citizen/aankalan", json=answer).status_code == 409  # nothing published yet
    assert client.post(f"/api/aankalan/{PW}/endorse", headers=login(client, "naljal.mitra"), json={}).status_code == 403
    stage = client.post(f"/api/aankalan/{PW}/endorse", headers=login(client, "vwsc.pimpalwadi"), json={"note": "Gram Sabha of 5 October"}).json()
    assert stage["stage"] == "feedback" and stage["days_left"] == 30
    assert client.post("/api/citizen/aankalan", json=answer).status_code == 201
    seen = client.get("/api/citizen/aankalan?household_id=PW-HH-014").json()
    assert seen["stage"] == "feedback" and seen["mine"] is True and seen["responses"] == 1 and len(seen["sections"]) == 5
    assert client.get(f"/api/aankalan/{PW}", headers=admin).json()["stage"]["comments"][0]["comment"] == "Water comes on time"


def test_scheme_exports_for_other_systems(client, admin):
    g = client.get(f"/api/villages/{PW}/export.geojson", headers=admin)
    assert g.status_code == 200 and g.headers["content-type"].startswith("application/geo+json")
    fc = g.json()
    kinds = [f["properties"]["kind"] for f in fc["features"]]
    assert fc["type"] == "FeatureCollection" and kinds.count("tap_connection") == 100 and kinds.count("distribution_lane") == 5
    assert {"elevated_tank", "pump_house", "borewell"} <= set(kinds)
    assert all(f["properties"]["sujal_gaon_id"].startswith("DEMO-") and f["properties"]["demo"] for f in fc["features"])
    lon, lat = fc["features"][-1]["geometry"]["coordinates"]
    assert 73 < lon < 74 and 18 < lat < 19  # longitude first, as GeoJSON requires
    csv = client.get(f"/api/villages/{PW}/service.csv", headers=admin)
    lines = csv.text.strip().splitlines()
    assert csv.headers["content-type"].startswith("text/csv") and lines[0].startswith("day,functional_pct") and len(lines) >= 31
    assert client.get(f"/api/villages/{PW}/export.geojson").status_code == 401

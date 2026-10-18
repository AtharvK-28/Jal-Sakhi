"""Procedural village layout for the GIS view (demo geometry, deterministic per village).

Lanes meander out from the tank, houses stand on plots either side with small front yards, fields
fill the wedges between lanes, trees are scattered behind the houses, a lane's name earns its
landmark (a temple on Mandir Lane, a pond by Talav Ali), and an approach road leaves the village
square through the clearest gap between two lanes.

Nothing here feeds the hydraulics: the network model only uses each household's position along its
lane. This module decides where that position sits on the ground. Working units are metres in a
local frame (x east, y north, origin at the tank); to_geo() converts to longitude / latitude.
"""
from __future__ import annotations

import math
import random

ROAD_HALF = 2.6  # half carriageway plus verge, metres
CROPS = ["#cfe3a5", "#b9d98c", "#e3dc9a", "#a9cf8b", "#d9cf8a", "#c4dba0", "#b4d39a"]
SUN = (math.sin(math.radians(38)), math.cos(math.radians(38)))  # shadows fall to the north-east (light from the south-west)
SHADOW = 0.75  # shadow length per metre of height


def _along(path: list[tuple], cum: list[float], s: float):
    """Point and heading (radians clockwise from north) at arc length s along a polyline."""
    s = max(0.0, min(s, cum[-1]))
    k = 1
    while k < len(cum) - 1 and cum[k] < s:
        k += 1
    (x0, y0), (x1, y1) = path[k - 1], path[k]
    seg = cum[k] - cum[k - 1] or 1.0
    t = (s - cum[k - 1]) / seg
    return x0 + (x1 - x0) * t, y0 + (y1 - y0) * t, math.atan2(x1 - x0, y1 - y0)


def _rect(cx: float, cy: float, w: float, d: float, heading: float) -> list[tuple]:
    """Rectangle w (along the heading) by d (across it), centred on (cx, cy)."""
    tx, ty = math.sin(heading), math.cos(heading)
    nx, ny = math.cos(heading), -math.sin(heading)
    return [(cx + sx * w / 2 * tx + sy * d / 2 * nx, cy + sx * w / 2 * ty + sy * d / 2 * ny)
            for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]


def _ngon(cx: float, cy: float, r: float, n: int = 12, rot: float = 0.0) -> list[tuple]:
    return [(cx + r * math.sin(rot + 2 * math.pi * i / n), cy + r * math.cos(rot + 2 * math.pi * i / n)) for i in range(n)]


def _hull(pts: list[tuple]) -> list[tuple]:
    """Convex hull (monotone chain), anticlockwise."""
    pts = sorted(set(pts))
    if len(pts) < 3:
        return pts

    def half(seq):
        out: list[tuple] = []
        for q in seq:
            while len(out) >= 2 and (out[-1][0] - out[-2][0]) * (q[1] - out[-2][1]) - (out[-1][1] - out[-2][1]) * (q[0] - out[-2][0]) <= 0:
                out.pop()
            out.append(q)
        return out[:-1]

    return half(pts) + half(reversed(pts))


def _shadow(poly: list[tuple], height: float, base: float = 0.0) -> list[tuple]:
    """Ground shadow of a prism standing on poly between base and height: the footprint swept along the sun's direction."""
    near, far = base * SHADOW, height * SHADOW
    return _hull([(x + SUN[0] * near, y + SUN[1] * near) for x, y in poly] + [(x + SUN[0] * far, y + SUN[1] * far) for x, y in poly])


def _dist_to_path(px: float, py: float, path: list[tuple]) -> float:
    best = 1e9
    for (x0, y0), (x1, y1) in zip(path, path[1:]):
        dx, dy = x1 - x0, y1 - y0
        t = max(0.0, min(1.0, ((px - x0) * dx + (py - y0) * dy) / (dx * dx + dy * dy or 1.0)))
        best = min(best, math.hypot(px - (x0 + t * dx), py - (y0 + t * dy)))
    return best


def build_layout(spec: dict, sizes: list[int], branch_ids: list[str], branch_names: list[str], hh_ids: list[str],
                 instrumented: list[bool], institutions: list[dict]) -> dict:
    rnd = random.Random(spec["seed"] * 101 + 7)
    nb = len(sizes)
    max_dev = math.radians(min(30.0, 130.0 / nb))  # how far a lane may swing from its bearing without crossing a neighbour

    # ---- lanes: a smooth meander is a heading that wobbles as a sum of slow sines
    lanes = []
    for b in range(nb):
        base = math.radians(spec.get("bearing", 20) + b * 360.0 / nb + rnd.uniform(-6, 6))
        spacing = rnd.uniform(7.2, 8.6)  # lane length per household; homes alternate sides, so plots are twice this wide
        lead = rnd.uniform(40, 54) + max(0, nb - 4) * 4
        total = lead + sizes[b] * spacing + 12
        a1, a2 = rnd.uniform(0.45, 0.85) * max_dev, rnd.uniform(0.15, 0.35) * max_dev
        w1, w2, ph = rnd.uniform(120, 210), rnd.uniform(48, 80), rnd.uniform(0, 6.28)
        path, x, y, step = [(0.0, 0.0)], 0.0, 0.0, 5.0
        for i in range(int(total / step) + 1):
            s = i * step
            ease = min(1.0, s / 30.0)  # leave the tank straight, then start to wander
            h = base + ease * (a1 * math.sin(2 * math.pi * s / w1 + ph) + a2 * math.sin(2 * math.pi * s / w2 + 2 * ph))
            x, y = x + math.sin(h) * step, y + math.cos(h) * step
            path.append((x, y))
        cum = [0.0]
        for p, q in zip(path, path[1:]):
            cum.append(cum[-1] + math.hypot(q[0] - p[0], q[1] - p[1]))
        lanes.append({"idx": b, "id": branch_ids[b], "name": branch_names[b], "n": sizes[b], "path": path, "cum": cum,
                      "lead": lead, "spacing": spacing, "length": cum[-1]})

    # ---- homes: alternate sides of the lane, set back behind a small front yard
    homes, i = [], 0
    for lane in lanes:
        for pos in range(1, lane["n"] + 1):
            s = lane["lead"] + pos * lane["spacing"]
            px, py, h = _along(lane["path"], lane["cum"], s)
            side = 1 if pos % 2 else -1
            w, d = rnd.uniform(6.5, 10.2), rnd.uniform(6.0, 9.2)
            off = ROAD_HALF + rnd.uniform(2.0, 5.5) + d / 2
            cx, cy = px + side * off * math.cos(h), py - side * off * math.sin(h)
            homes.append({"i": i, "id": hh_ids[i], "label": f"HH-{i + 1:03d}", "branch_idx": lane["idx"], "pos": pos,
                          "lane": lane["name"], "metered": bool(instrumented[i]), "c": (cx, cy), "join": (px, py),
                          "poly": _rect(cx, cy, w, d, h + math.radians(rnd.uniform(-7, 7))),
                          "h": round(rnd.choice([3.1, 3.3, 3.4, 3.6, 3.2, 6.2, 6.6]) + rnd.uniform(-0.2, 0.2), 1)})
            i += 1

    # ---- institutions sit behind the house row, reached by a short path
    sites = []
    for inst in institutions:
        lane = lanes[inst["branch_idx"]]
        px, py, h = _along(lane["path"], lane["cum"], lane["lead"] + inst["pos"] * lane["spacing"])
        w, d = (26.0, 12.0) if inst["kind"] == "school" else (15.0, 10.0)
        off = ROAD_HALF + 19.5 + d / 2
        cx, cy = px + off * math.cos(h), py - off * math.sin(h)
        sites.append({**inst, "c": (cx, cy), "join": (px, py), "poly": _rect(cx, cy, w, d, h), "h": 5.2 if inst["kind"] == "school" else 4.2})

    # ---- landmarks named by the lanes
    def lane_end(name: str, beyond: float, aside: float):
        lane = next((ln for ln in lanes if ln["name"] == name), None)
        if lane is None:
            return None
        ex, ey, h = _along(lane["path"], lane["cum"], lane["length"])
        return ex + beyond * math.sin(h) + aside * math.cos(h), ey + beyond * math.cos(h) - aside * math.sin(h), h

    temple = None
    spot = lane_end("Mandir Lane", 14, 0)
    if spot:
        temple = {"c": spot[:2], "poly": _rect(spot[0], spot[1], 9.5, 9.5, spot[2]), "h": 7.5,
                  "spire": _rect(spot[0], spot[1], 4.2, 4.2, spot[2]), "spire_h": 13.5}
    pond = None
    spot = lane_end("Talav Ali", 30, 12)
    if spot:
        wob = [(rnd.uniform(0.82, 1.18)) for _ in range(18)]
        pond = {"c": spot[:2], "r": 21.0,
                "poly": [(spot[0] + 21 * wob[k] * math.sin(2 * math.pi * k / 18), spot[1] + 17 * wob[k] * math.cos(2 * math.pi * k / 18)) for k in range(18)]}

    # ---- village land: an irregular blob that takes in every lane, pond and temple
    reach = max(math.hypot(*ln["path"][-1]) for ln in lanes) + (62 if pond else 44)

    # ---- approach road: out of the square through whichever gap between two lanes is clearest of buildings
    rr = random.Random(spec["seed"] * 977 + 3)  # its own stream, so the road does not reshuffle anything above
    ends = sorted(math.atan2(ln["path"][-1][0], ln["path"][-1][1]) for ln in lanes)
    obstacles = [h["c"] for h in homes] + [s["c"] for s in sites] + ([temple["c"]] if temple else []) + ([pond["c"]] if pond else [])
    wob, ph = rr.uniform(0.07, 0.13), rr.uniform(0, 6.28)
    road, clear = [], -1.0
    for a, b in zip(ends, ends[1:] + [ends[0] + 2 * math.pi]):
        theta, x, y, cand = (a + b) / 2, 0.0, 0.0, [(0.0, 0.0)]
        for i in range(int(reach * 1.75 / 6.0)):
            h = theta + min(1.0, i * 6.0 / 40.0) * wob * math.sin(2 * math.pi * i * 6.0 / 230.0 + ph)
            x, y = x + math.sin(h) * 6.0, y + math.cos(h) * 6.0
            cand.append((x, y))
        gap = min(_dist_to_path(o[0], o[1], cand) for o in obstacles)
        if gap > clear:
            road, clear = cand, gap
    plaza = _ngon(0.0, 0.0, 13.0, 28)
    p3, p5 = rnd.uniform(0, 6.28), rnd.uniform(0, 6.28)

    def land_r(theta: float) -> float:
        return reach * (1 + 0.07 * math.sin(3 * theta + p3) + 0.04 * math.sin(5 * theta + p5))

    land = [(land_r(t) * math.sin(t), land_r(t) * math.cos(t)) for t in (2 * math.pi * k / 56 for k in range(56))]

    # ---- fields: a rotated, jittered grid of plots, kept clear of lanes, homes and landmarks
    fields, rot = [], math.radians(rnd.uniform(8, 38))
    cw, ch = 44.0, 31.0
    cells = int(reach / min(cw, ch)) + 2
    for gx in range(-cells, cells + 1):
        for gy in range(-cells, cells + 1):
            ux, uy = gx * cw + rnd.uniform(-2, 2), gy * ch + rnd.uniform(-2, 2)
            cx, cy = ux * math.cos(rot) - uy * math.sin(rot), ux * math.sin(rot) + uy * math.cos(rot)
            r = math.hypot(cx, cy)
            if r < 58 or r > land_r(math.atan2(cx, cy)) * 0.93:
                continue
            if any(_dist_to_path(cx, cy, ln["path"]) < 31 for ln in lanes) or _dist_to_path(cx, cy, road) < 24:
                continue
            if any(math.hypot(cx - s["c"][0], cy - s["c"][1]) < 32 for s in sites):
                continue
            if pond and math.hypot(cx - pond["c"][0], cy - pond["c"][1]) < 44:
                continue
            if temple and math.hypot(cx - temple["c"][0], cy - temple["c"][1]) < 30:
                continue
            # _rect headings run clockwise from north, the grid angle anticlockwise from east: -rot lines them up
            fields.append({"poly": _rect(cx, cy, ch - 2.6, cw - 2.6, -rot), "crop": rnd.choice(CROPS)})

    # ---- trees: an avenue along the approach road, then behind the houses, round the pond, along field edges
    trees, tries = [], 0
    rcum = [0.0]
    for p, q in zip(road, road[1:]):
        rcum.append(rcum[-1] + math.hypot(q[0] - p[0], q[1] - p[1]))
    s, side = 34.0, 1
    while s < min(rcum[-1], reach * 1.3):
        px, py, h = _along(road, rcum, s)
        off = side * rr.uniform(6.6, 8.2)
        tx, ty = px + off * math.cos(h), py - off * math.sin(h)
        if all(math.hypot(tx - o["c"][0], ty - o["c"][1]) > 9 for o in homes) and all(_dist_to_path(tx, ty, ln["path"]) > 6.5 for ln in lanes):
            trees.append({"c": (tx, ty), "r": round(rr.uniform(2.6, 3.8), 1), "h": round(rr.uniform(7.0, 10.5), 1)})
        s, side = s + rr.uniform(13, 19), -side
    avenue = len(trees)
    while len(trees) < 110 + avenue and tries < 1600:
        tries += 1
        t, rr = rnd.uniform(0, 2 * math.pi), math.sqrt(rnd.random())
        tx, ty = rr * land_r(t) * 0.96 * math.sin(t), rr * land_r(t) * 0.96 * math.cos(t)
        if math.hypot(tx, ty) < 16:
            continue
        if any(_dist_to_path(tx, ty, ln["path"]) < 6.5 for ln in lanes) or _dist_to_path(tx, ty, road) < 6.0:
            continue
        if any(math.hypot(tx - h["c"][0], ty - h["c"][1]) < 8.5 for h in homes):
            continue
        if any(math.hypot(tx - s["c"][0], ty - s["c"][1]) < 17 for s in sites):
            continue
        if pond and math.hypot(tx - pond["c"][0], ty - pond["c"][1]) < 24:
            continue
        if temple and math.hypot(tx - temple["c"][0], ty - temple["c"][1]) < 9:
            continue
        if any(math.hypot(tx - o["c"][0], ty - o["c"][1]) < 5 for o in trees):
            continue
        trees.append({"c": (tx, ty), "r": round(rnd.uniform(2.0, 3.6), 1), "h": round(rnd.uniform(5.0, 9.5), 1)})

    return {"lanes": lanes, "homes": homes, "sites": sites, "temple": temple, "pond": pond, "land": land, "fields": fields,
            "trees": trees, "reach": reach, "road": road, "plaza": plaza, "tank": {"c": (0.0, 0.0), "r": 4.3, "leg_h": 10.0, "bowl_h": 4.6},
            "pump": {"c": (-17.0, -13.0), "poly": _rect(-17.0, -13.0, 4.8, 4.8, 0.3), "h": 3.0, "bore": (-22.5, -17.5)}}


def to_geo(layout: dict, lat0: float, lon0: float) -> dict:
    """Convert a layout to [lon, lat] coordinates ready for GeoJSON."""
    k_lat = 1 / 111_320.0
    k_lon = 1 / (111_320.0 * math.cos(math.radians(lat0)))

    def pt(p):
        return [round(lon0 + p[0] * k_lon, 7), round(lat0 + p[1] * k_lat, 7)]

    def ring(poly):
        return [pt(p) for p in poly] + [pt(poly[0])]

    t = layout["tank"]
    legs = [_rect(t["c"][0] + dx, t["c"][1] + dy, 0.7, 0.7, 0.0) for dx, dy in ((-2.6, -2.6), (2.6, -2.6), (2.6, 2.6), (-2.6, 2.6))]
    reach = layout["reach"]
    tp = layout["temple"]
    shadows = ([_shadow(h["poly"], h["h"]) for h in layout["homes"]] + [_shadow(s["poly"], s["h"]) for s in layout["sites"]]
               + ([_shadow(tp["poly"], tp["h"]), _shadow(tp["spire"], tp["spire_h"])] if tp else [])
               + [_shadow(layout["pump"]["poly"], layout["pump"]["h"])]
               + [_shadow(_ngon(tr["c"][0], tr["c"][1], tr["r"], 8), tr["h"] * 0.8, 1.9) for tr in layout["trees"]]
               + [_shadow(_ngon(*t["c"], t["r"], 14), t["leg_h"] + t["bowl_h"], t["leg_h"])] + [_shadow(leg, t["leg_h"]) for leg in legs])
    xs = [h["c"][0] for h in layout["homes"]] + [0.0]
    ys = [h["c"][1] for h in layout["homes"]] + [0.0]
    return {
        "center": pt(((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)),
        "bounds": [pt((-reach, -reach)), pt((reach, reach))],
        "view": [pt((min(xs) - 28, min(ys) - 28)), pt((max(xs) + 28, max(ys) + 28))],  # the built-up area: what the camera frames
        "land": ring(layout["land"]),
        "fields": [{"ring": ring(f["poly"]), "crop": f["crop"]} for f in layout["fields"]],
        "pond": ring(layout["pond"]["poly"]) if layout["pond"] else None,
        "road": [pt(p) for p in layout["road"]],
        "plaza": ring(layout["plaza"]),
        "shadows": [ring(sh) for sh in shadows],
        "temple": ({"ring": ring(layout["temple"]["poly"]), "h": layout["temple"]["h"], "spire": ring(layout["temple"]["spire"]),
                    "spire_h": layout["temple"]["spire_h"], "c": pt(layout["temple"]["c"])} if layout["temple"] else None),
        "lanes": [{"idx": ln["idx"], "id": ln["id"], "name": ln["name"], "n": ln["n"], "path": [pt(p) for p in ln["path"]],
                   "lead_frac": round(ln["lead"] / ln["length"], 4),
                   "house_frac": round((ln["lead"] + ln["n"] * ln["spacing"]) / ln["length"], 4)} for ln in layout["lanes"]],
        "homes": [{"i": h["i"], "id": h["id"], "label": h["label"], "branch_idx": h["branch_idx"], "pos": h["pos"], "lane": h["lane"],
                   "metered": h["metered"], "h": h["h"], "c": pt(h["c"]), "join": pt(h["join"]), "ring": ring(h["poly"]),
                   "mast": ring(_rect(h["poly"][2][0] * 0.82 + h["c"][0] * 0.18, h["poly"][2][1] * 0.82 + h["c"][1] * 0.18, 0.55, 0.55, 0.0))}
                  for h in layout["homes"]],
        "sites": [{"id": s["id"], "name": s["name"], "kind": s["kind"], "branch_idx": s["branch_idx"], "h": s["h"], "c": pt(s["c"]),
                   "join": pt(s["join"]), "ring": ring(s["poly"])} for s in layout["sites"]],
        "trees": [{"canopy": ring(_ngon(tr["c"][0], tr["c"][1], tr["r"], 8)), "trunk": ring(_ngon(tr["c"][0], tr["c"][1], 0.4, 6)),
                   "h": tr["h"]} for tr in layout["trees"]],
        "tank": {"c": pt(t["c"]), "bowl": ring(_ngon(*t["c"], t["r"], 20)), "water": ring(_ngon(*t["c"], t["r"] - 0.45, 20)),
                 "legs": [ring(leg) for leg in legs], "leg_h": t["leg_h"], "bowl_h": t["bowl_h"]},
        "pump": {"ring": ring(layout["pump"]["poly"]), "h": layout["pump"]["h"], "c": pt(layout["pump"]["c"]), "bore": pt(layout["pump"]["bore"]),
                 "pipe": [pt(layout["pump"]["bore"]), pt(layout["pump"]["c"]), pt((0, 0))]},
    }

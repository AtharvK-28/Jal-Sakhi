import { useEffect, useMemo, useRef, useState } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { Box, CloudOff, Download, Focus, LocateFixed, MapPinned, Orbit, Square } from "lucide-react";
import { download } from "../lib/api";
import { useLive, usePoll, useScopeVillages } from "../lib/live";
import { StatusBar, toast } from "../components/ui";
import { HouseholdDrawer } from "./Households";
import { SUPPLY, scoreColor } from "../lib/format";

// =================================================================================== base map
// Tiles come from a third-party server, so the map must survive that server being slow, blocked or
// unreachable. Order: the chosen provider, then the others, then no tiles at all (the village is
// drawn from our own vector data either way). All providers are keyless. Tile servers require a
// Referer: index.html and the backend both set a referrer policy that sends the page's origin.
type Tiles = "sat" | "osm" | "esri";
type BaseKey = Tiles | "none";
type Provider = { label: string; url: string; names?: string; probe: (x: number, y: number) => string; maxzoom: number; attribution: string };
const ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services";
const PROVIDERS: Record<Tiles, Provider> = {
  sat: {
    label: "Satellite", maxzoom: 17, // imagery exists to 18 at the demo villages; one level of margin, then upscale
    url: `${ESRI}/World_Imagery/MapServer/tile/{z}/{y}/{x}`,
    names: `${ESRI}/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}`, // place names over the imagery, wide views only
    probe: (x, y) => `${ESRI}/World_Imagery/MapServer/tile/8/${y}/${x}`,
    attribution: "Imagery &copy; Esri, Maxar, Earthstar Geographics",
  },
  osm: {
    label: "Streets", maxzoom: 19,
    url: "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
    probe: (x, y) => `https://tile.openstreetmap.org/8/${x}/${y}.png`,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap</a> contributors',
  },
  esri: {
    label: "Terrain", maxzoom: 16, // detailed tiles are not published everywhere in rural areas: stop at 16 and upscale
    url: `${ESRI}/World_Topo_Map/MapServer/tile/{z}/{y}/{x}`,
    probe: (x, y) => `${ESRI}/World_Topo_Map/MapServer/tile/8/${y}/${x}`,
    attribution: "Tiles &copy; Esri and its data providers",
  },
};
const ORDER: Tiles[] = ["sat", "osm", "esri"];

async function grab(url: string): Promise<Uint8Array | null> {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), 6000);
  try {
    // no explicit referrerPolicy: the probe must behave exactly like the map's own tile requests
    const r = await fetch(url, { mode: "cors", cache: "no-store", signal: ctl.signal });
    if (!r.ok || !(r.headers.get("content-type") || "").startsWith("image/")) return null;
    return new Uint8Array(await r.arrayBuffer());
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

/** Is this provider serving real map tiles right now?
 *  Tile servers that refuse a client (usage-policy block, missing API key) still answer HTTP 200 with a
 *  placeholder picture, so a status check is not enough. Every placeholder is the same picture, while two
 *  real tiles of different places never are: fetch two neighbouring land tiles and require them to differ. */
async function reachable(pr: Provider): Promise<boolean> {
  const [a, b] = await Promise.all([grab(pr.probe(180, 114)), grab(pr.probe(180, 115))]); // Pune and Satara
  if (!a || !b) return false;
  return !(a.length === b.length && a.every((v, i) => v === b[i]));
}

// ================================================================================== map style
const isDark = () => document.documentElement.getAttribute("data-theme") === "dark";
const palette = (dark: boolean) => dark
  ? { bg: "#071a2c", grat: "#17395a", land: "#22343f", fieldOpacity: 0.5, lane: "#5b6f80", laneEdge: "#33475a", road: "#3d4b57", roadEdge: "#26323c", shadow: "#000000", shade: 0.34, sky: "#0b2a47", horizon: "#123a5c" }
  : { bg: "#dcecf4", grat: "#b5d0e0", land: "#e2dac0", fieldOpacity: 0.96, lane: "#f3ead4", laneEdge: "#c9b792", road: "#9a9c98", roadEdge: "#7c7e7a", shadow: "#12303f", shade: 0.25, sky: "#bfe3f7", horizon: "#e8f5fb" };
const STATE: any = ["coalesce", ["feature-state", "s"], "idle"];
const shades = (c: Record<string, string>): any => ["match", STATE, "ok", c.ok, "low", c.low, "dry", c.dry, "unknown", c.unknown, c.idle];
// a roof is three stacked slabs: eaves darkest, ridge lightest, so it reads as pitched from any angle
const ROOF: any = ["match", ["get", "t"],
  1, shades({ ok: "#1e96d3", low: "#d68a08", dry: "#c63a3f", unknown: "#7d8ca0", idle: "#b0764f" }),
  3, shades({ ok: "#74cff8", low: "#fac45f", dry: "#f08387", unknown: "#b8c4d2", idle: "#ddae90" }),
  shades({ ok: "#2fb5f2", low: "#f59e0b", dry: "#e5484d", unknown: "#94a3b8", idle: "#c98a66" })];
const PIPE: any = ["match", ["coalesce", ["feature-state", "st"], "idle"], "ok", "#19a7e0", "low", "#f59e0b", "leak", "#dc2626", "interrupted", "#7f1d1d", "anomaly", "#7c5cf0", "unknown", "#8a9fb2", "#9db4c4"];
const WALLS = ["#f6efe2", "#f1e2c6", "#ebe6da", "#f7e6d2", "#e6edf2", "#f3ddcf", "#ecefdc"];
const GREENS = [["#4f9a55", "#6cb56c"], ["#5aa35a", "#7abf72"], ["#437f4d", "#5d9d64"]];
const metres = (w: number): any => ["interpolate", ["exponential", 2], ["zoom"], 12, w * 0.0276, 22, w * 28.26]; // line width in ground metres at this latitude
const px = (a: number, b: number, c: number): any => ["interpolate", ["linear"], ["zoom"], 13, a, 16, b, 19, c];
const fade = (color: string): any => ["interpolate", ["linear"], ["line-progress"], 0, color, 0.72, color, 1, "rgba(0,0,0,0)"];
const ROUND: any = { "line-cap": "round", "line-join": "round" };
const FEATHER = [[1.2, 0.07], [1.17, 0.08], [1.14, 0.1], [1.11, 0.12], [1.08, 0.15], [1.055, 0.2], [1.03, 0.3], [1, 0.97]]; // outline scale, opacity (they stack)
const TALL = 1.55; // vertical exaggeration for buildings: single-storey houses are hard to read from a tilted camera otherwise
const PITCH = 58;
const BEARINGS = [-22, -60, -50, -40, -30, -10, 0, 10, 20, 30, 40, 50, 60]; // first is preferred; the rest are tried for a better fit
const SOURCES = ["grat", "land", "fields", "pond", "road", "road-mark", "plaza", "lanes", "paths", "shadows", "services", "pipes", "leak", "trunks", "trees", "homes", "roofs", "masts", "misc", "beacons", "tank-legs", "tank-water", "tank-bowl"];
const GROUPS: Record<string, string[]> = {
  homes: ["walls", "roofs", "masts"],
  pipes: ["pipes-case", "pipes", "pipe-flow", "services", "leak"],
  rep: ["beacons"],
  land: ["fields", "pond", "trunks", "trees"],
};
// dash patterns that, played in order, make a dashed line appear to flow along its length
const DASH = [[0, 4, 3], [0.5, 4, 2.5], [1, 4, 2], [1.5, 4, 1.5], [2, 4, 1], [2.5, 4, 0.5], [3, 4, 0], [0, 0.5, 3, 3.5], [0, 1, 3, 3], [0, 1.5, 3, 2.5], [0, 2, 3, 2], [0, 2.5, 3, 1.5], [0, 3, 3, 1], [0, 3.5, 3, 0.5]];

// ------------------------------------------------------------------------------------ geometry
const K = 111_320; // metres per degree of latitude
const lonK = (lat: number) => K * Math.cos((lat * Math.PI) / 180);
const fc = (features: any[]): any => ({ type: "FeatureCollection", features });
const poly = (ring: number[][], properties: any = {}, id?: number): any => ({ type: "Feature", id, properties, geometry: { type: "Polygon", coordinates: [ring] } });
const line = (coordinates: number[][], properties: any = {}, id?: number): any => ({ type: "Feature", id, properties, geometry: { type: "LineString", coordinates } });
const middle = (ring: number[][]) => { const p = ring.slice(0, -1); return [p.reduce((a, q) => a + q[0], 0) / p.length, p.reduce((a, q) => a + q[1], 0) / p.length]; };
const grow = (ring: number[][], k: number, c = middle(ring)) => ring.map((p) => [c[0] + (p[0] - c[0]) * k, c[1] + (p[1] - c[1]) * k]);
function ngon(c: number[], r: number, n: number, rot = 0): number[][] {
  const pts = Array.from({ length: n }, (_, i) => { const a = rot + (2 * Math.PI * i) / n; return [c[0] + (r * Math.sin(a)) / lonK(c[1]), c[1] + (r * Math.cos(a)) / K]; });
  return [...pts, pts[0]];
}
/** A rectangular footprint scaled by a along its first side and b along the other, about its centre. */
function rect(ring: number[][], a: number, b: number): number[][] {
  const [p0, p1, p2, p3] = ring;
  const c = [(p0[0] + p2[0]) / 2, (p0[1] + p2[1]) / 2];
  const u = [(p1[0] - p0[0]) / 2, (p1[1] - p0[1]) / 2], v = [(p3[0] - p0[0]) / 2, (p3[1] - p0[1]) / 2];
  const at = (sx: number, sy: number) => [c[0] + sx * a * u[0] + sy * b * v[0], c[1] + sx * a * u[1] + sy * b * v[1]];
  const out = [at(-1, -1), at(1, -1), at(1, 1), at(-1, 1)];
  return [...out, out[0]];
}
function sides(ring: number[][]): [number, number] {
  const k = lonK(ring[0][1]);
  const len = (p: number[], q: number[]) => Math.hypot((q[0] - p[0]) * k, (q[1] - p[1]) * K);
  return [len(ring[0], ring[1]), len(ring[0], ring[3])];
}

/** A house as extrusions: walls, then a stepped gable (single storey) or a flat slab with a stair cabin (two storeys). */
function house(h: any) {
  const H = h.h * TALL, [w, d] = sides(h.ring), props = { id: h.id, label: h.label, lane: h.lane };
  const slab = (t: number, a: number, b: number, lo: number, hi: number) => poly(rect(h.ring, a, b), { ...props, t, b: lo, h: hi }, t * 1000 + h.i);
  const walls = (top: number) => poly(h.ring, { ...props, h: top, wall: WALLS[h.i % WALLS.length] }, h.i);
  if (h.h > 5) return { top: H + 1.5, walls: walls(H - 0.55), roofs: [slab(1, 1.05, 1.05, H - 0.55, H), slab(3, 0.36, 0.36, H, H + 1.5)] };
  const rise = Math.min(3, Math.max(1.7, Math.min(w, d) * 0.34)), eave = H - rise, ridge = w >= d; // the ridge runs along the longer side
  const tier = (t: number, along: number, across: number, lo: number, hi: number) => slab(t, ridge ? along : across, ridge ? across : along, lo, hi);
  return { top: H, walls: walls(eave), roofs: [tier(1, 1.05, 1.14, eave, eave + rise * 0.34), tier(2, 1.02, 0.7, eave + rise * 0.34, eave + rise * 0.7), tier(3, 1, 0.3, eave + rise * 0.7, H)] };
}

/** Part of a path between two fractions of its length. */
function slice(path: number[][], f0: number, f1: number): number[][] {
  const k = Math.cos((path[0][1] * Math.PI) / 180);
  const d = (a: number[], b: number[]) => Math.hypot((b[0] - a[0]) * k, b[1] - a[1]);
  const cum = [0];
  for (let i = 1; i < path.length; i++) cum.push(cum[i - 1] + d(path[i - 1], path[i]));
  const at = (s: number) => {
    let i = 1;
    while (i < cum.length - 1 && cum[i] < s) i++;
    const t = (s - cum[i - 1]) / (cum[i] - cum[i - 1] || 1);
    return [path[i - 1][0] + (path[i][0] - path[i - 1][0]) * t, path[i - 1][1] + (path[i][1] - path[i - 1][1]) * t];
  };
  const s0 = f0 * cum[cum.length - 1], s1 = f1 * cum[cum.length - 1];
  return [at(s0), ...path.filter((_p, i) => cum[i] > s0 && cum[i] < s1), at(s1)];
}

/** The camera that fills the canvas with these ground points at a given tilt.
 *  MapLibre's own cameraForBounds only solves the top-down case, which leaves a tilted village small in a
 *  wide window. Same pinhole model as the map (the eye sits 1.5 canvas-heights from the point it looks at):
 *  for each candidate bearing and look-at depth, search for the largest zoom that keeps every point inside. */
function frame(m: maplibregl.Map, pts: number[][], pitch: number, bearings: number[]) {
  const box = m.getContainer(), W = box.clientWidth, H = box.clientHeight;
  const lon0 = pts.reduce((a, p) => a + p[0], 0) / pts.length, lat0 = pts.reduce((a, p) => a + p[1], 0) / pts.length;
  const kx = lonK(lat0), phi = (pitch * Math.PI) / 180, eye = 1.5 * H;
  const pad = { l: 62, r: 84, t: pitch ? 92 : 56, b: 66 }; // room for the zoom buttons and for labels standing above the far houses
  const perMetre = (z: number) => (512 * 2 ** z) / (40_075_016.686 * Math.cos((lat0 * Math.PI) / 180));
  let best = { zoom: 15, bearing: bearings[0], center: [lon0, lat0] as [number, number], score: -1e9 };
  bearings.forEach((bearing, n) => {
    const th = (bearing * Math.PI) / 180;
    const loc = pts.map(([lon, lat]) => { const e = (lon - lon0) * kx, nn = (lat - lat0) * K; return [e * Math.cos(th) - nn * Math.sin(th), e * Math.sin(th) + nn * Math.cos(th)]; });
    const xs = loc.map((p) => p[0]), ys = loc.map((p) => p[1]);
    const cx = (Math.min(...xs) + Math.max(...xs)) / 2, y0 = Math.min(...ys), y1 = Math.max(...ys);
    for (let k = 0; k <= 8; k++) {
      const cy = y0 + (y1 - y0) * (0.3 + 0.05 * k);
      const fits = (z: number) => {
        const s = perMetre(z);
        return loc.every(([x, y]) => {
          const yy = (y - cy) * s, depth = eye + yy * Math.sin(phi);
          if (depth < eye * 0.25) return false;
          const sx = ((x - cx) * s * eye) / depth, sy = (yy * Math.cos(phi) * eye) / depth;
          return sx >= -(W / 2 - pad.l) && sx <= W / 2 - pad.r && sy <= H / 2 - pad.t && sy >= -(H / 2 - pad.b);
        });
      };
      let lo = 13, hi = 19;
      for (let i = 0; i < 18; i++) { const mid = (lo + hi) / 2; if (fits(mid)) lo = mid; else hi = mid; }
      const score = lo - (n ? 0.12 : 0) - Math.abs(bearing - bearings[0]) * 0.002; // only leave the preferred bearing for a clearly bigger picture
      if (score > best.score) {
        const e = cx * Math.cos(th) + cy * Math.sin(th), nn = -cx * Math.sin(th) + cy * Math.cos(th);
        best = { zoom: Math.min(18.7, lo), bearing, center: [lon0 + e / kx, lat0 + nn / K], score };
      }
    }
  });
  return best;
}

function addLayers(m: maplibregl.Map, dark: boolean) {
  const P = palette(dark);
  SOURCES.forEach((s) => m.addSource(s, { type: "geojson", data: fc([]), lineMetrics: s === "road" }));
  const ex = (id: string, source: string, paint: any) => m.addLayer({ id, type: "fill-extrusion", source, paint });
  m.addLayer({ id: "grat", type: "line", source: "grat", layout: { visibility: "none" }, paint: { "line-color": P.grat, "line-width": 1 } });
  m.addLayer({ id: "land", type: "fill", source: "land", paint: { "fill-color": P.land, "fill-opacity": ["get", "o"], "fill-antialias": false } });
  m.addLayer({ id: "fields", type: "fill", source: "fields", paint: { "fill-color": ["get", "crop"], "fill-opacity": P.fieldOpacity, "fill-outline-color": "rgba(90,110,70,0.45)" } });
  m.addLayer({ id: "pond", type: "fill", source: "pond", paint: { "fill-color": "#5fb8e6", "fill-outline-color": "#2f8fc0" } });
  m.addLayer({ id: "road-case", type: "line", source: "road", layout: ROUND, paint: { "line-gradient": fade(P.roadEdge), "line-width": metres(8.2) } });
  m.addLayer({ id: "road", type: "line", source: "road", layout: ROUND, paint: { "line-gradient": fade(P.road), "line-width": metres(6.6) } });
  m.addLayer({ id: "road-mark", type: "line", source: "road-mark", paint: { "line-color": "#ffffff", "line-opacity": 0.8, "line-width": metres(0.3), "line-dasharray": [14, 12] } });
  m.addLayer({ id: "lanes-case", type: "line", source: "lanes", layout: ROUND, paint: { "line-color": P.laneEdge, "line-width": metres(6.6) } });
  m.addLayer({ id: "plaza-case", type: "line", source: "plaza", paint: { "line-color": P.laneEdge, "line-width": metres(1.6) } });
  m.addLayer({ id: "lanes", type: "line", source: "lanes", layout: ROUND, paint: { "line-color": P.lane, "line-width": metres(5) } });
  m.addLayer({ id: "plaza", type: "fill", source: "plaza", paint: { "fill-color": P.lane } });
  m.addLayer({ id: "paths", type: "line", source: "paths", layout: ROUND, paint: { "line-color": P.laneEdge, "line-width": metres(1.8) } });
  m.addLayer({ id: "shadows", type: "fill", source: "shadows", paint: { "fill-color": P.shadow, "fill-opacity": P.shade, "fill-antialias": false } });
  m.addLayer({ id: "services", type: "line", source: "services", paint: { "line-color": "#7cc7ea", "line-width": metres(0.45), "line-opacity": 0.85 } });
  m.addLayer({ id: "pipes-case", type: "line", source: "pipes", layout: ROUND, paint: { "line-color": "#ffffff", "line-width": px(4, 6.5, 10), "line-opacity": 0.9 } });
  m.addLayer({ id: "pipes", type: "line", source: "pipes", layout: ROUND, paint: { "line-color": PIPE, "line-width": px(2.2, 3.8, 6) } });
  m.addLayer({ id: "pipe-flow", type: "line", source: "pipes", filter: ["in", ["get", "idx"], ["literal", []]], paint: { "line-color": "#ffffff", "line-width": px(1, 1.8, 3), "line-dasharray": DASH[0] } });
  m.addLayer({ id: "leak", type: "line", source: "leak", layout: ROUND, paint: { "line-color": ["get", "color"], "line-width": px(9, 15, 22), "line-opacity": 0.4 } });
  // every extrusion is fully opaque except the tank bowl (drawn last): opaque layers share one depth buffer,
  // so a tree in front of a house hides it and not the other way round
  ex("trunks", "trunks", { "fill-extrusion-color": "#7a5a3a", "fill-extrusion-height": 2.3 });
  ex("trees", "trees", { "fill-extrusion-color": ["get", "color"], "fill-extrusion-base": ["get", "b"], "fill-extrusion-height": ["get", "h"] });
  ex("walls", "homes", { "fill-extrusion-color": ["get", "wall"], "fill-extrusion-height": ["get", "h"] });
  ex("roofs", "roofs", { "fill-extrusion-color": ROOF, "fill-extrusion-base": ["get", "b"], "fill-extrusion-height": ["get", "h"] });
  ex("masts", "masts", { "fill-extrusion-color": "#0a6fb8", "fill-extrusion-base": ["get", "b"], "fill-extrusion-height": ["get", "h"] });
  ex("misc", "misc", { "fill-extrusion-color": ["get", "color"], "fill-extrusion-base": ["get", "b"], "fill-extrusion-height": ["get", "h"] });
  ex("beacons", "beacons", { "fill-extrusion-color": ["get", "color"], "fill-extrusion-base": ["get", "b"], "fill-extrusion-height": ["get", "h"] });
  ex("tank-legs", "tank-legs", { "fill-extrusion-color": "#8fa1af", "fill-extrusion-height": ["get", "h"] });
  ex("tank-water", "tank-water", { "fill-extrusion-color": "#1aa3e0", "fill-extrusion-base": ["get", "b"], "fill-extrusion-height": ["get", "h"] });
  ex("tank-bowl", "tank-bowl", { "fill-extrusion-color": "#e6eff5", "fill-extrusion-base": ["get", "b"], "fill-extrusion-height": ["get", "h"], "fill-extrusion-opacity": 0.5 });
  // lit from the south-west and fixed to the ground, to agree with the shadows the layout casts to the north-east
  m.setLight({ anchor: "map", color: "#ffffff", intensity: 0.46, position: [1.5, 218, 48] });
  // a 0.25 degree graticule, shown only when there are no background tiles
  const g: any[] = [];
  for (let lat = 15; lat <= 21.001; lat += 0.25) g.push(line([[71.5, lat], [76.5, lat]]));
  for (let lon = 71.5; lon <= 76.501; lon += 0.25) g.push(line([[lon, 15], [lon, 21]]));
  (m.getSource("grat") as maplibregl.GeoJSONSource).setData(fc(g));
}

const setData = (m: maplibregl.Map, id: string, data: any) => (m.getSource(id) as maplibregl.GeoJSONSource | undefined)?.setData(data);
const label = (html: string, cls = "") => { const el = document.createElement("div"); el.className = `m3-label ${cls}`; el.innerHTML = html; return el; };
type Tag = { el: HTMLElement; pr: number };

/** GIS view on MapLibre GL: village markers at state / district / block level, and a tiltable 3D village
 *  (house roofs coloured by live tap status, pipes, tank, fields) once you drop into one. */
export function MapPage() {
  const { scope, setScope, village, focus, snap, clock, stale } = useLive();
  const villages = useScopeVillages();
  const el = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const popup = useRef<maplibregl.Popup | null>(null);
  const marks = useRef<{ v: maplibregl.Marker[]; lab: maplibregl.Marker[]; hot: maplibregl.Marker[]; lanes: HTMLElement[]; tank: HTMLElement | null; fixed: Tag[]; calls: Tag[]; tops: Record<string, number> }>(
    { v: [], lab: [], hot: [], lanes: [], tank: null, fixed: [], calls: [], tops: {} });
  const live = useRef<any>({});
  const tidy = useRef<() => void>(() => {});
  const orbitRef = useRef(false);
  const [ready, setReady] = useState(false);
  const [failed, setFailed] = useState("");
  const [base, setBaseRaw] = useState<BaseKey>(() => {
    const saved = localStorage.getItem("jalsakhi.base");
    return saved === "osm" || saved === "esri" || saved === "none" ? saved : "sat";
  });
  const [active, setActive] = useState<BaseKey | "checking">("checking");
  const [dark, setDark] = useState(isDark);
  const [three, setThree] = useState(true);
  const [orbit, setOrbit] = useState(false);
  const [show, setShow] = useState({ homes: true, pipes: true, rep: true, land: true });
  const [sel, setSel] = useState<string | null>(null);
  const inVillage = scope.level === "village";
  const { data: geoRaw, error: geoErr, reload: reloadGeo } = usePoll<any>(inVillage ? `/api/villages/${village}/geo` : null, 0, [village, inVillage]);
  // A server from before the current map answers this route with an older payload: check the shape.
  const geoOk = !!geoRaw && Array.isArray(geoRaw.homes) && Array.isArray(geoRaw.lanes) && Array.isArray(geoRaw.shadows) && !!geoRaw.tank && !!geoRaw.road;
  const geo = inVillage && geoOk ? geoRaw : null;
  const geoFail = !inVillage || geo ? null : geoErr || (geoRaw ? "the server sent an older map format" : null);
  const setBase = (b: BaseKey) => { localStorage.setItem("jalsakhi.base", b); setBaseRaw(b); };
  orbitRef.current = orbit && !!geo;

  // keep asking while the layout is missing, so the village appears by itself once the server can serve it
  useEffect(() => {
    if (!geoFail) return;
    const t = setInterval(reloadGeo, 5000);
    return () => clearInterval(t);
  }, [geoFail, reloadGeo]);

  // ---------------------------------------------------------------------------------- create
  useEffect(() => {
    if (!el.current || map.current) return;
    let m: maplibregl.Map;
    try {
      m = new maplibregl.Map({
        container: el.current, center: [73.65, 18.45], zoom: 7.4, maxPitch: 78, attributionControl: false,
        style: { version: 8, sources: {}, layers: [{ id: "bg", type: "background", paint: { "background-color": palette(isDark()).bg } }] },
      });
    } catch (e: any) {
      setFailed(e?.message || "WebGL is not available in this browser");
      return;
    }
    m.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), "top-left");
    m.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-left");
    m.addControl(new maplibregl.AttributionControl({ compact: true }), "bottom-right");
    popup.current = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 14, maxWidth: "280px" });

    // Labels are HTML, so nothing stops two of them landing on the same pixels as the camera moves.
    // Each frame the map moved: place them by priority and hide any that would cover one already placed.
    let queued = 0;
    const place = () => {
      queued = 0;
      const taken: DOMRect[] = [];
      [...marks.current.calls, ...marks.current.fixed].sort((a, b) => b.pr - a.pr).forEach(({ el: tag }) => {
        const r = (tag.querySelector(".m3-label") || tag).getBoundingClientRect();
        const hit = taken.some((q) => r.left < q.right + 5 && r.right > q.left - 5 && r.top < q.bottom + 3 && r.bottom > q.top - 3);
        tag.classList.toggle("hid", hit);
        if (!hit) taken.push(r);
      });
    };
    tidy.current = () => { if (!queued) queued = requestAnimationFrame(place); };
    m.on("move", tidy.current);
    m.on("moveend", tidy.current);

    m.on("load", () => {
      addLayers(m, isDark());
      const hover = (layer: string, html: (f: any) => string | null) => {
        m.on("mousemove", layer, (e) => {
          const h = e.features?.[0] && html(e.features[0]);
          if (!h) return;
          m.getCanvas().style.cursor = "pointer";
          popup.current!.setLngLat(e.lngLat).setHTML(h).addTo(m);
        });
        m.on("mouseleave", layer, () => { m.getCanvas().style.cursor = ""; popup.current!.remove(); });
      };
      const home = (f: any) => {
        const h = live.current.byId?.[f.properties.id];
        const st = h?.s || "idle";
        return `<b>${f.properties.label}</b> · ${f.properties.lane}<br>${SUPPLY[st].label}${h && st !== "idle" && st !== "unknown" ? ` · ${h.p.toFixed(2)} bar` : ""}<br>`
          + (h?.m ? "Metered home (smart tap node)" : st === "unknown" ? "Cannot be estimated: nearby sensors are silent" : st === "idle" ? "Outside the supply window" : `Estimated from nearby sensors · ${Math.round((h?.c || 0) * 100)}% confidence`)
          + `<br>${h ? Math.round(h.v) : 0} L per person today${h?.r ? "<br><b>Open citizen report</b>" : ""}<br><i>Click for details</i>`;
      };
      hover("roofs", home);
      hover("walls", home);
      hover("misc", (f) => (f.properties.name ? `<b>${f.properties.name}</b>${f.properties.site ? "<br>Institutional tap connection" : ""}` : null));
      hover("pipes", (f) => {
        const b = live.current.focus?.branches?.[f.properties.idx];
        if (!b) return f.properties.idx === 99 ? "<b>Rising main</b><br>Borewell to tank" : null;
        const txt: Record<string, string> = { ok: "supplying normally", idle: "supply off (scheduled)", leak: "suspected leak", low: "low pressure", interrupted: "no supply", anomaly: "abnormal pattern (AI)", unknown: "entry sensor silent" };
        return `<b>${b.name}</b> · ${b.n} homes<br>${txt[b.status] || b.status}${b.fresh_in && b.flow != null && b.status !== "idle" ? `<br>${b.p_in?.toFixed(2)} bar at entry · ${Math.round(b.flow)} L/min` : ""}`;
      });
      const pick = (e: any) => { const f = e.features?.[0]; if (f) setSel(f.properties.id); };
      m.on("click", "roofs", pick);
      m.on("click", "walls", pick);
      m.on("dragstart", () => setOrbit(false));
      setReady(true);
    });
    map.current = m;
    const obs = new MutationObserver(() => setDark(isDark()));
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => { obs.disconnect(); cancelAnimationFrame(queued); m.remove(); map.current = null; setReady(false); };
  }, []);

  // ------------------------------------------------------------------------------ background
  useEffect(() => {
    const m = map.current;
    if (!m || !ready) return;
    let cancelled = false;
    const clear = () => ["base-names", "base"].forEach((id) => { if (m.getLayer(id)) m.removeLayer(id); if (m.getSource(id)) m.removeSource(id); });
    clear();
    if (base === "none") { setActive("none"); return; }
    setActive("checking");
    (async () => {
      for (const k of [base, ...ORDER.filter((x) => x !== base)]) {
        const pr = PROVIDERS[k];
        const ok = await reachable(pr);
        if (cancelled || !map.current) return;
        if (ok) {
          clear();
          m.addSource("base", { type: "raster", tiles: [pr.url], tileSize: 256, maxzoom: pr.maxzoom, attribution: pr.attribution });
          m.addLayer({ id: "base", type: "raster", source: "base" }, "grat");
          if (pr.names) {
            m.addSource("base-names", { type: "raster", tiles: [pr.names], tileSize: 256, maxzoom: 12 });
            m.addLayer({ id: "base-names", type: "raster", source: "base-names", maxzoom: 13.5 }, "grat");
          }
          setActive(k);
          return;
        }
      }
      setActive("none");
    })();
    return () => { cancelled = true; };
  }, [base, ready]);

  // ----------------------------------------------------------------------------------- theme
  useEffect(() => {
    const m = map.current;
    if (!m || !ready) return;
    const P = palette(dark);
    m.setPaintProperty("bg", "background-color", P.bg);
    m.setPaintProperty("grat", "line-color", P.grat);
    m.setPaintProperty("land", "fill-color", P.land);
    m.setPaintProperty("fields", "fill-opacity", P.fieldOpacity);
    m.setPaintProperty("lanes", "line-color", P.lane);
    m.setPaintProperty("plaza", "fill-color", P.lane);
    m.setPaintProperty("lanes-case", "line-color", P.laneEdge);
    m.setPaintProperty("plaza-case", "line-color", P.laneEdge);
    m.setPaintProperty("paths", "line-color", P.laneEdge);
    m.setPaintProperty("road", "line-gradient", fade(P.road));
    m.setPaintProperty("road-case", "line-gradient", fade(P.roadEdge));
    m.setPaintProperty("shadows", "fill-color", P.shadow);
    m.setPaintProperty("shadows", "fill-opacity", P.shade);
    m.setLayoutProperty("grat", "visibility", active === "none" ? "visible" : "none");
    if (m.getLayer("base")) {
      const sat = active === "sat"; // imagery is toned down a little so the drawn village stays the subject
      m.setPaintProperty("base", "raster-brightness-max", dark ? (sat ? 0.5 : 0.42) : 1);
      m.setPaintProperty("base", "raster-brightness-min", !dark && sat ? 0.1 : 0);
      m.setPaintProperty("base", "raster-saturation", dark ? (sat ? -0.45 : -0.6) : sat ? -0.22 : -0.12);
      m.setPaintProperty("base", "raster-contrast", dark ? 0.2 : sat ? -0.08 : 0);
    }
    (m as any).setSky?.({ "sky-color": P.sky, "horizon-color": P.horizon, "fog-color": P.horizon, "sky-horizon-blend": 0.6, "horizon-fog-blend": 0.7, "fog-ground-blend": 0.85 });
  }, [dark, ready, active]);

  // ------------------------------------------------------------------- static village layers
  useEffect(() => {
    const m = map.current;
    if (!m || !ready) return;
    marks.current.lab.forEach((x) => x.remove());
    Object.assign(marks.current, { lab: [], lanes: [], tank: null, fixed: [], tops: {} });
    if (!geo) {
      SOURCES.filter((s) => s !== "grat").forEach((s) => setData(m, s, fc([])));
      return;
    }
    const t = geo.tank;
    const built = geo.homes.map(house);
    geo.homes.forEach((h: any, i: number) => { marks.current.tops[h.id] = built[i].top; });
    // the village's ground fades out over wider, fainter copies of its outline instead of ending at a hard edge
    setData(m, "land", fc(FEATHER.map(([k, o]) => poly(grow(geo.land, k, t.c), { o }))));
    setData(m, "fields", fc(geo.fields.map((f: any) => poly(f.ring, { crop: f.crop }))));
    setData(m, "pond", fc(geo.pond ? [poly(geo.pond)] : []));
    setData(m, "road", fc([line(geo.road)]));
    setData(m, "road-mark", fc([line(slice(geo.road, 0.05, 0.66))])); // centre line stops before the road fades out
    setData(m, "plaza", fc([poly(geo.plaza)]));
    setData(m, "lanes", fc(geo.lanes.map((l: any) => line(l.path))));
    setData(m, "paths", fc(geo.sites.map((s: any) => line([s.join, s.c]))));
    setData(m, "shadows", fc(geo.shadows.map((r: any) => poly(r))));
    setData(m, "services", fc(geo.homes.map((h: any) => line([h.join, h.c]))));
    setData(m, "pipes", fc([...geo.lanes.map((l: any) => line(l.path, { idx: l.idx }, l.idx)), line(geo.pump.pipe, { idx: 99 }, 99)]));
    setData(m, "trunks", fc(geo.trees.map((tr: any) => poly(tr.trunk))));
    setData(m, "trees", fc(geo.trees.flatMap((tr: any, i: number) => { // two stacked canopies: broad below, narrower and lighter above
      const [low, high] = GREENS[i % GREENS.length];
      return [poly(tr.canopy, { color: low, b: 1.9, h: tr.h * 0.68 }), poly(grow(tr.canopy, 0.62), { color: high, b: tr.h * 0.68, h: tr.h })];
    })));
    setData(m, "homes", fc(built.map((b: any) => b.walls)));
    setData(m, "roofs", fc(built.flatMap((b: any) => b.roofs)));
    setData(m, "masts", fc(geo.homes.filter((h: any) => h.metered).map((h: any) => poly(h.mast, { b: built[h.i].walls.properties.h, h: h.h * TALL + 3.6 }))));
    const tp = geo.temple;
    setData(m, "misc", fc([
      poly(geo.pump.ring, { color: "#b6c2cb", b: 0, h: geo.pump.h * TALL, name: "Pump house and borewell" }),
      ...geo.sites.flatMap((s: any) => [ // pale walls under a purple roof slab
        poly(s.ring, { color: "#efeafb", b: 0, h: s.h * TALL - 0.8, name: s.name, site: true }),
        poly(rect(s.ring, 1.04, 1.06), { color: "#8b6cf2", b: s.h * TALL - 0.8, h: s.h * TALL, name: s.name, site: true }),
      ]),
      ...(tp ? [
        poly(tp.ring, { color: "#f2a33a", b: 0, h: tp.h * TALL, name: "Temple" }),
        poly(tp.spire, { color: "#e07b1a", b: tp.h * TALL, h: tp.spire_h * TALL, name: "Temple" }),
        poly(grow(tp.spire, 0.5), { color: "#f5b94e", b: tp.spire_h * TALL, h: tp.spire_h * TALL + 4.2, name: "Temple" }),
      ] : []),
    ]));
    setData(m, "tank-legs", fc(t.legs.map((r: any) => poly(r, { h: t.leg_h }))));
    setData(m, "tank-bowl", fc([poly(t.bowl, { b: t.leg_h, h: t.leg_h + t.bowl_h })]));
    const add = (tag: HTMLElement, at: number[], pr: number, z: number, anchor: any = "center") => {
      tag.style.zIndex = String(z);
      marks.current.lab.push(new maplibregl.Marker({ element: tag, anchor }).setLngLat(at as [number, number]).addTo(m));
      marks.current.fixed.push({ el: tag, pr });
    };
    geo.lanes.forEach((l: any) => {
      const tag = label(`${l.name}<small>${l.n} homes</small>`, "lane");
      marks.current.lanes[l.idx] = tag;
      add(tag, l.path[l.path.length - 1], 40 + l.n, 3); // at the far end of the lane, past its last house
    });
    marks.current.tank = label("Tank", "tank");
    add(marks.current.tank, t.c, 90, 4, "bottom");
    tidy.current();
  }, [geo, ready]);

  // --------------------------------------------------------------------------- live status
  useEffect(() => {
    const m = map.current;
    if (!m || !ready || !geo || !focus) return;
    const byId: Record<string, any> = Object.fromEntries(focus.households.map((h: any) => [h.id, h]));
    live.current = { byId, focus };
    geo.homes.forEach((h: any) => {
      const s = byId[h.id]?.s || "idle";
      m.setFeatureState({ source: "homes", id: h.i }, { s });
      [1, 2, 3].forEach((tier) => m.setFeatureState({ source: "roofs", id: tier * 1000 + h.i }, { s }));
    });
    geo.lanes.forEach((l: any) => m.setFeatureState({ source: "pipes", id: l.idx }, { st: focus.branches[l.idx]?.status || "idle" }));
    m.setFeatureState({ source: "pipes", id: 99 }, { st: focus.pump?.on ? "ok" : "idle" });
    const flowing = focus.branches.filter((b: any) => clock?.in_window && b.fresh_in && (b.p_in ?? 0) >= 0.15 && b.status !== "interrupted").map((b: any) => b.idx);
    if (focus.pump?.on) flowing.push(99);
    m.setFilter("pipe-flow", ["in", ["get", "idx"], ["literal", flowing]]);

    // citizen reports: a marker floating over each reporting home, and the count on its lane's label
    const reporting = geo.homes.filter((h: any) => byId[h.id]?.r);
    setData(m, "beacons", fc(reporting.flatMap((h: any) => {
      const top = marks.current.tops[h.id] ?? h.h * TALL;
      return [poly(ngon(h.c, 0.2, 4), { color: "#9a3412", b: top, h: top + 2.4 }), poly(ngon(h.c, 1.15, 4), { color: "#f97316", b: top + 2.4, h: top + 3.5 }),
        poly(ngon(h.c, 0.62, 4), { color: "#fff7ed", b: top + 3.5, h: top + 4.3 })];
    })));
    geo.lanes.forEach((l: any) => {
      const tag = marks.current.lanes[l.idx], n = reporting.filter((h: any) => h.branch_idx === l.idx).length;
      if (tag) tag.innerHTML = `${l.name}<small>${l.n} homes${n && show.rep ? ` · <b class="rep">${n} report${n > 1 ? "s" : ""}</b>` : ""}</small>`;
    });

    // unexplained pressure loss: highlight the pipe segment between the two bracketing sensors
    marks.current.hot.forEach((x) => x.remove());
    marks.current.hot = [];
    marks.current.calls = [];
    const segs: any[] = [];
    focus.branches.forEach((b: any) => {
      if (!b.segment || !["leak", "low", "anomaly"].includes(b.status)) return;
      const l = geo.lanes[b.idx];
      const f = (x: number) => l.lead_frac + x * (l.house_frac - l.lead_frac);
      const part = slice(l.path, f(b.segment.x0), f(b.segment.x1));
      const color = b.status === "leak" ? "#dc2626" : b.status === "low" ? "#f59e0b" : "#7c5cf0";
      segs.push(line(part, { color }));
      const text = b.status === "leak" ? "Suspected leak" : b.status === "low" ? "Pressure lost here" : "Abnormal loss (AI)";
      const call = document.createElement("div"); // the label stands on a stem, clear of the houses round the pipe
      call.className = `m3-call ${b.status}`;
      call.style.zIndex = "5";
      const near = b.segment.near ? `near ${b.segment.near}` : `${b.segment.from} to ${b.segment.to}`;
      call.append(label(`${text}<small>${l.name} · ${near}</small>`, `hot ${b.status}`), document.createElement("i"));
      const spot = b.segment.kind === "leak" && b.segment.x != null ? slice(l.path, f(b.segment.x), f(b.segment.x))[0] : part[Math.floor(part.length / 2)]; // the fitted leak position
      marks.current.hot.push(new maplibregl.Marker({ element: call, anchor: "bottom" }).setLngLat(spot as [number, number]).addTo(m));
      marks.current.calls.push({ el: call, pr: 100 });
    });
    setData(m, "leak", fc(segs));

    const t = geo.tank, lvl = focus.tank?.level_pct;
    setData(m, "tank-water", fc([poly(t.water, { b: t.leg_h + 0.35, h: t.leg_h + 0.35 + Math.max(0.05, (t.bowl_h - 0.8) * (lvl ?? 0) / 100) })]));
    if (marks.current.tank) marks.current.tank.innerHTML = `Tank ${lvl != null ? Math.round(lvl) + "%" : "?"}<small>${focus.pump?.on ? "pump running" : "pump idle"}</small>`;
    tidy.current();
  }, [focus, geo, ready, clock?.in_window, show.rep]);

  // ------------------------------------------------------------- village markers (wide view)
  useEffect(() => {
    const m = map.current;
    marks.current.v.forEach((x) => x.remove());
    marks.current.v = [];
    if (!m || !ready || geo) return; // the selected village keeps its marker until its houses are drawn
    villages.forEach((v: any) => {
      const size = 32 + Math.min(10, v.households / 14);
      const node = document.createElement("div");
      node.className = "m3-village";
      node.title = `${v.name} · ${v.block}: service score ${Math.round(v.score)}, ${v.households} taps, ${v.open} open incidents, ${v.complaints_open} reports`;
      node.innerHTML = `<div class="vmark ${v.critical || v.worst === "high" ? "alert" : ""}" style="width:${size}px;height:${size}px;background:${scoreColor(v.score)}">${Math.round(v.score)}</div><div class="vname">${v.name}</div>`;
      node.onclick = () => setScope({ level: "village", id: v.id });
      marks.current.v.push(new maplibregl.Marker({ element: node, anchor: "center" }).setLngLat([v.lon, v.lat]).addTo(m));
    });
  }, [villages, geo, ready, setScope]);

  // --------------------------------------------------------------------------------- camera
  const flyHome = (duration: number) => {
    const m = map.current;
    if (!m || !geo) return;
    // what must stay in view: every house corner, the institutions, the landmarks and the lane-end labels
    const pts = [...geo.homes.flatMap((h: any) => h.ring.slice(0, 4)), ...geo.sites.map((s: any) => s.c), geo.tank.c, geo.pump.c,
      ...(geo.temple ? [geo.temple.c] : []), ...geo.lanes.map((l: any) => l.path[l.path.length - 1])];
    const cam = frame(m, pts, three ? PITCH : 0, three ? BEARINGS : [0]);
    m.flyTo({ center: cam.center, zoom: cam.zoom, pitch: three ? PITCH : 0, bearing: cam.bearing, duration, essential: true });
  };
  const key = `${scope.level}:${scope.id}:${villages.length}:${geo ? 1 : 0}`;
  useEffect(() => {
    const m = map.current;
    if (!m || !ready) return;
    if (inVillage && geo) {
      flyHome(2600);
    } else if (inVillage && villages.length) { // layout not here yet: at least go to the village
      m.flyTo({ center: [villages[0].lon, villages[0].lat], zoom: 13, pitch: 0, bearing: 0, duration: 1600, essential: true });
    } else if (villages.length) {
      const b = new maplibregl.LngLatBounds();
      villages.forEach((v: any) => b.extend([v.lon, v.lat]));
      m.fitBounds(b, { padding: 110, maxZoom: 11, pitch: 0, bearing: 0, duration: 1600 });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, ready]);
  const first = useRef(true);
  useEffect(() => {
    if (first.current) { first.current = false; return; }
    flyHome(1100);
    if (!three) setOrbit(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [three]);

  // --------------------------------------------------------------------- layer visibility
  useEffect(() => {
    const m = map.current;
    if (!m || !ready) return;
    (Object.keys(GROUPS) as (keyof typeof show)[]).forEach((g) => GROUPS[g].forEach((id) => m.setLayoutProperty(id, "visibility", show[g] ? "visible" : "none")));
  }, [show, ready]);

  // ------------------------------------------------- animation: flowing pipes, pulse, orbit
  useEffect(() => {
    const m = map.current;
    if (!m || !ready) return;
    let raf = 0, last = 0, step = 0;
    const tick = (t: number) => {
      if (t - last > 75 && map.current) {
        last = t;
        step = (step + 1) % DASH.length;
        m.setPaintProperty("pipe-flow", "line-dasharray", DASH[step]);
        m.setPaintProperty("leak", "line-opacity", 0.28 + 0.24 * (1 + Math.sin(t / 240)) / 2);
      }
      if (orbitRef.current && map.current) m.setBearing((m.getBearing() + 0.09) % 360);
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [ready]);

  const counts = useMemo(() => {
    if (inVillage && focus) return { counts: focus.kpis.counts, total: focus.kpis.households };
    const c: any = { ok: 0, low: 0, dry: 0, unknown: 0, idle: 0 };
    villages.forEach((v: any) => Object.keys(c).forEach((k) => (c[k] += v.counts?.[k] || 0)));
    return { counts: c, total: villages.reduce((a: number, v: any) => a + v.households, 0) };
  }, [inVillage, focus, villages]);
  const fellBack = active !== "checking" && base !== "none" && active !== base;

  return (
    <div className="page">
      <div className="page-h">
        <div><h1>GIS map</h1><p>{inVillage
          ? `${focus?.name || ""}, house by house. Roof colour is the live status of each tap; dashes show water moving in the mains. Drag to pan, right-drag or Ctrl-drag to tilt and rotate. Demo geometry.`
          : "Service score by village. Markers pulse where a high-severity incident is open. Click a village to fly down to its lanes and taps."}</p></div>
        <div className="row wrap">
          {geo && <div className="seg" title="View">
            <button className={!three ? "on" : ""} onClick={() => setThree(false)}><Square size={13} style={{ verticalAlign: -2, marginRight: 5 }} />2D</button>
            <button className={three ? "on" : ""} onClick={() => setThree(true)}><Box size={13} style={{ verticalAlign: -2, marginRight: 5 }} />3D</button>
          </div>}
          {geo && <button className={`btn sm ${orbit ? "" : "ghost"}`} onClick={() => { if (!three) setThree(true); setOrbit(!orbit); }}><Orbit />{orbit ? "Stop orbit" : "Orbit"}</button>}
          {geo && <button className="btn ghost sm" title="Frame the whole village again" onClick={() => { setOrbit(false); flyHome(1100); }}><Focus />Reset view</button>}
          {geo && <div className="seg" title="Layers">{([["homes", "Homes"], ["pipes", "Pipes"], ["rep", "Reports"], ["land", "Fields"]] as const).map(([k, l]) => <button key={k} className={show[k] ? "on" : ""} onClick={() => setShow({ ...show, [k]: !show[k] })}>{l}</button>)}</div>}
          <div className="seg" title="Background map">
            {([...ORDER.map((k) => [k, PROVIDERS[k].label]), ["none", "None"]] as [BaseKey, string][]).map(([k, l]) => <button key={k} className={base === k ? "on" : ""} onClick={() => setBase(k)}>{l}</button>)}
          </div>
          {geo && <button className="btn ghost sm" title="Lanes, tap connections and assets as standard GeoJSON, for QGIS or a state GIS. Demo geometry."
            onClick={() => download(`/api/villages/${village}/export.geojson`, "scheme.geojson").then((n) => toast(`Saved ${n}`)).catch((e) => toast(e.message, true))}><Download />GeoJSON</button>}
          {inVillage && <button className="btn ghost sm" onClick={() => setScope({ level: "block", id: focus?.admin?.block_id })} disabled={!focus || !(snap?.summary || []).some((v: any) => v.id !== village)}><LocateFixed />Zoom out</button>}
        </div>
      </div>
      {fellBack && (
        <div className="note warn" style={{ marginBottom: 12 }}><CloudOff /><span>
          {active === "none" ? <>No map tile server is serving tiles to this machine (offline, or blocked on this network). The village is drawn from its own data on a plain background; everything else works as normal.</>
            : <>{PROVIDERS[base as Tiles].label} is not serving map tiles right now, so the background switched to {PROVIDERS[active as Tiles].label}.</>}
        </span></div>
      )}
      <div className="card" style={{ padding: 6, position: "relative" }}>
        {failed ? <div className="map m3 empty" style={{ display: "grid", placeItems: "center" }}><div><b>The 3D map needs WebGL, which this browser has turned off.</b><br />{failed}<br />The Network twin page shows the same live data without it.</div></div>
          : <div ref={el} className="map m3" />}
        {!failed && inVillage && !geo && (geoFail ? (
          <div className="m3-wait"><div>
            <b>{focus?.name || "This village"}'s streets and houses did not load</b>
            <span>{stale
              ? "The server was started before the latest map update, so it cannot send the village layout. Close the JalSakhi window and run start.bat again. The village will appear here by itself."
              : `The server answered: ${geoFail}. Trying again every few seconds.`}</span>
            <button className="btn sm" onClick={reloadGeo}>Try now</button>
          </div></div>
        ) : <div className="m3-wait quiet"><div>Loading the village layout…</div></div>)}
      </div>
      {inVillage && (
        <div className="legend" style={{ margin: "12px 4px 0" }}>
          <span><i style={{ background: "#2fb5f2" }} />Receiving water</span><span><i style={{ background: "#f59e0b" }} />Low pressure</span>
          <span><i style={{ background: "#e5484d" }} />No water</span><span><i style={{ background: "#94a3b8" }} />Unknown (no telemetry)</span>
          <span><i style={{ background: "#c98a66" }} />Supply off (plain roof)</span><span><i style={{ background: "#0a6fb8", width: 4, height: 13, borderRadius: 1 }} />Mast: metered home</span>
          <span><i style={{ background: "#8b6cf2" }} />School / anganwadi / health centre</span><span><i style={{ background: "#f97316", borderRadius: 2, transform: "rotate(45deg) scale(0.82)" }} />Citizen report</span>
        </div>
      )}
      <div className="grid g2" style={{ marginTop: 14 }}>
        <div className="card pad"><div className="upper muted" style={{ marginBottom: 8 }}>{inVillage ? "Households in this village" : "Households in view"}{clock && !clock.in_window ? " (supply currently off)" : ""}</div><StatusBar counts={counts.counts} total={counts.total} /></div>
        <div className="card pad sm ink2 row" style={{ alignItems: "flex-start" }}><MapPinned size={18} color="var(--brand)" style={{ flex: "none" }} />
          <span>Lanes, houses, fields, the approach road and the tank are generated demo geometry laid over a real background (Esri satellite imagery, OpenStreetMap streets or Esri terrain), so the imagery shows whatever really lies at these invented coordinates. The page tests each background before using it and drops it if it is not serving real tiles, so the village always draws, even offline. A deployment would load surveyed assets from the scheme's Sujalam Bharat geo-mapping.</span></div>
      </div>
      {sel && <HouseholdDrawer id={sel} onClose={() => setSel(null)} />}
    </div>
  );
}

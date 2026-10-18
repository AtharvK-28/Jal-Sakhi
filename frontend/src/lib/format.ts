// Formatting helpers and the vocabulary used across the staff UI.

export const hhmm = (iso?: string | null) => (iso ? iso.slice(11, 16) : "");
export const dayMon = (iso?: string | null) => {
  if (!iso) return "";
  const d = new Date(iso.slice(0, 10) + "T00:00:00");
  return d.toLocaleDateString("en-IN", { day: "2-digit", month: "short" });
};
export const dt = (iso?: string | null) => (iso ? `${dayMon(iso)} ${hhmm(iso)}` : "");
export const fromMinute = (m: number) => new Date(m * 60000).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", timeZone: "Asia/Kolkata" });
export const n1 = (v: any, d = 1) => (v === null || v === undefined || Number.isNaN(v) ? "–" : Number(v).toFixed(d));
export const n0 = (v: any) => (v === null || v === undefined ? "–" : Math.round(Number(v)).toLocaleString("en-IN"));
export const clamp = (v: number, a: number, b: number) => Math.max(a, Math.min(b, v));

/** Minutes between two sim timestamps (b defaults to "now" from the clock). */
export function minsBetween(a?: string | null, b?: string | null) {
  if (!a || !b) return null;
  return Math.round((new Date(b).getTime() - new Date(a).getTime()) / 60000);
}
export function dur(mins: number | null) {
  if (mins === null) return "–";
  const m = Math.abs(mins);
  if (m < 60) return `${m} min`;
  if (m < 1440) return `${Math.floor(m / 60)} h ${m % 60} min`;
  return `${Math.floor(m / 1440)} d ${Math.floor((m % 1440) / 60)} h`;
}

export const SUPPLY: Record<string, { label: string; color: string; hint: string }> = {
  ok: { label: "Receiving water", color: "var(--flow)", hint: "Pressure is adequate at the tap" },
  low: { label: "Low pressure", color: "var(--low)", hint: "Water is coming, but slowly" },
  dry: { label: "No water", color: "var(--dry)", hint: "No usable pressure during the supply window" },
  unknown: { label: "Unknown", color: "var(--unk)", hint: "No recent telemetry to estimate from" },
  idle: { label: "Scheduled off", color: "var(--idle)", hint: "Outside the supply window" },
};

export const INC_STATUS: Record<string, string> = {
  open: "Open", acknowledged: "Acknowledged", in_progress: "In progress",
  resolved_pending_verification: "Fixed · verifying", closed: "Closed",
};
export const CAT_LABEL: Record<string, string> = {
  no_water: "No water", low_pressure: "Low pressure", dirty_water: "Dirty water", leakage: "Leakage",
  smell_taste: "Smell / taste", irregular: "Irregular supply", tap_damage: "Damaged tap", other: "Other",
};
export const ORIGIN: Record<string, { label: string; cls: string }> = {
  sensor: { label: "Sensor rule", cls: "info" }, ml: { label: "AI model", cls: "ai" },
  forecast: { label: "AI forecast", cls: "ai" }, citizen: { label: "Citizen reports", cls: "high" },
  history: { label: "History", cls: "low" },
};
export const LANG_NAME: Record<string, string> = { en: "English", hi: "हिन्दी", mr: "मराठी", bn: "বাংলা", ta: "தமிழ்", te: "తెలుగు" };

export function scoreTone(score: number | null | undefined) {
  if (score === null || score === undefined) return { c1: "#9db1c2", c2: "#73899d", word: "No data" };
  if (score >= 88) return { c1: "#38bdf8", c2: "#0a6fb8", word: "Good" };
  if (score >= 72) return { c1: "#fbbf24", c2: "#e08a1e", word: "Needs attention" };
  return { c1: "#fb7185", c2: "#d03b3b", word: "Poor" };
}
export const scoreColor = (s: number | null | undefined) => (s === null || s === undefined ? "#8a9fb2" : s >= 88 ? "#0a86c4" : s >= 72 ? "#e08a1e" : "#d03b3b");

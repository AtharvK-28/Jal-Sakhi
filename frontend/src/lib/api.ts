// Thin API client: bearer token from the demo session, JSON in/out, errors surfaced as messages.

const KEY = "jalsakhi.session";

export type User = {
  username: string; name: string; role: string; role_label: string;
  scope_level: string; scope_id: string; villages: string[];
};
export type Session = { token: string; user: User };

export function getSession(): Session | null {
  try {
    return JSON.parse(localStorage.getItem(KEY) || "null");
  } catch {
    return null;
  }
}
export function setSession(s: Session) { localStorage.setItem(KEY, JSON.stringify(s)); }
export function clearSession() { localStorage.removeItem(KEY); }

export async function api(path: string, opts: { method?: string; body?: any; form?: FormData; auth?: boolean } = {}): Promise<any> {
  const headers: Record<string, string> = {};
  const s = getSession();
  if (s && opts.auth !== false) headers.Authorization = `Bearer ${s.token}`;
  let body: BodyInit | undefined;
  if (opts.form) body = opts.form;
  else if (opts.body !== undefined) { headers["Content-Type"] = "application/json"; body = JSON.stringify(opts.body); }
  const res = await fetch(path, { method: opts.method || (body ? "POST" : "GET"), headers, body });
  if (res.status === 401 && s && opts.auth !== false) {
    clearSession();
    window.location.href = "/";
    throw new Error("Session expired");
  }
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) {
    const d = data?.detail;
    throw new Error(typeof d === "string" ? d : Array.isArray(d) ? d.map((x: any) => x.msg).join("; ") : `Request failed (${res.status})`);
  }
  return data;
}

/** Fetch a file with the session's token and hand it to the browser as a download. */
export async function download(path: string, fallbackName: string): Promise<string> {
  const s = getSession();
  const res = await fetch(path, { headers: s ? { Authorization: `Bearer ${s.token}` } : {} });
  if (!res.ok) throw new Error(`Download failed (${res.status})`);
  const name = /filename="([^"]+)"/.exec(res.headers.get("Content-Disposition") || "")?.[1] || fallbackName;
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url; a.download = name;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  return name;
}

export async function login(username: string, password: string): Promise<Session> {
  const s = await api("/api/auth/login", { body: { username, password }, auth: false });
  setSession(s);
  return s;
}

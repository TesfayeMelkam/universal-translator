// Shared helpers: DOM lookup, banner, network requests (retry + timeout), low-data flag.
import { errorMessage, t } from "/static/js/i18n.js";

export const $ = (id) => document.getElementById(id);
export class ApiError extends Error {
  constructor(message, code, status) { super(message); this.code = code; this.status = status; }
}
export function banner(msg) { const b = $("banner"); if (!b) return; b.textContent = msg || ""; b.hidden = !msg; }

// ---- low-data mode: smaller photos, lower video quality, no stats polling noise ----
export function lowData() {
  let v = null; try { v = localStorage.getItem("ut_lowdata"); } catch (_) {}
  if (v === null) { const c = navigator.connection; return !!(c && (c.saveData || /(^|-)2g$/.test(c.effectiveType || ""))); }
  return v === "1";
}
export function setLowData(on) {
  try { localStorage.setItem("ut_lowdata", on ? "1" : "0"); } catch (_) {}
  document.dispatchEvent(new CustomEvent("lowdata", { detail: on }));
}

// ---- requests ----
let authHandler = null;                       // async (code) => true when the user fixed the problem (signed in, typed the code)
export function setAuthHandler(fn) { authHandler = fn; }
function accessCode() { try { return sessionStorage.ut_access || ""; } catch (_) { return ""; } }

export async function request(path, opts = {}) {
  const { retries = 2, timeout = 60000, ...init } = opts;
  const headers = { ...(init.headers || {}) };
  if (accessCode()) headers["X-Access-Code"] = accessCode();
  for (let attempt = 0; ; attempt++) {
    const ctl = new AbortController(), timer = setTimeout(() => ctl.abort(), timeout);
    try {
      const res = await fetch(path, { ...init, headers, signal: ctl.signal, credentials: "same-origin" });
      clearTimeout(timer);
      return res;
    } catch (e) {                              // no response at all: offline, dropped mobile data, timeout
      clearTimeout(timer);
      if (attempt >= retries) throw new ApiError(errorMessage("network", "Could not reach the server."), "network", 0);
      await new Promise((r) => setTimeout(r, 500 * (attempt + 1)));
    }
  }
}

export async function apiRaw(path, opts = {}, retried = false) {
  const res = await request(path, opts);
  if (res.ok) return res;
  let data = null; try { data = await res.clone().json(); } catch (_) { /* not JSON */ }
  const code = data && data.error && data.error.code;
  if (res.status === 401 && !retried && authHandler && (await authHandler(code))) return apiRaw(path, opts, true);
  throw new ApiError(errorMessage(code, (data && data.error && data.error.message) || `Request failed (${res.status})`), code || "http_" + res.status, res.status);
}

export async function api(path, opts = {}) {
  const o = { ...opts, headers: { "Content-Type": "application/json", ...(opts.headers || {}) } };
  return (await apiRaw(path, o)).json();
}
export function download(blob, name) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob); a.download = name; document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 4000);
}
export { t };

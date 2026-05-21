// Fetch wrapper for authenticated calls.
// • Always sends/receives the session cookie via credentials:'include'.
// • On 401 (except login itself), dispatches "auth:expired" so <App>
//   can route back to the login page with a "session expired" banner.

const HOSTS = ["", "http://localhost:5181"];

async function tryHosts(path, opts) {
  let lastErr;
  for (const h of HOSTS) {
    try {
      return await fetch(h + path, { credentials: "include", ...opts });
    } catch (e) { lastErr = e; }
  }
  throw lastErr;
}

export async function api(path, opts = {}) {
  const r = await tryHosts(path, opts);
  if (r.status === 401 && path !== "/api/auth/login") {
    window.dispatchEvent(new CustomEvent("auth:expired"));
  }
  return r;
}

export async function apiJson(path, opts = {}) {
  const r = await api(path, opts);
  let body = null;
  try { body = await r.json(); } catch { /* may be 204 */ }
  return { status: r.status, body };
}

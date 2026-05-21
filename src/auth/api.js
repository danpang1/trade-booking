// Fetch wrapper for authenticated calls.
// • Always sends/receives the session cookie via credentials:'include'.
// • On 401 (except login itself), dispatches "auth:expired" so <App>
//   can route back to the login page with a "session expired" banner.
// • Calls are always same-origin: Vite proxies /api → localhost:5181 in dev;
//   the Helm ingress routes /api to the right backend in UAT/prod.

export async function api(path, opts = {}) {
  const r = await fetch(path, { credentials: "include", ...opts });
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

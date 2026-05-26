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

export async function register({ username, email, password }) {
  const r = await api("/api/auth/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, email, password }),
  });
  let body = null;
  try { body = await r.json(); } catch { body = { ok: false, error: "non-JSON server response" }; }
  return { status: r.status, body };
}

// ── API Tokens (Phase 0) ─────────────────────────────────────────

export async function listTokens() {
  const { status, body } = await apiJson("/api/tokens");
  return { status, body };
}

export async function createToken({ name, expires_in_days }) {
  const { status, body } = await apiJson("/api/tokens", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, expires_in_days }),
  });
  return { status, body };
}

export async function revokeToken(id) {
  const { status, body } = await apiJson(`/api/tokens/${id}`, { method: "DELETE" });
  return { status, body };
}

// ── Bookings drafts (Phase 1a) ───────────────────────────────────

export async function listDrafts(filters = {}) {
  const params = new URLSearchParams();
  if (filters.status) params.set("status", filters.status);
  if (filters.batch_id) params.set("batch_id", filters.batch_id);
  const qs = params.toString() ? `?${params.toString()}` : "";
  const { status, body } = await apiJson(`/api/bookings/drafts${qs}`);
  return { status, body };
}

export async function getDraft(id) {
  const { status, body } = await apiJson(`/api/bookings/drafts/${id}`);
  return { status, body };
}

export async function createDraft({ category, payload, client_request_id }) {
  const { status, body } = await apiJson("/api/bookings/draft", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ category, payload, client_request_id }),
  });
  return { status, body };
}

export async function createDraftBatch(trades) {
  const { status, body } = await apiJson("/api/bookings/draft/batch", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ trades }),
  });
  return { status, body };
}

export async function patchDraft(id, payload) {
  const { status, body } = await apiJson(`/api/bookings/drafts/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ payload }),
  });
  return { status, body };
}

export async function approveDraft(id) {
  const { status, body } = await apiJson(`/api/bookings/drafts/${id}/approve`, {
    method: "POST",
  });
  return { status, body };
}

export async function rejectDraft(id, reason) {
  const { status, body } = await apiJson(`/api/bookings/drafts/${id}/reject`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reason: reason || null }),
  });
  return { status, body };
}

// Minimal API server for trade-booking. Mirrors dashboard/server.js pattern:
// startup backfill + hourly HH:15 UTC tick that re-snapshots reference tokens
// to public/tokens.json. The frontend fetches /tokens.json on mount.
//
// Run with: node server.js   (or via start.bat)

import { createServer } from "http";
import { spawn } from "child_process";
import { readFile, stat } from "fs/promises";
import { resolve, dirname, extname, normalize, sep } from "path";
import { fileURLToPath } from "url";
import { platform } from "os";

const PYTHON = process.env.PYTHON || (platform() === "win32" ? "python" : "python3");
const __dirname = dirname(fileURLToPath(import.meta.url));
const PORT = 5181;

const CASHFLOW_INSERT_SCRIPT   = resolve(__dirname, "scripts", "cashflow_insert.py");
const CASHFLOW_AMEND_SCRIPT    = resolve(__dirname, "scripts", "cashflow_amend.py");
const CASHFLOW_RECENT_SCRIPT   = resolve(__dirname, "scripts", "cashflow_recent.py");
const CASHFLOW_GET_SCRIPT      = resolve(__dirname, "scripts", "cashflow_get.py");
const CASHFLOW_HISTORY_SCRIPT  = resolve(__dirname, "scripts", "cashflow_history.py");
const CASHFLOW_TX_FETCH_SCRIPT = resolve(__dirname, "scripts", "cashflow_tx_fetch.py");
const LOAN_INSERT_SCRIPT  = resolve(__dirname, "scripts", "loan_insert.py");
const LOAN_AMEND_SCRIPT   = resolve(__dirname, "scripts", "loan_amend.py");
const LOAN_AMEND_BATCH_SCRIPT = resolve(__dirname, "scripts", "loan_amend_batch.py");
const LOAN_RECENT_SCRIPT  = resolve(__dirname, "scripts", "loan_recent.py");
const LOAN_GET_SCRIPT     = resolve(__dirname, "scripts", "loan_get.py");
const LOAN_HISTORY_SCRIPT = resolve(__dirname, "scripts", "loan_history.py");
const LOAN_SCHEDULE_COMMENT_UPSERT_SCRIPT = resolve(__dirname, "scripts", "loan_schedule_comment_upsert.py");
const RATES_LATEST_SCRIPT = resolve(__dirname, "scripts", "rates_latest.py");
const SPOT_INSERT_SCRIPT  = resolve(__dirname, "scripts", "spot_insert.py");
const SPOT_AMEND_SCRIPT   = resolve(__dirname, "scripts", "spot_amend.py");
const CASHFLOW_AMEND_BATCH_SCRIPT = resolve(__dirname, "scripts", "cashflow_amend_batch.py");
const SPOT_AMEND_BATCH_SCRIPT     = resolve(__dirname, "scripts", "spot_amend_batch.py");
const SPOT_RECENT_SCRIPT  = resolve(__dirname, "scripts", "spot_recent.py");
const SPOT_GET_SCRIPT     = resolve(__dirname, "scripts", "spot_get.py");
const SPOT_HISTORY_SCRIPT = resolve(__dirname, "scripts", "spot_history.py");
const EXPORT_BLOTTER_SCRIPT = resolve(__dirname, "scripts", "export_blotter.py");
const LOAN_EXPORT_SCRIPT    = resolve(__dirname, "scripts", "loan_export.py");
const BINANCE_VIP_LTV_SCRIPT = resolve(__dirname, "scripts", "binance_vip_loan_ltv.py");
const FUNDING_SETTINGS_READ_SCRIPT   = resolve(__dirname, "scripts", "funding_settings_read.py");
const FUNDING_SETTINGS_UPSERT_SCRIPT = resolve(__dirname, "scripts", "funding_settings_upsert.py");

const AUTH_LOGIN_SCRIPT    = resolve(__dirname, "scripts", "auth_login.py");
const AUTH_LOGOUT_SCRIPT   = resolve(__dirname, "scripts", "auth_logout.py");
const AUTH_WHOAMI_SCRIPT   = resolve(__dirname, "scripts", "auth_whoami.py");
const AUTH_REGISTER_SCRIPT = resolve(__dirname, "scripts", "auth_register.py");
const AUTH_WHOAMI_BEARER_SCRIPT = resolve(__dirname, "scripts", "auth_whoami_bearer.py");

const TOKEN_CREATE_SCRIPT = resolve(__dirname, "scripts", "token_create.py");
const TOKEN_LIST_SCRIPT   = resolve(__dirname, "scripts", "token_list.py");
const TOKEN_REVOKE_SCRIPT = resolve(__dirname, "scripts", "token_revoke.py");

const DRAFT_INSERT_SCRIPT       = resolve(__dirname, "scripts", "draft_insert.py");
const DRAFT_BATCH_INSERT_SCRIPT = resolve(__dirname, "scripts", "draft_batch_insert.py");
const DRAFT_LIST_SCRIPT         = resolve(__dirname, "scripts", "draft_list.py");
const DRAFT_GET_SCRIPT          = resolve(__dirname, "scripts", "draft_get.py");
const DRAFT_PATCH_SCRIPT        = resolve(__dirname, "scripts", "draft_patch.py");
const DRAFT_APPROVE_SCRIPT      = resolve(__dirname, "scripts", "draft_approve.py");
const DRAFT_REJECT_SCRIPT       = resolve(__dirname, "scripts", "draft_reject.py");

const USER_CREATE_SCRIPT  = resolve(__dirname, "scripts", "user_create.py");
const USER_LIST_SCRIPT    = resolve(__dirname, "scripts", "user_list.py");
const USER_UPDATE_SCRIPT  = resolve(__dirname, "scripts", "user_update.py");
const USER_DELETE_SCRIPT  = resolve(__dirname, "scripts", "user_delete.py");
const USER_APPROVE_SCRIPT = resolve(__dirname, "scripts", "user_approve.py");
const USER_REJECT_SCRIPT  = resolve(__dirname, "scripts", "user_reject.py");

const SESSION_COOKIE = "sid";
const SESSION_MAX_AGE_SEC = 8 * 60 * 60;

// ── Refdata syncs ──────────────────────────────────────────────────────
// Each entry: { key, script, label } — the key drives state tracking,
// route lookup (/refdata/<key>.json), and the response body of
// /api/refdata/refresh. To add a new dropdown source, drop a new
// sync_*.py under scripts/ and add a row here.
const REFDATA_SOURCES = [
  { key: "tokens",         script: "snapshot_tokens.py",       label: "tokens" },
  { key: "counterparties", script: "sync_counterparties.py",   label: "counterparties" },
  { key: "portfolios",     script: "sync_portfolios.py",       label: "portfolios" },
  { key: "users",          script: "sync_users.py",            label: "users" },
  { key: "accounts",       script: "sync_accounts.py",         label: "accounts" },
  // Key MUST equal the JSON filename stem — server.js routes
  // /refdata/<key>.json via REFDATA_BY_KEY.has(key). Mismatch
  // would silently fall through to the SPA fallback and serve
  // index.html instead of the JSON.
  { key: "perps_instruments", script: "sync_perps_instruments.py", label: "perps" },
];
const REFDATA_BY_KEY = new Map(REFDATA_SOURCES.map((s) => [s.key, s]));
const PUBLIC_DIR     = resolve(__dirname, "public");
const REFDATA_DIR    = resolve(PUBLIC_DIR, "refdata");
const TOKENS_JSON    = resolve(PUBLIC_DIR, "tokens.json");

// React production bundle. Present in prod images (built by `npm run build`),
// absent in local dev (Vite serves the bundle on its own port). The static
// fallback handler at the end of the request pipeline only activates if
// dist/index.html exists.
const DIST_DIR       = resolve(__dirname, "dist");
const DIST_INDEX     = resolve(DIST_DIR, "index.html");

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".js":   "application/javascript; charset=utf-8",
  ".mjs":  "application/javascript; charset=utf-8",
  ".css":  "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg":  "image/svg+xml",
  ".png":  "image/png",
  ".jpg":  "image/jpeg",
  ".jpeg": "image/jpeg",
  ".webp": "image/webp",
  ".ico":  "image/x-icon",
  ".woff": "font/woff",
  ".woff2": "font/woff2",
  ".map":  "application/json; charset=utf-8",
  ".txt":  "text/plain; charset=utf-8",
};

let distAvailable = null;  // cached after first probe (null | true | false)
async function isDistAvailable() {
  if (distAvailable !== null) return distAvailable;
  try {
    await stat(DIST_INDEX);
    distAvailable = true;
  } catch {
    distAvailable = false;
  }
  return distAvailable;
}

// Per-source state. Same shape across all 4 so the /api/health endpoint
// can serialize them uniformly.
const refdataState = new Map(
  REFDATA_SOURCES.map((s) => [
    s.key,
    { running: false, lastAt: null, lastOk: null, lastError: null },
  ])
);

// Run a single sync script. Returns a Promise that resolves with
// {key, ok, exitCode, error} so callers can await one or many.
function runSyncOnce(key, runLabel) {
  const source = REFDATA_BY_KEY.get(key);
  if (!source) {
    return Promise.resolve({ key, ok: false, exitCode: -1, error: "unknown refdata key" });
  }
  const state = refdataState.get(key);
  if (state.running) {
    console.log(`[${source.label}] ${runLabel}: skipped — prior run still in flight`);
    return Promise.resolve({ key, ok: true, exitCode: 0, skipped: true });
  }

  return new Promise((res) => {
    state.running = true;
    const scriptPath = resolve(__dirname, "scripts", source.script);
    console.log(`[${source.label}] ${runLabel}: spawning ${source.script}`);
    const proc = spawn(PYTHON, [scriptPath], { cwd: __dirname });
    let stderr = "";
    proc.stdout.on("data", (d) => process.stdout.write(`[${source.label}] ${d}`));
    proc.stderr.on("data", (d) => {
      stderr += d;
      process.stderr.write(`[${source.label}:err] ${d}`);
    });
    proc.on("close", (code) => {
      state.running = false;
      state.lastAt = new Date().toISOString();
      if (code === 0) {
        state.lastOk = true;
        state.lastError = null;
        console.log(`[${source.label}] ${runLabel}: ok`);
        res({ key, ok: true, exitCode: 0 });
      } else {
        state.lastOk = false;
        state.lastError = stderr.trim().split("\n").slice(-5).join(" | ");
        console.error(`[${source.label}] ${runLabel}: exit ${code}: ${state.lastError}`);
        res({ key, ok: false, exitCode: code, error: state.lastError });
      }
    });
  });
}

// Fan all 4 sync scripts out in parallel and resolve when the last
// one finishes. Per-script failures don't fail the batch — the caller
// gets per-script status in the response body.
async function runAllSyncs(runLabel) {
  return Promise.all(REFDATA_SOURCES.map((s) => runSyncOnce(s.key, runLabel)));
}

function msUntilNextHH15UTC() {
  const now = new Date();
  const target = new Date(
    Date.UTC(
      now.getUTCFullYear(),
      now.getUTCMonth(),
      now.getUTCDate(),
      now.getUTCHours(),
      15,
      0,
      0
    )
  );
  if (target <= now) target.setUTCHours(target.getUTCHours() + 1);
  return target.getTime() - now.getTime();
}

function scheduleHourlyRefdataSync() {
  runAllSyncs("startup-backfill");
  const firstDelay = msUntilNextHH15UTC();
  console.log(`[refdata] next hourly tick in ${Math.round(firstDelay / 1000)}s`);
  setTimeout(() => {
    runAllSyncs("hourly-tick");
    setInterval(() => runAllSyncs("hourly-tick"), 60 * 60 * 1000);
  }, firstDelay);
}

// Spawn a Python script, pipe stdinJson to its stdin, resolve to its
// parsed JSON stdout + exit code. Never throws — errors come back as
// { ok:false, error, detail } so the HTTP handler can map them cleanly.
function spawnPython(scriptPath, stdinJson) {
  return new Promise((resolveP) => {
    const proc = spawn(PYTHON, [scriptPath], { cwd: __dirname });
    let stdout = "";
    let stderr = "";
    proc.stdout.on("data", (d) => { stdout += d; });
    proc.stderr.on("data", (d) => { stderr += d; });
    proc.on("error", (e) => {
      resolveP({ code: -1, json: { ok: false, error: "spawn failed", detail: String(e) }, stderr });
    });
    proc.on("close", (code) => {
      let parsed;
      try { parsed = JSON.parse(stdout); }
      catch (e) {
        parsed = { ok: false, error: "non-JSON output from script", detail: stdout.slice(0, 500) };
      }
      // Surface Python failures in Grafana. We deliberately don't log
      // stdin (passwords on /api/auth/login, PII on booking POSTs), but
      // stderr is safe — Python tracebacks and our own logging only.
      if (code !== 0) {
        process.stdout.write(JSON.stringify({
          ts: new Date().toISOString(),
          level: "error",
          msg: "python",
          script: scriptPath.split(/[\\/]/).pop(),
          exit_code: code,
          stderr_tail: stderr.slice(-500),
        }) + "\n");
      }
      resolveP({ code, json: parsed, stderr });
    });
    proc.stdin.end(stdinJson);
  });
}

// Read the full request body as a string.
function readBody(req) {
  return new Promise((resolveB, rejectB) => {
    let buf = "";
    req.on("data", (d) => { buf += d; });
    req.on("end", () => resolveB(buf));
    req.on("error", rejectB);
  });
}

// Map a Python exit code → HTTP status code.
function httpStatusFor(exitCode, json) {
  if (exitCode === 0) return 200;
  if (json && json.code === "conflict") return 409;
  if (json && json.code === "not_found") return 404;
  if (json && json.code === "no_transfers") return 422;
  if (json && json.code === "upstream") return 502;
  if (exitCode === 3) return 400;  // validation
  if (exitCode === 4) return 404;  // not_found (fallback if code missing)
  if (exitCode === 6) return 401;  // auth failure
  if (exitCode === 7) return 409;  // conflict (draft already approved/rejected)
  return 500;
}

// ── Cookie + session helpers ──────────────────────────────────────
function parseCookies(req) {
  const header = req.headers.cookie || "";
  const out = {};
  for (const part of header.split(";")) {
    const [k, ...rest] = part.trim().split("=");
    if (!k) continue;
    const raw = rest.join("=");
    // decodeURIComponent throws URIError on malformed %-encoding. Browser-set
    // cookies are always valid (we encode in setSessionCookie), but a crafted
    // Cookie header from a non-browser client could otherwise crash the worker.
    try { out[k] = decodeURIComponent(raw); }
    catch { out[k] = raw; }
  }
  return out;
}

function setSessionCookie(res, sid) {
  res.setHeader(
    "Set-Cookie",
    `${SESSION_COOKIE}=${encodeURIComponent(sid)}; HttpOnly; SameSite=Lax; Path=/; Max-Age=${SESSION_MAX_AGE_SEC}`
  );
}

function clearSessionCookie(res) {
  res.setHeader(
    "Set-Cookie",
    `${SESSION_COOKIE}=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0`
  );
}

// Resolve the request identity.
// Path A: session cookie → auth_whoami.py
// Path B: Bearer token   → auth_whoami_bearer.py  (added Phase 0)
// Returns null if neither path yields a valid user.
// Both paths return the same shape plus an authMode field:
//   { authMode: "cookie"|"bearer", sid?, id, username, email, role }
async function resolveSession(req) {
  // Path A: existing cookie auth
  const sid = parseCookies(req)[SESSION_COOKIE];
  if (sid) {
    const result = await spawnPython(AUTH_WHOAMI_SCRIPT, JSON.stringify({ sid }));
    if (result.code === 0 && result.json && result.json.ok === true) {
      return { authMode: "cookie", sid, ...result.json.user };
    }
  }

  // Path B: Bearer token (added in Phase 0)
  const authHeader = req.headers.authorization || "";
  if (authHeader.startsWith("Bearer ")) {
    const token = authHeader.slice(7).trim();
    if (token) {
      const result = await spawnPython(AUTH_WHOAMI_BEARER_SCRIPT, JSON.stringify({ token }));
      if (result.code === 0 && result.json && result.json.ok === true) {
        return { authMode: "bearer", ...result.json.user };
      }
    }
  }

  return null;
}

function requireAdmin(req, res) {
  if (req.sessionUser && req.sessionUser.role === "admin") return true;
  res.statusCode = 403;
  res.setHeader("Content-Type", "application/json");
  res.end(JSON.stringify({ ok: false, error: "admin required" }));
  return false;
}

// Force-stamp user_id from session onto a body string before passing to Python.
// Accepts both raw-payload and {payload:{...}, attachments:[...]} shapes
// (cashflow_insert.py:88-99 handles both).
function stampUserId(rawBody, username) {
  let payload;
  try { payload = JSON.parse(rawBody || "{}"); }
  catch { return rawBody; }  // let Python report the bad-JSON error
  if (payload && typeof payload === "object") {
    if (payload.payload && typeof payload.payload === "object") {
      payload.payload.user_id = username;
    } else {
      payload.user_id = username;
    }
  }
  return JSON.stringify(payload);
}

// Like stampUserId, but for a bulk-amend body {rows:[...]} (or a bare array):
// force user_id from the session onto every row so the frontend can't spoof it.
function stampBatchUserId(rawBody, username) {
  let data;
  try { data = JSON.parse(rawBody || "{}"); }
  catch { return rawBody; }  // let Python report the bad-JSON error
  const rows = Array.isArray(data) ? data : (data && Array.isArray(data.rows) ? data.rows : null);
  if (rows) for (const r of rows) { if (r && typeof r === "object") r.user_id = username; }
  return JSON.stringify(data);
}

// One structured JSON line per /api/* response on stdout. Tokka's Loki
// agent scrapes container stdout and tags it `app=trade-booking-server-uat`
// from pod metadata, so these surface in Grafana with no extra wiring.
// LogQL: {app="trade-booking-server-uat"} | json | status >= 400
// Skips /api/health (k8s probes call it on a tight loop) and non-API
// paths (static bundle assets). Body is never logged — passwords would
// land in the login row.
function logRequest(req, res, t0) {
  const url = req.url || "";
  if (!url.startsWith("/api/")) return;
  if (url === "/api/health") return;
  const line = {
    ts: new Date().toISOString(),
    level: res.statusCode >= 500 ? "error" : res.statusCode >= 400 ? "warn" : "info",
    msg: "http",
    method: req.method,
    path: url.split("?")[0],
    status: res.statusCode,
    duration_ms: Date.now() - t0,
    user: (req.sessionUser && req.sessionUser.username) || null,
    ip: req.headers["x-forwarded-for"] || (req.socket && req.socket.remoteAddress) || null,
  };
  process.stdout.write(JSON.stringify(line) + "\n");
}

// ── HTTP server: serves /tokens.json (for non-Vite hosts) + /api/health ──
// In-memory cache for the Binance VIP loan LTV. The ongoing-orders call is
// a signed, rate-limited Binance request. Shared per worker — each replica
// of the prod HA pair keeps its own. { ts: epoch_ms, payload: object } | null.
//
// The whole VIP block is a 5s live ticker: the front-end polls the summary
// every 5s, and the detail (collateral + triggers) every 5s while its panel
// is open. Both caches therefore use a short 5s window — long enough only to
// COALESCE concurrent viewers into ~one Binance call per 5s rather than one
// per open tab, not to add staleness. The detail path is heavier (3–4 Binance
// calls per miss) but is only hit while a user has the panel expanded.
let binanceLtvCache = null;
let binanceLtvDetailCache = null;
const BINANCE_LTV_SUMMARY_TTL_MS = 5_000;
const BINANCE_LTV_DETAIL_TTL_MS = 5_000;

const server = createServer(async (req, res) => {
  const t0 = Date.now();
  res.on("finish", () => logRequest(req, res, t0));

  // CORS for the Vite dev server on a different port.
  // credentials:'include' requires echoing the request origin (browsers
  // refuse '*' with credentials) AND Access-Control-Allow-Credentials: true.
  const origin = req.headers.origin || "*";
  res.setHeader("Access-Control-Allow-Origin", origin);
  res.setHeader("Access-Control-Allow-Credentials", "true");
  res.setHeader("Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type, Authorization");
  if (req.method === "OPTIONS") {
    res.statusCode = 204;
    res.end();
    return;
  }

  // ── Auth gate ─────────────────────────────────────────────────────
  // Public paths: /api/auth/login (so users can log in) and /api/health
  // (so the Kubernetes startup/liveness probes can reach it without a
  // session cookie). Everything else under /api/* requires a valid
  // session. Static assets (no /api/ prefix) fall through unchanged.
  const isApi = (req.url || "").startsWith("/api/");
  const isPublicApi = req.url === "/api/auth/login"
                  || req.url === "/api/auth/register"
                  || req.url === "/api/health";
  if (isApi && !isPublicApi) {
    const sessionUser = await resolveSession(req);
    if (!sessionUser) {
      res.statusCode = 401;
      res.setHeader("Content-Type", "application/json");
      res.end(JSON.stringify({ ok: false, error: "not authenticated" }));
      return;
    }
    req.sessionUser = sessionUser;  // {sid, id, username, email, role}
  }

  if (req.url === "/api/health") {
    const refdata = {};
    for (const [k, v] of refdataState.entries()) refdata[k] = v;
    res.setHeader("Content-Type", "application/json");
    res.end(JSON.stringify({ status: "ok", refdata }));
    return;
  }

  // Manual refresh of ALL refdata sources (tokens + counterparties +
  // portfolios + users). Awaits the batch so the response carries
  // per-source success/fail status.
  if (req.url === "/api/refdata/refresh" && req.method === "POST") {
    const t0 = Date.now();
    const results = await runAllSyncs("manual-refresh");
    res.setHeader("Content-Type", "application/json");
    res.end(JSON.stringify({
      ok: results.every((r) => r.ok),
      elapsed_ms: Date.now() - t0,
      results,
    }));
    return;
  }

  // Back-compat: legacy /api/refresh endpoint kicked off the token
  // snapshot only. Keep it working for any code that still calls it.
  if (req.url === "/api/refresh" && req.method === "POST") {
    runSyncOnce("tokens", "manual-refresh");
    res.setHeader("Content-Type", "application/json");
    res.end(JSON.stringify({ status: "scheduled" }));
    return;
  }

  // ── Auth: login ───────────────────────────────────────────────────
  if (req.url === "/api/auth/login" && req.method === "POST") {
    const body = await readBody(req);
    const result = await spawnPython(AUTH_LOGIN_SCRIPT, body);
    const status = httpStatusFor(result.code, result.json);
    if (status === 200 && result.json && result.json.sid) {
      setSessionCookie(res, result.json.sid);
      // Don't leak the sid in the response body — it's now in the cookie.
      const { sid, ...rest } = result.json;
      res.statusCode = 200;
      res.setHeader("Content-Type", "application/json");
      res.end(JSON.stringify(rest));
      return;
    }
    res.statusCode = status;
    res.setHeader("Content-Type", "application/json");
    res.end(JSON.stringify(result.json));
    return;
  }

  // ── Auth: register ───────────────────────────────────────────────
  if (req.url === "/api/auth/register" && req.method === "POST") {
    const body = await readBody(req);
    const result = await spawnPython(AUTH_REGISTER_SCRIPT, body);
    const status = httpStatusFor(result.code, result.json);
    res.statusCode = status;
    res.setHeader("Content-Type", "application/json");
    res.end(JSON.stringify(result.json));
    return;
  }

  // ── Auth: logout ──────────────────────────────────────────────────
  if (req.url === "/api/auth/logout" && req.method === "POST") {
    if (req.sessionUser.authMode !== "cookie") {
      res.statusCode = 400;
      res.setHeader("Content-Type", "application/json");
      res.end(JSON.stringify({
        ok: false,
        error: "logout requires session login (cookie). To revoke a Bearer token, use DELETE /api/tokens/:id",
      }));
      return;
    }
    const sid = req.sessionUser.sid;
    await spawnPython(AUTH_LOGOUT_SCRIPT, JSON.stringify({ sid }));
    clearSessionCookie(res);
    res.statusCode = 204;
    res.end();
    return;
  }

  // ── Auth: whoami ──────────────────────────────────────────────────
  if (req.url === "/api/auth/me" && req.method === "GET") {
    const { username, email, role } = req.sessionUser;
    res.statusCode = 200;
    res.setHeader("Content-Type", "application/json");
    res.end(JSON.stringify({ ok: true, user: { username, email, role } }));
    return;
  }

  // ── Users: list ───────────────────────────────────────────────────
  if (req.url === "/api/users" && req.method === "GET") {
    if (!requireAdmin(req, res)) return;
    const result = await spawnPython(USER_LIST_SCRIPT, "{}");
    res.statusCode = httpStatusFor(result.code, result.json);
    res.setHeader("Content-Type", "application/json");
    res.end(JSON.stringify(result.json));
    return;
  }

  // ── Users: create ────────────────────────────────────────────────
  if (req.url === "/api/users" && req.method === "POST") {
    if (!requireAdmin(req, res)) return;
    const body = await readBody(req);
    let payload;
    try { payload = JSON.parse(body || "{}"); }
    catch { payload = {}; }
    payload._acting_user = req.sessionUser.username;
    const result = await spawnPython(USER_CREATE_SCRIPT, JSON.stringify(payload));
    res.statusCode = httpStatusFor(result.code, result.json);
    res.setHeader("Content-Type", "application/json");
    res.end(JSON.stringify(result.json));
    return;
  }

  // ── Users: update / delete (path /api/users/:id) ──────────────────
  const userIdMatch = (req.url || "").match(/^\/api\/users\/(\d+)$/);
  if (userIdMatch && req.method === "PATCH") {
    if (!requireAdmin(req, res)) return;
    const body = await readBody(req);
    let payload;
    try { payload = JSON.parse(body || "{}"); }
    catch { payload = {}; }
    payload.id = parseInt(userIdMatch[1], 10);
    payload._acting_user = req.sessionUser.username;
    const result = await spawnPython(USER_UPDATE_SCRIPT, JSON.stringify(payload));
    res.statusCode = httpStatusFor(result.code, result.json);
    res.setHeader("Content-Type", "application/json");
    res.end(JSON.stringify(result.json));
    return;
  }
  if (userIdMatch && req.method === "DELETE") {
    if (!requireAdmin(req, res)) return;
    const payload = {
      id: parseInt(userIdMatch[1], 10),
      _acting_user_id: req.sessionUser.id,
    };
    const result = await spawnPython(USER_DELETE_SCRIPT, JSON.stringify(payload));
    res.statusCode = httpStatusFor(result.code, result.json);
    res.setHeader("Content-Type", "application/json");
    res.end(JSON.stringify(result.json));
    return;
  }

  // ── Admin: approve pending user ─────────────────────────────────
  const approveMatch = req.url && req.url.match(/^\/api\/users\/(\d+)\/approve$/);
  if (approveMatch && req.method === "POST") {
    if (!requireAdmin(req, res)) return;
    const userId = parseInt(approveMatch[1], 10);
    const body = await readBody(req);
    let parsed; try { parsed = JSON.parse(body || "{}"); } catch { parsed = {}; }
    parsed.user_id = userId;
    parsed._acting_user = req.sessionUser.username;
    const result = await spawnPython(USER_APPROVE_SCRIPT, JSON.stringify(parsed));
    const status = httpStatusFor(result.code, result.json);
    res.statusCode = status;
    res.setHeader("Content-Type", "application/json");
    res.end(JSON.stringify(result.json));
    return;
  }

  // ── Admin: reject pending user ──────────────────────────────────────────
  const rejectMatch = req.url && req.url.match(/^\/api\/users\/(\d+)\/reject$/);
  if (rejectMatch && req.method === "POST") {
    if (!requireAdmin(req, res)) return;
    const userId = parseInt(rejectMatch[1], 10);
    const result = await spawnPython(USER_REJECT_SCRIPT, JSON.stringify({ user_id: userId }));
    const status = httpStatusFor(result.code, result.json);
    res.statusCode = status;
    res.setHeader("Content-Type", "application/json");
    res.end(JSON.stringify(result.json));
    return;
  }

  // ── API Tokens (cookie-auth ONLY; Bearer can't mint more Bearer) ──
  if ((req.url || "").startsWith("/api/tokens")) {
    if (req.sessionUser.authMode !== "cookie") {
      res.statusCode = 403;
      res.setHeader("Content-Type", "application/json");
      res.end(JSON.stringify({
        ok: false,
        error: "tokens API requires session login (cookie), not Bearer",
      }));
      return;
    }

    // POST /api/tokens — create
    if (req.url === "/api/tokens" && req.method === "POST") {
      const body = await readBody(req);
      let parsed;
      try { parsed = JSON.parse(body || "{}"); } catch { parsed = {}; }
      parsed._acting_user = req.sessionUser.username;
      const result = await spawnPython(TOKEN_CREATE_SCRIPT, JSON.stringify(parsed));
      res.statusCode = httpStatusFor(result.code, result.json);
      res.setHeader("Content-Type", "application/json");
      res.end(JSON.stringify(result.json));
      return;
    }

    // GET /api/tokens — list
    if (req.url === "/api/tokens" && req.method === "GET") {
      const stdin = JSON.stringify({ _acting_user: req.sessionUser.username });
      const result = await spawnPython(TOKEN_LIST_SCRIPT, stdin);
      res.statusCode = httpStatusFor(result.code, result.json);
      res.setHeader("Content-Type", "application/json");
      res.end(JSON.stringify(result.json));
      return;
    }

    // DELETE /api/tokens/:id — revoke
    const m = (req.url || "").match(/^\/api\/tokens\/(\d+)$/);
    if (m && req.method === "DELETE") {
      const id = parseInt(m[1], 10);
      const stdin = JSON.stringify({ id, _acting_user: req.sessionUser.username });
      const result = await spawnPython(TOKEN_REVOKE_SCRIPT, stdin);
      res.statusCode = httpStatusFor(result.code, result.json);
      res.setHeader("Content-Type", "application/json");
      res.end(JSON.stringify(result.json));
      return;
    }

    // unknown method/path under /api/tokens
    res.statusCode = 404;
    res.setHeader("Content-Type", "application/json");
    res.end(JSON.stringify({ ok: false, error: "not found" }));
    return;
  }
  // ── API Tokens end ────────────────────────────────────────────────────

  // ── Bookings: drafts (cookie OR Bearer auth, per-user isolation) ──
  if ((req.url || "").startsWith("/api/bookings/draft")) {
    const acting = req.sessionUser.username;

    // POST /api/bookings/draft/batch  — atomic N-row batch
    if (req.url === "/api/bookings/draft/batch" && req.method === "POST") {
      const body = await readBody(req);
      let parsed; try { parsed = JSON.parse(body || "{}"); } catch { parsed = {}; }
      parsed._acting_user = acting;
      const result = await spawnPython(DRAFT_BATCH_INSERT_SCRIPT, JSON.stringify(parsed));
      res.statusCode = httpStatusFor(result.code, result.json);
      res.setHeader("Content-Type", "application/json");
      res.end(JSON.stringify(result.json));
      return;
    }

    // POST /api/bookings/draft  — single
    if (req.url === "/api/bookings/draft" && req.method === "POST") {
      const body = await readBody(req);
      let parsed; try { parsed = JSON.parse(body || "{}"); } catch { parsed = {}; }
      parsed._acting_user = acting;
      const result = await spawnPython(DRAFT_INSERT_SCRIPT, JSON.stringify(parsed));
      res.statusCode = httpStatusFor(result.code, result.json);
      res.setHeader("Content-Type", "application/json");
      res.end(JSON.stringify(result.json));
      return;
    }

    // GET /api/bookings/drafts (bare list, optional query filters)
    // Single-draft GET (/drafts/:id) is handled by the idOnlyMatch below.
    {
      const u = new URL(req.url || "", "http://localhost");
      if (req.method === "GET" && /^\/api\/bookings\/drafts\/?$/.test(u.pathname)) {
        const stdin = JSON.stringify({
          _acting_user: acting,
          status: u.searchParams.get("status") || null,
          batch_id: u.searchParams.get("batch_id") || null,
        });
        const result = await spawnPython(DRAFT_LIST_SCRIPT, stdin);
        res.statusCode = httpStatusFor(result.code, result.json);
        res.setHeader("Content-Type", "application/json");
        res.end(JSON.stringify(result.json));
        return;
      }
    }

    // POST /api/bookings/drafts/:id/approve
    const approveMatch = (req.url || "").match(/^\/api\/bookings\/drafts\/(\d+)\/approve$/);
    if (approveMatch && req.method === "POST") {
      const id = parseInt(approveMatch[1], 10);
      const stdin = JSON.stringify({ id, _acting_user: acting });
      const result = await spawnPython(DRAFT_APPROVE_SCRIPT, stdin);
      res.statusCode = httpStatusFor(result.code, result.json);
      res.setHeader("Content-Type", "application/json");
      res.end(JSON.stringify(result.json));
      return;
    }

    // POST /api/bookings/drafts/:id/reject
    const rejectMatch = (req.url || "").match(/^\/api\/bookings\/drafts\/(\d+)\/reject$/);
    if (rejectMatch && req.method === "POST") {
      const id = parseInt(rejectMatch[1], 10);
      const body = await readBody(req);
      let parsed; try { parsed = JSON.parse(body || "{}"); } catch { parsed = {}; }
      parsed.id = id;
      parsed._acting_user = acting;
      const result = await spawnPython(DRAFT_REJECT_SCRIPT, JSON.stringify(parsed));
      res.statusCode = httpStatusFor(result.code, result.json);
      res.setHeader("Content-Type", "application/json");
      res.end(JSON.stringify(result.json));
      return;
    }

    // PATCH /api/bookings/drafts/:id
    const idOnlyMatch = (req.url || "").match(/^\/api\/bookings\/drafts\/(\d+)$/);
    if (idOnlyMatch && req.method === "PATCH") {
      const id = parseInt(idOnlyMatch[1], 10);
      const body = await readBody(req);
      let parsed; try { parsed = JSON.parse(body || "{}"); } catch { parsed = {}; }
      parsed.id = id;
      parsed._acting_user = acting;
      const result = await spawnPython(DRAFT_PATCH_SCRIPT, JSON.stringify(parsed));
      res.statusCode = httpStatusFor(result.code, result.json);
      res.setHeader("Content-Type", "application/json");
      res.end(JSON.stringify(result.json));
      return;
    }

    // GET /api/bookings/drafts/:id
    if (idOnlyMatch && req.method === "GET") {
      const id = parseInt(idOnlyMatch[1], 10);
      const stdin = JSON.stringify({ id, _acting_user: acting });
      const result = await spawnPython(DRAFT_GET_SCRIPT, stdin);
      res.statusCode = httpStatusFor(result.code, result.json);
      res.setHeader("Content-Type", "application/json");
      res.end(JSON.stringify(result.json));
      return;
    }

    // unknown method/path under /api/bookings/draft(s)
    res.statusCode = 404;
    res.setHeader("Content-Type", "application/json");
    res.end(JSON.stringify({ ok: false, error: "not found" }));
    return;
  }
  // ── Bookings drafts end ──────────────────────────────────────────────

  // Static serve of any refdata JSON: /refdata/portfolios.json, etc.
  // Only matches known keys (REFDATA_SOURCES) so we don't accidentally
  // expose other files under public/refdata/.
  {
    const m = /^\/refdata\/([a-z_]+)\.json$/.exec(req.url || "");
    if (m && REFDATA_BY_KEY.has(m[1])) {
      try {
        const data = await readFile(resolve(REFDATA_DIR, `${m[1]}.json`));
        res.setHeader("Content-Type", "application/json");
        res.setHeader("Cache-Control", "no-cache");
        res.end(data);
      } catch (e) {
        res.statusCode = 503;
        res.end(JSON.stringify({ error: `${m[1]}.json not yet generated` }));
      }
      return;
    }
  }

  if (req.url === "/tokens.json") {
    try {
      const data = await readFile(TOKENS_JSON);
      res.setHeader("Content-Type", "application/json");
      res.setHeader("Cache-Control", "no-cache");
      res.end(data);
    } catch (e) {
      res.statusCode = 503;
      res.end(JSON.stringify({ error: "tokens.json not yet generated" }));
    }
    return;
  }

  // POST /api/cashflow/insert
  if (req.url === "/api/cashflow/insert" && req.method === "POST") {
    const body = await readBody(req);
    const stampedBody = stampUserId(body, req.sessionUser.username);
    const t0 = Date.now();
    const { code, json, stderr } = await spawnPython(CASHFLOW_INSERT_SCRIPT, stampedBody);
    const dealRefs = (json && json.rows || []).map((r) => r.deal_ref).join(",");
    console.log(`[cashflow] insert ${dealRefs || "FAIL"} (${Date.now() - t0}ms, exit ${code})`);
    if (stderr) console.error(`[cashflow:err] ${stderr.trim()}`);
    res.statusCode = httpStatusFor(code, json);
    res.setHeader("Content-Type", "application/json");
    res.end(JSON.stringify(json));
    return;
  }

  // POST /api/cashflow/fetch-tx
  //   Body: { tx_hash, network }
  //   Calls Goldrush via scripts/cashflow_tx_fetch.py and returns parsed transfers.
  //   Session-gated like all /api/cashflow/* — the global middleware already enforces it.
  if (req.url === "/api/cashflow/fetch-tx" && req.method === "POST") {
    const rawBody = await readBody(req);
    const { code, json, stderr } = await spawnPython(CASHFLOW_TX_FETCH_SCRIPT, rawBody);
    if (stderr) {
      // surfaced in spawnPython's own structured log when code !== 0; nothing extra here.
    }
    res.statusCode = httpStatusFor(code, json);
    res.setHeader("Content-Type", "application/json");
    res.end(JSON.stringify(json));
    return;
  }

  // POST /api/cashflow/amend
  if (req.url === "/api/cashflow/amend" && req.method === "POST") {
    const body = await readBody(req);
    const stampedBody = stampUserId(body, req.sessionUser.username);
    const t0 = Date.now();
    const { code, json, stderr } = await spawnPython(CASHFLOW_AMEND_SCRIPT, stampedBody);
    const dealRef = (json && json.rows && json.rows[0] && json.rows[0].deal_ref) || "FAIL";
    console.log(`[cashflow] amend ${dealRef} (${Date.now() - t0}ms, exit ${code})`);
    if (stderr) console.error(`[cashflow:err] ${stderr.trim()}`);
    res.statusCode = httpStatusFor(code, json);
    res.setHeader("Content-Type", "application/json");
    res.end(JSON.stringify(json));
    return;
  }

  // POST /api/cashflow/amend/batch  — bulk amend, all-or-nothing (one txn)
  if (req.url === "/api/cashflow/amend/batch" && req.method === "POST") {
    const body = await readBody(req);
    const stampedBody = stampBatchUserId(body, req.sessionUser.username);
    const t0 = Date.now();
    const { code, json, stderr } = await spawnPython(CASHFLOW_AMEND_BATCH_SCRIPT, stampedBody);
    console.log(`[cashflow] amend-batch ${(json && json.count) || 0} rows (${Date.now() - t0}ms, exit ${code})`);
    if (stderr) console.error(`[cashflow:err] ${stderr.trim()}`);
    res.statusCode = httpStatusFor(code, json);
    res.setHeader("Content-Type", "application/json");
    res.end(JSON.stringify(json));
    return;
  }

  // GET /api/cashflow/recent?limit=N
  if (req.method === "GET" && req.url.startsWith("/api/cashflow/recent")) {
    const url = new URL(req.url, "http://localhost");
    const limit = parseInt(url.searchParams.get("limit") || "20", 10);
    const stdin = JSON.stringify({ limit: Number.isNaN(limit) ? 20 : limit });
    const { code, json } = await spawnPython(CASHFLOW_RECENT_SCRIPT, stdin);
    res.statusCode = httpStatusFor(code, json);
    res.setHeader("Content-Type", "application/json");
    res.end(JSON.stringify(json));
    return;
  }

  // GET /api/cashflow/:deal_ref/history  (full SCD2 audit trail)
  // Must come BEFORE the bare :deal_ref route so the trailing /history
  // segment isn't swallowed by the [^/]+ catch-all.
  if (req.method === "GET" && /^\/api\/cashflow\/[^/]+\/history$/.test(req.url)) {
    const segments = req.url.split("/");
    const dealRef = decodeURIComponent(segments[segments.length - 2]);
    const stdin = JSON.stringify({ deal_ref: dealRef });
    const { code, json } = await spawnPython(CASHFLOW_HISTORY_SCRIPT, stdin);
    res.statusCode = httpStatusFor(code, json);
    res.setHeader("Content-Type", "application/json");
    res.end(JSON.stringify(json));
    return;
  }

  // GET /api/cashflow/:deal_ref  (must come AFTER /api/cashflow/recent so the more-specific route matches first)
  if (req.method === "GET" && /^\/api\/cashflow\/[^/]+$/.test(req.url)) {
    const dealRef = decodeURIComponent(req.url.split("/").pop());
    const stdin = JSON.stringify({ deal_ref: dealRef });
    const { code, json } = await spawnPython(CASHFLOW_GET_SCRIPT, stdin);
    res.statusCode = httpStatusFor(code, json);
    res.setHeader("Content-Type", "application/json");
    res.end(JSON.stringify(json));
    return;
  }

  // POST /api/loan/schedule-comment — upsert one (deal_ref, period_start)
  // schedule-row comment. Body: {deal_ref, period_start_date, comment, user_id}.
  // Must come BEFORE the bare /api/loan/* routes so it doesn't get matched as a deal_ref.
  if (req.url === "/api/loan/schedule-comment" && req.method === "POST") {
    const body = await readBody(req);
    const stampedBody = stampUserId(body, req.sessionUser.username);
    const t0 = Date.now();
    const { code, json, stderr } = await spawnPython(LOAN_SCHEDULE_COMMENT_UPSERT_SCRIPT, stampedBody);
    const ref = json && json.row && json.row.loan_deal_ref;
    console.log(`[loan] schedule-comment ${ref || "FAIL"} (${Date.now() - t0}ms, exit ${code})`);
    if (stderr) console.error(`[loan:err] ${stderr.trim()}`);
    res.statusCode = httpStatusFor(code, json);
    res.setHeader("Content-Type", "application/json");
    res.end(JSON.stringify(json));
    return;
  }

  // GET /api/funding/settings — Capital + ITD PnL for the Dashboard's
  // Funding & Deployment band. Absent keys fall back to defaults.
  if (req.url === "/api/funding/settings" && req.method === "GET") {
    const { code, json } = await spawnPython(FUNDING_SETTINGS_READ_SCRIPT, "{}");
    res.statusCode = httpStatusFor(code, json);
    res.setHeader("Content-Type", "application/json");
    res.end(JSON.stringify(json));
    return;
  }

  // POST /api/funding/settings — upsert one setting {key, value}. user_id is
  // stamped from the session so the frontend can't spoof who edited it.
  if (req.url === "/api/funding/settings" && req.method === "POST") {
    const body = await readBody(req);
    const stampedBody = stampUserId(body, req.sessionUser.username);
    const t0 = Date.now();
    const { code, json, stderr } = await spawnPython(FUNDING_SETTINGS_UPSERT_SCRIPT, stampedBody);
    const key = json && json.row && json.row.key;
    console.log(`[funding] settings ${key || "FAIL"} (${Date.now() - t0}ms, exit ${code})`);
    if (stderr) console.error(`[funding:err] ${stderr.trim()}`);
    res.statusCode = httpStatusFor(code, json);
    res.setHeader("Content-Type", "application/json");
    res.end(JSON.stringify(json));
    return;
  }

  // POST /api/loan/insert
  if (req.url === "/api/loan/insert" && req.method === "POST") {
    const body = await readBody(req);
    const stampedBody = stampUserId(body, req.sessionUser.username);
    const t0 = Date.now();
    const { code, json, stderr } = await spawnPython(LOAN_INSERT_SCRIPT, stampedBody);
    const dealRefs = ((json && json.rows) || []).map((r) => r.deal_ref).join(",");
    console.log(`[loan] insert ${dealRefs || "FAIL"} (${Date.now() - t0}ms, exit ${code})`);
    if (stderr) console.error(`[loan:err] ${stderr.trim()}`);
    res.statusCode = httpStatusFor(code, json);
    res.setHeader("Content-Type", "application/json");
    res.end(JSON.stringify(json));
    return;
  }

  // POST /api/loan/amend
  if (req.url === "/api/loan/amend" && req.method === "POST") {
    const body = await readBody(req);
    const stampedBody = stampUserId(body, req.sessionUser.username);
    const t0 = Date.now();
    const { code, json, stderr } = await spawnPython(LOAN_AMEND_SCRIPT, stampedBody);
    const dealRef = (json && json.rows && json.rows[0] && json.rows[0].deal_ref) || "FAIL";
    console.log(`[loan] amend ${dealRef} (${Date.now() - t0}ms, exit ${code})`);
    if (stderr) console.error(`[loan:err] ${stderr.trim()}`);
    res.statusCode = httpStatusFor(code, json);
    res.setHeader("Content-Type", "application/json");
    res.end(JSON.stringify(json));
    return;
  }

  // POST /api/loan/amend/batch  — bulk amend, all-or-nothing (one txn)
  if (req.url === "/api/loan/amend/batch" && req.method === "POST") {
    const body = await readBody(req);
    const stampedBody = stampBatchUserId(body, req.sessionUser.username);
    const t0 = Date.now();
    const { code, json, stderr } = await spawnPython(LOAN_AMEND_BATCH_SCRIPT, stampedBody);
    console.log(`[loan] amend-batch ${(json && json.count) || 0} rows (${Date.now() - t0}ms, exit ${code})`);
    if (stderr) console.error(`[loan:err] ${stderr.trim()}`);
    res.statusCode = httpStatusFor(code, json);
    res.setHeader("Content-Type", "application/json");
    res.end(JSON.stringify(json));
    return;
  }

  // GET /api/loan/recent?limit=N
  if (req.method === "GET" && req.url.startsWith("/api/loan/recent")) {
    const url = new URL(req.url, "http://localhost");
    const limit = parseInt(url.searchParams.get("limit") || "20", 10);
    const stdin = JSON.stringify({ limit: Number.isNaN(limit) ? 20 : limit });
    const { code, json } = await spawnPython(LOAN_RECENT_SCRIPT, stdin);
    res.statusCode = httpStatusFor(code, json);
    res.setHeader("Content-Type", "application/json");
    res.end(JSON.stringify(json));
    return;
  }

  // GET /api/rates/latest
  // Returns the latest available USD rates from reference_data.price_token_new,
  // walking back up to 7 days from today. Consumed by Loan Enquiry to
  // USD-value the exposure breakdown panel.
  if (req.method === "GET" && req.url.startsWith("/api/rates/latest")) {
    const { code, json } = await spawnPython(RATES_LATEST_SCRIPT, "{}");
    res.statusCode = httpStatusFor(code, json);
    res.setHeader("Content-Type", "application/json");
    res.end(JSON.stringify(json));
    return;
  }

  // GET /api/binance/vip-loan/ltv
  // Returns the current Binance VIP loan LTV (worst-case across ongoing
  // orders) for the Loan Enquiry tile. Served from a short 5s in-memory cache
  // (BINANCE_LTV_SUMMARY_TTL_MS): the tile polls every 5s, so the cache just
  // coalesces concurrent viewers into ~one Binance call per window rather than
  // adding latency. Only successful payloads are cached; errors fall through
  // so a transient Binance hiccup self-heals on the next poll.
  if (req.method === "GET" && req.url.startsWith("/api/binance/vip-loan/ltv")) {
    const now = Date.now();
    if (binanceLtvCache && now - binanceLtvCache.ts < BINANCE_LTV_SUMMARY_TTL_MS) {
      res.statusCode = 200;
      res.setHeader("Content-Type", "application/json");
      res.end(JSON.stringify(binanceLtvCache.payload));
      return;
    }
    const { code, json } = await spawnPython(BINANCE_VIP_LTV_SCRIPT, "{}");
    if (code === 0 && json && json.ok) {
      binanceLtvCache = { ts: now, payload: json };
    }
    res.statusCode = httpStatusFor(code, json);
    res.setHeader("Content-Type", "application/json");
    res.end(JSON.stringify(json));
    return;
  }

  // GET /api/binance/vip-loan/detail
  // Heavier sibling of /ltv: adds the collateral basket (per-asset qty,
  // price, haircut) plus margin-call & liquidation trigger prices. Fetched
  // polled every 5s while the user has the LTV tile expanded, so the extra
  // Binance calls (spot account + collateral/haircut tiers) run only while the
  // panel is open. Own 5s cache (BINANCE_LTV_DETAIL_TTL_MS) so concurrent
  // viewers coalesce. Passes {detail:true} to the same script.
  if (req.method === "GET" && req.url.startsWith("/api/binance/vip-loan/detail")) {
    const now = Date.now();
    if (binanceLtvDetailCache && now - binanceLtvDetailCache.ts < BINANCE_LTV_DETAIL_TTL_MS) {
      res.statusCode = 200;
      res.setHeader("Content-Type", "application/json");
      res.end(JSON.stringify(binanceLtvDetailCache.payload));
      return;
    }
    const { code, json } = await spawnPython(BINANCE_VIP_LTV_SCRIPT, JSON.stringify({ detail: true }));
    if (code === 0 && json && json.ok) {
      binanceLtvDetailCache = { ts: now, payload: json };
    }
    res.statusCode = httpStatusFor(code, json);
    res.setHeader("Content-Type", "application/json");
    res.end(JSON.stringify(json));
    return;
  }

  // GET /api/loan/export?from=&to=&portfolio=...
  // Returns all live loans (with mappings + schedule_comments) matching
  // the optional filters. Frontend builds the per-period schedule CSV
  // by calling buildLoanScheduleRows() on each loan. See loan_export.py.
  // MUST come before the /api/loan/:deal_ref catch-all so "export" isn't
  // interpreted as a deal_ref.
  if (req.method === "GET" && req.url.startsWith("/api/loan/export")) {
    const url = new URL(req.url, "http://localhost");
    const from = url.searchParams.get("from") || null;
    const to   = url.searchParams.get("to")   || null;
    const portfolioIds = url.searchParams.getAll("portfolio").filter(Boolean);
    const stdin = JSON.stringify({ from, to, portfolio_ids: portfolioIds });
    const t0 = Date.now();
    const { code, json, stderr } = await spawnPython(LOAN_EXPORT_SCRIPT, stdin);
    if (stderr) console.error(`[loan:export:err] ${stderr.trim()}`);
    const rowCount = json && json.rows ? json.rows.length : 0;
    console.log(`[loan] export ${rowCount} loans (${Date.now() - t0}ms)`);
    res.statusCode = httpStatusFor(code, json);
    res.setHeader("Content-Type", "application/json");
    res.end(JSON.stringify(json));
    return;
  }

  // GET /api/loan/:deal_ref/history  (must come BEFORE the bare :deal_ref route)
  if (req.method === "GET" && /^\/api\/loan\/[^/]+\/history$/.test(req.url)) {
    const segments = req.url.split("/");
    const dealRef = decodeURIComponent(segments[segments.length - 2]);
    const stdin = JSON.stringify({ deal_ref: dealRef });
    const { code, json } = await spawnPython(LOAN_HISTORY_SCRIPT, stdin);
    res.statusCode = httpStatusFor(code, json);
    res.setHeader("Content-Type", "application/json");
    res.end(JSON.stringify(json));
    return;
  }

  // GET /api/loan/:deal_ref  (must come AFTER /api/loan/recent so the more-specific route matches first)
  if (req.method === "GET" && /^\/api\/loan\/[^/]+$/.test(req.url)) {
    const dealRef = decodeURIComponent(req.url.split("/").pop());
    const stdin = JSON.stringify({ deal_ref: dealRef });
    const { code, json } = await spawnPython(LOAN_GET_SCRIPT, stdin);
    res.statusCode = httpStatusFor(code, json);
    res.setHeader("Content-Type", "application/json");
    res.end(JSON.stringify(json));
    return;
  }

  // POST /api/spot/insert
  if (req.url === "/api/spot/insert" && req.method === "POST") {
    const body = await readBody(req);
    const stampedBody = stampUserId(body, req.sessionUser.username);
    const t0 = Date.now();
    const { code, json, stderr } = await spawnPython(SPOT_INSERT_SCRIPT, stampedBody);
    const dealRefs = ((json && json.rows) || []).map((r) => r.deal_ref).join(",");
    console.log(`[spot] insert ${dealRefs || "FAIL"} (${Date.now() - t0}ms, exit ${code})`);
    if (stderr) console.error(`[spot:err] ${stderr.trim()}`);
    res.statusCode = httpStatusFor(code, json);
    res.setHeader("Content-Type", "application/json");
    res.end(JSON.stringify(json));
    return;
  }

  // POST /api/spot/amend
  if (req.url === "/api/spot/amend" && req.method === "POST") {
    const body = await readBody(req);
    const stampedBody = stampUserId(body, req.sessionUser.username);
    const t0 = Date.now();
    const { code, json, stderr } = await spawnPython(SPOT_AMEND_SCRIPT, stampedBody);
    const dealRef = (json && json.rows && json.rows[0] && json.rows[0].deal_ref) || "FAIL";
    console.log(`[spot] amend ${dealRef} (${Date.now() - t0}ms, exit ${code})`);
    if (stderr) console.error(`[spot:err] ${stderr.trim()}`);
    res.statusCode = httpStatusFor(code, json);
    res.setHeader("Content-Type", "application/json");
    res.end(JSON.stringify(json));
    return;
  }

  // POST /api/spot/amend/batch  — bulk amend, all-or-nothing (one txn)
  if (req.url === "/api/spot/amend/batch" && req.method === "POST") {
    const body = await readBody(req);
    const stampedBody = stampBatchUserId(body, req.sessionUser.username);
    const t0 = Date.now();
    const { code, json, stderr } = await spawnPython(SPOT_AMEND_BATCH_SCRIPT, stampedBody);
    console.log(`[spot] amend-batch ${(json && json.count) || 0} rows (${Date.now() - t0}ms, exit ${code})`);
    if (stderr) console.error(`[spot:err] ${stderr.trim()}`);
    res.statusCode = httpStatusFor(code, json);
    res.setHeader("Content-Type", "application/json");
    res.end(JSON.stringify(json));
    return;
  }

  // GET /api/spot/recent?limit=N
  if (req.method === "GET" && req.url.startsWith("/api/spot/recent")) {
    const url = new URL(req.url, "http://localhost");
    const limit = parseInt(url.searchParams.get("limit") || "20", 10);
    const stdin = JSON.stringify({ limit: Number.isNaN(limit) ? 20 : limit });
    const { code, json } = await spawnPython(SPOT_RECENT_SCRIPT, stdin);
    res.statusCode = httpStatusFor(code, json);
    res.setHeader("Content-Type", "application/json");
    res.end(JSON.stringify(json));
    return;
  }

  // GET /api/spot/:deal_ref/history  (must come BEFORE the bare :deal_ref route)
  if (req.method === "GET" && /^\/api\/spot\/[^/]+\/history$/.test(req.url)) {
    const segments = req.url.split("/");
    const dealRef = decodeURIComponent(segments[segments.length - 2]);
    const stdin = JSON.stringify({ deal_ref: dealRef });
    const { code, json } = await spawnPython(SPOT_HISTORY_SCRIPT, stdin);
    res.statusCode = httpStatusFor(code, json);
    res.setHeader("Content-Type", "application/json");
    res.end(JSON.stringify(json));
    return;
  }

  // GET /api/spot/:deal_ref  (must come AFTER /api/spot/recent so the more-specific route matches first)
  if (req.method === "GET" && /^\/api\/spot\/[^/]+$/.test(req.url)) {
    const dealRef = decodeURIComponent(req.url.split("/").pop());
    const stdin = JSON.stringify({ deal_ref: dealRef });
    const { code, json } = await spawnPython(SPOT_GET_SCRIPT, stdin);
    res.statusCode = httpStatusFor(code, json);
    res.setHeader("Content-Type", "application/json");
    res.end(JSON.stringify(json));
    return;
  }

  // GET /api/exports/blotter.csv?from=&to=&type=&portfolio=...
  // Streams a CSV download of live cashflow + spot trades in the
  // 18-column MO blotter layout. Spot trades are exploded into 2-3
  // per-asset legs; INTER PTF FUNDING counterparties are resolved to
  // portfolio names. See scripts/export_blotter.py for the contract.
  // HEAD is accepted so the UI can probe for errors before triggering
  // the actual download (so users see in-page errors, not a broken file).
  if ((req.method === "GET" || req.method === "HEAD") && req.url.startsWith("/api/exports/blotter.csv")) {
    const url = new URL(req.url, "http://localhost");
    const from = url.searchParams.get("from") || null;
    const to   = url.searchParams.get("to")   || null;
    const type = (url.searchParams.get("type") || "all").toLowerCase();
    const portfolioIds = url.searchParams.getAll("portfolio").filter(Boolean);
    const stdin = JSON.stringify({
      from, to, type,
      portfolio_ids: portfolioIds,
    });
    const t0 = Date.now();
    const { code, json, stderr } = await spawnPython(EXPORT_BLOTTER_SCRIPT, stdin);
    if (stderr) console.error(`[exports:err] ${stderr.trim()}`);
    if (code !== 0 || !json || json.ok !== true) {
      res.statusCode = httpStatusFor(code, json);
      res.setHeader("Content-Type", "application/json");
      res.end(JSON.stringify(json || { ok: false, error: "export failed" }));
      return;
    }
    const today = new Date().toISOString().slice(0, 10);
    const safeTag = (s) => String(s).replace(/[^A-Za-z0-9\-]/g, "").slice(0, 10) || "x";
    const fromTag = safeTag(from || "all");
    const toTag = safeTag(to || today);
    const filename = `blotter_${fromTag}_${toTag}.csv`;
    console.log(`[exports] blotter ${json.row_count} rows (${Date.now() - t0}ms)`);
    res.statusCode = 200;
    res.setHeader("Content-Type", "text/csv; charset=utf-8");
    res.setHeader("Content-Disposition", `attachment; filename="${filename}"`);
    // UTF-8 BOM so Excel opens the file in the correct codepage. Matches
    // the client-side downloadCsv helper convention in TradeBookingForm.jsx.
    res.end("﻿" + json.csv);
    return;
  }

  // ── Static fallback: serve React bundle from dist/ if it exists ──────
  // GET-only. Path-traversal-safe: the resolved file must be inside DIST_DIR.
  // Unknown routes (SPA navigation) get index.html — the React router takes
  // over client-side. Only runs in prod images (built by `npm run build`).
  if (req.method === "GET" && (await isDistAvailable())) {
    const pathname = (req.url || "/").split("?")[0];
    const rel = pathname === "/" ? "index.html" : pathname.replace(/^\/+/, "");
    const candidate = normalize(resolve(DIST_DIR, rel));
    const inside = candidate === DIST_DIR || candidate.startsWith(DIST_DIR + sep);
    const targetPath = inside ? candidate : DIST_INDEX;
    try {
      const data = await readFile(targetPath);
      const ext = extname(targetPath).toLowerCase();
      res.setHeader("Content-Type", MIME[ext] || "application/octet-stream");
      res.end(data);
      return;
    } catch {
      // Asset miss → SPA fallback to index.html (let React Router handle).
      try {
        const data = await readFile(DIST_INDEX);
        res.setHeader("Content-Type", MIME[".html"]);
        res.end(data);
        return;
      } catch {
        // dist/index.html went missing between the probe and now — fall through to 404.
      }
    }
  }

  res.statusCode = 404;
  res.end("Not found");
});

server.listen(PORT, () => {
  console.log(`[server] trade-booking API listening on http://localhost:${PORT}`);
  console.log(`[server]   GET  /tokens.json              — token snapshot (legacy path)`);
  console.log(`[server]   GET  /refdata/<key>.json       — counterparties / portfolios / users / tokens`);
  console.log(`[server]   GET  /api/health               — per-source last-run status`);
  console.log(`[server]   POST /api/refdata/refresh      — re-sync all refdata sources (awaits)`);
  console.log(`[server]   POST /api/refresh              — re-sync tokens only (legacy)`);
  console.log(`[server]   POST /api/cashflow/insert      — book new cashflow row(s)`);
  console.log(`[server]   POST /api/cashflow/amend       — amend an existing cashflow`);
  console.log(`[server]   GET  /api/cashflow/recent      — list N recent live rows`);
  console.log(`[server]   GET  /api/cashflow/:deal_ref   — fetch one live row`);
  console.log(`[server]   GET  /api/cashflow/:deal_ref/history — all SCD2 versions`);
  console.log(`[server]   POST /api/loan/insert          — book new loan row`);
  console.log(`[server]   POST /api/loan/amend           — amend an existing loan`);
  console.log(`[server]   GET  /api/loan/recent          — list N recent live rows`);
  console.log(`[server]   GET  /api/loan/:deal_ref       — fetch one live row`);
  console.log(`[server]   GET  /api/loan/:deal_ref/history — all SCD2 versions`);
  console.log(`[server]   POST /api/spot/insert          — book new spot row`);
  console.log(`[server]   POST /api/spot/amend           — amend an existing spot`);
  console.log(`[server]   GET  /api/spot/recent          — list N recent live rows`);
  console.log(`[server]   GET  /api/spot/:deal_ref       — fetch one live row`);
  console.log(`[server]   GET  /api/spot/:deal_ref/history — all SCD2 versions`);
  console.log(`[server]   GET  /api/exports/blotter.csv  — full blotter CSV (cashflow + spot)`);
  console.log(`[server]   GET  /api/loan/export          — all live loans + mappings for export`);
  scheduleHourlyRefdataSync();
});

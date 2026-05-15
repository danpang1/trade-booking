// Minimal API server for trade-booking. Mirrors dashboard/server.js pattern:
// startup backfill + hourly HH:15 UTC tick that re-snapshots reference tokens
// to public/tokens.json. The frontend fetches /tokens.json on mount.
//
// Run with: node server.js   (or via start.bat)

import { createServer } from "http";
import { spawn } from "child_process";
import { readFile } from "fs/promises";
import { resolve, dirname } from "path";
import { fileURLToPath } from "url";
import { platform } from "os";

const PYTHON = platform() === "win32" ? "python" : "python3";
const __dirname = dirname(fileURLToPath(import.meta.url));
const PORT = 5181;

const SNAPSHOT_SCRIPT = resolve(__dirname, "scripts", "snapshot_tokens.py");
const CASHFLOW_INSERT_SCRIPT = resolve(__dirname, "scripts", "cashflow_insert.py");
const CASHFLOW_AMEND_SCRIPT  = resolve(__dirname, "scripts", "cashflow_amend.py");
const CASHFLOW_RECENT_SCRIPT = resolve(__dirname, "scripts", "cashflow_recent.py");
const CASHFLOW_GET_SCRIPT    = resolve(__dirname, "scripts", "cashflow_get.py");
const CASHFLOW_HISTORY_SCRIPT = resolve(__dirname, "scripts", "cashflow_history.py");
const TOKENS_JSON = resolve(__dirname, "public", "tokens.json");

let snapshotRunning = false;
let lastSnapshotAt = null;
let lastSnapshotOk = null;
let lastSnapshotError = null;

function runSnapshotOnce(label) {
  if (snapshotRunning) {
    console.log(`[tokens] ${label}: skipped — prior run still in flight`);
    return;
  }
  snapshotRunning = true;
  console.log(`[tokens] ${label}: spawning snapshot_tokens.py`);
  const proc = spawn(PYTHON, [SNAPSHOT_SCRIPT], { cwd: __dirname });
  let stderr = "";
  proc.stdout.on("data", (d) => process.stdout.write(`[tokens] ${d}`));
  proc.stderr.on("data", (d) => {
    stderr += d;
    process.stderr.write(`[tokens:err] ${d}`);
  });
  proc.on("close", (code) => {
    snapshotRunning = false;
    lastSnapshotAt = new Date().toISOString();
    if (code === 0) {
      lastSnapshotOk = true;
      lastSnapshotError = null;
      console.log(`[tokens] ${label}: ok`);
    } else {
      lastSnapshotOk = false;
      lastSnapshotError = stderr.trim().split("\n").slice(-5).join(" | ");
      console.error(`[tokens] ${label}: exit ${code}: ${lastSnapshotError}`);
    }
  });
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

function scheduleHourlySnapshot() {
  runSnapshotOnce("startup-backfill");
  const firstDelay = msUntilNextHH15UTC();
  console.log(`[tokens] next tick in ${Math.round(firstDelay / 1000)}s`);
  setTimeout(() => {
    runSnapshotOnce("hourly-tick");
    setInterval(() => runSnapshotOnce("hourly-tick"), 60 * 60 * 1000);
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
  if (exitCode === 3) return 400;  // validation
  if (exitCode === 4) return 404;  // not_found (fallback if code missing)
  return 500;
}

// ── HTTP server: serves /tokens.json (for non-Vite hosts) + /api/health ──
const server = createServer(async (req, res) => {
  // CORS for the Vite dev server on a different port
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type");
  if (req.method === "OPTIONS") {
    res.statusCode = 204;
    res.end();
    return;
  }

  if (req.url === "/api/health") {
    res.setHeader("Content-Type", "application/json");
    res.end(
      JSON.stringify({
        status: "ok",
        last_snapshot_at: lastSnapshotAt,
        last_snapshot_ok: lastSnapshotOk,
        last_snapshot_error: lastSnapshotError,
        snapshot_running: snapshotRunning,
      })
    );
    return;
  }

  if (req.url === "/api/refresh" && req.method === "POST") {
    runSnapshotOnce("manual-refresh");
    res.setHeader("Content-Type", "application/json");
    res.end(JSON.stringify({ status: "scheduled" }));
    return;
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
    const t0 = Date.now();
    const { code, json, stderr } = await spawnPython(CASHFLOW_INSERT_SCRIPT, body);
    const dealRefs = (json && json.rows || []).map((r) => r.deal_ref).join(",");
    console.log(`[cashflow] insert ${dealRefs || "FAIL"} (${Date.now() - t0}ms, exit ${code})`);
    if (stderr) console.error(`[cashflow:err] ${stderr.trim()}`);
    res.statusCode = httpStatusFor(code, json);
    res.setHeader("Content-Type", "application/json");
    res.end(JSON.stringify(json));
    return;
  }

  // POST /api/cashflow/amend
  if (req.url === "/api/cashflow/amend" && req.method === "POST") {
    const body = await readBody(req);
    const t0 = Date.now();
    const { code, json, stderr } = await spawnPython(CASHFLOW_AMEND_SCRIPT, body);
    const dealRef = (json && json.rows && json.rows[0] && json.rows[0].deal_ref) || "FAIL";
    console.log(`[cashflow] amend ${dealRef} (${Date.now() - t0}ms, exit ${code})`);
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

  res.statusCode = 404;
  res.end("Not found");
});

server.listen(PORT, () => {
  console.log(`[server] trade-booking API listening on http://localhost:${PORT}`);
  console.log(`[server]   GET  /tokens.json    — serve current snapshot`);
  console.log(`[server]   GET  /api/health     — last-run status`);
  console.log(`[server]   POST /api/refresh    — force a re-snapshot`);
  console.log(`[server]   POST /api/cashflow/insert    — book new cashflow row(s)`);
  console.log(`[server]   POST /api/cashflow/amend     — amend an existing cashflow`);
  console.log(`[server]   GET  /api/cashflow/recent    — list N recent live rows`);
  console.log(`[server]   GET  /api/cashflow/:deal_ref — fetch one live row`);
  console.log(`[server]   GET  /api/cashflow/:deal_ref/history — all SCD2 versions`);
  scheduleHourlySnapshot();
});

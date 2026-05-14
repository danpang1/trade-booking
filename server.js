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

// ── HTTP server: serves /tokens.json (for non-Vite hosts) + /api/health ──
const server = createServer(async (req, res) => {
  // CORS for the Vite dev server on a different port
  res.setHeader("Access-Control-Allow-Origin", "*");

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

  res.statusCode = 404;
  res.end("Not found");
});

server.listen(PORT, () => {
  console.log(`[server] trade-booking API listening on http://localhost:${PORT}`);
  console.log(`[server]   GET  /tokens.json    — serve current snapshot`);
  console.log(`[server]   GET  /api/health     — last-run status`);
  console.log(`[server]   POST /api/refresh    — force a re-snapshot`);
  scheduleHourlySnapshot();
});
